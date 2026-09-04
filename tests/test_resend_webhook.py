import unittest
from unittest.mock import patch
from uuid import uuid4

from app.services.resend_webhook import process_resend_event, verify_resend_webhook


class ResendWebhookTests(unittest.TestCase):
    @patch("app.services.resend_webhook.RESEND_WEBHOOK_SECRET", "whsec_test")
    @patch("app.services.resend_webhook.resend.Webhooks.verify")
    def test_signature_verifier_receives_raw_payload_and_svix_headers(self, verify):
        verify.return_value = {"type": "email.sent", "data": {}}
        result = verify_resend_webhook(
            b'{"type":"email.sent","data":{}}',
            {"svix-id": "id-1", "svix-timestamp": "1", "svix-signature": "v1,sig"},
        )
        self.assertEqual(result["type"], "email.sent")
        options = verify.call_args.args[0]
        self.assertEqual(options["payload"], '{"type":"email.sent","data":{}}')
        self.assertEqual(options["headers"]["id"], "id-1")

    @patch("app.services.resend_webhook.create_event")
    @patch("app.services.resend_webhook.get_email_log_by_provider_message_id")
    def test_click_is_mapped_and_provider_id_preserved(self, get_log, create_event):
        lead_id, log_id = uuid4(), uuid4()
        get_log.return_value = {"id": log_id, "lead_id": lead_id}
        create_event.return_value = {"id": uuid4(), "event_type": "click"}
        payload = {
            "type": "email.clicked", "created_at": "2026-01-01T00:00:00Z",
            "data": {
                "email_id": "provider-message", "click": {
                    "link": "https://example.com/demo", "ipAddress": "127.0.0.1",
                    "userAgent": "test-agent",
                },
            },
        }
        result = process_resend_event(payload, "svix-event-1")
        self.assertEqual(result["status"], "processed")
        kwargs = create_event.call_args.kwargs
        self.assertEqual(kwargs["event_type"], "click")
        self.assertEqual(kwargs["provider_event_id"], "svix-event-1")
        self.assertEqual(kwargs["metadata"]["clicked_url"], "https://example.com/demo")

    @patch("app.services.resend_webhook.get_email_log_by_provider_message_id")
    def test_unmatched_message_is_ignored(self, get_log):
        get_log.return_value = None
        result = process_resend_event(
            {"type": "email.opened", "data": {"email_id": "unknown"}}, "svix-2"
        )
        self.assertEqual(result["status"], "ignored")

    def test_received_email_is_not_fabricated_as_reply(self):
        result = process_resend_event(
            {"type": "email.received", "data": {"email_id": "inbound"}}, "svix-3"
        )
        self.assertEqual(result["status"], "ignored")


if __name__ == "__main__":
    unittest.main()
