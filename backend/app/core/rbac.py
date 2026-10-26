"""Role-based access control.

Roles map to coarse permissions; jurisdiction (a state code) further scopes
data access for state- and partner-level users. Admins and federal analysts
have national scope.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    EPIDEMIOLOGIST = "epidemiologist"
    CDC_ANALYST = "cdc_analyst"
    STATE_HEALTH_OFFICER = "state_health_officer"
    HEALTHCARE_PARTNER = "healthcare_partner"
    VIEWER = "viewer"


class Perm(StrEnum):
    READ_DASHBOARD = "dashboard:read"
    READ_SURVEILLANCE = "surveillance:read"
    INGEST = "surveillance:ingest"
    READ_LINELIST = "linelist:read"
    RUN_ANALYTICS = "analytics:run"
    READ_ANALYTICS = "analytics:read"
    READ_ALERTS = "alerts:read"
    MANAGE_ALERTS = "alerts:manage"
    USE_COPILOT = "copilot:use"
    MANAGE_KNOWLEDGE = "copilot:manage"
    READ_AUDIT = "audit:read"
    MANAGE_USERS = "users:manage"


_ANALYST = {
    Perm.READ_DASHBOARD, Perm.READ_SURVEILLANCE, Perm.READ_LINELIST, Perm.RUN_ANALYTICS, Perm.READ_ANALYTICS,
    Perm.READ_ALERTS, Perm.MANAGE_ALERTS, Perm.USE_COPILOT,
}

ROLE_PERMISSIONS: dict[Role, frozenset[Perm]] = {
    Role.ADMIN: frozenset(Perm),
    Role.EPIDEMIOLOGIST: frozenset(_ANALYST | {Perm.MANAGE_KNOWLEDGE}),
    Role.CDC_ANALYST: frozenset(_ANALYST),
    Role.STATE_HEALTH_OFFICER: frozenset(_ANALYST - {Perm.READ_LINELIST}),
    Role.HEALTHCARE_PARTNER: frozenset({Perm.INGEST, Perm.READ_ALERTS, Perm.READ_DASHBOARD}),
    Role.VIEWER: frozenset({Perm.READ_DASHBOARD}),
}

NATIONAL_ROLES = {Role.ADMIN, Role.CDC_ANALYST}


def has_permission(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False


def jurisdiction_filter(role: str, jurisdiction: str | None) -> str | None:
    """State code the user is restricted to, or ``None`` for national scope."""
    if Role(role) in NATIONAL_ROLES:
        return None
    return jurisdiction
