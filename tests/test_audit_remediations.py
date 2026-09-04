import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx

from app.services.enrichment_providers import apollo_people_match, hunter_email_finder
from app.services.lead_extractor import UnsafeExtractionURL, fetch_html, validate_public_url
from app.services.lead_scoring import score_bio_keywords, score_title
from app.services.scanner_filter import detect_scanner_burst, is_suspicious_open


class AuthorityMatchingTests(unittest.TestCase):
    def test_expected_authority_titles(self):
        for title in ("CEO", "Chief Revenue Officer", "CRO"):
            self.assertEqual(score_title(title), 30)
        self.assertEqual(score_title("VP of Sales"), 28)

    def test_substring_and_subordinate_false_positives(self):
        self.assertNotEqual(score_title("Microbiologist"), 30)
        self.assertEqual(score_title("Assistant to CEO"), 2)
        self.assertEqual(score_title("Intern to CEO"), 0)

    def test_gtm_requires_token_boundaries(self):
        self.assertEqual(score_bio_keywords("Runs agtmigration project"), (0, []))
        self.assertIn("gtm", score_bio_keywords("Owns GTM strategy")[1])


class SSRFTests(unittest.TestCase):
    def test_non_http_and_private_destinations_are_rejected(self):
        with self.assertRaises(UnsafeExtractionURL):
            validate_public_url("file:///etc/passwd")
        with patch("app.services.lead_extractor.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("169.254.169.254", 80)),
        ]):
            with self.assertRaises(UnsafeExtractionURL):
                validate_public_url("http://metadata.example/")

    @patch("app.services.lead_extractor.httpx.get")
    @patch("app.services.lead_extractor.socket.getaddrinfo")
    def test_public_redirect_to_private_is_rejected(self, getaddrinfo, get):
        def resolve(host, *_args, **_kwargs):
            address = "93.184.216.34" if host == "public.example" else "127.0.0.1"
            return [(2, 1, 6, "", (address, 80))]
        getaddrinfo.side_effect = resolve
        response = Mock(is_redirect=True, headers={"location": "http://localhost/admin"})
        get.return_value = response
        with self.assertRaises(UnsafeExtractionURL):
            fetch_html("https://public.example/profile")
        self.assertEqual(get.call_count, 1)


class ProviderPayloadTests(unittest.TestCase):
    @patch("app.services.enrichment_providers.HUNTER_API_KEY", "test-key")
    @patch("app.services.enrichment_providers.requests.get")
    def test_hunter_single_name_uses_full_name(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {}}
        get.return_value = response
        hunter_email_finder(name="Prince", company="Example", domain="example.com")
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["full_name"], "Prince")
        self.assertNotIn("last_name", params)

    @patch("app.services.enrichment_providers.APOLLO_API_KEY", "test-key")
    @patch("app.services.enrichment_providers.requests.post")
    def test_apollo_http_200_error_is_not_a_miss(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"message": "API key is not authorized for this plan"}
        post.return_value = response
        candidates, step = apollo_people_match(
            name="Jane Doe", company="Example", domain="example.com",
        )
        self.assertEqual(candidates, [])
        self.assertEqual(step["status"], "error")
        self.assertEqual(step["error"], "authentication_or_plan_restricted")
        self.assertNotIn("API key", str(step))


class ScannerHeuristicTests(unittest.TestCase):
    def test_human_like_and_separated_opens_are_not_scanners(self):
        sent = datetime.now(timezone.utc)
        self.assertFalse(is_suspicious_open(
            created_at=sent + timedelta(minutes=2), sent_at=sent,
            user_agent="Mozilla/5.0",
        ))
        separated = [sent + timedelta(minutes=index * 10) for index in range(3)]
        self.assertFalse(detect_scanner_burst(separated, burst_count=3, window_seconds=5))

    def test_immediate_and_known_scanner_user_agent(self):
        sent = datetime.now(timezone.utc)
        self.assertTrue(is_suspicious_open(
            created_at=sent + timedelta(seconds=1), sent_at=sent,
            user_agent="Mozilla/5.0",
        ))
        self.assertTrue(is_suspicious_open(
            created_at=sent + timedelta(minutes=5), sent_at=sent,
            user_agent="Proofpoint URL Defense",
        ))

    def test_rapid_burst(self):
        start = datetime.now(timezone.utc)
        opens = [start + timedelta(milliseconds=100 * index) for index in range(20)]
        self.assertTrue(detect_scanner_burst(opens))


if __name__ == "__main__":
    unittest.main()
