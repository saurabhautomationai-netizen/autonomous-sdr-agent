import unittest
from unittest.mock import patch
from uuid import uuid4

from app.services.email_sender import (
    OutboundBlockedError,
    ResendTestModeConfigurationError,
    send_email,
)
from app.services.outbound_email import execute_behavior_followup


class TransportRoutingTests(unittest.TestCase):
    def setUp(self):
        self.lead_id = uuid4()
        self.lead = {
            "id": self.lead_id, "email": "prospect@example.com", "status": "contacted",
        }

    @patch("app.services.email_sender.RESEND_API_KEY", "test-api-key")
    @patch("app.services.email_sender.RESEND_TEST_RECIPIENT", "delivered@resend.dev")
    @patch("app.services.email_sender.RESEND_TEST_MODE", True)
    @patch("app.services.email_sender.resend.Emails.send", return_value={"id": "msg-1"})
    @patch("app.services.email_sender.get_lead")
    def test_mode_routes_physical_send_without_mutating_lead(self, get_lead, provider_send):
        get_lead.return_value = self.lead
        original_email = self.lead["email"]
        result = send_email(original_email, "Subject", "Body", lead_id=self.lead_id)
        self.assertEqual(provider_send.call_args.args[0]["to"], ["delivered@resend.dev"])
        self.assertEqual(result["routing"]["logical_recipient"], original_email)
        self.assertTrue(result["routing"]["test_mode"])
        self.assertEqual(self.lead["email"], original_email)

    @patch("app.services.email_sender.RESEND_API_KEY", "test-api-key")
    @patch("app.services.email_sender.RESEND_TEST_MODE", False)
    @patch("app.services.email_sender.resend.Emails.send", return_value={"id": "msg-2"})
    @patch("app.services.email_sender.get_lead")
    def test_production_mode_uses_logical_recipient(self, get_lead, provider_send):
        get_lead.return_value = self.lead
        send_email(self.lead["email"], "Subject", "Body", lead_id=self.lead_id)
        self.assertEqual(provider_send.call_args.args[0]["to"], ["prospect@example.com"])

    @patch("app.services.email_sender.RESEND_TEST_RECIPIENT", "delivered@resend.dev")
    @patch("app.services.email_sender.RESEND_TEST_MODE", True)
    @patch("app.services.email_sender.resend.Emails.send")
    @patch("app.services.email_sender.get_lead")
    def test_unsubscribed_remains_blocked_in_test_mode(self, get_lead, provider_send):
        get_lead.return_value = {**self.lead, "status": "unsubscribed"}
        with self.assertRaises(OutboundBlockedError):
            send_email(self.lead["email"], "Subject", "Body", lead_id=self.lead_id)
        provider_send.assert_not_called()

    @patch("app.services.email_sender.RESEND_API_KEY", "test-api-key")
    @patch("app.services.email_sender.RESEND_TEST_RECIPIENT", "")
    @patch("app.services.email_sender.RESEND_TEST_MODE", True)
    @patch("app.services.email_sender.resend.Emails.send")
    @patch("app.services.email_sender.get_lead")
    def test_missing_test_recipient_is_controlled_error(self, get_lead, provider_send):
        get_lead.return_value = self.lead
        with self.assertRaises(ResendTestModeConfigurationError):
            send_email(self.lead["email"], "Subject", "Body", lead_id=self.lead_id)
        provider_send.assert_not_called()


class FollowupRoutingTests(unittest.TestCase):
    def _run_scenario(self, scenario):
        lead_id, log_id = uuid4(), uuid4()
        lead = {
            "id": lead_id, "name": "Jane", "company": "Example",
            "email": "prospect@example.com", "status": "contacted",
        }
        decision = {
            "scenario": scenario,
            "action": "send_no_open_followup" if scenario == "A" else "send_contextual_followup",
            "reason": "test", "follow_up_type": "restructured_subject" if scenario == "A" else "clicked_link",
            "clicked_url": None if scenario == "A" else "https://example.com/demo",
        }
        with (
            patch("app.services.outbound_email.get_lead", side_effect=[lead, lead]),
            patch("app.services.outbound_email.generate_followup_email", return_value={"subject": "Hi", "body": "Body"}),
            patch("app.services.outbound_email.try_create_followup_email_log", return_value={"id": log_id}),
            patch("app.services.outbound_email.mark_email_sent", return_value={"id": log_id, "status": "sent"}),
            patch("app.services.outbound_email.create_agent_action", return_value={"id": "action"}),
            patch("app.services.email_sender.get_lead", return_value=lead),
            patch("app.services.email_sender.RESEND_API_KEY", "test-api-key"),
            patch("app.services.email_sender.RESEND_TEST_MODE", True),
            patch("app.services.email_sender.RESEND_TEST_RECIPIENT", "delivered@resend.dev"),
            patch("app.services.email_sender.resend.Emails.send", return_value={"id": "provider-id"}) as provider_send,
        ):
            result = execute_behavior_followup(lead_id, decision)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(provider_send.call_args.args[0]["to"], ["delivered@resend.dev"])

    def test_contextual_followup_uses_test_recipient(self):
        self._run_scenario("B")

    def test_no_open_followup_uses_test_recipient(self):
        self._run_scenario("A")


if __name__ == "__main__":
    unittest.main()
