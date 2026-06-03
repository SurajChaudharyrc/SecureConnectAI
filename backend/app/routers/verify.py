import logging

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..models import User, VerificationAttempt
from ..rate_limit import limiter
from ..schemas import FaceVerifyResponse
from ..services.face import verify_faces
from ..services.uploads import save_image_safely

router = APIRouter(prefix="/api/verify", tags=["verify"])
log = logging.getLogger("secureconnect.verify")


def _record_attempt(db: Session, user_id: int | None, kind: str, success: bool, ip: str | None) -> None:
    db.add(VerificationAttempt(user_id=user_id, kind=kind, success=success, ip=ip))
    db.commit()


def _bump_trust(user: User, delta: float) -> None:
    user.trust_score = max(0.0, min(5.0, user.trust_score + delta))


@router.post(
    "/face",
    response_model=FaceVerifyResponse,
    dependencies=[Depends(require_csrf)],
)
@limiter.limit("3/minute")
async def verify_face(
    request: Request,
    id_image: UploadFile = File(...),
    selfie: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FaceVerifyResponse:
    saved_id = await save_image_safely(id_image)
    saved_selfie = await save_image_safely(selfie)

    ip = request.client.host if request.client else None
    try:
        result = verify_faces(saved_id.path, saved_selfie.path)
    finally:
        saved_id.cleanup()
        saved_selfie.cleanup()

    if result.verified:
        current_user.is_face_verified = True
        _bump_trust(current_user, +0.2)
        db.commit()
        _record_attempt(db, current_user.id, "face", True, ip)
        return FaceVerifyResponse(
            verified=True,
            confidence=result.confidence,
            trust_score=current_user.trust_score,
            detail=None,
        )

    _bump_trust(current_user, -0.1)
    db.commit()
    _record_attempt(db, current_user.id, "face", False, ip)
    return FaceVerifyResponse(
        verified=False,
        confidence=result.confidence,
        trust_score=current_user.trust_score,
        detail=result.detail or "Verification failed.",
    )
