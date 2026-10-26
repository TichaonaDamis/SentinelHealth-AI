"""Query helpers that turn operational tables into the DataFrames the ML library expects."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailySignal, Region

SIGNAL_COLUMNS = ["cases", "ed_visits", "admissions", "deaths", "positivity", "otc_sales", "wastewater"]


async def latest_signal_date(db: AsyncSession) -> date | None:
    return await db.scalar(select(func.max(DailySignal.observed_on)))


async def load_panel(
    db: AsyncSession,
    *,
    end: date,
    days: int,
    diseases: list[str] | None = None,
    state: str | None = None,
    region_id: str | None = None,
) -> pd.DataFrame:
    """Daily panel for ``[end - days + 1, end]`` with region attributes, gaps filled per series."""
    start = end - timedelta(days=days - 1)
    stmt = (
        select(DailySignal, Region)
        .join(Region, Region.id == DailySignal.region_id)
        .where(DailySignal.observed_on.between(start, end))
    )
    if diseases:
        stmt = stmt.where(DailySignal.disease_code.in_(diseases))
    if state:
        stmt = stmt.where(Region.state == state)
    if region_id:
        stmt = stmt.where(DailySignal.region_id == region_id)
    rows = (await db.execute(stmt)).all()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(
        [
            {
                "date": s.observed_on, "region_id": s.region_id, "disease": s.disease_code,
                "region_name": r.name, "state": r.state, "lat": r.lat, "lon": r.lon, "population": r.population,
                **{c: getattr(s, c) for c in SIGNAL_COLUMNS},
            }
            for s, r in rows
        ]
    )
    df["date"] = pd.to_datetime(df["date"])
    return _complete(df, start, end)


def _complete(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Reindex every series to a full daily calendar; counts missing -> 0, rates/indices forward-filled."""
    calendar = pd.date_range(start, end, freq="D")
    attrs = ["region_name", "state", "lat", "lon", "population"]
    out = []
    for (disease, rid), g in df.groupby(["disease", "region_id"]):
        g = g.set_index("date").reindex(calendar)
        for c in ["cases", "ed_visits", "admissions", "deaths"]:
            g[c] = g[c].astype(float).fillna(0.0)
        for c in ["positivity", "otc_sales", "wastewater"]:
            g[c] = g[c].astype(float).ffill().bfill().fillna(0.0)
        g[attrs] = g[attrs].ffill().bfill()
        g["disease"], g["region_id"] = disease, rid
        out.append(g.rename_axis("date").reset_index())
    res = pd.concat(out, ignore_index=True)
    res["population"] = res["population"].astype(int)
    res["outbreak"] = 0  # unknown in production; required column for feature builders
    return res
