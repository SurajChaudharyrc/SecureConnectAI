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


async def test_in_memory_broker_presence_and_socket_count():
    from backend.app.services.chat import Connection, InMemoryChatBroker

    b = InMemoryChatBroker()
    c1 = Connection(websocket=None, user_id=1, username="a")
    c2 = Connection(websocket=None, user_id=1, username="a")  # same user, 2nd socket
    c3 = Connection(websocket=None, user_id=2, username="b")

    await b.connect(5, c1)
    await b.connect(5, c2)
    await b.connect(5, c3)
    # Presence dedups by user_id; socket_count is the raw socket total.
    assert {o["user_id"] for o in await b.presence(5)} == {1, 2}
    assert await b.socket_count(5) == 3

    await b.disconnect(5, c1)  # user 1 still has c2
    assert {o["user_id"] for o in await b.presence(5)} == {1, 2}
    assert await b.socket_count(5) == 2

    await b.disconnect(5, c2)
    assert {o["user_id"] for o in await b.presence(5)} == {2}

    await b.disconnect(5, c3)
    assert await b.presence(5) == []
    assert await b.socket_count(5) == 0


def test_rate_limiter_allows_then_blocks():
    from backend.app.routers.chat import RateLimiter

    rl = RateLimiter(max_events=3, window_s=100.0)  # huge window: no expiry mid-test
    assert [rl.allow() for _ in range(5)] == [True, True, True, False, False]


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


def test_ws_typing_does_not_trip_send_limit(client):
    # Typing frames must not consume the send rate budget (regression guard:
    # the limiter used to cover only `send`, but a separate concern now).
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        _recv_type(ws, "presence")
        for _ in range(8):  # more than chat_send_rate_max (5)
            ws.send_json({"type": "typing", "state": True})
        # A normal send afterwards still succeeds (send budget untouched).
        ws.send_json({"type": "send", "body": "hi"})
        assert _recv_type(ws, "message")["body"] == "hi"


def test_ws_connection_cap_rejects_extra_socket(client, monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_max_connections_per_group", 1)
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws1:
        _recv_type(ws1, "presence")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/groups/{gid}/ws") as ws2:
                ws2.receive_json()


def test_ws_per_user_connection_cap(client, monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_max_connections_per_user", 1)
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws1:
        _recv_type(ws1, "presence")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/groups/{gid}/ws") as ws2:
                ws2.receive_json()


def test_ws_malformed_frame_does_not_crash_socket(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        _recv_type(ws, "presence")
        ws.send_text("this is not json")
        assert _recv_type(ws, "error")["detail"] == "Invalid frame."
        # Socket survived: a subsequent valid send still works.
        ws.send_json({"type": "send", "body": "still alive"})
        assert _recv_type(ws, "message")["body"] == "still alive"


def test_ws_edit_and_delete_broadcast_to_others(client):
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws1, \
            client.websocket_connect(f"/api/groups/{gid}/ws") as ws2:
        _recv_type(ws1, "presence")
        _recv_type(ws2, "presence")
        ws1.send_json({"type": "send", "body": "original"})
        mid = _recv_type(ws1, "message")["id"]

        r = client.patch(f"/api/groups/{gid}/messages/{mid}", json={"body": "edited"})
        assert r.status_code == 200, r.text
        ef = _recv_type(ws2, "edit")
        assert ef["id"] == mid and ef["body"] == "edited" and ef["edited_at"]

        r = client.delete(f"/api/groups/{gid}/messages/{mid}")
        assert r.status_code == 200, r.text
        df = _recv_type(ws2, "delete")
        assert df["id"] == mid and df["deleted_at"]


def test_ws_send_after_leaving_group_closes_socket(client):
    # Authorization is re-validated per send against a fresh session, so a user
    # who leaves mid-session loses write access immediately (not only on reconnect).
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as ws:
        _recv_type(ws, "presence")
        r = client.post(f"/api/groups/{gid}/leave")
        assert r.status_code == 200, r.text
        ws.send_json({"type": "send", "body": "no longer allowed"})
        with pytest.raises(WebSocketDisconnect):
            for _ in range(5):
                ws.receive_json()


async def test_broker_reaps_dead_socket_on_broadcast():
    from backend.app.services.chat import Connection, InMemoryChatBroker

    class DeadWS:
        async def send_json(self, payload):
            raise RuntimeError("socket closed")

    class LiveWS:
        def __init__(self):
            self.received = []

        async def send_json(self, payload):
            self.received.append(payload)

    broker = InMemoryChatBroker()
    live_ws = LiveWS()
    dead = Connection(websocket=DeadWS(), user_id=1, username="a")
    live = Connection(websocket=live_ws, user_id=2, username="b")
    await broker.connect(7, dead)
    await broker.connect(7, live)
    assert await broker.socket_count(7) == 2

    await broker.broadcast(7, {"type": "message", "body": "x"})

    # The failing socket is reaped; the healthy one received the payload.
    assert live_ws.received == [{"type": "message", "body": "x"}]
    assert await broker.socket_count(7) == 1
    assert {o["user_id"] for o in await broker.presence(7)} == {2}


async def test_try_connect_enforces_caps():
    from backend.app.services.chat import Connection, InMemoryChatBroker

    broker = InMemoryChatBroker()
    a1 = Connection(websocket=None, user_id=1, username="a")
    a2 = Connection(websocket=None, user_id=1, username="a")
    b1 = Connection(websocket=None, user_id=2, username="b")
    # Per-user cap = 1: second socket for user 1 is refused.
    assert await broker.try_connect(5, a1, max_group=10, max_user=1) is True
    assert await broker.try_connect(5, a2, max_group=10, max_user=1) is False
    # A different user still fits under the group cap.
    assert await broker.try_connect(5, b1, max_group=10, max_user=1) is True
    # Per-group cap = 2 now reached.
    c1 = Connection(websocket=None, user_id=3, username="c")
    assert await broker.try_connect(5, c1, max_group=2, max_user=1) is False


def test_ws_broadcast_reaches_other_connections(client):
    # A message sent on one connection must fan out to every other connection
    # in the group. We use two concurrent sockets on a single TestClient so
    # both server coroutines share one event loop — Starlette gives each
    # TestClient its own loop, and the in-process manager's cross-socket
    # `await send_json` cannot wake a receiver parked on a different loop.
    register_and_login(client, "alice")
    gid = _make_group()
    _join(gid, "alice")
    with client.websocket_connect(f"/api/groups/{gid}/ws") as wsa, \
            client.websocket_connect(f"/api/groups/{gid}/ws") as wsb:
        _recv_type(wsa, "presence")
        _recv_type(wsb, "presence")
        wsa.send_json({"type": "send", "body": "hi there"})
        # The other connection receives the broadcast message frame.
        assert _recv_type(wsb, "message")["body"] == "hi there"


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
