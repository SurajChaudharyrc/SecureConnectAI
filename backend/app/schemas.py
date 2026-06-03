import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
DOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=120)

    @field_validator("username")
    @classmethod
    def _username_charset(cls, v: str) -> str:
        if not USERNAME_REGEX.match(v):
            raise ValueError("username must match [a-zA-Z0-9_] and be 3-32 chars")
        return v

    @field_validator("password")
    @classmethod
    def _password_complexity(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
            raise ValueError("password must contain both letters and digits")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    full_name: str
    trust_score: float
    is_face_verified: bool
    verified_domain: str | None = None
    interests: list[str] = []
    current_lat: float | None = None
    current_lon: float | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class FaceVerifyResponse(BaseModel):
    verified: bool
    confidence: float | None = None
    trust_score: float
    detail: str | None = None


class DiscoverItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    niche_type: str
    description: str | None = None
    distance_km: float
    radius_km: float
    domain_match: bool = False
    is_member: bool = False
    member_count: int = 0


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=120)
    interests: list[str] | None = Field(None, max_length=20)
    current_lat: float | None = Field(None, ge=-90, le=90)
    current_lon: float | None = Field(None, ge=-180, le=180)

    @field_validator("interests")
    @classmethod
    def _validate_interests(cls, v):
        if v is None:
            return v
        cleaned = []
        for item in v:
            if not isinstance(item, str):
                raise ValueError("interests must be strings")
            stripped = item.strip()
            if 1 <= len(stripped) <= 40:
                cleaned.append(stripped)
        return cleaned


class OrgRequest(BaseModel):
    email: EmailStr
    domain: str = Field(..., min_length=3, max_length=120)

    @field_validator("domain")
    @classmethod
    def _validate_domain(cls, v: str) -> str:
        v = v.lower().strip()
        if not DOMAIN_REGEX.match(v):
            raise ValueError("domain must look like example.edu")
        return v


class OrgConfirm(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class SimpleMessage(BaseModel):
    message: str


class MessageItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    group_id: int
    user_id: int | None = None
    username: str | None = None
    body: str | None = None  # None when the message is soft-deleted
    created_at: datetime
    edited_at: datetime | None = None
    deleted_at: datetime | None = None


class MessageEditRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message body cannot be blank")
        return v
