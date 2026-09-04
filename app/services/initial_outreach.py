import logging
from uuid import UUID

from app.logging_utils import log_event
from app.repositories.agent_action_repository import create_agent_action
from app.repositories.email_log_repository import (
    mark_email_failed, mark_email_sent, try_create_initial_email_log,
)
from app.repositories.lead_repository import get_lead, update_lead_status
from app.services.decision_engine import decide_lead_action
from app.services.email_generator import generate_initial_email
from app.services.email_sender import OutboundBlockedError, send_email
from app.services.outbound_email import _safe_error, is_outreach_blocked


logger = logging.getLogger(__name__)


def execute_initial_outreach(lead_id: UUID) -> dict:
    lead = get_lead(lead_id)
    if not lead:
        raise LookupError(f"Lead {lead_id} was not found")
    if is_outreach_blocked(lead.get("status")):
        action = create_agent_action(
            lead_id=lead_id, trigger_type="outbound_safety_gate",
            action_type="blocked_send", reason="Lead status blocks initial outreach.",
            status="blocked", metadata={"lead_status": lead.get("status")},
        )
        return {"status": "blocked", "email_log": None, "agent_action": action}
    if lead.get("score") is None or not lead.get("classification"):
        raise ValueError("Lead must have a persisted score and classification")
    if not lead.get("email"):
        raise ValueError("Lead must have an enriched email")

    decision = decide_lead_action(lead["score"], lead["classification"])
    log_event(logger, "initial_outreach_decision", lead_id=lead_id, action=decision["action"])
    if not decision["outreach_allowed"]:
        action = create_agent_action(
            lead_id=lead_id, trigger_type="lead_scored", action_type=decision["action"],
            reason=decision["reason"], metadata={"score": lead["score"]},
        )
        return {"status": "not_eligible", "decision": decision, "agent_action": action}

    email = generate_initial_email(
        name=lead.get("name") or "there", title=lead.get("title") or "",
        company=lead.get("company") or "your company",
        score_reason=lead.get("score_reason") or decision["reason"],
    )
    email_log = try_create_initial_email_log(lead_id, email["subject"], email["body"])
    if not email_log:
        action = create_agent_action(
            lead_id=lead_id, trigger_type="duplicate_send_guard",
            action_type="skip_duplicate_initial", reason="Initial outreach already exists.",
            status="blocked", metadata={"email_type": "initial"},
        )
        return {
            "status": "duplicate_skipped", "decision": decision,
            "email_log": None, "agent_action": action,
        }
    log_event(logger, "email_pending", lead_id=lead_id, email_log_id=email_log["id"], email_type="initial")
    try:
        response = send_email(
            lead["email"], email["subject"], email["body"], lead_id=lead_id,
        )
        sent = mark_email_sent(email_log["id"], response["id"])
        update_lead_status(lead_id, "contacted")
        action = create_agent_action(
            lead_id=lead_id, trigger_type="initial_outreach",
            action_type="send_outreach", reason=decision["reason"],
            metadata={
                "email_log_id": str(email_log["id"]),
                "routing": response.get("routing"),
            },
        )
        return {"status": "sent", "decision": decision, "email_log": sent, "agent_action": action}
    except Exception as error:
        failure = _safe_error(error)
        failed = mark_email_failed(email_log["id"], failure)
        blocked = isinstance(error, OutboundBlockedError)
        action = create_agent_action(
            lead_id=lead_id,
            trigger_type="outbound_safety_gate" if blocked else "initial_outreach",
            action_type="blocked_send" if blocked else "send_outreach",
            reason="Initial outreach was blocked." if blocked else "Provider send failed.",
            status="blocked" if blocked else "failed",
            metadata={"email_log_id": str(email_log["id"]), "error_type": type(error).__name__},
        )
        return {"status": "blocked" if blocked else "failed", "decision": decision, "email_log": failed, "agent_action": action}
