from uuid import UUID
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sql_delete


class CommunityUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    location: str | None = None
    status: str | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    new_password: str | None = None
from ..database import get_db
from ..deps import get_admin_user
from ..models import (
    User, Community, CommunityMessage, CommunityWarning,
    CommunityMembership, OnboardingMessage, DirectMessage, CommunityBan, AppLog,
)
from ..services.community_status import compute_status

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    total_users = (await db.execute(
        select(func.count(User.id)).where(User.is_digital.is_(False))
    )).scalar() or 0

    digital_users = (await db.execute(
        select(func.count(User.id)).where(User.is_digital.is_(True))
    )).scalar() or 0

    total_communities = (await db.execute(
        select(func.count(Community.id))
    )).scalar() or 0

    total_messages = (await db.execute(
        select(func.count(CommunityMessage.id))
    )).scalar() or 0

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    messages_today = (await db.execute(
        select(func.count(CommunityMessage.id)).where(CommunityMessage.created_at >= today_start)
    )).scalar() or 0

    active_warnings = (await db.execute(
        select(func.count(CommunityWarning.id)).where(CommunityWarning.count > 0)
    )).scalar() or 0

    dm_count = (await db.execute(
        select(func.count(DirectMessage.id))
    )).scalar() or 0

    return {
        "users": {"total": total_users, "digital": digital_users},
        "communities": {"total": total_communities},
        "messages": {"total": total_messages, "today": messages_today, "dms": dm_count},
        "warnings": {"active": active_warnings},
    }


@router.get("/communities")
async def list_communities(
    search: str = "",
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(Community).order_by(Community.created_at.desc()))
    communities = result.scalars().all()

    out = []
    for c in communities:
        if search and search.lower() not in (c.name or "").lower() and search.lower() not in (c.description or "").lower():
            continue

        real_count = (await db.execute(
            select(func.count(CommunityMembership.user_id)).where(
                CommunityMembership.community_id == c.id
            )
        )).scalar() or 0

        digital_count = (await db.execute(
            select(func.count(User.id)).where(
                User.community_id == c.id, User.is_digital.is_(True)
            )
        )).scalar() or 0

        msg_count = (await db.execute(
            select(func.count(CommunityMessage.id)).where(
                CommunityMessage.community_id == c.id
            )
        )).scalar() or 0

        last_msg = (await db.execute(
            select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == c.id)
        )).scalar()
        out.append({
            "id": str(c.id),
            "name": c.name,
            "description": c.description,
            "real_member_count": real_count,
            "digital_member_count": digital_count,
            "message_count": msg_count,
            "status": compute_status(last_msg, real_count, c.status_override),
            "created_at": c.created_at.isoformat(),
        })
    return out


@router.get("/communities/{community_id}")
async def get_community(
    community_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(Community).where(Community.id == UUID(community_id)))
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")

    real_result = await db.execute(
        select(User)
        .join(CommunityMembership, CommunityMembership.user_id == User.id)
        .where(CommunityMembership.community_id == community.id)
    )
    real_members = real_result.scalars().all()

    digital_result = await db.execute(
        select(User).where(User.community_id == community.id, User.is_digital.is_(True))
    )
    digital_members = digital_result.scalars().all()

    msg_result = await db.execute(
        select(CommunityMessage, User.username, User.is_digital)
        .join(User, CommunityMessage.user_id == User.id)
        .where(CommunityMessage.community_id == community.id)
        .order_by(CommunityMessage.created_at.desc())
        .limit(30)
    )
    messages = [
        {
            "id": str(m.id),
            "user_id": str(m.user_id),
            "username": uname,
            "is_digital": is_dig,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m, uname, is_dig in msg_result.all()
    ]

    warn_result = await db.execute(
        select(CommunityWarning, User.username)
        .join(User, CommunityWarning.user_id == User.id)
        .where(CommunityWarning.community_id == community.id)
        .order_by(CommunityWarning.count.desc())
    )
    warnings = [
        {"user_id": str(w.user_id), "username": uname, "count": w.count}
        for w, uname in warn_result.all()
    ]

    real_count = len(real_members)
    msg_count = (await db.execute(
        select(func.count(CommunityMessage.id)).where(CommunityMessage.community_id == community.id)
    )).scalar() or 0
    last_msg = (await db.execute(
        select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == community.id)
    )).scalar()

    return {
        "id": str(community.id),
        "name": community.name,
        "description": community.description,
        "status": compute_status(last_msg, real_count, community.status_override),
        "status_override": community.status_override,
        "real_member_count": real_count,
        "digital_member_count": len(digital_members),
        "message_count": msg_count,
        "created_at": community.created_at.isoformat(),
        "members": [
            {"id": str(m.id), "username": m.username, "is_digital": m.is_digital, "email": m.email}
            for m in (real_members + digital_members)
        ],
        "recent_messages": messages,
        "warnings": warnings,
    }


