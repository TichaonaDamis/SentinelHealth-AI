from datetime import date

import numpy as np
import pandas as pd
import pytest

from sentinel_ml.anomaly import EnsembleAnomalyDetector, IsolationForestDetector
from sentinel_ml.anomaly.detectors import ears_c2
from sentinel_ml.classification import OutbreakClassifier, classification_metrics, risk_tier
from sentinel_ml.data import REGIONS, SyntheticConfig, generate_surveillance
from sentinel_ml.evaluation import early_detection_metrics, outbreak_episodes
from sentinel_ml.features import SIGNAL_FEATURES, add_outbreak_target, build_features
from sentinel_ml.forecasting import SeasonalNaiveForecaster, XGBoostForecaster, derive_risk
from sentinel_ml.registry import load_model, save_model
from sentinel_ml.spatial import detect_hotspots


@pytest.fixture(scope="module")
def panel():
    cfg = SyntheticConfig(start=date(2023, 1, 1), days=500, seed=3, regions=REGIONS[:8],
                          diseases=["INFLUENZA", "MEASLES"])
    return generate_surveillance(cfg)


@pytest.fixture(scope="module")
def feats(panel):
    df = add_outbreak_target(build_features(panel))
    return df[df["date"] >= df["date"].min() + pd.Timedelta(days=42)].reset_index(drop=True)


def test_synthetic_panel_shape_and_labels(panel):
    assert len(panel) == 8 * 2 * 500
    assert panel["cases"].min() >= 0
    assert 0 < panel["outbreak"].mean() < 0.3
    # Outbreak days have markedly higher activity than non-outbreak days in the same series.
    flu = panel[panel["disease"] == "INFLUENZA"]
    ratio = flu[flu.outbreak == 1]["cases"].mean() / flu[flu.outbreak == 0]["cases"].mean()
    assert ratio > 1.5


def test_features_have_no_lookahead(panel):
    """Changing future values must not change features at an earlier date."""
    cut = panel["date"].min() + pd.Timedelta(days=200)
    f1 = build_features(panel)
    p2 = panel.copy()
    p2.loc[p2["date"] > cut, ["cases", "ed_visits", "wastewater"]] *= 10
    f2 = build_features(p2)
    m = f1["date"] <= cut
    cols = [c for c in SIGNAL_FEATURES]
    pd.testing.assert_frame_equal(f1.loc[m, cols].reset_index(drop=True), f2.loc[m, cols].reset_index(drop=True))


def test_ears_c2_flags_spike():
    s = pd.Series([10, 11, 9, 10, 12, 10, 11, 9, 10, 10, 11, 40], dtype=float)
    z = ears_c2(s)
    assert z.iloc[-1] > 3
    assert z.iloc[:-1].max() < 3


def test_isolation_forest_scores_outbreaks_higher(feats):
    det = IsolationForestDetector().fit(feats)
    s = det.score(feats)
    assert s[feats["outbreak"] == 1].mean() > s[feats["outbreak"] == 0].mean()
    assert len(det.explain(feats.head(2))[0]) == 3


def test_ensemble_anomaly(feats):
    ens = EnsembleAnomalyDetector(contamination=0.05).fit(feats)
    flags = ens.predict(feats)
    assert 0 < flags.mean() < 0.2
    assert set(ens.component_scores(feats.head(5)).columns) == {"isolation_forest", "one_class_svm", "autoencoder"}


def test_classifier_and_metrics(feats):
    train = feats[feats["date"] < "2024-01-01"]
    test = feats[feats["date"] >= "2024-01-01"]
    clf = OutbreakClassifier().fit(train)
    p = clf.predict_proba(test)
    m = classification_metrics(test["target_outbreak"], p, clf.decision_threshold)
    assert m["roc_auc"] > 0.8
    assert np.array(m["confusion_matrix"]).sum() == len(test)
    assert len(clf.explain(test.head(3))) == 3
    assert risk_tier(0.7) == "High" and risk_tier(0.4) == "Medium" and risk_tier(0.1) == "Low"


def test_forecasters(feats):
    hist = feats[(feats.disease == "INFLUENZA") & (feats.region_id == REGIONS[0].region_id)]
    naive = SeasonalNaiveForecaster().fit(feats)
    xgbf = XGBoostForecaster(stride=14, params={"n_estimators": 50, "max_depth": 4, "tree_method": "hist"}).fit(feats)
    for model in (naive, xgbf):
        fc = model.predict(hist, 30)
        assert len(fc.mean) == 30
        assert (fc.lower <= fc.mean + 1e-9).all() and (fc.mean <= fc.upper + 1e-9).all()
    risk = derive_risk(fc, hist, "INFLUENZA", REGIONS[0].population, horizon=14)
    assert risk.hospitalization_risk in {"low", "moderate", "high", "very_high"}
    assert risk.forecast_cases_lower <= risk.forecast_cases <= risk.forecast_cases_upper


def test_hotspot_detection_finds_injected_cluster():
    rng = np.random.default_rng(0)
    background = pd.DataFrame({"lat": rng.uniform(30, 40, 300), "lon": rng.uniform(-100, -90, 300)})
    cluster = pd.DataFrame({"lat": rng.normal(35, 0.03, 80), "lon": rng.normal(-95, 0.03, 80)})
    pts = pd.concat([background, cluster]).assign(disease="FOODBORNE")
    base = pd.DataFrame({"lat": rng.uniform(30, 40, 1200), "lon": rng.uniform(-100, -90, 1200)})
    for method in ("dbscan", "hdbscan"):
        hs = detect_hotspots(pts, base, method=method, eps_km=10, min_samples=20, window_ratio=4)
        assert hs, method
        top = hs[0]
        assert abs(top.centroid_lat - 35) < 0.2 and abs(top.centroid_lon + 95) < 0.2
        assert top.relative_risk > 3


def test_early_detection_metrics():
    dates = pd.date_range("2024-01-01", periods=60)
    label = np.zeros(60, dtype=int)
    label[20:35] = 1
    df = pd.DataFrame({"date": dates, "disease": "X", "region_id": "R", "outbreak": label})
    df["early"] = False
    df.loc[18, "early"] = True
    df["late"] = False
    df.loc[30, "late"] = True
    assert len(outbreak_episodes(df)) == 1
    m = early_detection_metrics(df, {"late": 7, "early": 1}, reference="late")
    assert m["early"]["detected"] == 1
    assert m["early"]["median_lead_days_vs_late"] == (30 + 7) - (18 + 1)


def test_registry_roundtrip(tmp_path):
    save_model({"a": 1}, "thing", tmp_path)
    assert load_model("thing", tmp_path) == {"a": 1}
    (tmp_path / "thing.joblib").write_bytes(b"tampered")
    with pytest.raises(ValueError):
        load_model("thing", tmp_path)
