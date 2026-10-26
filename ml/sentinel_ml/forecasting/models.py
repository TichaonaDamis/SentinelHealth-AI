"""Disease-activity forecasters (7/14/30-day horizons).

Forecasts are made on the 7-day moving average of daily cases, which removes
day-of-week reporting artefacts. Models predict the log-ratio between future and
current activity so a single *global* model generalises across regions of very
different size. Prediction intervals are split-conformal (80% by default), which
gives honest coverage without distributional assumptions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import xgboost as xgb

log = logging.getLogger(__name__)

MAX_HORIZON = 30
HORIZONS = (7, 14, 30)
CONTEXT_FEATURES = [
    "cases_ratio_7_28", "cases_growth_7", "ed_ratio_7_28", "ed_growth_7", "admissions_ratio_7_28",
    "positivity_delta_7", "otc_ratio_7_28", "wastewater_ratio_7_28", "wastewater_growth_7",
    "neighbor_ratio_7_28", "disease_code",
]


@dataclass
class Forecast:
    origin: pd.Timestamp
    dates: pd.DatetimeIndex
    mean: np.ndarray
    lower: np.ndarray
    upper: np.ndarray
    model: str

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"date": self.dates, "mean": self.mean, "lower": self.lower, "upper": self.upper, "model": self.model}
        )

    def total(self, horizon: int) -> float:
        return float(self.mean[:horizon].sum())


def _lag_features(ma7: pd.Series) -> pd.DataFrame:
    lm = np.log1p(ma7)
    out = pd.DataFrame(index=ma7.index)
    for lag in (1, 3, 7, 14, 21, 28):
        out[f"logdiff_{lag}"] = lm - lm.shift(lag)
    out["log_level"] = lm
    return out


def _series_frame(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date").reset_index(drop=True)
    ma7 = g["cases"].rolling(7, min_periods=1).mean()
    f = _lag_features(ma7)
    for c in CONTEXT_FEATURES:
        f[c] = g[c].to_numpy() if c in g else 0.0
    f["date"] = g["date"].to_numpy()
    f["ma7"] = ma7.to_numpy()
    return f


@dataclass
class SeasonalNaiveForecaster:
    """Persistence of the current 7-day average; the reference model every other model must beat."""

    name: str = "seasonal_naive"
    coverage: float = 0.8
    q_: dict[int, tuple[float, float]] = field(default_factory=dict)

    def fit(self, panel: pd.DataFrame):
        errs: dict[int, list[np.ndarray]] = {k: [] for k in range(1, MAX_HORIZON + 1)}
        for _, g in panel.groupby(["disease", "region_id"]):
            lm = np.log1p(g.sort_values("date")["cases"].rolling(7, min_periods=1).mean().to_numpy())
            for k in errs:
                errs[k].append(lm[k:] - lm[:-k])
        a = (1 - self.coverage) / 2
        for k, e in errs.items():
            e = np.concatenate(e)
            self.q_[k] = (float(np.quantile(e, a)), float(np.quantile(e, 1 - a)))
        return self

    def predict(self, history: pd.DataFrame, horizon: int = MAX_HORIZON) -> Forecast:
        g = history.sort_values("date")
        level = float(g["cases"].tail(7).mean())
        origin = pd.Timestamp(g["date"].iloc[-1])
        ks = np.arange(1, horizon + 1)
        lo = np.array([self.q_.get(k, (0, 0))[0] for k in ks])
        hi = np.array([self.q_.get(k, (0, 0))[1] for k in ks])
        lv = np.log1p(level)
        return Forecast(
            origin, pd.date_range(origin + pd.Timedelta(days=1), periods=horizon),
            np.full(horizon, level), np.clip(np.expm1(lv + lo), 0, None), np.expm1(lv + hi), self.name,
        )


@dataclass
class XGBoostForecaster:
    """Global gradient-boosted model with horizon-as-a-feature (direct multi-step strategy)."""

    name: str = "xgboost"
    stride: int = 5
    coverage: float = 0.8
    calibration_fraction: float = 0.2
    params: dict = field(default_factory=lambda: {
        "n_estimators": 400, "max_depth": 6, "learning_rate": 0.05, "subsample": 0.8,
        "colsample_bytree": 0.8, "min_child_weight": 5, "tree_method": "hist", "n_jobs": -1,
    })
    model_: xgb.XGBRegressor | None = None
    feature_names_: list[str] = field(default_factory=list)
    q_: dict[int, tuple[float, float]] = field(default_factory=dict)

    def _rows(self, f: pd.DataFrame, origins: np.ndarray, target: bool) -> pd.DataFrame:
        lm = np.log1p(f["ma7"].to_numpy())
        dates = pd.to_datetime(f["date"])
        base = f.iloc[origins].reset_index(drop=True)
        blocks = []
        for k in range(1, MAX_HORIZON + 1):
            b = base.copy()
            b["horizon"] = k
            target_doy = (dates.iloc[origins] + pd.Timedelta(days=k)).dt.dayofyear.to_numpy()
            b["target_doy_sin"] = np.sin(2 * np.pi * target_doy / 365.25)
            b["target_doy_cos"] = np.cos(2 * np.pi * target_doy / 365.25)
            b["origin_idx"] = origins
            if target:
                b["y"] = lm[origins + k] - lm[origins]
            blocks.append(b)
        return pd.concat(blocks, ignore_index=True)

    def _training_rows(self, panel: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for _, g in panel.groupby(["disease", "region_id"]):
            f = _series_frame(g)
            valid = np.arange(28, len(f) - MAX_HORIZON, self.stride)
            if len(valid):
                rows.append(self._rows(f, valid, target=True))
        return pd.concat(rows, ignore_index=True)

    def fit(self, panel: pd.DataFrame):
        data = self._training_rows(panel)
        self.feature_names_ = [c for c in data.columns if c not in ("y", "date", "ma7", "origin_idx")]
        cutoff = data["date"].quantile(1 - self.calibration_fraction)
        train, calib = data[data["date"] < cutoff], data[data["date"] >= cutoff]
        self.model_ = xgb.XGBRegressor(**self.params).fit(train[self.feature_names_], train["y"])
        resid = calib["y"].to_numpy() - self.model_.predict(calib[self.feature_names_])
        a = (1 - self.coverage) / 2
        for k in range(1, MAX_HORIZON + 1):
            r = resid[calib["horizon"].to_numpy() == k]
            self.q_[k] = (float(np.quantile(r, a)), float(np.quantile(r, 1 - a))) if len(r) else (-0.5, 0.5)
        # Refit on all data now that intervals are calibrated.
        self.model_ = xgb.XGBRegressor(**self.params).fit(data[self.feature_names_], data["y"])
        return self

    def predict(self, history: pd.DataFrame, horizon: int = MAX_HORIZON) -> Forecast:
        f = _series_frame(history)
        rows = self._rows(f, np.array([len(f) - 1]), target=False)
        rows = rows[rows["horizon"] <= horizon]
        delta = self.model_.predict(rows[self.feature_names_])
        lv = np.log1p(f["ma7"].iloc[-1])
        lo = np.array([self.q_[k][0] for k in range(1, horizon + 1)])
        hi = np.array([self.q_[k][1] for k in range(1, horizon + 1)])
        origin = pd.Timestamp(f["date"].iloc[-1])
        return Forecast(
            origin, pd.date_range(origin + pd.Timedelta(days=1), periods=horizon),
            np.clip(np.expm1(lv + delta), 0, None),
            np.clip(np.expm1(lv + delta + lo), 0, None),
            np.expm1(lv + delta + hi), self.name,
        )

    def feature_importance(self, top_k: int = 15) -> list[tuple[str, float]]:
        imp = self.model_.feature_importances_
        order = np.argsort(-imp)[:top_k]
        return [(self.feature_names_[i], round(float(imp[i]), 4)) for i in order]


@dataclass
class LSTMForecaster:
    """Sequence-to-vector LSTM over the last 56 days of log activity (requires PyTorch)."""

    name: str = "lstm"
    window: int = 56
    hidden: int = 32
    epochs: int = 15
    stride: int = 3
    coverage: float = 0.8
    random_state: int = 42
    model_: object | None = None
    q_: dict[int, tuple[float, float]] = field(default_factory=dict)

    @staticmethod
    def available() -> bool:
        try:
            import torch  # noqa: F401
        except ImportError:
            return False
        return True

    def _windows(self, panel: pd.DataFrame):
        X, Y = [], []
        for _, g in panel.groupby(["disease", "region_id"]):
            lm = np.log1p(g.sort_values("date")["cases"].rolling(7, min_periods=1).mean().to_numpy())
            for t in range(self.window, len(lm) - MAX_HORIZON, self.stride):
                X.append(lm[t - self.window:t] - lm[t - 1])
                Y.append(lm[t:t + MAX_HORIZON] - lm[t - 1])
        return np.asarray(X, dtype=np.float32)[..., None], np.asarray(Y, dtype=np.float32)

    def fit(self, panel: pd.DataFrame):
        import torch
        from torch import nn

        torch.manual_seed(self.random_state)
        X, Y = self._windows(panel)
        n_cal = int(len(X) * 0.15)
        idx = np.random.default_rng(self.random_state).permutation(len(X))
        cal, tr = idx[:n_cal], idx[n_cal:]

        class Net(nn.Module):
            def __init__(self, hidden: int):
                super().__init__()
                self.lstm = nn.LSTM(1, hidden, batch_first=True)
                self.head = nn.Linear(hidden, MAX_HORIZON)

            def forward(self, x):
                _, (h, _) = self.lstm(x)
                return self.head(h[-1])

        net = Net(self.hidden)
        opt = torch.optim.Adam(net.parameters(), lr=2e-3)
        ds = torch.utils.data.TensorDataset(torch.tensor(X[tr]), torch.tensor(Y[tr]))
        loader = torch.utils.data.DataLoader(ds, batch_size=256, shuffle=True)
        for _ in range(self.epochs):
            for xb, yb in loader:
                opt.zero_grad()
                nn.functional.smooth_l1_loss(net(xb), yb).backward()
                opt.step()
        net.eval()
        with torch.no_grad():
            resid = Y[cal] - net(torch.tensor(X[cal])).numpy()
        a = (1 - self.coverage) / 2
        for k in range(1, MAX_HORIZON + 1):
            self.q_[k] = (float(np.quantile(resid[:, k - 1], a)), float(np.quantile(resid[:, k - 1], 1 - a)))
        self.model_ = net
        return self

    def predict(self, history: pd.DataFrame, horizon: int = MAX_HORIZON) -> Forecast:
        import torch

        g = history.sort_values("date")
        lm = np.log1p(g["cases"].rolling(7, min_periods=1).mean().to_numpy())
        x = (lm[-self.window:] - lm[-1]).astype(np.float32)[None, :, None]
        with torch.no_grad():
            delta = self.model_(torch.tensor(x)).numpy()[0][:horizon]
        lo = np.array([self.q_[k][0] for k in range(1, horizon + 1)])
        hi = np.array([self.q_[k][1] for k in range(1, horizon + 1)])
        origin = pd.Timestamp(g["date"].iloc[-1])
        return Forecast(
            origin, pd.date_range(origin + pd.Timedelta(days=1), periods=horizon),
            np.clip(np.expm1(lm[-1] + delta), 0, None), np.clip(np.expm1(lm[-1] + delta + lo), 0, None),
            np.expm1(lm[-1] + delta + hi), self.name,
        )


@dataclass
class ProphetForecaster:
    """Per-series Prophet model with yearly + weekly seasonality (requires ``prophet``)."""

    name: str = "prophet"
    coverage: float = 0.8

    @staticmethod
    def available() -> bool:
        try:
            import prophet  # noqa: F401
        except ImportError:
            return False
        return True

    def fit(self, panel: pd.DataFrame):
        return self  # Prophet is fitted per series at prediction time.

    def predict(self, history: pd.DataFrame, horizon: int = MAX_HORIZON) -> Forecast:
        from prophet import Prophet

        g = history.sort_values("date")
        df = pd.DataFrame({"ds": g["date"], "y": np.log1p(g["cases"].rolling(7, min_periods=1).mean())})
        m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False,
                    interval_width=self.coverage)
        m.fit(df)
        fc = m.predict(m.make_future_dataframe(periods=horizon, include_history=False))
        origin = pd.Timestamp(g["date"].iloc[-1])
        return Forecast(
            origin, pd.DatetimeIndex(fc["ds"]), np.clip(np.expm1(fc["yhat"].to_numpy()), 0, None),
            np.clip(np.expm1(fc["yhat_lower"].to_numpy()), 0, None), np.expm1(fc["yhat_upper"].to_numpy()),
            self.name,
        )


@dataclass
class EnsembleForecaster:
    """Median-of-models ensemble; robust to any single model failing on a regime change."""

    members: list
    name: str = "ensemble"

    def predict(self, history: pd.DataFrame, horizon: int = MAX_HORIZON) -> Forecast:
        fcs = [m.predict(history, horizon) for m in self.members]
        stack = lambda attr: np.median(np.vstack([getattr(f, attr) for f in fcs]), axis=0)  # noqa: E731
        return Forecast(fcs[0].origin, fcs[0].dates, stack("mean"), stack("lower"), stack("upper"), self.name)


def backtest(
    panel: pd.DataFrame,
    models: list,
    start: pd.Timestamp,
    step_days: int = 14,
    horizons: tuple[int, ...] = HORIZONS,
    max_series: int | None = None,
) -> pd.DataFrame:
    """Rolling-origin evaluation. Error is measured on horizon-total cases (what planners use)."""
    records = []
    groups = list(panel.groupby(["disease", "region_id"]))
    if max_series:
        groups = groups[:max_series]
    for (disease, region), g in groups:
        g = g.sort_values("date").reset_index(drop=True)
        origins = g.index[(g["date"] >= start) & (g.index < len(g) - max(horizons))][::step_days]
        for o in origins:
            hist = g.iloc[: o + 1]
            for model in models:
                fc = model.predict(hist, max(horizons))
                for h in horizons:
                    actual = float(g["cases"].iloc[o + 1: o + 1 + h].sum())
                    pred = fc.total(h)
                    lo, hi = float(fc.lower[:h].sum()), float(fc.upper[:h].sum())
                    records.append({
                        "disease": disease, "region_id": region, "origin": g["date"].iloc[o], "model": model.name,
                        "horizon": h, "actual": actual, "pred": pred,
                        "abs_err": abs(actual - pred),
                        "smape": 0.0 if actual + pred == 0 else 2 * abs(actual - pred) / (abs(actual) + abs(pred)),
                        "covered": lo <= actual <= hi,
                    })
    return pd.DataFrame.from_records(records)


def summarize_backtest(results: pd.DataFrame) -> pd.DataFrame:
    s = results.groupby(["model", "horizon"]).agg(
        mae=("abs_err", "mean"), smape=("smape", "mean"), coverage_80=("covered", "mean"), n=("abs_err", "size"),
    ).reset_index()
    naive = s[s["model"] == "seasonal_naive"].set_index("horizon")["mae"]
    s["skill_vs_naive"] = 1 - s["mae"] / s["horizon"].map(naive)
    return s
