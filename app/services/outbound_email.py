import logging
from uuid import UUID

from app.repositories.agent_action_repository import create_agent_action
from app.repositories.email_log_repository import (
    mark_email_failed,
    mark_email_sent,
    try_create_followup_email_log,
)
from app.repositories.lead_repository import get_lead
from app.services.email_generator import generate_followup_email
from app.services.email_sender import OutboundBlockedError, send_email
from app.logging_utils import log_event


BLOCKED_STATUSES = frozenset({"unsubscribed", "dead"})
logger = logging.getLogger(__name__)


def is_outreach_blocked(status: str | None) -> bool:
    return (status or "").strip().lower() in BLOCKED_STATUSES


def _safe_error(error: Exception) -> str:
    status_code = getattr(getattr(error, "response", None), "status_code", None)
    detail = f" http_status={status_code}" if status_code else ""
    return f"{type(error).__name__}: provider operation failed{detail}"


def execute_behavior_followup(lead_id: UUID, decision: dict) -> dict:
    """Execute Scenario A/B with a reusable, last-moment safety gate."""
    lead = get_lead(lead_id)
    if not lead:
        raise LookupError(f"Lead {lead_id} was not found")

    if is_outreach_blocked(lead.get("status")):
        log_event(logger, "outbound_blocked", lead_id=lead_id, status=lead.get("status"))
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="outbound_safety_gate",
            action_type="blocked_send",
            reason="Outbound send blocked because lead is unsubscribed or dead.",
            status="blocked",
            metadata={"lead_status": lead.get("status"), "scenario": decision.get("scenario")},
        )
        return {"status": "blocked", "email_log": None, "agent_action": action}

    email = generate_followup_email(
        name=lead.get("name") or "there",
        company=lead.get("company") or "your company",
        follow_up_type=decision.get("follow_up_type") or "contextual",
        clicked_url=decision.get("clicked_url"),
    )
    email_type = "no_open_followup" if decision.get("scenario") == "A" else "contextual_followup"
    log_event(logger, "email_generated", lead_id=lead_id, email_type=email_type)
    email_log = try_create_followup_email_log(
        lead_id=lead_id,
        email_type=email_type,
        subject=email["subject"],
        body=email["body"],
    )
    if not email_log:
        log_event(logger, "duplicate_send_blocked", lead_id=lead_id, email_type=email_type)
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="duplicate_send_guard",
            action_type="skip_duplicate_followup",
            reason="An active follow-up already exists for this lead and email type.",
            status="blocked",
            metadata={"email_type": email_type, "scenario": decision.get("scenario")},
        )
        return {"status": "duplicate_skipped", "email_log": None, "agent_action": action}
    log_event(logger, "email_pending", lead_id=lead_id, email_log_id=email_log["id"], email_type=email_type)

    # Re-read immediately before transport to close the normal unsubscribe race window.
    current_lead = get_lead(lead_id)
    if not current_lead or is_outreach_blocked(current_lead.get("status")):
        log_event(logger, "outbound_blocked", lead_id=lead_id, email_log_id=email_log["id"])
        failed = mark_email_failed(email_log["id"], "Blocked by outbound safety gate")
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="outbound_safety_gate",
            action_type="blocked_send",
            reason="Outbound send blocked by a final status check.",
            status="blocked",
            metadata={"email_log_id": str(email_log["id"])},
        )
        return {"status": "blocked", "email_log": failed, "agent_action": action}

    try:
        response = send_email(
            to_email=current_lead["email"],
            subject=email["subject"],
            body=email["body"],
            lead_id=lead_id,
        )
        sent = mark_email_sent(email_log["id"], response["id"])
        log_event(logger, "email_sent", lead_id=lead_id, email_log_id=email_log["id"])
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="behavior_followup",
            action_type=decision["action"],
            reason=decision["reason"],
            metadata={
                "scenario": decision.get("scenario"),
                "email_log_id": str(email_log["id"]),
                "clicked_url_used_as_context": bool(decision.get("clicked_url")),
                "routing": response.get("routing"),
            },
        )
        return {"status": "sent", "email_log": sent, "agent_action": action}
    except OutboundBlockedError as error:
        failure = _safe_error(error)
        failed = mark_email_failed(email_log["id"], failure)
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="outbound_safety_gate",
            action_type="blocked_send",
            reason="Outbound send blocked by the transport status check.",
            status="blocked",
            metadata={"email_log_id": str(email_log["id"])},
        )
        log_event(logger, "outbound_blocked", lead_id=lead_id, email_log_id=email_log["id"])
        return {"status": "blocked", "email_log": failed, "agent_action": action}
    except Exception as error:
        failure = _safe_error(error)
        failed = mark_email_failed(email_log["id"], failure)
        log_event(
            logger, "email_failed", lead_id=lead_id, email_log_id=email_log["id"],
            error_type=type(error).__name__,
        )
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="behavior_followup",
            action_type=decision["action"],
            reason="Provider send failed; no successful delivery was recorded.",
            status="failed",
            metadata={"email_log_id": str(email_log["id"]), "error": failure},
        )
        return {"status": "failed", "email_log": failed, "agent_action": action}
