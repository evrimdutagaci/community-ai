"""
Community data tool handlers.
Shared between the MCP server (standalone process) and the personal agent's tool-use loop.
Each function accepts a DB session and returns plain Python structures (JSON-serialisable).
"""
import json
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from ..models import User, Community, CommunityMessage, CommunityMembership

# ── Community resolver ────────────────────────────────────────────────────────

async def resolve_community_id(community_ref: str, db: AsyncSession) -> str | None:
    """Accept a UUID or a community name (case-insensitive). Returns the UUID string or None."""
    # Try as UUID first
    try:
        UUID(community_ref)
        return community_ref
    except ValueError:
        pass
    # Fall back to name search
    result = await db.execute(
        select(Community).where(Community.name.ilike(f"%{community_ref}%"))
    )
    community = result.scalars().first()
    return str(community.id) if community else None


# ── Tool schemas (Claude tool-use format) ────────────────────────────────────

_COMMUNITY_REF = {
    "type": "string",
    "description": "Community UUID or community name (partial match supported, e.g. 'AI builders')",
}

TOOL_SCHEMAS = [
    {
        "name": "list_communities",
        "description": "List all available communities with their names, IDs, and descriptions. Use this first to discover community names and IDs.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_recent_messages",
        "description": (
            "Fetch the most recent messages from a community. "
            "Use when the user asks what's been discussed, what they missed, or what people are talking about."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "community_id": _COMMUNITY_REF,
                "limit": {"type": "integer", "description": "Number of messages to return (max 20)", "default": 10},
            },
            "required": ["community_id"],
        },
    },
    {
        "name": "get_community_members",
        "description": (
            "List the members of a community with their profile summaries. "
            "Use when the user asks who's in the community or wants an introduction to someone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"community_id": _COMMUNITY_REF},
            "required": ["community_id"],
        },
    },
    {
        "name": "search_messages",
        "description": (
            "Search community messages for a keyword or topic. "
            "Use when the user asks whether something was discussed or wants to find a specific conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "community_id": _COMMUNITY_REF,
                "query": {"type": "string", "description": "Keyword or phrase to search for"},
            },
            "required": ["community_id", "query"],
        },
    },
    {
        "name": "get_community_activity",
        "description": (
            "Get an activity summary for a community: message volume, most active members, last activity. "
            "Use when the user asks about community health or engagement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"community_id": _COMMUNITY_REF},
            "required": ["community_id"],
        },
    },
]


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def list_communities(db: AsyncSession) -> list[dict]:
    result = await db.execute(select(Community).order_by(Community.name))
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "description": c.description or "",
            "location": c.location or "",
        }
        for c in result.scalars().all()
        if c.status_override != "ARCHIVED"
    ]


async def get_recent_messages(community_ref: str, db: AsyncSession, limit: int = 10) -> list[dict]:
    community_id = await resolve_community_id(community_ref, db)
    if not community_id:
        return [{"error": f"Community not found: {community_ref!r}"}]
    limit = max(1, min(limit, 20))
    result = await db.execute(
        select(CommunityMessage, User.username, User.is_digital)
        .join(User, CommunityMessage.user_id == User.id)
        .where(CommunityMessage.community_id == UUID(community_id))
        .order_by(CommunityMessage.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "username": uname.split(".")[0].capitalize() if is_dig else uname,
            "is_digital": is_dig,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m, uname, is_dig in reversed(result.all())
    ]


async def get_community_members(community_ref: str, db: AsyncSession) -> list[dict]:
    community_id = await resolve_community_id(community_ref, db)
    if not community_id:
        return [{"error": f"Community not found: {community_ref!r}"}]
    real_result = await db.execute(
        select(User)
        .join(CommunityMembership, CommunityMembership.user_id == User.id)
        .where(CommunityMembership.community_id == UUID(community_id))
    )
    digital_result = await db.execute(
        select(User).where(
            User.community_id == UUID(community_id),
            User.is_digital.is_(True),
        )
    )
    members = []
    for u in real_result.scalars().all():
        members.append({
            "username": u.username,
            "is_digital": False,
            "profile": u.profile_summary or "No profile yet.",
        })
    for u in digital_result.scalars().all():
        members.append({
            "username": u.username.split(".")[0].capitalize(),
            "is_digital": True,
        })
    return members


async def search_messages(community_ref: str, query: str, db: AsyncSession) -> list[dict]:
    community_id = await resolve_community_id(community_ref, db)
    if not community_id:
        return [{"error": f"Community not found: {community_ref!r}"}]
    result = await db.execute(
        select(CommunityMessage, User.username, User.is_digital)
        .join(User, CommunityMessage.user_id == User.id)
        .where(
            CommunityMessage.community_id == UUID(community_id),
            CommunityMessage.content.ilike(f"%{query}%"),
        )
        .order_by(CommunityMessage.created_at.desc())
        .limit(10)
    )
    return [
        {
            "username": uname.split(".")[0].capitalize() if is_dig else uname,
            "content": m.content,
            "created_at": m.created_at.isoformat(),
        }
        for m, uname, is_dig in result.all()
    ]


async def get_community_activity(community_ref: str, db: AsyncSession) -> dict:
    community_id = await resolve_community_id(community_ref, db)
    if not community_id:
        return {"error": f"Community not found: {community_ref!r}"}
    msg_count = (await db.execute(
        select(func.count(CommunityMessage.id)).where(CommunityMessage.community_id == UUID(community_id))
    )).scalar() or 0

    last_msg = (await db.execute(
        select(func.max(CommunityMessage.created_at)).where(CommunityMessage.community_id == UUID(community_id))
    )).scalar()

    active_result = await db.execute(
        select(User.username, func.count(CommunityMessage.id).label("cnt"))
        .join(CommunityMessage, CommunityMessage.user_id == User.id)
        .where(
            CommunityMessage.community_id == UUID(community_id),
            User.is_digital.is_(False),
        )
        .group_by(User.username)
        .order_by(func.count(CommunityMessage.id).desc())
        .limit(3)
    )

    return {
        "total_messages": msg_count,
        "last_activity": last_msg.isoformat() if last_msg else None,
        "most_active_members": [{"username": u, "messages": c} for u, c in active_result.all()],
    }


async def execute_tool(name: str, tool_input: dict, db: AsyncSession, community_ids: list[str]) -> dict | list:
    """Dispatch a tool call by name. Falls back to first available community if none specified."""
    if name == "list_communities":
        return await list_communities(db)

    community_ref = tool_input.get("community_id")
    if not community_ref and community_ids:
        community_ref = community_ids[0]
    if not community_ref:
        return {"error": "No community available for this user."}

    if name == "get_recent_messages":
        return await get_recent_messages(community_ref, db, tool_input.get("limit", 10))
    if name == "get_community_members":
        return await get_community_members(community_ref, db)
    if name == "search_messages":
        return await search_messages(community_ref, tool_input.get("query", ""), db)
    if name == "get_community_activity":
        return await get_community_activity(community_ref, db)

    return {"error": f"Unknown tool: {name}"}
