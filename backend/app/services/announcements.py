"""
Daily event announcement service.
Fetches events relevant to each community and stores them as announcements.
"""
import logging
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID

from ..models import Community, CommunityAnnouncement
from .event_tools import search_local_events

logger = logging.getLogger(__name__)


async def fetch_and_store_announcements(
    community: Community,
    db: AsyncSession,
    force: bool = False,
) -> list[CommunityAnnouncement]:
    """
    Return today's announcements for a community, fetching them if they don't exist yet.
    Set force=True to re-fetch even if today's announcements already exist.
    """
    today = date.today()

    if not force:
        existing_count = (await db.execute(
            select(func.count(CommunityAnnouncement.id)).where(
                CommunityAnnouncement.community_id == community.id,
                CommunityAnnouncement.announced_date == today,
            )
        )).scalar() or 0

        if existing_count > 0:
            result = await db.execute(
                select(CommunityAnnouncement)
                .where(
                    CommunityAnnouncement.community_id == community.id,
                    CommunityAnnouncement.announced_date == today,
                )
                .order_by(CommunityAnnouncement.created_at)
            )
            return result.scalars().all()

    location = community.location or ""
    topic = community.name

    events = await search_local_events(location=location, query=topic)

    new_items = []
    for event in events:
        ann = CommunityAnnouncement(
            community_id=community.id,
            title=event.get("title", "Untitled Event"),
            description=event.get("description"),
            event_url=event.get("url"),
            source=event.get("source", "Web"),
            announced_date=today,
        )
        db.add(ann)
        new_items.append(ann)

    await db.commit()
    for item in new_items:
        await db.refresh(item)
    return new_items


async def get_today_announcements(community_id: str, db: AsyncSession) -> list[dict]:
    result = await db.execute(
        select(CommunityAnnouncement)
        .where(
            CommunityAnnouncement.community_id == UUID(community_id),
            CommunityAnnouncement.announced_date == date.today(),
        )
        .order_by(CommunityAnnouncement.created_at)
    )
    return [
        {
            "id": str(a.id),
            "title": a.title,
            "description": a.description,
            "event_url": a.event_url,
            "source": a.source,
            "announced_date": a.announced_date.isoformat(),
        }
        for a in result.scalars().all()
    ]
