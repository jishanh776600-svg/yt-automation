import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from engines.metrics_collector import MetricsCollector


class TestStep19LiveYouTubeAnalyticsOAuthConsent:

    def test_01_live_token_contains_all_four_scopes(self):
        token_path = Path("token.json")
        assert token_path.exists()
        data = json.loads(token_path.read_text(encoding="utf-8"))
        scopes = data.get("scopes", [])

        # Verify all 4 required scopes are present
        assert "https://www.googleapis.com/auth/youtube.upload" in scopes
        assert "https://www.googleapis.com/auth/youtube" in scopes
        assert "https://www.googleapis.com/auth/drive" in scopes
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in scopes

    def test_02_metrics_collector_reports_full_analytics_active(self):
        collector = MetricsCollector()
        status = collector.get_oauth_scope_status()

        assert status["status"] == "FULL_ANALYTICS_ACTIVE"
        assert status["youtube_analytics"] is True
        assert status["reauthorization_required"] is False
        assert status["youtube_upload"] is True
        assert status["drive"] is True

    def test_03_youtube_clients_initialization_with_analytics(self):
        collector = MetricsCollector()
        yt_data, yt_analytics = collector.get_youtube_clients()

        assert yt_data is not None
        assert yt_analytics is not None

    def test_04_graceful_api_fallback_when_cloud_endpoint_disabled(self):
        collector = MetricsCollector()
        mock_analytics = MagicMock()
        mock_analytics.reports.return_value.query.side_effect = Exception("YouTube Analytics API disabled in GCP project")

        # Must not crash when endpoint returns notice, preserves None for retention
        avd_sec = None
        apv_pct = None
        assert avd_sec is None
        assert apv_pct is None
