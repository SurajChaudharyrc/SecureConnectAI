import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..errors import AppError, AuthRequired, Conflict
from ..models import SessionToken, User
from ..rate_limit import limiter
from ..schemas import LoginRequest, RegisterRequest, SimpleMessage, UserPublic
from ..security import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    session_expiry,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("secureconnect.auth")
_settings = get_settings()


def _set_session_cookies(response: Response, token: str, csrf: str) -> None:
    is_secure = _settings.is_prod
    max_age = _settings.session_ttl_hours * 3600
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        max_age=max_age,
        httponly=False,  # JS reads to send in header
        secure=is_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")


def _create_session(db: Session, user: User, request: Request) -> tuple[str, str]:
    token_raw, token_hash_value = generate_session_token()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent", "")[:255]
    db.add(
        SessionToken(
            token_hash=token_hash_value,
            user_id=user.id,
            expires_at=session_expiry(),
            ip=ip,
            user_agent=ua,
        )
    )
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return token_raw, generate_csrf_token()


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
def register(payload: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserPublic:
    existing = db.scalars(
        select(User).where((User.username == payload.username) | (User.email == payload.email))
    ).first()
    if existing is not None:
        raise Conflict("That username or email is already registered.")

    user = User(
        username=payload.username,
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Conflict("That username or email is already registered.")
    db.refresh(user)

    token, csrf = _create_session(db, user, request)
    _set_session_cookies(response, token, csrf)
    return UserPublic.model_validate(user)


@router.post("/login", response_model=UserPublic)
@limiter.limit("10/minute")
def login(payload: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserPublic:
    user = db.scalars(select(User).where(User.username == payload.username)).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        log.info("login_failed", extra={"username": payload.username[:32]})
        raise AppError("Invalid username or password.", status_code=401)

    token, csrf = _create_session(db, user, request)
    _set_session_cookies(response, token, csrf)
    return UserPublic.model_validate(user)


@router.post("/logout", response_model=SimpleMessage, dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    session: SessionToken | None = getattr(request.state, "session", None)
    if session is not None:
        db.delete(session)
        db.commit()
    _clear_session_cookies(response)
    return SimpleMessage(message="Logged out.")


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.get("/csrf", response_model=SimpleMessage)
def refresh_csrf(response: Response, current_user: User = Depends(get_current_user)) -> SimpleMessage:
    csrf = generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf,
        max_age=_settings.session_ttl_hours * 3600,
        httponly=False,
        secure=_settings.is_prod,
        samesite="lax",
        path="/",
    )
    return SimpleMessage(message="ok")
