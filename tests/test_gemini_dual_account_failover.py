"""
Unit & Integration Test Suite for Gemini Dual-Account Routing, Failover, & Quota Resilience.
Tests:
- TEST 1: Primary succeeds -> only primary is used.
- TEST 2: Primary returns quota/RESOURCE_EXHAUSTED -> Secondary succeeds -> production continues using secondary.
- TEST 3: Primary and Secondary both exhausted -> bounded failure, no infinite retries, clear final status.
- TEST 4: Primary returns non-quota error -> no incorrect provider rotation.
- TEST 5: Repeated calls skip previously exhausted provider without retry hammering.
- TEST 6: Production run with 0 produced reports 0 produced and exact reason.
- TEST 7: Test execution leaves canonical database untouched.
"""
import unittest
from unittest.mock import MagicMock, patch
from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    GeminiRateLimiter
)
from core.database import init_db, SessionLocal
from core.models import Job, Topic
import sqlite3
import os


class TestGeminiDualAccountFailover(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_01_primary_succeeds_only_primary_used(self):
        """TEST 1: When Primary succeeds, only Primary provider is dispatched."""
        client = GeminiClient(
            api_key="primary_key_123",
            secondary_api_key="secondary_key_456",
            sleeper=MagicMock()
        )
        call_log = []

        def fake_execute(api_key, model, contents, provider_name="primary", **kwargs):
            call_log.append(provider_name)
            resp = MagicMock()
            resp.text = '{"success": true}'
            return resp

        client._execute_request = fake_execute

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(call_log, ["primary"])
        self.assertEqual(client.active_provider, "primary")
        self.assertFalse(client.is_provider_exhausted("primary"))

    def test_02_primary_quota_exhausted_failover_to_secondary(self):
        """TEST 2: When Primary returns 429 RESOURCE_EXHAUSTED, Secondary is used."""
        client = GeminiClient(
            api_key="primary_key_123",
            secondary_api_key="secondary_key_456",
            sleeper=MagicMock()
        )
        call_log = []

        def fake_execute(api_key, model, contents, provider_name="primary", **kwargs):
            call_log.append(provider_name)
            if provider_name == "primary":
                raise GeminiQuotaExhaustedError("Daily API quota exhausted on PRIMARY provider")
            resp = MagicMock()
            resp.text = '{"success_from_secondary": true}'
            return resp

        client._execute_request = fake_execute

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(call_log, ["primary", "secondary"])
        self.assertEqual(client.active_provider, "secondary")
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertFalse(client.is_provider_exhausted("secondary"))

    def test_03_all_providers_exhausted_bounded_failure(self):
        """TEST 3: When all providers are exhausted, bounded failure raises clean GeminiQuotaExhaustedError."""
        client = GeminiClient(
            api_key="primary_key_123",
            secondary_api_key="secondary_key_456",
            sleeper=MagicMock()
        )
        call_log = []

        def fake_execute(api_key, model, contents, provider_name="primary", **kwargs):
            call_log.append(provider_name)
            raise GeminiQuotaExhaustedError(f"Daily quota exhausted on {provider_name}")

        client._execute_request = fake_execute

        with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
            client.generate_content(model="gemini-3.6-flash", contents="Generate topic")

        self.assertIn("exhausted", str(ctx.exception).lower())
        self.assertEqual(call_log, ["primary", "secondary"])
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertTrue(client.is_provider_exhausted("secondary"))

    def test_04_non_quota_error_does_not_rotate_providers(self):
        """TEST 4: Non-quota errors (e.g. ValueError, 400 Bad Request) do not rotate providers."""
        client = GeminiClient(
            api_key="primary_key_123",
            secondary_api_key="secondary_key_456",
            sleeper=MagicMock()
        )
        call_log = []

        def fake_execute(api_key, model, contents, provider_name="primary", **kwargs):
            call_log.append(provider_name)
            raise ValueError("Prompt blocked by safety settings")

        client._execute_request = fake_execute

        with self.assertRaises(ValueError):
            client.generate_content(model="gemini-3.6-flash", contents="Bad prompt")

        # Must have only attempted primary and NOT rotated or marked exhausted
        self.assertEqual(call_log, ["primary"])
        self.assertFalse(client.is_provider_exhausted("primary"))

    def test_05_repeated_calls_skip_exhausted_provider(self):
        """TEST 5: Once Primary is exhausted, subsequent calls immediately route to Secondary without touching Primary."""
        client = GeminiClient(
            api_key="primary_key_123",
            secondary_api_key="secondary_key_456",
            sleeper=MagicMock()
        )
        call_log = []

        def fake_execute(api_key, model, contents, provider_name="primary", **kwargs):
            call_log.append(provider_name)
            if provider_name == "primary":
                raise GeminiQuotaExhaustedError("Daily API quota exhausted on PRIMARY")
            resp = MagicMock()
            resp.text = '{"ok": true}'
            return resp

        client._execute_request = fake_execute

        # First request triggers failover: Primary (fails) -> Secondary (succeeds)
        resp1 = client.generate_content(model="gemini-3.6-flash", contents="Call 1")
        self.assertEqual(call_log, ["primary", "secondary"])

        # Second request must directly route to Secondary (0 calls to Primary!)
        resp2 = client.generate_content(model="gemini-3.6-flash", contents="Call 2")
        self.assertEqual(call_log, ["primary", "secondary", "secondary"])

        # Third request must also directly route to Secondary
        resp3 = client.generate_content(model="gemini-3.6-flash", contents="Call 3")
        self.assertEqual(call_log, ["primary", "secondary", "secondary", "secondary"])

    def test_06_production_summary_reports_exact_quota_reason(self):
        """TEST 6: Production run with 0 created reports BLOCKED / ALL_GEMINI_PROVIDERS_EXHAUSTED."""
        from main import ShortsPipeline
        pipeline = ShortsPipeline()
        pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=0)

        # Mock produce_single_to_vault to raise GeminiQuotaExhaustedError
        def fake_produce():
            raise GeminiQuotaExhaustedError("All configured Gemini providers exhausted daily API quotas.")

        pipeline.produce_single_to_vault = fake_produce

        produced_count, summary = pipeline.maintain_buffer(target_stock=6)
        self.assertEqual(produced_count, 0)
        self.assertEqual(summary["outcome"], "BLOCKED")
        self.assertEqual(summary["block_reason"], "ALL_GEMINI_PROVIDERS_EXHAUSTED")
        self.assertEqual(summary["produced_count"], 0)

    def test_07_canonical_db_remains_isolated_during_tests(self):
        """TEST 7: Executing test suite leaves canonical pipeline.db completely isolated and intact."""
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
