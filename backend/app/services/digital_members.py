import json
import random
import hashlib
import time
import anthropic
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from uuid import UUID
from ..models import User, Community, CommunityMessage, CommunityMembership
from ..config import settings
from .guardrails import wrap_user_content, validate_output
from .community_tools import TOOL_SCHEMAS, execute_tool
from .event_tools import EVENT_TOOL_SCHEMAS, execute_event_tool
from .metrics import metrics

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

PERSONAS = [
    {"key": "aria",  "persona": "Warm and curious. Loves asking thoughtful follow-up questions and connecting ideas across domains."},
    {"key": "leo",   "persona": "Direct and practical. Shares concrete examples, has a dry sense of humor, enjoys friendly pushback."},
    {"key": "sage",  "persona": "Reflective and measured. Offers deeper perspectives on topics, finds common ground between viewpoints."},
    {"key": "nova",  "persona": "Enthusiastic and energetic. Quick to celebrate ideas, loves brainstorming, brings infectious optimism."},
    {"key": "finn",  "persona": "Laid-back and witty. Defuses tension with humor, cuts through jargon with simple analogies."},
    {"key": "eden",  "persona": "Empathetic and perceptive. Listens carefully, picks up on what's unsaid, bridges different perspectives."},
    {"key": "blake", "persona": "Analytical and precise. Breaks down complex topics methodically, loves specifics over generalities."},
    {"key": "mira",  "persona": "Creative and playful. Approaches topics from unexpected angles, enjoys thought experiments."},
    {"key": "theo",  "persona": "Steady and grounded. Brings historical context and long-term thinking, values depth over speed."},
]


