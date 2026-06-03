# Group Chat — Design Spec

**Date:** 2026-05-29
**Status:** Approved (pre-implementation)
**Author:** brainstormed with user

## Summary

Add real-time text chat to SecureConnect-AI's existing groups. Each group already
supports trust/geo/domain-gated discovery and join/leave via `Group` + `Membership`.
This feature adds a **flat (WhatsApp-style) chat stream per group** — one room per
group, delivered over **WebSockets** for true real-time, with persisted history and
soft-deletable / editable messages, online presence, and typing indicators.

Access is inherited from the existing membership model: **you must be a member of a
group to read or post in its chat.** Joining is already trust- and geo/domain-gated,
so the chat needs no new gating logic of its own.

### Decisions locked during brainstorming

- **Structure:** Flat chat — one stream per group (not Discord-style channels).
- **Transport:** WebSockets (true real-time push), not polling/SSE.
- **Features in v1:** text + history, online presence, typing indicators, edit/delete
  own messages.
- **Connection state:** in-process in-memory connection manager (no Redis/broker).
- **Send path:** sender's own message is **echoed by the server** after persistence
  (no client-side optimistic insert).
- **Split:** history load + edit + delete = REST; live new-messages + typing +
  presence = WebSocket.

## Non-goals (explicitly out of scope for v1)

- Channels / sub-rooms within a group.
- Attachments, images, files, voice.
- Read receipts, reactions, threads, mentions, search.
- Multi-process / horizontally-scaled deployment (see Scaling note).
- Message moderation / admin tools.

## Architecture

### Connection manager (in-process)

A single in-memory structure living in the FastAPI process:

```
group_id -> set[Connection]
```

where each `Connection` wraps a live WebSocket plus its `user_id`/`username`. On
`send`, the message is written to SQLite and then fanned out to every connection in
that group's set (including the sender). Presence is derived from the set: a user is
"online" in a group if they have ≥1 live socket there.

- ✅ Zero new infra; fits the single-process SQLite app.
- ⚠️ **Single-process only.** State is in memory, so presence and fan-out break under
  multiple workers/replicas.

**Scaling note (future):** to run >1 process, replace the in-process broadcast with a
Redis pub/sub channel per group and a shared presence store. The connection manager's
public interface (`connect`, `disconnect`, `broadcast`, `online_for`) should be kept
narrow so this swap is localized.

## Data model

One new table, `messages`:

| column       | type                | notes                                                        |
|--------------|---------------------|--------------------------------------------------------------|
| `id`         | int PK              |                                                              |
| `group_id`   | FK → groups (CASCADE) | indexed                                                    |
| `user_id`    | FK → users (SET NULL) | author; nullable so deleting a user preserves history      |
| `body`       | String(2000)        | text, length-capped at 2000 chars                            |
| `created_at` | datetime (tz), indexed | ordering + cursor pagination                              |
| `edited_at`  | datetime (tz), nullable | set when edited                                           |
| `deleted_at` | datetime (tz), nullable | soft-delete; row retained, body suppressed in responses   |

Soft-delete keeps the stream coherent ("this message was deleted") and avoids holes in
pagination. A deleted message is returned in history as a tombstone with its `body`
suppressed.

## API surface

All endpoints live on the existing `/api/groups` router and reuse the existing
session-cookie auth, CSRF protection, and member checks.

### REST

| method   | path                                            | purpose                                                                 |
|----------|-------------------------------------------------|-------------------------------------------------------------------------|
| `GET`    | `/api/groups/{id}/messages?before=<id>&limit=50` | History, newest-first, cursor-paginated via `before` (message id). Members only. `limit` capped (e.g. ≤100). |
| `PATCH`  | `/api/groups/{id}/messages/{msg_id}`            | Edit own message (CSRF). Sets `edited_at`, broadcasts an `edit` event.   |
| `DELETE` | `/api/groups/{id}/messages/{msg_id}`            | Soft-delete own message (CSRF). Sets `deleted_at`, broadcasts a `delete` event. |

Edit/delete on a message not authored by the caller → `403 Forbidden`.
Edit/delete of an already-deleted message → `404`/`409` as appropriate.

### WebSocket

- `WS /api/groups/{id}/ws` — the live connection for one group.
- **Handshake auth:** resolve the session cookie → user; verify membership.
  - Not authenticated → close `4401`.
  - Authenticated but not a member → close `4403`.
