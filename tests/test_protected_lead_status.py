import unittest
from unittest.mock import patch
from uuid import uuid4

from app.repositories.lead_repository import update_lead_enrichment, update_lead_score


class _Mappings:
    def __init__(self, row): self.row = row
    def first(self): return self.row


class _Result:
    def __init__(self, row): self.row = row
    def mappings(self): return _Mappings(self.row)


class _Connection:
    def __init__(self, status): self.status, self.sql = status, ""
    def execute(self, statement, _params):
        self.sql = str(statement)
        return _Result({"id": uuid4(), "status": self.status})


class _Begin:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): return self.connection
    def __exit__(self, *_args): return False


class ProtectedStatusTests(unittest.TestCase):
    def _assert_enrichment_preserves(self, status):
        connection = _Connection(status)
        with patch("app.repositories.lead_repository.engine.begin", return_value=_Begin(connection)):
            result = update_lead_enrichment(uuid4(), "test@example.com", 90)
        self.assertEqual(result["status"], status)
        self.assertIn("WHEN status IN ('unsubscribed', 'dead') THEN status", connection.sql)

    def _assert_scoring_preserves(self, status):
        connection = _Connection(status)
        with patch("app.repositories.lead_repository.engine.begin", return_value=_Begin(connection)):
            result = update_lead_score(uuid4(), 80, "high", "reason", {})
        self.assertEqual(result["status"], status)
        self.assertIn("WHEN status IN ('unsubscribed', 'dead') THEN status", connection.sql)

    def test_unsubscribed_enrichment_stays_unsubscribed(self):
        self._assert_enrichment_preserves("unsubscribed")

    def test_unsubscribed_scoring_stays_unsubscribed(self):
        self._assert_scoring_preserves("unsubscribed")

    def test_dead_enrichment_stays_dead(self):
        self._assert_enrichment_preserves("dead")

    def test_dead_scoring_stays_dead(self):
        self._assert_scoring_preserves("dead")


if __name__ == "__main__":
    unittest.main()
