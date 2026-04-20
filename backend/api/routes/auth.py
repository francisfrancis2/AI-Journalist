"""
Auth routes — register, login, and current-user endpoints.
"""

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
from backend.models.user import ChangePasswordRequest, LoginRequest, Token, UserORM, UserRead

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


@router.post("/dismiss-password-change", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_password_change(
    current_user: UserORM = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Allow user to skip the forced password change and continue to the app."""
    current_user.must_change_password = False
    await db.commit()


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: UserORM = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Change the authenticated user's password."""
    if not _verify(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )
    current_user.hashed_password = _hash(payload.new_password)
    current_user.must_change_password = False
    await db.commit()
    log.info("auth.password_changed", user_id=str(current_user.id))
