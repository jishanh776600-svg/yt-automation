"""
Focused Unit & Integration Test Suite for Phase 10.7:
Gemini API Rate-Limit Hardening & Buffer Production Reliability.
Covers:
- Request pacing and minimum interval enforcement
- Repeated calls staying below configured RPM threshold
- 429 RESOURCE_EXHAUSTED detection
- Retry-After / retryDelay extraction from Google RPC payloads
- Exponential backoff with jitter on transient failures
- Bounded retry exhaustion (GeminiQuotaExhaustedError)
- Preservation of fail-safe quarantine behavior
- Zero production mutation on failed generation
- Shared singleton rate limiter across multiple engines
"""
import time
import unittest
from unittest.mock import patch, MagicMock
from core.gemini_client import (
    GeminiRateLimiter,
    GeminiClient,
    GeminiQuotaExhaustedError,
    get_shared_rate_limiter,
    get_gemini_client
)
from engines.deduplication_engine import StoryDeduplicationEngine
from core.database import init_db, SessionLocal
from core.models import Job, Topic


class TestGeminiRateLimiterPhase107(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_01_request_pacing_minimum_interval(self):
        """Test 1: Request pacing enforces minimum interval between calls."""
        sleep_durations = []
        limiter = GeminiRateLimiter(max_rpm=15, min_interval=4.0, sleeper=lambda d: sleep_durations.append(d))

        # First call has no prior request -> no sleep
        w1 = limiter.wait_for_slot()
        self.assertEqual(w1, 0.0)
        self.assertEqual(len(sleep_durations), 0)

        # Immediate second call -> must pace and sleep 4.0s
        w2 = limiter.wait_for_slot()
        self.assertAlmostEqual(w2, 4.0, delta=0.2)
        self.assertEqual(len(sleep_durations), 1)
        self.assertAlmostEqual(sleep_durations[0], 4.0, delta=0.2)

    def test_02_repeated_calls_stay_below_rpm_threshold(self):
        """Test 2: Repeated calls pace properly and enforce the max_rpm window."""
        sleep_calls = []
        # Test with 5 RPM (min_interval=0.1s for fast simulation)
        limiter = GeminiRateLimiter(max_rpm=5, min_interval=0.1, sleeper=lambda d: sleep_calls.append(d))

        for _ in range(7):
            limiter.wait_for_slot()

        # At least 6 sleeps occurred to maintain interval/sliding window
        self.assertGreaterEqual(len(sleep_calls), 6)

    def test_03_429_detection_and_retry_after_extraction(self):
        """Test 3: 429 RESOURCE_EXHAUSTED with Google RPC retryDelay is parsed and respected."""
        sleeps = []
        limiter = GeminiRateLimiter(max_rpm=15, min_interval=0.0, sleeper=lambda d: sleeps.append(d))
        client = GeminiClient(api_key="AIzaSyDummyKeyForTesting", rate_limiter=limiter, sleeper=lambda d: sleeps.append(d))

        # Mock google.genai.Client to raise 429 with retryDelay on first call, then succeed
        mock_response = MagicMock()
        mock_response.text = '{"success": true}'

        err_429 = Exception(
            "429 Resource has been exhausted (e.g. check quota). "
            "{'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '12s'}]}}"
        )

        with patch("google.genai.Client") as mock_genai_cls:
            mock_instance = MagicMock()
            mock_instance.models.generate_content.side_effect = [err_429, mock_response]
            mock_genai_cls.return_value = mock_instance

            resp = client.generate_content(model="gemini-3.6-flash", contents="Test prompt")
            self.assertEqual(resp, mock_response)
            # Must have slept ~12 seconds
            self.assertGreaterEqual(len(sleeps), 1)
            self.assertAlmostEqual(sleeps[0], 12.0, delta=1.5)

    def test_04_exponential_backoff_on_transient_failure(self):
        """Test 4: Exponential backoff is applied when no retryDelay header is provided."""
        sleeps = []
        limiter = GeminiRateLimiter(max_rpm=15, min_interval=0.0, sleeper=lambda d: sleeps.append(d))
        client = GeminiClient(api_key="AIzaSyDummyKeyForTesting", rate_limiter=limiter, sleeper=lambda d: sleeps.append(d))

        mock_response = MagicMock()
        mock_response.text = '{"success": true}'

        err_transient = Exception("503 Service Unavailable: High load")

        with patch("google.genai.Client") as mock_genai_cls:
            mock_instance = MagicMock()
            mock_instance.models.generate_content.side_effect = [err_transient, mock_response]
            mock_genai_cls.return_value = mock_instance

            resp = client.generate_content(model="gemini-3.6-flash", contents="Test", base_delay=2.0)
            self.assertEqual(resp, mock_response)
            self.assertGreaterEqual(len(sleeps), 1)
            # Base delay 2.0 with jitter
            self.assertGreaterEqual(sleeps[0], 1.5)

    def test_05_bounded_retry_exhaustion_raises_gemini_quota_exhausted(self):
        """Test 5: Bounded retries exhaust after 3 attempts and raise GeminiQuotaExhaustedError."""
        sleeps = []
        limiter = GeminiRateLimiter(max_rpm=15, min_interval=0.0, sleeper=lambda d: sleeps.append(d))
        client = GeminiClient(api_key="AIzaSyDummyKeyForTesting", rate_limiter=limiter, sleeper=lambda d: sleeps.append(d))

        err_429 = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")

        with patch("google.genai.Client") as mock_genai_cls:
            mock_instance = MagicMock()
            mock_instance.models.generate_content.side_effect = err_429
            mock_genai_cls.return_value = mock_instance

            with self.assertRaises(GeminiQuotaExhaustedError):
                client.generate_content(model="gemini-3.6-flash", contents="Test", max_retries=3, base_delay=0.1)

            # Exactly 3 attempts made -> 2 backoff sleeps
            self.assertEqual(mock_instance.models.generate_content.call_count, 3)
            self.assertEqual(len(sleeps), 2)

    def test_06_fail_safe_preservation_on_gemini_failure(self):
        """Test 6: StoryDeduplicationEngine fail-closed safety rejects potential duplicate when Gemini fails."""
        dedup = StoryDeduplicationEngine()
        with patch("core.gemini_client.GeminiClient.generate_content") as mock_gen:
            mock_gen.side_effect = GeminiQuotaExhaustedError("Quota exhausted")

            res = dedup.check_semantic_llm(
                candidate_title="The Summer London Smelled So Bad",
                candidate_summary="Sewage boiled in the Thames.",
                candidate_script="",
                existing_title="The Summer London Smelled So Bad Parliament Shut Down",
                existing_summary="Sewage in Thames 1858.",
                existing_script="",
                has_entity_pair_collision=True,
                colliding_pair=(1858, "london")
            )
            # Under fail-closed safety, must reject candidate on entity collision during LLM failure
            self.assertFalse(res.is_allowed)
            self.assertTrue(res.is_duplicate)
            self.assertEqual(res.classification, "REJECTED_POTENTIAL_EVENT_COLLISION")

    def test_07_no_production_mutation_on_failed_gemini_call(self):
        """Test 7: No jobs are scheduled or published in DB when Gemini quota is exhausted."""
        initial_job_count = self.db.query(Job).count()
        limiter = GeminiRateLimiter(max_rpm=15, min_interval=0.0, sleeper=lambda d: None)
        client = GeminiClient(api_key="AIzaSyDummyKeyForTesting", rate_limiter=limiter, sleeper=lambda d: None)

        with patch("google.genai.Client") as mock_genai_cls:
            mock_instance = MagicMock()
            mock_instance.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
            mock_genai_cls.return_value = mock_instance

            try:
                client.generate_content(model="gemini-3.6-flash", contents="Test prompt", max_retries=2, base_delay=0.01)
            except GeminiQuotaExhaustedError:
                pass

        final_job_count = self.db.query(Job).count()
        self.assertEqual(initial_job_count, final_job_count, "Database job count must remain untouched on failure.")

    def test_08_singleton_accessor_shares_same_limiter(self):
        """Test 8: get_gemini_client returns clients that share the exact same rate limiter."""
        c1 = get_gemini_client()
        c2 = get_gemini_client()
        shared_limiter = get_shared_rate_limiter()

        self.assertIs(c1.rate_limiter, shared_limiter)
        self.assertIs(c2.rate_limiter, shared_limiter)


if __name__ == "__main__":
    unittest.main()
