from uuid import UUID
import logging

from app.repositories.agent_action_repository import create_agent_action
from app.repositories.event_repository import get_lead_events
from app.repositories.lead_repository import get_lead, update_lead_status
from app.config import NO_OPEN_THRESHOLD_SECONDS
from app.services.outbound_email import execute_behavior_followup
from app.services.behavior_engine import evaluate_behavior
from app.logging_utils import log_event


logger = logging.getLogger(__name__)


def process_lead_behavior(
    lead_id: UUID,
    lead_status: str,
    seconds_since_sent: int,
    execute_actions: bool = True,
) -> dict:
    """
    Read a lead's behavioral history,
    evaluate the next action,
    and persist important state changes.
    """

    lead = get_lead(lead_id)
    if not lead:
        raise LookupError(f"Lead {lead_id} was not found")
    authoritative_status = lead.get("status") or lead_status
    events = get_lead_events(lead_id)

    valid_open_count = sum(
        1
        for event in events
        if (
            event["event_type"] == "open"
            and not event["is_suspected_scanner"]
        )
    )

    click_events = [
        event
        for event in events
        if event["event_type"] == "click"
    ]

    click_count = len(click_events)

    last_clicked_url = None

    if click_events:
        last_clicked_url = (
            click_events[-1]
            .get("metadata", {})
            .get("clicked_url")
        )

    reply_events = [
        event
        for event in events
        if event["event_type"] in {"reply", "unsubscribe"}
    ]

    latest_reply_text = None

    if reply_events:
        latest_reply_text = (
            reply_events[-1]
            .get("metadata", {})
            .get("reply_text")
        )

    decision = evaluate_behavior(
        lead_status=authoritative_status,
        seconds_since_sent=seconds_since_sent,
        valid_open_count=valid_open_count,
        click_count=click_count,
        last_clicked_url=last_clicked_url,
        latest_reply_text=latest_reply_text,
        no_open_threshold_seconds=NO_OPEN_THRESHOLD_SECONDS,
    )
    log_event(
        logger, "behavior_evaluated", lead_id=lead_id,
        action=decision["action"], valid_open_count=valid_open_count,
        click_count=click_count,
    )

    updated_lead = None

    if decision["action"] == "unsubscribe_lead":
        updated_lead = update_lead_status(
            lead_id=lead_id,
            status="unsubscribed",
        )

    decision_action = create_agent_action(
        lead_id=lead_id,
        trigger_type="behavior_evaluated",
        action_type=decision["action"],
        reason=decision["reason"],
        metadata={
            "scenario": decision["scenario"],
            "valid_open_count": valid_open_count,
            "click_count": click_count,
            "clicked_url": last_clicked_url,
            "halt_outreach": decision["halt_outreach"],
            "authoritative_lead_status": authoritative_status,
        },
    )

    execution = None
    if execute_actions and decision["action"] in {
        "send_no_open_followup", "send_contextual_followup"
    }:
        execution = execute_behavior_followup(lead_id, decision)
        log_event(
            logger, "followup_executed", lead_id=lead_id,
            scenario=decision["scenario"], status=execution["status"],
        )

    return {
        "decision": decision,
        "event_summary": {
            "valid_open_count": valid_open_count,
            "click_count": click_count,
            "latest_reply_text": latest_reply_text,
            "last_clicked_url": last_clicked_url,
        },
        "updated_lead": updated_lead,
        "decision_action": decision_action,
        "execution": execution,
    }
