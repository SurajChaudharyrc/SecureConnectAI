from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..models import User
from ..schemas import ProfileUpdate, UserPublic

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=UserPublic)
def get_profile(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.patch("", response_model=UserPublic, dependencies=[Depends(require_csrf)])
def update_profile(
    payload: ProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserPublic:
    if payload.full_name is not None:
        current_user.full_name = payload.full_name.strip()
    if payload.interests is not None:
        # Dedupe + cap at 20.
        seen = []
        for item in payload.interests:
            if item not in seen:
                seen.append(item)
            if len(seen) >= 20:
                break
        current_user.interests = seen
    if payload.current_lat is not None:
        current_user.current_lat = payload.current_lat
    if payload.current_lon is not None:
        current_user.current_lon = payload.current_lon
    db.commit()
    db.refresh(current_user)
    return UserPublic.model_validate(current_user)
