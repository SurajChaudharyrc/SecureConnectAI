"""Seed demo data. Idempotent: safe to run multiple times.

Run from project root:
    python -m backend.seed
"""
from __future__ import annotations

from sqlalchemy import select

from .app.db import SessionLocal, init_db
from .app.models import Group, Membership, Message, User
from .app.security import hash_password


# All demo accounts share this password for easy testing.
DEMO_PASSWORD = "DemoPass1234"

DEMO_USERS = [
    {
        "username": "aryan_dev",
        "email": "aryan@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Aryan Sharma",
        "trust_score": 1.6,
        "is_face_verified": True,
        "verified_domain": "muj.manipal.edu",
        "interests": ["Cricket", "Data Science", "Gaming"],
        "current_lat": 26.8467,
        "current_lon": 80.9462,
    },
    {
        "username": "new_user",
        "email": "demo@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Demo Newcomer",
        "trust_score": 1.0,
        "is_face_verified": False,
        "verified_domain": None,
        "interests": ["Photography"],
        "current_lat": 26.8500,
        "current_lon": 80.9500,
    },
    # Extra co-located members so the group chat can be tested with several
    # people. All near Lucknow center so they discover & join the same groups.
    {
        "username": "maya_chen",
        "email": "maya@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Maya Chen",
        "trust_score": 1.3,
        "is_face_verified": True,
        "verified_domain": None,
        "interests": ["Design", "Coffee", "Gaming"],
        "current_lat": 26.8470,
        "current_lon": 80.9465,
    },
    {
        "username": "raj_patel",
        "email": "raj@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Raj Patel",
        "trust_score": 1.2,
        "is_face_verified": True,
        "verified_domain": None,
        "interests": ["Cricket", "Startups"],
        "current_lat": 26.8460,
        "current_lon": 80.9455,
    },
    {
        "username": "sara_k",
        "email": "sara@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Sara Khan",
        "trust_score": 1.1,
        "is_face_verified": False,
        "verified_domain": None,
        "interests": ["Photography", "Travel"],
        "current_lat": 26.8480,
        "current_lon": 80.9470,
    },
    {
        "username": "leo_m",
        "email": "leo@example.com",
        "password": DEMO_PASSWORD,
        "full_name": "Leo Martins",
        "trust_score": 1.0,
        "is_face_verified": False,
        "verified_domain": None,
        "interests": ["Gaming", "Music"],
        "current_lat": 26.8455,
        "current_lon": 80.9450,
    },
]

DEMO_GROUPS = [
    {
        "name": "Lucknow Tech Innovators",
        "niche_type": "Technology",
        "latitude": 26.8467, "longitude": 80.9462, "radius_km": 5.0,
        "description": "Builders, hackers, and curious minds across Lucknow.",
    },
    {
        "name": "Downtown Crypto Meetup",
        "niche_type": "Finance",
        "latitude": 26.8500, "longitude": 80.9500, "radius_km": 2.0,
        "description": "Casual chats on markets, on-chain analysis, and tools.",
    },
    {
        "name": "Remote Worker Network",
        "niche_type": "Social",
        "latitude": 26.8600, "longitude": 80.9600, "radius_km": 10.0,
        "description": "Coworking pop-ups, accountability buddies, monthly coffee.",
    },
    {
        "name": "Cachan Cricket Club",
        "niche_type": "Sports",
        "latitude": 48.7900, "longitude": 2.3300, "radius_km": 5.0,
        "description": "Weekend cricket near Cachan and the southern Paris suburbs.",
    },
    {
        "name": "Delhi Photography Walks",
        "niche_type": "Creative",
        "latitude": 28.6139, "longitude": 77.2090, "radius_km": 10.0,
        "description": "Old Delhi sunrise walks, street portraits, gear swaps.",
    },
    {
        "name": "MUJ Alumni Network",
        "niche_type": "Professional",
        "latitude": 26.9124, "longitude": 75.7873, "radius_km": 50.0,
        "required_domain": "muj.manipal.edu",
        "description": "Open to anyone with a verified @muj.manipal.edu email.",
    },
    # Chat-ready groups: co-located with the demo members above, wide radius so
    # everyone nearby can discover, join, and chat together.
    {
        "name": "SecureConnect Lounge",
        "niche_type": "Social",
        "latitude": 26.8467, "longitude": 80.9462, "radius_km": 25.0,
        "description": "The town square — everyone nearby hangs out and chats here.",
    },
    {
        "name": "Weekend Gamers",
        "niche_type": "Gaming",
        "latitude": 26.8467, "longitude": 80.9462, "radius_km": 25.0,
        "description": "Squad up for weekend sessions and a bit of trash talk.",
    },
]

