import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, Principal, require
from app.core.rbac import Perm
from app.db.base import utcnow
from app.models import Alert, Region
from app.schemas import AlertOut, AlertUpdate

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
async def list_alerts(db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_ALERTS))],
                      status_: Annotated[Literal["open", "acknowledged", "resolved", "dismissed"] | None,
                                         Query(alias="status")] = None,
                      level: Literal["yellow", "orange", "red"] | None = None, disease: str | None = None,
                      state: str | None = None, limit: int = Query(100, le=1000)):
    st = principal.effective_state(state)
    stmt = select(Alert).join(Region, Region.id == Alert.region_id)
    if status_:
        stmt = stmt.where(Alert.status == status_)
    if level:
        stmt = stmt.where(Alert.risk_level == level)
    if disease:
        stmt = stmt.where(Alert.disease_code == disease)
    if st:
        stmt = stmt.where(Region.state == st)
    return (await db.scalars(stmt.order_by(Alert.created_at.desc()).limit(limit))).all()


@router.patch("/{alert_id}", response_model=AlertOut)
async def update_alert(alert_id: uuid.UUID, body: AlertUpdate, request: Request, db: DB,
                       principal: Annotated[Principal, Depends(require(Perm.MANAGE_ALERTS))]):
    alert = await db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "alert not found")
    region = await db.get(Region, alert.region_id)
    principal.effective_state(region.state)
    alert.status = body.status
    if body.status == "acknowledged":
        alert.acknowledged_by, alert.acknowledged_at = principal.user.email, utcnow()
    if body.note:
        alert.resolution_note = body.note
    request.state.audit_resource = f"alert:{alert_id}"
    await db.commit()
    return alert
