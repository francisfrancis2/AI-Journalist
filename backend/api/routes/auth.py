"""
Auth routes — register, login, and current-user endpoints.
"""

import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.config import settings
from backend.db.database import get_db
from backend.models.user import LoginRequest, Token, UserCreate, UserORM, UserRead

log = structlog.get_logger(__name__)
router = APIRouter()

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _hash(password: str) -> str:
    return _pwd.hash(password)


def _verify(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def _make_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)) -> Token:
    """Create a new account and return a JWT."""
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
        hashed_password=_hash(payload.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log.info("auth.registered", user_id=str(user.id))
    return Token(access_token=_make_token(str(user.id)))


@router.post("/login", response_model=Token)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> Token:
    """Authenticate with email + password and return a JWT."""
    result = await db.execute(
        select(UserORM).where(UserORM.email == payload.email.lower().strip())
    )
    user = result.scalar_one_or_none()

    if not user or not _verify(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )

    log.info("auth.login", user_id=str(user.id))
    return Token(access_token=_make_token(str(user.id)))


@router.get("/me", response_model=UserRead)
async def me(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    """Return the currently authenticated user."""
    return current_user
