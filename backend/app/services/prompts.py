"""
Central loader for all AI system prompts.
Each prompt lives in backend/prompts/*.txt so it can be edited without touching Python code.
Dynamic templates use {placeholder} markers and are formatted with .format() at call sites.
"""
from pathlib import Path

# Resolve to an absolute path so it works regardless of working directory at startup
_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


# Static prompts — used as-is by the agent service
ONBOARDING_SYSTEM = _load("onboarding_system.txt")
PROFILE_SYSTEM = _load("profile_system.txt")
NAMING_SYSTEM = _load("naming_system.txt")
MODERATION_SYSTEM = _load("moderation_system.txt")

# DM persona prompt — split into parts because the tools section is conditionally included
DIGITAL_MEMBER_DM_BASE = _load("digital_member_dm_base.txt")      # Accepts: name, persona, user_name, profile_summary, community_info
DIGITAL_MEMBER_DM_TOOLS = _load("digital_member_dm_tools.txt")    # Accepts: user_name, location_hint
DIGITAL_MEMBER_DM_NO_TOOLS = _load("digital_member_dm_no_tools.txt")  # Accepts: user_name, community_info
DIGITAL_MEMBER_DM_FOOTER = _load("digital_member_dm_footer.txt")  # Static suffix, no placeholders

# Community chat persona prompt — same split pattern as DM
DIGITAL_MEMBER_CHAT_BASE = _load("digital_member_chat_base.txt")    # Accepts: name, persona, community_name, community_description
DIGITAL_MEMBER_CHAT_TOOLS = _load("digital_member_chat_tools.txt")  # Accepts: location_hint
DIGITAL_MEMBER_CHAT_FOOTER = _load("digital_member_chat_footer.txt")  # Static suffix, no placeholders
