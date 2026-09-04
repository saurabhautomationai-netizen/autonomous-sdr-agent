from uuid import UUID

import json

from sqlalchemy import text

from app.database import engine


def update_lead_enrichment(
    lead_id: UUID,
    email: str,
    email_confidence: float | None,
    candidate_score: float | None = None,
    provider_source: str | None = None,
    verification_status: str | None = None,
    enrichment_metadata: dict | None = None,
) -> dict | None:
    """
    Persist enrichment results and transition the lead
    from its current state to 'enriched'.
    """

    query = text(
        """
        UPDATE leads
        SET
            email = :email,
            email_confidence = :email_confidence,
            provider_verification_confidence = :email_confidence,
            email_candidate_score = :candidate_score,
            email_provider_source = :provider_source,
            email_verification_status = :verification_status,
            enrichment_metadata = CAST(:enrichment_metadata AS jsonb),
            status = CASE
                WHEN status IN ('unsubscribed', 'dead') THEN status
                ELSE 'enriched'
            END,
            updated_at = NOW()
        WHERE id = :lead_id
        RETURNING
            id,
            name,
            title,
            company,
            domain,
            email,
            email_confidence,
            email_candidate_score,
            email_provider_source,
            email_verification_status,
            enrichment_metadata,
            status,
            updated_at
        """
    )

    with engine.begin() as connection:
        result = connection.execute(
            query,
            {
                "lead_id": lead_id,
                "email": email,
                "email_confidence": email_confidence,
                "candidate_score": candidate_score,
                "provider_source": provider_source,
                "verification_status": verification_status,
                "enrichment_metadata": json.dumps(enrichment_metadata or {}),
            },
        )

        row = result.mappings().first()

    return dict(row) if row else None


def update_lead_status(
    lead_id: UUID,
    status: str,
) -> dict | None:
    """
    Update the lead's lifecycle status.
    """

    query = text(
        """
        UPDATE leads
        SET
            status = CASE
                WHEN status IN ('unsubscribed', 'dead') THEN status
                ELSE :status
            END,
            updated_at = NOW()
        WHERE id = :lead_id
        RETURNING
            id,
            name,
            title,
            company,
            email,
            score,
            status,
            updated_at
        """
    )

    with engine.begin() as connection:
        row = connection.execute(
            query,
            {
                "lead_id": lead_id,
                "status": status,
            },
        ).mappings().first()

    return dict(row) if row else None


def get_lead(lead_id: UUID) -> dict | None:
    query = text("SELECT * FROM leads WHERE id = :lead_id")
    with engine.connect() as connection:
        row = connection.execute(query, {"lead_id": lead_id}).mappings().first()
    return dict(row) if row else None


def update_lead_score(
    lead_id: UUID,
    score: int,
    classification: str,
    score_reason: str,
    score_metadata: dict | None = None,
) -> dict | None:
    query = text(
        """
        UPDATE leads
        SET score = :score,
            classification = :classification,
            score_reason = :score_reason,
            score_metadata = CAST(:score_metadata AS jsonb),
            status = CASE
                WHEN status IN ('unsubscribed', 'dead') THEN status
                ELSE 'scored'
            END,
            updated_at = NOW()
        WHERE id = :lead_id
        RETURNING *
        """
    )
    with engine.begin() as connection:
        row = connection.execute(query, {
            "lead_id": lead_id,
            "score": score,
            "classification": classification,
            "score_reason": score_reason,
            "score_metadata": json.dumps(score_metadata or {}),
        }).mappings().first()
    return dict(row) if row else None
