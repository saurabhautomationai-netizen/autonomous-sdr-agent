"""Fully mocked, synthetic end-to-end assessment demonstration.

This script deliberately performs no database or network I/O and cannot send mail.
It exercises the production enrichment, scoring, outreach, and behavior orchestration
while replacing every external provider and repository boundary with in-memory data.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from unittest.mock import patch
from uuid import UUID

from app.services.behavior_orchestrator import process_lead_behavior
from app.services.enrichment import enrich_lead
from app.services.initial_outreach import execute_initial_outreach
from app.services.lead_scoring import calculate_lead_score


TEST_RECIPIENT = "delivered@resend.dev"
LEAD_ID = UUID("00000000-0000-4000-8000-000000000101")
INITIAL_LOG_ID = UUID("00000000-0000-4000-8000-000000000201")


def _show(step: str, value: object) -> None:
    print(f"\n=== {step} ===")
    print(json.dumps(value, indent=2, default=str, sort_keys=True))


def run_demo() -> dict:
    lead = {
        "id": LEAD_ID,
        "name": "Jordan Demo",
        "title": "VP Sales",
        "company": "Northstar Demo Labs",
        "domain": "northstar.example",
        "bio": "Owns revenue, budget, and go-to-market strategy.",
        "employee_count": 120,
        "industry": "B2B software",
        "status": "new",
    }
    actions: list[dict] = []

    def record_action(**kwargs):
        action = {"id": f"action-{len(actions) + 1}", **kwargs}
        actions.append(action)
        return action

    print("SAFE ASSESSMENT DEMO: synthetic lead, mocked providers, no network, no email")
    _show("1. synthetic lead fixture", lead)

    provider_miss = ([], {"provider": "hunter", "status": "miss", "results_found": 0, "error": None})
    apollo_miss = ([], {"provider": "apollo", "status": "miss", "results_found": 0, "error": None})
    with patch("app.services.enrichment.hunter_email_finder", return_value=provider_miss), patch(
        "app.services.enrichment.apollo_people_match", return_value=apollo_miss
    ):
        enrichment = enrich_lead(lead["name"], lead["company"], lead["domain"])
    lead["email"] = enrichment["primary_email"]["email"]
    lead["email_source"] = enrichment["primary_email"]["source"]
    _show("2. mocked waterfall enrichment", enrichment)

    with patch(
        "app.services.lead_scoring.calculate_llm_score",
        return_value={"score": 8, "reason": "Mocked contextual fit for a revenue owner."},
    ):
        scoring = calculate_lead_score(
            name=lead["name"], title=lead["title"], company=lead["company"],
            bio=lead["bio"], employee_count=lead["employee_count"],
            industry=lead["industry"], email_confidence=None,
        )
    lead.update({
        "score": scoring["final_score"], "classification": scoring["classification"],
        "score_reason": scoring["score_reason"],
    })
    _show("3. hybrid score (LLM result mocked)", scoring)

    pending = {"id": INITIAL_LOG_ID, "lead_id": LEAD_ID, "status": "pending", "email_type": "initial"}
    sent = {**pending, "status": "sent", "provider_message_id": "mock-resend-message"}

    def set_contacted(_lead_id, status):
        lead["status"] = status
        return dict(lead)

    mocked_send = {
        "id": "mock-resend-message",
        "routing": {
            "logical_recipient": lead["email"],
            "provider_recipient": TEST_RECIPIENT,
            "test_mode": True,
        },
    }
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.initial_outreach.get_lead", return_value=lead))
        stack.enter_context(patch("app.services.initial_outreach.generate_initial_email", return_value={
            "subject": "A practical idea for Northstar", "body": "Synthetic, mocked demo body.",
        }))
        stack.enter_context(patch("app.services.initial_outreach.try_create_initial_email_log", return_value=pending))
        stack.enter_context(patch("app.services.initial_outreach.send_email", return_value=mocked_send))
        stack.enter_context(patch("app.services.initial_outreach.mark_email_sent", return_value=sent))
        stack.enter_context(patch("app.services.initial_outreach.update_lead_status", side_effect=set_contacted))
        stack.enter_context(patch("app.services.initial_outreach.create_agent_action", side_effect=record_action))
        outreach = execute_initial_outreach(LEAD_ID)
    assert outreach["agent_action"]["metadata"]["routing"]["test_mode"] is True
    assert outreach["agent_action"]["metadata"]["routing"]["provider_recipient"] == TEST_RECIPIENT
    _show("4. initial outreach lifecycle (transport mocked)", outreach)

    event = {
        "event_type": "click", "is_suspected_scanner": False,
        "metadata": {"clicked_url": "https://northstar.example/demo"},
    }
    _show("5. simulated persisted event", event)
    mocked_followup = {
        "status": "sent",
        "email_log": {"status": "sent", "provider_message_id": "mock-followup-message"},
        "agent_action": {"action_type": "send_contextual_followup", "mocked": True},
    }
    with ExitStack() as stack:
        stack.enter_context(patch("app.services.behavior_orchestrator.get_lead", return_value=lead))
        stack.enter_context(patch("app.services.behavior_orchestrator.get_lead_events", return_value=[event]))
        stack.enter_context(patch("app.services.behavior_orchestrator.create_agent_action", side_effect=record_action))
        stack.enter_context(patch("app.services.behavior_orchestrator.execute_behavior_followup", return_value=mocked_followup))
        behavior = process_lead_behavior(LEAD_ID, "contacted", 120, execute_actions=True)
    _show("6. Scenario B behavior decision and mocked action", behavior)
    _show("7. persisted-action equivalents captured in memory", actions)

    result = {
        "lead": lead, "enrichment": enrichment, "scoring": scoring,
        "initial_outreach": outreach, "event": event, "behavior": behavior,
        "actions": actions,
    }
    print("\nDEMO COMPLETE: all provider, database, LLM, and email boundaries remained mocked.")
    return result


if __name__ == "__main__":
    run_demo()
