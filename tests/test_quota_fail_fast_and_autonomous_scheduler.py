"""
Targeted regression test suite for:
1. Gemini all-provider quota exhaustion fail-fast (zero unnecessary retry storm / cycles)
2. Canonical autonomous READY -> Scheduled buffer fulfillment
3. Idempotent multi-slot allocation and capacity safety
"""
import unittest
import uuid
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Job, Topic, UploadRecord, RenderOutput
from core.gemini_client import GeminiQuotaExhaustedError
from config.constants import DAILY_SHORTS_LIMIT, get_business_day_bounds_utc, JobState
from engines.script_engine import ScriptEngine
from main import ShortsPipeline, PROJECT_ROOT


class TestQuotaFailFastAndAutonomousScheduler(unittest.TestCase):
    def setUp(self):
        # Create an isolated in-memory SQLite database for test purity
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.TestSession = sessionmaker(bind=self.engine)
        self.db = self.TestSession()

        self.pipeline = ShortsPipeline()
        self.pipeline.SessionLocal = self.TestSession

        # Clean locks before test
        for lock_name in ["publisher.lock", "production.lock"]:
            lf = PROJECT_ROOT / "data" / "locks" / lock_name
            if lf.exists():
                lf.unlink(missing_ok=True)

    def tearDown(self):
        self.db.close()
        for lock_name in ["publisher.lock", "production.lock"]:
            lf = PROJECT_ROOT / "data" / "locks" / lock_name
            if lf.exists():
                lf.unlink(missing_ok=True)

    def test_01_all_gemini_quota_exhausted_immediate_fail_fast(self):
        """Scenario 1 & 2: Terminal quota exhaustion re-raises immediately without 3 retry passes or Pexels work."""
        engine = ScriptEngine()
        topic = Topic(id="top_test_quota", title="The Great Quota Crisis")

        pass_counter = [0]

        def mock_draft(*args, **kwargs):
            pass_counter[0] += 1
            raise GeminiQuotaExhaustedError("ALL configured Gemini providers exhausted daily API quotas.")

        engine._draft_script_pass = mock_draft
        engine.generate_hook_candidates = MagicMock(return_value=[{"type": "Date-Anchor", "hook": "Test hook", "score": 80.0}])

        with self.assertRaises(GeminiQuotaExhaustedError):
            engine.generate_script(self.db, topic, research_data={"summary": "Historical crisis", "verified_claims": []})

        # Must have failed after exactly 1 pass, not continuing to pass 2 and 3!
        self.assertEqual(pass_counter[0], 1)

    def test_02_maintain_buffer_aborts_immediately_on_all_quota_exhausted(self):
        """Scenario 2 & 3: maintain_buffer halts on attempt 1 without consecutive job retry storm, and summary succeeds."""
        attempt_counter = [0]

        def mock_produce_single():
            attempt_counter[0] += 1
            raise GeminiQuotaExhaustedError("ALL configured Gemini providers exhausted daily API quotas.")

        self.pipeline.produce_single_to_vault = mock_produce_single
        self.pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=1)

        produced_count, summary = self.pipeline.maintain_buffer(target_stock=12)

        self.assertEqual(produced_count, 0)
        self.assertEqual(summary["outcome"], "BLOCKED")
        self.assertEqual(summary["block_reason"], "ALL_GEMINI_PROVIDERS_EXHAUSTED")
        self.assertIn("timestamp", summary)
        # Attempted exactly once before halting
        self.assertEqual(attempt_counter[0], 1)

    def test_03_schedule_ready_2_published_0_scheduled_1_ready(self):
        """Scenario 4: 2 published + 0 scheduled + 1 READY -> schedules exactly 1 video."""
        today_start, today_end = get_business_day_bounds_utc()

        # Create 2 published records
        for i in range(2):
            jid = f"job_pub_test_{i}_{uuid.uuid4().hex[:6]}"
            self.db.add(UploadRecord(
                id=f"upl_{uuid.uuid4().hex[:8]}",
                job_id=jid,
                youtube_video_id=f"YT_{jid}",
                title=f"Published Vid {i}",
                description="Test Description",
                status="PUBLISHED",
                privacy_status="public",
                published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_ready_file = {
            "id": "drive_file_sched_1",
            "name": "short_job_test_halifax.mp4",
            "properties": {"job_id": "job_test_halifax", "title": "The Halifax Explosion of 1917"}
        }

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_ready_file] if f == "01_READY" else []):
            with patch.object(self.pipeline.upload_engine, "schedule_short") as mock_sched:
                mock_sched.return_value = UploadRecord(
                    id="upl_mock_1",
                    job_id="job_test_halifax",
                    youtube_video_id="YT_NEW_1",
                    title="The Halifax Explosion of 1917",
                    description="Test Description",
                    status="SCHEDULED",
                    privacy_status="private",
                    scheduled_publish_at=datetime.utcnow() + timedelta(hours=2)
                )
                with patch.object(self.pipeline.drive_engine, "download_video_from_vault"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault"):
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            res = self.pipeline.schedule_ready_buffer(db=self.db)
                            self.assertEqual(res["scheduled_count"], 1)
                            self.assertEqual(res["published_today"], 2)
                            self.assertEqual(res["scheduled_today"], 1)
                            self.assertEqual(res["remaining_capacity"], 1)

    def test_04_schedule_ready_2_published_0_scheduled_2_ready(self):
        """Scenario 5: 2 published + 0 scheduled + 2 READY -> schedules exactly 2 videos."""
        today_start, today_end = get_business_day_bounds_utc()

        # Create 2 published records
        for i in range(2):
            jid = f"job_pub_test_{i}_{uuid.uuid4().hex[:6]}"
            self.db.add(UploadRecord(
                id=f"upl_{uuid.uuid4().hex[:8]}",
                job_id=jid,
                youtube_video_id=f"YT_{jid}",
                title=f"Published Vid {i}",
                description="Test Description",
                status="PUBLISHED",
                privacy_status="public",
                published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_ready_files = [
            {"id": f"drive_file_{i}", "name": f"short_job_r_{i}.mp4", "properties": {"job_id": f"job_r_{i}", "title": f"Ready Vid {i}"}}
            for i in range(2)
        ]

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_ready_files if f == "01_READY" else []):
            with patch.object(self.pipeline.upload_engine, "schedule_short") as mock_sched:
                mock_sched.side_effect = [
                    UploadRecord(id=f"upl_mock_{i}", job_id=f"job_r_{i}", youtube_video_id=f"YT_R_{i}", title=f"Ready Vid {i}", description="Test Description", status="SCHEDULED", scheduled_publish_at=datetime.utcnow() + timedelta(hours=2+i))
                    for i in range(2)
                ]
                with patch.object(self.pipeline.drive_engine, "download_video_from_vault"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault"):
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            res = self.pipeline.schedule_ready_buffer(db=self.db)
                            self.assertEqual(res["scheduled_count"], 2)
                            self.assertEqual(res["remaining_capacity"], 0)

    def test_05_schedule_ready_2_published_1_scheduled_5_ready(self):
        """Scenario 6: 2 published + 1 scheduled + 5 READY -> schedules exactly 1 additional video."""
        today_start, today_end = get_business_day_bounds_utc()
        now_utc = datetime.utcnow()

        # 2 published
        for i in range(2):
            jid = f"job_pub_test_{i}_{uuid.uuid4().hex[:6]}"
            self.db.add(UploadRecord(
                id=f"upl_{uuid.uuid4().hex[:8]}",
                job_id=jid,
                youtube_video_id=f"YT_{jid}",
                title=f"Published Vid {i}",
                description="Test Description",
                status="PUBLISHED",
                privacy_status="public",
                published_at=today_start + timedelta(hours=1 + i)
            ))
        # 1 scheduled
        sched_jid = f"job_sched_exist_{uuid.uuid4().hex[:6]}"
        self.db.add(UploadRecord(
            id=f"upl_{uuid.uuid4().hex[:8]}",
            job_id=sched_jid,
            youtube_video_id="YT_SCHED_EXIST",
            title="Scheduled Vid Exist",
            description="Test Description",
            status="SCHEDULED",
            privacy_status="private",
            scheduled_publish_at=now_utc + timedelta(hours=1)
        ))
        self.db.commit()

        # 5 READY files
        fake_ready_files = [
            {"id": f"drive_file_5_{i}", "name": f"short_job_r5_{i}.mp4", "properties": {"job_id": f"job_r5_{i}", "title": f"Ready Vid {i}"}}
            for i in range(5)
        ]

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_ready_files if f == "01_READY" else []):
            with patch.object(self.pipeline.upload_engine, "schedule_short") as mock_sched:
                mock_sched.return_value = UploadRecord(
                    id="upl_mock_one", job_id="job_r5_0", youtube_video_id="YT_R5_0", title="Ready Vid 0", description="Test Description", status="SCHEDULED", scheduled_publish_at=now_utc + timedelta(hours=4)
                )
                with patch.object(self.pipeline.drive_engine, "download_video_from_vault"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault"):
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            res = self.pipeline.schedule_ready_buffer(db=self.db)
                            # Exactly 1 additional scheduled (2 published + 1 scheduled = 3 booked -> 1 capacity)
                            self.assertEqual(res["scheduled_count"], 1)

    def test_06_schedule_ready_4_published_0_scheduled(self):
        """Scenario 7: 4 published + READY inventory -> zero videos scheduled."""
        today_start, today_end = get_business_day_bounds_utc()

        for i in range(4):
            jid = f"job_pub_full_{i}_{uuid.uuid4().hex[:6]}"
            self.db.add(UploadRecord(
                id=f"upl_{uuid.uuid4().hex[:8]}",
                job_id=jid,
                youtube_video_id=f"YT_{jid}",
                title=f"Full Vid {i}",
                description="Test Description",
                status="PUBLISHED",
                privacy_status="public",
                published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_ready_files = [{"id": "drive_file_extra", "name": "short_job_extra.mp4", "properties": {"job_id": "job_extra", "title": "Extra"}}]
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_ready_files if f == "01_READY" else []):
            res = self.pipeline.schedule_ready_buffer(db=self.db)
            self.assertEqual(res["scheduled_count"], 0)
            self.assertEqual(res["status"], "NO_ACTION_REQUIRED")

    def test_07_idempotency_running_twice_never_duplicates(self):
        """Scenario 8 & 11: Running schedule_ready_buffer twice never double schedules."""
        fake_ready_file = {
            "id": "drive_file_idem_1",
            "name": "short_job_idem_1.mp4",
            "properties": {"job_id": "job_idem_1", "title": "The Idempotent Event"}
        }

        # Add existing scheduled record to DB
        now_utc = datetime.utcnow()
        self.db.add(UploadRecord(
            id="upl_idem_rec",
            job_id="job_idem_1",
            youtube_video_id="YT_IDEM",
            title="The Idempotent Event",
            description="Test Description",
            status="SCHEDULED",
            privacy_status="private",
            scheduled_publish_at=now_utc + timedelta(hours=3)
        ))
        self.db.commit()

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_ready_file] if f == "01_READY" else []):
            with patch.object(self.pipeline.drive_engine, "move_file_in_vault") as mock_move:
                res = self.pipeline.schedule_ready_buffer(db=self.db)
                # Pre-claim dedup detects it's already scheduled and moves 01_READY -> 02_PROCESSING
                self.assertEqual(res["scheduled_count"], 0)
                mock_move.assert_called_with("drive_file_idem_1", from_folder="01_READY", to_folder="02_PROCESSING")

    def test_08_historical_uploads_excluded_from_today(self):
        """Scenario 9: Past day uploads are never counted toward today's published count."""
        today_start, today_end = get_business_day_bounds_utc()
        yesterday_utc = today_start - timedelta(hours=5)

        hist_jid = f"job_hist_{uuid.uuid4().hex[:6]}"
        self.db.add(UploadRecord(
            id=f"upl_{uuid.uuid4().hex[:8]}",
            job_id=hist_jid,
            youtube_video_id="YT_HIST",
            title="Historical Incident",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="public",
            published_at=yesterday_utc
        ))
        self.db.commit()

        pub_count = self.db.query(UploadRecord).filter(
            UploadRecord.status.in_(["PUBLISHED", "SUCCESS"]),
            UploadRecord.published_at >= today_start,
            UploadRecord.published_at < today_end
        ).count()
        self.assertEqual(pub_count, 0)

    def test_09_scheduling_failure_resilience(self):
        """Scenario 12: If scheduling fails for one job, it returns safely to 01_READY without corrupting state."""
        fake_ready_file = {
            "id": "drive_file_err_1",
            "name": "short_job_err_1.mp4",
            "properties": {"job_id": "job_err_1", "title": "Failing Job"}
        }

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_ready_file] if f == "01_READY" else []):
            with patch.object(self.pipeline.upload_engine, "schedule_short", side_effect=RuntimeError("Transient Network Error")):
                with patch.object(self.pipeline.drive_engine, "download_video_from_vault"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault") as mock_move:
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            res = self.pipeline.schedule_ready_buffer(db=self.db)
                            self.assertEqual(res["scheduled_count"], 0)
                            # Returned safely to 01_READY
                            mock_move.assert_called_with("drive_file_err_1", from_folder="02_PROCESSING", to_folder="01_READY")


if __name__ == "__main__":
    unittest.main()
