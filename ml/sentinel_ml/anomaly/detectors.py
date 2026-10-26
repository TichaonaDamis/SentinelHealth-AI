"""Anomaly detectors for unusual disease activity.

Every detector exposes the same contract:

* ``fit(X)``     learn "normal" behaviour from historical feature vectors
* ``score(X)``   anomaly score, higher = more unusual
* ``predict(X)`` boolean flags using a threshold calibrated on training data
* ``explain(X)`` per-feature contribution for analyst-facing explanations

``EARSC2Detector`` is the CDC Early Aberration Reporting System C2 statistic and
serves as the traditional baseline the ML detectors are compared against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import RobustScaler
from sklearn.svm import OneClassSVM

from sentinel_ml.features import SIGNAL_FEATURES

log = logging.getLogger(__name__)

UPWARD_SIGNALS = ["cases_ratio_7_28", "ed_ratio_7_28", "wastewater_ratio_7_28", "otc_ratio_7_28"]


def _transform(X: pd.DataFrame) -> pd.DataFrame:
    """Log-transform multiplicative features so increases and decreases are symmetric."""
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float).copy()
    for col in X.columns:
        if "ratio" in col or "growth" in col:
            X[col] = np.log(np.clip(X[col], 1e-3, None))
        elif col.startswith("incidence"):
            X[col] = np.log1p(np.clip(X[col], 0, None))
    return X


def ears_c2(counts: pd.Series, baseline: int = 7, guard: int = 2, min_sd: float = 0.5) -> pd.Series:
    """EARS C2 statistic: today's count vs. a 7-day baseline separated by a 2-day guard band."""
    hist = counts.shift(guard + 1).rolling(baseline, min_periods=baseline)
    sd = hist.std().clip(lower=min_sd)
    return ((counts - hist.mean()) / sd).fillna(0.0)


@dataclass
class _BaseDetector:
    features: list[str] = field(default_factory=lambda: list(SIGNAL_FEATURES))
    contamination: float = 0.02
    threshold_: float | None = None
    scaler_: RobustScaler | None = None
    center_: np.ndarray | None = None

    def _prep(self, X: pd.DataFrame, fit: bool = False) -> np.ndarray:
        Xt = _transform(X[self.features])
        if fit:
            self.scaler_ = RobustScaler().fit(Xt)
        assert self.scaler_ is not None, "detector is not fitted"
        return self.scaler_.transform(Xt)

    def _raw_score(self, Z: np.ndarray) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def _fit_model(self, Z: np.ndarray) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def fit(self, X: pd.DataFrame):
        Z = self._prep(X, fit=True)
        self.center_ = np.median(Z, axis=0)
        self._fit_model(Z)
        self.threshold_ = float(np.quantile(self._raw_score(Z), 1 - self.contamination))
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return self._raw_score(self._prep(X))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.score(X) >= self.threshold_

    def explain(self, X: pd.DataFrame, top_k: int = 3) -> list[list[tuple[str, float]]]:
        """Largest standardized deviations from the training median, signed."""
        Z = self._prep(X) - self.center_
        out = []
        for row in Z:
            idx = np.argsort(-np.abs(row))[:top_k]
            out.append([(self.features[i], round(float(row[i]), 3)) for i in idx])
        return out


@dataclass
class IsolationForestDetector(_BaseDetector):
    n_estimators: int = 300
    random_state: int = 42
    model_: IsolationForest | None = None

    def _fit_model(self, Z):
        self.model_ = IsolationForest(
            n_estimators=self.n_estimators, contamination="auto", random_state=self.random_state, n_jobs=-1
        ).fit(Z)

    def _raw_score(self, Z):
        return -self.model_.score_samples(Z)


@dataclass
class OneClassSVMDetector(_BaseDetector):
    nu: float = 0.02
    gamma: str | float = "scale"
    max_train: int = 15_000
    random_state: int = 42
    model_: OneClassSVM | None = None

    def _fit_model(self, Z):
        if len(Z) > self.max_train:  # kernel SVM is O(n^2); subsample the normal class
            rng = np.random.default_rng(self.random_state)
            Z = Z[rng.choice(len(Z), self.max_train, replace=False)]
        self.model_ = OneClassSVM(nu=self.nu, gamma=self.gamma).fit(Z)

    def _raw_score(self, Z):
        return -self.model_.decision_function(Z)


