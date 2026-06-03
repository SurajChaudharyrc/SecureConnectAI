# Group Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time, per-group text chat (history, presence, typing, edit/delete) to SecureConnect-AI's existing groups.

**Architecture:** A flat chat stream per group delivered over a WebSocket, backed by a new `messages` table and an in-process in-memory connection manager. History/edit/delete go through REST (reusing the existing cookie-auth + CSRF path); live new-messages, typing, and presence go over the WebSocket. Access is gated by the existing `Membership` model — only members may read or post.

**Tech Stack:** FastAPI (incl. Starlette WebSockets), SQLAlchemy 2 + SQLite, vanilla HTML/CSS/JS frontend, pytest with `TestClient.websocket_connect`.

**Spec:** `docs/superpowers/specs/2026-05-29-group-chat-design.md`

---

## File Structure

**Backend (create):**
- `backend/app/services/chat.py` — `Connection` dataclass + `ConnectionManager` + module-level `manager` singleton. In-memory only.

**Backend (modify):**
- `backend/app/models.py` — add `Message` model + `Group.messages` relationship.
- `backend/app/schemas.py` — add `MessageItem`, `MessageEditRequest`.
- `backend/app/routers/groups.py` — add membership helper, message serializer, REST history/edit/delete endpoints, and the WebSocket endpoint.
- `backend/app/main.py` — register the `/chat` page route + `chat.html`.

**Frontend (create):**
- `frontend/chat.html` — chat page shell.
- `frontend/js/chat.js` — chat page logic (history load, WebSocket, composer, presence, typing, edit/delete).

**Frontend (modify):**
- `frontend/js/api.js` — add message REST helpers + WebSocket URL builder.
- `frontend/js/discover.js` — add "Open chat" action to groups the user is a member of.
- `frontend/css/components.css` — chat component styles (bubbles, composer, presence).

**Tests (create):**
- `backend/tests/test_chat.py` — model, connection manager, REST, and WebSocket tests.

---

## Task 1: `Message` model

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_chat.py` with:

```python
from fastapi.testclient import TestClient

from backend.app import db as db_module
from backend.app.main import app
from backend.app.models import Group, Membership, Message, User
from backend.tests.conftest import register_and_login


# ----------------------------- helpers -----------------------------

def _make_group(name="Chat Group"):
    with db_module.SessionLocal() as db:
        g = Group(name=name, niche_type="Social", latitude=0.0, longitude=0.0, radius_km=1.0)
        db.add(g)
        db.commit()
        db.refresh(g)
        return g.id


def _join(group_id, username):
    with db_module.SessionLocal() as db:
        u = db.query(User).filter_by(username=username).one()
        db.add(Membership(user_id=u.id, group_id=group_id))
        db.commit()


def _add_message(group_id, username, body):
    with db_module.SessionLocal() as db:
        u = db.query(User).filter_by(username=username).one()
        m = Message(group_id=group_id, user_id=u.id, body=body)
        db.add(m)
        db.commit()
        db.refresh(m)
        return m.id


def _recv_type(ws, type_, max_frames=12):
    """Receive frames until one matches `type_`; skip presence/typing noise."""
    for _ in range(max_frames):
        frame = ws.receive_json()
        if frame.get("type") == type_:
            return frame
    raise AssertionError(f"did not receive a {type_!r} frame")


# ----------------------------- tests -----------------------------

