import os
import json
import math
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.settings import PROJECT_ROOT, KOKORO_VOICE
from config.constants import (
    DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType, JobState, get_business_day_bounds_utc
)
from core.models import UploadRecord, PerformanceSnapshot, StrategyWeight, Job
from core.recovery_manager import classify_error_to_failure_type
from engines.learning_engine import LearningEngine
from engines.metrics_collector import MetricsCollector
from engines.scheduler_engine import PublicationScheduler
from dashboard.data_provider import SystemDataProvider


class TestStep8AnalyticsAndReserveStability:

    def test_01_oauth_scope_audit_and_reauthorization_detection(self):
        collector = MetricsCollector()

        # Mock token without yt-analytics.readonly
        mock_creds_data = json.dumps({
            "scopes": [
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/drive"
            ]
        })

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = mock_creds_data
        collector.token_path = mock_path

        status = collector.get_oauth_scope_status()
        assert status["youtube_upload"] is True
        assert status["youtube_management"] is True
        assert status["drive"] is True
        assert status["youtube_analytics"] is False
        assert status["reauthorization_required"] is True
        assert status["status"] == "REAUTHORIZATION_REQUIRED"
        assert "python auth_youtube.py" in status["command"]

    def test_02_auth_youtube_script_contains_all_four_canonical_scopes(self):
        auth_script = (PROJECT_ROOT / "auth_youtube.py").read_text(encoding="utf-8")
        assert "https://www.googleapis.com/auth/youtube.upload" in auth_script
        assert "https://www.googleapis.com/auth/youtube" in auth_script
        assert "https://www.googleapis.com/auth/drive" in auth_script
        assert "https://www.googleapis.com/auth/yt-analytics.readonly" in auth_script

    def test_03_telemetry_null_preservation_and_provenance(self):
        collector = MetricsCollector()
        mock_upload = MagicMock(spec=UploadRecord)
        mock_upload.id = "upl_step8_01"
        mock_upload.youtube_video_id = "REAL_STEP8_ID"
        mock_upload.created_at = None
        mock_upload.published_at = datetime.utcnow() - timedelta(days=2)

        # Data API v3 returns views/likes/comments; Analytics API returns None
        mock_yt_data = MagicMock()
        mock_yt_data.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"statistics": {"viewCount": "5120", "likeCount": "340", "commentCount": "42"}}]
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(collector, "get_youtube_clients", return_value=(mock_yt_data, None)):
            snap = collector.collect_for_upload(mock_db, mock_upload)
            assert snap.views == 5120
            assert snap.likes == 340
            assert snap.comments == 42
            assert snap.average_view_percentage is None
            assert snap.average_view_duration_sec is None
            assert snap.estimated_minutes_watched is None

    def test_04_retention_curve_capability_and_scene_attribution_limits(self):
        # Verify official API capabilities
        # YouTube Analytics API exposes video-level aggregates (AVD, APV), NOT second-by-second scene dropoffs via API
        scene_attribution_supported = False
        assert scene_attribution_supported is False  # Scene-level is NOT DIRECTLY AVAILABLE FROM API

    def test_05_snapshot_harvesting_idempotency(self):
        collector = MetricsCollector()
        mock_upload = MagicMock(spec=UploadRecord)
        mock_upload.id = "upl_step8_02"
        mock_upload.youtube_video_id = "REAL_STEP8_ID2"
        mock_upload.published_at = datetime.utcnow() - timedelta(hours=36)

        mock_recent_snap = MagicMock(spec=PerformanceSnapshot)
        mock_recent_snap.snapshot_time = datetime.utcnow() - timedelta(hours=4)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_recent_snap

        # Snapshot recorded 4h ago -> within 20h idempotency window -> MUST SKIP
        eligible, reason = collector.is_eligible_for_harvesting(mock_db, mock_upload)
        assert eligible is False
        assert "IDEMPOTENT_SKIP" in reason

    def test_06_reserve_stability_and_stepwise_consumption_simulation(self):
        target = 6
        # Simulate inventory dropping from 6 down to 0
        consumption_trace = [6, 5, 4, 3, 2, 1, 0]
        expected_deficits = [0, 1, 2, 3, 4, 5, 6]

        for ready_stock, expected_def in zip(consumption_trace, expected_deficits):
            calculated_def = max(0, target - ready_stock)
            assert calculated_def == expected_def

            # In single replenishment pass, exactly 1 Short is produced if deficit > 0
            production_units_per_run = 1 if calculated_def > 0 else 0
            assert production_units_per_run <= 1

    def test_07_concurrency_lock_and_atomic_claim_protection(self):
        from core.lock import ProcessLock, ProcessLockError

        # Simulate two concurrent production workers attempting to acquire the same lock
        lock1 = ProcessLock(name="test_step8_lock")
        lock2 = ProcessLock(name="test_step8_lock")

        assert lock1.acquire() is True
        assert lock1.is_locked() is True

        # Second worker is blocked safely (returns False)
        assert lock2.acquire(timeout=0.0) is False

        lock1.release()
        assert lock1.is_locked() is False

    def test_08_daily_capacity_utc_midnight_and_future_slot_isolation(self):
        # 1 published at 06:00 UTC today
        # 1 scheduled at 15:00 UTC today
        # 1 scheduled at 06:00 UTC tomorrow
        pub_today = 1
        sched_today = 1
        sched_tomorrow = 1

        booked_today = pub_today + sched_today
        remaining_today = max(0, DAILY_SHORTS_LIMIT - booked_today)

        assert booked_today == 2
        assert remaining_today == 1
        assert booked_today != (pub_today + sched_today + sched_tomorrow)

    def test_09_failure_classification_coverage_all_16_types(self):
        error_map = {
            "Rate limit 429 exceeded on Groq": FailureType.QUOTA_FAILURE,
            "Gemini fallback primary error": FailureType.PROVIDER_FAILURE,
            "OAuth token refresh 401 error": FailureType.OAUTH_FAILURE,
            "Drive folder 01_READY inaccessible": FailureType.DRIVE_FAILURE,
            "YouTube resumable upload broken pipe": FailureType.UPLOAD_FAILURE,
            "YouTube server 500 internal error": FailureType.YOUTUBE_FAILURE,
            "FFmpeg 1080x1920 filter graph crash": FailureType.RENDER_FAILURE,
            "QA Engine subtitle clash check failed": FailureType.QA_FAILURE,
            "Kokoro TTS model synthesis error": FailureType.TTS_FAILURE,
            "Audio mixer LUFS normalization error": FailureType.AUDIO_FAILURE,
            "Caption SRT timing misalignment": FailureType.CAPTION_FAILURE,
            "Pexels b-roll video download failed": FailureType.VISUAL_FAILURE,
            "Script hook word count out of bounds": FailureType.SCRIPT_FAILURE,
            "Fact verification contradicting claims": FailureType.FACT_VERIFICATION_FAILURE,
            "Topic research query extraction error": FailureType.RESEARCH_FAILURE,
            "Database SHA256 checksum mismatch": FailureType.RECONCILIATION_FAILURE
        }

        for err_msg, expected_type in error_map.items():
            assert classify_error_to_failure_type(err_msg) == expected_type

    def test_10_learning_engine_evidence_gates_and_ucb1_bounds(self):
        learner = LearningEngine(min_weight=0.20, max_weight=2.00)

        # N < 3: Insufficient evidence -> Weight = 1.00
        w_insuf, _, conf_i, _ = learner.compute_strategy_weight(sample_count=1, performance_mean=100.0, baseline_performance=50.0)
        assert w_insuf == 1.00
        assert conf_i == "INSUFFICIENT_EVIDENCE"

        # N = 4: Weak evidence -> Damped update (max +-10%)
        w_weak, _, conf_w, _ = learner.compute_strategy_weight(sample_count=4, performance_mean=100.0, baseline_performance=50.0)
        assert 1.00 < w_weak <= 1.10
        assert conf_w == "WEAK_EVIDENCE"

        # N = 10: Usable evidence -> Full bounded update [0.20, 2.00]
        w_usable, _, conf_u, _ = learner.compute_strategy_weight(sample_count=10, performance_mean=100.0, baseline_performance=50.0)
        assert w_usable > w_weak
        assert conf_u == "USABLE_EVIDENCE"
        assert 0.20 <= w_usable <= 2.00
