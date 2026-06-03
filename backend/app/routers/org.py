import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..models import User, VerificationAttempt
from ..rate_limit import limiter
from ..schemas import OrgConfirm, OrgRequest, SimpleMessage
from ..services.otp import consume_otp, email_matches_domain, issue_otp

router = APIRouter(prefix="/api/verify/org", tags=["verify"])
log = logging.getLogger("secureconnect.org")


@router.post("/request", response_model=SimpleMessage, dependencies=[Depends(require_csrf)])
@limiter.limit("5/hour")
def request_org_otp(
    request: Request,
    payload: OrgRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    if not email_matches_domain(payload.email, payload.domain):
        # Don't leak which arm failed; behave the same as success.
        log.info("org_domain_mismatch", extra={"user_id": current_user.id})
        return SimpleMessage(message="If the email matches the domain, a code has been sent.")

    code = issue_otp(db, email=payload.email, domain=payload.domain)
    # Demo: print to console (replace with real SMTP in prod).
    print(f"\n=== MOCK ORG OTP for {payload.email}: {code} (expires in 10 min) ===\n", flush=True)
    return SimpleMessage(message="If the email matches the domain, a code has been sent.")


@router.post("/confirm", response_model=SimpleMessage, dependencies=[Depends(require_csrf)])
@limiter.limit("10/hour")
def confirm_org_otp(
    request: Request,
    payload: OrgConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    ip = request.client.host if request.client else None
    verified_domain = consume_otp(db, email=payload.email, code=payload.code)
    success = verified_domain is not None

    db.add(VerificationAttempt(user_id=current_user.id, kind="org", success=success, ip=ip))

    if not success:
        db.commit()
        return SimpleMessage(message="Code did not match or has expired.")

    current_user.verified_domain = verified_domain
    current_user.trust_score = min(5.0, current_user.trust_score + 0.3)
    db.commit()
    return SimpleMessage(message=f"Organization verified for {verified_domain}.")
