"""Chat connection/fan-out layer behind a pluggable broker interface.

`ChatBroker` is an async interface for tracking live WebSocket connections,
broadcasting messages, and reporting presence. The shipped implementation,
`InMemoryChatBroker`, keeps everything in this process's memory — so presence
and fan-out only work with a single worker.

`CHAT_BROKER` selects the implementation, and the async interface is the seam
that makes a network-backed broker possible. To be honest about scope, though,
horizontal scale is more than "swap the class": a real `RedisChatBroker` would
add a per-worker subscribe loop (each worker holds its own live, non-serializable
`Connection` sockets and must receive PUBLISHes to fan out locally), a shared
presence store, and — separately — a shared store for the SlowAPI rate limiter
(currently in-memory) plus a real database (SQLite cannot back multi-worker
writes). The interface keeps the call sites stable; it does not by itself make
the system multi-worker.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from ..config import get_settings


@dataclass(eq=False)
class Connection:
    """One live socket. `eq=False` keeps it identity-hashable for use in a set
    (two sockets for the same user are distinct connections)."""

    websocket: Any  # starlette.websockets.WebSocket (None in unit tests)
    user_id: int
    username: str


class ChatBroker(ABC):
    """Tracks connections and delivers messages for group chat."""

    @abstractmethod
    async def connect(self, group_id: int, conn: Connection) -> None: ...

    @abstractmethod
    async def disconnect(self, group_id: int, conn: Connection) -> None: ...

    @abstractmethod
    async def broadcast(self, group_id: int, payload: dict[str, Any]) -> None: ...

    @abstractmethod
    async def presence(self, group_id: int) -> list[dict[str, Any]]:
        """Distinct online users in the group (deduped by user_id)."""

    @abstractmethod
    async def socket_count(self, group_id: int) -> int:
        """Raw count of live sockets in the group (for connection caps)."""

    @abstractmethod
    async def try_connect(
        self, group_id: int, conn: Connection, max_group: int, max_user: int
    ) -> bool:
        """Atomically connect iff under both the per-group and per-user socket
        caps. Returns True on success, False if either cap is reached. Atomic
        (no await between the checks and the add) so concurrent handshakes
        cannot both slip past the cap."""


class InMemoryChatBroker(ChatBroker):
    """Single-process, in-memory broker.

    Mutations (connect/disconnect) never yield mid-operation under asyncio, so
    no lock is needed; only broadcast awaits (it sends on sockets).
    """

    def __init__(self) -> None:
        self._groups: dict[int, set[Connection]] = {}

    async def connect(self, group_id: int, conn: Connection) -> None:
        self._groups.setdefault(group_id, set()).add(conn)

    async def disconnect(self, group_id: int, conn: Connection) -> None:
        conns = self._groups.get(group_id)
        if conns is None:
            return
        conns.discard(conn)
        if not conns:
            self._groups.pop(group_id, None)

    async def presence(self, group_id: int) -> list[dict[str, Any]]:
        seen: dict[int, str] = {}
        for c in self._groups.get(group_id, set()):
            seen[c.user_id] = c.username
        return [{"user_id": uid, "username": un} for uid, un in seen.items()]

    async def socket_count(self, group_id: int) -> int:
        return len(self._groups.get(group_id, ()))

    async def try_connect(
        self, group_id: int, conn: Connection, max_group: int, max_user: int
    ) -> bool:
        conns = self._groups.setdefault(group_id, set())
        if len(conns) >= max_group:
            if not conns:
                self._groups.pop(group_id, None)
            return False
        if sum(1 for c in conns if c.user_id == conn.user_id) >= max_user:
            if not conns:
                self._groups.pop(group_id, None)
            return False
        conns.add(conn)
        return True

    async def broadcast(self, group_id: int, payload: dict[str, Any]) -> None:
        dead: list[Connection] = []
        for c in list(self._groups.get(group_id, set())):
            try:
                await c.websocket.send_json(payload)
            except Exception:
                dead.append(c)
        for c in dead:
            await self.disconnect(group_id, c)


def build_broker(kind: str = "memory") -> ChatBroker:
    """Select a broker implementation by name (from the CHAT_BROKER setting)."""
    if kind == "memory":
        return InMemoryChatBroker()
    # A 'redis' implementation can be added here without touching call sites.
    raise ValueError(f"unknown CHAT_BROKER: {kind!r}")


# Module-level singleton used by the chat router.
broker: ChatBroker = build_broker(get_settings().chat_broker)
