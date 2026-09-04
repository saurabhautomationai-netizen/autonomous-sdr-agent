import unittest
from contextlib import redirect_stdout
from io import StringIO

from scripts.demo_end_to_end import TEST_RECIPIENT, run_demo


class SafeDemoTests(unittest.TestCase):
    def test_demo_uses_synthetic_local_fallback_and_mocked_test_recipient(self):
        output = StringIO()
        with redirect_stdout(output):
            result = run_demo()
        self.assertIn("SAFE ASSESSMENT DEMO", output.getvalue())
        self.assertIn("DEMO COMPLETE", output.getvalue())
        self.assertEqual(result["enrichment"]["primary_email"]["source"], "generated_pattern")
        self.assertEqual(result["initial_outreach"]["status"], "sent")
        routing = result["initial_outreach"]["agent_action"]["metadata"]["routing"]
        self.assertTrue(routing["test_mode"])
        self.assertEqual(routing["provider_recipient"], TEST_RECIPIENT)
        self.assertEqual(result["behavior"]["decision"]["scenario"], "B")
        self.assertEqual(result["behavior"]["decision"]["action"], "send_contextual_followup")


if __name__ == "__main__":
    unittest.main()
