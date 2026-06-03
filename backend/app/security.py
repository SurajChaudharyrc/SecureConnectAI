from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, URLSafeTimedSerializer
from passlib.context import CryptContext

from .config import get_settings

_settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_csrf_serializer = URLSafeTimedSerializer(_settings.app_secret, salt="csrf-v1")

SESSION_COOKIE_NAME = "sc_session"
CSRF_COOKIE_NAME = "sc_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return pwd_context.verify(password, password_hash)
    except Exception:
        return False


def generate_session_token() -> tuple[str, str]:
    """Returns (plaintext_token, sha256_hash). Store the hash only."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=_settings.session_ttl_hours)


def generate_csrf_token() -> str:
    return _csrf_serializer.dumps(secrets.token_urlsafe(16))


def verify_csrf_token(token: str, max_age_seconds: int = 60 * 60 * 24) -> bool:
    try:
        _csrf_serializer.loads(token, max_age=max_age_seconds)
        return True
    except BadSignature:
        return False
    except Exception:
        return False


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def generate_otp_code() -> str:
    """6-digit OTP via secrets (not random)."""
    return f"{secrets.randbelow(10**6):06d}"


def hash_otp(code: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{code}".encode("utf-8")).hexdigest()
