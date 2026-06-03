from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, Request
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AuthRequired, CsrfInvalid
from .models import SessionToken, User
from .security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    constant_time_eq,
    hash_token,
    verify_csrf_token,
)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    sc_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> User:
    if not sc_session:
        raise AuthRequired()

    token_hash = hash_token(sc_session)
    session: SessionToken | None = db.get(SessionToken, token_hash)
    if session is None:
        raise AuthRequired()

    if session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        db.delete(session)
        db.commit()
        raise AuthRequired()

    user = session.user
    if user is None:
        raise AuthRequired()

    request.state.user = user
    request.state.session = session
    return user


def require_csrf(
    request: Request,
    sc_csrf: str | None = Cookie(default=None, alias=CSRF_COOKIE_NAME),
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    """Double-submit cookie pattern. Skips on safe methods."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if not sc_csrf or not x_csrf_token:
        raise CsrfInvalid()
    if not constant_time_eq(sc_csrf, x_csrf_token):
        raise CsrfInvalid()
    # Double-submit match alone trusts an attacker-writable cookie; also require
    # a valid itsdangerous signature so a forged/injected sc_csrf is rejected.
    if not verify_csrf_token(x_csrf_token):
        raise CsrfInvalid()
