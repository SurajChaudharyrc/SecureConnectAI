# Chat: Scalability, Refactor & Design — Design Spec

**Date:** 2026-05-29
**Status:** Approved (scopes chosen; user waived per-section confirmation — execute autonomously)
**Builds on:** `2026-05-29-group-chat-design.md`

## Summary

Three improvements to the group-chat feature, executed as one spec in two phases:

1. **Scalability — pluggable broker (ship in-memory).** Put the connection/fan-out
   layer behind an async `ChatBroker` interface so a Redis-backed implementation
   can drop in later as a config change, not a rewrite. Plus in-place hardening
   (inbound-frame rate limiting incl. typing, per-group connection cap,
   config-driven limits).
2. **Refactor — targeted.** Split chat out of `routers/groups.py` (now 339 lines,
   two responsibilities) into `routers/chat.py` + the chat service, and decompose
   the long WS handler into small, testable functions.
3. **Design — chat page + Discover polish.** Elevate the newest surfaces while
   keeping the existing dark-glass aesthetic: message grouping, avatar initials,
   day dividers, empty state, auto-growing composer with counter, touch-friendly
   message actions, nicer presence/typing, and cleaner Discover member-card actions.

**Non-negotiable invariant:** all existing chat URLs and WS protocol stay byte-for-byte
identical (frontend + 46 passing tests depend on them). The refactor is internal only.

## Phase 1 — Backend

### 1A. `ChatBroker` abstraction (`backend/app/services/chat.py`)

Replace the concrete `ConnectionManager` with an abstract async interface plus an
in-memory implementation. Async is the lowest common denominator so a future
network-backed broker drops in without changing call sites.

```python
@dataclass(eq=False)
class Connection:
    websocket: Any
    user_id: int
    username: str

class ChatBroker(ABC):
    @abstractmethod
    async def connect(self, group_id: int, conn: Connection) -> None: ...
    @abstractmethod
    async def disconnect(self, group_id: int, conn: Connection) -> None: ...
    @abstractmethod
    async def broadcast(self, group_id: int, payload: dict) -> None: ...
    @abstractmethod
    async def presence(self, group_id: int) -> list[dict]: ...
    @abstractmethod
    async def socket_count(self, group_id: int) -> int: ...

class InMemoryChatBroker(ChatBroker):
    """Single-process, in-memory. Presence/fan-out live in this process's
    memory, so it only works with one worker. A RedisChatBroker implementing
    the same interface enables horizontal scale without touching call sites."""
    # current ConnectionManager logic, methods made async
```

Factory + module singleton:

```python
def build_broker(kind: str = "memory") -> ChatBroker:
    if kind == "memory":
        return InMemoryChatBroker()
    raise ValueError(f"unknown CHAT_BROKER: {kind!r}")  # 'redis' added later

broker: ChatBroker = build_broker(get_settings().chat_broker)
```

The old `manager` name is retired; call sites use `broker`. `presence()` dedups by
`user_id` (a user with two sockets shows once). `socket_count()` returns the raw
live-socket count for cap enforcement. `broadcast()` still copies the connection set,
sends to each, and reaps dead sockets.

### 1B. Config knobs (`backend/app/config.py`)

Add to `Settings` (all overridable via env, sensible defaults):

```python
chat_broker: str = "memory"               # 'memory' | (future) 'redis'
chat_max_message_len: int = 2000
chat_send_rate_max: int = 5               # max sends per window per connection
chat_send_rate_window_s: float = 2.0
chat_frame_rate_max: int = 30             # max ANY inbound frames per window (flood guard)
chat_frame_rate_window_s: float = 5.0
chat_max_connections_per_group: int = 200
```

### 1C. `routers/chat.py` (new) — owns all chat endpoints

Moves out of `groups.py`, keeping the `/api/groups` prefix so URLs are unchanged:
- `GET  /api/groups/{group_id}/messages` (history; member-gated; cursor pagination)
- `PATCH  /api/groups/{group_id}/messages/{msg_id}` (edit own; CSRF; broadcast `edit`)
- `DELETE /api/groups/{group_id}/messages/{msg_id}` (soft-delete own; CSRF; broadcast `delete`)
- `WS   /api/groups/{group_id}/ws` (live stream)

