import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import DB, Principal, require
from app.core.config import get_settings
from app.core.rbac import Perm
from app.models import AuditLog
from app.schemas import AuditLogOut
from app.services.ml_runtime import get_runtime

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(db: DB, _: Annotated[Principal, Depends(require(Perm.READ_AUDIT))],
                     user_email: str | None = None, action: str | None = None, since: datetime | None = None,
                     limit: int = Query(200, le=5000)):
    stmt = select(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(limit)
    if user_email:
        stmt = stmt.where(AuditLog.user_email == user_email.lower())
    if action:
        stmt = stmt.where(AuditLog.action.like(f"{action}%"))
    if since:
        stmt = stmt.where(AuditLog.occurred_at >= since)
    return (await db.scalars(stmt)).all()


@router.get("/models", summary="Loaded model artifacts and versions")
async def models(_: Annotated[Principal, Depends(require(Perm.READ_ANALYTICS))]) -> dict:
    rt = get_runtime()
    return {
        "outbreak_classifier": rt.versions.get("outbreak_classifier", "fallback:heuristic"),
        "anomaly_ensemble": rt.versions.get("anomaly_ensemble", "fallback:ears_c2"),
        "forecaster_xgboost": rt.versions.get("forecaster_xgboost", "fallback:seasonal_naive"),
        "forecaster_naive": rt.versions.get("forecaster_naive", "unfitted"),
    }


@router.get("/model-evaluation", summary="Latest model evaluation metrics (confusion matrix, ROC, backtests)")
async def model_evaluation(_: Annotated[Principal, Depends(require(Perm.READ_ANALYTICS))]) -> dict:
    path = get_settings().model_dir / "metrics.json"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no evaluation metrics; run the training pipeline")
    return json.loads(path.read_text())
