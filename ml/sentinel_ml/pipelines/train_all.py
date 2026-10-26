"""End-to-end training + evaluation pipeline.

    python -m sentinel_ml.pipelines.train_all --out ml/artifacts --report docs/model-evaluation-report.md

Steps: generate (or load) surveillance data -> engineer features -> temporal
train/test split -> train classifier, anomaly ensemble and forecasters ->
evaluate (day-level metrics, event-level early detection, forecast backtest,
spatial hotspots) -> write artifacts, metrics JSON and a Markdown report.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score

from sentinel_ml.anomaly import EnsembleAnomalyDetector
from sentinel_ml.anomaly.detectors import ears_c2
from sentinel_ml.classification import OutbreakClassifier, classification_metrics
from sentinel_ml.data import SyntheticConfig, generate_surveillance
from sentinel_ml.data.synthetic import generate_case_line_list
from sentinel_ml.evaluation import early_detection_metrics
from sentinel_ml.evaluation.report import write_report
from sentinel_ml.features import SIGNAL_FEATURES, add_outbreak_target, build_features
from sentinel_ml.forecasting import (
    LSTMForecaster,
    SeasonalNaiveForecaster,
    XGBoostForecaster,
    backtest,
    summarize_backtest,
)
from sentinel_ml.registry import save_model
from sentinel_ml.spatial import detect_hotspots

log = logging.getLogger("sentinel_ml.train")

REPORT_LAG_DAYS = 7  # confirmed-case reporting delay (onset -> health department)
FEED_LAG_DAYS = 1  # syndromic / wastewater / pharmacy feeds


def run(out_dir: Path, report_path: Path | None, test_start: str, data_path: Path | None,
        quick: bool = False, seed: int = 42) -> dict:
    t0 = time.time()
    if data_path:
        panel = pd.read_parquet(data_path) if data_path.suffix == ".parquet" else pd.read_csv(data_path)
        panel["date"] = pd.to_datetime(panel["date"])
    else:
        cfg = SyntheticConfig(seed=seed)
        if quick:
            cfg.regions = cfg.regions[:10]
            cfg.diseases = ["INFLUENZA", "CLI", "MEASLES"]
        panel = generate_surveillance(cfg)
    log.info("panel: %d rows, %d series", len(panel), panel.groupby(["disease", "region_id"]).ngroups)

    df = add_outbreak_target(build_features(panel))
    df = df[df["date"] >= df["date"].min() + pd.Timedelta(days=42)]  # feature warm-up
    split = pd.Timestamp(test_start)
    train, test = df[df["date"] < split].copy(), df[df["date"] >= split].copy()
    log.info("train %d rows / test %d rows (split %s)", len(train), len(test), split.date())

    metrics: dict = {"data": {
        "rows": int(len(panel)), "series": int(panel.groupby(["disease", "region_id"]).ngroups),
        "train_rows": int(len(train)), "test_rows": int(len(test)), "test_start": str(split.date()),
        "outbreak_prevalence_test": float(test["outbreak"].mean()),
        "source": str(data_path) if data_path else "synthetic",
    }}

    # 1. Outbreak classifier --------------------------------------------------
    clf = OutbreakClassifier(backend="lightgbm").fit(train)
    proba = clf.predict_proba(test)
    metrics["classifier"] = classification_metrics(test["target_outbreak"], proba, clf.decision_threshold)
    metrics["classifier"]["feature_importance"] = clf.feature_importance()[:10]
    test["p_outbreak"] = proba
    if not quick:
        alt = OutbreakClassifier(backend="xgboost").fit(train)
        p_alt = alt.predict_proba(test)
        metrics["classifier_xgboost"] = {
            k: v for k, v in classification_metrics(test["target_outbreak"], p_alt, alt.decision_threshold).items()
            if k in ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc")
        }
    by_disease = {}
    for disease, g in test.groupby("disease"):
        y = g["target_outbreak"]
        if y.nunique() > 1:
            by_disease[disease] = {
                "roc_auc": float(roc_auc_score(y, g["p_outbreak"])),
                "f1": float(f1_score(y, g["p_outbreak"] >= clf.decision_threshold)),
            }
    metrics["classifier_by_disease"] = by_disease
    log.info("classifier AUC=%.3f F1=%.3f", metrics["classifier"]["roc_auc"], metrics["classifier"]["f1"])

    # 2. Anomaly ensemble -----------------------------------------------------
    ens = EnsembleAnomalyDetector(contamination=0.03).fit(train)
    test["anomaly_score"] = ens.score(test)
    test["flag_ensemble"] = test["anomaly_score"] >= ens.threshold_
    comps = ens.component_scores(test)
    anomaly = {}
    y = test["outbreak"].to_numpy()
    for name in comps.columns:
        flags = comps[name].to_numpy() >= 1 - ens.contamination
        anomaly[name] = {
            "roc_auc": float(roc_auc_score(y, comps[name])),
            "precision": float(precision_score(y, flags, zero_division=0)),
            "recall": float(recall_score(y, flags, zero_division=0)),
        }
    anomaly["ensemble"] = {
        "roc_auc": float(roc_auc_score(y, test["anomaly_score"])),
        "precision": float(precision_score(y, test["flag_ensemble"], zero_division=0)),
        "recall": float(recall_score(y, test["flag_ensemble"], zero_division=0)),
        "autoencoder_backend": ens.detectors["autoencoder"].backend_,
    }
    metrics["anomaly"] = anomaly

    # 3. Early detection vs traditional reporting ----------------------------
    test = test.sort_values(["disease", "region_id", "date"])
    test["c2_cases"] = test.groupby(["disease", "region_id"])["cases"].transform(ears_c2)
    test["flag_traditional_ears"] = test["c2_cases"] >= 3.0
    test["flag_classifier"] = test["p_outbreak"] >= 0.6
    test["flag_sentinel"] = test["flag_classifier"] | (test["flag_ensemble"] & (test["p_outbreak"] >= 0.3))
    metrics["early_detection"] = early_detection_metrics(
        test,
        {"flag_traditional_ears": REPORT_LAG_DAYS, "flag_ensemble": FEED_LAG_DAYS,
         "flag_classifier": FEED_LAG_DAYS, "flag_sentinel": FEED_LAG_DAYS},
        reference="flag_traditional_ears",
    )

    # 4. Forecasting backtest -------------------------------------------------
    train_panel = df[df["date"] < split]
    naive = SeasonalNaiveForecaster().fit(train_panel)
    xgbf = XGBoostForecaster(stride=7 if quick else 5).fit(train_panel)
    models = [naive, xgbf]
    if LSTMForecaster.available():
        models.append(LSTMForecaster().fit(train_panel))
    bt = backtest(df, models, start=split, step_days=21 if quick else 14)
    summary = summarize_backtest(bt)
    metrics["forecast"] = summary.round(4).to_dict(orient="records")
    metrics["forecast_feature_importance"] = xgbf.feature_importance(10)

    # 5. Spatial hotspots (demonstration on the last 21 days of the test set) --
    line = generate_case_line_list(panel[panel["date"] >= panel["date"].max() - pd.Timedelta(days=104)], seed=seed)
    cutoff = line["date"].max() - pd.Timedelta(days=21)
    hot = []
    for _, g in line.groupby("disease"):
        frac = min(1.0, 600 / max((g["date"] > cutoff).sum(), 1))  # same sampling rate in both windows
        g = g.sample(frac=frac, random_state=seed)
        cur, base = g[g["date"] > cutoff], g[g["date"] <= cutoff]
        hot += [h.as_dict() for h in detect_hotspots(cur, base, method="hdbscan", min_samples=15,
                                                      window_ratio=83 / 21)]
    metrics["hotspots_demo"] = hot[:10]

    # 6. Persist ---------------------------------------------------------------
    meta = {"test_start": str(split.date()), "features": SIGNAL_FEATURES}
    save_model(clf, "outbreak_classifier", out_dir, {**meta, "roc_auc": metrics["classifier"]["roc_auc"]})
    save_model(ens, "anomaly_ensemble", out_dir, meta)
    save_model(xgbf, "forecaster_xgboost", out_dir, meta)
    save_model(naive, "forecaster_naive", out_dir, meta)
    metrics["runtime_seconds"] = round(time.time() - t0, 1)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=_json_default))
    if report_path:
        write_report(metrics, report_path, image_dir=report_path.parent / "images")
    log.info("done in %.1fs", metrics["runtime_seconds"])
    return metrics


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=Path("ml/artifacts"))
    p.add_argument("--report", type=Path, default=None)
    p.add_argument("--data", type=Path, default=None, help="CSV/Parquet panel; synthetic data if omitted")
    p.add_argument("--test-start", default="2025-01-01")
    p.add_argument("--quick", action="store_true", help="small run for CI")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args.out.mkdir(parents=True, exist_ok=True)
    run(args.out, args.report, args.test_start, args.data, quick=args.quick, seed=args.seed)


if __name__ == "__main__":
    main()
