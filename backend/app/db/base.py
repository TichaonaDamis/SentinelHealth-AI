from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator

# BIGSERIAL on PostgreSQL, INTEGER PRIMARY KEY (rowid alias) on SQLite for tests.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


class Vector(TypeDecorator):
    """pgvector column on PostgreSQL, JSON list elsewhere (tests, local SQLite)."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector as PGVector

            return dialect.type_descriptor(PGVector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class Base(DeclarativeBase):
    pass
