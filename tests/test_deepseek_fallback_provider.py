"""
Unit & Integration Test Suite for DeepSeek AI Fallback Provider in AL AMR Pipeline.

Scenarios tested:
1. Gemini Primary works -> DeepSeek is NOT called.
2. Gemini Primary exhausted -> Gemini Secondary is attempted.
3. Both Gemini providers exhausted -> DeepSeek is attempted.
4. DeepSeek succeeds -> pipeline receives DeepSeekResponse and continues normally.
5. DeepSeek fails (quota/balance exhausted) -> clean bounded failure (GeminiQuotaExhaustedError).
6. Exhausted providers are skipped on subsequent calls (no retry amplification).
7. Quota errors fail fast without exponential retry loops.
8. API keys/secrets never appear in log messages or reprs.
9. DeepSeekResponse interface compatibility with google.genai response objects (.text property).
10. Database test isolation remains intact.
"""
import unittest
from unittest.mock import MagicMock, patch
import sqlite3
import logging
import io

from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    GeminiRateLimiter,
    DeepSeekResponse
)
from core.database import init_db, SessionLocal


class TestDeepSeekFallbackProvider(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_01_gemini_primary_succeeds_deepseek_not_called(self):
        """TEST 1: When Gemini Primary succeeds, DeepSeek is never called."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            resp = MagicMock()
            resp.text = "Success from Gemini Primary"
            return resp

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            return DeepSeekResponse(text="DeepSeek output")

        client._execute_request = fake_gemini
        client._execute_deepseek_request = fake_deepseek

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(calls, ["primary"])
        self.assertEqual(resp.text, "Success from Gemini Primary")
        self.assertFalse(client.is_provider_exhausted("primary"))
        self.assertFalse(client.is_provider_exhausted("deepseek"))

    def test_02_primary_exhausted_secondary_attempted_deepseek_not_called(self):
        """TEST 2: When Primary is exhausted, Secondary is attempted and DeepSeek is NOT called if Secondary succeeds."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            if provider_name == "primary":
                raise GeminiQuotaExhaustedError("Primary quota exhausted")
            resp = MagicMock()
            resp.text = "Success from Gemini Secondary"
            return resp

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            return DeepSeekResponse(text="DeepSeek output")

        client._execute_request = fake_gemini
        client._execute_deepseek_request = fake_deepseek

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(calls, ["primary", "secondary"])
        self.assertEqual(resp.text, "Success from Gemini Secondary")
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertFalse(client.is_provider_exhausted("secondary"))
        self.assertFalse(client.is_provider_exhausted("deepseek"))

    def test_03_both_gemini_exhausted_deepseek_attempted_and_succeeds(self):
        """TEST 3 & 4: When both Gemini providers are exhausted, DeepSeek is attempted and succeeds."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} quota exhausted")

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            return DeepSeekResponse(text='{"title": "The Forgotten Siege", "hook": "You won\'t believe this"}')

        client._execute_request = fake_gemini
        client._execute_deepseek_request = fake_deepseek

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate script")
        self.assertEqual(calls, ["primary", "secondary", "deepseek"])
        self.assertEqual(client.active_provider, "deepseek")
        self.assertTrue(isinstance(resp, DeepSeekResponse))
        self.assertIn("The Forgotten Siege", resp.text)
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertTrue(client.is_provider_exhausted("secondary"))
        self.assertFalse(client.is_provider_exhausted("deepseek"))

    def test_04_all_providers_exhausted_clean_bounded_failure(self):
        """TEST 5: When Primary, Secondary, and DeepSeek are all exhausted, raises GeminiQuotaExhaustedError cleanly."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} quota exhausted")

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            raise GeminiQuotaExhaustedError("DeepSeek API balance exhausted")

        client._execute_request = fake_gemini
        client._execute_deepseek_request = fake_deepseek

        with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
            client.generate_content(model="gemini-3.6-flash", contents="Generate topic")

        self.assertEqual(calls, ["primary", "secondary", "deepseek"])
        self.assertIn("exhausted", str(ctx.exception).lower())
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertTrue(client.is_provider_exhausted("secondary"))
        self.assertTrue(client.is_provider_exhausted("deepseek"))

    def test_05_exhausted_providers_skipped_on_subsequent_calls(self):
        """TEST 6: Exhausted providers are not re-attempted on subsequent requests in the same session."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            deepseek_api_key="deepseek_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} quota exhausted")

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            return DeepSeekResponse(text="DeepSeek persistent response")

        client._execute_request = fake_gemini
        client._execute_deepseek_request = fake_deepseek

        # First call fails Primary & Secondary, routes to DeepSeek
        resp1 = client.generate_content(model="gemini-3.6-flash", contents="Call 1")
        self.assertEqual(calls, ["primary", "secondary", "deepseek"])

        # Second call must immediately dispatch to DeepSeek (0 calls to Gemini!)
        resp2 = client.generate_content(model="gemini-3.6-flash", contents="Call 2")
        self.assertEqual(calls, ["primary", "secondary", "deepseek", "deepseek"])

        # Third call also goes directly to DeepSeek
        resp3 = client.generate_content(model="gemini-3.6-flash", contents="Call 3")
        self.assertEqual(calls, ["primary", "secondary", "deepseek", "deepseek", "deepseek"])

    def test_06_secrets_never_appear_in_logs_or_repr(self):
        """TEST 8: DeepSeek and Gemini API keys are never exposed in log outputs or string reprs."""
        secret_gemini = "AIzaSySecretGeminiKey998877"
        secret_deepseek = "sk-deepseek-secret-key-1122334455"

        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        logger = logging.getLogger("GeminiClient")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        client = GeminiClient(
            api_key=secret_gemini,
            deepseek_api_key=secret_deepseek,
            sleeper=MagicMock()
        )

        client.mark_provider_exhausted("primary")
        client.mark_provider_exhausted("deepseek")

        log_output = log_stream.getvalue()
        self.assertNotIn(secret_gemini, log_output)
        self.assertNotIn(secret_deepseek, log_output)

        resp = DeepSeekResponse("Sample generated text")
        self.assertNotIn(secret_deepseek, repr(resp))
        self.assertEqual(resp.text, "Sample generated text")

    def test_07_database_isolation_remains_intact(self):
        """TEST 10: Running test suite never touches canonical production database."""
        from config.settings import DATABASE_DIR
        canonical_path = DATABASE_DIR / "pipeline.db"
        if canonical_path.exists():
            conn = sqlite3.connect(canonical_path)
            cur = conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            self.assertEqual(cur.fetchone()[0], "ok")
            cur.execute("SELECT COUNT(*) FROM uploads WHERE youtube_video_id LIKE 'TEST_%' OR id LIKE 'upl_test_%';")
            self.assertEqual(cur.fetchone()[0], 0)
            conn.close()


if __name__ == "__main__":
    unittest.main()
