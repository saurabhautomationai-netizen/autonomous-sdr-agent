import asyncio
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.main import LeadScoringRequest, score_and_save_lead
from app.repositories.scheduler_repository import get_due_no_open_leads
from app.services.outbound_email import execute_behavior_followup
from app.services.scheduler import run_scheduler, run_scheduler_once


class SchedulerTests(unittest.TestCase):
    @patch("app.services.scheduler.process_lead_behavior")
    @patch("app.services.scheduler.get_due_no_open_leads")
    def test_due_lead_is_evaluated_automatically(self, get_due, process):
        lead_id = uuid4()
        get_due.return_value = [{
            "lead_id": lead_id, "lead_status": "contacted", "seconds_since_sent": 90,
        }]
        process.return_value = {
            "decision": {"action": "send_no_open_followup"},
            "execution": {"status": "sent"},
        }
        results = run_scheduler_once()
        self.assertEqual(len(results), 1)
        process.assert_called_once_with(
            lead_id=lead_id, lead_status="contacted",
            seconds_since_sent=90, execute_actions=True,
        )

    @patch("app.repositories.scheduler_repository.engine")
    def test_due_query_derives_elapsed_time_and_filters_unsafe_duplicates(self, engine):
        mappings = MagicMock()
        mappings.all.return_value = []
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value = mappings
        engine.connect.return_value.__enter__.return_value = connection

        self.assertEqual(get_due_no_open_leads(3600, limit=25), [])

        statement, parameters = connection.execute.call_args.args
        sql = str(statement)
        self.assertIn("NOW() - initial.sent_at", sql)
        self.assertIn("email_type = 'initial'", sql)
        self.assertIn("l.status NOT IN ('unsubscribed', 'dead')", sql)
        self.assertIn("followup.email_type = 'no_open_followup'", sql)
        self.assertIn("followup.status IN ('pending', 'sent')", sql)
        self.assertEqual(parameters, {"threshold_seconds": 3600, "limit": 25})


class SchedulerShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_pre_set_stop_event_exits_without_polling(self):
        stop = asyncio.Event()
        stop.set()
        with patch("app.services.scheduler.run_scheduler_once") as run_once:
            await run_scheduler(stop)
        run_once.assert_not_called()


class DuplicateGuardTests(unittest.TestCase):
    @patch("app.services.outbound_email.create_agent_action", return_value={"id": "action"})
    @patch("app.services.outbound_email.try_create_followup_email_log", return_value=None)
    @patch("app.services.outbound_email.generate_followup_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.outbound_email.get_lead")
    @patch("app.services.outbound_email.send_email")
    def test_duplicate_claim_never_sends(self, send, get_lead, generate, claim, action):
        lead_id = uuid4()
        get_lead.return_value = {
            "id": lead_id, "status": "contacted", "email": "lead@example.com",
            "name": "Lead", "company": "Example",
        }
        result = execute_behavior_followup(lead_id, {
            "scenario": "A", "action": "send_no_open_followup", "reason": "No open",
            "follow_up_type": "restructured_subject", "clicked_url": None,
        })
        self.assertEqual(result["status"], "duplicate_skipped")
        send.assert_not_called()


class ScorePersistenceTests(unittest.TestCase):
    @patch("app.main.update_lead_score")
    @patch("app.main.calculate_lead_score")
    def test_score_breakdown_is_persisted(self, calculate, update):
        lead_id = uuid4()
        calculate.return_value = {
            "final_score": 82, "classification": "high", "rule_score": 74,
            "llm_score": 8, "score_reason": "Strong fit",
            "rule_breakdown": {"title_score": 28}, "authority_matches": ["budget"],
        }
        update.return_value = {"id": lead_id, "score": 82, "classification": "high"}
        result = score_and_save_lead(lead_id, LeadScoringRequest(
            name="Jane Doe", title="VP Sales", company="Example", bio="Owns budget",
        ))
        kwargs = update.call_args.kwargs
        self.assertEqual(kwargs["score"], 82)
        self.assertEqual(kwargs["classification"], "high")
        self.assertEqual(kwargs["score_reason"], "Strong fit")
        self.assertEqual(kwargs["score_metadata"]["rule_breakdown"], {"title_score": 28})
        self.assertEqual(result["database_record"]["score"], 82)


if __name__ == "__main__":
    unittest.main()
