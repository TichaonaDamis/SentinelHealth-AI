"""Feature engineering shared by anomaly detection, classification and forecasting.

All features at date ``t`` use only information available at ``t`` (no
look-ahead), so the same function serves training and real-time scoring.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sentinel_ml.data.reference import DISEASES, neighbor_map

SIGNAL_FEATURES = [
    "cases_ratio_7_28",
    "cases_zscore",
    "cases_growth_7",
    "incidence_7d_per_100k",
    "ed_ratio_7_28",
    "ed_growth_7",
    "admissions_ratio_7_28",
    "positivity_ma7",
    "positivity_delta_7",
    "otc_ratio_7_28",
    "wastewater_ratio_7_28",
    "wastewater_growth_7",
    "neighbor_ratio_7_28",
]
CALENDAR_FEATURES = ["doy_sin", "doy_cos"]
MODEL_FEATURES = SIGNAL_FEATURES + CALENDAR_FEATURES + ["disease_code"]
DISEASE_INDEX = {code: i for i, code in enumerate(DISEASES)}

_EPS = 1.0


def _ratio(recent: pd.Series, baseline: pd.Series, eps: float = _EPS) -> pd.Series:
    return (recent + eps) / (baseline + eps)


def _per_series(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("date")
    out = pd.DataFrame(index=g.index)
    for col, prefix in [("cases", "cases"), ("ed_visits", "ed"), ("admissions", "admissions"),
                        ("otc_sales", "otc"), ("wastewater", "wastewater")]:
        ma7 = g[col].rolling(7, min_periods=3).mean()
        base28 = g[col].shift(7).rolling(28, min_periods=10).mean()
        out[f"{prefix}_ma7"] = ma7
        out[f"{prefix}_ratio_7_28"] = _ratio(ma7, base28)
        out[f"{prefix}_growth_7"] = _ratio(ma7, ma7.shift(7))
    base = g["cases"].shift(7).rolling(28, min_periods=10)
    out["cases_zscore"] = (out["cases_ma7"] - base.mean()) / (base.std() / np.sqrt(7) + 0.5)
    out["incidence_7d_per_100k"] = out["cases_ma7"] * 7 / g["population"] * 1e5
    pos7 = g["positivity"].rolling(7, min_periods=3).mean()
    out["positivity_ma7"] = pos7
    out["positivity_delta_7"] = pos7 - pos7.shift(7)
    return out


def build_features(panel: pd.DataFrame, neighbor_radius_km: float = 900.0) -> pd.DataFrame:
    """Return ``panel`` with engineered feature columns appended."""
    df = panel.sort_values(["disease", "region_id", "date"]).reset_index(drop=True)
    feats = df.groupby(["disease", "region_id"], group_keys=False, sort=False)[
        ["date", "cases", "ed_visits", "admissions", "otc_sales", "wastewater", "positivity", "population"]
    ].apply(_per_series)
    df = df.join(feats)

    # Mean case ratio across geographic neighbours on the same day captures regional spread.
    neighbors = neighbor_map(neighbor_radius_km)
    pivot = df.pivot_table(index=["disease", "date"], columns="region_id", values="cases_ratio_7_28")
    nb_frames = []
    for rid in pivot.columns:
        nbs = [n for n in neighbors.get(rid, ()) if n in pivot.columns]
        series = pivot[nbs].mean(axis=1) if nbs else pd.Series(1.0, index=pivot.index)
        nb_frames.append(series.rename("neighbor_ratio_7_28").to_frame().assign(region_id=rid))
    nb = pd.concat(nb_frames).reset_index()
    df = df.merge(nb, on=["disease", "date", "region_id"], how="left")
    df["neighbor_ratio_7_28"] = df["neighbor_ratio_7_28"].fillna(1.0)

    doy = pd.to_datetime(df["date"]).dt.dayofyear
    df["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["disease_code"] = df["disease"].map(DISEASE_INDEX).fillna(-1).astype(int)
    return df


def add_outbreak_target(df: pd.DataFrame, horizon_days: int = 7) -> pd.DataFrame:
    """Target = an outbreak is active now or begins within ``horizon_days``."""
    df = df.sort_values(["disease", "region_id", "date"]).copy()
    rev = df.groupby(["disease", "region_id"])["outbreak"].transform(
        lambda s: s[::-1].rolling(horizon_days + 1, min_periods=1).max()[::-1]
    )
    df["target_outbreak"] = rev.astype(int)
    return df


def feature_matrix(df: pd.DataFrame, columns: list[str] | None = None) -> pd.DataFrame:
    cols = columns or MODEL_FEATURES
    return df[cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(float)
