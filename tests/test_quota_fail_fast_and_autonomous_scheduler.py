"""
Comprehensive Regression Test Suite Covering Scenarios A through S:
A. 4/day capacity ceiling enforcement
B. 2 published + 0 scheduled + 2 READY -> schedule 2
C. 2 published + 1 scheduled + 5 READY -> schedule only 1
D. 4 published -> schedule 0
E. READY video gets automatically scheduled
F. Multiple READY videos schedule into consecutive valid slots
G. Expired slot is skipped; next valid future slot is allocated
H. Duplicate scheduler execution does not duplicate YouTube upload (idempotency)
I. Concurrent scheduler claims are safe (process locks & transactional safety)
J. Gemini primary exhausted -> secondary provider used
K. Both Gemini providers exhausted -> immediate termination (ALL_GEMINI_PROVIDERS_EXHAUSTED)
L. No extra Gemini calls when production requirement = 0 (maintain_buffer / produce_batch)
M. Production requirement = 1 -> exactly one production job
N. Gemini request waits for actual response before proceeding (blocking synchronous execution)
O. Transient Gemini error retries with bounded exponential backoff
P. Quota exhaustion does NOT retry repeatedly
Q. Dashboard SCRIPT count and table counts reflect true intended database meaning
R. Dashboard Published / Scheduled / Remaining counts remain accurate
S. Drive / DB / YouTube reconciliation remains consistent
"""
import unittest
import uuid
import os
import time
import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta, date, time as dtime
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Base, Job, Topic, UploadRecord, RenderOutput, AssetRecord, ScriptRecord
)
from core.gemini_client import (
    GeminiClient, GeminiQuotaExhaustedError, GeminiRateLimiter
)
from config.constants import DAILY_SHORTS_LIMIT, get_business_day_bounds_utc, JobState
from engines.script_engine import ScriptEngine
from engines.scheduler_engine import PublicationScheduler
from core.database_sync import get_database_stats
from dashboard.data_provider import SystemDataProvider
from main import ShortsPipeline, PROJECT_ROOT


