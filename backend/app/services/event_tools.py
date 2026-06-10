"""
Event discovery tools for the personal agent.
Uses Brave Search API to find local AI/tech events and generates calendar URLs.
Shared between the MCP server and the personal agent's tool-use loop.
"""
import json
import urllib.parse
from datetime import datetime, timezone

import httpx

from ..config import settings

# ── Tool schemas (Claude tool-use format) ────────────────────────────────────

EVENT_TOOL_SCHEMAS = [
    {
        "name": "search_local_events",
        "description": (
            "Search for upcoming AI, tech, or community events near a location. "
            "Use when the user asks what's happening near them, local meetups, upcoming AI events, "
            "conferences, or anything about events in their area this week or month."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City, region, or 'online'. Example: 'Berlin', 'San Francisco', 'online'",
                },
                "query": {
                    "type": "string",
                    "description": "Topic to search for. Example: 'AI meetup', 'machine learning', 'LLM workshop'",
                },
                "timeframe": {
                    "type": "string",
                    "description": "When to search: 'this week', 'this month', 'next month'. Defaults to 'this week'.",
                    "default": "this week",
                },
            },
            "required": ["location", "query"],
        },
    },
    {
        "name": "save_to_calendar",
        "description": (
            "Generate a Google Calendar link so the user can save an event. "
            "Use after the user says they want to attend or save an event."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_datetime": {
                    "type": "string",
                    "description": "ISO 8601 datetime string, e.g. '2026-06-10T18:00:00'",
                },
                "end_datetime": {
                    "type": "string",
                    "description": "ISO 8601 datetime string for end time",
                },
                "location": {
                    "type": "string",
                    "description": "Physical address or URL of the event",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description or URL",
                },
            },
            "required": ["title", "start_datetime"],
        },
    },
]


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def search_local_events(location: str, query: str, timeframe: str = "this week") -> list[dict]:
    """Search for events using Brave Search API. Falls back to empty list if key not set."""
    if not settings.brave_api_key:
        return _mock_events(location, query)

    location_part = f"in {location} " if location and location.lower() not in ("", "online") else ""
    search_query = f"{query} events {location_part}{timeframe} (site:eventbrite.com OR site:meetup.com OR site:lu.ma)"
    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": settings.brave_api_key,
    }
    params = {"q": search_query, "count": 10, "freshness": "pw"}  # pw = past week

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
                "source": _source_label(item.get("url", "")),
            })
        return results

    except Exception:
        return _mock_events(location, query)


def save_to_calendar(
    title: str,
    start_datetime: str,
    end_datetime: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict:
    """Generate a Google Calendar add-event URL."""
    def _gcal_dt(iso: str) -> str:
        # Strip punctuation to get YYYYMMDDTHHmmssZ format
        dt = iso.replace("-", "").replace(":", "").replace(" ", "T")
        if not dt.endswith("Z"):
            dt += "Z"
        return dt

    start = _gcal_dt(start_datetime)
    end = _gcal_dt(end_datetime) if end_datetime else start

    params: dict[str, str] = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start}/{end}",
    }
    if location:
        params["location"] = location
    if description:
        params["details"] = description

    calendar_url = "https://calendar.google.com/calendar/render?" + urllib.parse.urlencode(params)
    return {"calendar_url": calendar_url, "title": title}


async def execute_event_tool(name: str, tool_input: dict) -> dict | list:
    """Dispatch an event tool call by name."""
    if name == "search_local_events":
        return await search_local_events(
            location=tool_input.get("location", ""),
            query=tool_input.get("query", "AI events"),
            timeframe=tool_input.get("timeframe", "this week"),
        )
    if name == "save_to_calendar":
        return save_to_calendar(
            title=tool_input.get("title", "Event"),
            start_datetime=tool_input.get("start_datetime", ""),
            end_datetime=tool_input.get("end_datetime"),
            location=tool_input.get("location"),
            description=tool_input.get("description"),
        )
    return {"error": f"Unknown event tool: {name}"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _source_label(url: str) -> str:
    if "eventbrite" in url:
        return "Eventbrite"
    if "meetup.com" in url:
        return "Meetup"
    if "lu.ma" in url:
        return "Lu.ma"
    return "Web"


def _mock_events(location: str, query: str) -> list[dict]:
    """Placeholder results when no API key is configured — links point to real search pages."""
    import urllib.parse as _up
    where = location if location and location.lower() not in ("", "online") else ""
    meetup_url = "https://www.meetup.com/find/?" + _up.urlencode(
        {"keywords": query, **({"location": where} if where else {}), "source": "EVENTS"}
    )
    luma_url = "https://lu.ma/search?" + _up.urlencode({"q": f"{query} {where}".strip()})
    return [
        {
            "title": f"Search '{query}' events on Meetup{' in ' + where if where else ''}",
            "url": meetup_url,
            "description": "Click to browse matching events on Meetup. (Add BRAVE_API_KEY to .env for automatic results.)",
            "source": "Meetup",
        },
        {
            "title": f"Search '{query}' events on Lu.ma{' in ' + where if where else ''}",
            "url": luma_url,
            "description": "Click to browse matching events on Lu.ma. (Add BRAVE_API_KEY to .env for automatic results.)",
            "source": "Lu.ma",
        },
    ]
