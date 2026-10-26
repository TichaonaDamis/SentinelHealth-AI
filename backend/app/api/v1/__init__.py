from fastapi import APIRouter

from app.api.v1 import admin, alerts, analytics, auth, copilot, dashboard, surveillance

api_router = APIRouter()
for module in (auth, surveillance, analytics, alerts, dashboard, copilot, admin):
    api_router.include_router(module.router)
