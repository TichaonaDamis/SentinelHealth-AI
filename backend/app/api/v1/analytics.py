from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, Principal, require
from app.core.rbac import Perm
from app.models import OutbreakEvent, Region
from app.schemas import ForecastOut, HotspotOut, OutbreakEventOut, RiskAssessmentOut, ScanRequest, ScanResult
from app.services import analytics, forecasting

router = APIRouter(tags=["analytics"])


@router.get("/analytics/risk", response_model=list[RiskAssessmentOut],
            summary="Current risk assessment for every region/disease (no side effects)")
async def current_risk(db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_ANALYTICS))],
                       disease: str | None = None, state: str | None = None, as_of: date | None = None,
                       min_level: Literal["green", "yellow", "orange", "red"] = "green"):
    out = await analytics.assess(db, as_of, [disease] if disease else None, principal.effective_state(state))
    order = ["green", "yellow", "orange", "red"]
    return [a for a in out if order.index(a.risk_level) >= order.index(min_level)]


@router.post("/analytics/scan", response_model=ScanResult,
             summary="Run anomaly detection + outbreak classification, persist events and raise alerts")
async def run_scan(body: ScanRequest, db: DB, principal: Annotated[Principal, Depends(require(Perm.RUN_ANALYTICS))]):
    assessments, created = await analytics.scan_and_alert(
        db, body.as_of, body.diseases, principal.scope_state, notify=body.notify)
    if not assessments:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no surveillance data for the requested scope/date")
    return ScanResult(as_of=assessments[0].as_of, evaluated=len(assessments),
                      signals=sum(a.risk_level != "green" for a in assessments), alerts_created=created,
                      assessments=assessments[:200])


@router.get("/analytics/outbreaks", response_model=list[OutbreakEventOut])
async def list_outbreaks(db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_ANALYTICS))],
                         disease: str | None = None, state: str | None = None, since: date | None = None,
                         limit: int = Query(200, le=2000)):
    st = principal.effective_state(state)
    stmt = select(OutbreakEvent).join(Region, Region.id == OutbreakEvent.region_id)
    if disease:
        stmt = stmt.where(OutbreakEvent.disease_code == disease)
    if st:
        stmt = stmt.where(Region.state == st)
    if since:
        stmt = stmt.where(OutbreakEvent.detected_on >= since)
    return (await db.scalars(stmt.order_by(OutbreakEvent.created_at.desc()).limit(limit))).all()


@router.get("/analytics/hotspots", response_model=list[HotspotOut], summary="Spatial clusters (DBSCAN/HDBSCAN)")
async def get_hotspots(db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_LINELIST))],
                       disease: str, state: str | None = None,
                       method: Literal["hdbscan", "dbscan"] = "hdbscan",
                       window_days: int = Query(21, ge=7, le=90), min_samples: int = Query(15, ge=5, le=500)):
    return await analytics.hotspots(db, disease, window_days=window_days, state=principal.effective_state(state),
                                    method=method, min_samples=min_samples)


@router.get("/forecasts/{disease}/{region_id}", response_model=ForecastOut,
            summary="7/14/30-day forecast with hospitalization, mortality and outbreak risk")
async def get_forecast(disease: str, region_id: str, db: DB,
                       principal: Annotated[Principal, Depends(require(Perm.READ_ANALYTICS))],
                       as_of: date | None = None, persist: bool = True):
    region = await db.get(Region, region_id)
    if region is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown region")
    principal.effective_state(region.state)
    try:
        return await forecasting.forecast_series(db, disease, region_id, as_of, persist=persist)
    except forecasting.InsufficientHistory as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
