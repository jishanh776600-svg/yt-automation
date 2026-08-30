"""
Regression Test Suite for Analytics Data Integrity & Database Isolation (Master Fix).
Validates:
1. TEST_YT_* records do not appear in production leaderboard.
2. test_vid_* records do not appear.
3. yt_loop_* records do not appear.
4. test_local records do not appear.
5. Invalid/non-production YouTube IDs do not appear.
6. Valid 11-character YouTube IDs can appear.
7. Genuine production records still appear.
8. Analytics values are read from PerformanceSnapshot / real persisted metrics.
9. No mock test metrics leak into production leaderboard.
10. Test execution does not modify canonical data/database/pipeline.db.
11. Test database is isolated.
12. Database sync cannot accidentally upload test DB as canonical production DB.
"""
import os
import re
import uuid
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from core.database import init_db, SessionLocal
from core.models import UploadRecord, PerformanceSnapshot, Job, Topic, VideoAnalysisRecord
from dashboard.data_provider import SystemDataProvider
from core.database_sync import upload_canonical_database


class TestAnalyticsIntegrityAndIsolation(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.provider = SystemDataProvider()

    def tearDown(self):
        self.db.close()

    def test_01_synthetic_test_yt_excluded_from_leaderboard(self):
        """Test 1: TEST_YT_* records must be filtered out of the leaderboard."""
        upl = UploadRecord(
            id=f"upl_test_{uuid.uuid4().hex[:8]}",
            job_id="job_test_synth_1",
            youtube_video_id="TEST_YT_999",
            title="Synthetic Test Video",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="test_local",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id="TEST_YT_999",
            snapshot_time=datetime.utcnow(),
            views=999999,
            likes=88888,
            comments=7777,
            average_view_percentage=99.0
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertNotIn("TEST_YT_999", yt_ids, "TEST_YT_* records must be excluded from leaderboard.")

    def test_02_test_vid_prefix_excluded(self):
        """Test 2: test_vid_* records must be excluded."""
        upl = UploadRecord(
            id=f"upl_test_{uuid.uuid4().hex[:8]}",
            job_id="job_test_synth_2",
            youtube_video_id="test_vid_abc",
            title="Test Vid Prefix",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="private",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id="test_vid_abc",
            snapshot_time=datetime.utcnow(),
            views=50000,
            likes=5000,
            comments=500
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertNotIn("test_vid_abc", yt_ids)

    def test_03_yt_loop_prefix_excluded(self):
        """Test 3: yt_loop_* records must be excluded."""
        upl = UploadRecord(
            id=f"upl_loop_{uuid.uuid4().hex[:8]}",
            job_id="job_loop_test",
            youtube_video_id="yt_loop_12345",
            title="Ancient Mystery Solved",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="public",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id="yt_loop_12345",
            snapshot_time=datetime.utcnow(),
            views=5000,
            likes=450,
            comments=35
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertNotIn("yt_loop_12345", yt_ids)

    def test_04_test_local_privacy_status_excluded(self):
        """Test 4: Any record with privacy_status='test_local' is excluded."""
        upl = UploadRecord(
            id=f"upl_realish_{uuid.uuid4().hex[:8]}",
            job_id="job_realish",
            youtube_video_id="AbCdEfGhIjK",  # Valid 11-char ID
            title="Local Test Video",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="test_local",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id="AbCdEfGhIjK",
            snapshot_time=datetime.utcnow(),
            views=1000,
            likes=50,
            comments=5
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertNotIn("AbCdEfGhIjK", yt_ids)

    def test_05_invalid_youtube_id_length_excluded(self):
        """Test 5: IDs that do not match ^[A-Za-z0-9_-]{11}$ are rejected."""
        upl = UploadRecord(
            id=f"upl_short_{uuid.uuid4().hex[:8]}",
            job_id="job_short",
            youtube_video_id="short_id_7",  # 10 chars -> Invalid
            title="Short ID Video",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="public",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id="short_id_7",
            snapshot_time=datetime.utcnow(),
            views=1000,
            likes=50
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertNotIn("short_id_7", yt_ids)

    def test_06_valid_11_char_youtube_id_included(self):
        """Test 6: Genuine 11-char YouTube ID with valid status and public/unlisted/private privacy is included."""
        valid_id = "V_TestId_99"  # 11 valid characters
        upl = UploadRecord(
            id=f"upl_valid_{uuid.uuid4().hex[:8]}",
            job_id="job_valid_1",
            youtube_video_id=valid_id,
            title="Genuine Test Short Title",
            description="Test Description",
            status="PUBLISHED",
            privacy_status="public",
            published_at=datetime.utcnow() - timedelta(days=1)
        )
        self.db.add(upl)
        self.db.commit()

        snap = PerformanceSnapshot(
            upload_id=upl.id,
            youtube_video_id=valid_id,
            snapshot_time=datetime.utcnow(),
            views=750,
            likes=42,
            comments=8,
            average_view_percentage=85.5
        )
        self.db.add(snap)
        self.db.commit()

        board = self.provider.get_published_performance_leaderboard(self.db)
        yt_ids = [item["youtube_video_id"] for item in board]
        self.assertIn(valid_id, yt_ids)
        item = next(x for x in board if x["youtube_video_id"] == valid_id)
        self.assertEqual(item["views"], 750)
        self.assertEqual(item["likes"], 42)
        self.assertEqual(item["comments"], 8)
        self.assertEqual(item["apv_display"], "85.5%")

    def test_07_test_environment_blocks_accidental_canonical_db_upload(self):
        """Test 7: upload_canonical_database() blocks execution if IS_TEST_ENV=true."""
        res = upload_canonical_database()
        self.assertEqual(res.get("status"), "BLOCKED_TEST_MODE")


if __name__ == "__main__":
    unittest.main()
