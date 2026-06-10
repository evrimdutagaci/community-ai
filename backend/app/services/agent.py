import json
import re
import time
import anthropic
from ..config import settings
from .guardrails import wrap_user_content, validate_output
from .metrics import metrics
from .prompts import ONBOARDING_SYSTEM, PROFILE_SYSTEM, NAMING_SYSTEM

client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def chat_onboarding(messages: list[dict], user_context: str = "") -> str:
    start = time.perf_counter()
    error = False
    try:
        system = ONBOARDING_SYSTEM
        if user_context:
            system = f"{ONBOARDING_SYSTEM}\n\nUser context (facts you can state directly if asked):\n{user_context}"
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
            system=PROFILE_SYSTEM,
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
            system=NAMING_SYSTEM,
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
