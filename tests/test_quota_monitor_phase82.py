"""
Phase 8.2 Unified API & Service Limit Monitor Tests.
Covers:
  1. /api/quotas requires authentication
  2. /api/quotas returns normalized schema with 5 providers
  3. Pexels observed values surfaced correctly
  4. Pexels unknown state preserved when unobserved
  5. YouTube internal 4/day limit unchanged
  6. YouTube API quota not fabricated (labeled ESTIMATED)
  7. Gemini quota not fabricated (labeled UNKNOWN)
  8. GitHub PAT never appears in responses
  9. Google OAuth credentials never appear in responses
  10. Drive storage values only shown when measurable
  11. UNKNOWN state works correctly across providers
  12. Provider failure does not crash the dashboard
  13. Provider 429 handling safe
  14. Frontend template contains API & Service Limits card
  15. Frontend template contains zero secrets
  16. Service worker does not cache /api/quotas or /api/*
  17. Quota endpoint performs zero production mutation
  18. Existing Pexels fallback remains intact
  19. Existing session authentication enforced
  20. Existing CSRF protections remain intact
"""
import os
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import PEXELS_API_KEY, GITHUB_PAT
from config.constants import DAILY_SHORTS_LIMIT
from core.models import Base, ProviderUsage, UploadRecord
from dashboard.app import app
from dashboard.auth import session_store, SESSION_COOKIE_NAME
from dashboard.data_provider import SystemDataProvider


