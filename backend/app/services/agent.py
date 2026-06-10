import json
import re
import time
import anthropic
from ..config import settings
from .guardrails import wrap_user_content, validate_output
from .metrics import metrics

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

_ONBOARDING_SYSTEM = """You are a friendly AI helping someone find their community.

Your goal: learn who they are through natural chat — interests, hobbies, passions, what kind of people they'd like to meet.

Rules:
- Keep every reply to 1-2 short sentences. No exceptions.
- No bullet points, no bold text, no lists, no emojis.
- Ask at most one follow-up question per message.
- Sound like a real person texting, not a customer service bot.
- If they ask you to name or create a community, acknowledge the idea warmly in one sentence, then ask one question to learn more about their taste — the system will handle matching or creating automatically.
- Never mention profiling, algorithms, or embeddings.
"""

_PROFILE_SYSTEM = """You are extracting a matching profile for community search. Given a conversation, write a concise profile optimized for semantic similarity matching.

Rules:
- 2-3 sentences, under 60 words total
- Name specific interests, hobbies, sports, topics, and activities
- State what kind of community they are looking for
- Include any relevant context (location, life stage, goals)
- No filler phrases ("values genuine connections", "enjoys real-world activities", etc.)
- Use concrete nouns and verbs

Example: "Competitive squash player and French language learner living as an expat in Brussels. Looking for squash clubs with a social scene, French conversation practice, and fellow expats. Interested in sports, language exchange, and local integration."
"""

_NAMING_SYSTEM = """You are naming a community based on its members' shared interests. Given member profiles, return JSON only:
{"name": "<3-5 word name reflecting PRIMARY shared interests>", "description": "<one sentence describing the community's specific core interests — avoid vague phrases like 'real-world hobbies' or 'genuine connections'>", "location": "<city or region if clearly shared by the members, otherwise null>"}

Examples:
- Squash + expat + French learners in Brussels → {"name": "Expats, Courts & Café", "description": "A community for expats learning French and staying active through racket sports and outdoor activities.", "location": "Brussels"}
- DevOps + open source engineers (no shared location) → {"name": "Ship It Engineers", "description": "A community for DevOps engineers and open source contributors focused on CI/CD, cloud infrastructure, and platform engineering.", "location": null}
- Road cyclists in Warsaw → {"name": "Warsaw Road Cyclists", "description": "A community for competitive road cyclists in Warsaw.", "location": "Warsaw"}"""


async def chat_onboarding(messages: list[dict], user_context: str = "") -> str:
    start = time.perf_counter()
    error = False
    try:
        system = _ONBOARDING_SYSTEM
        if user_context:
            system = f"{_ONBOARDING_SYSTEM}\n\nUser context (facts you can state directly if asked):\n{user_context}"
        safe_messages = [
            {"role": m["role"], "content": wrap_user_content(m["content"]) if m["role"] == "user" else m["content"]}
            for m in messages
        ] if messages else [{"role": "user", "content": "hi"}]
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=150,
            system=system,
            messages=safe_messages,
        )
        text, _ = validate_output(response.content[0].text, max_length=400)
        return text
    except Exception:
        error = True
        raise
    finally:
        metrics.record_call("onboarding_chat", (time.perf_counter() - start) * 1000, error=error)


async def generate_profile(conversation: list[dict]) -> str:
    start = time.perf_counter()
    error = False
    try:
        transcript = "\n".join(f"{m['role'].upper()}: {m['content']}" for m in conversation)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=400,
            system=_PROFILE_SYSTEM,
            messages=[{"role": "user", "content": f"Conversation:\n\n{transcript}"}],
        )
        return response.content[0].text
    except Exception:
        error = True
        raise
    finally:
        metrics.record_call("profile_generation", (time.perf_counter() - start) * 1000, error=error)


async def generate_community_name(profiles: list[str]) -> dict:
    start = time.perf_counter()
    error = False
    try:
        sample = "\n\n---\n\n".join(profiles[:5])
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            system=_NAMING_SYSTEM,
            messages=[{"role": "user", "content": f"Member profiles:\n\n{sample}"}],
        )
        text = response.content[0].text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"name": "Community Hub", "description": "A community of like-minded people."}
    except Exception:
        error = True
        raise
    finally:
        metrics.record_call("community_naming", (time.perf_counter() - start) * 1000, error=error)
