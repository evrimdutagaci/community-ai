from datetime import datetime, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import jwt
from passlib.context import CryptContext
from ..database import get_db
from ..models import User
from ..schemas import UserRegister, UserLogin, Token, UserOut, ProfileUpdate, PasswordChange
from ..config import settings
from ..deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _create_token(user_id: UUID) -> str:
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.secret_key,
        algorithm=settings.algorithm,
    )


@router.post("/register", response_model=Token)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=data.email,
        username=data.username,
        password_hash=_pwd.hash(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return Token(access_token=_create_token(user.id))


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not _pwd.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return Token(access_token=_create_token(user.id))


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/profile", response_model=UserOut)
async def update_profile(
    data: ProfileUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    new_username = data.username.strip()
    if not new_username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if new_username != current_user.username:
        conflict = await db.execute(select(User).where(User.username == new_username))
        if conflict.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username already taken")
        current_user.username = new_username
        await db.commit()
        await db.refresh(current_user)
    return current_user


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not _pwd.verify(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    current_user.password_hash = _pwd.hash(data.new_password)
    await db.commit()
    return {"status": "ok"}


@router.post("/make-admin")
async def make_admin(
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    current_user.is_admin = True
    await db.commit()
    return {"status": "ok", "username": current_user.username}
