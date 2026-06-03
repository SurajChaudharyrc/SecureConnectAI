"""Group chat: message history + edit/delete (REST) and the live WebSocket.

Split out of routers/groups.py. URLs keep the `/api/groups` prefix, so the HTTP
and WebSocket contract is unchanged. Connection tracking and fan-out go through
the pluggable `broker` (see services/chat.py), so this layer is unaware of
whether delivery is in-process or (future) cross-process via Redis.
"""
import json
import time
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .. import db as _dbmod  # access SessionLocal via module (tests reassign it)
from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..errors import Forbidden, NotFound
from ..models import Group, Membership, Message, SessionToken, User
from ..rate_limit import limiter
from ..schemas import MessageEditRequest, MessageItem, SimpleMessage
from ..security import SESSION_COOKIE_NAME, hash_token
from ..services.chat import Connection, broker

router = APIRouter(prefix="/api/groups", tags=["chat"])

# WebSocket close codes (4000-4999 = application-defined).
WS_CLOSE_UNAUTHENTICATED = 4401
WS_CLOSE_FORBIDDEN = 4403
WS_CLOSE_TOO_MANY = 4429


class RateLimiter:
    """Sliding-window limiter over time.monotonic().

    One instance per concern per connection (the WS handler owns its own), so it
    needs no locking. `allow()` records the event and returns whether it was
    permitted under the cap.
    """

    def __init__(self, max_events: int, window_s: float) -> None:
        self._max = max_events
        self._window = window_s
        self._events: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._window
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()
        if len(self._events) >= self._max:
            return False
        self._events.append(now)
        return True


# ----------------------------- helpers -----------------------------

def _require_membership(db: Session, user: User, group_id: int) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise NotFound("Group not found.")
    if db.get(Membership, {"user_id": user.id, "group_id": group_id}) is None:
        raise Forbidden("You are not a member of this group.")
    return group


def _serialize_message(msg: Message, username: str | None) -> MessageItem:
    deleted = msg.deleted_at is not None
    return MessageItem(
        id=msg.id,
        group_id=msg.group_id,
        user_id=msg.user_id,
        username=username,
        body=None if deleted else msg.body,
        created_at=msg.created_at,
        edited_at=msg.edited_at,
        deleted_at=msg.deleted_at,
    )


def _resolve_ws_user(websocket: WebSocket, db: Session) -> User | None:
    raw = websocket.cookies.get(SESSION_COOKIE_NAME)
    if not raw:
        return None
    session = db.get(SessionToken, hash_token(raw))
    if session is None:
        return None
    if session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        return None
    return session.user


async def _broadcast_presence(group_id: int) -> None:
    await broker.broadcast(
        group_id, {"type": "presence", "online": await broker.presence(group_id)}
    )


# ----------------------------- REST: history -----------------------------