class TestQuotaMonitorPhase82(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.provider = SystemDataProvider()
        self.client = TestClient(app)
        self.session_id, self.csrf_token = session_store.create_session("admin", duration_hours=1)
        self.auth_cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        self.db.close()
        session_store.invalidate_session(self.session_id)

    def test_01_quotas_requires_authentication(self):
        """Verify GET /api/quotas rejects unauthenticated requests with 401."""
        resp = self.client.get("/api/quotas")
        self.assertEqual(resp.status_code, 401)

    def test_02_quotas_returns_normalized_schema(self):
        """Verify GET /api/quotas returns 5 providers matching normalized schema."""
        resp = self.client.get("/api/quotas", cookies=self.auth_cookies)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("services", data)
        self.assertEqual(len(data["services"]), 5)

        required_fields = [
            "service", "display_name", "category", "limit", "used", "remaining",
            "unit", "reset_type", "status", "measurement_type", "automation_impact",
            "fallback_available", "message"
        ]
        for s in data["services"]:
            for f in required_fields:
                self.assertIn(f, s, f"Field {f} missing in service {s.get('service')}")

    def test_03_pexels_observed_values_surfaced_correctly(self):
        """Verify that observed Pexels rate limits are surfaced in /api/quotas."""
        pu = ProviderUsage(
            provider_name="pexels",
            units_used=1,
            endpoint="/v1/search",
            status_code=200,
            rate_limit=20000,
            rate_remaining=18500,
            rate_reset=1750000000,
            is_observed=True
        )
        self.db.add(pu)
        self.db.commit()

        res = self.provider.get_all_service_quotas(self.db)
        pexels = next(s for s in res["services"] if s["service"] == "pexels_api")
        self.assertEqual(pexels["limit"], 20000)
        self.assertEqual(pexels["remaining"], 18500)
        self.assertEqual(pexels["status"], "OK")
        self.assertEqual(pexels["measurement_type"], "LIVE_OBSERVED")
        self.assertTrue(pexels["fallback_available"])

    def test_04_pexels_unknown_state_when_unobserved(self):
        """Verify Pexels remaining is None and status is UNKNOWN when no headers exist."""
        res = self.provider.get_all_service_quotas(self.db)
        pexels = next(s for s in res["services"] if s["service"] == "pexels_api")
        self.assertIsNone(pexels["limit"])
        self.assertIsNone(pexels["remaining"])
        self.assertEqual(pexels["status"], "UNKNOWN")
        self.assertEqual(pexels["measurement_type"], "UNKNOWN")

    def test_05_youtube_internal_limit_remains_four(self):
        """Verify YouTube internal production capacity is strictly 4 Shorts/day."""
        self.assertEqual(DAILY_SHORTS_LIMIT, 4)
        res = self.provider.get_all_service_quotas(self.db)
        yt = next(s for s in res["services"] if s["service"] == "youtube_data_api")
        self.assertEqual(yt["internal_production_capacity"]["limit"], 4)
        self.assertEqual(yt["internal_production_capacity"]["unit"], "Shorts/day")

    def test_06_youtube_api_quota_not_fabricated(self):
        """Verify YouTube API quota is labeled ESTIMATED and does not claim live measurement."""
        res = self.provider.get_all_service_quotas(self.db)
        yt = next(s for s in res["services"] if s["service"] == "youtube_data_api")
        self.assertEqual(yt["measurement_type"], "ESTIMATED")
        self.assertEqual(yt["limit"], 10000)
        self.assertEqual(yt["reset_type"], "DAILY")
        self.assertEqual(yt["automation_impact"], "HIGH")

    def test_07_gemini_quota_not_fabricated(self):
        """Verify Gemini quota is labeled UNKNOWN and shows deterministic fallback."""
        res = self.provider.get_all_service_quotas(self.db)
        gem = next(s for s in res["services"] if s["service"] == "gemini_api")
        self.assertIsNone(gem["remaining"])
        self.assertEqual(gem["status"], "UNKNOWN")
        self.assertEqual(gem["reset_type"], "TIER_DEPENDENT")
        self.assertTrue(gem["fallback_available"])
        self.assertEqual(gem["automation_impact"], "LOW")

    def test_08_github_pat_never_appears_in_responses(self):
        """Security: Verify GITHUB_PAT never leaks into /api/quotas or /api/state."""
        if GITHUB_PAT:
            resp_quotas = self.client.get("/api/quotas", cookies=self.auth_cookies)
            self.assertNotIn(GITHUB_PAT, resp_quotas.text)
            resp_state = self.client.get("/api/state", cookies=self.auth_cookies)
            self.assertNotIn(GITHUB_PAT, resp_state.text)

    def test_09_google_credentials_never_appear_in_responses(self):
        """Security: Verify OAuth tokens or client secrets do not appear in API responses."""
        resp = self.client.get("/api/quotas", cookies=self.auth_cookies)
        text = resp.text.lower()
        self.assertNotIn("client_secret", text)
        self.assertNotIn("refresh_token", text)
        self.assertNotIn("access_token", text)

    def test_10_drive_storage_values_only_shown_when_measurable(self):
        """Verify Drive storage returns values when available and UNKNOWN when offline."""
        from config.settings import GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES
        # 1. With explicit 5 TB capacity
        with patch.object(self.provider.drive_engine, "get_storage_quota", return_value={"limit": GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES, "usage": 3000000000}):
            res = self.provider.get_all_service_quotas(self.db)
            drive = next(s for s in res["services"] if s["service"] == "google_drive")
            self.assertEqual(drive["limit"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES)
            self.assertEqual(drive["used"], 3000000000)
            self.assertEqual(drive["remaining"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES - 3000000000)
            self.assertEqual(drive["status"], "SAFE")
            self.assertEqual(drive["measurement_type"], "LIVE_OBSERVED")
            self.assertIn("5.00 TB", drive["message"])

        # 2. When API limit is None, defaults to configured 5 TB entitlement
        with patch.object(self.provider.drive_engine, "get_storage_quota", return_value={"usage": 3000000000}):
            res_default = self.provider.get_all_service_quotas(self.db)
            drive_def = next(s for s in res_default["services"] if s["service"] == "google_drive")
            self.assertEqual(drive_def["limit"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES)
            self.assertEqual(drive_def["used"], 3000000000)
            self.assertEqual(drive_def["remaining"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES - 3000000000)

        # 3. When offline (None), returns UNKNOWN
        with patch.object(self.provider.drive_engine, "get_storage_quota", return_value=None):
            res_offline = self.provider.get_all_service_quotas(self.db)
            drive_off = next(s for s in res_offline["services"] if s["service"] == "google_drive")
            self.assertIsNone(drive_off["remaining"])
            self.assertEqual(drive_off["status"], "UNKNOWN")

    def test_11_unknown_state_works_correctly(self):
        """Verify services with unmeasurable balances correctly report UNKNOWN status."""
        res = self.provider.get_all_service_quotas(self.db)
        gemini = next(s for s in res["services"] if s["service"] == "gemini_api")
        github = next(s for s in res["services"] if s["service"] == "github_actions")
        self.assertEqual(gemini["status"], "UNKNOWN")
        self.assertEqual(github["status"], "UNKNOWN")

    def test_12_provider_failure_does_not_crash_dashboard(self):
        """Verify that an exception in any single provider does not crash get_all_service_quotas."""
        with patch.object(self.provider, "get_pexels_quota_status", side_effect=RuntimeError("Pexels DB error")):
            res = self.provider.get_all_service_quotas(self.db)
            self.assertIn("services", res)
            self.assertTrue(len(res["services"]) >= 4)

    def test_13_provider_429_handling_is_safe(self):
        """Verify that a recorded 429 sets Pexels quota status to CRITICAL without raising errors."""
        pu = ProviderUsage(
            provider_name="pexels",
            units_used=1,
            endpoint="/v1/search",
            status_code=429,
            rate_limit=200,
            rate_remaining=0,
            is_observed=True
        )
        self.db.add(pu)
        self.db.commit()

        res = self.provider.get_all_service_quotas(self.db)
        pexels = next(s for s in res["services"] if s["service"] == "pexels_api")
        self.assertEqual(pexels["status"], "CRITICAL")
        self.assertEqual(pexels["remaining"], 0)

    def test_14_frontend_contains_limits_panel(self):
        """Verify mobile.html template includes API & Service Limits container."""
        from pathlib import Path
        template_path = Path("dashboard/templates/mobile.html")
        self.assertTrue(template_path.exists())
        content = template_path.read_text(encoding="utf-8")
        self.assertIn("API & Service Limits", content)
        self.assertIn('id="service-quotas-list"', content)

    def test_15_frontend_contains_no_secrets(self):
        """Security: Verify mobile.html contains no embedded API keys or tokens."""
        from pathlib import Path
        content = Path("dashboard/templates/mobile.html").read_text(encoding="utf-8")
        if PEXELS_API_KEY:
            self.assertNotIn(PEXELS_API_KEY, content)
        if GITHUB_PAT:
            self.assertNotIn(GITHUB_PAT, content)

    def test_16_service_worker_does_not_cache_api(self):
        """Verify sw.js explicitly bypasses caching for /api/*."""
        from pathlib import Path
        sw_content = Path("dashboard/static/sw.js").read_text(encoding="utf-8")
        self.assertIn("url.pathname.startsWith('/api')", sw_content)

    def test_17_quota_endpoint_performs_zero_production_mutation(self):
        """Verify GET /api/quotas does not invoke upload, drive move, or workflow dispatch."""
        with patch("engines.upload_engine.UploadEngine.schedule_short") as mock_sched, \
             patch("engines.drive_engine.DriveVaultEngine.move_file_in_vault") as mock_move, \
             patch("dashboard.github_client.GitHubWorkflowDispatcher.dispatch_workflow") as mock_disp:
            _ = self.client.get("/api/quotas", cookies=self.auth_cookies)
            mock_sched.assert_not_called()
            mock_move.assert_not_called()
            mock_disp.assert_not_called()

    def test_18_existing_pexels_fallback_intact(self):
        """Verify Pexels provider metadata declares fallback availability."""
        res = self.provider.get_all_service_quotas(self.db)
        pexels = next(s for s in res["services"] if s["service"] == "pexels_api")
        self.assertTrue(pexels["fallback_available"])
        self.assertIn("Pollinations.ai", pexels["fallback_description"])

    def test_19_existing_auth_remains_enforced(self):
        """Verify invalid session cookie is rejected on /api/quotas."""
        bad_cookies = {SESSION_COOKIE_NAME: "invalid_session_id_xyz"}
        resp = self.client.get("/api/quotas", cookies=bad_cookies)
        self.assertEqual(resp.status_code, 401)

    def test_20_existing_csrf_protections_intact(self):
        """Verify POST control endpoints still require CSRF tokens."""
        resp = self.client.post("/api/actions/publish-next", cookies=self.auth_cookies, json={})
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()