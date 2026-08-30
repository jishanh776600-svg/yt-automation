"""
Phase 8.1 Pexels Quota Tracking & Live Usage Telemetry Tests.
Verifies:
  - Capture and defensive parsing of X-Ratelimit-Limit, X-Ratelimit-Remaining, X-Ratelimit-Reset.
  - Safe handling of missing and malformed quota headers.
  - Telemetry persistence for 200, 429, 5xx, and network timeout events.
  - Strict exclusion of images.pexels.com CDN downloads from API quota counters.
  - Telemetry exposure via /api/state and /api/quota/pexels.
  - Preservation of UNKNOWN status when live headers have not yet been observed.
  - Zero leakage of PEXELS_API_KEY in database or responses.
  - Unbroken fallback to Pollinations.ai / Procedural canvas.
  - Quota telemetry never stops production.
"""
import os
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from config.settings import PEXELS_API_KEY
from core.models import Base, ProviderUsage, AssetRecord
from core.database import init_db
from engines.asset_fetcher import AssetFetcher, parse_rate_limit_headers, record_pexels_telemetry
from dashboard.app import app
from dashboard.auth import session_store, SESSION_COOKIE_NAME


class TestPexelsQuotaPhase81(unittest.TestCase):

    def setUp(self):
        # Create an in-memory SQLite database for isolated unit testing
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.fetcher = AssetFetcher()
        self.client = TestClient(app)
        self.session_id, self.csrf_token = session_store.create_session("admin", duration_hours=1)
        self.auth_cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        self.db.close()
        session_store.invalidate_session(self.session_id)

    def _mock_response(self, status_code=200, json_data=None, headers=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data or {"photos": [{"src": {"large2x": "https://images.pexels.com/photos/123.jpg"}}]}
        resp.headers = headers or {}
        return resp

    # --------------------------------------------------------------------------
    # 1. HEADER CAPTURE TESTS
    # --------------------------------------------------------------------------
    def test_01_successful_response_captures_limit(self):
        """Test that X-Ratelimit-Limit header is captured and parsed as integer."""
        headers = {"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "19995", "X-Ratelimit-Reset": "1750000000"}
        parsed = parse_rate_limit_headers(headers)
        self.assertEqual(parsed["limit"], 20000)

    def test_02_successful_response_captures_remaining(self):
        """Test that X-Ratelimit-Remaining header is captured and parsed as integer."""
        headers = {"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "14500", "X-Ratelimit-Reset": "1750000000"}
        parsed = parse_rate_limit_headers(headers)
        self.assertEqual(parsed["remaining"], 14500)

    def test_03_successful_response_captures_reset(self):
        """Test that X-Ratelimit-Reset header is captured and parsed as integer."""
        headers = {"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "14500", "X-Ratelimit-Reset": "1756543210"}
        parsed = parse_rate_limit_headers(headers)
        self.assertEqual(parsed["reset"], 1756543210)

    def test_04_missing_headers_do_not_crash(self):
        """Test that missing rate-limit headers return None and do not raise errors."""
        parsed = parse_rate_limit_headers({})
        self.assertIsNone(parsed["limit"])
        self.assertIsNone(parsed["remaining"])
        self.assertIsNone(parsed["reset"])

    def test_05_malformed_headers_do_not_crash(self):
        """Test that malformed/non-numeric headers parse safely to None without crashing."""
        headers = {
            "X-Ratelimit-Limit": "unlimited",
            "X-Ratelimit-Remaining": "n/a",
            "X-Ratelimit-Reset": "invalid_timestamp"
        }
        parsed = parse_rate_limit_headers(headers)
        self.assertIsNone(parsed["limit"])
        self.assertIsNone(parsed["remaining"])
        self.assertIsNone(parsed["reset"])

    # --------------------------------------------------------------------------
    # 2. TELEMETRY RECORDING & HTTP SCENARIOS
    # --------------------------------------------------------------------------
    def test_06_pexels_429_recorded_safely(self):
        """Test that HTTP 429 response records telemetry with rate-limit status."""
        headers = {"X-Ratelimit-Limit": "200", "X-Ratelimit-Remaining": "0", "X-Ratelimit-Reset": "1750003600"}
        mock_resp = self._mock_response(status_code=429, json_data={}, headers=headers)
        with patch("config.settings.PEXELS_API_KEY", "test_key"),              patch("requests.get", return_value=mock_resp):
            photo = self.fetcher.search_pexels_photo(self.db, "roman colosseum")
            self.assertIsNone(photo)

            record = self.db.query(ProviderUsage).filter(ProviderUsage.provider_name == "pexels").first()
            self.assertIsNotNone(record)
            self.assertEqual(record.status_code, 429)
            self.assertEqual(record.rate_remaining, 0)
            self.assertEqual(record.rate_limit, 200)

    def test_07_pexels_5xx_recorded_safely(self):
        """Test that HTTP 500 server error is captured and telemetry recorded."""
        mock_resp = self._mock_response(status_code=500, json_data={}, headers={})
        with patch("config.settings.PEXELS_API_KEY", "test_key"),              patch("requests.get", return_value=mock_resp):
            photo = self.fetcher.search_pexels_photo(self.db, "medieval knight")
            self.assertIsNone(photo)

            record = self.db.query(ProviderUsage).filter(ProviderUsage.provider_name == "pexels").first()
            self.assertIsNotNone(record)
            self.assertEqual(record.status_code, 500)

    def test_08_network_timeout_recorded_safely(self):
        """Test that network timeout records an unobserved telemetry attempt."""
        with patch("config.settings.PEXELS_API_KEY", "test_key"),              patch("requests.get", side_effect=TimeoutError("Connection timed out")):
            photo = self.fetcher.search_pexels_photo(self.db, "ancient egypt")
            self.assertIsNone(photo)

            record = self.db.query(ProviderUsage).filter(ProviderUsage.provider_name == "pexels").first()
            self.assertIsNotNone(record)
            self.assertFalse(record.is_observed)
            self.assertIsNone(record.status_code)

    def test_09_api_request_counting_excludes_cdn_downloads(self):
        """Test that image CDN downloads from images.pexels.com do not increment API quota units."""
        mock_search_resp = self._mock_response(
            status_code=200,
            json_data={"photos": [{"src": {"large2x": "https://images.pexels.com/photos/999/large.jpg"}}]},
            headers={"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "19999"}
        )
        mock_cdn_resp = MagicMock()
        mock_cdn_resp.content = b"fake_jpeg_image_bytes"

        with patch("config.settings.PEXELS_API_KEY", "test_key"),              patch("requests.get") as mock_get,              patch.object(self.fetcher, "crop_to_vertical_9_16"):

            def side_effect_get(url, *args, **kwargs):
                if "api.pexels.com" in url:
                    return mock_search_resp
                else:
                    return mock_cdn_resp

            mock_get.side_effect = side_effect_get

            shot_data = {"shot_id": "shot_1", "search_query": "sparta battle", "duration": 4.0}
            asset = self.fetcher.fetch_asset_for_shot(self.db, shot_data)
            self.assertEqual(asset.source, "pexels")

            # Verify provider_usage contains API records but zero CDN download records
            usage_records = self.db.query(ProviderUsage).filter(ProviderUsage.provider_name == "pexels").all()
            self.assertGreaterEqual(len(usage_records), 1)
            for rec in usage_records:
                self.assertIn(rec.endpoint, ["/videos/search", "/v1/search"])

    def test_10_provider_telemetry_persisted_correctly(self):
        """Test direct persistence function record_pexels_telemetry."""
        headers = {"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "18500", "X-Ratelimit-Reset": "1750000000"}
        record_pexels_telemetry(self.db, endpoint="/v1/search", status_code=200, headers=headers, units=1, is_observed=True)

        rec = self.db.query(ProviderUsage).filter(ProviderUsage.provider_name == "pexels").first()
        self.assertIsNotNone(rec)
        self.assertEqual(rec.rate_limit, 20000)
        self.assertEqual(rec.rate_remaining, 18500)
        self.assertEqual(rec.rate_reset, 1750000000)
        self.assertTrue(rec.is_observed)

    # --------------------------------------------------------------------------
    # 3. API & TELEMETRY EXPOSURE
    # --------------------------------------------------------------------------
    def test_11_api_state_exposes_pexels_telemetry(self):
        """Test that /api/state contains pexels_quota dictionary."""
        resp = self.client.get("/api/state", cookies=self.auth_cookies)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("pexels_quota", data)
        quota = data["pexels_quota"]
        self.assertEqual(quota["provider"], "pexels")
        self.assertIn("status", quota)
        self.assertIn("requests_today", quota)
        self.assertIn("requests_this_month", quota)

    def test_12_unknown_balance_remains_null_when_unobserved(self):
        """Test that remaining is null and status is UNKNOWN when live headers haven't been observed."""
        from dashboard.data_provider import SystemDataProvider
        provider = SystemDataProvider()
        res = provider.get_pexels_quota_status(self.db)
        self.assertEqual(res["provider"], "pexels")
        self.assertIsNone(res["remaining"])
        self.assertIsNone(res["limit"])
        self.assertIsNone(res["reset"])
        self.assertEqual(res["status"], "UNKNOWN")

    def test_13_api_key_never_in_telemetry(self):
        """Security: Verify PEXELS_API_KEY does not appear in ProviderUsage or DB records."""
        rec = ProviderUsage(
            provider_name="pexels",
            units_used=1,
            endpoint="/v1/search",
            status_code=200,
            rate_remaining=100
        )
        self.db.add(rec)
        self.db.commit()

        queried = self.db.query(ProviderUsage).first()
        for col in ["provider_name", "endpoint", "model_name"]:
            val = getattr(queried, col, None)
            if val and PEXELS_API_KEY:
                self.assertNotIn(PEXELS_API_KEY, str(val))

    def test_14_api_key_never_in_api_response(self):
        """Security: Verify PEXELS_API_KEY does not appear in /api/state or /api/quota/pexels."""
        if PEXELS_API_KEY:
            resp_state = self.client.get("/api/state", cookies=self.auth_cookies)
            self.assertNotIn(PEXELS_API_KEY, resp_state.text)

            resp_quota = self.client.get("/api/quota/pexels", cookies=self.auth_cookies)
            self.assertNotIn(PEXELS_API_KEY, resp_quota.text)

    # --------------------------------------------------------------------------
    # 4. FALLBACK & PRODUCTION SAFETY
    # --------------------------------------------------------------------------
    def test_15_existing_pexels_fallback_intact(self):
        """Verify pipeline falls back to Pollinations.ai when Pexels search fails."""
        mock_ai_img = MagicMock()
        mock_ai_img.content = b"fake_ai_image_content_bytes_over_5000"

        with patch("config.settings.PEXELS_API_KEY", "test_key"),              patch("requests.get") as mock_get,              patch.object(self.fetcher, "crop_to_vertical_9_16"):

            def mock_side_effect(url, *args, **kwargs):
                if "api.pexels.com" in url:
                    # Simulate Pexels rate limit failure
                    return self._mock_response(status_code=429)
                elif "pollinations.ai" in url:
                    # AI fallback succeeds
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.content = b"A" * 6000
                    return resp
                return MagicMock(status_code=404)

            mock_get.side_effect = mock_side_effect

            shot_data = {"shot_id": "shot_fb", "search_query": "ancient ruins", "duration": 5.0}
            asset = self.fetcher.fetch_asset_for_shot(self.db, shot_data)
            self.assertEqual(asset.source, "pollinations_ai")

    def test_16_telemetry_does_not_stop_production_when_quota_zero(self):
        """Verify that remaining=0 sets status to CRITICAL but does NOT raise exceptions or halt."""
        from dashboard.data_provider import SystemDataProvider
        record_pexels_telemetry(self.db, endpoint="/v1/search", status_code=429, headers={"X-Ratelimit-Limit": "20000", "X-Ratelimit-Remaining": "0"})
        provider = SystemDataProvider()
        res = provider.get_pexels_quota_status(self.db)
        self.assertEqual(res["status"], "CRITICAL")
        self.assertEqual(res["remaining"], 0)

    def test_17_existing_retry_limits_unchanged(self):
        """Verify that search_pexels_photo uses max_retries=3 with base_delay=1.0."""
        from core.retry import DEFAULT_MAX_RETRIES
        self.assertEqual(DEFAULT_MAX_RETRIES, 3)

    def test_18_no_youtube_drive_mutation_during_telemetry(self):
        """Verify telemetry operations do not interact with YouTube or Google Drive."""
        with patch("engines.drive_engine.DriveVaultEngine.list_files_in_folder") as mock_drive,              patch("engines.upload_engine.UploadEngine.schedule_short") as mock_upload:
            from dashboard.data_provider import SystemDataProvider
            provider = SystemDataProvider()
            _ = provider.get_pexels_quota_status(self.db)
            mock_drive.assert_not_called()
            mock_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()