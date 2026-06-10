from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load(name: str) -> str:
    return (_DIR / name).read_text(encoding="utf-8")


ONBOARDING_SYSTEM = _load("onboarding_system.txt")
PROFILE_SYSTEM = _load("profile_system.txt")
NAMING_SYSTEM = _load("naming_system.txt")
MODERATION_SYSTEM = _load("moderation_system.txt")

DIGITAL_MEMBER_DM_BASE = _load("digital_member_dm_base.txt")
DIGITAL_MEMBER_DM_TOOLS = _load("digital_member_dm_tools.txt")
DIGITAL_MEMBER_DM_NO_TOOLS = _load("digital_member_dm_no_tools.txt")
DIGITAL_MEMBER_DM_FOOTER = _load("digital_member_dm_footer.txt")

DIGITAL_MEMBER_CHAT_BASE = _load("digital_member_chat_base.txt")
DIGITAL_MEMBER_CHAT_TOOLS = _load("digital_member_chat_tools.txt")
DIGITAL_MEMBER_CHAT_FOOTER = _load("digital_member_chat_footer.txt")