@router.get("/{group_id}/messages", response_model=list[MessageItem])
def list_messages(
    group_id: int,
    before: int | None = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[MessageItem]:
    _require_membership(db, current_user, group_id)

    stmt = (
        select(Message, User.username)
        .join(User, Message.user_id == User.id, isouter=True)
        .where(Message.group_id == group_id)
    )
    if before is not None:
        stmt = stmt.where(Message.id < before)
    stmt = stmt.order_by(Message.id.desc()).limit(limit)

    return [_serialize_message(msg, username) for (msg, username) in db.execute(stmt).all()]


# ----------------------------- REST: edit / delete -----------------------------

@router.patch(
    "/{group_id}/messages/{msg_id}",
    response_model=MessageItem,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("60/minute")
async def edit_message(
    request: Request,
    group_id: int,
    msg_id: int,
    payload: MessageEditRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageItem:
    _require_membership(db, current_user, group_id)
    msg = db.get(Message, msg_id)
    if msg is None or msg.group_id != group_id or msg.deleted_at is not None:
        raise NotFound("Message not found.")
    if msg.user_id != current_user.id:
        raise Forbidden("You can only edit your own messages.")

    msg.body = payload.body.strip()
    msg.edited_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(msg)

    await broker.broadcast(
        group_id,
        {
            "type": "edit",
            "id": msg.id,
            "body": msg.body,
            "edited_at": msg.edited_at.isoformat(),
        },
    )
    return _serialize_message(msg, current_user.username)


@router.delete(
    "/{group_id}/messages/{msg_id}",
    response_model=SimpleMessage,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("60/minute")
async def delete_message(
    request: Request,
    group_id: int,
    msg_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    _require_membership(db, current_user, group_id)
    msg = db.get(Message, msg_id)
    if msg is None or msg.group_id != group_id or msg.deleted_at is not None:
        raise NotFound("Message not found.")
    if msg.user_id != current_user.id:
        raise Forbidden("You can only delete your own messages.")

    msg.deleted_at = datetime.now(timezone.utc)
    db.commit()

    await broker.broadcast(
        group_id,
        {"type": "delete", "id": msg.id, "deleted_at": msg.deleted_at.isoformat()},
    )
    return SimpleMessage(message="Message deleted.")


# ----------------------------- WebSocket -----------------------------

def _origin_allowed(websocket: WebSocket) -> bool:
    """CSWSH guard. Allow when: no Origin (non-browser client, not cookie-bound
    to a victim); Origin equals the configured ALLOWED_ORIGIN; or Origin is
    same-origin with the request Host. Same-origin is by definition not
    cross-site, so accepting it is safe — and it lets the app deploy to any
    domain without setting ALLOWED_ORIGIN. Only a *present, cross-site* Origin
    is rejected.
    """
    origin = websocket.headers.get("origin")
    if origin is None:
        return True
    if origin == get_settings().allowed_origin:
        return True
    host = websocket.headers.get("host")
    if host:
        from urllib.parse import urlparse

        if urlparse(origin).netloc == host:
            return True
    return False


async def _authorize_ws(websocket: WebSocket, db: Session, group_id: int) -> User | None:
    """Run the WS handshake gate: Origin/CSWSH check, session-cookie auth, and
    membership. Closes the socket with the right code and returns None on any
    failure; returns the authenticated member on success (socket NOT yet accepted).
    """
    if not _origin_allowed(websocket):
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    user = _resolve_ws_user(websocket, db)
    if user is None:
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return None

    if db.get(Membership, {"user_id": user.id, "group_id": group_id}) is None:
        await websocket.close(code=WS_CLOSE_FORBIDDEN)
        return None

    return user


def _persist_message_sync(
    token_hash: str, user_id: int, username: str, group_id: int, body: str
) -> tuple[str, dict | None]:
    """Runs in a worker thread (keeps blocking DB I/O off the event loop).

    Re-validates access with a FRESH session — the long-lived handshake session
    won't observe external commits like POST /leave or logout — then persists.
    Returns ('ok', payload) | ('unauth', None) | ('forbidden', None).
    """
    now = datetime.now(timezone.utc)
    with _dbmod.SessionLocal() as db:
        session = db.get(SessionToken, token_hash)
        if session is None or session.expires_at.replace(tzinfo=timezone.utc) <= now:
            return ("unauth", None)
        if db.get(Membership, {"user_id": user_id, "group_id": group_id}) is None:
            return ("forbidden", None)
        msg = Message(group_id=group_id, user_id=user_id, body=body)
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return (
            "ok",
            {
                "type": "message",
                "id": msg.id,
                "group_id": group_id,
                "user_id": user_id,
                "username": username,
                "body": msg.body,
                "created_at": msg.created_at.isoformat(),
            },
        )


async def _handle_send(
    websocket: WebSocket,
    group_id: int,
    user: User,
    token_hash: str,
    data: dict,
    send_limiter: RateLimiter,
) -> int | None:
    """Validate, persist (off-loop, with fresh-session re-authorization), and
    broadcast. Returns a WS close code if the sender's access was revoked
    (left the group / session expired) since the handshake, else None."""
    settings = get_settings()
    body = (data.get("body") or "").strip()
    if not body:
        await websocket.send_json({"type": "error", "detail": "Message is empty."})
        return None
    if len(body) > settings.chat_max_message_len:
        await websocket.send_json({"type": "error", "detail": "Message too long."})
        return None
    if not send_limiter.allow():
        await websocket.send_json({"type": "error", "detail": "Slow down."})
        return None

    status, payload = await run_in_threadpool(
        _persist_message_sync, token_hash, user.id, user.username, group_id, body
    )
    if status == "unauth":
        return WS_CLOSE_UNAUTHENTICATED
    if status == "forbidden":
        return WS_CLOSE_FORBIDDEN
    await broker.broadcast(group_id, payload)
    return None


async def _handle_typing(group_id: int, user: User, data: dict) -> None:
    await broker.broadcast(
        group_id,
        {
            "type": "typing",
            "user_id": user.id,
            "username": user.username,
            "state": bool(data.get("state")),
        },
    )


@router.websocket("/{group_id}/ws")
async def group_ws(
    websocket: WebSocket,
    group_id: int,
    db: Session = Depends(get_db),
) -> None:
    user = await _authorize_ws(websocket, db, group_id)
    if user is None:
        return
    token_hash = hash_token(websocket.cookies.get(SESSION_COOKIE_NAME, ""))

    settings = get_settings()
    await websocket.accept()
    conn = Connection(websocket=websocket, user_id=user.id, username=user.username)
    # Atomic cap check: per-group AND per-user (bounds the per-socket
    # rate-limiter bypass — one user can't hold every slot or open 200 sockets).
    if not await broker.try_connect(
        group_id,
        conn,
        settings.chat_max_connections_per_group,
        settings.chat_max_connections_per_user,
    ):
        await websocket.close(code=WS_CLOSE_TOO_MANY)
        return
    await _broadcast_presence(group_id)

    send_limiter = RateLimiter(settings.chat_send_rate_max, settings.chat_send_rate_window_s)
    frame_limiter = RateLimiter(settings.chat_frame_rate_max, settings.chat_frame_rate_window_s)
    try:
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                # Malformed / non-JSON / binary frame: tell the client, keep the
                # socket alive instead of crashing the receive loop.
                await websocket.send_json({"type": "error", "detail": "Invalid frame."})
                continue

            # Per-connection flood guard across ALL inbound frames (incl. typing).
            if not frame_limiter.allow():
                continue
            mtype = data.get("type") if isinstance(data, dict) else None
            close_code: int | None = None
            if mtype == "send":
                close_code = await _handle_send(
                    websocket, group_id, user, token_hash, data, send_limiter
                )
            elif mtype == "typing":
                await _handle_typing(group_id, user, data)
            # unknown types are ignored
            if close_code is not None:
                await websocket.close(code=close_code)
                break
    except WebSocketDisconnect:
        pass
    finally:
        await broker.disconnect(group_id, conn)
        await _broadcast_presence(group_id)
