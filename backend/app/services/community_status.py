from datetime import datetime

CANDIDATE_MEMBER_THRESHOLD = 5
INACTIVE_DAYS = 30
ARCHIVED_DAYS = 60

VALID_STATUSES = {"ACTIVE", "CANDIDATE", "INACTIVE", "ARCHIVED"}


def compute_status(
    last_message_at: datetime | None,
    real_member_count: int,
    status_override: str | None = None,
) -> str:
    if status_override and status_override in VALID_STATUSES:
        return status_override

    if last_message_at is not None:
        days = (datetime.utcnow() - last_message_at).days
        if days >= ARCHIVED_DAYS:
            return "ARCHIVED"
        if days >= INACTIVE_DAYS:
            return "INACTIVE"

    if real_member_count < CANDIDATE_MEMBER_THRESHOLD:
        return "CANDIDATE"

    return "ACTIVE"
