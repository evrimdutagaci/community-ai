"""
Community AI — MCP Server

Exposes the community data layer as MCP tools so any MCP-capable agent
(Claude Desktop, external agents) can query live community data.

Run:
    python mcp_server.py

Configure in Claude Desktop (~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "community-ai": {
          "command": "python",
          "args": ["/path/to/backend/mcp_server.py"]
        }
      }
    }
"""
import asyncio
import json
import sys
import os

# Make app imports work when run from the backend/ directory
sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.config import settings
from app.services.community_tools import (
    list_communities,
    get_recent_messages,
    get_community_members,
    search_messages,
    get_community_activity,
)
from app.services.event_tools import (
    search_local_events,
    save_to_calendar,
)

# ── DB setup (own connection — runs as separate process) ──────────────────────

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

mcp = FastMCP(
    "community-ai",
    instructions=(
        "You have access to live data from the Community AI platform. "
        "Use these tools to answer questions about communities, members, and discussions."
    ),
)


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def list_communities_tool() -> str:
    """
    List all communities with their names, IDs, descriptions, and locations.
    Call this first to discover community names before using other tools.
    """
    async with AsyncSessionLocal() as db:
        communities = await list_communities(db)
    return json.dumps(communities, default=str)


@mcp.tool()
async def get_recent_messages_tool(community_id: str, limit: int = 10) -> str:
    """
    Get the most recent messages from a community.
    community_id accepts a UUID or a community name (partial match supported).
    Use when asked what's been discussed, what people are talking about, or what was missed.
    """
    async with AsyncSessionLocal() as db:
        messages = await get_recent_messages(community_id, db, limit)
    return json.dumps(messages, default=str)


@mcp.tool()
async def get_community_members_tool(community_id: str) -> str:
    """
    List the members of a community with their profiles.
    community_id accepts a UUID or a community name (partial match supported).
    Use when asked who's in the community or to help make introductions.
    """
    async with AsyncSessionLocal() as db:
        members = await get_community_members(community_id, db)
    return json.dumps(members, default=str)


@mcp.tool()
async def search_messages_tool(community_id: str, query: str) -> str:
    """
    Search community messages for a keyword or topic.
    community_id accepts a UUID or a community name (partial match supported).
    Use when asked whether something was discussed or to find a specific conversation.
    """
    async with AsyncSessionLocal() as db:
        results = await search_messages(community_id, query, db)
    return json.dumps(results, default=str)


@mcp.tool()
async def get_community_activity_tool(community_id: str) -> str:
    """
    Get a community activity summary: message volume, most active members, last activity time.
    community_id accepts a UUID or a community name (partial match supported).
    Use when asked about community health or engagement levels.
    """
    async with AsyncSessionLocal() as db:
        activity = await get_community_activity(community_id, db)
    return json.dumps(activity, default=str)


@mcp.tool()
async def search_local_events_tool(location: str, query: str, timeframe: str = "this week") -> str:
    """
    Search for upcoming AI, tech, or community events near a location.
    Use when asked what's happening locally, about meetups, conferences, or events this week.
    Requires BRAVE_API_KEY env variable; returns sample data otherwise.
    """
    results = await search_local_events(location=location, query=query, timeframe=timeframe)
    return json.dumps(results, default=str)


@mcp.tool()
async def save_to_calendar_tool(
    title: str,
    start_datetime: str,
    end_datetime: str = "",
    location: str = "",
    description: str = "",
) -> str:
    """
    Generate a Google Calendar link so the user can save an event to their calendar.
    Returns a URL the user can open to add the event.
    start_datetime and end_datetime must be ISO 8601 format, e.g. '2026-06-10T18:00:00'.
    """
    result = save_to_calendar(
        title=title,
        start_datetime=start_datetime,
        end_datetime=end_datetime or None,
        location=location or None,
        description=description or None,
    )
    return json.dumps(result)


if __name__ == "__main__":
    if "--http" in sys.argv:
        port_idx = sys.argv.index("--port") + 1 if "--port" in sys.argv else None
        port = int(sys.argv[port_idx]) if port_idx else 8002
        import uvicorn
        uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
    else:
        mcp.run()
