"""
Guardrails: rate limiting, prompt injection detection, jailbreak detection, output validation.
"""
import re
import time
import random
import logging
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# ── Rate Limiter ──────────────────────────────────────────────────────────────

class RateLimiter:
    """In-memory sliding-window rate limiter keyed by arbitrary strings."""

    def __init__(self):
        self._windows: dict[str, deque] = defaultdict(deque)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - window_seconds
        dq = self._windows[key]
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    def seconds_until_reset(self, key: str, window_seconds: int) -> float:
        dq = self._windows.get(key)
        if not dq:
            return 0.0
        return max(0.0, window_seconds - (time.monotonic() - dq[0]))


rate_limiter = RateLimiter()

# Limits: (max_messages, window_seconds)
RATE_LIMITS = {
    "community": (20, 60),
    "onboarding": (10, 60),
    "dm": (15, 60),
}


# ── Prompt Injection Detection ────────────────────────────────────────────────

_INJECTION_PATTERNS = [
    r"ignore\s+(previous|prior|above|all)\s+(instructions?|prompts?|rules?|directives?)",
    r"disregard\s+(previous|prior|above|all)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(previous|prior|above|all)\s+(instructions?|prompts?|rules?)",
    r"new\s+(instructions?|system\s+prompt|directives?)\s*:",
    r"(system|assistant)\s*:\s*(?:ignore|disregard|override)",
    r"<\s*/?system\s*>",
    r"\[INST\]|\[/INST\]",
    r"###\s*instruction",
    r"override\s+(your\s+)?(safety|ethical|content)\s+(filter|guideline|rule)",
    r"your\s+(real|true|actual)\s+(instructions?|purpose|goal|directive)\s+is",
    r"end\s+of\s+system\s+prompt",
    r"reveal\s+your\s+(system\s+)?prompt",
    r"print\s+your\s+(system\s+)?instructions",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def detect_prompt_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text))


def wrap_user_content(text: str) -> str:
    """Wrap user-supplied text in XML tags so the model treats it as data, not instructions."""
    return f"<user_message>{text}</user_message>"


# ── Jailbreak Detection ───────────────────────────────────────────────────────

_JAILBREAK_PATTERNS = [
    r"\bdan\b.*\bmode\b|\bdo\s+anything\s+now\b",
    r"you\s+have\s+no\s+(restrictions?|limitations?|guidelines?|rules?)",
    r"(disable|remove|bypass|ignore)\s+(your\s+)?(safety|content|ethical)\s+(filter|check|guard|policy)",
    r"without\s+(any\s+)?(restrictions?|limitations?|ethical\s+considerations?)",
    r"(unfiltered|unrestricted|uncensored)\s+(mode|response|version|ai)",
    r"(evil|dark|shadow|alternate|unhinged)\s+(mode|version|personality|self)",
    r"simulate\s+(an?\s+)?(ai\s+)?(without|with\s+no)\s+restrictions?",
    r"pretend\s+(you\s+are|to\s+be)\s+(?!a\s+(community\s+)?member|an?\s+AI)",
    r"act\s+as\s+(if\s+you\s+(are|were)\s+)?an?\s+(unrestricted|uncensored|unfiltered)",
    r"you\s+are\s+now\s+(?!a\s+(community\s+)?member)",
    r"jailbreak",
    r"(token|word|prompt)\s+smuggling",
    r"stay\s+in\s+character\s+no\s+matter\s+what",
]

_JAILBREAK_RE = re.compile("|".join(_JAILBREAK_PATTERNS), re.IGNORECASE)


def detect_jailbreak(text: str) -> bool:
    return bool(_JAILBREAK_RE.search(text))


def is_suspicious(text: str) -> bool:
    """Combined check — returns True if either injection or jailbreak is detected."""
    result = detect_prompt_injection(text) or detect_jailbreak(text)
    if result:
        logger.warning("Suspicious input detected: %.120s", text)
    return result


# ── Output Validation ─────────────────────────────────────────────────────────

_LEAK_PATTERNS = [
    r"(my|the)\s+(system\s+prompt|instructions?|directives?)\s+(say|state|tell|require|are)",
    r"as\s+per\s+(my\s+)?(instructions?|system\s+prompt|guidelines?)",
    r"i\s+(was|am)\s+(told|instructed|programmed|designed)\s+to\s+(say|respond|reply|pretend)",
    r"i\s+cannot\s+reveal\s+my\s+(system\s+prompt|instructions?)",
    r"my\s+prompt\s+(says?|states?|tells?\s+me)",
]

_LEAK_RE = re.compile("|".join(_LEAK_PATTERNS), re.IGNORECASE)

_FALLBACKS = [
    "I'm not sure how to respond to that.",
    "Let's keep the conversation going — what else is on your mind?",
    "I didn't quite catch that. Could you rephrase?",
]


def validate_output(text: str, max_length: int = 600) -> tuple[str, bool]:
    """
    Validate and sanitize an AI output before forwarding to users.
    Returns (text_to_use, was_valid).
    If invalid, returns a safe fallback string.
    """
    if not text or not text.strip():
        logger.warning("Output validation failed: empty response")
        return random.choice(_FALLBACKS), False

    if len(text) > max_length:
        logger.warning("Output validation failed: response too long (%d chars)", len(text))
        # Truncate at last sentence boundary within limit
        truncated = text[:max_length]
        last_stop = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
        text = truncated[:last_stop + 1] if last_stop > 0 else truncated
        return text, False

    if _LEAK_RE.search(text):
        logger.warning("Output validation failed: potential system prompt leak")
        return random.choice(_FALLBACKS), False

    return text, True
