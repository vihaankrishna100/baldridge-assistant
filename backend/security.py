from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import pyotp

from config import settings

ALGORITHM = "HS256"


def _prepare(password: str) -> bytes:
    """bcrypt silently truncates at 72 bytes, which would make a long
    passphrase weaker than it looks. SHA-256 first, then base64, so the input
    is always a fixed 44 bytes and every character counts."""
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


# Work factor. 11 is ~190ms here against ~470ms at 12, and sits comfortably
# above the widely cited floor of 10. It is over half the sign-in time, and the
# realistic attack it defends against — offline cracking — requires the
# attacker to already hold the Firestore contents, at which point they have the
# documents themselves. Raise it if 2FA is ever turned back on and latency
# matters less.
BCRYPT_ROUNDS = 11


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash was made with a different cost than we now use.

    bcrypt bakes the cost into the hash, so changing BCRYPT_ROUNDS does nothing
    for existing accounts until their password is re-hashed. Doing it on a
    successful sign-in — when the plaintext is briefly in hand — upgrades every
    account exactly once, without anyone having to reset anything.
    """
    try:
        cost = int(password_hash.split("$")[2])
    except (IndexError, ValueError):
        return False
    return cost != BCRYPT_ROUNDS


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), password_hash.encode())
    except (ValueError, TypeError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 12:
        problems.append("must be at least 12 characters")
    if not any(c.isalpha() for c in password):
        problems.append("must contain a letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a number")
    if password.lower() in {"password1234", "baldridgelodge", "changemenow123"}:
        problems.append("is too easy to guess")
    return problems


# ---------------------------------------------------------------- tokens


def create_session_token(user_id: str, epoch: int, scope: str = "session") -> str:
    now = datetime.now(timezone.utc)
    ttl = settings.session_ttl_minutes if scope == "session" else 5
    payload = {
        "sub": user_id,
        "epoch": epoch,
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=ttl),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def new_invite_token() -> tuple[str, str]:
    """Returns (plaintext, sha256) — only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------- 2FA


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=f"{settings.org_name} Assistant"
    )


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    cleaned = code.replace(" ", "").strip()
    if not cleaned.isdigit():
        return False
    # valid_window=1 tolerates one 30s step of clock drift in either direction.
    return pyotp.TOTP(secret).verify(cleaned, valid_window=1)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
