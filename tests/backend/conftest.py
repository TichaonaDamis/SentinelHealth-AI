import os
import tempfile
from datetime import date

import pytest

_tmp = tempfile.mkdtemp(prefix="sentinel-test-")
os.environ.update({
    "SENTINEL_ENVIRONMENT": "test",
    "SENTINEL_DATABASE_URL": f"sqlite+aiosqlite:///{_tmp}/test.db",
    "SENTINEL_JWT_SECRET": "test-secret-with-enough-length-0123456789",
    "SENTINEL_COPILOT_PROVIDER": "offline",
    "SENTINEL_ANTHROPIC_API_KEY": "",
    "SENTINEL_OPENAI_API_KEY": "",
})

import httpx  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.seed import seed  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.main import create_app  # noqa: E402

AS_OF = date(2026, 3, 31)
PASSWORD = "ChangeMe!2026"


@pytest.fixture(scope="session")
async def app():
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as db:
        await seed(db, days=200, end=AS_OF, regions=10, diseases=["INFLUENZA", "CLI", "MEASLES"],
                   max_cases=4000, line_list_days=60)
    yield create_app()


@pytest.fixture(scope="session")
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _token(client, email: str) -> dict:
    r = await client.post("/api/v1/auth/token", data={"username": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
async def admin(client):
    return await _token(client, "admin@sentinelhealth.dev")


@pytest.fixture(scope="session")
async def epi(client):
    return await _token(client, "epi@sentinelhealth.dev")


@pytest.fixture(scope="session")
async def tx_officer(client):
    return await _token(client, "tx.officer@sentinelhealth.dev")


@pytest.fixture(scope="session")
async def partner(client):
    return await _token(client, "partner@sentinelhealth.dev")


@pytest.fixture(scope="session")
async def viewer(client):
    return await _token(client, "viewer@sentinelhealth.dev")
