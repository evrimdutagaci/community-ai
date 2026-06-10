from datetime import datetime

# Status thresholds — days of inactivity before escalating to the next status
CANDIDATE_MEMBER_THRESHOLD = 5   # Fewer than this many real members → CANDIDATE
INACTIVE_DAYS = 30               # No messages for 30 days → INACTIVE
ARCHIVED_DAYS = 60               # No messages for 60 days → ARCHIVED

VALID_STATUSES = {"ACTIVE", "CANDIDATE", "INACTIVE", "ARCHIVED"}


def compute_status(
    last_message_at: datetime | None,
    real_member_count: int,
    status_override: str | None = None,
) -> str:
    """
    Derive the community lifecycle status.
    Admin-set overrides always win; otherwise the status is computed from activity and size.
    """
    if status_override and status_override in VALID_STATUSES:
        return status_override

    if last_message_at is not None:
        days = (datetime.utcnow() - last_message_at).days
        if days >= ARCHIVED_DAYS:
            return "ARCHIVED"
        if days >= INACTIVE_DAYS:
            return "INACTIVE"

    # A community with very few real members is still forming — keep it as CANDIDATE
    if real_member_count < CANDIDATE_MEMBER_THRESHOLD:
        return "CANDIDATE"

    return "ACTIVE"
