"""Seed reference data, demo users, synthetic surveillance history and the knowledge base.

    python -m app.db.seed --create-schema --days 400

``--create-schema`` uses ``metadata.create_all`` for local SQLite demos; with
PostgreSQL run ``alembic upgrade head`` first instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from datetime import date, timedelta

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.knowledge_seed import DOCUMENTS
from app.db.session import get_engine, get_sessionmaker
from app.models import CaseReport, DailySignal, Disease, IngestionBatch, KnowledgeDocument, Region, User
from app.schemas import KnowledgeDocIn
from app.services.copilot.service import index_document
from sentinel_ml.data import DISEASES, REGIONS, SyntheticConfig, generate_surveillance
from sentinel_ml.data.synthetic import generate_case_line_list

log = logging.getLogger("sentinel.seed")

DEMO_USERS = [
    ("admin@sentinelhealth.dev", "Platform Admin", "admin", None),
    ("epi@sentinelhealth.dev", "Dr. Ana Rivera", "epidemiologist", None),
    ("cdc.analyst@sentinelhealth.dev", "CDC Surveillance Analyst", "cdc_analyst", None),
    ("tx.officer@sentinelhealth.dev", "Texas DSHS Officer", "state_health_officer", "TX"),
    ("partner@sentinelhealth.dev", "Gulf Coast Health Network", "healthcare_partner", "TX"),
    ("viewer@sentinelhealth.dev", "Executive Viewer", "viewer", None),
]


async def seed(
    db: AsyncSession, *, days: int = 400, end: date | None = None, regions: int | None = None,
    diseases: list[str] | None = None, seed_value: int = 7, line_list_days: int = 105, max_cases: int = 40_000,
) -> None:
    s = get_settings()
    end = end or date.today() - timedelta(days=1)
    region_list = REGIONS[:regions] if regions else REGIONS
    disease_codes = diseases or list(DISEASES)

    for p in DISEASES.values():
        if await db.get(Disease, p.code) is None:
            db.add(Disease(code=p.code, name=p.name, category=p.category, icd10=p.icd10,
                           severity_weight=p.severity_weight))
    for r in REGIONS:
        if await db.get(Region, r.region_id) is None:
            db.add(Region(id=r.region_id, name=r.name, state=r.state, lat=r.lat, lon=r.lon, population=r.population))
    for email, name, role, jur in DEMO_USERS:
        if await db.scalar(select(User).where(User.email == email)) is None:
            db.add(User(email=email, full_name=name, hashed_password=hash_password(s.seed_password), role=role,
                        jurisdiction=jur, organization="SentinelHealth demo"))
    await db.flush()

    cfg = SyntheticConfig(start=end - timedelta(days=days - 1), days=days, seed=seed_value,
                          diseases=disease_codes, regions=list(region_list))
    panel = generate_surveillance(cfg)
    batch = IngestionBatch(source="synthetic_generator", pipeline="seed", source_uri="sentinel_ml.data.synthetic",
                           transform_version="1", record_count=len(panel), details={"seed": seed_value})
    db.add(batch)
    await db.flush()
    await db.execute(delete(DailySignal).where(DailySignal.observed_on >= cfg.start))
    cols = ["cases", "ed_visits", "admissions", "deaths", "positivity", "otc_sales", "wastewater"]
    records = [
        {"observed_on": row.date.date(), "region_id": row.region_id, "disease_code": row.disease,
         "batch_id": batch.id, **{c: float(getattr(row, c)) for c in cols}}
        for row in panel.itertuples(index=False)
    ]
    for i in range(0, len(records), 5000):
        await db.execute(DailySignal.__table__.insert(), records[i:i + 5000])

    recent = panel[panel["date"] > panel["date"].max() - np.timedelta64(line_list_days, "D")]
    line = generate_case_line_list(recent, seed=seed_value, max_rows=max_cases)
    rng = np.random.default_rng(seed_value)
    case_batch = IngestionBatch(source="synthetic_line_list", pipeline="seed", record_count=len(line))
    db.add(case_batch)
    await db.flush()
    case_rows = [
        {"id": uuid.uuid4(), "disease_code": r.disease, "region_id": r.region_id,
         "onset_date": r.date.date(), "report_date": (r.date + np.timedelta64(int(rng.integers(2, 9)), "D")).date(),
         "age_group": r.age_group, "lat": float(r.lat), "lon": float(r.lon), "case_status": "confirmed",
         "batch_id": case_batch.id}
        for r in line.itertuples(index=False)
    ]
    for i in range(0, len(case_rows), 5000):
        await db.execute(CaseReport.__table__.insert(), case_rows[i:i + 5000])
    await db.commit()

    existing = set((await db.scalars(select(KnowledgeDocument.title))).all())
    for doc in DOCUMENTS:
        if doc["title"] not in existing:
            await index_document(db, KnowledgeDocIn(**doc))
    log.info("seeded %d daily signals, %d case reports, %d documents", len(records), len(case_rows), len(DOCUMENTS))


async def _main(args) -> None:
    if args.create_schema:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as db:
        await seed(db, days=args.days, regions=args.regions)
        if args.scan:
            from app.services.analytics import scan_and_alert
            from app.services.forecasting import forecast_series

            # Replay the last few weeks so the demo has an alert history, then forecast every series.
            last = date.today() - timedelta(days=1)
            for back in range(28, -1, -7):
                _, n = await scan_and_alert(db, as_of=last - timedelta(days=back), notify=False)
                log.info("scan %s: %d alerts", last - timedelta(days=back), n)
            for r in (await db.scalars(select(Region))).all():
                for code in DISEASES:
                    try:
                        await forecast_series(db, code, r.id)
                    except ValueError:
                        pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=400)
    p.add_argument("--regions", type=int, default=None)
    p.add_argument("--create-schema", action="store_true")
    p.add_argument("--scan", action="store_true", help="run detection + forecasts after seeding")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