class TestComprehensiveAutonomousPipeline(unittest.TestCase):
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

    def test_scenario_a_daily_capacity_ceiling(self):
        """Scenario A: 4/day capacity ceiling enforcement."""
        today_start, today_end = get_business_day_bounds_utc()
        for i in range(4):
            self.db.add(UploadRecord(
                id=f"upl_cap_{i}",
                job_id=f"job_cap_{i}",
                youtube_video_id=f"YT_CAP_{i}",
                title=f"Cap Video {i}",
                description="Test",
                status="PUBLISHED",
                privacy_status="public",
                published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_files = [{"id": f"f_{i}", "name": f"vid_{i}.mp4", "properties": {"job_id": f"j_{i}", "title": f"T {i}"}} for i in range(3)]
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_files if f == "01_READY" else []):
            res = self.pipeline.schedule_ready_buffer(db=self.db)
            self.assertEqual(res["scheduled_count"], 0)
            self.assertEqual(res["remaining_capacity"], 0)
            self.assertEqual(res["published_today"], 4)

    def test_scenario_b_2pub_0sched_2ready(self):
        """Scenario B: 2 published + 0 scheduled + 2 READY -> schedule 1 under 3 daily limit."""
        today_start, today_end = get_business_day_bounds_utc()
        for i in range(2):
            self.db.add(UploadRecord(
                id=f"upl_b_{i}", job_id=f"job_b_pub_{i}", youtube_video_id=f"YT_B_PUB_{i}", title=f"Pub {i}", description="Test",
                status="PUBLISHED", privacy_status="public", published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_files = [
            {"id": "f_b_1", "name": "short_job_b_ready_1.mp4", "properties": {"job_id": "job_b_ready_1", "title": "Vid 1"}},
            {"id": "f_b_2", "name": "short_job_b_ready_2.mp4", "properties": {"job_id": "job_b_ready_2", "title": "Vid 2"}}
        ]
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_files if f == "01_READY" else []):
            def fake_download(fid, path):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"0" * 600000)

            with patch.object(self.pipeline.drive_engine, "download_video_from_vault", side_effect=fake_download):
                with patch.object(self.pipeline.upload_engine, "validate_media_integrity"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault"):
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            with patch("shutil.copy2"):
                                res = self.pipeline.schedule_ready_buffer(db=self.db)
                                self.assertEqual(res["scheduled_count"], 1)
                                self.assertEqual(res["published_today"], 2)
                                self.assertEqual(res["scheduled_today"], 1)
                                self.assertEqual(res["remaining_capacity"], 0)

    def test_scenario_c_2pub_1sched_5ready(self):
        """Scenario C: 2 published + 1 scheduled + 5 READY -> schedule 0 under 3 daily limit."""
        today_start, today_end = get_business_day_bounds_utc()
        now_utc = datetime.utcnow()
        for i in range(2):
            self.db.add(UploadRecord(
                id=f"upl_c_{i}", job_id=f"job_c_pub_{i}", youtube_video_id=f"YT_C_PUB_{i}", title=f"Pub {i}", description="Test",
                status="PUBLISHED", privacy_status="public", published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.add(UploadRecord(
            id="upl_c_sched", job_id="job_c_sched", youtube_video_id="YT_C_SCHED", title="Sched", description="Test",
            status="SCHEDULED", privacy_status="private", scheduled_publish_at=now_utc + timedelta(hours=1)
        ))
        self.db.commit()

        fake_files = [{"id": f"f_c_{i}", "name": f"short_job_c_ready_{i}.mp4", "properties": {"job_id": f"job_c_ready_{i}", "title": f"Ready {i}"}} for i in range(5)]
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_files if f == "01_READY" else []):
            res = self.pipeline.schedule_ready_buffer(db=self.db)
            self.assertEqual(res["scheduled_count"], 0)
            self.assertEqual(res["remaining_capacity"], 0)

    def test_scenario_d_4pub_0sched_ready(self):
        """Scenario D: 4 published -> schedule 0."""
        today_start, today_end = get_business_day_bounds_utc()
        for i in range(4):
            self.db.add(UploadRecord(
                id=f"upl_d_{i}", job_id=f"job_d_{i}", youtube_video_id=f"YT_D_{i}", title=f"Pub {i}", description="Test",
                status="PUBLISHED", privacy_status="public", published_at=today_start + timedelta(hours=1 + i)
            ))
        self.db.commit()

        fake_files = [{"id": "f_d_1", "name": "vid.mp4", "properties": {"job_id": "j_d", "title": "T"}}]
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: fake_files if f == "01_READY" else []):
            res = self.pipeline.schedule_ready_buffer(db=self.db)
            self.assertEqual(res["scheduled_count"], 0)
            self.assertEqual(res["status"], "NO_ACTION_REQUIRED")

    def test_scenario_e_ready_video_auto_scheduled(self):
        """Scenario E: Single READY video gets automatically scheduled when capacity allows."""
        fake_file = {"id": "f_e_1", "name": "short_job_e_ready_1.mp4", "properties": {"job_id": "job_e_ready_1", "title": "Auto Ready Event"}}
        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_file] if f == "01_READY" else []):
            def fake_download(fid, path):
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_bytes(b"0" * 600000)

            with patch.object(self.pipeline.drive_engine, "download_video_from_vault", side_effect=fake_download):
                with patch.object(self.pipeline.upload_engine, "validate_media_integrity"):
                    with patch.object(self.pipeline.drive_engine, "move_file_in_vault") as mock_move:
                        with patch.object(self.pipeline.drive_engine, "set_file_properties"):
                            with patch("shutil.copy2"):
                                res = self.pipeline.schedule_ready_buffer(db=self.db)
                                self.assertEqual(res["scheduled_count"], 1)
                                mock_move.assert_called_with("f_e_1", from_folder="01_READY", to_folder="02_PROCESSING")

    def test_scenario_f_consecutive_valid_slots(self):
        """Scenario F: Multiple READY videos schedule into consecutive valid slots."""
        scheduler = PublicationScheduler()
        ref_time = datetime(2026, 8, 30, 7, 0, 0) # 07:00 UTC
        
        # 1st slot after 07:00 UTC is 11:00 UTC
        s1 = scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(s1, datetime(2026, 8, 30, 11, 0, 0))

        # Mark 11:00 UTC as occupied
        self.db.add(UploadRecord(id="upl_f_1", job_id="job_f_1", youtube_video_id="YT_F1", title="F1", description="T", status="SCHEDULED", scheduled_publish_at=s1))
        self.db.commit()

        # 2nd slot after 11:00 UTC is 15:00 UTC
        s2 = scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(s2, datetime(2026, 8, 30, 15, 0, 0))

        # Mark 15:00 UTC as occupied
        self.db.add(UploadRecord(id="upl_f_2", job_id="job_f_2", youtube_video_id="YT_F2", title="F2", description="T", status="SCHEDULED", scheduled_publish_at=s2))
        self.db.commit()

        # 3rd slot rolls over to next day 06:00 UTC
        s3 = scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(s3, datetime(2026, 8, 31, 6, 0, 0))

    def test_scenario_g_expired_slot_skipped(self):
        """Scenario G: Expired slot is skipped; next valid future slot is allocated."""
        scheduler = PublicationScheduler(min_lead_minutes=15)
        # At 06:10 UTC, the 06:00 UTC slot has already expired
        now_dt = datetime(2026, 8, 30, 6, 10, 0)
        next_slot = scheduler.calculate_next_available_slot(self.db, reference_time=now_dt)
        # Must allocate 11:00 UTC, NOT 06:00 UTC
        self.assertEqual(next_slot, datetime(2026, 8, 30, 11, 0, 0))

    def test_scenario_h_idempotent_no_duplicate_upload(self):
        """Scenario H: Duplicate scheduler execution does not duplicate YouTube upload."""
        fake_file = {"id": "f_h_1", "name": "short_job_h.mp4", "properties": {"job_id": "job_h", "title": "Idem Video"}}
        self.db.add(UploadRecord(id="upl_h", job_id="job_h", youtube_video_id="YT_H", title="Idem Video", description="Test", status="SCHEDULED", scheduled_publish_at=datetime.utcnow() + timedelta(hours=3)))
        self.db.commit()

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_file] if f == "01_READY" else []):
            with patch.object(self.pipeline.drive_engine, "move_file_in_vault") as mock_move:
                res = self.pipeline.schedule_ready_buffer(db=self.db)
                self.assertEqual(res["scheduled_count"], 0)
                mock_move.assert_called_with("f_h_1", from_folder="01_READY", to_folder="02_PROCESSING")

    def test_scenario_i_concurrent_claims_safe(self):
        """Scenario I: Concurrent scheduler claims are safe with process locks."""
        from core.lock import ProcessLock
        lock = ProcessLock(name="publisher", command_name="test-concurrent")
        self.assertTrue(lock.acquire())
        try:
            # Second attempt to schedule will detect lock and exit cleanly
            res = self.pipeline.schedule_ready_buffer(db=self.db)
            self.assertEqual(res["status"], "LOCK_HELD")
            self.assertEqual(res["scheduled_count"], 0)
        finally:
            lock.release()

    def test_scenario_j_gemini_fallback_to_secondary(self):
        """Scenario J: Gemini primary exhausted -> secondary provider used transparently."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            sleeper=MagicMock()
        )
        call_log = []

        def mock_execute(api_key, model, contents, **kwargs):
            call_log.append(kwargs.get("provider_name"))
            if kwargs.get("provider_name") == "primary":
                raise GeminiQuotaExhaustedError("Daily API quota exhausted on primary provider")
            return MagicMock(text="Generated script successfully from secondary provider")

        client._execute_request = mock_execute
        resp = client.generate_content(model="gemini-2.5-flash", contents="Test prompt")
        self.assertEqual(resp.text, "Generated script successfully from secondary provider")
        self.assertEqual(call_log, ["primary", "secondary"])
        self.assertEqual(client.active_provider, "secondary")

    def test_scenario_k_gemini_all_exhausted_fail_fast(self):
        """Scenario K: Both Gemini providers exhausted -> immediate termination."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            sleeper=MagicMock()
        )
        def mock_execute(api_key, model, contents, **kwargs):
            raise GeminiQuotaExhaustedError(f"Daily quota exhausted on {kwargs.get('provider_name')}")

        client._execute_request = mock_execute
        with self.assertRaises(GeminiQuotaExhaustedError):
            client.generate_content(model="gemini-2.5-flash", contents="Test prompt")

    def test_scenario_l_zero_requirement_zero_gemini(self):
        """Scenario L: No extra Gemini calls when production requirement = 0."""
        self.pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=12)
        mock_produce = MagicMock()
        self.pipeline.produce_single_to_vault = mock_produce

        produced_count, summary = self.pipeline.maintain_buffer(target_stock=12)
        self.assertEqual(produced_count, 0)
        self.assertEqual(summary["outcome"], "SUCCEEDED")
        mock_produce.assert_not_called()

    def test_scenario_m_demand_driven_single_production(self):
        """Scenario M: Production requirement = 1 -> exactly one production job executed."""
        self.pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=[11, 11, 12, 12])
        mock_produce = MagicMock(return_value=Job(id="job_m_1", state=JobState.READY_TO_UPLOAD.value))
        self.pipeline.produce_single_to_vault = mock_produce

        produced_count, summary = self.pipeline.maintain_buffer(target_stock=12)
        self.assertEqual(produced_count, 1)
        self.assertEqual(mock_produce.call_count, 1)

    def test_scenario_n_gemini_synchronous_blocking_wait(self):
        """Scenario N: Gemini request executes as synchronous blocking wait without in-flight duplicates."""
        client = GeminiClient(api_key="test_key", sleeper=MagicMock())
        execution_order = []

        def mock_execute(*args, **kwargs):
            execution_order.append("start_request")
            time.sleep(0.01)
            execution_order.append("finish_request")
            return MagicMock(text="Success")

        client._execute_request = mock_execute
        client.generate_content(model="gemini-2.5-flash", contents="Test prompt")
        self.assertEqual(execution_order, ["start_request", "finish_request"])

    def test_scenario_o_transient_gemini_error_retry(self):
        """Scenario O: Transient Gemini error retries with bounded exponential backoff."""
        client = GeminiClient(api_key="test_key", sleeper=MagicMock())
        attempts = [0]

        with patch("google.genai.Client") as mock_genai_cls:
            mock_inst = MagicMock()
            def fake_generate(*args, **kwargs):
                attempts[0] += 1
                if attempts[0] == 1:
                    raise ConnectionResetError("Transient socket disconnect")
                return MagicMock(text="Success after retry")
            mock_inst.models.generate_content = fake_generate
            mock_genai_cls.return_value = mock_inst

            resp = client._execute_request(api_key="test_key", model="gemini-2.5-flash", contents="Prompt", max_retries=3)
            self.assertEqual(resp.text, "Success after retry")
            self.assertEqual(attempts[0], 2)

    def test_scenario_p_daily_quota_no_retry_storm(self):
        """Scenario P: Quota exhaustion does NOT retry repeatedly."""
        client = GeminiClient(api_key="test_key", sleeper=MagicMock())
        attempts = [0]

        with patch("google.genai.Client") as mock_genai_cls:
            mock_inst = MagicMock()
            def fake_generate(*args, **kwargs):
                attempts[0] += 1
                raise RuntimeError("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay quota exceeded")
            mock_inst.models.generate_content = fake_generate
            mock_genai_cls.return_value = mock_inst

            with self.assertRaises(GeminiQuotaExhaustedError):
                client._execute_request(api_key="test_key", model="gemini-2.5-flash", contents="Prompt", max_retries=3)

            # Daily quota fails fast immediately on attempt 1 without 3 attempts!
            self.assertEqual(attempts[0], 1)

    def test_scenario_q_dashboard_script_and_table_counts(self):
        """Scenario Q: Dashboard SCRIPT count and table counts reflect true intended database meaning."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db_path = Path(tf.name)

        try:
            temp_engine = create_engine(f"sqlite:///{temp_db_path}")
            Base.metadata.create_all(temp_engine)
            TempSession = sessionmaker(bind=temp_engine)
            tdb = TempSession()

            # Add sample data
            for i in range(5):
                tdb.add(Topic(id=f"top_{i}", title=f"Topic {i}", summary="Summary"))
            for i in range(3):
                tdb.add(ScriptRecord(id=f"scr_{i}", topic_id=f"top_{i}", hook="Hook", context="Ctx", escalation="Esc", reveal="Rev", loop_twist="Loop", full_text="Full", word_count=50, estimated_duration_sec=22.0))
            for i in range(2):
                tdb.add(AssetRecord(id=f"ass_{i}", asset_type="voice", source="kokoro", license="CC0", commercial_use=True, local_path="a.mp3"))
            for i in range(4):
                tdb.add(RenderOutput(id=f"ren_{i}", job_id=f"j_{i}", video_path="v.mp4", duration_sec=23.0, file_size_bytes=1024000))
            tdb.commit()
            tdb.close()
            temp_engine.dispose()

            stats = get_database_stats(temp_db_path)
            self.assertEqual(stats["topics"], 5)
            self.assertEqual(stats["scripts"], 3)
            self.assertEqual(stats["voice"], 2)
            self.assertEqual(stats["renders"], 4)
        finally:
            if temp_db_path.exists():
                try:
                    temp_db_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def test_scenario_r_dashboard_capacity_metrics(self):
        """Scenario R: Dashboard Published / Scheduled / Remaining counts remain accurate."""
        today_start, today_end = get_business_day_bounds_utc()
        now_utc = datetime.utcnow()

        # 2 published today
        for i in range(2):
            self.db.add(UploadRecord(id=f"upl_r_pub_{i}", job_id=f"j_pub_{i}", youtube_video_id=f"YT_PUB_{i}", title=f"Pub {i}", description="T", status="PUBLISHED", published_at=today_start + timedelta(hours=1+i)))
        # 1 scheduled today
        self.db.add(UploadRecord(id="upl_r_sched", job_id="j_sched", youtube_video_id="YT_SCHED", title="Sched", description="T", status="SCHEDULED", scheduled_publish_at=today_start + timedelta(hours=14)))
        self.db.commit()

        provider = SystemDataProvider()
        pub_status = provider.get_publishing_status(self.db)
        self.assertEqual(pub_status["published_today"], 2)
        self.assertEqual(pub_status["scheduled_today"], 1)
        self.assertEqual(pub_status["remaining_capacity"], 0)
        self.assertEqual(pub_status["total_booked_today"], 3)
        self.assertEqual(pub_status["limit_reached"], True)

    def test_scenario_s_drive_db_youtube_reconciliation(self):
        """Scenario S: Drive / DB / YouTube reconciliation transitions public video and cleans up processing."""
        today_start, today_end = get_business_day_bounds_utc()
        past_time = datetime.utcnow() - timedelta(hours=1)

        # Upload record that was scheduled in the past
        upl = UploadRecord(
            id="upl_s_test",
            job_id="job_s_test",
            youtube_video_id="TEST_S_YT",
            title="Reconciled Video",
            description="T",
            status="SCHEDULED",
            scheduled_publish_at=past_time
        )
        self.db.add(upl)
        self.db.commit()

        fake_processing_file = {
            "id": "drive_s_file",
            "name": "short_job_s_test_1080x1920.mp4",
            "properties": {"job_id": "job_s_test", "youtube_video_id": "TEST_S_YT"}
        }

        with patch.object(self.pipeline.drive_engine, "list_files_in_folder", side_effect=lambda f: [fake_processing_file] if f == "02_PROCESSING" else []):
            with patch.object(self.pipeline.drive_engine, "move_file_in_vault") as mock_move:
                res = self.pipeline.schedule_ready_buffer(db=self.db)
                # Auto-reconciled scheduled record whose slot has passed
                self.assertEqual(upl.status, "PUBLISHED")
                # Processing file moved to 03_PUBLISHED
                mock_move.assert_called_with("drive_s_file", from_folder="02_PROCESSING", to_folder="03_PUBLISHED")


if __name__ == "__main__":
    unittest.main()
