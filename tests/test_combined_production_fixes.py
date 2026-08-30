"""
Tests for AL AMR Combined Production Fixes:
1. Issue 1: Drive Vault Reserve Discrepancy & Authoritative Synchronization
2. Issue 2: Gemini Secondary Provider Fallback & Zero-Exposure Safety Invariants
"""
import io
import os
import sys
import logging
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    GeminiRateLimiter
)
from dashboard.data_provider import SystemDataProvider
from dashboard.app import app
from fastapi.testclient import TestClient


class TestCombinedProductionFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.dp = SystemDataProvider()

    def test_01_drive_reserve_telemetry_consistency_1_stock(self):
        """Test 1: 1 physical file in 01_READY returns 1/6 across all field aliases."""
        buf = self.dp.get_buffer_status(ready_stock=1)
        self.assertEqual(buf["ready_stock"], 1)
        self.assertEqual(buf["current_reserve"], 1)
        self.assertEqual(buf["target_reserve"], 6)
        self.assertEqual(buf["health"], "CRITICAL_LOW")
        self.assertIn("1/6 Shorts", buf["health_message"])

    def test_02_drive_reserve_telemetry_consistency_0_stock(self):
        """Test 2: 0 physical files in 01_READY returns 0/6 across all field aliases."""
        buf = self.dp.get_buffer_status(ready_stock=0)
        self.assertEqual(buf["ready_stock"], 0)
        self.assertEqual(buf["current_reserve"], 0)
        self.assertEqual(buf["target_reserve"], 6)
        self.assertEqual(buf["health"], "DEPLETED")
        self.assertIn("0/6 Shorts", buf["health_message"])

    def test_03_drive_reserve_telemetry_consistency_12_stock(self):
        """Test 3: 6 physical files in 01_READY returns 6/6 fully stocked."""
        buf = self.dp.get_buffer_status(ready_stock=6)
        self.assertEqual(buf["ready_stock"], 6)
        self.assertEqual(buf["current_reserve"], 6)
        self.assertEqual(buf["target_reserve"], 6)
        self.assertEqual(buf["health"], "HEALTHY")
        self.assertIn("6/6 Shorts", buf["health_message"])

    def test_04_primary_gemini_success_secondary_not_used(self):
        """Test 4: When primary Gemini succeeds, secondary provider is NEVER invoked."""
        mock_response = MagicMock()
        mock_response.text = "Primary Success Content"

        limiter = GeminiRateLimiter(min_interval=0.0)
        client = GeminiClient(
            api_key="mock_primary_key",
            secondary_api_key="mock_secondary_key",
            rate_limiter=limiter,
            sleeper=lambda s: None
        )

        mock_genai_client = MagicMock()
        mock_genai_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_genai_client) as mock_genai_cls:
            res = client.generate_content(model="gemini-3.6-flash", contents="Test Prompt")
            self.assertEqual(res.text, "Primary Success Content")
            self.assertEqual(client.active_provider, "primary")
            mock_genai_cls.assert_called_once_with(api_key="mock_primary_key")

    def test_05_primary_quota_exhaustion_triggers_secondary_success(self):
        """Test 5: On primary 429 quota exhaustion, secondary provider is invoked and succeeds."""
        mock_secondary_response = MagicMock()
        mock_secondary_response.text = "Secondary Provider Success Content"

        limiter = GeminiRateLimiter(min_interval=0.0)
        client = GeminiClient(
            api_key="mock_primary_key",
            secondary_api_key="mock_secondary_key",
            rate_limiter=limiter,
            sleeper=lambda s: None
        )

        primary_quota_err = Exception("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay quota exceeded")

        def mock_client_factory(api_key):
            m = MagicMock()
            if api_key == "mock_primary_key":
                m.models.generate_content.side_effect = primary_quota_err
            elif api_key == "mock_secondary_key":
                m.models.generate_content.return_value = mock_secondary_response
            return m

        with patch("google.genai.Client", side_effect=mock_client_factory) as mock_genai_cls:
            res = client.generate_content(model="gemini-3.6-flash", contents="Test Prompt")
            self.assertEqual(res.text, "Secondary Provider Success Content")
            self.assertEqual(client.active_provider, "secondary")
            self.assertEqual(mock_genai_cls.call_count, 2)
            mock_genai_cls.assert_any_call(api_key="mock_primary_key")
            mock_genai_cls.assert_any_call(api_key="mock_secondary_key")

    def test_06_both_providers_exhausted_fails_fast_with_error(self):
        """Test 6: When both providers exhaust quota, fails fast with GeminiQuotaExhaustedError."""
        limiter = GeminiRateLimiter(min_interval=0.0)
        client = GeminiClient(
            api_key="mock_primary_key",
            secondary_api_key="mock_secondary_key",
            rate_limiter=limiter,
            sleeper=lambda s: None
        )

        quota_err = Exception("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay quota exceeded")

        def mock_client_factory(api_key):
            m = MagicMock()
            m.models.generate_content.side_effect = quota_err
            return m

        with patch("google.genai.Client", side_effect=mock_client_factory):
            with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
                client.generate_content(model="gemini-3.6-flash", contents="Test Prompt")
            self.assertIn("All configured Gemini providers exhausted daily API quotas", str(ctx.exception))

    def test_07_no_api_keys_exposed_in_logs(self):
        """Test 7: Verification that secret API keys are never exposed in logger outputs."""
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("GeminiClient")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        primary_secret = "AIzaSy_PRIMARY_SUPER_SECRET_12345"
        secondary_secret = "AIzaSy_SECONDARY_SUPER_SECRET_67890"

        limiter = GeminiRateLimiter(min_interval=0.0)
        client = GeminiClient(
            api_key=primary_secret,
            secondary_api_key=secondary_secret,
            rate_limiter=limiter,
            sleeper=lambda s: None
        )

        quota_err = Exception("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay limit reached")

        def mock_client_factory(api_key):
            m = MagicMock()
            m.models.generate_content.side_effect = quota_err
            return m

        with patch("google.genai.Client", side_effect=mock_client_factory):
            try:
                client.generate_content(model="gemini-3.6-flash", contents="Prompt")
            except GeminiQuotaExhaustedError:
                pass

        logger.removeHandler(handler)
        log_output = log_stream.getvalue()

        self.assertNotIn(primary_secret, log_output)
        self.assertNotIn(secondary_secret, log_output)
        self.assertIn("switching immediately to secondary", log_output.lower())

    def test_08_non_retryable_error_does_not_trigger_secondary(self):
        """Test 8: Ordinary non-quota error (e.g. 400 Bad Request) fails immediately without secondary fallback."""
        limiter = GeminiRateLimiter(min_interval=0.0)
        client = GeminiClient(
            api_key="mock_primary_key",
            secondary_api_key="mock_secondary_key",
            rate_limiter=limiter,
            sleeper=lambda s: None
        )

        bad_req_err = ValueError("400 INVALID_ARGUMENT: Invalid prompt structure")

        mock_genai_client = MagicMock()
        mock_genai_client.models.generate_content.side_effect = bad_req_err

        with patch("google.genai.Client", return_value=mock_genai_client) as mock_genai_cls:
            with self.assertRaises(ValueError):
                client.generate_content(model="gemini-3.6-flash", contents="Bad Prompt")
            mock_genai_cls.assert_called_once_with(api_key="mock_primary_key")


if __name__ == "__main__":
    unittest.main()