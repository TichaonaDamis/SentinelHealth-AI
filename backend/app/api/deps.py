from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Perm, has_permission, jurisdiction_filter
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class Principal:
    user: User

    @property
    def role(self) -> str:
        return self.user.role

    @property
    def scope_state(self) -> str | None:
        """State the user is restricted to (``None`` = national)."""
        return jurisdiction_filter(self.user.role, self.user.jurisdiction)

    def effective_state(self, requested: str | None) -> str | None:
        """Combine a requested state filter with the user's jurisdiction; reject out-of-scope requests."""
        scope = self.scope_state
        if scope and requested and requested.upper() != scope:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "outside your jurisdiction")
        return scope or (requested.upper() if requested else None)


async def get_principal(request: Request, db: DB, token: Annotated[str, Depends(oauth2_scheme)]) -> Principal:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token",
                                 headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(token)
        user = await db.get(User, uuid.UUID(claims["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized from None
    if user is None or not user.is_active:
        raise unauthorized
    request.state.user_email = user.email
    return Principal(user)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require(perm: Perm):
    async def checker(request: Request, principal: CurrentPrincipal) -> Principal:
        if not has_permission(principal.role, perm):
            request.state.audit_action = f"denied:{perm.value}"
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"missing permission {perm.value}")
        request.state.audit_action = perm.value
        return principal

    return checker
