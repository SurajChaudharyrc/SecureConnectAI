from backend.app import db as db_module
from backend.app.models import Group, Membership, User
from backend.tests.conftest import register_and_login


def _seed_groups():
    with db_module.SessionLocal() as db:
        db.add_all([
            Group(name="Near Group", niche_type="Social",
                  latitude=26.8467, longitude=80.9462, radius_km=5.0,
                  description="Within 5km of Lucknow center."),
            Group(name="Far Group", niche_type="Social",
                  latitude=48.8566, longitude=2.3522, radius_km=2.0,
                  description="Paris."),
            Group(name="MUJ Alumni", niche_type="Professional",
                  latitude=26.9124, longitude=75.7873, radius_km=10.0,
                  required_domain="muj.manipal.edu",
                  description="Domain-restricted."),
        ])
        db.commit()


def test_discover_proximity(client):
    register_and_login(client, "user_one")
    _seed_groups()
    r = client.get("/api/groups/discover", params={"lat": 26.8467, "lon": 80.9462})
    assert r.status_code == 200
    names = [g["name"] for g in r.json()]
    assert "Near Group" in names
    assert "Far Group" not in names


def test_discover_domain_bypass(client):
    register_and_login(client, "user_two")
    _seed_groups()
    # Promote this user to verified domain manually.
    with db_module.SessionLocal() as db:
        u = db.query(User).filter_by(username="user_two").one()
        u.verified_domain = "muj.manipal.edu"
        db.commit()

    # Stand in Paris — would normally see nothing.
    r = client.get("/api/groups/discover", params={"lat": 48.8566, "lon": 2.3522})
    assert r.status_code == 200
    payload = r.json()
    names = [g["name"] for g in payload]
    assert "MUJ Alumni" in names
    # The MUJ entry should be flagged as a domain match.
    muj = next(g for g in payload if g["name"] == "MUJ Alumni")
    assert muj["domain_match"] is True


def test_low_trust_blocks_discovery(client):
    register_and_login(client, "user_three")
    _seed_groups()
    # Drop trust below the 0.5 threshold.
    with db_module.SessionLocal() as db:
        u = db.query(User).filter_by(username="user_three").one()
        u.trust_score = 0.1
        db.commit()

    r = client.get("/api/groups/discover", params={"lat": 26.8467, "lon": 80.9462})
    assert r.status_code == 403


def test_join_requires_proximity_or_domain(client):
    register_and_login(client, "user_four")
    _seed_groups()
    # No verified domain, no location set on profile => join requires location-in-radius.
    with db_module.SessionLocal() as db:
        muj = db.query(Group).filter_by(name="MUJ Alumni").one()
        muj_id = muj.id

    r = client.post(f"/api/groups/{muj_id}/join")
    assert r.status_code == 403


def test_member_sees_group_even_when_far(client):
    # A member must keep seeing their group in discovery even if their saved
    # location has moved outside the group's radius (regression: location filter
    # used to hide joined groups).
    register_and_login(client, "user_five")
    _seed_groups()
    with db_module.SessionLocal() as db:
        u = db.query(User).filter_by(username="user_five").one()
        near = db.query(Group).filter_by(name="Near Group").one()
        db.add(Membership(user_id=u.id, group_id=near.id))
        db.commit()

    # Stand in Paris — far from the Lucknow "Near Group" — but we're a member.
    r = client.get("/api/groups/discover", params={"lat": 48.8566, "lon": 2.3522})
    assert r.status_code == 200
    item = next((g for g in r.json() if g["name"] == "Near Group"), None)
    assert item is not None, "member should see their group regardless of distance"
    assert item["is_member"] is True