Helpers move here (or to the service): `_resolve_ws_user`, `_serialize_message`,
`_require_membership`. A small reusable rate limiter:

```python
class RateLimiter:
    def __init__(self, max_events: int, window_s: float): ...
    def allow(self) -> bool:
        """Sliding window over time.monotonic(); True if under cap, else False."""
```

WS handler decomposed:
- `async def _authorize_ws(websocket, db, group_id) -> User | None` — Origin/CSWSH
  check, session-cookie auth, membership check; closes with `4403`/`4401` and
  returns `None` on failure.
- `async def _handle_send(websocket, db, group_id, user, data, send_limiter)` —
  validate (non-empty, ≤ max len), send-rate-limit, persist, broadcast `message`.
- `async def _handle_typing(group_id, user, data)` — broadcast `typing`.
- `group_ws` orchestrates: authorize → connection-cap check (`socket_count` ≥ cap →
  close `4429`) → accept → connect → presence broadcast → receive loop (per-frame
  flood limiter; dispatch on type) → finally disconnect + presence broadcast.

`routers/groups.py` shrinks to discover/join/leave only. `_require_membership`
moves to chat (groups' join/leave use their own inline checks).

### 1D. `main.py`

Register the new router: `app.include_router(chat.router)` next to `groups.router`.

### 1E. Tests

- Update the broker unit test: `InMemoryChatBroker`, async `connect`/`disconnect`/
  `presence`/`socket_count` (awaited; `asyncio_mode=auto`).
- Add unit tests: `RateLimiter` (allows up to N in window, blocks beyond), broker
  `socket_count`.
- Add WS tests: typing frames don't trip the send limiter; a flood of frames is
  bounded (frame limiter) without crashing; connection-cap close (use a low cap via
  monkeypatched settings or a dedicated broker instance).
- All existing chat + group tests must still pass unchanged (URLs/protocol identical).

## Phase 2 — Frontend (chat page + Discover polish; dark-glass preserved)

Files: `frontend/js/chat.js`, `frontend/chat.html`, `frontend/css/components.css`,
`frontend/js/discover.js` (+ shared initials helper, possibly into `ui.js`).

1. **Message grouping** — consecutive messages from the same author within 5 minutes
   render as one block: first shows avatar + author + time; followers show only the
   body, tightly spaced. Day boundaries always break a group.
2. **Avatar initials** — circular badge with the author's initials; background color
   derived deterministically from the username (hash → hue). Reuse/extract the
   `initials()` logic currently in `profile.js` into `ui.js`.
3. **Day dividers** — a centered "Today" / "Yesterday" / `D MMM YYYY` separator when
   the calendar day changes between messages.
4. **Empty state** — when a group has no messages, show a friendly placeholder
   ("No messages yet — say hello 👋") instead of a blank window.
5. **Composer** — textarea auto-grows with content (capped); Send disabled when
   empty; a subtle character counter appears when within 100 of the 2000 limit;
   Enter sends, Shift+Enter newlines (unchanged).
6. **Touch-friendly actions** — replace hover-only edit/delete with a small "⋯"
   kebab button (always present on own messages) that toggles an actions menu;
   works on touch. Keyboard-focusable.
7. **Presence & typing** — presence shows a small avatar stack + "N online"; typing
   indicator uses animated dots and names ("Alice is typing…").
8. **Discover** — member cards group "Open chat" (primary) + "Leave" (ghost) in a
   tidy action row (`.group-actions`); subtle "Member" emphasis. Minimal, consistent
   with existing card styling.

Verification: `node --check` all touched JS; live smoke against the running server
(seeded multi-user data); visual reasoning on rendered output. No automated UI test
framework exists in this project (out of scope to add one).

## Sequencing

Backend Phase 1 first (behavior-preserving refactor + broker + hardening, fully test-
gated and green), then Phase 2 frontend. Frontend depends only on the unchanged HTTP/WS
contract, so it is insulated from the refactor.

## Out of scope

- Actually implementing `RedisChatBroker` (only the seam + factory).
- Postgres / multi-worker deployment config.
- Adding a JS test framework.
- Reworking pages other than chat and Discover.
