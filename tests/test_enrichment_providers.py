import unittest
from unittest.mock import Mock, patch

import requests

from app.services.enrichment import enrich_lead
from app.services.enrichment_providers import apollo_people_match, hunter_email_finder


HUNTER_CANDIDATE = {
    "email": "jane.doe@example.com", "source": "hunter", "confidence": 96,
    "verification_status": "valid", "provider_metadata": {},
}
APOLLO_CANDIDATE = {
    "email": "jdoe@example.com", "source": "apollo", "confidence": None,
    "verification_status": "verified", "provider_metadata": {"person_id": "p1"},
}


class EnrichmentWaterfallTests(unittest.TestCase):
    @patch("app.services.enrichment.apollo_people_match")
    @patch("app.services.enrichment.hunter_email_finder")
    def test_hunter_success(self, hunter, apollo):
        hunter.return_value = ([HUNTER_CANDIDATE], {
            "provider": "hunter", "status": "success", "results_found": 1, "error": None,
        })
        result = enrich_lead("Jane Doe", "Example", "example.com")
        apollo.assert_not_called()
        self.assertEqual(result["primary_email"]["source"], "hunter")
        self.assertEqual(result["primary_email"]["provider_verification_confidence"], 96)

    @patch("app.services.enrichment.apollo_people_match")
    @patch("app.services.enrichment.hunter_email_finder")
    def test_hunter_miss_then_apollo_success(self, hunter, apollo):
        hunter.return_value = ([], {
            "provider": "hunter", "status": "miss", "results_found": 0, "error": None,
        })
        apollo.return_value = ([APOLLO_CANDIDATE], {
            "provider": "apollo", "status": "success", "results_found": 1, "error": None,
        })
        result = enrich_lead("Jane Doe", "Example", "example.com")
        self.assertEqual(result["primary_email"]["source"], "apollo")
        self.assertIsNone(result["primary_email"]["provider_verification_confidence"])
        self.assertEqual(result["primary_email"]["provider_verification_status"], "verified")

    @patch("app.services.enrichment.apollo_people_match")
    @patch("app.services.enrichment.hunter_email_finder")
    def test_both_miss_uses_local_pattern(self, hunter, apollo):
        hunter.return_value = ([], {"provider": "hunter", "status": "miss", "results_found": 0})
        apollo.return_value = ([], {"provider": "apollo", "status": "miss", "results_found": 0})
        result = enrich_lead("Jane Doe", "Example", "example.com")
        self.assertEqual(result["primary_email"]["source"], "generated_pattern")
        self.assertIsNone(result["primary_email"]["provider_verification_confidence"])

    @patch("app.services.enrichment.apollo_people_match")
    @patch("app.services.enrichment.hunter_email_finder")
    def test_provider_timeout_continues_fallback(self, hunter, apollo):
        hunter.return_value = ([], {
            "provider": "hunter", "status": "error", "results_found": 0, "error": "timeout",
        })
        apollo.return_value = ([], {
            "provider": "apollo", "status": "error", "results_found": 0,
            "error": "quota_or_rate_limited",
        })
        result = enrich_lead("Jane Doe", "Example", "example.com")
        self.assertEqual(result["primary_email"]["source"], "generated_pattern")
        self.assertEqual(result["waterfall_steps"][0]["error"], "timeout")
        self.assertEqual(result["waterfall_steps"][1]["error"], "quota_or_rate_limited")

    @patch("app.services.enrichment.apollo_people_match")
    @patch("app.services.enrichment.hunter_email_finder")
    def test_multiple_candidates_are_ranked_deterministically(self, hunter, apollo):
        hunter.return_value = ([
            {"email": "info@example.com", "source": "hunter", "confidence": 100,
             "verification_status": "valid"},
            {"email": "jane.doe@example.com", "source": "hunter", "confidence": 50,
             "verification_status": "accept_all"},
        ], {"provider": "hunter", "status": "success", "results_found": 2})
        result = enrich_lead("Jane Doe", "Example", "example.com")
        self.assertEqual(result["primary_email"]["email"], "jane.doe@example.com")
        apollo.assert_not_called()


class ProviderAdapterTests(unittest.TestCase):
    @patch("app.services.enrichment_providers.HUNTER_API_KEY", "hunter-test-key")
    @patch("app.services.enrichment_providers.requests.get")
    def test_hunter_response_is_normalized_and_key_is_header_only(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {
            "email": "jane.doe@example.com", "score": 91,
            "verification": {"status": "valid", "date": "2026-01-01"},
            "accept_all": False,
        }}
        get.return_value = response
        candidates, step = hunter_email_finder(
            name="Jane Doe", company="Example", domain="example.com", timeout=2,
        )
        self.assertEqual(candidates[0]["confidence"], 91)
        self.assertEqual(candidates[0]["verification_status"], "valid")
        self.assertNotIn("api_key", get.call_args.kwargs["params"])
        self.assertEqual(get.call_args.kwargs["headers"]["X-API-KEY"], "hunter-test-key")

    @patch("app.services.enrichment_providers.HUNTER_API_KEY", "hunter-test-key")
    @patch("app.services.enrichment_providers.requests.get", side_effect=requests.Timeout())
    def test_hunter_timeout_is_safe(self, get):
        candidates, step = hunter_email_finder(
            name="Jane Doe", company="Example", domain="example.com", timeout=1,
        )
        self.assertEqual(candidates, [])
        self.assertEqual(step["error"], "timeout")

    @patch("app.services.enrichment_providers.APOLLO_API_KEY", "apollo-test-key")
    @patch("app.services.enrichment_providers.requests.post")
    def test_apollo_response_is_normalized(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"person": {
            "id": "person-1", "email": "jdoe@example.com", "email_status": "verified",
        }}
        post.return_value = response
        candidates, step = apollo_people_match(
            name="Jane Doe", company="Example", domain="example.com", timeout=2,
        )
        self.assertEqual(candidates[0]["source"], "apollo")
        self.assertIsNone(candidates[0]["confidence"])
        self.assertEqual(candidates[0]["verification_status"], "verified")
        self.assertEqual(post.call_args.kwargs["headers"]["x-api-key"], "apollo-test-key")
        self.assertEqual(post.call_args.kwargs["json"]["domain"], "example.com")


if __name__ == "__main__":
    unittest.main()
