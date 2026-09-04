from uuid import UUID

from sqlalchemy import text

from app.database import engine


def create_email_log(
    lead_id: UUID,
    email_type: str,
    subject: str,
    body: str,
    provider: str = "resend",
    provider_message_id: str | None = None,
    status: str = "pending",
) -> dict:
    """
    Create an email log entry before or after sending.
    """

    query = text(
        """
        INSERT INTO email_logs (
            lead_id,
            email_type,
            subject,
            body,
            provider,
            provider_message_id,
            status,
            sent_at
        )
        VALUES (
            :lead_id,
            :email_type,
            :subject,
            :body,
            :provider,
            :provider_message_id,
            :status,
            CASE
                WHEN :status = 'sent' THEN NOW()
                ELSE NULL
            END
        )
        RETURNING
            id,
            lead_id,
            email_type,
            subject,
            body,
            provider,
            provider_message_id,
            status,
            sent_at,
            created_at
        """
    )

    with engine.begin() as connection:
        row = connection.execute(
            query,
            {
                "lead_id": lead_id,
                "email_type": email_type,
                "subject": subject,
                "body": body,
                "provider": provider,
                "provider_message_id": provider_message_id,
                "status": status,
            },
        ).mappings().one()

    return dict(row)


def try_create_followup_email_log(
    lead_id: UUID,
    email_type: str,
    subject: str,
    body: str,
    provider: str = "resend",
) -> dict | None:
    """Atomically claim one active send per lead/follow-up type."""
    query = text(
        """
        INSERT INTO email_logs (lead_id, email_type, subject, body, provider, status)
        VALUES (:lead_id, :email_type, :subject, :body, :provider, 'pending')
        ON CONFLICT (lead_id, email_type)
            WHERE status IN ('pending', 'sent')
              AND email_type IN ('no_open_followup', 'contextual_followup')
            DO NOTHING
        RETURNING *
        """
    )
    with engine.begin() as connection:
        row = connection.execute(query, {
            "lead_id": lead_id, "email_type": email_type,
            "subject": subject, "body": body, "provider": provider,
        }).mappings().first()
    return dict(row) if row else None


def try_create_initial_email_log(
    lead_id: UUID, subject: str, body: str, provider: str = "resend",
) -> dict | None:
    query = text(
        """
        INSERT INTO email_logs (lead_id, email_type, subject, body, provider, status)
        VALUES (:lead_id, 'initial', :subject, :body, :provider, 'pending')
        ON CONFLICT (lead_id, email_type)
            WHERE status IN ('pending', 'sent') AND email_type = 'initial'
            DO NOTHING
        RETURNING *
        """
    )
    with engine.begin() as connection:
        row = connection.execute(query, {
            "lead_id": lead_id, "subject": subject, "body": body, "provider": provider,
        }).mappings().first()
    return dict(row) if row else None


def mark_email_sent(
    email_log_id: UUID,
    provider_message_id: str,
) -> dict | None:
    """
    Mark an existing email log as successfully sent.
    """

    query = text(
        """
        UPDATE email_logs
        SET
            status = 'sent',
            provider_message_id = :provider_message_id,
            sent_at = NOW()
        WHERE id = :email_log_id AND status = 'pending'
        RETURNING
            id,
            lead_id,
            email_type,
            subject,
            body,
            provider,
            provider_message_id,
            status,
            sent_at,
            created_at
        """
    )

    with engine.begin() as connection:
        row = connection.execute(
            query,
            {
                "email_log_id": email_log_id,
                "provider_message_id": provider_message_id,
            },
        ).mappings().first()

    return dict(row) if row else None


def mark_email_failed(email_log_id: UUID, error_message: str) -> dict | None:
    """Mark the same pending log as failed without storing secrets."""
    query = text(
        """
        UPDATE email_logs
        SET status = 'failed', error_message = :error_message
        WHERE id = :email_log_id AND status = 'pending'
        RETURNING *
        """
    )
    with engine.begin() as connection:
        row = connection.execute(query, {
            "email_log_id": email_log_id,
            "error_message": error_message[:1000],
        }).mappings().first()
    return dict(row) if row else None


def get_email_log_by_provider_message_id(provider_message_id: str) -> dict | None:
    query = text(
        "SELECT * FROM email_logs WHERE provider_message_id = :message_id LIMIT 1"
    )
    with engine.connect() as connection:
        row = connection.execute(
            query, {"message_id": provider_message_id}
        ).mappings().first()
    return dict(row) if row else None


def get_email_log(email_log_id: UUID) -> dict | None:
    query = text("SELECT * FROM email_logs WHERE id = :email_log_id")
    with engine.connect() as connection:
        row = connection.execute(
            query, {"email_log_id": email_log_id}
        ).mappings().first()
    return dict(row) if row else None
