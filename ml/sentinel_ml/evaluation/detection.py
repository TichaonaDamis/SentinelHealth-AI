"""Event-level early-detection evaluation.

Day-level precision/recall says little about what epidemiologists care about:
*was each outbreak caught, and how many days earlier than we would otherwise
have known?* This module scores detectors at the outbreak-episode level.

"Traditional reporting" is modelled as the EARS C2 statistic computed on
confirmed cases, which reach the health department ``report_lag_days`` after
onset. ML detectors consume near-real-time feeds (syndromic, wastewater,
pharmacy) available with a ``feed_lag_days`` delay.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

KEYS = ["disease", "region_id"]


def outbreak_episodes(df: pd.DataFrame, label: str = "outbreak", min_days: int = 5) -> pd.DataFrame:
    """Contiguous runs of ``label == 1`` per series."""
    rows = []
    for (disease, region), g in df.sort_values("date").groupby(KEYS):
        y = g[label].to_numpy()
        dates = g["date"].to_numpy()
        run_id = np.cumsum(np.r_[1, np.diff(y) != 0])
        for rid in np.unique(run_id[y == 1]):
            idx = np.where(run_id == rid)[0]
            if len(idx) >= min_days:
                rows.append({"disease": disease, "region_id": region,
                             "start": pd.Timestamp(dates[idx[0]]), "end": pd.Timestamp(dates[idx[-1]])})
    return pd.DataFrame(rows, columns=["disease", "region_id", "start", "end"])


def _first_flag(flags: pd.Series, start, end, lookback_days: int) -> pd.Timestamp | None:
    window = flags[(flags.index >= start - pd.Timedelta(days=lookback_days)) & (flags.index <= end)]
    hits = window[window]
    return hits.index[0] if len(hits) else None


def early_detection_metrics(
    df: pd.DataFrame,
    flag_columns: dict[str, int],
    lookback_days: int = 7,
    reference: str | None = None,
) -> dict:
    """Score boolean flag columns against outbreak episodes.

    ``flag_columns`` maps column -> data-availability lag in days (added to the
    flag date to get the date a human could act on it).
    Returns, per detector: detection rate, median delay from outbreak onset,
    false alerts per series-year and (if ``reference`` given) median lead time
    over the reference detector.
    """
    episodes = outbreak_episodes(df)
    series = {k: g.set_index("date") for k, g in df.sort_values("date").groupby(KEYS)}
    detect_dates: dict[str, list] = {c: [] for c in flag_columns}
    for ep in episodes.itertuples(index=False):
        g = series[(ep.disease, ep.region_id)]
        for col, lag in flag_columns.items():
            d = _first_flag(g[col].astype(bool), ep.start, ep.end, lookback_days)
            detect_dates[col].append(None if d is None else d + pd.Timedelta(days=lag))

    # Outbreak windows (with margin) for counting false alerts.
    in_window = pd.Series(False, index=df.index)
    for ep in episodes.itertuples(index=False):
        in_window |= (
            (df["disease"] == ep.disease) & (df["region_id"] == ep.region_id)
            & (df["date"] >= ep.start - pd.Timedelta(days=lookback_days))
            & (df["date"] <= ep.end + pd.Timedelta(days=14))
        )
    n_series_years = df.groupby(KEYS).ngroups * (df["date"].nunique() / 365.25)

    results = {}
    for col in flag_columns:
        dates = detect_dates[col]
        delays = [(d - ep.start).days for d, ep in zip(dates, episodes.itertuples(index=False)) if d is not None]
        flags = df[col].astype(bool) & ~in_window
        onsets = (flags & ~flags.groupby([df["disease"], df["region_id"]]).shift(1, fill_value=False)).sum()
        results[col] = {
            "episodes": int(len(episodes)),
            "detected": int(len(delays)),
            "detection_rate": float(len(delays) / max(len(episodes), 1)),
            "median_delay_days": float(np.median(delays)) if delays else None,
            "false_alerts_per_series_year": float(onsets / max(n_series_years, 1e-9)),
        }
    if reference:
        ref_dates = detect_dates[reference]
        for col in flag_columns:
            if col == reference:
                continue
            leads = []
            for d, r, ep in zip(detect_dates[col], ref_dates, episodes.itertuples(index=False)):
                if d is None:
                    continue
                r = r if r is not None else ep.end + pd.Timedelta(days=flag_columns[reference])
                leads.append((r - d).days)
            results[col]["median_lead_days_vs_" + reference] = float(np.median(leads)) if leads else None
            results[col]["share_detected_earlier"] = float(np.mean(np.array(leads) > 0)) if leads else None
    return results
