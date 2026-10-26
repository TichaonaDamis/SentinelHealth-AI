"""Render the model evaluation report (Markdown + optional PNG figures)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def _plots(metrics: dict, image_dir: Path) -> dict[str, str]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {}
    image_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    c = metrics["classifier"]

    fig, ax = plt.subplots(figsize=(4.2, 4))
    ax.plot(c["roc_curve"]["fpr"], c["roc_curve"]["tpr"], color="#2563eb", lw=2, label=f"LightGBM (AUC {c['roc_auc']:.3f})")
    ax.plot([0, 1], [0, 1], color="#9ca3af", ls="--", lw=1)
    ax.set(xlabel="False positive rate", ylabel="True positive rate", title="Outbreak classifier ROC")
    ax.legend(loc="lower right", frameon=False)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(image_dir / "roc_curve.png", dpi=140)
    paths["roc"] = "images/roc_curve.png"
    plt.close(fig)

    cm = c["confusion_matrix"]
    fig, ax = plt.subplots(figsize=(3.8, 3.4))
    ax.imshow(cm, cmap="Blues")
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{cm[i][j]:,}", ha="center", va="center",
                    color="white" if cm[i][j] > max(map(max, cm)) / 2 else "#111827")
    ax.set_xticks([0, 1], ["No outbreak", "Outbreak"])
    ax.set_yticks([0, 1], ["No outbreak", "Outbreak"])
    ax.set(xlabel="Predicted", ylabel="Actual", title="Confusion matrix")
    fig.tight_layout()
    fig.savefig(image_dir / "confusion_matrix.png", dpi=140)
    paths["cm"] = "images/confusion_matrix.png"
    plt.close(fig)

    fc = metrics.get("forecast", [])
    if fc:
        fig, ax = plt.subplots(figsize=(5, 3.4))
        models = sorted({r["model"] for r in fc})
        colors = {"seasonal_naive": "#9ca3af", "xgboost": "#2563eb", "lstm": "#d97706", "prophet": "#059669"}
        for m in models:
            rows = sorted((r for r in fc if r["model"] == m), key=lambda r: r["horizon"])
            ax.plot([r["horizon"] for r in rows], [r["smape"] for r in rows], marker="o", label=m,
                    color=colors.get(m, "#6b7280"), lw=2)
        ax.set(xlabel="Horizon (days)", ylabel="sMAPE (lower is better)", title="Forecast error by horizon")
        ax.legend(frameon=False)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        fig.tight_layout()
        fig.savefig(image_dir / "forecast_error.png", dpi=140)
        paths["fc"] = "images/forecast_error.png"
        plt.close(fig)
    return paths


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _num(x, nd=3) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def write_report(metrics: dict, path: Path, image_dir: Path) -> None:
    imgs = _plots(metrics, image_dir)
    c, d = metrics["classifier"], metrics["data"]
    cm = c["confusion_matrix"]
    L = []
    w = L.append
    w("# SentinelHealth AI — Model Evaluation Report\n")
    w(f"_Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `sentinel_ml.pipelines.train_all` "
      f"(runtime {metrics.get('runtime_seconds', 'n/a')} s). Re-run with `make train` to reproduce._\n")
    w("> **Data provenance.** Unless stated otherwise these results come from the built-in synthetic surveillance "
      "generator (`sentinel_ml.data.synthetic`), which injects labelled outbreaks into seasonal baselines across "
      "multiple feeds. Synthetic results validate the pipeline and relative model behaviour; they are **not** "
      "evidence of real-world performance. Before operational use, models must be re-validated on jurisdictional "
      "data with retrospective outbreak line lists (see `docs/ml-pipeline.md` §Validation).\n")
    w("## 1. Dataset\n")
    w("| Item | Value |\n|---|---|")
    w(f"| Source | {d['source']} |")
    w(f"| Rows (region × disease × day) | {d['rows']:,} |")
    w(f"| Series | {d['series']} |")
    w(f"| Train rows / Test rows | {d['train_rows']:,} / {d['test_rows']:,} |")
    w(f"| Temporal split | train < {d['test_start']} ≤ test |")
    w(f"| Outbreak-day prevalence (test) | {_pct(d['outbreak_prevalence_test'])} |\n")

    w("## 2. Outbreak likelihood classifier (LightGBM, isotonic-calibrated)\n")
    w("Target: outbreak active now or starting within 7 days. Operating threshold chosen to maximise F1 on a "
      "time-ordered calibration window (no test leakage).\n")
    w("| Metric | Value |\n|---|---|")
    for k, label in [("accuracy", "Accuracy"), ("precision", "Precision"), ("recall", "Recall"), ("f1", "F1 score"),
                     ("roc_auc", "ROC AUC"), ("pr_auc", "PR AUC (average precision)")]:
        w(f"| {label} | {_num(c[k])} |")
    w(f"| Decision threshold | {_num(c['threshold'], 2)} |\n")
    w("**Confusion matrix (test set)**\n")
    w("| | Predicted: no outbreak | Predicted: outbreak |\n|---|---|---|")
    w(f"| **Actual: no outbreak** | {cm[0][0]:,} (TN) | {cm[0][1]:,} (FP) |")
    w(f"| **Actual: outbreak** | {cm[1][0]:,} (FN) | {cm[1][1]:,} (TP) |\n")
    if imgs:
        w(f"![ROC curve]({imgs['roc']}) ![Confusion matrix]({imgs['cm']})\n")
    w("**Risk tier calibration** — share of days in each tier that were truly outbreak days:\n")
    w("| Tier | Probability | Days | Observed outbreak rate |\n|---|---|---|---|")
    bounds = {"High": "≥ 0.60", "Medium": "0.30 – 0.60", "Low": "< 0.30"}
    for tier, v in c["risk_tiers"].items():
        w(f"| {tier} | {bounds[tier]} | {v['n']:,} | {_pct(v['outbreak_rate'])} |")
    w("")
    if "classifier_xgboost" in metrics:
        x = metrics["classifier_xgboost"]
        w(f"Challenger XGBoost classifier: AUC {_num(x['roc_auc'])}, F1 {_num(x['f1'])}, "
          f"precision {_num(x['precision'])}, recall {_num(x['recall'])}.\n")
    w("**Per-disease performance**\n")
    w("| Disease | ROC AUC | F1 |\n|---|---|---|")
    for dis, v in metrics.get("classifier_by_disease", {}).items():
        w(f"| {dis} | {_num(v['roc_auc'])} | {_num(v['f1'])} |")
    w("\n**Top features (gain share)**: " + ", ".join(f"`{f}` ({v:.2f})" for f, v in c["feature_importance"]) + "\n")

    w("## 3. Anomaly detection (unsupervised)\n")
    w("Day-level scores vs. outbreak labels. Detectors are trained without labels; the ensemble rank-averages "
      "components and only flags *increases* in activity.\n")
    w("| Detector | ROC AUC | Precision @ 97th pct | Recall @ 97th pct |\n|---|---|---|---|")
    for name, v in metrics["anomaly"].items():
        w(f"| {name} | {_num(v['roc_auc'])} | {_num(v['precision'])} | {_num(v['recall'])} |")
    w(f"\nAutoencoder backend: `{metrics['anomaly']['ensemble'].get('autoencoder_backend')}` "
      "(PyTorch when installed, scikit-learn MLP otherwise).\n")

    w("## 4. Early detection vs. traditional reporting\n")
    w("Event-level evaluation over outbreak episodes in the test period. *Traditional* = EARS C2 (CDC) on "
      "confirmed cases with a 7-day reporting lag. SentinelHealth detectors use syndromic, wastewater, pharmacy and "
      "lab feeds with a 1-day lag. Lead time = days earlier than the traditional signal (episodes the traditional "
      "method missed are credited at outbreak end).\n")
    w("| Detector | Episodes detected | Median delay from onset (days) | Median lead vs traditional (days) | "
      "Detected earlier | False alerts / series-year |\n|---|---|---|---|---|---|")
    for name, v in metrics["early_detection"].items():
        lead = v.get("median_lead_days_vs_flag_traditional_ears")
        w(f"| {name.replace('flag_', '')} | {v['detected']}/{v['episodes']} ({_pct(v['detection_rate'])}) | "
          f"{_num(v['median_delay_days'], 1)} | {_num(lead, 1) if lead is not None else '—'} | "
          f"{_pct(v.get('share_detected_earlier')) if 'share_detected_earlier' in v else '—'} | "
          f"{_num(v['false_alerts_per_series_year'], 2)} |")
    w("")

    w("## 5. Forecasting (rolling-origin backtest)\n")
    w("Error on total cases over the horizon; intervals are 80% split-conformal. Skill = 1 − MAE/MAE(naive).\n")
    w("| Model | Horizon | MAE | sMAPE | 80% interval coverage | Skill vs naive | Forecasts |\n|---|---|---|---|---|---|---|")
    for r in sorted(metrics["forecast"], key=lambda r: (r["horizon"], r["model"])):
        w(f"| {r['model']} | {r['horizon']}d | {r['mae']:.1f} | {r['smape']:.3f} | {_pct(r['coverage_80'])} | "
          f"{r['skill_vs_naive']:+.3f} | {r['n']:,} |")
    if imgs.get("fc"):
        w(f"\n![Forecast error]({imgs['fc']})")
    w("\nTop forecaster features: " + ", ".join(f"`{f}`" for f, _ in metrics.get("forecast_feature_importance", [])) + "\n")
    if not any(r["model"] == "lstm" for r in metrics["forecast"]):
        w("_LSTM and Prophet are implemented (`sentinel_ml.forecasting`) and run automatically when `torch` / "
          "`prophet` are installed (`pip install -e 'ml[all]'`); they were not installed for this run._\n")

    w("## 6. Spatial hotspots (HDBSCAN, haversine)\n")
    hs = metrics.get("hotspots_demo", [])
    if hs:
        w("| Disease | Cases | Centroid | Radius (km) | Relative risk |\n|---|---|---|---|---|")
        for h in hs:
            w(f"| {h['disease']} | {h['case_count']} | {h['centroid_lat']}, {h['centroid_lon']} | {h['radius_km']} | "
              f"{h['relative_risk']} |")
    else:
        w("No clusters exceeded the relative-risk threshold in the final 21-day window.")
    w("\n## 7. Limitations and governance\n")
    w("- Synthetic labels are cleaner than real outbreak determinations; expect lower real-world precision.\n"
      "- Thresholds trade sensitivity for alert fatigue; each jurisdiction should tune them (Admin → Alert policy).\n"
      "- Models are monitored for drift (PSI on inputs, rolling AUC on adjudicated alerts) and retrained weekly by "
      "the `model_retraining` Airflow DAG; promotion requires beating the champion on the backtest.\n"
      "- All predictions ship with feature attributions (TreeSHAP / detector deviations) to support explainability.\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L))
