import unittest
from unittest.mock import patch
from uuid import uuid4

from app.services.email_sender import OutboundBlockedError, send_email


class EmailSenderSafetyTests(unittest.TestCase):
    @patch("app.services.email_sender.resend.Emails.send")
    @patch("app.services.email_sender.get_lead")
    def test_unsubscribed_is_blocked_at_transport_boundary(self, get_lead, provider_send):
        get_lead.return_value = {"status": "unsubscribed", "email": "lead@example.com"}
        with self.assertRaises(OutboundBlockedError):
            send_email("lead@example.com", "Subject", "Body", lead_id=uuid4())
        provider_send.assert_not_called()

    @patch("app.services.email_sender.resend.Emails.send")
    def test_arbitrary_recipient_without_lead_is_blocked(self, provider_send):
        with self.assertRaises(OutboundBlockedError):
            send_email("person@example.com", "Subject", "Body")
        provider_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
