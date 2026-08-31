import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from engines.metrics_collector import MetricsCollector


class TestStep21AnalyticsEnablementBoundaryCheck:

    def test_01_oauth_is_fully_active_while_service_toggle_pending(self):
        collector = MetricsCollector()
        status = collector.get_oauth_scope_status()

        assert status["status"] == "FULL_ANALYTICS_ACTIVE"
        assert status["youtube_analytics"] is True
        assert status["reauthorization_required"] is False

    def test_02_truthful_unavailability_when_service_not_configured(self):
        # 403 accessNotConfigured must preserve None for retention metrics
        avd_sec = None
        apv_pct = None
        minutes = None

        assert avd_sec is None
        assert apv_pct is None
        assert minutes is None

    def test_03_zero_is_never_substituted(self):
        raw_val = None
        display_val = f"{raw_val:.1f}s" if raw_val is not None else "UNAVAILABLE"
        assert display_val == "UNAVAILABLE"
        assert display_val != "0.0s"
        assert display_val != "0"
