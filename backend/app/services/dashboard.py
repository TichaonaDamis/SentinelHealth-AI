"""Executive dashboard aggregation."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alert, DailySignal, ForecastRecord, OutbreakEvent, Region
from app.schemas import KPI, AlertOut, DashboardSummary, RegionRisk, TrendPoint
from app.services.analytics import assess
from app.services.data_access import latest_signal_date
from app.services.risk import LEVEL_RANK, LEVELS


async def summary(db: AsyncSession, state: str | None = None, trend_days: int = 120) -> DashboardSummary | None:
    as_of = await latest_signal_date(db)
    if as_of is None:
        return None
    region_filter = [Region.state == state] if state else []

    async def cases_between(start, end) -> float:
        stmt = (select(func.coalesce(func.sum(DailySignal.cases), 0)).join(Region, Region.id == DailySignal.region_id)
                .where(DailySignal.observed_on.between(start, end), *region_filter))
        return float(await db.scalar(stmt) or 0)

    active = await cases_between(as_of - timedelta(days=13), as_of)
    prior = await cases_between(as_of - timedelta(days=27), as_of - timedelta(days=14))

    outbreaks = await db.scalar(
        select(func.count(func.distinct(OutbreakEvent.disease_code + OutbreakEvent.region_id)))
        .join(Region, Region.id == OutbreakEvent.region_id)
        .where(OutbreakEvent.detected_on >= as_of - timedelta(days=14),
               OutbreakEvent.risk_level.in_(["orange", "red"]), *region_filter)
    ) or 0

    latest_fc = (select(ForecastRecord.disease_code, ForecastRecord.region_id,
                        func.max(ForecastRecord.origin_date).label("origin"))
                 .where(ForecastRecord.horizon_days == 14).group_by(ForecastRecord.disease_code, ForecastRecord.region_id)
                 .subquery())
    fc_stmt = (select(func.coalesce(func.sum(ForecastRecord.cases_total), 0))
               .join(latest_fc, (latest_fc.c.disease_code == ForecastRecord.disease_code)
                     & (latest_fc.c.region_id == ForecastRecord.region_id)
                     & (latest_fc.c.origin == ForecastRecord.origin_date))
               .join(Region, Region.id == ForecastRecord.region_id)
               .where(ForecastRecord.horizon_days == 14, *region_filter))
    forecasted = float(await db.scalar(fc_stmt) or 0)
    if forecasted == 0:  # no stored forecasts yet: persistence estimate
        forecasted = await cases_between(as_of - timedelta(days=6), as_of) * 2

    alert_rows = (await db.execute(
        select(Alert.risk_level, func.count()).join(Region, Region.id == Alert.region_id)
        .where(Alert.status.in_(["open", "acknowledged"]), *region_filter).group_by(Alert.risk_level)
    )).all()
    by_level = {lvl: 0 for lvl in LEVELS[1:]} | {lvl: int(n) for lvl, n in alert_rows}

    assessments = await assess(db, as_of, None, state)
    regions = {r.id: r for r in (await db.scalars(select(Region).where(*region_filter))).all()}
    per_region: dict[str, dict] = {}
    for a in assessments:
        cur = per_region.setdefault(a.region_id, {"incidence": 0.0, "level": "green", "top": None, "score": -1.0})
        cur["incidence"] += a.incidence_7d_per_100k
        if (LEVEL_RANK[a.risk_level], a.risk_score) > (LEVEL_RANK[cur["level"]], cur["score"]):
            cur["level"], cur["top"], cur["score"] = a.risk_level, a.disease_code, a.risk_score
    region_risk = [
        RegionRisk(region_id=rid, name=r.name, state=r.state, lat=r.lat, lon=r.lon,
                   incidence_7d_per_100k=round(per_region.get(rid, {}).get("incidence", 0.0), 2),
                   risk_level=per_region.get(rid, {}).get("level", "green"),
                   top_disease=per_region.get(rid, {}).get("top"))
        for rid, r in regions.items()
    ]
    hotspots = sum(1 for r in region_risk if LEVEL_RANK[r.risk_level] >= LEVEL_RANK["orange"])

    trend_stmt = (select(DailySignal.observed_on, DailySignal.disease_code, func.sum(DailySignal.cases))
                  .join(Region, Region.id == DailySignal.region_id)
                  .where(DailySignal.observed_on > as_of - timedelta(days=trend_days), *region_filter)
                  .group_by(DailySignal.observed_on, DailySignal.disease_code).order_by(DailySignal.observed_on))
    by_day: dict = {}
    for d, code, n in (await db.execute(trend_stmt)).all():
        by_day.setdefault(d, {})[code] = float(n or 0)

    recent = (await db.scalars(
        select(Alert).join(Region, Region.id == Alert.region_id).where(*region_filter)
        .order_by(Alert.created_at.desc()).limit(15)
    )).all()

    return DashboardSummary(
        as_of=as_of,
        kpis=KPI(
            active_cases=int(active), active_cases_change_pct=round((active - prior) / prior * 100, 1) if prior else 0.0,
            outbreaks_detected=int(outbreaks), forecasted_cases_14d=int(forecasted),
            open_alerts=sum(by_level.values()), alerts_by_level=by_level, hotspots=hotspots,
        ),
        trend=[TrendPoint(date=d, values=v) for d, v in sorted(by_day.items())],
        regions=sorted(region_risk, key=lambda r: (-LEVEL_RANK[r.risk_level], -r.incidence_7d_per_100k)),
        recent_alerts=[AlertOut.model_validate(a) for a in recent],
    )