def test_message_persists_and_reads_back(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    mid = _add_message(gid, "alice", "hello")
    with db_module.SessionLocal() as db:
        m = db.get(Message, mid)
        assert m is not None
        assert m.body == "hello"
        assert m.group_id == gid
        assert m.deleted_at is None
        assert m.edited_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat.py::test_message_persists_and_reads_back -v`
Expected: FAIL with `ImportError: cannot import name 'Message'`.

- [ ] **Step 3: Add the model**

In `backend/app/models.py`, add this class after the `Membership` class (before `OrgOtp`):

```python
class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

Then, inside the existing `Group` class, add a `messages` relationship alongside `memberships`:

```python
    messages: Mapped[list[Message]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
```

And give `Message` the matching back-reference by appending to the `Message` class body:

```python
    group: Mapped[Group] = relationship(back_populates="messages")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat.py::test_message_persists_and_reads_back -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_chat.py
git commit -m "feat(chat): add Message model"
```

---

## Task 2: Message schemas

**Files:**
- Modify: `backend/app/schemas.py`

- [ ] **Step 1: Add the schemas**

Append to `backend/app/schemas.py`:

```python
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
```

- [ ] **Step 2: Verify it imports**

Run: `cd backend && python -c "from app.schemas import MessageItem, MessageEditRequest; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(chat): add message schemas"
```

---

## Task 3: In-process connection manager

**Files:**
- Create: `backend/app/services/chat.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_chat.py`:

```python
def test_connection_manager_presence_dedup():
    from backend.app.services.chat import Connection, ConnectionManager

    m = ConnectionManager()
    c1 = Connection(websocket=None, user_id=1, username="a")
    c2 = Connection(websocket=None, user_id=1, username="a")  # same user, 2nd socket
    c3 = Connection(websocket=None, user_id=2, username="b")

    m.connect(5, c1)
    m.connect(5, c2)
    m.connect(5, c3)
    assert {o["user_id"] for o in m.online_for(5)} == {1, 2}

    m.disconnect(5, c1)  # user 1 still has c2
    assert {o["user_id"] for o in m.online_for(5)} == {1, 2}

    m.disconnect(5, c2)
    assert {o["user_id"] for o in m.online_for(5)} == {2}

    m.disconnect(5, c3)
    assert m.online_for(5) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_chat.py::test_connection_manager_presence_dedup -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.chat'` (or import error).

- [ ] **Step 3: Create the service**

Create `backend/app/services/chat.py`:

```python
"""In-process WebSocket connection manager for group chat.

State lives in memory in this single process. Presence and broadcast therefore
only work with one server process. To scale horizontally, replace the broadcast
and presence internals with a Redis pub/sub channel per group — the public
interface (connect / disconnect / broadcast / online_for) is intentionally
narrow so that swap stays localized.

connect/disconnect/online_for are synchronous: under asyncio they never yield
mid-mutation, so no lock is needed. Only broadcast awaits (it sends on sockets).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(eq=False)
class Connection:
    websocket: Any  # starlette.websockets.WebSocket (None in unit tests)
    user_id: int
    username: str


class ConnectionManager:
    def __init__(self) -> None:
        self._groups: dict[int, set[Connection]] = {}

    def connect(self, group_id: int, conn: Connection) -> None:
        self._groups.setdefault(group_id, set()).add(conn)

    def disconnect(self, group_id: int, conn: Connection) -> None:
        conns = self._groups.get(group_id)
        if conns is None:
            return
        conns.discard(conn)
        if not conns:
            self._groups.pop(group_id, None)

    def online_for(self, group_id: int) -> list[dict[str, Any]]:
        seen: dict[int, str] = {}
        for c in self._groups.get(group_id, set()):
            seen[c.user_id] = c.username
        return [{"user_id": uid, "username": un} for uid, un in seen.items()]

    async def broadcast(self, group_id: int, payload: dict[str, Any]) -> None:
        dead: list[Connection] = []
        for c in list(self._groups.get(group_id, set())):
            try:
                await c.websocket.send_json(payload)
            except Exception:
                dead.append(c)
        for c in dead:
            self.disconnect(group_id, c)


manager = ConnectionManager()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_chat.py::test_connection_manager_presence_dedup -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chat.py backend/tests/test_chat.py
git commit -m "feat(chat): in-process connection manager"
```

---

## Task 4: REST history endpoint + member guard

**Files:**
- Modify: `backend/app/routers/groups.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat.py`:

```python
def test_history_member_only(client):
    register_and_login(client, "alice")
    gid = _make_group()  # not joined
    r = client.get(f"/api/groups/{gid}/messages")
    assert r.status_code == 403


def test_history_newest_first_and_pagination(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    m1 = _add_message(gid, "alice", "one")
    m2 = _add_message(gid, "alice", "two")
    m3 = _add_message(gid, "alice", "three")

    r = client.get(f"/api/groups/{gid}/messages", params={"limit": 2})
    assert r.status_code == 200
    assert [x["id"] for x in r.json()] == [m3, m2]
    assert r.json()[0]["username"] == "alice"

    r2 = client.get(f"/api/groups/{gid}/messages", params={"before": m2, "limit": 2})
    assert [x["id"] for x in r2.json()] == [m1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_chat.py::test_history_member_only tests/test_chat.py::test_history_newest_first_and_pagination -v`
Expected: FAIL (404 / route not found).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/routers/groups.py`, update the imports at the top. Add `import time` at the very top of the file (with the stdlib imports), then replace the existing model/schema import lines with:

```python
import time
from datetime import datetime, timezone

from ..config import get_settings
from ..models import Group, Membership, Message, User, SessionToken
from ..schemas import DiscoverItem, MessageEditRequest, MessageItem, SimpleMessage
from ..security import SESSION_COOKIE_NAME, hash_token
from ..services.chat import Connection, manager
```

Also add `WebSocket` and `WebSocketDisconnect` to the existing `fastapi` import line so it reads:

```python
from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
```

Add these constants below `MIN_TRUST_FOR_DISCOVERY = 0.5`:

```python
MAX_MESSAGE_LEN = 2000
WS_RATE_MAX = 5
WS_RATE_WINDOW_S = 2.0
```

Add these helpers (place them after the constants, before `discover_groups`):

```python
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
```

Add the history endpoint at the end of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_chat.py::test_history_member_only tests/test_chat.py::test_history_newest_first_and_pagination -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/groups.py backend/tests/test_chat.py
git commit -m "feat(chat): message history endpoint with member guard"
```

---

## Task 5: WebSocket endpoint (auth, presence, send, typing, rate limit)

**Files:**
- Modify: `backend/app/routers/groups.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat.py`:

```python
import pytest
from starlette.websockets import WebSocketDisconnect


def test_ws_unauthenticated_rejected(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/groups/1/ws") as ws:
            ws.receive_json()


def test_ws_non_member_rejected(client):
    register_and_login(client, "alice")
    gid = _make_group()  # not joined
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
            ws.receive_json()


def test_ws_bad_origin_rejected(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/api/groups/{gid}/ws", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()


def test_ws_send_broadcasts_and_persists(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        assert _recv_type(ws, "presence")["online"][0]["username"] == "alice"
        ws.send_json({"type": "send", "body": "hello world"})
        frame = _recv_type(ws, "message")
        assert frame["body"] == "hello world"
        assert frame["username"] == "alice"

    r = client.get(f"/api/groups/{gid}/messages")
    assert r.json()[0]["body"] == "hello world"


def test_ws_send_validation(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        _recv_type(ws, "presence")
        ws.send_json({"type": "send", "body": "   "})
        assert _recv_type(ws, "error")
        ws.send_json({"type": "send", "body": "x" * 2001})
        assert _recv_type(ws, "error")


def test_ws_rate_limit(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        _recv_type(ws, "presence")
        for i in range(7):
            ws.send_json({"type": "send", "body": f"m{i}"})
        errors = 0
        for _ in range(7):
            f = ws.receive_json()
            if f["type"] == "error":
                errors += 1
        assert errors >= 1


def test_ws_two_members_broadcast(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with TestClient(app) as c2:
        register_and_login(c2, "bob")
        _join(gid, "bob")
        with client.websocket_connect(f"/api/groups/{gid}/ws") as wsa, \
                c2.websocket_connect(f"/api/groups/{gid}/ws") as wsb:
            _recv_type(wsa, "presence")
            _recv_type(wsb, "presence")
            wsa.send_json({"type": "send", "body": "hi bob"})
            assert _recv_type(wsb, "message")["body"] == "hi bob"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_chat.py -k "ws_" -v`
Expected: FAIL (no websocket route; connections close/raise unexpectedly or 403/404).

- [ ] **Step 3: Implement the WebSocket auth helper + endpoint**

In `backend/app/routers/groups.py`, add this helper after `_serialize_message`:

```python
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
```

Add the WebSocket endpoint at the end of the file:

```python
@router.websocket("/{group_id}/ws")
async def group_ws(
    websocket: WebSocket,
    group_id: int,
    db: Session = Depends(get_db),
) -> None:
    # CSWSH guard: browsers always send Origin on WS connects, so a cross-site
    # page cannot omit it. Non-browser clients (no Origin) are not cookie-bound
    # to a victim, so allowing a missing Origin is safe.
    origin = websocket.headers.get("origin")
    if origin is not None and origin != get_settings().allowed_origin:
        await websocket.close(code=4403)
        return

    user = _resolve_ws_user(websocket, db)
    if user is None:
        await websocket.close(code=4401)
        return

    if db.get(Membership, {"user_id": user.id, "group_id": group_id}) is None:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    conn = Connection(websocket=websocket, user_id=user.id, username=user.username)
    manager.connect(group_id, conn)
    await manager.broadcast(
        group_id, {"type": "presence", "online": manager.online_for(group_id)}
    )

    sent_times: list[float] = []
    try:
        while True:
            data = await websocket.receive_json()
            mtype = data.get("type")

            if mtype == "send":
                body = (data.get("body") or "").strip()
                if not body:
                    await websocket.send_json({"type": "error", "detail": "Message is empty."})
                    continue
                if len(body) > MAX_MESSAGE_LEN:
                    await websocket.send_json({"type": "error", "detail": "Message too long."})
                    continue

                now = time.monotonic()
                sent_times[:] = [t for t in sent_times if now - t <= WS_RATE_WINDOW_S]
                if len(sent_times) >= WS_RATE_MAX:
                    await websocket.send_json({"type": "error", "detail": "Slow down."})
                    continue
                sent_times.append(now)

                msg = Message(group_id=group_id, user_id=user.id, body=body)
                db.add(msg)
                db.commit()
                db.refresh(msg)
                await manager.broadcast(
                    group_id,
                    {
                        "type": "message",
                        "id": msg.id,
                        "group_id": group_id,
                        "user_id": user.id,
                        "username": user.username,
                        "body": msg.body,
                        "created_at": msg.created_at.isoformat(),
                    },
                )

            elif mtype == "typing":
                await manager.broadcast(
                    group_id,
                    {
                        "type": "typing",
                        "user_id": user.id,
                        "username": user.username,
                        "state": bool(data.get("state")),
                    },
                )
            # unknown types are ignored
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(group_id, conn)
        await manager.broadcast(
            group_id, {"type": "presence", "online": manager.online_for(group_id)}
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_chat.py -k "ws_" -v`
Expected: PASS (all 6 ws tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/groups.py backend/tests/test_chat.py
git commit -m "feat(chat): websocket endpoint with presence, typing, rate limit"
```

---

## Task 6: Edit + delete endpoints (REST + broadcast)

**Files:**
- Modify: `backend/app/routers/groups.py`
- Test: `backend/tests/test_chat.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chat.py`:

```python
def test_edit_own_message(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    mid = _add_message(gid, "alice", "original")

    r = client.patch(f"/api/groups/{gid}/messages/{mid}", json={"body": "edited"})
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "edited"
    assert r.json()["edited_at"] is not None


def test_cannot_edit_others_message(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    mid = _add_message(gid, "alice", "alice's message")

    with TestClient(app) as c2:
        register_and_login(c2, "bob")
        _join(gid, "bob")
        r = c2.patch(f"/api/groups/{gid}/messages/{mid}", json={"body": "hacked"})
        assert r.status_code == 403


def test_delete_soft_deletes_and_tombstones(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    mid = _add_message(gid, "alice", "to be deleted")

    r = client.delete(f"/api/groups/{gid}/messages/{mid}")
    assert r.status_code == 200, r.text

    hist = client.get(f"/api/groups/{gid}/messages").json()
    row = next(x for x in hist if x["id"] == mid)
    assert row["body"] is None
    assert row["deleted_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_chat.py -k "edit or delete" -v`
Expected: FAIL (route not found / 405).

- [ ] **Step 3: Implement edit + delete**

Add to the end of `backend/app/routers/groups.py`:

```python
@router.patch(
    "/{group_id}/messages/{msg_id}",
    response_model=MessageItem,
    dependencies=[Depends(require_csrf)],
)
async def edit_message(
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

    await manager.broadcast(
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
async def delete_message(
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

    await manager.broadcast(
        group_id,
        {"type": "delete", "id": msg.id, "deleted_at": msg.deleted_at.isoformat()},
    )
    return SimpleMessage(message="Message deleted.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_chat.py -k "edit or delete" -v`
Expected: PASS.

- [ ] **Step 5: Run the whole chat suite + full suite**

Run: `cd backend && python -m pytest tests/test_chat.py -v && python -m pytest -q`
Expected: all chat tests PASS; full suite (previous 31 + new) PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/groups.py backend/tests/test_chat.py
git commit -m "feat(chat): edit and delete message endpoints"
```

---

## Task 7: Serve the chat page route

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add the page route**

In `backend/app/main.py`, in the `_PAGE_FILES` dict (around line 106-113), add a `"/chat"` entry:

```python
    _PAGE_FILES = {
        "/": "index.html",
        "/login": "login.html",
        "/register": "register.html",
        "/verify": "verify.html",
        "/discover": "discover.html",
        "/profile": "profile.html",
        "/chat": "chat.html",
    }
```

- [ ] **Step 2: Verify the app still imports**

Run: `cd backend && python -c "from app.main import app; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(chat): serve /chat page"
```

---

## Task 8: Frontend API helpers

**Files:**
- Modify: `frontend/js/api.js`

`api.js` exports a single `api` object whose methods call the module-private
`request()` wrapper (which already attaches `credentials: "same-origin"` and the
`X-CSRF-Token` header for non-GET methods). Add chat methods to that object — do
**not** introduce loose exported functions.

- [ ] **Step 1: Add the message methods to the `api` object**

In `frontend/js/api.js`, inside the `export const api = { ... }` literal, add the
following under the existing `// Groups` section (after `leaveGroup`):

```javascript
  // Group chat
  messages: (id, { before = null, limit = 50 } = {}) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (before != null) p.set("before", String(before));
    return request(`/api/groups/${id}/messages?${p}`);
  },
  editMessage: (id, msgId, body) =>
    request(`/api/groups/${id}/messages/${msgId}`, { method: "PATCH", body: { body } }),
  deleteMessage: (id, msgId) =>
    request(`/api/groups/${id}/messages/${msgId}`, { method: "DELETE" }),
```

(The WebSocket URL is built directly in `chat.js`, so no helper is needed here.
`request()` already throws an `Error` with `.status` on failure, matching the
rest of the app's error handling.)

- [ ] **Step 2: Verify the module still parses**

Run: `node --check frontend/js/api.js` (if Node is available) — Expected: no output (exit 0).
If Node is unavailable, skip; the manual browser smoke in Task 9 will surface syntax errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/js/api.js
git commit -m "feat(chat): frontend api methods for messages"
```

---

## Task 9: Chat page (HTML + JS)

**Files:**
- Create: `frontend/chat.html`
- Create: `frontend/js/chat.js`

- [ ] **Step 1: Create `frontend/chat.html`**

Mirror the head/nav from `discover.html` (same stylesheet links and nav block). Use this content:

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="color-scheme" content="dark" />
  <title>Chat — SecureConnect-AI</title>
  <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg" />
  <link rel="stylesheet" href="/css/tokens.css" />
  <link rel="stylesheet" href="/css/base.css" />
  <link rel="stylesheet" href="/css/components.css" />
  <link rel="stylesheet" href="/css/pages.css" />
</head>
<body>
  <header class="nav">
    <div class="container nav-inner">
      <a class="brand" href="/"><span class="brand-dot" aria-hidden="true"></span><span>SecureConnect<span class="muted">·AI</span></span></a>
      <nav class="nav-links" aria-label="Primary">
        <a class="nav-link" href="/discover">Discover</a>
        <a class="nav-link" href="/verify">Verify</a>
        <a class="nav-link" href="/profile">Profile</a>
        <button class="nav-link btn btn-ghost btn-sm" data-logout>Sign out</button>
      </nav>
    </div>
  </header>

  <main class="container chat-page">
    <div class="chat-head">
      <a class="nav-link" href="/discover">← Back</a>
      <h1 class="chat-title" id="chat-title">Group chat</h1>
      <span class="chat-presence" id="chat-presence">0 online</span>
    </div>

    <section class="chat-window" id="chat-window" aria-live="polite">
      <button class="chat-load-older" id="load-older" hidden>Load older messages</button>
      <ol class="chat-messages" id="chat-messages"></ol>
      <div class="chat-typing" id="chat-typing" aria-live="polite"></div>
    </section>

    <form class="chat-composer" id="chat-composer">
      <textarea id="chat-input" rows="1" maxlength="2000"
        placeholder="Message… (Enter to send, Shift+Enter for newline)"
        aria-label="Message"></textarea>
      <button class="btn btn-primary" type="submit">Send</button>
    </form>
  </main>

  <script type="module" src="/js/chat.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `frontend/js/chat.js`**

This uses the shared `ui.js` helpers exactly like `discover.js` does:
`setNavActive()` for nav state, `requireAuth(api)` for the auth guard (it redirects
to `/login` on 401 and **returns the user object**, giving us `user.id` directly —
so "mine" styling works immediately), plus `escapeHtml` and `toast`.

```javascript
import { api } from "/js/api.js";
import { escapeHtml, requireAuth, setNavActive, toast } from "/js/ui.js";

setNavActive();
const user = await requireAuth(api);
if (!user) {
  // requireAuth already redirected to /login.
} else {
  await boot(user);
}

async function boot(user) {
  const myUserId = user.id;
  const groupId = Number(new URLSearchParams(window.location.search).get("group"));

  const els = {
    title: document.getElementById("chat-title"),
    presence: document.getElementById("chat-presence"),
    list: document.getElementById("chat-messages"),
    typing: document.getElementById("chat-typing"),
    loadOlder: document.getElementById("load-older"),
    composer: document.getElementById("chat-composer"),
    input: document.getElementById("chat-input"),
  };

  if (!Number.isFinite(groupId) || groupId <= 0) {
    els.title.textContent = "Invalid group";
    return;
  }

  let oldestId = null;
  let socket = null;
  let reconnectDelay = 1000;
  const typingUsers = new Map(); // user_id -> { username, timer }

  function fmtTime(iso) {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  function renderMessage(m, { prepend = false } = {}) {
    const existing = document.getElementById(`msg-${m.id}`);
    const li = existing || document.createElement("li");
    li.id = `msg-${m.id}`;
    li.className = "chat-msg";

    if (m.deleted_at) {
      li.classList.add("is-deleted");
      li.innerHTML = `<span class="chat-msg-deleted">message deleted</span>`;
    } else {
      const mine = m.user_id === myUserId;
      li.classList.toggle("is-mine", mine);
      const edited = m.edited_at ? ` <span class="chat-msg-edited">(edited)</span>` : "";
      const controls = mine
        ? `<span class="chat-msg-actions">
             <button class="chat-link" data-edit="${m.id}">edit</button>
             <button class="chat-link" data-delete="${m.id}">delete</button>
           </span>`
        : "";
      li.innerHTML = `
        <div class="chat-msg-meta">
          <span class="chat-msg-author">${escapeHtml(m.username || "unknown")}</span>
          <span class="chat-msg-time">${fmtTime(m.created_at)}</span>
          ${controls}
        </div>
        <div class="chat-msg-body" data-body="${m.id}">${escapeHtml(m.body)}${edited}</div>`;
    }

    if (!existing) {
      if (prepend) els.list.prepend(li);
      else els.list.append(li);
    }
    return li;
  }

  function scrollToBottom() {
    window.scrollTo(0, document.body.scrollHeight);
    els.list.lastElementChild?.scrollIntoView({ block: "end" });
  }

  async function loadHistory({ older = false } = {}) {
    const opts = older && oldestId ? { before: oldestId } : {};
    const rows = await api.messages(groupId, opts); // newest-first
    if (!rows.length) {
      if (older) els.loadOlder.hidden = true;
      return;
    }
    if (older) {
      // rows are newest-first; prepend each so the oldest ends up on top.
      for (const m of rows) renderMessage(m, { prepend: true });
    } else {
      for (const m of [...rows].reverse()) renderMessage(m);
      scrollToBottom();
    }
    oldestId = rows[rows.length - 1].id;
    els.loadOlder.hidden = rows.length < 50;
  }

  function setPresence(online) {
    els.presence.textContent = `${online.length} online`;
  }

  function renderTyping() {
    const names = [...typingUsers.values()].map((t) => t.username);
    els.typing.textContent = names.length
      ? `${names.join(", ")} ${names.length === 1 ? "is" : "are"} typing…`
      : "";
  }

  function handleTyping(frame) {
    if (frame.user_id === myUserId) return; // ignore self
    const prev = typingUsers.get(frame.user_id);
    if (prev) clearTimeout(prev.timer);
    if (frame.state) {
      const timer = setTimeout(() => {
        typingUsers.delete(frame.user_id);
        renderTyping();
      }, 4000);
      typingUsers.set(frame.user_id, { username: frame.username, timer });
    } else {
      typingUsers.delete(frame.user_id);
    }
    renderTyping();
  }

  function wsUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/api/groups/${groupId}/ws`;
  }

  function connect() {
    socket = new WebSocket(wsUrl());

    socket.addEventListener("open", () => {
      reconnectDelay = 1000;
    });

    socket.addEventListener("message", (ev) => {
      const frame = JSON.parse(ev.data);
      switch (frame.type) {
        case "message":
          renderMessage(frame);
          scrollToBottom();
          break;
        case "edit": {
          const body = document.querySelector(`[data-body="${frame.id}"]`);
          if (body) body.innerHTML = `${escapeHtml(frame.body)} <span class="chat-msg-edited">(edited)</span>`;
          break;
        }
        case "delete": {
          const li = document.getElementById(`msg-${frame.id}`);
          if (li) {
            li.classList.add("is-deleted");
            li.innerHTML = `<span class="chat-msg-deleted">message deleted</span>`;
          }
          break;
        }
        case "presence":
          setPresence(frame.online);
          break;
        case "typing":
          handleTyping(frame);
          break;
        case "error":
          toast(frame.detail || "Message rejected.", { kind: "warn" });
          break;
      }
    });

    socket.addEventListener("close", () => {
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 15000);
    });
  }

  // --- composer ---
  let typingSent = false;
  let typingStopTimer = null;

  function sendTyping(state) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "typing", state }));
    }
  }

  els.input.addEventListener("input", () => {
    if (!typingSent) {
      typingSent = true;
      sendTyping(true);
    }
    clearTimeout(typingStopTimer);
    typingStopTimer = setTimeout(() => {
      typingSent = false;
      sendTyping(false);
    }, 2000);
  });

  function submitMessage() {
    const body = els.input.value.trim();
    if (!body) return;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "send", body }));
      els.input.value = "";
      typingSent = false;
      sendTyping(false);
    }
  }

  els.composer.addEventListener("submit", (e) => {
    e.preventDefault();
    submitMessage();
  });

  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitMessage();
    }
  });

  els.loadOlder.addEventListener("click", () => loadHistory({ older: true }));

  // edit / delete via event delegation
  els.list.addEventListener("click", async (e) => {
    const editId = e.target.getAttribute?.("data-edit");
    const delId = e.target.getAttribute?.("data-delete");
    if (editId) {
      const bodyEl = document.querySelector(`[data-body="${editId}"]`);
      const current = bodyEl ? bodyEl.textContent.replace(/\s*\(edited\)\s*$/, "") : "";
      const next = window.prompt("Edit message:", current);
      if (next != null && next.trim()) {
        try {
          await api.editMessage(groupId, Number(editId), next.trim());
        } catch (err) {
          toast(err.message, { kind: "err" });
        }
      }
    } else if (delId) {
      if (window.confirm("Delete this message?")) {
        try {
          await api.deleteMessage(groupId, Number(delId));
        } catch (err) {
          toast(err.message, { kind: "err" });
        }
      }
    }
  });

  // boot
  try {
    await loadHistory();
  } catch (err) {
    if (err.status === 403) {
      els.title.textContent = "You are not a member of this group";
      toast("Join this group from Discover to chat.", { kind: "warn" });
      return;
    }
    toast(err.message, { kind: "err" });
  }
  connect();
}
```

> **Logout note:** `discover.js` does not wire the `data-logout` button itself,
> so whatever handles it app-wide will handle it on `/chat` too (the nav markup
> is identical). If you find logout is genuinely unwired anywhere, that's a
> pre-existing bug — out of scope for this plan; flag it separately.

- [ ] **Step 3: Manual verification**

Start the server (kill any prior instance first), then drive the page in a browser-like way:

Run:
```bash
cd "C:\Users\ayamu\python-programs\Git-Uploads\suraj"
.venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```
Then, in a browser, log in with a demo account (see README), open `/discover`, join a nearby group, and visit `/chat?group=<id>`. Confirm: history loads, sending a message appears instantly, opening the same group in a second browser/profile shows the message arrive live, presence count updates, typing indicator shows, and edit/delete work.

Expected: messages send and appear; presence/typing/edit/delete all function. **Look at the page** — a blank message list after sending is a failure.

- [ ] **Step 4: Commit**

```bash
git add frontend/chat.html frontend/js/chat.js
git commit -m "feat(chat): chat page (history, live messages, presence, typing, edit/delete)"
```

---

## Task 10: Chat styles

**Files:**
- Modify: `frontend/css/components.css`

- [ ] **Step 1: Inspect existing tokens**

Run: `sed -n '1,40p' frontend/css/tokens.css`
Expected: shows the CSS custom properties (color/space/radius tokens). Use these variable names in the next step instead of hardcoded values where equivalents exist (e.g. `var(--surface)`, `var(--text)`, `var(--accent)`, `var(--radius)` — substitute the actual names you find).

- [ ] **Step 2: Append chat styles**

Append to `frontend/css/components.css` (adjust `var(--…)` names to match what tokens.css actually defines):

```css
/* ---- Group chat ---- */
.chat-page { display: flex; flex-direction: column; gap: 1rem; padding-bottom: 1.5rem; }
.chat-head { display: flex; align-items: center; gap: 1rem; }
.chat-title { font-size: 1.25rem; margin: 0; flex: 1; }
.chat-presence { font-size: 0.85rem; opacity: 0.75; }

.chat-window {
  display: flex; flex-direction: column;
  background: var(--surface, rgba(255,255,255,0.03));
  border: 1px solid var(--border, rgba(255,255,255,0.08));
  border-radius: var(--radius, 14px);
  padding: 0.75rem;
  max-height: 62vh; overflow: hidden;
}
.chat-messages {
  list-style: none; margin: 0; padding: 0.25rem;
  overflow-y: auto; display: flex; flex-direction: column; gap: 0.5rem; flex: 1;
}
.chat-load-older {
  align-self: center; background: none; border: 0;
  color: var(--accent, #6ea8fe); cursor: pointer; font-size: 0.8rem; padding: 0.25rem;
}
.chat-msg { max-width: 78%; padding: 0.4rem 0.6rem; border-radius: 12px;
  background: rgba(255,255,255,0.05); align-self: flex-start; }
.chat-msg.is-mine { align-self: flex-end; background: var(--accent-soft, rgba(110,168,254,0.18)); }
.chat-msg.is-deleted { opacity: 0.5; font-style: italic; }
.chat-msg-meta { display: flex; gap: 0.5rem; align-items: baseline; font-size: 0.72rem; opacity: 0.7; }
.chat-msg-author { font-weight: 600; }
.chat-msg-body { white-space: pre-wrap; word-break: break-word; margin-top: 0.15rem; }
.chat-msg-edited { font-size: 0.7rem; opacity: 0.6; }
.chat-msg-actions { margin-left: auto; display: none; gap: 0.4rem; }
.chat-msg.is-mine:hover .chat-msg-actions { display: inline-flex; }
.chat-link { background: none; border: 0; color: var(--accent, #6ea8fe); cursor: pointer; font-size: 0.7rem; }
.chat-typing { min-height: 1.1rem; font-size: 0.78rem; opacity: 0.7; padding: 0.25rem 0.5rem; }

.chat-composer { display: flex; gap: 0.5rem; align-items: flex-end; }
.chat-composer textarea {
  flex: 1; resize: none; max-height: 140px;
  background: var(--surface, rgba(255,255,255,0.04));
  border: 1px solid var(--border, rgba(255,255,255,0.12));
  border-radius: var(--radius, 12px); color: inherit; padding: 0.6rem 0.75rem; font: inherit;
}
```

- [ ] **Step 3: Manual verification**

Reload `/chat?group=<id>` and confirm the layout looks consistent with the rest of the app (dark glass, accent color), messages align left/right, composer sits at the bottom.

- [ ] **Step 4: Commit**

```bash
git add frontend/css/components.css
git commit -m "feat(chat): chat page styles"
```

---

## Task 11: "Open chat" link on discover

**Files:**
- Modify: `frontend/js/discover.js`

- [ ] **Step 1: Add the chat link inside `renderCard`**

In `frontend/js/discover.js`, the `renderCard(g)` function builds the `action`
button (around lines 149-151). Add a chat link variable right after the `action`
assignment:

```javascript
  const chatLink = g.is_member
    ? `<a class="btn btn-ghost btn-sm" href="/chat?group=${g.id}">Open chat</a>`
    : "";
```

Then, in the returned template's `.group-foot` block, place `chatLink` before
`action` so members get both buttons. Change:

```javascript
      <div class="group-foot">
        <span class="mono dim" style="font-size:0.85rem;">${memberLabel} · radius ${g.radius_km} km</span>
        ${action}
      </div>
```

to:

```javascript
      <div class="group-foot">
        <span class="mono dim" style="font-size:0.85rem;">${memberLabel} · radius ${g.radius_km} km</span>
        <span class="group-actions">${chatLink}${action}</span>
      </div>
```

(The `data-action` join/leave handler is attached via delegation in
`renderGroups` after `innerHTML` is set; the new `<a>` is a plain navigation link
and needs no handler. The `group-actions` span just groups the two buttons — add
`.group-actions { display:inline-flex; gap:0.5rem; }` to `components.css` if they
need spacing.)

- [ ] **Step 2: Manual verification**

Reload `/discover`, join a group, and confirm an "Open chat" button appears on that group's card and navigates to `/chat?group=<id>`.

- [ ] **Step 3: Commit**

```bash
git add frontend/js/discover.js frontend/css/components.css
git commit -m "feat(chat): open-chat link on joined groups"
```

---

## Task 12: Final verification

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS (the original 31 + the new chat tests, ~16 added).

- [ ] **Step 2: End-to-end manual smoke**

With the server running, complete one full loop in the browser: log in → discover → join → open chat → send → edit → delete → open second session → see live delivery + presence + typing. Confirm visually.

- [ ] **Step 3: Final commit (if any stragglers)**

```bash
git status
# commit any remaining intended changes
```

---

## Notes & Known Limitations

- **Single process only.** Presence and broadcast are in-memory; running multiple uvicorn workers/replicas breaks live delivery. See the spec's scaling note (Redis pub/sub upgrade path).
- **Origin/CSWSH rule:** connections with no `Origin` header are allowed (non-browser clients); only a *present and mismatched* Origin is rejected. Browsers always send Origin, so cross-site WebSocket hijacking is still blocked.
- **Rate limit** is per-connection (5 msgs / 2 s), enforced in the WS handler (SlowAPI is HTTP-only and does not cover WebSockets).
```
