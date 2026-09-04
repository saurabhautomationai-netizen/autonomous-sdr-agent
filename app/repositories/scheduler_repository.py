from sqlalchemy import text

from app.database import engine


def get_due_no_open_leads(threshold_seconds: int, limit: int = 100) -> list[dict]:
    """Find initial sends old enough for Scenario A and with no valid engagement."""
    query = text(
        """
        SELECT
            l.id AS lead_id,
            l.status AS lead_status,
            EXTRACT(EPOCH FROM (NOW() - initial.sent_at))::integer AS seconds_since_sent
        FROM leads l
        JOIN LATERAL (
            SELECT el.id, el.sent_at
            FROM email_logs el
            WHERE el.lead_id = l.id
              AND el.email_type = 'initial'
              AND el.status = 'sent'
            ORDER BY el.sent_at DESC
            LIMIT 1
        ) initial ON true
        WHERE l.status NOT IN ('unsubscribed', 'dead')
          AND initial.sent_at <= NOW() - (:threshold_seconds * INTERVAL '1 second')
          AND NOT EXISTS (
              SELECT 1 FROM events e
              WHERE e.email_log_id = initial.id
                AND (
                    e.event_type = 'click'
                    OR (e.event_type = 'open' AND NOT e.is_suspected_scanner)
                    OR e.event_type IN ('reply', 'unsubscribe')
                )
          )
          AND NOT EXISTS (
              SELECT 1 FROM email_logs followup
              WHERE followup.lead_id = l.id
                AND followup.email_type = 'no_open_followup'
                AND followup.status IN ('pending', 'sent')
          )
        ORDER BY initial.sent_at ASC
        LIMIT :limit
        """
    )
    with engine.connect() as connection:
        rows = connection.execute(query, {
            "threshold_seconds": threshold_seconds, "limit": limit,
        }).mappings().all()
    return [dict(row) for row in rows]
