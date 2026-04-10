"""
Shared pytest fixtures for the AI Journalist test suite.

Uses an in-memory SQLite database (via aiosqlite) so tests have no external
dependencies.  All Pydantic settings are patched via environment variables
before any backend imports that trigger Settings() instantiation.
"""

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Patch env vars before any backend module is imported ─────────────────────
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("TAVILY_API_KEY", "test-tavily-key")
os.environ.setdefault("NEWS_API_KEY", "test-news-key")
os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "test-av-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-tests-only")

# ── Now it's safe to import backend modules ───────────────────────────────────
from backend.api.deps import get_current_user
from backend.db.database import Base, get_db
from backend.models.user import UserORM
from backend.models.story import StoryORM  # noqa: F401 — registers table with metadata


# ── In-memory async SQLite engine ─────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a fresh in-memory SQLite engine for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """Yield an AsyncSession bound to the in-memory test database."""
    factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="function")
async def api_client(db_session):
    """
    Async HTTPX client wired to the FastAPI app with DB dependency overridden
    to use the in-memory test session.
    """
    from backend.api.main import create_app

    app = create_app()

    test_user = UserORM(
        email="test@example.com",
        hashed_password="not-a-real-hash",
        is_active=True,
    )

    async def _override_get_db():
        yield db_session

    async def _override_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_get_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ── Common data fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def sample_story_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_topic() -> str:
    return "How NVIDIA became the world's most valuable chip company"
