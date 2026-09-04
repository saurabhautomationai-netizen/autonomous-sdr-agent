import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from app.services.behavior_engine import evaluate_behavior
from app.services.outbound_email import execute_behavior_followup
from app.services.scanner_filter import detect_scanner_burst
from app.services.behavior_orchestrator import process_lead_behavior


class BehaviorDecisionTests(unittest.TestCase):
    def test_scenario_a(self):
        result = evaluate_behavior(
            lead_status="contacted", seconds_since_sent=60,
            valid_open_count=0, click_count=0,
        )
        self.assertEqual(result["action"], "send_no_open_followup")

    def test_scenario_b_click(self):
        result = evaluate_behavior(
            lead_status="contacted", seconds_since_sent=5,
            click_count=1, last_clicked_url="https://example.com/demo",
        )
        self.assertEqual(result["action"], "send_contextual_followup")
        self.assertEqual(result["clicked_url"], "https://example.com/demo")

    def test_scenario_b_multiple_opens(self):
        result = evaluate_behavior(
            lead_status="contacted", seconds_since_sent=5, valid_open_count=2,
        )
        self.assertEqual(result["action"], "send_contextual_followup")

    def test_scenario_c_unsubscribe(self):
        result = evaluate_behavior(
            lead_status="contacted", seconds_since_sent=5,
            latest_reply_text="No thanks, unsubscribe me",
        )
        self.assertEqual(result["action"], "unsubscribe_lead")
        self.assertTrue(result["halt_outreach"])

    def test_already_unsubscribed_hard_stop(self):
        result = evaluate_behavior(
            lead_status="unsubscribed", seconds_since_sent=500,
        )
        self.assertEqual(result["action"], "stop_outreach")

    def test_scanner_burst_detection(self):
        start = datetime.now(timezone.utc)
        timestamps = [start + timedelta(milliseconds=200 * i) for i in range(20)]
        self.assertTrue(detect_scanner_burst(timestamps, 20, 5))
        self.assertFalse(detect_scanner_burst(timestamps[:19], 20, 5))


class OutboundLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lead_id = uuid4()
        self.log_id = uuid4()
        self.lead = {
            "id": self.lead_id, "name": "Sam Lee", "company": "Acme",
            "email": "sam@example.com", "status": "contacted",
        }
        self.decision = {
            "action": "send_contextual_followup", "scenario": "B",
            "reason": "Strong engagement", "follow_up_type": "clicked_link",
            "clicked_url": "https://example.com/demo",
        }

    @patch("app.services.outbound_email.create_agent_action", return_value={"id": "action"})
    @patch("app.services.outbound_email.mark_email_sent")
    @patch("app.services.outbound_email.send_email", return_value={"id": "provider-123"})
    @patch("app.services.outbound_email.try_create_followup_email_log")
    @patch("app.services.outbound_email.generate_followup_email")
    @patch("app.services.outbound_email.get_lead")
    def test_pending_to_sent(self, get_lead, generate, create_log, send, mark_sent, action):
        get_lead.side_effect = [self.lead, self.lead]
        generate.return_value = {"subject": "A fresh idea", "body": "Hello"}
        create_log.return_value = {"id": self.log_id, "status": "pending"}
        mark_sent.return_value = {"id": self.log_id, "status": "sent"}
        result = execute_behavior_followup(self.lead_id, self.decision)
        self.assertEqual(result["status"], "sent")
        create_log.assert_called_once()
        mark_sent.assert_called_once_with(self.log_id, "provider-123")
        self.assertEqual(generate.call_args.kwargs["clicked_url"], self.decision["clicked_url"])

    @patch("app.services.outbound_email.create_agent_action", return_value={"id": "action"})
    @patch("app.services.outbound_email.mark_email_failed")
    @patch("app.services.outbound_email.send_email", side_effect=RuntimeError("provider down"))
    @patch("app.services.outbound_email.try_create_followup_email_log")
    @patch("app.services.outbound_email.generate_followup_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.outbound_email.get_lead")
    def test_send_failure_to_failed(self, get_lead, generate, create_log, send, mark_failed, action):
        get_lead.side_effect = [self.lead, self.lead]
        create_log.return_value = {"id": self.log_id, "status": "pending"}
        mark_failed.return_value = {"id": self.log_id, "status": "failed"}
        result = execute_behavior_followup(self.lead_id, self.decision)
        self.assertEqual(result["status"], "failed")
        mark_failed.assert_called_once()

    @patch("app.services.outbound_email.create_agent_action", return_value={"id": "action"})
    @patch("app.services.outbound_email.send_email")
    @patch("app.services.outbound_email.get_lead")
    def test_hard_stop_never_calls_provider(self, get_lead, send, action):
        get_lead.return_value = {**self.lead, "status": "dead"}
        result = execute_behavior_followup(self.lead_id, self.decision)
        self.assertEqual(result["status"], "blocked")
        send.assert_not_called()


class OrchestratorSafetyTests(unittest.TestCase):
    @patch("app.services.behavior_orchestrator.get_lead", return_value={"status": "contacted"})
    @patch("app.services.behavior_orchestrator.create_agent_action", return_value={"id": "action"})
    @patch("app.services.behavior_orchestrator.update_lead_status", return_value={"status": "unsubscribed"})
    @patch("app.services.behavior_orchestrator.get_lead_events")
    def test_unsubscribe_event_updates_lead_and_does_not_send(self, events, update, action, lead):
        events.return_value = [{
            "event_type": "unsubscribe", "is_suspected_scanner": False,
            "metadata": {"reply_text": "not interested"},
        }]
        result = process_lead_behavior(
            uuid4(), "contacted", 5, execute_actions=True
        )
        self.assertEqual(result["decision"]["action"], "unsubscribe_lead")
        update.assert_called_once()
        self.assertIsNone(result["execution"])


if __name__ == "__main__":
    unittest.main()
