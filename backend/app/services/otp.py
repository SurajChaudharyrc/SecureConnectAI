from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import OrgOtp
from ..security import generate_otp_code, hash_otp

_settings = get_settings()
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
MAX_ATTEMPTS = 5


def email_matches_domain(email: str, domain: str) -> bool:
    if not email or not domain:
        return False
    if not _DOMAIN_RE.match(domain):
        return False
    local, _, rhs = email.lower().partition("@")
    return bool(local) and rhs == domain.lower()


def issue_otp(db: Session, email: str, domain: str) -> str:
    """Generate, persist (hashed), and return the plaintext OTP."""
    code = generate_otp_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=_settings.otp_ttl_minutes)
    record = OrgOtp(
        email=email.lower(),
        domain=domain.lower(),
        code_hash=hash_otp(code, salt=email.lower()),
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()
    return code


def consume_otp(db: Session, email: str, code: str) -> str | None:
    """Validate + mark used. Returns the verified domain on success, else None."""
    email_l = email.lower()
    now = datetime.now(timezone.utc)
    stmt = (
        select(OrgOtp)
        .where(OrgOtp.email == email_l, OrgOtp.used_at.is_(None))
        .order_by(OrgOtp.created_at.desc())
        .limit(1)
    )
    otp: OrgOtp | None = db.scalars(stmt).first()
    if otp is None:
        return None

    if otp.expires_at.replace(tzinfo=timezone.utc) <= now:
        return None

    if otp.attempts >= MAX_ATTEMPTS:
        return None

    otp.attempts += 1
    expected = hash_otp(code, salt=email_l)
    if expected != otp.code_hash:
        db.commit()
        return None

    otp.used_at = now
    db.commit()
    return otp.domain