- **CSWSH protection:** validate the `Origin` header against the app's allowed origins
  (cookies auto-attach to WebSocket connects, so Origin must be checked). Reject
  mismatches before accepting.

**Rationale for the REST/WS split:** history, edit, and delete are request/response
shaped and benefit from the existing CSRF path → REST. The WebSocket carries only the
live stream (new messages, typing, presence) and *notifications* of edits/deletes so
other connected clients update their view.

## WebSocket protocol

JSON frames, each tagged with `type`.

### Client → server

```jsonc
{ "type": "send",   "body": "hello" }   // post a new message
{ "type": "typing", "state": true }     // true = started typing, false = stopped
```

### Server → client

```jsonc
{ "type": "message",  "id": 1, "group_id": 7, "user_id": 3, "username": "aryan_dev", "body": "hi", "created_at": "…" }
{ "type": "edit",     "id": 1, "body": "edited text", "edited_at": "…" }
{ "type": "delete",   "id": 1, "deleted_at": "…" }
{ "type": "typing",   "user_id": 3, "username": "aryan_dev", "state": true }
{ "type": "presence", "online": [ { "user_id": 3, "username": "aryan_dev" } ] }
{ "type": "error",    "detail": "…" }
```

### Behavior

- **On connect:** add socket to the group's set → broadcast updated `presence` to the
  group. Client loads history separately via the REST history endpoint.
- **On `send`:** validate (member, non-empty after trim, ≤2000 chars, **rate-limit
  ~5 msgs / 2s per connection**) → persist row → broadcast `message` to all connections
  in the group, including the sender (server echo confirms persistence).
- **On `typing`:** broadcast to *others* only; not persisted. Server auto-expires a
  user's typing state after a few seconds if not refreshed.
- **On disconnect:** remove socket → broadcast updated `presence`.
- **Validation failures** over WS → send an `error` frame (do not drop the connection
  for ordinary validation errors; reserve closing for auth/protocol violations).
- Presence and typing are **best-effort, in-memory only**, never persisted, and reset
  on server restart (acceptable).

## Frontend

- **New page `chat.html`** (`chat.html?group=<id>`): same nav/header/CSS shell as the
  other pages (`tokens.css`/`base.css`/`components.css`/`pages.css`).
- **`discover.html`:** each group the user is *already a member of* gets an
  **"Open chat"** action linking to `chat.html?group=<id>`.
- **New `js/chat.js`:**
  - On load: `GET /api/groups/{id}/messages` → render newest-at-bottom; scroll-up
    triggers `before=` pagination ("load older").
  - Open `WS /api/groups/{id}/ws`; dispatch on the event types above.
  - Composer textarea → `send` over WS (Enter sends, Shift+Enter newline); debounced
    `typing` events.
  - Own messages expose edit/delete affordances → REST PATCH/DELETE; UI updates when
    the `edit`/`delete` broadcast echoes back.
  - Presence pill ("N online") + typing line ("Alice is typing…").
  - Auto-reconnect with backoff on socket drop.
  - Deleted messages render as a muted tombstone; edited messages show an "(edited)" tag.
- **`js/api.js`:** add message REST helpers + a WS-URL builder (`ws`/`wss` chosen from
  page protocol).
- **CSS:** chat layout (scrolling message list, bubbles, sticky composer, presence)
  added to `components.css`/`pages.css` using existing design tokens.

## Testing

Extend the existing pytest suite (31 passing) using FastAPI `TestClient`
(`websocket_connect`).

**Access control**
- Non-member rejected at WS handshake (`4403`) and on REST history/edit/delete.
- Unauthenticated (no session cookie) rejected (`4401`).
- WS connect with a bad/foreign `Origin` rejected (CSWSH guard).

**Messaging**
- `send` over WS persists a row and broadcasts to a second connected member's socket.
- History endpoint returns newest-first, respects `before` cursor + `limit`.
- Body validation: empty rejected, >2000 chars rejected, rate-limit trips after burst.

**Edit / delete**
- Author can edit/delete own message → `edited_at`/`deleted_at` set, broadcast received.
- Non-author gets `403` editing/deleting another user's message.
- Deleted message renders as tombstone in history (body suppressed, row retained).

## Build summary

- 1 new table: `messages` (+ migration via existing `Base.metadata.create_all` pattern).
- 1 new WS endpoint + 3 REST endpoints on the existing groups router.
- 1 new in-process connection-manager service (`services/chat.py` or similar).
- New `chat.html` + `js/chat.js` + CSS additions.
- ~10 new tests.
