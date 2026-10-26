"""Password hashing, JWT handling and field-level encryption."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.config import get_settings

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 64}


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = hashed.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), **_SCRYPT)
    return hmac.compare_digest(digest, base64.b64decode(digest_b64))


def create_access_token(subject: str, role: str, jurisdiction: str | None) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = s.access_token_ttl_minutes * 60
    claims = {
        "sub": subject,
        "role": role,
        "jur": jurisdiction,
        "iss": s.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm), ttl


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], issuer=s.jwt_issuer)


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().field_encryption_key
    if not key:
        # Local/test only: derive a stable key from the JWT secret so data stays readable across restarts.
        key = base64.urlsafe_b64encode(hashlib.sha256(get_settings().jwt_secret.encode()).digest()).decode()
    return Fernet(key.encode())


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - indicates key rotation problem
        raise ValueError("unable to decrypt protected field") from exc


class EncryptedString(TypeDecorator):
    """Column type that transparently encrypts values (AES-128-CBC + HMAC via Fernet).

    Used for direct identifiers (e.g. pseudonymous patient references) on top of
    RDS storage encryption, so a database dump alone never exposes them.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt_value(str(value))

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt_value(value)
