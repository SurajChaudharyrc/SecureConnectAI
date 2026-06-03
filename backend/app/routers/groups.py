from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user, require_csrf
from ..errors import Conflict, Forbidden, NotFound
from ..models import Group, Membership, User
from ..schemas import DiscoverItem, SimpleMessage
from ..services.geo import haversine_km

router = APIRouter(prefix="/api/groups", tags=["groups"])

MIN_TRUST_FOR_DISCOVERY = 0.5


@router.get("/discover", response_model=list[DiscoverItem])
def discover_groups(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DiscoverItem]:
    if current_user.trust_score < MIN_TRUST_FOR_DISCOVERY:
        raise Forbidden("Trust score is too low to discover groups.")

    member_group_ids = {
        gid for (gid,) in db.execute(
            select(Membership.group_id).where(Membership.user_id == current_user.id)
        )
    }
    member_counts = dict(
        db.execute(
            select(Membership.group_id, func.count(Membership.user_id))
            .group_by(Membership.group_id)
        ).all()
    )

    items: list[DiscoverItem] = []
    user_domain = (current_user.verified_domain or "").lower()
    for group in db.scalars(select(Group)).all():
        dist = haversine_km(lat, lon, group.latitude, group.longitude)
        domain_match = bool(
            group.required_domain and user_domain
            and group.required_domain.lower() == user_domain
        )
        is_member = group.id in member_group_ids

        # Visibility: within proximity OR domain match OR already a member.
        # Members always see (and can re-open chat for) their groups, even if
        # their saved location has since moved out of the group's radius.
        if dist > group.radius_km and not domain_match and not is_member:
            continue

        items.append(
            DiscoverItem(
                id=group.id,
                name=group.name,
                niche_type=group.niche_type,
                description=group.description,
                distance_km=round(dist, 2),
                radius_km=group.radius_km,
                domain_match=domain_match,
                is_member=is_member,
                member_count=int(member_counts.get(group.id, 0)),
            )
        )

    items.sort(key=lambda x: x.distance_km)
    return items


@router.post("/{group_id}/join", response_model=SimpleMessage, dependencies=[Depends(require_csrf)])
def join_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    if current_user.trust_score < MIN_TRUST_FOR_DISCOVERY:
        raise Forbidden("Trust score is too low to join groups.")

    group = db.get(Group, group_id)
    if group is None:
        raise NotFound("Group not found.")

    if group.required_domain:
        user_domain = (current_user.verified_domain or "").lower()
        if user_domain != group.required_domain.lower():
            # Allow proximity-based join only if within radius.
            if current_user.current_lat is None or current_user.current_lon is None:
                raise Forbidden("Set your location or verify the required organization domain.")
            dist = haversine_km(
                current_user.current_lat, current_user.current_lon,
                group.latitude, group.longitude,
            )
            if dist > group.radius_km:
                raise Forbidden("You are outside this group's radius and lack the required organization.")

    existing = db.get(Membership, {"user_id": current_user.id, "group_id": group_id})
    if existing is not None:
        raise Conflict("Already a member.")

    db.add(Membership(user_id=current_user.id, group_id=group_id))
    db.commit()
    return SimpleMessage(message=f"Joined {group.name}.")


@router.post("/{group_id}/leave", response_model=SimpleMessage, dependencies=[Depends(require_csrf)])
def leave_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SimpleMessage:
    membership = db.get(Membership, {"user_id": current_user.id, "group_id": group_id})
    if membership is None:
        raise NotFound("Not a member of that group.")
    db.delete(membership)
    db.commit()
    return SimpleMessage(message="Left the group.")
