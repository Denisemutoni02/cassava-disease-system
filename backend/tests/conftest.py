"""Pytest configuration.

Environment variables are set BEFORE the app is imported so that Settings
picks up the test database (file-based SQLite), mock classifier and a temp
upload directory. This lets the full API stack run without PostgreSQL.
"""

import io
import os
import sys
import uuid
from pathlib import Path

# --- Environment must be configured before any app import -------------------
TEST_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = TEST_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

_TMP = Path("/tmp/cassava_guard_test")
_TMP.mkdir(parents=True, exist_ok=True)

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{_TMP}/test_{uuid.uuid4().hex[:8]}.db",
        "ENVIRONMENT": "test",
        "FORCE_MOCK_MODEL": "true",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "JWT_SECRET": "test-secret-do-not-use-in-prod",
        "CORS_ORIGINS": "http://localhost:5173",
        "CONFIDENCE_THRESHOLD": "0.60",
    }
)

import numpy as np  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.classifier import reset_classifier_singleton  # noqa: E402


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Create the SQLite schema once per session."""
    import asyncio

    reset_classifier_singleton()
    asyncio.run(init_db())
    yield


@pytest.fixture()
async def db_session():
    """Fresh database session per test (rolled back)."""
    async with SessionLocal() as session:
        yield session
        await session.rollback()


@pytest.fixture()
def client():
    """FastAPI TestClient (runs the ASGI app in-process)."""
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


def _make_image_bytes(width: int = 224, height: int = 224, colour=(34, 139, 34)) -> bytes:
    """Generate a small solid-colour JPEG in memory."""
    img = Image.new("RGB", (width, height), colour)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture()
def leaf_jpeg() -> bytes:
    return _make_image_bytes()


@pytest.fixture()
def register_and_login(client):
    """Factory: register a user and return (headers, user_json)."""

    def _register(role: str = "farmer", name: str | None = None) -> tuple[dict, dict]:
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "full_name": name or f"Test User {suffix}",
            "password": "secret123",
            "phone": f"+2567{uuid.uuid4().int % 10_000_000:07d}",
            "role": role,
        }
        r = client.post("/api/v1/auth/register", json=payload)
        assert r.status_code == 201, r.text
        data = r.json()
        return {"Authorization": f"Bearer {data['access_token']}"}, data["user"]

    return _register
