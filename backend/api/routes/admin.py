"""Admin-only user management routes."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_admin_user
from backend.db.database import get_db
from backend.models.user import UserORM, UserRead

log = structlog.get_logger(__name__)
router = APIRouter()

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
