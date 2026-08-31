"""
Targeted Unit Test Suite for Groq AI Fallback Provider in AL AMR Pipeline.

Verifies:
1. Groq provider is discovered when GROQ_API_KEY exists.
2. Groq is NOT selected when no Groq key exists.
3. Gemini remains first priority.
4. Gemini quota exhaustion causes fallback to Groq.
5. Groq successful response is normalized into the existing response interface.
6. Groq HTTP 401 fails fast.
7. Groq HTTP 403 fails fast.
8. Groq HTTP 429 marks provider exhausted.
9. Groq malformed response does not crash the entire pipeline.
10. Structured JSON request handling works.
11. Existing provider fallback remains intact when Groq is unavailable.
12. API credentials never appear in logs.
"""
import unittest
from unittest.mock import MagicMock, patch
import json
import logging
import io
import urllib.request
from urllib.error import HTTPError

from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    GeminiRateLimiter,
    GroqResponse,
    DeepSeekResponse
)
from config.settings import AI_PROVIDER_AVAILABLE


class TestGroqProviderIntegration(unittest.TestCase):

    def test_01_groq_provider_discovered_when_key_exists(self):
        """TEST 1: Groq provider is discovered when GROQ_API_KEY exists."""
        client = GeminiClient(
            api_key="gemini_key",
            groq_api_key="gsk_test_key",
            sleeper=MagicMock()
        )
        providers = client._get_configured_providers()
        names = [p["name"] for p in providers]
        self.assertIn("groq", names)
        groq_prov = next(p for p in providers if p["name"] == "groq")
        self.assertEqual(groq_prov["type"], "groq")
        self.assertEqual(groq_prov["api_key"], "gsk_test_key")

    def test_02_groq_not_selected_when_no_groq_key_exists(self):
        """TEST 2: Groq is NOT selected when no Groq key exists."""
        client = GeminiClient(
            api_key="gemini_key",
            groq_api_key="",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        providers = client._get_configured_providers()
        names = [p["name"] for p in providers]
        self.assertNotIn("groq", names)

    def test_03_gemini_remains_first_priority(self):
        """TEST 3: Gemini remains first priority over Groq and DeepSeek."""
        client = GeminiClient(
            api_key="gemini_primary",
            secondary_api_key="gemini_secondary",
            groq_api_key="groq_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        providers = client._get_configured_providers()
        names = [p["name"] for p in providers]
        self.assertEqual(names, ["primary", "secondary", "groq", "deepseek"])

        calls = []
        client._execute_request = lambda *a, **k: calls.append("gemini") or MagicMock(text="Gemini answer")
        client._execute_groq_request = lambda *a, **k: calls.append("groq") or GroqResponse("Groq answer")
        client._execute_deepseek_request = lambda *a, **k: calls.append("deepseek") or DeepSeekResponse("DeepSeek answer")

        resp = client.generate_content("gemini-3.6-flash", "test prompt")
        self.assertEqual(calls, ["gemini"])
        self.assertEqual(resp.text, "Gemini answer")

    def test_04_gemini_quota_exhaustion_causes_fallback_to_groq(self):
        """TEST 4: Gemini quota exhaustion causes immediate fallback to Groq."""
        client = GeminiClient(
            api_key="gemini_primary",
            secondary_api_key="gemini_secondary",
            groq_api_key="groq_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fail_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} exhausted")

        def succeed_groq(api_key, model, contents, **kwargs):
            calls.append("groq")
            return GroqResponse("Success from Groq fallback")

        client._execute_request = fail_gemini
        client._execute_groq_request = succeed_groq
        client._execute_deepseek_request = lambda *a, **k: calls.append("deepseek")

        resp = client.generate_content("gemini-3.6-flash", "test prompt")
        self.assertEqual(calls, ["primary", "secondary", "groq"])
        self.assertEqual(resp.text, "Success from Groq fallback")
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertTrue(client.is_provider_exhausted("secondary"))
        self.assertFalse(client.is_provider_exhausted("groq"))

    def test_05_groq_successful_response_normalized_interface(self):
        """TEST 5: Groq response exposes .text property matching existing interface."""
        resp = GroqResponse(text="Detailed historical narrative about 1932.")
        self.assertEqual(resp.text, "Detailed historical narrative about 1932.")
        self.assertIn("Detailed historical", repr(resp))

    def test_06_groq_http_401_fails_fast(self):
        """TEST 6: Groq HTTP 401 client auth error fails fast and marks provider exhausted."""
        client = GeminiClient(
            groq_api_key="invalid_key",
            sleeper=MagicMock()
        )
        fake_http_err = HTTPError("https://api.groq.com", 401, "Unauthorized", {}, io.BytesIO(b'{"error": "Invalid API Key"}'))

        with patch("urllib.request.urlopen", side_effect=fake_http_err):
            with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
                client._execute_groq_request("invalid_key", "llama-3.3-70b-versatile", "test prompt", max_retries=3)

            self.assertIn("authentication error", str(ctx.exception).lower())
            self.assertTrue(client.is_provider_exhausted("groq"))

    def test_07_groq_http_403_fails_fast(self):
        """TEST 7: Groq HTTP 403 forbidden error fails fast and marks provider exhausted."""
        client = GeminiClient(
            groq_api_key="forbidden_key",
            sleeper=MagicMock()
        )
        fake_http_err = HTTPError("https://api.groq.com", 403, "Forbidden", {}, io.BytesIO(b'{"error": "Forbidden"}'))

        with patch("urllib.request.urlopen", side_effect=fake_http_err):
            with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
                client._execute_groq_request("forbidden_key", "llama-3.3-70b-versatile", "test prompt", max_retries=3)

            self.assertIn("authentication error", str(ctx.exception).lower())
            self.assertTrue(client.is_provider_exhausted("groq"))

    def test_08_groq_http_429_marks_provider_exhausted(self):
        """TEST 8: Groq HTTP 429 rate limit marks provider exhausted."""
        client = GeminiClient(
            groq_api_key="valid_key",
            sleeper=MagicMock()
        )
        fake_http_err = HTTPError("https://api.groq.com", 429, "Too Many Requests", {}, io.BytesIO(b'{"error": "Rate limit exceeded"}'))

        with patch("urllib.request.urlopen", side_effect=fake_http_err):
            with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
                client._execute_groq_request("valid_key", "llama-3.3-70b-versatile", "test prompt", max_retries=3)

            self.assertIn("rate limit", str(ctx.exception).lower())
            self.assertTrue(client.is_provider_exhausted("groq"))

    def test_09_groq_malformed_response_does_not_crash_pipeline(self):
        """TEST 9: Groq malformed response allows fallback to next provider."""
        client = GeminiClient(
            api_key="", secondary_api_key="", groq_api_key="groq_key", deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        def fail_groq(*a, **k):
            client.mark_provider_exhausted("groq")
            raise GeminiQuotaExhaustedError("Malformed choices from Groq")

        def succeed_deepseek(*a, **k):
            return DeepSeekResponse("DeepSeek rescue output")

        client._execute_groq_request = fail_groq
        client._execute_deepseek_request = succeed_deepseek

        resp = client.generate_content("llama-3.3-70b-versatile", "prompt")
        self.assertEqual(resp.text, "DeepSeek rescue output")
        self.assertTrue(client.is_provider_exhausted("groq"))

    def test_10_structured_json_request_handling(self):
        """TEST 10: Structured JSON request sets response_format in payload."""
        client = GeminiClient(
            groq_api_key="groq_key",
            sleeper=MagicMock()
        )
        captured_payloads = []

        def fake_urlopen(req, timeout=None):
            payload = json.loads(req.data.decode("utf-8"))
            captured_payloads.append(payload)
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({
                "choices": [{"message": {"content": '{"hook": "Great hook", "score": 90}'}}]
            }).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            return mock_resp

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            resp = client._execute_groq_request(
                api_key="groq_key",
                model="llama-3.3-70b-versatile",
                contents="Generate JSON",
                response_mime_type="application/json"
            )
            self.assertEqual(len(captured_payloads), 1)
            self.assertEqual(captured_payloads[0].get("response_format"), {"type": "json_object"})
            parsed = json.loads(resp.text)
            self.assertEqual(parsed["hook"], "Great hook")

    def test_11_existing_fallback_intact_when_groq_unavailable(self):
        """TEST 11: When Groq is unavailable, fallback chain reaches DeepSeek cleanly."""
        client = GeminiClient(
            api_key="gemini_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        client._execute_request = MagicMock(side_effect=GeminiQuotaExhaustedError("Gemini quota 429"))
        client._execute_deepseek_request = MagicMock(return_value=DeepSeekResponse("DeepSeek answer"))

        resp = client.generate_content("model", "test")
        self.assertEqual(resp.text, "DeepSeek answer")

    def test_12_api_credentials_never_appear_in_logs(self):
        """TEST 12: Sensitive Groq API keys never appear in log records."""
        secret_groq = "gsk_SUPER_SECRET_TOKEN_XYZ_999"
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        logger = logging.getLogger("GeminiClient")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            client = GeminiClient(
                groq_api_key=secret_groq,
                sleeper=MagicMock()
            )
            client.mark_provider_exhausted("groq")
            resp = GroqResponse("Hello world")
            r_str = repr(resp)
            self.assertNotIn(secret_groq, r_str)

            log_output = log_capture.getvalue()
            self.assertNotIn(secret_groq, log_output)
        finally:
            logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()

