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
from .prompts import (
    DIGITAL_MEMBER_DM_BASE,
    DIGITAL_MEMBER_DM_TOOLS,
    DIGITAL_MEMBER_DM_NO_TOOLS,
    DIGITAL_MEMBER_DM_FOOTER,
    DIGITAL_MEMBER_CHAT_BASE,
    DIGITAL_MEMBER_CHAT_TOOLS,
    DIGITAL_MEMBER_CHAT_FOOTER,
)

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

# The full persona pool — 3 are picked per community deterministically
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
    """
    Deterministically pick 3 distinct personas for a community using its ID as a seed.
    MD5 of the UUID gives a stable integer seed — same community always gets the same 3 personas.
    """
    seed = int(hashlib.md5(str(community_id).encode()).hexdigest(), 16)
    rng = random.Random(seed)
    pool = PERSONAS.copy()
    rng.shuffle(pool)
    return pool[:3]


def display_name(user: User) -> str:
    """Extract readable display name from a digital member's username (format: key.community_prefix)."""
    base = user.username.split(".")[0]
    return base.capitalize()


def _username(persona_key: str, community_id) -> str:
    # Include a community ID prefix so the same persona key maps to a unique username per community
    return f"{persona_key}.{str(community_id)[:8]}"


async def ensure_digital_members(community: Community, db: AsyncSession) -> list[User]:
    """Create 3 digital members for a newly created community if none exist yet."""
    result = await db.execute(
        select(User).where(User.community_id == community.id, User.is_digital.is_(True))
    )
    if result.scalars().all():
        return []  # Already have digital members — nothing to do

    members = []
    for p in _personas_for_community(community.id):
        uname = _username(p["key"], community.id)
        member = User(
            email=f"{uname}@digital.community.ai",
            username=uname,
            # "!" is an invalid bcrypt hash — it can never match any real password,
            # preventing accidental login as a digital member
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
    """Detach digital members from the community when enough real members have joined. Returns their display names."""
    members = await get_digital_members(community_id, db)
    names = [display_name(m) for m in members]  # Capture names before commit expires the ORM objects
    for m in members:
        m.community_id = None  # Detach rather than delete — preserves message history
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

        # Tools are only available when a DB session and community list are provided
        has_tools = db is not None and bool(community_ids)

        # Build system prompt from templates — base + conditional tools section + footer
        system = DIGITAL_MEMBER_DM_BASE.format(
            name=name,
            persona=persona["persona"],
            user_name=user_name,
            profile_summary=real_user.profile_summary or "Not shared yet.",
            community_info=community_info,
        )

        if has_tools:
            location_hint = f"'{community_location}'" if community_location else "the location implied by the community name"
            system += DIGITAL_MEMBER_DM_TOOLS.format(
                user_name=user_name,
                location_hint=location_hint,
            )
        else:
            system += DIGITAL_MEMBER_DM_NO_TOOLS.format(
                user_name=user_name,
                community_info=community_info,
            )

        system += DIGITAL_MEMBER_DM_FOOTER

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

        # Agentic loop capped at 5 iterations to prevent runaway tool chains
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

        # Build system prompt from templates — base + conditional tools section + footer
        system = DIGITAL_MEMBER_CHAT_BASE.format(
            name=name,
            persona=persona["persona"],
            community_name=community.name,
            community_description=community.description or "a shared interest community",
        )

        if has_tools:
            system += DIGITAL_MEMBER_CHAT_TOOLS.format(location_hint=location_hint)

        system += DIGITAL_MEMBER_CHAT_FOOTER

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

        # Agentic loop capped at 5 iterations to prevent runaway tool chains
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
