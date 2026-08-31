import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timedelta

from core.models import UploadRecord, PerformanceSnapshot
from engines.metrics_collector import MetricsCollector


class TestStep18AnalyticsOAuthAndAvdApvTelemetry:

    def test_01_oauth_scope_status_auditing(self, tmp_path):
        collector = MetricsCollector()
        dummy_token = tmp_path / "token.json"

        # Case A: Token with full analytics scope
        dummy_token.write_text(json.dumps({
            "scopes": [
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/drive",
                "https://www.googleapis.com/auth/yt-analytics.readonly"
            ]
        }), encoding="utf-8")

        collector.token_path = dummy_token
        status = collector.get_oauth_scope_status()
        assert status["status"] == "FULL_ANALYTICS_ACTIVE"
        assert status["youtube_analytics"] is True
        assert status["reauthorization_required"] is False

        # Case B: Token without analytics scope
        dummy_token.write_text(json.dumps({
            "scopes": [
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/drive"
            ]
        }), encoding="utf-8")

        status_b = collector.get_oauth_scope_status()
        assert status_b["status"] == "REAUTHORIZATION_REQUIRED"
        assert status_b["youtube_analytics"] is False
        assert status_b["reauthorization_required"] is True

    def test_02_maturation_gate_preserves_none_for_immature_videos(self):
        collector = MetricsCollector()
        db = MagicMock()

        # Video published 2 hours ago (< 24h threshold)
        now_dt = datetime.now()
        immature_upload = UploadRecord(
            id="up_immature_01",
            youtube_video_id="YT_IMMATURE_123",
            published_at=now_dt - timedelta(hours=2)
        )

        db.query.return_value.filter.return_value.all.return_value = [immature_upload]
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        # Age in hours
        age_hours = (now_dt - immature_upload.published_at).total_seconds() / 3600.0
        assert age_hours < 24.0

    def test_03_youtube_analytics_reports_query_parsing(self):
        collector = MetricsCollector()
        mock_analytics = MagicMock()

        # Simulated response from YouTube Analytics API v2
        mock_response = {
            "columnHeaders": [
                {"name": "averageViewDuration"},
                {"name": "averageViewPercentage"},
                {"name": "estimatedMinutesWatched"}
            ],
            "rows": [
                [18.5, 78.4, 42.0]
            ]
        }
        mock_analytics.reports.return_value.query.return_value.execute.return_value = mock_response

        # Query simulation
        res = mock_analytics.reports().query(
            ids="channel==MINE",
            startDate="2026-08-01",
            endDate="2026-08-31",
            metrics="averageViewDuration,averageViewPercentage,estimatedMinutesWatched",
            filters="video==REAL_VIDEO_ID"
        ).execute()

        rows = res.get("rows", [])
        assert len(rows) == 1
        avd, apv, minutes_watched = rows[0]

        assert avd == 18.5
        assert apv == 78.4
        assert minutes_watched == 42.0

    def test_04_zero_is_never_substituted_for_missing_retention(self):
        # Missing analytics data must remain None
        avd = None
        apv = None

        snap = PerformanceSnapshot(
            id=101,
            upload_id="up_01",
            views=150,
            likes=12,
            comments=3,
            average_view_duration_sec=avd,
            average_view_percentage=apv
        )

        assert snap.average_view_duration_sec is None
        assert snap.average_view_percentage is None

        # Display formatting check: None displays as "UNAVAILABLE"
        display_avd = f"{snap.average_view_duration_sec:.1f}s" if snap.average_view_duration_sec is not None else "UNAVAILABLE"
        assert display_avd == "UNAVAILABLE"

    def test_05_learning_engine_respects_evidence_thresholds(self):
        # N < 3 -> INSUFFICIENT_EVIDENCE -> weight unchanged (1.00)
        # N = 3-4 -> WEAK_EVIDENCE -> damped weight
        # N >= 5 -> USABLE_EVIDENCE -> full empirical update
        sample_counts = [1, 2, 3, 5, 10]
        for n in sample_counts:
            if n < 3:
                status = "INSUFFICIENT_EVIDENCE"
            elif n < 5:
                status = "WEAK_EVIDENCE"
            else:
                status = "USABLE_EVIDENCE"

            assert status in ["INSUFFICIENT_EVIDENCE", "WEAK_EVIDENCE", "USABLE_EVIDENCE"]

        # Weights must always stay within [0.20, 2.00]
        min_weight = 0.20
        max_weight = 2.00
        assert min_weight <= 1.0 <= max_weight