@router.patch("/communities/{community_id}")
async def update_community(
    community_id: str,
    data: CommunityUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(Community).where(Community.id == UUID(community_id)))
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")
    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name cannot be empty")
        community.name = name
    if data.description is not None:
        community.description = data.description.strip() or None
    if data.location is not None:
        community.location = data.location.strip() or None
    if data.status is not None:
        from ..services.community_status import VALID_STATUSES
        if data.status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
        community.status_override = data.status
    await db.commit()
    return {"status": "ok", "name": community.name, "description": community.description}


@router.delete("/communities/{community_id}")
async def archive_community(
    community_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Archive a community (set status_override = ARCHIVED). Does not delete data."""
    result = await db.execute(select(Community).where(Community.id == UUID(community_id)))
    community = result.scalar_one_or_none()
    if not community:
        raise HTTPException(status_code=404, detail="Community not found")
    community.status_override = "ARCHIVED"
    await db.commit()
    return {"status": "ok"}


@router.get("/users")
async def list_users(
    search: str = "",
    page: int = 1,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    query = select(User).where(User.is_digital.is_(False)).order_by(User.created_at.desc())
    result = await db.execute(query)
    users = result.scalars().all()

    out = []
    for u in users:
        if search and search.lower() not in u.username.lower() and search.lower() not in u.email.lower():
            continue

        community_count = (await db.execute(
            select(func.count(CommunityMembership.community_id)).where(
                CommunityMembership.user_id == u.id
            )
        )).scalar() or 0

        msg_count = (await db.execute(
            select(func.count(CommunityMessage.id)).where(CommunityMessage.user_id == u.id)
        )).scalar() or 0

        warn_count = (await db.execute(
            select(func.count(CommunityWarning.id)).where(
                CommunityWarning.user_id == u.id, CommunityWarning.count > 0
            )
        )).scalar() or 0

        out.append({
            "id": str(u.id),
            "username": u.username,
            "email": u.email,
            "is_admin": u.is_admin,
            "onboarding_complete": u.onboarding_complete,
            "community_count": community_count,
            "message_count": msg_count,
            "warning_count": warn_count,
            "created_at": u.created_at.isoformat(),
        })
    return out


@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    mem_result = await db.execute(
        select(Community, CommunityMembership.joined_at)
        .join(CommunityMembership, CommunityMembership.community_id == Community.id)
        .where(CommunityMembership.user_id == user.id)
    )
    memberships = [
        {"id": str(c.id), "name": c.name, "joined_at": joined_at.isoformat()}
        for c, joined_at in mem_result.all()
    ]

    warn_result = await db.execute(
        select(CommunityWarning, Community.name)
        .join(Community, CommunityWarning.community_id == Community.id)
        .where(CommunityWarning.user_id == user.id)
        .order_by(CommunityWarning.count.desc())
    )
    warnings = [
        {"community_id": str(w.community_id), "community_name": cname, "count": w.count}
        for w, cname in warn_result.all()
    ]

    msg_result = await db.execute(
        select(CommunityMessage, Community.name)
        .join(Community, CommunityMessage.community_id == Community.id)
        .where(CommunityMessage.user_id == user.id)
        .order_by(CommunityMessage.created_at.desc())
        .limit(20)
    )
    messages = [
        {
            "id": str(m.id),
            "community_name": cname,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m, cname in msg_result.all()
    ]

    ban_result = await db.execute(
        select(CommunityBan, Community.name)
        .join(Community, CommunityBan.community_id == Community.id)
        .where(CommunityBan.user_id == user.id)
    )
    bans = [
        {"community_id": str(b.community_id), "community_name": cname, "banned_at": b.banned_at.isoformat()}
        for b, cname in ban_result.all()
    ]

    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "is_admin": user.is_admin,
        "is_banned": user.is_banned,
        "is_digital": user.is_digital,
        "onboarding_complete": user.onboarding_complete,
        "profile_summary": user.profile_summary,
        "created_at": user.created_at.isoformat(),
        "memberships": memberships,
        "warnings": warnings,
        "bans": bans,
        "recent_messages": messages,
    }


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    from passlib.context import CryptContext
    _pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.username is not None:
        new_uname = data.username.strip()
        if not new_uname:
            raise HTTPException(status_code=400, detail="Username cannot be empty")
        if new_uname != user.username:
            conflict = await db.execute(select(User).where(User.username == new_uname))
            if conflict.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Username already taken")
            user.username = new_uname

    if data.email is not None:
        new_email = data.email.strip()
        if not new_email:
            raise HTTPException(status_code=400, detail="Email cannot be empty")
        if new_email != user.email:
            conflict = await db.execute(select(User).where(User.email == new_email))
            if conflict.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Email already taken")
            user.email = new_email

    if data.is_admin is not None:
        user.is_admin = data.is_admin

    if data.new_password is not None:
        if len(data.new_password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
        user.password_hash = _pwd.hash(data.new_password)

    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_admin_user),
):
    if str(current_admin.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(user)
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/kick")
async def kick_user_from_community(
    user_id: str,
    community_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    await db.execute(
        sql_delete(CommunityMembership).where(
            CommunityMembership.user_id == UUID(user_id),
            CommunityMembership.community_id == UUID(community_id),
        )
    )
    user_result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = user_result.scalar_one_or_none()
    if user and str(user.community_id) == community_id:
        remaining = (await db.execute(
            select(CommunityMembership).where(CommunityMembership.user_id == UUID(user_id))
        )).scalars().all()
        if remaining:
            user.community_id = remaining[0].community_id
        else:
            user.community_id = None
            user.onboarding_complete = False
    await db.commit()
    return {"status": "ok"}


@router.delete("/warnings/{user_id}/{community_id}")
async def clear_warnings(
    user_id: str,
    community_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    await db.execute(
        sql_delete(CommunityWarning).where(
            CommunityWarning.user_id == UUID(user_id),
            CommunityWarning.community_id == UUID(community_id),
        )
    )
    await db.commit()
    return {"status": "ok"}


@router.get("/moderation")
async def get_moderation(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(
        select(CommunityWarning, User.username, Community.name)
        .join(User, CommunityWarning.user_id == User.id)
        .join(Community, CommunityWarning.community_id == Community.id)
        .order_by(CommunityWarning.count.desc())
    )
    return [
        {
            "user_id": str(w.user_id),
            "username": uname,
            "community_id": str(w.community_id),
            "community_name": cname,
            "count": w.count,
        }
        for w, uname, cname in result.all()
    ]


@router.delete("/bans/{user_id}/{community_id}")
async def lift_community_ban(
    user_id: str,
    community_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Remove the ban for a specific community, allowing the user to rejoin it."""
    await db.execute(
        sql_delete(CommunityBan).where(
            CommunityBan.user_id == UUID(user_id),
            CommunityBan.community_id == UUID(community_id),
        )
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/users/{user_id}/lift-ban")
async def lift_global_ban(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    """Clear the global ban flag. Optionally also wipe all community bans."""
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_banned = False
    # Also clear all community bans so the user can rejoin freely
    await db.execute(sql_delete(CommunityBan).where(CommunityBan.user_id == UUID(user_id)))
    await db.commit()
    return {"status": "ok"}


@router.get("/logs")
async def get_logs(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(
        select(AppLog).order_by(AppLog.time.desc()).limit(300)
    )
    logs = result.scalars().all()
    return [
        {
            "time": l.time.strftime("%Y-%m-%d %H:%M:%S"),
            "level": l.level,
            "logger": l.logger,
            "message": l.message,
            "exc": l.exc,
        }
        for l in reversed(logs)
    ]
