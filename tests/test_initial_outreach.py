import unittest
from unittest.mock import patch
from uuid import uuid4

from app.services.initial_outreach import execute_initial_outreach


class InitialOutreachTests(unittest.TestCase):
    def setUp(self):
        self.lead_id = uuid4()
        self.log_id = uuid4()
        self.lead = {
            "id": self.lead_id, "name": "Jane", "title": "CEO", "company": "Example",
            "email": "jane@example.com", "status": "scored", "score": 85,
            "classification": "high", "score_reason": "Strong fit",
        }

    @patch("app.services.initial_outreach.create_agent_action", return_value={"id": "a"})
    @patch("app.services.initial_outreach.update_lead_status", return_value={"status": "contacted"})
    @patch("app.services.initial_outreach.mark_email_sent")
    @patch("app.services.initial_outreach.send_email", return_value={"id": "provider-id"})
    @patch("app.services.initial_outreach.try_create_initial_email_log")
    @patch("app.services.initial_outreach.generate_initial_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.initial_outreach.get_lead")
    def test_success_lifecycle(self, get_lead, generate, claim, send, mark_sent, update, action):
        get_lead.return_value = self.lead
        claim.return_value = {"id": self.log_id, "status": "pending"}
        mark_sent.return_value = {"id": self.log_id, "status": "sent"}
        result = execute_initial_outreach(self.lead_id)
        self.assertEqual(result["status"], "sent")
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs["lead_id"], self.lead_id)
        mark_sent.assert_called_once_with(self.log_id, "provider-id")
        update.assert_called_once_with(self.lead_id, "contacted")

    @patch("app.services.initial_outreach.create_agent_action", return_value={"id": "a"})
    @patch("app.services.initial_outreach.update_lead_status", return_value={"status": "contacted"})
    @patch("app.services.initial_outreach.mark_email_sent")
    @patch("app.services.initial_outreach.send_email")
    @patch("app.services.initial_outreach.try_create_initial_email_log")
    @patch("app.services.initial_outreach.generate_initial_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.initial_outreach.get_lead")
    def test_test_mode_routing_metadata_survives_initial_lifecycle(
        self, get_lead, generate, claim, send, mark_sent, update, action,
    ):
        get_lead.return_value = self.lead
        claim.return_value = {"id": self.log_id, "status": "pending"}
        send.return_value = {
            "id": "provider-id", "routing": {
                "logical_recipient": "jane@example.com",
                "provider_recipient": "delivered@resend.dev", "test_mode": True,
            },
        }
        mark_sent.return_value = {
            "id": self.log_id, "status": "sent", "provider_message_id": "provider-id",
            "sent_at": "2026-09-05T00:00:00Z",
        }
        result = execute_initial_outreach(self.lead_id)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["email_log"]["provider_message_id"], "provider-id")
        metadata = action.call_args.kwargs["metadata"]
        self.assertEqual(metadata["routing"]["provider_recipient"], "delivered@resend.dev")

    @patch("app.services.initial_outreach.create_agent_action", return_value={"id": "a"})
    @patch("app.services.initial_outreach.get_lead")
    @patch("app.services.initial_outreach.send_email")
    def test_unsubscribed_is_blocked(self, send, get_lead, action):
        get_lead.return_value = {**self.lead, "status": "unsubscribed"}
        result = execute_initial_outreach(self.lead_id)
        self.assertEqual(result["status"], "blocked")
        send.assert_not_called()

    @patch("app.services.initial_outreach.create_agent_action", return_value={"id": "a"})
    @patch("app.services.initial_outreach.try_create_initial_email_log", return_value=None)
    @patch("app.services.initial_outreach.generate_initial_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.initial_outreach.get_lead")
    @patch("app.services.initial_outreach.send_email")
    def test_duplicate_is_not_sent(self, send, get_lead, generate, claim, action):
        get_lead.return_value = self.lead
        result = execute_initial_outreach(self.lead_id)
        self.assertEqual(result["status"], "duplicate_skipped")
        send.assert_not_called()

    @patch("app.services.initial_outreach.create_agent_action", return_value={"id": "a"})
    @patch("app.services.initial_outreach.mark_email_failed")
    @patch("app.services.initial_outreach.send_email", side_effect=RuntimeError("provider failed"))
    @patch("app.services.initial_outreach.try_create_initial_email_log")
    @patch("app.services.initial_outreach.generate_initial_email", return_value={"subject": "Hi", "body": "Body"})
    @patch("app.services.initial_outreach.get_lead")
    def test_provider_failure_marks_failed(self, get_lead, generate, claim, send, mark_failed, action):
        get_lead.return_value = self.lead
        claim.return_value = {"id": self.log_id, "status": "pending"}
        mark_failed.return_value = {"id": self.log_id, "status": "failed"}
        result = execute_initial_outreach(self.lead_id)
        self.assertEqual(result["status"], "failed")
        mark_failed.assert_called_once()


if __name__ == "__main__":
    unittest.main()