# (username, group_name) pairs — who is already a member of which chat group.
DEMO_MEMBERSHIPS = [
    ("aryan_dev", "SecureConnect Lounge"),
    ("new_user", "SecureConnect Lounge"),
    ("maya_chen", "SecureConnect Lounge"),
    ("raj_patel", "SecureConnect Lounge"),
    ("sara_k", "SecureConnect Lounge"),
    ("leo_m", "SecureConnect Lounge"),
    ("aryan_dev", "Weekend Gamers"),
    ("maya_chen", "Weekend Gamers"),
    ("raj_patel", "Weekend Gamers"),
    ("leo_m", "Weekend Gamers"),
]

# (group_name, username, body) — starter conversation, seeded only into groups
# that currently have no messages (so re-running does not duplicate them).
DEMO_MESSAGES = [
    ("SecureConnect Lounge", "aryan_dev", "Welcome to the Lounge, everyone! 👋"),
    ("SecureConnect Lounge", "maya_chen", "Hey! Glad to be here."),
    ("SecureConnect Lounge", "raj_patel", "Anyone up for cricket this weekend?"),
    ("SecureConnect Lounge", "sara_k", "Count me in — I'll bring the camera 📸"),
    ("SecureConnect Lounge", "leo_m", "Nice, see you all there."),
    ("Weekend Gamers", "leo_m", "Lobby's up tonight around 9?"),
    ("Weekend Gamers", "maya_chen", "I'm in."),
    ("Weekend Gamers", "aryan_dev", "Same. Loser buys coffee."),
]


def main() -> None:
    init_db()
    with SessionLocal() as db:
        # Users
        for u in DEMO_USERS:
            existing = db.scalars(select(User).where(User.username == u["username"])).first()
            if existing is None:
                db.add(User(
                    username=u["username"],
                    email=u["email"],
                    password_hash=hash_password(u["password"]),
                    full_name=u["full_name"],
                    trust_score=u["trust_score"],
                    is_face_verified=u["is_face_verified"],
                    verified_domain=u["verified_domain"],
                    interests=u["interests"],
                    current_lat=u["current_lat"],
                    current_lon=u["current_lon"],
                ))
            else:
                # Re-pin demo accounts to their canonical location so the demo
                # groups stay discoverable even if "Use my location" moved them.
                existing.current_lat = u["current_lat"]
                existing.current_lon = u["current_lon"]

        # Groups
        for g in DEMO_GROUPS:
            existing = db.scalars(select(Group).where(Group.name == g["name"])).first()
            if existing is None:
                db.add(Group(**g))

        db.commit()

        # Resolve names -> rows now that ids exist.
        users = {u.username: u for u in db.scalars(select(User)).all()}
        groups = {g.name: g for g in db.scalars(select(Group)).all()}

        # Memberships
        for username, group_name in DEMO_MEMBERSHIPS:
            user = users.get(username)
            group = groups.get(group_name)
            if user is None or group is None:
                continue
            if db.get(Membership, {"user_id": user.id, "group_id": group.id}) is None:
                db.add(Membership(user_id=user.id, group_id=group.id))
        db.commit()

        # Starter messages — only for groups that have none yet (idempotent).
        groups_with_messages = {
            gid for (gid,) in db.execute(select(Message.group_id).distinct())
        }
        for group_name, username, body in DEMO_MESSAGES:
            group = groups.get(group_name)
            user = users.get(username)
            if group is None or user is None or group.id in groups_with_messages:
                continue
            db.add(Message(group_id=group.id, user_id=user.id, body=body))
        db.commit()

    print("Seed complete.")
    print("Demo credentials (all use password DemoPass1234):")
    print("  aryan_dev  (verified, MUJ alumni)")
    print("  new_user   (unverified)")
    print("  maya_chen, raj_patel, sara_k, leo_m  (nearby members)")
    print("Chat groups seeded with members + starter messages:")
    print("  'SecureConnect Lounge'  — all 6 demo users")
    print("  'Weekend Gamers'        — aryan_dev, maya_chen, raj_patel, leo_m")


if __name__ == "__main__":
    main()
