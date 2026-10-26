"""Loads trained model artifacts once per process and provides safe fallbacks.

If an artifact is missing (fresh environment, CI) the platform still works:
classification falls back to a transparent logistic heuristic, anomaly
detection to EARS C2 and forecasting to the persistence model.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from sentinel_ml.forecasting import SeasonalNaiveForecaster
from sentinel_ml.registry import load_model

log = logging.getLogger(__name__)

# Coefficients of the fallback heuristic (log-ratio features -> logit).
_HEURISTIC = {
    "cases_ratio_7_28": 1.6, "ed_ratio_7_28": 1.3, "wastewater_ratio_7_28": 1.0,
    "otc_ratio_7_28": 0.6, "neighbor_ratio_7_28": 0.8, "admissions_ratio_7_28": 0.6,
}
_HEURISTIC_BIAS = -2.4


@dataclass
class ModelRuntime:
    classifier: object | None = None
    anomaly: object | None = None
    forecaster: object | None = None
    naive: object | None = None
    versions: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, directory: Path) -> ModelRuntime:
        rt = cls()
        for attr, name in [("classifier", "outbreak_classifier"), ("anomaly", "anomaly_ensemble"),
                           ("forecaster", "forecaster_xgboost"), ("naive", "forecaster_naive")]:
            try:
                obj = load_model(name, directory)
            except Exception:  # corrupted or incompatible artifact must not take the API down
                log.exception("failed to load model %s", name)
                obj = None
            setattr(rt, attr, obj)
            manifest = directory / f"{name}.json"
            if obj is not None and manifest.exists():
                rt.versions[name] = json.loads(manifest.read_text())["sha256"][:12]
        log.info("model runtime loaded: %s", {k: v for k, v in rt.versions.items()} or "fallbacks only")
        return rt

    # ---- classification -------------------------------------------------------
    def outbreak_probability(self, feats: pd.DataFrame) -> tuple[np.ndarray, list[list[tuple[str, float]]], str]:
        if self.classifier is not None:
            return self.classifier.predict_proba(feats), self.classifier.explain(feats), "lightgbm"
        logits = np.full(len(feats), _HEURISTIC_BIAS)
        contribs = []
        for col, w in _HEURISTIC.items():
            vals = np.log(np.clip(feats[col].fillna(1.0).to_numpy(dtype=float), 1e-3, None)) * w
            logits = logits + vals
            contribs.append((col, vals))
        drivers = [
            sorted(((c, round(float(v[i]), 4)) for c, v in contribs), key=lambda t: -abs(t[1]))[:4]
            for i in range(len(feats))
        ]
        return 1 / (1 + np.exp(-logits)), drivers, "heuristic"

    # ---- anomaly ---------------------------------------------------------------
    def anomaly_scores(self, feats: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, str]:
        if self.anomaly is not None:
            scores = self.anomaly.score(feats)
            return scores, scores >= self.anomaly.threshold_, "ensemble(iforest+ocsvm+autoencoder)"
        z = feats["cases_zscore"].fillna(0.0).to_numpy(dtype=float)
        scores = 1 / (1 + np.exp(-(z - 3.0)))
        return scores, z >= 3.0, "ears_c2"

    # ---- forecasting -----------------------------------------------------------
    def forecast_model(self, history: pd.DataFrame):
        if self.forecaster is not None and len(history) >= 35:
            return self.forecaster
        if self.naive is not None:
            return self.naive
        return SeasonalNaiveForecaster().fit(history.assign(disease="x", region_id="x"))


@lru_cache
def get_runtime() -> ModelRuntime:
    return ModelRuntime.load(get_settings().model_dir)


