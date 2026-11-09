"""Async SQLAlchemy engine, session factory and FastAPI dependency."""

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import BACKEND_ROOT, get_settings


class Base(DeclarativeBase):
    """Common declarative base for all ORM models."""


def _resolve_sqlite_url(url: str) -> str:
    """Anchor *relative* SQLite paths to backend/ so the DB file never depends
    on the process working directory (tests pass absolute paths → untouched)."""
    if not url.startswith("sqlite"):
        return url
    prefix, sep, path = url.partition("///")
    if not sep or not path or path in (":memory:",) or path.startswith("file:"):
        return url
    p = Path(path)
    if p.is_absolute():
        return url
    return f"{prefix}///{(BACKEND_ROOT / p).resolve().as_posix()}"


settings = get_settings()

# SQLite needs a busy timeout so the background clustering task can wait for
# the request connection to release its write lock (dev/test only).
database_url = _resolve_sqlite_url(settings.database_url)
_connect_args: dict = {}
if database_url.startswith("sqlite"):
    _connect_args = {"timeout": 30}

engine = create_async_engine(
    database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a request-scoped database session."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create tables via SQLAlchemy metadata (SQLite tests / bootstrap).

    Production PostgreSQL should be initialised from app/db/schema.sql
    (which also enables PostGIS and creates enum types + spatial indexes).
    """
    from app import models  # noqa: F401  (register all ORM models)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
