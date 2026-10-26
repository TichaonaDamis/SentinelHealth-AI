from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DB, CurrentPrincipal, Principal, require
from app.core.rbac import Perm
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import utcnow
from app.models import User
from app.schemas import Token, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token, summary="OAuth2 password grant")
async def login(request: Request, db: DB, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    user = await db.scalar(select(User).where(User.email == form.username.lower()))
    request.state.user_email = form.username.lower()
    if user is None or not user.is_active or not verify_password(form.password, user.hashed_password):
        request.state.audit_action = "auth:login_failed"
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "incorrect email or password")
    request.state.audit_action = "auth:login"
    user.last_login_at = utcnow()
    await db.commit()
    token, ttl = create_access_token(str(user.id), user.role, user.jurisdiction)
    return Token(access_token=token, expires_in=ttl)


@router.get("/me", response_model=UserOut)
async def me(principal: CurrentPrincipal) -> User:
    return principal.user


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, db: DB,
                      _: Annotated[Principal, Depends(require(Perm.MANAGE_USERS))]) -> User:
    if await db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "user already exists")
    user = User(email=body.email.lower(), full_name=body.full_name, hashed_password=hash_password(body.password),
                role=body.role, jurisdiction=body.jurisdiction.upper() if body.jurisdiction else None,
                organization=body.organization)
    db.add(user)
    await db.commit()
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(db: DB, _: Annotated[Principal, Depends(require(Perm.MANAGE_USERS))]) -> list[User]:
    return list((await db.scalars(select(User).order_by(User.email))).all())
