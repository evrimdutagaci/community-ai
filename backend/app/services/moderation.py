import json
import re
import time
import anthropic
from ..config import settings
from .metrics import metrics
from .prompts import MODERATION_SYSTEM

# Haiku is used here instead of Sonnet for cost efficiency — moderation runs on every community message
client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)


async def moderate_message(content: str) -> tuple[bool, str]:
    """Returns (is_violation, reason). Reason is an empty string when there is no violation."""
    start = time.perf_counter()
    error = False
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=MODERATION_SYSTEM,
            messages=[{"role": "user", "content": content}],
        )
        text = response.content[0].text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Model occasionally wraps the JSON in markdown — extract the object directly
            match = re.search(r'\{.*\}', text, re.DOTALL)
            data = json.loads(match.group()) if match else {"violation": False, "reason": ""}
        return bool(data.get("violation", False)), str(data.get("reason", ""))
    except Exception:
        error = True
        raise
    finally:
        metrics.record_call("moderation", (time.perf_counter() - start) * 1000, error=error)
