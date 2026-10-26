"""Audit logging: every API request and every sensitive data access is recorded.

The middleware records who did what, when, from where and with what result.
Records are written to the ``audit_logs`` table (append-only DB grants) and
mirrored as structured JSON log lines to CloudWatch, where a subscription
filter ships them to the immutable S3 audit bucket (Object Lock).
"""

from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.security import decode_access_token
from app.db.session import get_sessionmaker
from app.models import AuditLog

log = logging.getLogger("sentinel.audit")
SKIP_PATHS = {"/health", "/ready", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


async def write_audit(**fields) -> None:
    log.info(json.dumps({"type": "audit", **{k: v for k, v in fields.items() if v is not None}}, default=str))
    try:
        async with get_sessionmaker()() as session:
            session.add(AuditLog(**fields))
            await session.commit()
    except Exception:  # never fail a request because the audit DB is unavailable; CloudWatch copy remains
        log.exception("failed to persist audit record")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        if request.url.path in SKIP_PATHS or request.method == "OPTIONS":
            return response

        user_id = email = role = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                claims = decode_access_token(auth[7:])
                user_id, role = claims.get("sub"), claims.get("role")
            except Exception:  # invalid token: request is rejected by the endpoint; audit as anonymous
                log.debug("audit: could not decode bearer token")
        email = getattr(request.state, "user_email", None)
        await write_audit(
            request_id=request_id, user_id=user_id, user_email=email, role=role,
            action=getattr(request.state, "audit_action", f"{request.method.lower()}:{request.url.path}"),
            resource=getattr(request.state, "audit_resource", None),
            method=request.method, path=request.url.path[:500], status_code=response.status_code,
            ip_address=_client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:300],
            details={"duration_ms": round((time.perf_counter() - start) * 1000, 1),
                     "query": str(request.url.query)[:500] or None},
        )
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("strict-transport-security", "max-age=63072000; includeSubDomains; preload")
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("x-frame-options", "DENY")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("cache-control", "no-store")
        return response
