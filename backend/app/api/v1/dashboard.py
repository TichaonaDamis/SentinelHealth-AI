from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, Principal, require
from app.core.rbac import Perm
from app.schemas import DashboardSummary
from app.services import dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DashboardSummary, summary="Executive dashboard KPIs, trends, map and alerts")
async def get_summary(db: DB, principal: Annotated[Principal, Depends(require(Perm.READ_DASHBOARD))],
                      state: str | None = None, trend_days: int = Query(120, ge=14, le=730)):
    result = await dashboard.summary(db, principal.effective_state(state), trend_days)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no surveillance data loaded")
    return result
