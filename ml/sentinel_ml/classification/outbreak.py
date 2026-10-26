"""Outbreak-likelihood classifier (High / Medium / Low).

A LightGBM gradient-boosted classifier predicts the probability that an outbreak
is active or will begin within 7 days for a region/disease/day. Probabilities
are isotonic-calibrated on a time-ordered hold-out so the tiers mean what they
say ("High" ~= at least 60% of such days are truly outbreak days).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
)

from sentinel_ml.features import MODEL_FEATURES, feature_matrix

RISK_TIERS = {"High": 0.6, "Medium": 0.3, "Low": 0.0}


def risk_tier(probability: float) -> str:
    for tier, threshold in RISK_TIERS.items():
        if probability >= threshold:
            return tier
    return "Low"


def _make_model(backend: str, random_state: int):
    if backend == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=500, learning_rate=0.03, num_leaves=31, min_child_samples=40, subsample=0.8,
            subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=random_state, verbose=-1,
        )
    if backend == "xgboost":
        import xgboost as xgb

        return xgb.XGBClassifier(
            n_estimators=500, learning_rate=0.03, max_depth=6, subsample=0.8, colsample_bytree=0.8,
            eval_metric="logloss", tree_method="hist", random_state=random_state,
        )
    raise ValueError(f"unknown backend {backend!r}")


@dataclass
class OutbreakClassifier:
    backend: str = "lightgbm"
    features: list[str] = field(default_factory=lambda: list(MODEL_FEATURES))
    calibration_fraction: float = 0.2
    random_state: int = 42
    decision_threshold: float = 0.5
    model_: object | None = None
    calibrator_: IsotonicRegression | None = None

    def fit(self, df: pd.DataFrame, target: str = "target_outbreak"):
        df = df.sort_values("date")
        cutoff = df["date"].quantile(1 - self.calibration_fraction)
        tr, cal = df[df["date"] < cutoff], df[df["date"] >= cutoff]
        model = _make_model(self.backend, self.random_state).fit(feature_matrix(tr, self.features), tr[target])
        raw = model.predict_proba(feature_matrix(cal, self.features))[:, 1]
        self.calibrator_ = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(raw, cal[target])
        # Choose the operating point that maximises F1 on the calibration window.
        cal_p = self.calibrator_.predict(raw)
        grid = np.linspace(0.1, 0.9, 81)
        f1s = [f1_score(cal[target], cal_p >= t, zero_division=0) for t in grid]
        self.decision_threshold = float(grid[int(np.argmax(f1s))])
        self.model_ = _make_model(self.backend, self.random_state).fit(feature_matrix(df, self.features), df[target])
        return self

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        raw = self.model_.predict_proba(feature_matrix(df, self.features))[:, 1]
        return self.calibrator_.predict(raw)

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(df) >= self.decision_threshold).astype(int)

    def predict_tier(self, df: pd.DataFrame) -> list[str]:
        return [risk_tier(p) for p in self.predict_proba(df)]

    def feature_importance(self) -> list[tuple[str, float]]:
        imp = np.asarray(self.model_.feature_importances_, dtype=float)
        imp = imp / imp.sum() if imp.sum() else imp
        order = np.argsort(-imp)
        return [(self.features[i], round(float(imp[i]), 4)) for i in order]

    def explain(self, df: pd.DataFrame, top_k: int = 4) -> list[list[tuple[str, float]]]:
        """Per-prediction SHAP-style contributions using the booster's native TreeSHAP."""
        X = feature_matrix(df, self.features)
        if self.backend == "lightgbm":
            contrib = self.model_.predict_proba(X, pred_contrib=True)[:, :-1]
        else:
            import xgboost as xgb

            contrib = self.model_.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)[:, :-1]
        out = []
        for row in contrib:
            idx = np.argsort(-np.abs(row))[:top_k]
            out.append([(self.features[i], round(float(row[i]), 4)) for i in idx])
        return out


def classification_metrics(y_true, proba, threshold: float) -> dict:
    y_true = np.asarray(y_true).astype(int)
    pred = (np.asarray(proba) >= threshold).astype(int)
    fpr, tpr, thr = roc_curve(y_true, proba)
    # Down-sample ROC points for compact storage / plotting.
    keep = np.unique(np.linspace(0, len(fpr) - 1, min(len(fpr), 200)).astype(int))
    tiers = np.array([risk_tier(p) for p in proba])
    tier_rates = {
        t: {"n": int((tiers == t).sum()), "outbreak_rate": float(y_true[tiers == t].mean()) if (tiers == t).any() else None}
        for t in RISK_TIERS
    }
    return {
        "threshold": threshold,
        "accuracy": float(accuracy_score(y_true, pred)),
        "precision": float(precision_score(y_true, pred, zero_division=0)),
        "recall": float(recall_score(y_true, pred, zero_division=0)),
        "f1": float(f1_score(y_true, pred, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, proba)),
        "pr_auc": float(average_precision_score(y_true, proba)),
        "prevalence": float(y_true.mean()),
        "confusion_matrix": confusion_matrix(y_true, pred, labels=[0, 1]).tolist(),
        "roc_curve": {"fpr": fpr[keep].round(4).tolist(), "tpr": tpr[keep].round(4).tolist()},
        "risk_tiers": tier_rates,
    }
