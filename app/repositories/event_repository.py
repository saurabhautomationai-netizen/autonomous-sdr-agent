import json
from uuid import UUID

from sqlalchemy import text

from app.database import engine


def create_event(
    lead_id: UUID,
    event_type: str,
    email_log_id: UUID | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    is_suspected_scanner: bool = False,
    provider: str | None = None,
    provider_event_id: str | None = None,
) -> dict:
    """
    Persist an engagement event for a lead.
    """

    query = text(
        """
        INSERT INTO events (
            lead_id,
            email_log_id,
            event_type,
            metadata,
            ip_address,
            user_agent,
            is_suspected_scanner
            , provider
            , provider_event_id
        )
        VALUES (
            :lead_id,
            :email_log_id,
            :event_type,
            CAST(:metadata AS jsonb),
            :ip_address,
            :user_agent,
            :is_suspected_scanner
            , :provider
            , :provider_event_id
        )
        ON CONFLICT (provider, provider_event_id)
            WHERE provider_event_id IS NOT NULL
            DO NOTHING
        RETURNING
            id,
            lead_id,
            email_log_id,
            event_type,
            metadata,
            ip_address,
            user_agent,
            is_suspected_scanner,
            provider,
            provider_event_id,
            created_at
        """
    )

    with engine.begin() as connection:
        row = connection.execute(
            query,
            {
                "lead_id": lead_id,
                "email_log_id": email_log_id,
                "event_type": event_type,
                "metadata": json.dumps(metadata or {}),
                "ip_address": ip_address,
                "user_agent": user_agent,
                "is_suspected_scanner": is_suspected_scanner,
                "provider": provider,
                "provider_event_id": provider_event_id,
            },
        ).mappings().first()

    return dict(row) if row else {}


def get_lead_events(
    lead_id: UUID,
) -> list[dict]:
    """
    Return all behavioral events for a lead.
    """

    query = text(
        """
        SELECT
            id,
            lead_id,
            email_log_id,
            event_type,
            metadata,
            ip_address,
            user_agent,
            is_suspected_scanner,
            created_at
        FROM events
        WHERE lead_id = :lead_id
        ORDER BY created_at ASC
        """
    )

    with engine.connect() as connection:
        rows = connection.execute(
            query,
            {
                "lead_id": lead_id,
            },
        ).mappings().all()

    return [dict(row) for row in rows]


def mark_events_as_scanner(event_ids: list[UUID]) -> None:
    if not event_ids:
        return
    query = text(
        "UPDATE events SET is_suspected_scanner = true WHERE id = ANY(:event_ids)"
    )
    with engine.begin() as connection:
        connection.execute(query, {"event_ids": event_ids})
