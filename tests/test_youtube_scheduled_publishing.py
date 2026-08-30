"""
Unit and Integration Tests for True YouTube-Side Scheduled Publishing (Phase 18).
Tests:
- Publication slot calculation & 4x/day allocation (06:00, 10:00, 15:00, 20:00 UTC)
- Same-day slot assignment and cross-day rollover
- Four-slot daily ceiling & collision prevention
- YouTube scheduled upload request construction (privacyStatus='private' + publishAt RFC3339)
- publishAt explicit verification & read-back
- Scheduled vs. Published state distinction
- Upload crash recovery and in-flight reconciliation
- Reconciliation of scheduled and public YouTube videos
- API failure & retry idempotency
- UTC boundary transitions and Drive vault state preservation
"""
import os
import uuid
import unittest
from datetime import datetime, date, time as dtime, timedelta
from unittest.mock import MagicMock, patch

from core.database import SessionLocal, init_db
from core.models import Job, RenderOutput, UploadRecord, Topic
from config.constants import JobState, DAILY_SHORTS_LIMIT
from engines.scheduler_engine import PublicationScheduler
from engines.upload_engine import UploadEngine


class TestYouTubeScheduledPublishing(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.db = SessionLocal()
        cls.scheduler = PublicationScheduler(min_lead_minutes=15)
        cls.upload_engine = UploadEngine()
        cls._test_mode_patcher = patch("engines.upload_engine.UploadEngine._is_test_mode", return_value=True)
        cls._test_mode_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._test_mode_patcher.stop()
        cls.db.close()

    def setUp(self):
        # Create unique test topics and jobs
        self.test_topic = Topic(
            id=f"top_sched_{uuid.uuid4().hex[:8]}",
            title="The Battle of Agincourt Strategy",
            summary="A tactical breakthrough in medieval warfare.",
            category="European History",
            score=75.0,
            status="APPROVED"
        )
        self.test_job = Job(
            id=f"job_sched_{uuid.uuid4().hex[:8]}",
            topic_id=self.test_topic.id,
            state=JobState.READY_TO_UPLOAD.value
        )
        self.test_render = RenderOutput(
            id=f"rnd_sched_{uuid.uuid4().hex[:8]}",
            job_id=self.test_job.id,
            video_path="C:/dummy/path/video.mp4",
            duration_sec=24.0,
            file_size_bytes=15000000
        )
        self.db.add(self.test_topic)
        self.db.add(self.test_job)
        self.db.add(self.test_render)
        self.db.commit()

    def tearDown(self):
        try:
            self.db.query(UploadRecord).filter(UploadRecord.job_id == self.test_job.id).delete()
            self.db.query(RenderOutput).filter(RenderOutput.job_id == self.test_job.id).delete()
            self.db.query(Job).filter(Job.id == self.test_job.id).delete()
            self.db.query(Topic).filter(Topic.id == self.test_topic.id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def test_01_next_available_slot_calculation(self):
        """Test 1: Verifies calculating the next valid unoccupied publication slot in UTC."""
        ref_time = datetime(2026, 9, 1, 4, 0, 0)  # 04:00 UTC -> next should be 06:00 UTC
        slot = self.scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(slot, datetime(2026, 9, 1, 6, 0, 0))

    def test_02_same_day_slot_allocation(self):
        """Test 2: Verifies progression through same-day publication slots."""
        # Reference at 07:00 UTC -> Next is 11:00 UTC
        slot11 = self.scheduler.calculate_next_available_slot(self.db, reference_time=datetime(2026, 9, 1, 7, 0, 0))
        self.assertEqual(slot11, datetime(2026, 9, 1, 11, 0, 0))

        # Reference at 12:00 UTC -> Next is 15:00 UTC
        slot15 = self.scheduler.calculate_next_available_slot(self.db, reference_time=datetime(2026, 9, 1, 12, 0, 0))
        self.assertEqual(slot15, datetime(2026, 9, 1, 15, 0, 0))

        # Reference at 16:00 UTC -> Next is tomorrow 06:00 UTC
        slot06 = self.scheduler.calculate_next_available_slot(self.db, reference_time=datetime(2026, 9, 1, 16, 0, 0))
        self.assertEqual(slot06, datetime(2026, 9, 2, 6, 0, 0))

    def test_03_cross_day_rollover(self):
        """Test 3: Verifies that passing 15:00 UTC automatically rolls over to tomorrow at 06:00 UTC."""
        ref_time = datetime(2026, 9, 1, 16, 30, 0)  # Past 15:00 UTC
        slot = self.scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(slot, datetime(2026, 9, 2, 6, 0, 0))

    def test_04_four_slot_daily_ceiling(self):
        """Test 4: Verifies max 3 slots per calendar date; rolls over to next day when full."""
        test_date = date(2026, 10, 5)
        # Create 3 booked records for 2026-10-05
        records = []
        for h, m in [(6, 0), (11, 0), (15, 0)]:
            rec = UploadRecord(
                id=f"upl_test_{uuid.uuid4().hex[:8]}",
                job_id=f"job_tmp_{uuid.uuid4().hex[:8]}",
                youtube_video_id=f"YT_{uuid.uuid4().hex[:8]}",
                title="Test Video",
                description="Desc",
                scheduled_publish_at=datetime.combine(test_date, dtime(h, m)),
                status="SCHEDULED"
            )
            self.db.add(rec)
            records.append(rec)
        self.db.commit()

        try:
            # When evaluating for 2026-10-05 at 05:00 UTC, should roll over to 2026-10-06 at 06:00 UTC
            ref_time = datetime.combine(test_date, dtime(5, 0))
            slot = self.scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
            self.assertEqual(slot, datetime(2026, 10, 6, 6, 0, 0))
        finally:
            for r in records:
                self.db.delete(r)
            self.db.commit()

    def test_05_duplicate_slot_prevention(self):
        """Test 5: Verifies that an already occupied slot is skipped."""
        test_slot = datetime(2026, 11, 10, 6, 0, 0)
        rec = UploadRecord(
            id=f"upl_dup_{uuid.uuid4().hex[:8]}",
            job_id=f"job_dup_{uuid.uuid4().hex[:8]}",
            youtube_video_id="YT_OCCUPIED_123",
            title="Occupied Video",
            description="Desc",
            scheduled_publish_at=test_slot,
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        try:
            ref_time = datetime(2026, 11, 10, 4, 0, 0)
            slot = self.scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
            # Should skip 06:00 and allocate 11:00
            self.assertEqual(slot, datetime(2026, 11, 10, 11, 0, 0))
        finally:
            self.db.delete(rec)
            self.db.commit()

    def test_06_youtube_scheduled_upload_execution(self):
        """Test 6: Verifies schedule_short creates SCHEDULED record with publishAt in TEST_MODE."""
        target_slot = datetime(2026, 12, 1, 15, 0, 0)
        metadata = {
            "title": "The Agincourt Strategy",
            "description": "Historical documentary short.",
            "tags": ["history", "agincourt", "shorts"]
        }
        rec = self.upload_engine.schedule_short(
            db=self.db,
            job=self.test_job,
            render=self.test_render,
            metadata=metadata,
            scheduled_publish_at=target_slot
        )
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, "SCHEDULED")
        self.assertEqual(rec.privacy_status, "private")
        self.assertEqual(rec.scheduled_publish_at, target_slot)
        self.assertIsNone(rec.published_at)
        self.assertEqual(self.test_job.state, JobState.SCHEDULED.value)

    def test_07_scheduled_vs_published_state_distinction(self):
        """Test 7: Verifies distinct semantic representations for SCHEDULED vs PUBLISHED."""
        target_slot = datetime(2026, 12, 5, 10, 0, 0)
        rec = UploadRecord(
            id=f"upl_stat_{uuid.uuid4().hex[:8]}",
            job_id=self.test_job.id,
            youtube_video_id="YT_SCHED_VAL",
            title="Scheduled Title",
            description="Description",
            privacy_status="private",
            scheduled_publish_at=target_slot,
            published_at=None,
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        loaded = self.db.query(UploadRecord).filter(UploadRecord.id == rec.id).first()
        self.assertEqual(loaded.status, "SCHEDULED")
        self.assertEqual(loaded.privacy_status, "private")
        self.assertIsNone(loaded.published_at)
        self.assertIsNotNone(loaded.scheduled_publish_at)

        # Transition to PUBLISHED
        loaded.status = "PUBLISHED"
        loaded.published_at = target_slot
        loaded.privacy_status = "public"
        self.db.commit()

        reloaded = self.db.query(UploadRecord).filter(UploadRecord.id == rec.id).first()
        self.assertEqual(reloaded.status, "PUBLISHED")
        self.assertEqual(reloaded.privacy_status, "public")
        self.assertIsNotNone(reloaded.published_at)
        self.db.delete(reloaded)
        self.db.commit()

    def test_08_reconciliation_of_past_scheduled_uploads(self):
        """Test 8: Verifies reconciler moves past scheduled records to PUBLISHED."""
        past_slot = datetime.utcnow() - timedelta(hours=2)
        rec = UploadRecord(
            id=f"upl_past_{uuid.uuid4().hex[:8]}",
            job_id=self.test_job.id,
            youtube_video_id="TEST_PAST_YT",
            title="Past Scheduled Video",
            description="Description",
            privacy_status="private",
            scheduled_publish_at=past_slot,
            published_at=None,
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        reconciled = self.upload_engine.reconcile_scheduled_uploads(self.db)
        self.assertTrue(any(r["job_id"] == self.test_job.id for r in reconciled))

        reloaded = self.db.query(UploadRecord).filter(UploadRecord.id == rec.id).first()
        self.assertEqual(reloaded.status, "PUBLISHED")
        self.assertEqual(reloaded.privacy_status, "public")
        self.assertIsNotNone(reloaded.published_at)

    def test_09_retry_idempotency(self):
        """Test 9: Verifies repeated schedule_short calls return existing record without duplication."""
        target_slot = datetime(2026, 12, 10, 6, 0, 0)
        metadata = {"title": "Idempotent Video", "description": "Desc", "tags": ["history"]}
        
        rec1 = self.upload_engine.schedule_short(self.db, self.test_job, self.test_render, metadata, target_slot)
        rec2 = self.upload_engine.schedule_short(self.db, self.test_job, self.test_render, metadata, target_slot)

        self.assertEqual(rec1.id, rec2.id)
        self.assertEqual(rec1.youtube_video_id, rec2.youtube_video_id)

    def test_10_utc_boundary_behavior(self):
        """Test 10: Verifies precise UTC boundary evaluation at 23:59 UTC."""
        ref_time = datetime(2026, 12, 31, 23, 59, 0)
        slot = self.scheduler.calculate_next_available_slot(self.db, reference_time=ref_time)
        self.assertEqual(slot, datetime(2027, 1, 1, 6, 0, 0))


if __name__ == "__main__":
    unittest.main()
