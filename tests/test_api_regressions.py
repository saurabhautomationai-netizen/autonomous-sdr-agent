import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class APIRouteTests(unittest.TestCase):
    def test_health(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_invalid_extraction_url(self):
        response = client.post("/leads/extract", json={"url": "file:///etc/passwd"})
        self.assertEqual(response.status_code, 400)

    def test_webhook_missing_headers(self):
        response = client.post("/webhooks/resend", content=b"{}")
        self.assertEqual(response.status_code, 400)

    def test_webhook_missing_svix_id(self):
        response = client.post("/webhooks/resend", content=b"{}", headers={
            "svix-timestamp": "1", "svix-signature": "v1,sig",
        })
        self.assertEqual(response.status_code, 400)

    def test_webhook_missing_signature_header(self):
        response = client.post("/webhooks/resend", content=b"{}", headers={
            "svix-id": "id", "svix-timestamp": "1",
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.main.verify_resend_webhook", side_effect=ValueError("bad signature"))
    def test_webhook_invalid_signature(self, verify):
        response = client.post("/webhooks/resend", content=b"{}", headers={
            "svix-id": "id", "svix-timestamp": "1", "svix-signature": "v1,bad",
        })
        self.assertEqual(response.status_code, 400)

    @patch("app.main.process_resend_event", return_value={"status": "processed"})
    @patch("app.main.verify_resend_webhook", return_value={"type": "email.sent", "data": {}})
    def test_valid_mocked_webhook(self, verify, process):
        response = client.post("/webhooks/resend", content=b"{}", headers={
            "svix-id": "id", "svix-timestamp": "1", "svix-signature": "v1,ok",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "processed")

    @patch("app.services.behavior_orchestrator.create_agent_action", return_value={"id": "a"})
    @patch("app.services.behavior_orchestrator.get_lead_events", return_value=[])
    @patch("app.services.behavior_orchestrator.get_lead")
    def test_database_status_overrides_behavior_request(self, get_lead, events, action):
        get_lead.return_value = {"status": "unsubscribed"}
        response = client.post(f"/leads/{uuid4()}/behavior", json={
            "lead_status": "contacted", "seconds_since_sent": 500,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["decision"]["action"], "stop_outreach")

    @patch("app.main.execute_initial_outreach", side_effect=ValueError("Lead must be scored"))
    def test_initial_outreach_validation(self, execute):
        response = client.post(f"/leads/{uuid4()}/initial-outreach")
        self.assertEqual(response.status_code, 422)

    def test_initial_outreach_uses_persisted_scored_lead_projection(self):
        lead_id = uuid4()
        email_log_id = uuid4()
        persisted_lead = {
            "id": lead_id,
            "name": "Synthetic Lead",
            "title": "VP Sales",
            "company": "Synthetic Company",
            "email": "synthetic@example.com",
            "score": 85,
            "classification": "high",
            "score_reason": "Persisted synthetic qualification",
            "status": "scored",
        }
        connection = MagicMock()
        connection.execute.return_value.mappings.return_value.first.return_value = persisted_lead
        engine = MagicMock()
        engine.connect.return_value.__enter__.return_value = connection

        with ExitStack() as stack:
            stack.enter_context(patch("app.repositories.lead_repository.engine", engine))
            stack.enter_context(patch(
                "app.services.initial_outreach.generate_initial_email",
                return_value={"subject": "Mock subject", "body": "Mock body"},
            ))
            stack.enter_context(patch(
                "app.services.initial_outreach.try_create_initial_email_log",
                return_value={"id": email_log_id, "status": "pending"},
            ))
            send = stack.enter_context(patch(
                "app.services.initial_outreach.send_email",
                return_value={"id": "mock-provider-id", "routing": {"test_mode": True}},
            ))
            stack.enter_context(patch(
                "app.services.initial_outreach.mark_email_sent",
                return_value={"id": email_log_id, "status": "sent"},
            ))
            stack.enter_context(patch(
                "app.services.initial_outreach.update_lead_status",
                return_value={**persisted_lead, "status": "contacted"},
            ))
            stack.enter_context(patch(
                "app.services.initial_outreach.create_agent_action",
                return_value={"id": "mock-action-id"},
            ))
            response = client.post(f"/leads/{lead_id}/initial-outreach")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "sent")
        send.assert_called_once_with(
            "synthetic@example.com", "Mock subject", "Mock body", lead_id=lead_id,
        )
        statement, parameters = connection.execute.call_args.args
        self.assertIn("SELECT * FROM leads", str(statement))
        self.assertEqual(parameters, {"lead_id": lead_id})


if __name__ == "__main__":
    unittest.main()
