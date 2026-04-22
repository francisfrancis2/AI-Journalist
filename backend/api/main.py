"""
FastAPI application factory and lifecycle management.
"""

import asyncio
import uuid
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import ORJSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.routes import admin as admin_router
from backend.api.routes import auth as auth_router
from backend.api.routes import benchmarks as benchmarks_router
from backend.api.routes import research as research_router
from backend.api.routes import stories as stories_router
from backend.config import settings
from backend.db.database import AsyncSessionLocal, create_tables
from backend.models import benchmark as _benchmark_models  # noqa: F401 — registers BIReferenceDocORM, BIPatternLibraryORM
from backend.models import user as _user_models  # noqa: F401 — ensures UserORM is registered with Base
from backend.models.benchmark import BIReferenceDocORM
from backend.models.user import UserORM

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

def _is_sqlite_url() -> bool:
    return settings.database_url.startswith("sqlite")


async def _run_database_migrations() -> None:
    """Apply Alembic migrations on real databases; use create_all only for SQLite tests."""
    if not settings.run_migrations_on_startup:
        log.info("app.migrations_skipped", reason="disabled")
        return

    if _is_sqlite_url():
        await create_tables()
        return

    # Run alembic in a subprocess to avoid import-lock deadlock with asyncio event loop
    root = Path(__file__).resolve().parents[2]
    proc = await asyncio.create_subprocess_exec(
        "python", "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head",
        cwd=str(root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    if stdout:
        for line in stdout.decode().splitlines():
            log.info("alembic", msg=line)
    if proc.returncode != 0:
        raise RuntimeError(f"Alembic migration failed (exit {proc.returncode})")


async def _seed_admin() -> None:
    """Create the configured admin account without hard-coded credentials."""
    if not settings.admin_email or not settings.admin_password:
        log.warning("auth.admin_seed_skipped", reason="ADMIN_EMAIL/ADMIN_PASSWORD not configured")
        return

    admin_email = settings.admin_email.lower().strip()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(UserORM).where(UserORM.email == admin_email)
        )
        existing = result.scalar_one_or_none()
        if existing:
            if not existing.is_admin:
                existing.is_admin = True
                await session.commit()
                log.info("auth.admin_promoted", email=admin_email)
            else:
                log.info("auth.admin_exists", email=admin_email)
            return
        admin = UserORM(
            id=uuid.uuid4(),
            email=admin_email,
            hashed_password=_pwd.hash(settings.admin_password),
            is_admin=True,
            must_change_password=False,
        )
        session.add(admin)
        await session.commit()
        log.info("auth.admin_seeded", email=admin_email)

log = structlog.get_logger(__name__)


class _SelectiveTrustedHostMiddleware:
    """TrustedHostMiddleware that bypasses the host check for /health.

    Fly.io's internal health prober sends the machine's IPv6 address as the
    Host header (e.g. fdaa:6d:97e7:a7b:…), which Starlette's built-in
    TrustedHostMiddleware rejects with 400.  The /health path carries no
    sensitive data, so skipping the check there is safe.
    """

    _BYPASS_PATHS = frozenset({"/health", "/healthz", "/ready"})

    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self._inner = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") == "http" and scope.get("path") in self._BYPASS_PATHS:
            await self._app(scope, receive, send)
        else:
            await self._inner(scope, receive, send)


async def _seed_benchmark_corpus_if_empty() -> None:
    """On first deployment, kick off a background corpus rebuild if no docs exist."""
    if not settings.youtube_api_key:
        log.warning("benchmarking.seed_skipped", reason="YOUTUBE_API_KEY not configured")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BIReferenceDocORM).limit(1))
        if result.scalar_one_or_none() is not None:
            log.info("benchmarking.seed_skipped", reason="corpus already has documents")
            return

    log.info("benchmarking.seed_starting", reason="no corpus docs found on startup")
    from backend.services.benchmarking import run_benchmark_rebuild
    asyncio.create_task(
        run_benchmark_rebuild(
            library_key="combined",
            max_docs=settings.benchmark_default_rebuild_docs,
        )
    )


def create_app() -> FastAPI:
    """
    Construct and configure the FastAPI application instance.

    Returns:
        Configured FastAPI app ready to be served by Uvicorn.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI Journalist — autonomous documentary research and scriptwriting pipeline "
            "powered by LangGraph multi-agent orchestration and Claude."
        ),
        # Disable interactive docs in production to reduce attack surface
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        default_response_class=ORJSONResponse,
    )

    # ── Trusted host guard (reject requests with unexpected Host headers) ─────
    # Uses _SelectiveTrustedHostMiddleware to bypass the check for /health,
    # where Fly.io's internal prober sends the machine's IPv6 as Host header.
    app.add_middleware(
        _SelectiveTrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
    )

    # ── CORS — only the frontend origin is allowed ────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Strip server fingerprinting headers ───────────────────────────────────
    @app.middleware("http")
    async def remove_server_header(request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.__delitem__("server") if "server" in response.headers else None
        response.headers.__delitem__("x-powered-by") if "x-powered-by" in response.headers else None
        return response

    # ── Startup / Shutdown ────────────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup() -> None:
        log.info("app.startup", version=settings.app_version)
        await _run_database_migrations()
        await _seed_admin()
        log.info("app.database_ready")
        await _seed_benchmark_corpus_if_empty()

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        log.info("app.shutdown")

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health_check() -> dict:
        return {"status": "ok", "version": settings.app_version}

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(auth_router.router, prefix="/api/v1/auth", tags=["Auth"])
    app.include_router(
        admin_router.router,
        prefix="/api/v1/admin",
        tags=["Admin"],
    )
    app.include_router(
        stories_router.router,
        prefix="/api/v1/stories",
        tags=["Stories"],
        dependencies=[Depends(get_current_user)],
    )
    app.include_router(
        research_router.router,
        prefix="/api/v1/research",
        tags=["Research"],
        dependencies=[Depends(get_current_user)],
    )
    app.include_router(
        benchmarks_router.router,
        prefix="/api/v1/benchmarks",
        tags=["Benchmarks"],
        dependencies=[Depends(get_current_user)],
    )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
