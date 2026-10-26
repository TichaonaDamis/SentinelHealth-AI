"""SentinelHealth AI API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import text

from app import __version__
from app.api.v1 import api_router
from app.core.audit import AuditMiddleware, SecurityHeadersMiddleware
from app.core.config import get_settings
from app.db.session import dispose_engine, get_engine
from app.services.ml_runtime import get_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_runtime()  # load model artifacts once, before serving traffic
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Audit records are emitted as bare JSON lines so CloudWatch metric filters / Logs Insights can parse them.
    audit_log = logging.getLogger("sentinel.audit")
    if not audit_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        audit_log.addHandler(handler)
        audit_log.propagate = False
        audit_log.setLevel(logging.INFO)
    app = FastAPI(
        title=s.app_name,
        version=__version__,
        description="AI-powered disease surveillance, outbreak detection and forecasting platform.",
        lifespan=lifespan,
        docs_url=None if s.environment == "prod" else "/docs",
        openapi_url="/openapi.json",
    )
    app.add_middleware(AuditMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.trusted_hosts)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["authorization", "content-type"])
    app.include_router(api_router, prefix=s.api_prefix)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["ops"])
    async def ready() -> dict:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready", "models": get_runtime().versions}

    return app


app = create_app()