def _personas_for_community(community_id) -> list[dict]:
    """Deterministically pick 3 distinct personas for a community using its ID as a seed."""
    seed = int(hashlib.md5(str(community_id).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    pool = PERSONAS.copy()
    rng.shuffle(pool)
    return pool[:3]


def display_name(user: User) -> str:
    """Extract readable display name from a digital member's username."""
    base = user.username.split(".")[0]
    return base.capitalize()


def _username(persona_key: str, community_id) -> str:
    return f"{persona_key}.{str(community_id)[:8]}"


async def ensure_digital_members(community: Community, db: AsyncSession) -> list[User]:
    """Create 3 digital members for a newly created community."""
    result = await db.execute(
        select(User).where(User.community_id == community.id, User.is_digital.is_(True))
    )
    if result.scalars().all():
        return []

    members = []
    for p in _personas_for_community(community.id):
        uname = _username(p["key"], community.id)
        member = User(
            email=f"{uname}@digital.community.ai",
            username=uname,
            password_hash="!",
            is_digital=True,
            onboarding_complete=True,
            community_id=community.id,
        )
        db.add(member)
        members.append(member)
    await db.flush()
    return members


async def get_digital_members(community_id: str, db: AsyncSession) -> list[User]:
    result = await db.execute(
        select(User).where(
            User.community_id == UUID(community_id),
            User.is_digital.is_(True),
        )
    )
    return result.scalars().all()


async def get_real_member_count(community_id: str, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(CommunityMembership.user_id)).where(
            CommunityMembership.community_id == UUID(community_id),
        )
    )
    return result.scalar() or 0


async def remove_digital_members(community_id: str, db: AsyncSession) -> list[str]:
    """Detach digital members from the community. Returns their display names."""
    members = await get_digital_members(community_id, db)
    names = [display_name(m) for m in members]  # Extract before commit expires objects
    for m in members:
        m.community_id = None
    await db.commit()
    return names


async def generate_dm_response_stream(
    digital_member: User,
    real_user: User,
    community_name: str | None,
    community_description: str | None,
    recent_messages: list[dict],
    db: AsyncSession | None = None,
    community_ids: list[str] | None = None,
    community_location: str | None = None,
) -> AsyncGenerator[str, None]:
    start = time.perf_counter()
    gen_error = False
    tool_calls_used = 0
    try:
        persona = next(
            (p for p in PERSONAS if digital_member.username.startswith(p["key"] + ".")),
            PERSONAS[0],
        )
        name = display_name(digital_member)
        user_name = real_user.username.split(".")[0].capitalize()

        community_info = (
            f"{community_name} — {community_description or 'a shared interest community'}"
            if community_name
            else "they are not currently in any community"
        )

        has_tools = db is not None and bool(community_ids)

        system = (
            f"You are {name}, a digital (AI) community member in a private one-on-one chat.\n"
            f"Be upfront about being digital/AI if asked — never pretend to be human.\n\n"
            f"Your personality: {persona['persona']}\n\n"
            f"== Facts about the person you're chatting with ==\n"
            f"Name: {user_name}\n"
            f"Profile: {real_user.profile_summary or 'Not shared yet.'}\n"
            f"Current community: {community_info}\n\n"
        )

        if has_tools:
            location_hint = f"'{community_location}'" if community_location else "the location implied by the community name"
            system += (
                f"You have real internet-connected tools. NEVER say you cannot access links, search the web, "
                f"or find events — that is false. You MUST call tools instead of guessing or answering from memory:\n"
                f"- search_local_events: call this IMMEDIATELY whenever {user_name} asks about meetups, "
                f"events, groups, or anything happening outside this community. "
                f"Use {location_hint} as the location and the relevant topic as query. "
                f"Share the returned URLs directly — do not say you cannot provide links.\n"
                f"- Community tools (get_recent_messages, get_community_members, search_messages, get_community_activity): "
                f"use for anything about this community's discussions, members, or activity.\n"
                f"- save_to_calendar: use when {user_name} wants to save an event.\n"
                f"Never describe or suggest events from memory — always call search_local_events first.\n\n"
            )
        else:
            system += (
                f"If {user_name} asks which community they are in, answer directly: \"{community_info}\".\n\n"
            )

        system += "Keep replies to 1-3 sentences. No bullet points. No filler phrases."

        if recent_messages:
            context = "\n".join(
                f"{m.get('sender_username', 'user')}: {wrap_user_content(m.get('content', ''))}"
                for m in recent_messages[-10:]
            )
            user_content = f"Chat history:\n{context}\n\nRespond naturally as {name}."
        else:
            user_content = f"Say a brief, warm hello to {user_name} as {name}."

        messages_payload = [{"role": "user", "content": user_content}]
        tools = (TOOL_SCHEMAS + EVENT_TOOL_SCHEMAS) if has_tools else EVENT_TOOL_SCHEMAS

        for _ in range(5):
            kwargs: dict = dict(model="claude-haiku-4-5-20251001", max_tokens=300, system=system, messages=messages_payload)
            if tools:
                kwargs["tools"] = tools

            async with client.messages.stream(**kwargs) as stream:
                async for chunk in stream.text_stream:
                    yield chunk
                final = await stream.get_final_message()

            if final.stop_reason == "end_turn":
                return

            if final.stop_reason == "tool_use":
                messages_payload.append({"role": "assistant", "content": final.content})
                tool_results = []
                for block in final.content:
                    if block.type == "tool_use":
                        tool_calls_used += 1
                        if block.name in ("search_local_events", "save_to_calendar"):
                            result = await execute_event_tool(block.name, block.input)
                        else:
                            result = await execute_tool(block.name, block.input, db, community_ids)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                messages_payload.append({"role": "user", "content": tool_results})
            else:
                break
    except Exception:
        gen_error = True
        raise
    finally:
        metrics.record_call(
            "dm_ai",
            (time.perf_counter() - start) * 1000,
            error=gen_error,
            tool_calls=tool_calls_used,
        )


async def generate_response_stream(
    community: Community,
    digital_member: User,
    recent_messages: list[dict],
    db: AsyncSession | None = None,
    community_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    start = time.perf_counter()
    gen_error = False
    tool_calls_used = 0
    try:
        persona = next(
            (p for p in PERSONAS if digital_member.username.startswith(p["key"] + ".")),
            PERSONAS[0],
        )
        name = display_name(digital_member)
        has_tools = db is not None and bool(community_ids)
        location_hint = f"'{community.location}'" if community.location else "the location implied by the community name"

        system = (
            f"You are {name}, a digital (AI) community member. "
            f"Be upfront about being digital/AI if asked — never pretend to be human.\n\n"
            f"Your personality: {persona['persona']}\n\n"
            f"Community: \"{community.name}\" — {community.description or 'a shared interest community'}\n\n"
        )

        if has_tools:
            system += (
                f"You have real internet-connected tools. NEVER say you cannot access links, search the web, "
                f"or find events — that is false. ALWAYS call tools instead of guessing or answering from memory:\n"
                f"- search_local_events: call this IMMEDIATELY whenever anyone asks about meetups, "
                f"events, groups, or anything happening outside this community. "
                f"Use {location_hint} as the location and the relevant topic as query. "
                f"Share the returned URLs directly — do not say you cannot provide links.\n"
                f"- Community tools (get_recent_messages, get_community_members, search_messages, get_community_activity): "
                f"use for questions about this community's discussions, members, or activity.\n"
                f"- save_to_calendar: use when someone wants to save an event.\n"
                f"Never describe or suggest events from memory — always call search_local_events first.\n\n"
            )

        system += (
            f"Keep replies concise (1–3 sentences), natural, and genuinely engaged with the topic. "
            f"Avoid filler phrases like 'Great question!' or 'Absolutely!'"
        )

        if recent_messages:
            context = "\n".join(
                f"{m.get('display_name', m.get('username', 'user'))}: {wrap_user_content(m.get('content', ''))}"
                for m in recent_messages[-10:]
            )
            user_content = f"Recent conversation:\n{context}\n\nRespond naturally as {name}."
        else:
            user_content = (
                f"A new member just joined \"{community.name}\". "
                f"Send a brief, genuine welcome as {name} — mention the community theme."
            )

        tools = (TOOL_SCHEMAS + EVENT_TOOL_SCHEMAS) if has_tools else []
        messages_payload = [{"role": "user", "content": user_content}]

        for _ in range(5):
            kwargs: dict = dict(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                system=system,
                messages=messages_payload,
            )
            if tools:
                kwargs["tools"] = tools

            async with client.messages.stream(**kwargs) as stream:
                async for chunk in stream.text_stream:
                    yield chunk
                final = await stream.get_final_message()

            if final.stop_reason == "end_turn":
                return

            if final.stop_reason == "tool_use":
                messages_payload.append({"role": "assistant", "content": final.content})
                tool_results = []
                for block in final.content:
                    if block.type == "tool_use":
                        tool_calls_used += 1
                        if block.name in ("search_local_events", "save_to_calendar"):
                            result = await execute_event_tool(block.name, block.input)
                        else:
                            result = await execute_tool(block.name, block.input, db, community_ids)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })
                messages_payload.append({"role": "user", "content": tool_results})
            else:
                break
    except Exception:
        gen_error = True
        raise
    finally:
        metrics.record_call("community_chat_ai", (time.perf_counter() - start) * 1000, error=gen_error, tool_calls=tool_calls_used)
