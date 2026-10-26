"""Synthetic multi-source surveillance data generator.

Produces a daily panel (region x disease x day) that mimics the signals a health
department receives from different feeds, each with a realistic relationship to
the true (unobserved) epidemic curve:

* ``cases``            confirmed cases by onset date (reported ~7 days late in practice)
* ``ed_visits``        syndromic emergency-department visits; leads cases by ~2 days
* ``admissions``       hospital admissions; lags cases by ~3 days
* ``deaths``           deaths; lags cases by ~10 days
* ``positivity``       lab test positivity
* ``otc_sales``        pharmacy over-the-counter sales index; leads cases by ~5 days
* ``wastewater``       viral concentration index; leads cases by ~5 days

Outbreaks are injected as gamma-shaped multipliers on the seasonal baseline and
spread to neighbouring regions with a delay. Ground-truth labels (``outbreak``)
make the data usable for supervised training and for measuring detection lead
time against traditional (lagged) case reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from sentinel_ml.data.reference import DISEASES, REGIONS, DiseaseProfile, Region, neighbor_map

LEADS = {"ed_visits": 2, "otc_sales": 5, "wastewater": 5}
LAGS = {"admissions": 3, "deaths": 10}


@dataclass
class SyntheticConfig:
    start: date = date(2023, 1, 1)
    days: int = 3 * 365
    seed: int = 42
    diseases: list[str] = field(default_factory=lambda: list(DISEASES))
    regions: list[Region] = field(default_factory=lambda: list(REGIONS))
    dispersion: float = 12.0  # negative-binomial size; lower = noisier
    spread_probability: float = 0.45


def _seasonal(doy: np.ndarray, profile: DiseaseProfile) -> np.ndarray:
    s = 1.0 + profile.seasonal_amplitude * np.cos(2 * np.pi * (doy - profile.peak_day_of_year) / 365.25)
    return np.clip(s, 0.08, None)


def _epi_curve(n: int, start: int, peak: int, duration: int, k: float = 3.0) -> np.ndarray:
    """Gamma-shaped pulse equal to 1.0 at the peak, 0 outside ``[start, start+duration)``."""
    t = np.arange(n, dtype=float) - start
    curve = np.zeros(n)
    mask = (t >= 0) & (t < duration)
    x = t[mask] / peak
    curve[mask] = np.power(x, k) * np.exp(k * (1 - x))
    return curve


def _shift(arr: np.ndarray, lead: int) -> np.ndarray:
    """Return ``arr`` evaluated ``lead`` days in the future (positive) or past (negative)."""
    if lead == 0:
        return arr
    out = np.empty_like(arr)
    if lead > 0:
        out[:-lead] = arr[lead:]
        out[-lead:] = arr[-1]
    else:
        out[-lead:] = arr[:lead]
        out[:-lead] = arr[0]
    return out


def _signal(base: np.ndarray, excess: np.ndarray, lead: int, additive: bool) -> np.ndarray:
    """Expected activity seen by a feed that leads (lead > 0) or lags (lead < 0) the true curve."""
    shifted = _shift(excess, lead)
    return base + shifted if additive else base * (1.0 + shifted)


def _negbin(rng: np.random.Generator, mean: np.ndarray, size: float) -> np.ndarray:
    lam = rng.gamma(shape=size, scale=np.maximum(mean, 1e-9) / size)
    return rng.poisson(lam)


def _outbreak_signals(
    cfg: SyntheticConfig, rng: np.random.Generator, profile: DiseaseProfile
) -> dict[str, np.ndarray]:
    """Per-region outbreak intensity (0 = none). Multiplicative excess or additive cases."""
    n = cfg.days
    intensity = {r.region_id: np.zeros(n) for r in cfg.regions}
    neighbors = neighbor_map()
    years = n / 365.0
    for region in cfg.regions:
        for _ in range(rng.poisson(profile.outbreaks_per_region_year * years)):
            start = int(rng.integers(30, n - 20))
            peak = int(rng.integers(7, 22))
            duration = int(rng.integers(peak + 14, peak + 40))
            if profile.additive_outbreaks:
                magnitude = float(rng.uniform(2.0, 12.0)) * region.population / 1_000_000
                magnitude = max(magnitude, 1.5)
            else:
                magnitude = float(rng.uniform(0.8, 4.0))
            intensity[region.region_id] += magnitude * _epi_curve(n, start, peak, duration)
            for nb in neighbors.get(region.region_id, ()):
                if nb in intensity and rng.random() < cfg.spread_probability:
                    delay = int(rng.integers(5, 12))
                    scale = float(rng.uniform(0.3, 0.7))
                    intensity[nb] += scale * magnitude * _epi_curve(n, start + delay, peak, duration)
    return intensity


def generate_surveillance(cfg: SyntheticConfig | None = None) -> pd.DataFrame:
    cfg = cfg or SyntheticConfig()
    rng = np.random.default_rng(cfg.seed)
    dates = pd.date_range(cfg.start, periods=cfg.days, freq="D")
    doy = dates.dayofyear.to_numpy()
    dow_effect = np.where(dates.dayofweek.to_numpy() >= 5, 0.72, 1.06)

    frames: list[pd.DataFrame] = []
    for code in cfg.diseases:
        profile = DISEASES[code]
        seasonal = _seasonal(doy, profile)
        intensities = _outbreak_signals(cfg, rng, profile)
        for region in cfg.regions:
            geo = 1.0
            if profile.tropical:
                geo = float(np.clip((36.0 - region.lat) / 10.0, 0.03, 1.8))
            base = region.population / 1e5 * profile.base_rate_per_100k * seasonal * geo
            excess = intensities[region.region_id]
            if profile.additive_outbreaks:
                truth = base + excess
                label = excess >= 1.0
            else:
                truth = base * (1.0 + excess)
                label = excess >= 0.3

            def signal(lead: int, base=base, excess=excess, additive=profile.additive_outbreaks) -> np.ndarray:
                return _signal(base, excess, lead, additive)

            cases = _negbin(rng, truth * dow_effect, cfg.dispersion)
            ed = _negbin(rng, signal(LEADS["ed_visits"]) * 2.8 * dow_effect + 0.5, cfg.dispersion)
            admissions = _negbin(rng, signal(-LAGS["admissions"]) * profile.hospitalization_rate, cfg.dispersion)
            deaths = _negbin(rng, signal(-LAGS["deaths"]) * profile.case_fatality_rate, cfg.dispersion)
            rel = signal(0) / np.maximum(base, 1e-6)
            positivity = np.clip(0.03 * seasonal * np.sqrt(rel) + rng.normal(0, 0.006, cfg.days), 0.001, 0.7)
            otc_rel = signal(LEADS["otc_sales"]) / np.maximum(base, 1e-6)
            otc = 100.0 * (0.85 + 0.15 * seasonal) * (1 + 0.25 * np.log(otc_rel)) + rng.normal(0, 4, cfg.days)
            ww_rel = signal(LEADS["wastewater"]) / np.maximum(base, 1e-6)
            wastewater = 50.0 * seasonal * ww_rel * rng.lognormal(0, 0.18, cfg.days)

            frames.append(
                pd.DataFrame(
                    {
                        "date": dates,
                        "region_id": region.region_id,
                        "region_name": region.name,
                        "state": region.state,
                        "lat": region.lat,
                        "lon": region.lon,
                        "population": region.population,
                        "disease": code,
                        "cases": cases,
                        "ed_visits": ed,
                        "admissions": admissions,
                        "deaths": deaths,
                        "positivity": positivity.round(4),
                        "otc_sales": otc.round(2),
                        "wastewater": wastewater.round(2),
                        "outbreak": label.astype(int),
                    }
                )
            )
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["disease", "region_id", "date"], ignore_index=True)


def generate_case_line_list(panel: pd.DataFrame, seed: int = 7, max_rows: int = 50_000) -> pd.DataFrame:
    """Expand aggregated counts into de-identified, geo-jittered case records.

    Used for spatial cluster detection; coordinates are jittered around the
    region centroid (the production system receives census-tract centroids,
    never residential addresses).
    """
    rng = np.random.default_rng(seed)
    rows = panel.loc[panel["cases"] > 0, ["date", "region_id", "disease", "lat", "lon", "cases", "outbreak"]]
    reps = rows.loc[rows.index.repeat(rows["cases"].clip(upper=200))].reset_index(drop=True)
    if len(reps) > max_rows:
        reps = reps.sample(max_rows, random_state=seed).reset_index(drop=True)
    spread = np.where(reps["outbreak"].to_numpy() == 1, 0.05, 0.35)
    reps["lat"] = reps["lat"] + rng.normal(0, spread)
    reps["lon"] = reps["lon"] + rng.normal(0, spread)
    reps["age_group"] = rng.choice(["0-4", "5-17", "18-49", "50-64", "65+"], len(reps), p=[0.1, 0.18, 0.4, 0.17, 0.15])
    return reps.drop(columns=["cases"])
