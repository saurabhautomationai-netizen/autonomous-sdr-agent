from datetime import datetime, timedelta
import logging
from uuid import UUID

from app.config import (
    SCANNER_OPEN_BURST_COUNT,
    SCANNER_OPEN_BURST_WINDOW_SECONDS,
    SCANNER_IMMEDIATE_OPEN_SECONDS,
)
from app.repositories.event_repository import (
    create_event,
    get_lead_events,
    mark_events_as_scanner,
)
from app.logging_utils import log_event
from app.repositories.email_log_repository import get_email_log


logger = logging.getLogger(__name__)
SCANNER_USER_AGENT_MARKERS = (
    "barracuda", "mimecast", "proofpoint", "safelinks",
    "microsoft office existence discovery", "urlscan",
)


def is_suspicious_open(
    *, created_at: datetime, sent_at: datetime | None,
    user_agent: str | None, immediate_seconds: float = SCANNER_IMMEDIATE_OPEN_SECONDS,
) -> bool:
    ua = (user_agent or "").lower()
    if any(marker in ua for marker in SCANNER_USER_AGENT_MARKERS):
        return True
    return bool(
        sent_at and 0 <= (created_at - sent_at).total_seconds() <= immediate_seconds
    )


def detect_scanner_burst(
    timestamps: list[datetime],
    burst_count: int = SCANNER_OPEN_BURST_COUNT,
    window_seconds: int = SCANNER_OPEN_BURST_WINDOW_SECONDS,
) -> bool:
    """Return true when at least burst_count opens fit in a rolling time window."""
    if burst_count < 2 or len(timestamps) < burst_count:
        return False
    ordered = sorted(timestamps)
    window = timedelta(seconds=window_seconds)
    return any(
        ordered[index + burst_count - 1] - ordered[index] <= window
        for index in range(len(ordered) - burst_count + 1)
    )


def record_open_event(
    *,
    lead_id: UUID,
    email_log_id: UUID | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    provider: str | None = None,
    provider_event_id: str | None = None,
) -> dict:
    event = create_event(
        lead_id=lead_id,
        email_log_id=email_log_id,
        event_type="open",
        metadata=metadata,
        ip_address=ip_address,
        user_agent=user_agent,
        provider=provider,
        provider_event_id=provider_event_id,
    )
    if not event:  # Idempotent provider replay.
        return {}

    email_log = get_email_log(email_log_id) if email_log_id else None
    if is_suspicious_open(
        created_at=event["created_at"],
        sent_at=(email_log or {}).get("sent_at"),
        user_agent=user_agent,
    ):
        mark_events_as_scanner([event["id"]])
        event["is_suspected_scanner"] = True
        log_event(logger, "scanner_open_detected", lead_id=lead_id, reason="timing_or_user_agent")
        return event

    opens = [
        item for item in get_lead_events(lead_id)
        if item["event_type"] == "open" and not item["is_suspected_scanner"]
    ]
    timestamps = [item["created_at"] for item in opens]
    if detect_scanner_burst(timestamps):
        cutoff = max(timestamps) - timedelta(seconds=SCANNER_OPEN_BURST_WINDOW_SECONDS)
        burst_ids = [item["id"] for item in opens if item["created_at"] >= cutoff]
        mark_events_as_scanner(burst_ids)
        event["is_suspected_scanner"] = True
        log_event(
            logger, "scanner_burst_detected", lead_id=lead_id,
            event_count=len(burst_ids),
            window_seconds=SCANNER_OPEN_BURST_WINDOW_SECONDS,
        )
    return event
