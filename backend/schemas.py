from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, PlainSerializer, model_validator


def utc_iso(value: datetime) -> str:
    """Every timestamp is stored as naive UTC. Sent without a zone, the
    browser reads it as local time, which put the whole audit trail 4-5 hours
    ahead for Eastern users. The trailing Z says what the value actually is."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


UtcDatetime = Annotated[datetime, PlainSerializer(utc_iso, return_type=str, when_used="json")]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    status: str  # "2fa_required" | "2fa_setup_required" | "ok"
    challenge_token: str | None = None
    access_token: str | None = None
    user: "UserOut | None" = None
    method: str | None = None  # "app" | "email", with 2fa_required
    sent_to: str | None = None  # masked address, for email codes


class EnrollRequest(BaseModel):
    method: str


class EnrollConfirmRequest(BaseModel):
    enroll_token: str
    code: str


class ChallengeRequest(BaseModel):
    challenge_token: str


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
    twofa_method: str = ""
    is_active: bool
    last_login_at: UtcDatetime | None = None
    created_at: UtcDatetime
    # What this person's role may do, so the site can hide what they can't.
    # The server still checks each request; this is only for the interface.
    permissions: list[str] = []

    model_config = {"from_attributes": True}

    @model_validator(mode="after")
    def _fill_permissions(self) -> "UserOut":
        import permissions as perms

        held = perms.for_role(self.role)
        self.permissions = [p for p in perms.PERMISSIONS if p in held]
        return self


class TeamAccountIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class InviteCreate(BaseModel):
    email: EmailStr
    role: str = "staff"


class InviteOut(BaseModel):
    id: str
    email: str
    role: str
    invite_url: str
    expires_at: UtcDatetime
    # True when the link also went out by email (SMTP configured and the send
    # worked). The admin still sees the link either way.
    emailed: bool = False


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
    created_at: UtcDatetime
    updated_at: UtcDatetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    visibility: str | None = None
    is_active: bool | None = None


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    # The last few turns of this conversation, held by the browser for the
    # life of the tab and resent with each question — chat history is
    # session-only and is never written to the database. Capped well above
    # what the model actually uses (the last 10) so a stray client can't pad
    # the request without limit.
    history: list[HistoryTurn] = Field(default_factory=list, max_length=20)


class CitationOut(BaseModel):
    n: int
    document_id: str
    document_title: str
    heading: str = ""
    page: int | None = None
    score: float = 0.0
    excerpt: str = ""


class AuditOut(BaseModel):
    # str, not int. The original SQLAlchemy model used an autoincrement
    # integer; every repo entity now carries a uuid string, and Firestore has
    # no autoincrement at all. Typing this int made /admin/audit 500 against
    # Firestore while passing against SQLite, whose ids really are integers.
    id: str
    at: UtcDatetime
    user_email: str
    action: str
    target: str
    detail: str
    ip: str

    model_config = {"from_attributes": True}


LoginResponse.model_rebuild()
