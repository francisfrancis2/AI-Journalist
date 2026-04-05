"""
FastAPI application factory and lifecycle management.
"""

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse

from backend.api.routes import research as research_router
from backend.api.routes import stories as stories_router
from backend.config import settings
from backend.db.database import create_tables

log = structlog.get_logger(__name__)


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
        docs_url="/docs",
        redoc_url="/redoc",
        default_response_class=ORJSONResponse,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Startup / Shutdown ────────────────────────────────────────────────────
    @app.on_event("startup")
    async def on_startup() -> None:
        log.info("app.startup", version=settings.app_version)
        await create_tables()
        log.info("app.database_ready")

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        log.info("app.shutdown")

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health_check() -> dict:
        return {"status": "ok", "version": settings.app_version}

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(stories_router.router, prefix="/api/v1/stories", tags=["Stories"])
    app.include_router(research_router.router, prefix="/api/v1/research", tags=["Research"])

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
