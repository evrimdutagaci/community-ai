from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    username: str
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: str
    username: str
    onboarding_complete: bool
    community_id: UUID | None
    is_admin: bool = False

    model_config = {"from_attributes": True}


class ProfileUpdate(BaseModel):
    username: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class CommunityOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    member_count: int = 0

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: UUID
    user_id: UUID
    username: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
