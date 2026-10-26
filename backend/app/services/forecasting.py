"""Forecast service: 7/14/30-day case forecasts with hospitalization and mortality risk."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ForecastRecord
from app.schemas import ForecastOut, ForecastPoint, HorizonRisk
from app.services.data_access import latest_signal_date, load_panel
from app.services.ml_runtime import get_runtime
from sentinel_ml.classification import risk_tier
from sentinel_ml.features import build_features
from sentinel_ml.forecasting import HORIZONS, derive_risk

HISTORY_DAYS = 120


class InsufficientHistory(ValueError):
    pass


async def forecast_series(
    db: AsyncSession, disease: str, region_id: str, as_of: date | None = None, persist: bool = True,
    history_days_returned: int = 60,
) -> ForecastOut:
    as_of = as_of or await latest_signal_date(db)
    if as_of is None:
        raise InsufficientHistory("no surveillance data loaded")
    panel = await load_panel(db, end=as_of, days=HISTORY_DAYS, diseases=[disease], region_id=region_id)
    if panel.empty or len(panel) < 28:
        raise InsufficientHistory(f"need at least 28 days of history for {disease}/{region_id}")
    feats = build_features(panel)
    rt = get_runtime()
    model = rt.forecast_model(feats)
    fc = model.predict(feats, max(HORIZONS))
    proba, _, _ = rt.outbreak_probability(feats.tail(1).reset_index(drop=True))
    p = float(proba[0])
    population = int(panel["population"].iloc[0])
    risks = [derive_risk(fc, panel, disease, population, horizon=h) for h in HORIZONS]

    if persist:
        version = rt.versions.get("forecaster_xgboost") if model.name == "xgboost" else None
        for r in risks:
            db.add(ForecastRecord(
                disease_code=disease, region_id=region_id, origin_date=as_of, horizon_days=r.horizon_days,
                model=model.name, model_version=version, cases_total=r.forecast_cases,
                cases_lower=r.forecast_cases_lower, cases_upper=r.forecast_cases_upper, outbreak_probability=p,
                hospitalization_risk=r.hospitalization_risk, mortality_risk=r.mortality_risk, details=r.as_dict(),
            ))
        await db.commit()

    hist = panel.sort_values("date").tail(history_days_returned)
    ma7 = panel.sort_values("date")["cases"].rolling(7, min_periods=1).mean().tail(history_days_returned)
    return ForecastOut(
        disease_code=disease, region_id=region_id, origin_date=as_of, model=model.name,
        outbreak_probability=round(p, 4), outbreak_tier=risk_tier(p),
        horizons=[HorizonRisk(**r.as_dict()) for r in risks],
        history=[ForecastPoint(date=d.date(), mean=round(float(m), 2), lower=float(c), upper=float(c))
                 for d, m, c in zip(pd.to_datetime(hist["date"]), ma7, hist["cases"])],
        path=[ForecastPoint(date=d.date(), mean=round(float(m), 2), lower=round(float(lo), 2),
                            upper=round(float(hi), 2))
              for d, m, lo, hi in zip(fc.dates, fc.mean, fc.lower, fc.upper)],
    )
