"""
Async SQLAlchemy engine, session factory, and base declarative model.
"""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.config import settings

_raw_url = settings.database_url

# asyncpg uses ssl=True connect_arg — strip sslmode from URL to avoid TypeError
_needs_ssl = "sslmode=require" in _raw_url
_db_url = (
    _raw_url
    .replace("postgresql://", "postgresql+asyncpg://")
    .replace("postgres://", "postgresql+asyncpg://")
    .replace("?sslmode=require", "")
    .replace("&sslmode=require", "")
    .replace("sslmode=require&", "")
)

# SQLite (used in tests) doesn't support connection pool args
_is_sqlite = _db_url.startswith("sqlite")
_engine_kwargs: dict = {} if _is_sqlite else {
    "pool_size": settings.db_pool_size,
    "max_overflow": settings.db_max_overflow,
    "pool_timeout": settings.db_pool_timeout,
    "pool_pre_ping": True,
    "pool_recycle": settings.db_pool_recycle_seconds,
}
if _needs_ssl:
    _engine_kwargs["connect_args"] = {"ssl": True}

engine = create_async_engine(
    _db_url,
    echo=settings.debug,
    future=True,
    **_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class shared by all ORM models."""
    pass


async def create_tables() -> None:
    """Create all tables defined in ORM models (used at startup / for tests)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables() -> None:
    """Drop all tables — only call this in test teardown."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a database session and handles rollback."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a database session.

    Usage::

        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_db_session() as session:
        yield session
