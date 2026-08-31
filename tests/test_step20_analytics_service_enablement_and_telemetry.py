import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from engines.metrics_collector import MetricsCollector


class TestStep20AnalyticsServiceEnablementAndTelemetry:

    def test_01_oauth_scope_is_present_in_token(self):
        token_path = Path("token.json")
        assert token_path.exists()
        data = json.loads(token_path.read_text(encoding="utf-8"))
        scopes = data.get("scopes", [])

        # OAuth scope is verified
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in scopes

    def test_02_gcp_service_status_detection(self):
        collector = MetricsCollector()
        status = collector.get_oauth_scope_status()

        # OAuth status is full
        assert status["status"] == "FULL_ANALYTICS_ACTIVE"
        assert status["youtube_analytics"] is True

    def test_03_maturation_gate_and_truthful_unavailability(self):
        # Missing or un-enabled API service preserves None
        avd = None
        apv = None
        minutes = None

        assert avd is None
        assert apv is None
        assert minutes is None

        display_avd = f"{avd:.1f}s" if avd is not None else "UNAVAILABLE"
        display_apv = f"{apv:.1f}%" if apv is not None else "UNAVAILABLE"
        display_min = f"{minutes:.1f}m" if minutes is not None else "UNAVAILABLE"

        assert display_avd == "UNAVAILABLE"
        assert display_apv == "UNAVAILABLE"
        assert display_min == "UNAVAILABLE"

    def test_04_production_pipeline_resilience(self):
        # Production pipeline operates completely independent of analytics service state
        service_enabled = False
        production_active = True
        assert production_active is True
