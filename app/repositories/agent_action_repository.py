from uuid import UUID

from sqlalchemy import text

from app.database import engine


def create_agent_action(
    lead_id: UUID,
    trigger_type: str,
    action_type: str,
    reason: str,
    status: str = "completed",
    metadata: dict | None = None,
) -> dict:
    """
    Persist an autonomous SDR decision into agent_actions.
    """

    query = text(
        """
        INSERT INTO agent_actions (
            lead_id,
            trigger_type,
            action_type,
            reason,
            status,
            metadata
        )
        VALUES (
            :lead_id,
            :trigger_type,
            :action_type,
            :reason,
            :status,
            CAST(:metadata AS jsonb)
        )
        RETURNING
            id,
            lead_id,
            trigger_type,
            action_type,
            reason,
            status,
            metadata,
            created_at
        """
    )

    import json

    with engine.begin() as connection:
        row = connection.execute(
            query,
            {
                "lead_id": lead_id,
                "trigger_type": trigger_type,
                "action_type": action_type,
                "reason": reason,
                "status": status,
                "metadata": json.dumps(metadata or {}),
            },
        ).mappings().one()

    return dict(row)