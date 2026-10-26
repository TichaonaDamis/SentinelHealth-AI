"""Translate a case forecast into hospitalization and mortality risk."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from sentinel_ml.data.reference import DISEASES
from sentinel_ml.forecasting.models import Forecast

# Expected 14-day admissions per 100k population that map to each level.
HOSP_THRESHOLDS = (2.0, 6.0, 12.0)
DEATH_THRESHOLDS = (0.1, 0.4, 1.0)
LEVELS = ("low", "moderate", "high", "very_high")


def _level(value: float, thresholds: tuple[float, float, float]) -> str:
    for level, t in zip(LEVELS, thresholds):
        if value < t:
            return level
    return LEVELS[-1]


@dataclass
class ForecastRisk:
    horizon_days: int
    forecast_cases: float
    forecast_cases_lower: float
    forecast_cases_upper: float
    expected_admissions: float
    expected_deaths: float
    admissions_per_100k: float
    deaths_per_100k: float
    hospitalization_risk: str
    mortality_risk: str
    trend: str

    def as_dict(self) -> dict:
        return asdict(self)


def derive_risk(
    forecast: Forecast, history: pd.DataFrame, disease: str, population: int, horizon: int = 14
) -> ForecastRisk:
    """Combine forecast cases with observed (or prior) severity ratios.

    Severity ratios are estimated from the last 56 days when enough events were
    observed, otherwise the disease prior is used (empirical-Bayes style shrink).
    """
    profile = DISEASES.get(disease)
    prior_h = profile.hospitalization_rate if profile else 0.02
    prior_d = profile.case_fatality_rate if profile else 0.001
    recent = history.sort_values("date").tail(56)
    cases = float(recent["cases"].sum()) if "cases" in recent else 0.0
    k = 200.0  # pseudo-count strength of the prior
    hosp_rate = (float(recent.get("admissions", pd.Series(dtype=float)).sum()) + k * prior_h) / (cases + k)
    death_rate = (float(recent.get("deaths", pd.Series(dtype=float)).sum()) + k * prior_d) / (cases + k)

    total = forecast.total(horizon)
    adm, deaths = total * hosp_rate, total * death_rate
    per100k = 1e5 / max(population, 1)
    current_level = float(recent["cases"].tail(7).mean()) if len(recent) else 0.0
    end_level = float(forecast.mean[min(horizon, len(forecast.mean)) - 1])
    change = (end_level + 1) / (current_level + 1)
    trend = "increasing" if change > 1.15 else "decreasing" if change < 0.87 else "stable"
    return ForecastRisk(
        horizon_days=horizon,
        forecast_cases=round(total, 1),
        forecast_cases_lower=round(float(forecast.lower[:horizon].sum()), 1),
        forecast_cases_upper=round(float(forecast.upper[:horizon].sum()), 1),
        expected_admissions=round(adm, 1),
        expected_deaths=round(deaths, 2),
        admissions_per_100k=round(adm * per100k, 2),
        deaths_per_100k=round(deaths * per100k, 3),
        hospitalization_risk=_level(adm * per100k * 14 / horizon, HOSP_THRESHOLDS),
        mortality_risk=_level(deaths * per100k * 14 / horizon, DEATH_THRESHOLDS),
        trend=trend,
    )
