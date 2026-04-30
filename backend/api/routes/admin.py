"""Admin-only user management and system health routes."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_admin_user
from backend.config import settings
from backend.db.database import AsyncSessionLocal, get_db
from backend.models.user import UserORM, UserRead

log = structlog.get_logger(__name__)
router = APIRouter()


# ── Health check models ───────────────────────────────────────────────────────

class ServiceHealth(BaseModel):
    name: str
    label: str
    status: Literal["ok", "error", "unknown"]
    latency_ms: Optional[int] = None
    detail: Optional[str] = None


class HealthReport(BaseModel):
    services: list[ServiceHealth]
    checked_at: str


# ── Individual probes (each times out after 10 s) ─────────────────────────────

async def _probe_postgres() -> ServiceHealth:
    t = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=10)
        return ServiceHealth(name="postgres", label="Neon / PostgreSQL",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        return ServiceHealth(name="postgres", label="Neon / PostgreSQL",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=str(exc)[:200])


async def _probe_anthropic() -> ServiceHealth:
    t = time.monotonic()
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        async def _call():
            return await client.messages.count_tokens(
                model=settings.claude_haiku_model,
                messages=[{"role": "user", "content": "ping"}],
            )
        await asyncio.wait_for(_call(), timeout=10)
        return ServiceHealth(name="anthropic", label="Anthropic API",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        return ServiceHealth(name="anthropic", label="Anthropic API",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=str(exc)[:200])


async def _probe_tavily() -> ServiceHealth:
    t = time.monotonic()
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.tavily_api_key)
        loop = asyncio.get_event_loop()
        await asyncio.wait_for(
            loop.run_in_executor(None, lambda: client.search("test", max_results=1)),
            timeout=10,
        )
        return ServiceHealth(name="tavily", label="Tavily Search",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        return ServiceHealth(name="tavily", label="Tavily Search",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=str(exc)[:200])


async def _probe_newsapi() -> ServiceHealth:
    t = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{settings.news_api_base_url}/top-headlines",
                params={"country": "us", "pageSize": 1, "apiKey": settings.news_api_key},
            )
            r.raise_for_status()
        return ServiceHealth(name="newsapi", label="NewsAPI",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        return ServiceHealth(name="newsapi", label="NewsAPI",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=str(exc)[:200])


async def _probe_alpha_vantage() -> ServiceHealth:
    t = time.monotonic()
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                settings.alpha_vantage_base_url,
                params={"function": "SYMBOL_SEARCH", "keywords": "AAPL",
                        "apikey": settings.alpha_vantage_api_key},
            )
            r.raise_for_status()
            data = r.json()
            if "Information" in data:
                raise ValueError(data["Information"])
        return ServiceHealth(name="alpha_vantage", label="Alpha Vantage",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        return ServiceHealth(name="alpha_vantage", label="Alpha Vantage",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=str(exc)[:200])


async def _probe_s3() -> ServiceHealth:
    t = time.monotonic()
    try:
        import boto3
        from botocore.exceptions import ClientError
        loop = asyncio.get_event_loop()

        def _check():
            s3 = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
                **({"endpoint_url": settings.s3_endpoint_url} if settings.s3_endpoint_url else {}),
            )
            s3.head_bucket(Bucket=settings.s3_bucket_scripts)

        await asyncio.wait_for(loop.run_in_executor(None, _check), timeout=10)
        return ServiceHealth(name="s3", label="AWS S3",
                             status="ok", latency_ms=int((time.monotonic() - t) * 1000))
    except Exception as exc:
        detail = str(exc)[:200]
        # Missing credentials in local dev is expected — treat as unknown, not error
        if not settings.aws_access_key_id or settings.aws_access_key_id == "test":
            return ServiceHealth(name="s3", label="AWS S3", status="unknown",
                                 detail="Not configured (local dev)")
        return ServiceHealth(name="s3", label="AWS S3",
                             status="error", latency_ms=int((time.monotonic() - t) * 1000),
                             detail=detail)


# ── Health endpoint ───────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthReport)
async def api_health(
    _admin: UserORM = Depends(get_admin_user),
) -> HealthReport:
    """Run all external-service probes in parallel and return a health report."""
    probes = [
        _probe_postgres(),
        _probe_anthropic(),
        _probe_tavily(),
        _probe_newsapi(),
        _probe_alpha_vantage(),
        _probe_s3(),
    ]
    results: list[ServiceHealth] = list(await asyncio.gather(*probes))
    log.info("admin.health_check", statuses={r.name: r.status for r in results})
    return HealthReport(
        services=results,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AdminCreateUser(BaseModel):
    email: str
    password: str


@router.get("/users", response_model=list[UserRead])
async def list_users(
    _admin: UserORM = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserORM]:
    result = await db.execute(select(UserORM).order_by(UserORM.created_at))
    return list(result.scalars().all())


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: AdminCreateUser,
    admin: UserORM = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> UserORM:
    result = await db.execute(
        select(UserORM).where(UserORM.email == payload.email.lower().strip())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )
    user = UserORM(
        id=uuid.uuid4(),
        email=payload.email.lower().strip(),
        hashed_password=_pwd.hash(payload.password),
        must_change_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("admin.user_created", admin_id=str(admin.id), new_user=user.email)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    admin: UserORM = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    result = await db.execute(select(UserORM).where(UserORM.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete your own account")
    await db.delete(user)
    await db.commit()
    log.info("admin.user_deleted", admin_id=str(admin.id), deleted_user=user.email)
