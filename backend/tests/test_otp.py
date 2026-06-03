from datetime import datetime, timedelta, timezone

from backend.app import db as db_module
from backend.app.models import OrgOtp
from backend.app.services.otp import (
    MAX_ATTEMPTS,
    consume_otp,
    email_matches_domain,
    issue_otp,
)


def test_email_domain_match():
    assert email_matches_domain("aryan@muj.manipal.edu", "muj.manipal.edu") is True
    assert email_matches_domain("Aryan@MUJ.Manipal.Edu", "muj.manipal.edu") is True
    assert email_matches_domain("aryan@evil.com", "muj.manipal.edu") is False
    assert email_matches_domain("", "muj.manipal.edu") is False
    assert email_matches_domain("aryan@muj.manipal.edu", "bad domain") is False


def test_otp_happy_path(client):
    with db_module.SessionLocal() as db:
        code = issue_otp(db, "x@example.com", "example.com")
        verified = consume_otp(db, "x@example.com", code)
        assert verified == "example.com"


def test_otp_wrong_code(client):
    with db_module.SessionLocal() as db:
        issue_otp(db, "y@example.com", "example.com")
        assert consume_otp(db, "y@example.com", "000000") is None


def test_otp_single_use(client):
    with db_module.SessionLocal() as db:
        code = issue_otp(db, "z@example.com", "example.com")
        assert consume_otp(db, "z@example.com", code) == "example.com"
        assert consume_otp(db, "z@example.com", code) is None


def test_otp_expired(client):
    with db_module.SessionLocal() as db:
        code = issue_otp(db, "exp@example.com", "example.com")
        otp = db.query(OrgOtp).filter_by(email="exp@example.com").one()
        otp.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        assert consume_otp(db, "exp@example.com", code) is None


def test_otp_attempts_capped(client):
    with db_module.SessionLocal() as db:
        code = issue_otp(db, "cap@example.com", "example.com")
        for _ in range(MAX_ATTEMPTS):
            consume_otp(db, "cap@example.com", "000000")
        assert consume_otp(db, "cap@example.com", code) is None
