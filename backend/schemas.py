from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    status: str  # "2fa_required" | "2fa_setup_required" | "ok"
    challenge_token: str | None = None
    access_token: str | None = None
    user: "UserOut | None" = None


class TwoFactorRequest(BaseModel):
    challenge_token: str
    code: str


class TotpSetupResponse(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class AcceptInviteRequest(BaseModel):
    token: str
    full_name: str = Field(min_length=1, max_length=200)
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    totp_confirmed: bool
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "staff"


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    invite_url: str
    expires_at: datetime


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    category: str
    visibility: str
    version: int
    is_active: bool
    chunk_count: int
    char_count: int
    size_bytes: int
    pii_flags: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    visibility: str | None = None
    is_active: bool | None = None


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = None


class CitationOut(BaseModel):
    n: int
    document_id: str
    document_title: str
    heading: str = ""
    page: int | None = None
    score: float = 0.0
    excerpt: str = ""


class AuditOut(BaseModel):
    id: int
    at: datetime
    user_email: str
    action: str
    target: str
    detail: str
    ip: str

    model_config = {"from_attributes": True}


LoginResponse.model_rebuild()