@dataclass
class AutoencoderDetector(_BaseDetector):
    """Reconstruction-error detector. Uses PyTorch when installed, else an sklearn MLP autoencoder."""

    bottleneck: int = 4
    epochs: int = 40
    random_state: int = 42
    backend_: str = ""
    model_: object | None = None

    def _fit_model(self, Z):
        try:
            import torch
            from torch import nn
        except ImportError:
            self.backend_ = "sklearn"
            self.model_ = MLPRegressor(
                hidden_layer_sizes=(16, self.bottleneck, 16),
                max_iter=self.epochs * 5,
                random_state=self.random_state,
                early_stopping=True,
            ).fit(Z, Z)
            return
        self.backend_ = "torch"
        torch.manual_seed(self.random_state)
        d = Z.shape[1]
        net = nn.Sequential(
            nn.Linear(d, 16), nn.ReLU(), nn.Linear(16, self.bottleneck), nn.ReLU(),
            nn.Linear(self.bottleneck, 16), nn.ReLU(), nn.Linear(16, d),
        )
        opt = torch.optim.Adam(net.parameters(), lr=1e-3)
        data = torch.tensor(Z, dtype=torch.float32)
        loader = torch.utils.data.DataLoader(data, batch_size=256, shuffle=True)
        for _ in range(self.epochs):
            for batch in loader:
                opt.zero_grad()
                loss = nn.functional.mse_loss(net(batch), batch)
                loss.backward()
                opt.step()
        net.eval()
        self.model_ = net

    def _reconstruct(self, Z):
        if self.backend_ == "torch":
            import torch

            with torch.no_grad():
                return self.model_(torch.tensor(Z, dtype=torch.float32)).numpy()
        return self.model_.predict(Z)

    def _raw_score(self, Z):
        return np.mean((Z - self._reconstruct(Z)) ** 2, axis=1)


@dataclass
class EARSC2Detector:
    """Feature-space wrapper around the EARS C2 z-score (``cases_zscore``) for side-by-side evaluation."""

    threshold_: float = 3.0
    features: list[str] = field(default_factory=lambda: ["cases_zscore"])

    def fit(self, X: pd.DataFrame):
        return self

    def score(self, X: pd.DataFrame) -> np.ndarray:
        return X["cases_zscore"].fillna(0.0).to_numpy()

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.score(X) >= self.threshold_


@dataclass
class EnsembleAnomalyDetector:
    """Rank-averaged ensemble of Isolation Forest, One-Class SVM and Autoencoder.

    Scores are converted to empirical percentiles of the training distribution,
    averaged, and gated so only *increases* in activity are flagged (a drop in
    flu cases is not a public-health alert).
    """

    contamination: float = 0.02
    detectors: dict[str, _BaseDetector] = field(default_factory=dict)
    train_scores_: dict[str, np.ndarray] = field(default_factory=dict)
    threshold_: float | None = None

    def __post_init__(self):
        if not self.detectors:
            self.detectors = {
                "isolation_forest": IsolationForestDetector(contamination=self.contamination),
                "one_class_svm": OneClassSVMDetector(contamination=self.contamination),
                "autoencoder": AutoencoderDetector(contamination=self.contamination),
            }

    def fit(self, X: pd.DataFrame):
        for name, det in self.detectors.items():
            det.fit(X)
            self.train_scores_[name] = np.sort(det.score(X))
        combined = self._combine(X)
        self.threshold_ = float(np.quantile(combined, 1 - self.contamination))
        return self

    def _percentile(self, name: str, scores: np.ndarray) -> np.ndarray:
        ref = self.train_scores_[name]
        return np.searchsorted(ref, scores, side="right") / len(ref)

    def _combine(self, X: pd.DataFrame) -> np.ndarray:
        pct = [self._percentile(n, d.score(X)) for n, d in self.detectors.items()]
        return np.mean(pct, axis=0)

    def component_scores(self, X: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {n: self._percentile(n, d.score(X)) for n, d in self.detectors.items()}, index=X.index
        )

    def score(self, X: pd.DataFrame) -> np.ndarray:
        combined = self._combine(X)
        upward = np.zeros(len(X), dtype=bool)
        for col in UPWARD_SIGNALS:
            if col in X:
                upward |= X[col].fillna(1.0).to_numpy() > 1.15
        return np.where(upward, combined, combined * 0.5)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.score(X) >= self.threshold_

    def explain(self, X: pd.DataFrame, top_k: int = 3):
        return self.detectors["isolation_forest"].explain(X, top_k=top_k)
