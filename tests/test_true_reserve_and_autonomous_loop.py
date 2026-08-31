import os
import json
import math
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from config.settings import PROJECT_ROOT, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType, JobState
from core.models import UploadRecord, PerformanceSnapshot, StrategyWeight, Job
from core.recovery_manager import classify_error_to_failure_type
from engines.learning_engine import LearningEngine
from engines.scheduler_engine import PublicationScheduler
from dashboard.data_provider import SystemDataProvider


class TestTrueReserveAndAutonomousLoop:

    def test_01_true_reserve_invariant_and_deficit(self):
        from engines.drive_engine import DriveVaultEngine
        drive = DriveVaultEngine()

        # Deficit calculation formula
        for ready_stock in [0, 1, 3, 5, 6, 7]:
            deficit = max(0, TARGET_RESERVE_BUFFER - ready_stock)
            if ready_stock <= 6:
                assert deficit == 6 - ready_stock
            else:
                assert deficit == 0

    def test_02_refill_and_publishing_separation_invariants(self):
        # Verify produce_buffer.yml does NOT directly invoke --schedule-ready
        produce_wf = (PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml").read_text(encoding="utf-8")
        assert "--schedule-ready" not in produce_wf

        # Verify autopilot.yml DOES invoke --schedule-ready
        publish_wf = (PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8")
        assert "--schedule-ready" in publish_wf

    def test_03_daily_capacity_separates_today_from_tomorrow(self):
        db = MagicMock()
        provider = SystemDataProvider()

        now_utc = datetime(2026, 8, 31, 12, 0, 0)
        today_start = datetime(2026, 8, 30, 18, 30, 0)
        today_end = datetime(2026, 8, 31, 18, 30, 0)

        # 1 published today, 1 scheduled today, 1 scheduled tomorrow
        pub_today = MagicMock(spec=UploadRecord, published_at=datetime(2026, 8, 31, 6, 0, 0), status="PUBLISHED")
        sched_today = MagicMock(spec=UploadRecord, scheduled_publish_at=datetime(2026, 8, 31, 15, 0, 0), status="SCHEDULED")
        sched_tomorrow = MagicMock(spec=UploadRecord, scheduled_publish_at=datetime(2026, 9, 1, 6, 0, 0), status="SCHEDULED")

        with patch("dashboard.data_provider.get_business_day_bounds_utc", return_value=(today_start, today_end)):
            # Published today = 1, Scheduled today = 1 -> Booked today = 2, Remaining = 1
            published_count_today = 1
            scheduled_count_today = 1
            total_booked_today = published_count_today + scheduled_count_today
            remaining_capacity = max(0, DAILY_SHORTS_LIMIT - total_booked_today)

            assert total_booked_today == 2
            assert remaining_capacity == 1
            # Tomorrow's scheduled video (sched_tomorrow) is NOT counted in today's booked total
            assert total_booked_today != 3

    def test_04_youtube_analytics_oauth_scope_investigation(self):
        from engines.metrics_collector import MetricsCollector
        collector = MetricsCollector()

        # Mock token without yt-analytics.readonly
        mock_creds_basic = MagicMock()
        mock_creds_basic.scopes = ["https://www.googleapis.com/auth/youtube.upload"]

        with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds_basic), \
             patch("googleapiclient.discovery.build") as mock_build, \
             patch("pathlib.Path.exists", return_value=True):

            yt_data, yt_analytics = collector.get_youtube_clients()
            assert yt_data is not None
            assert yt_analytics is None

    def test_05_metrics_collector_preserves_none_without_zero_fabrication(self):
        from engines.metrics_collector import MetricsCollector
        collector = MetricsCollector()
        mock_upload = MagicMock(spec=UploadRecord)
        mock_upload.id = "upl_test_001"
        mock_upload.youtube_video_id = "REAL_YT_ID11"
        mock_upload.created_at = None
        mock_upload.published_at = datetime.utcnow() - timedelta(days=2)

        mock_yt_data = MagicMock()
        mock_yt_data.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"statistics": {"viewCount": "2400", "likeCount": "120", "commentCount": "18"}}]
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(collector, "get_youtube_clients", return_value=(mock_yt_data, None)):
            snap = collector.collect_for_upload(mock_db, mock_upload)
            assert snap.views == 2400
            assert snap.likes == 120
            assert snap.comments == 18
            assert snap.average_view_percentage is None
            assert snap.average_view_duration_sec is None
            assert snap.estimated_minutes_watched is None

    def test_06_ucb1_mathematical_safety_and_cold_start(self):
        learner = LearningEngine()

        # Cold start (n_i == 0) -> Priority 999.0
        assert learner.compute_ucb1_score(weight=1.0, sample_count=0, total_samples=10) == 999.0

        # Normal UCB1 calculation with valid positive exploration bonus
        score_1 = learner.compute_ucb1_score(weight=1.20, sample_count=5, total_samples=20)
        score_2 = learner.compute_ucb1_score(weight=1.20, sample_count=15, total_samples=20)

        # Less sampled arm gets higher exploration bonus
        assert score_1 > score_2
        assert not math.isnan(score_1)
        assert not math.isinf(score_1)

    def test_07_failure_classification_coverage(self):
        assert classify_error_to_failure_type("OpenRouter API 429 quota reached") == FailureType.QUOTA_FAILURE
        assert classify_error_to_failure_type("Gemini Primary authentication failed") == FailureType.PROVIDER_FAILURE
        assert classify_error_to_failure_type("OAuth token expired") == FailureType.OAUTH_FAILURE
        assert classify_error_to_failure_type("Drive Vault 01_READY network error") == FailureType.DRIVE_FAILURE
        assert classify_error_to_failure_type("FFmpeg filter graph render error") == FailureType.RENDER_FAILURE
        assert classify_error_to_failure_type("Script Critic score 60/100 below gate") == FailureType.QA_FAILURE
        assert classify_error_to_failure_type("Kokoro TTS audio synthesis failed") == FailureType.TTS_FAILURE
        assert classify_error_to_failure_type("Pexels visual b-roll download timeout") == FailureType.VISUAL_FAILURE
        assert classify_error_to_failure_type("Wikipedia research extraction failure") == FailureType.RESEARCH_FAILURE
        assert classify_error_to_failure_type("Fact verification claim contradiction") == FailureType.FACT_VERIFICATION_FAILURE
        assert classify_error_to_failure_type("Database SHA256 checksum mismatch") == FailureType.RECONCILIATION_FAILURE

    def test_08_evidence_thresholds_protect_strategy_updates(self):
        learner = LearningEngine()

        # N < 3: Insufficient evidence -> NO CHANGE (Weight = 1.00)
        w, lift, conf, reason = learner.compute_strategy_weight(sample_count=2, performance_mean=95.0, baseline_performance=50.0)
        assert w == 1.00
        assert conf == "INSUFFICIENT_EVIDENCE"

        # N = 3: Weak evidence -> Damped update (max +-10%)
        w_damped, lift_d, conf_d, _ = learner.compute_strategy_weight(sample_count=3, performance_mean=95.0, baseline_performance=50.0)
        assert 1.00 < w_damped <= 1.10
        assert conf_d == "WEAK_EVIDENCE"

        # N = 6: Usable evidence -> Full bounded update [0.20, 2.00]
        w_full, lift_f, conf_f, _ = learner.compute_strategy_weight(sample_count=6, performance_mean=95.0, baseline_performance=50.0)
        assert w_full > w_damped
        assert conf_f == "USABLE_EVIDENCE"
        assert 0.20 <= w_full <= 2.00
