from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sql_delete
from ..database import get_db
from ..models import Community, User, OnboardingMessage, CommunityMembership, CommunityMessage
from ..deps import get_current_user
from ..services.clustering import recluster_all
from ..services.community_status import compute_status
from ..services.announcements import fetch_and_store_announcements, get_today_announcements

router = APIRouter(prefix="/api/communities", tags=["communities"])


class LeaveBody(BaseModel):
    community_id: str


@router.get("/")
async def list_communities(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Community))
    communities = result.scalars().all()

    out = []
    for c in communities:
        count_result = await db.execute(
            select(func.count(CommunityMembership.user_id)).where(
                CommunityMembership.community_id == c.id
            )
        )
        count = count_result.scalar() or 0
        mem_check = await db.execute(
            select(CommunityMembership).where(
                CommunityMembership.user_id == current_user.id,
                CommunityMembership.community_id == c.id,
            )
        )
        out.append({
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "member_count": count,
            "is_mine": mem_check.scalar_one_or_none() is not None,
        })
    return out


@router.get("/memberships")
async def my_memberships(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all communities the current user belongs to."""
    result = await db.execute(
        select(Community)
        .join(CommunityMembership, CommunityMembership.community_id == Community.id)
        .where(CommunityMembership.user_id == current_user.id)
        .order_by(CommunityMembership.joined_at)
    )
    communities = result.scalars().all()
    out = []
    for c in communities:
        real_count = (await db.execute(
            select(func.count(CommunityMembership.user_id)).where(CommunityMembership.community_id == c.id)
        )).scalar() or 0
        last_msg = (await db.execute(
            select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == c.id)
        )).scalar()
        out.append({
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "status": compute_status(last_msg, real_count, c.status_override),
        })
    return out


@router.get("/mine")
async def my_community(
    community_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_id = community_id or (str(current_user.community_id) if current_user.community_id else None)
    if not target_id:
        raise HTTPException(status_code=404, detail="Not assigned to a community yet")

    # Verify membership
    mem_check = await db.execute(
        select(CommunityMembership).where(
            CommunityMembership.user_id == current_user.id,
            CommunityMembership.community_id == UUID(target_id),
        )
    )
    if not mem_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this community")

    result = await db.execute(select(Community).where(Community.id == UUID(target_id)))
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    members_result = await db.execute(
        select(User).where(User.community_id == community.id, User.is_digital.is_(True))
    )
    digital_members = members_result.scalars().all()

    real_result = await db.execute(
        select(User)
        .join(CommunityMembership, CommunityMembership.user_id == User.id)
        .where(CommunityMembership.community_id == community.id)
    )
    real_members = real_result.scalars().all()

    all_members = real_members + digital_members
    real_count = len(real_members)
    last_msg = (await db.execute(
        select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == community.id)
    )).scalar()
    return {
        "id": str(community.id),
        "name": community.name,
        "description": community.description,
        "status": compute_status(last_msg, real_count, community.status_override),
        "members": [{"id": str(m.id), "username": m.username, "is_digital": m.is_digital} for m in all_members],
    }


@router.post("/leave")
async def leave_community(
    body: LeaveBody,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify membership exists
    mem_result = await db.execute(
        select(CommunityMembership).where(
            CommunityMembership.user_id == current_user.id,
            CommunityMembership.community_id == UUID(body.community_id),
        )
    )
    if not mem_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Not a member of this community")

    await db.execute(
        sql_delete(CommunityMembership).where(
            CommunityMembership.user_id == current_user.id,
            CommunityMembership.community_id == UUID(body.community_id),
        )
    )

    # Find remaining memberships
    remaining = await db.execute(
        select(CommunityMembership).where(CommunityMembership.user_id == current_user.id)
    )
    other = remaining.scalars().all()

    if other:
        current_user.community_id = other[0].community_id
    else:
        current_user.community_id = None
        current_user.onboarding_complete = False
        current_user.profile_summary = None
        current_user.embedding = None
        await db.execute(sql_delete(OnboardingMessage).where(OnboardingMessage.user_id == current_user.id))

    await db.commit()
    return {"status": "ok"}


@router.post("/start-search")
async def start_community_search(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Begin searching for a new community while staying in the current one."""
    current_user.onboarding_complete = False
    current_user.profile_summary = None
    current_user.embedding = None
    await db.execute(sql_delete(OnboardingMessage).where(OnboardingMessage.user_id == current_user.id))
    await db.commit()
    return {"status": "ok"}


@router.get("/{community_id}/announcements")
async def get_announcements(
    community_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    mem_check = await db.execute(
        select(CommunityMembership).where(
            CommunityMembership.user_id == current_user.id,
            CommunityMembership.community_id == UUID(community_id),
        )
    )
    if not mem_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Not a member of this community")

    result = await db.execute(select(Community).where(Community.id == UUID(community_id)))
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    await fetch_and_store_announcements(community, db)
    return await get_today_announcements(community_id, db)


@router.post("/recluster")
async def trigger_recluster(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger k-means re-clustering of all users."""
    await recluster_all(db)
    return {"status": "reclustered"}
