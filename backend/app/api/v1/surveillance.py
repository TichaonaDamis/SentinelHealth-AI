import hashlib
import json
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, CurrentPrincipal, Principal, require
from app.core.rbac import Perm
from app.models import CaseReport, DailySignal, Disease, IngestionBatch, Region
from app.schemas import (
    CaseReportIn,
    DiseaseOut,
    IngestRequest,
    IngestResult,
    LineageOut,
    RegionOut,
    SignalOut,
)
from app.services.data_access import SIGNAL_COLUMNS

router = APIRouter(tags=["surveillance"])


@router.get("/diseases", response_model=list[DiseaseOut])
async def list_diseases(db: DB, _: CurrentPrincipal):
    return (await db.scalars(select(Disease).order_by(Disease.name))).all()


@router.get("/regions", response_model=list[RegionOut])
async def list_regions(db: DB, principal: CurrentPrincipal, state: str | None = None):
    st = principal.effective_state(state)
    stmt = select(Region).order_by(Region.state, Region.name)
    if st:
        stmt = stmt.where(Region.state == st)
    return (await db.scalars(stmt)).all()


@router.post("/surveillance/signals", response_model=IngestResult, status_code=201,
             summary="Ingest daily aggregated signals (idempotent upsert, lineage-tracked)")
async def ingest_signals(body: IngestRequest, request: Request, db: DB,
                         principal: Annotated[Principal, Depends(require(Perm.INGEST))]) -> IngestResult:
    regions = {r.id: r for r in (await db.scalars(select(Region))).all()}
    diseases = set((await db.scalars(select(Disease.code))).all())
    scope = principal.scope_state
    payload = json.dumps([r.model_dump(mode="json") for r in body.records], sort_keys=True).encode()
    batch = IngestionBatch(source=body.source, source_uri=body.source_uri, pipeline="api",
                           pipeline_run_id=body.pipeline_run_id, checksum_sha256=hashlib.sha256(payload).hexdigest(),
                           submitted_by=principal.user.email, status="processing")
    db.add(batch)
    await db.flush()

    errors: list[str] = []
    accepted = 0
    for i, rec in enumerate(body.records):
        region = regions.get(rec.region_id)
        if region is None or rec.disease_code not in diseases:
            errors.append(f"record {i}: unknown region or disease")
            continue
        if scope and region.state != scope:
            errors.append(f"record {i}: region {rec.region_id} outside submitter jurisdiction")
            continue
        if rec.observed_on > date.today() + timedelta(days=1):
            errors.append(f"record {i}: observed_on is in the future")
            continue
        existing = await db.scalar(select(DailySignal).where(
            DailySignal.observed_on == rec.observed_on, DailySignal.region_id == rec.region_id,
            DailySignal.disease_code == rec.disease_code))
        values = {c: getattr(rec, c) for c in SIGNAL_COLUMNS if getattr(rec, c) is not None}
        if existing is None:
            db.add(DailySignal(observed_on=rec.observed_on, region_id=rec.region_id, disease_code=rec.disease_code,
                               batch_id=batch.id, **values))
        else:  # partial update: each feed only supplies its own metric
            for k, v in values.items():
                setattr(existing, k, v)
            existing.batch_id = batch.id
        accepted += 1
    batch.record_count, batch.rejected_count = accepted, len(errors)
    batch.status = "completed" if accepted else "rejected"
    batch.details = {"errors": errors[:100]}
    request.state.audit_resource = f"ingestion_batch:{batch.id}"
    await db.commit()
    return IngestResult(batch_id=batch.id, accepted=accepted, rejected=len(errors), errors=errors[:100])


@router.get("/surveillance/signals", response_model=list[SignalOut])
async def query_signals(
    db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_SURVEILLANCE))],
    disease: str, region_id: str | None = None, state: str | None = None,
    start: date | None = None, end: date | None = None, limit: int = Query(5000, le=50_000),
):
    st = principal.effective_state(state)
    stmt = select(DailySignal).join(Region, Region.id == DailySignal.region_id).where(DailySignal.disease_code == disease)
    if region_id:
        stmt = stmt.where(DailySignal.region_id == region_id)
    if st:
        stmt = stmt.where(Region.state == st)
    if start:
        stmt = stmt.where(DailySignal.observed_on >= start)
    if end:
        stmt = stmt.where(DailySignal.observed_on <= end)
    return (await db.scalars(stmt.order_by(DailySignal.observed_on, DailySignal.region_id).limit(limit))).all()


@router.post("/surveillance/cases", status_code=201, summary="Submit de-identified case reports")
async def submit_cases(cases: list[CaseReportIn], request: Request, db: DB,
                       principal: Annotated[Principal, Depends(require(Perm.INGEST))]) -> dict:
    if len(cases) > 10_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "max 10,000 cases per request")
    regions = {r.id: r.state for r in (await db.scalars(select(Region))).all()}
    scope = principal.scope_state
    bad = [i for i, c in enumerate(cases) if c.region_id not in regions or (scope and regions[c.region_id] != scope)]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid or out-of-scope region in records {bad[:20]}")
    batch = IngestionBatch(source="case_reports", pipeline="api", record_count=len(cases),
                           submitted_by=principal.user.email)
    db.add(batch)
    await db.flush()
    db.add_all([CaseReport(**c.model_dump(), batch_id=batch.id) for c in cases])
    request.state.audit_resource = f"ingestion_batch:{batch.id}"
    await db.commit()
    return {"batch_id": str(batch.id), "accepted": len(cases)}


@router.get("/lineage/batches", response_model=list[LineageOut], tags=["lineage"])
async def list_batches(db: DB, _: Annotated[Principal, Depends(require(Perm.READ_AUDIT))],
                       source: str | None = None, limit: int = Query(100, le=1000)):
    stmt = select(IngestionBatch).order_by(IngestionBatch.received_at.desc()).limit(limit)
    if source:
        stmt = stmt.where(IngestionBatch.source == source)
    return (await db.scalars(stmt)).all()


@router.get("/lineage/signal", response_model=LineageOut, tags=["lineage"],
            summary="Trace a daily signal value back to the batch (and source system) that produced it")
async def signal_lineage(db: DB, _: Annotated[Principal, Depends(require(Perm.READ_SURVEILLANCE))],
                         disease: str, region_id: str, observed_on: date):
    sig = await db.scalar(select(DailySignal).where(DailySignal.disease_code == disease,
                                                    DailySignal.region_id == region_id,
                                                    DailySignal.observed_on == observed_on))
    if sig is None or sig.batch_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no lineage for that signal")
    return await db.get(IngestionBatch, sig.batch_id)
