"""
Phase 10.2 Dedicated Upload Integrity & Test Isolation Regression Test Suite.
Verifies:
1. Missing media file is rejected locally (FileNotFoundError).
2. The 26-byte dummy test file (b"dummy_mp4_content_for_test") is rejected locally (ValueError - too small).
3. Corrupt/truncated media (>500KB but invalid container/streams) is rejected locally by FFmpeg probe.
4. Real production MP4 passes integrity validation without error.
5. Rejected media causes zero YouTube upload calls (zero API requests made).
6. Production upload behavior remains unchanged for valid media (proceeds through API).
7. Test execution (_is_test_mode=True) cannot transmit real media or dummy media to YouTube.
"""
import os
import unittest
import tempfile
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models import Base, Job, RenderOutput, UploadRecord
from config.constants import JobState
from engines.upload_engine import UploadEngine
import imageio_ffmpeg


class TestUploadIntegrityAudit(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.upload_engine = UploadEngine()

    def tearDown(self):
        self.db.close()

    def test_01_rejects_missing_file_locally(self):
        """1. Missing media file is rejected locally with FileNotFoundError."""
        non_existent = Path("data/renders/definitely_not_existing_12345.mp4")
        with self.assertRaises(FileNotFoundError) as ctx:
            self.upload_engine.validate_media_integrity(non_existent)
        self.assertIn("does not exist", str(ctx.exception))

    def test_02_rejects_26_byte_dummy_test_file_locally(self):
        """2. The 26-byte dummy test file is rejected locally before reaching any upload step."""
        dummy_bytes = b"dummy_mp4_content_for_test"
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(dummy_bytes)
            dummy_path = tf.name

        try:
            with self.assertRaises(ValueError) as ctx:
                self.upload_engine.validate_media_integrity(dummy_path)
            self.assertIn("too small", str(ctx.exception))
            self.assertIn("26 bytes", str(ctx.exception))
        finally:
            Path(dummy_path).unlink(missing_ok=True)

    def test_03_rejects_corrupt_truncated_media_locally(self):
        """3. Corrupt/truncated media exceeding 500KB is rejected locally by FFmpeg probe."""
        # Create 600 KB of random invalid bytes (passes size check, fails FFmpeg probe)
        corrupt_bytes = b"CORRUPT_HEADER_NOT_A_VALID_MP4_ATOM" * 15000  # ~540 KB
        self.assertGreater(len(corrupt_bytes), 500 * 1024)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(corrupt_bytes)
            corrupt_path = tf.name

        try:
            with self.assertRaises(ValueError) as ctx:
                self.upload_engine.validate_media_integrity(corrupt_path)
            self.assertIn("failed FFmpeg integrity validation", str(ctx.exception))
        finally:
            Path(corrupt_path).unlink(missing_ok=True)

    def test_04_valid_production_mp4_passes_integrity_validation(self):
        """4. Valid production MP4 passes integrity validation cleanly without error."""
        real_video = Path("data/renders/short_job_5a2b077ebe_1080x1920.mp4")
        if real_video.exists():
            # Must complete without raising any exception
            self.upload_engine.validate_media_integrity(real_video)
        else:
            self.skipTest("Production test video not found on disk")

    def test_05_rejected_media_causes_zero_youtube_upload_calls(self):
        """5. Rejected media causes zero YouTube upload calls."""
        job = Job(id="job_audit_reject_01", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        # Dummy file (26 bytes)
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
            tf.write(b"dummy_mp4_content_for_test")
            dummy_path = tf.name

        render = RenderOutput(
            id="rnd_reject_01",
            job_id=job.id,
            video_path=dummy_path,
            duration_sec=22.0,
            file_size_bytes=26
        )
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "The Strange London Fog of 1952", "description": "Desc", "tags": ["history"]}
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=4)

        try:
            # Force production mode (_is_test_mode returns False)
            with patch.object(self.upload_engine, "_is_test_mode", return_value=False),                  patch("googleapiclient.discovery.build") as mock_build,                  patch("googleapiclient.http.MediaFileUpload") as mock_media:

                with self.assertRaises(ValueError) as ctx:
                    self.upload_engine.schedule_short(self.db, job, render, metadata, slot)

                # Confirm error is pre-upload integrity rejection
                self.assertIn("too small", str(ctx.exception))

                # Verify ZERO YouTube API calls or media file uploads were made
                mock_build.assert_not_called()
                mock_media.assert_not_called()
        finally:
            Path(dummy_path).unlink(missing_ok=True)

    def test_06_production_upload_behavior_unchanged_for_valid_media(self):
        """6. Production upload behavior remains unchanged for valid media when mocked."""
        real_video = Path("data/renders/short_job_5a2b077ebe_1080x1920.mp4")
        if not real_video.exists():
            self.skipTest("Production test video not found on disk")

        job = Job(id="job_audit_valid_01", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(
            id="rnd_valid_01",
            job_id=job.id,
            video_path=str(real_video),
            duration_sec=23.0,
            file_size_bytes=real_video.stat().st_size
        )
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "Valid Historical Short", "description": "Desc", "tags": ["history"]}
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=4)

        # Mock YouTube API interactions
        mock_youtube = MagicMock()
        mock_insert_req = MagicMock()
        mock_insert_req.execute.return_value = {"id": "MOCK_YT_VALID_123"}
        mock_youtube.videos().insert.return_value = mock_insert_req

        mock_list_req = MagicMock()
        mock_list_req.execute.return_value = {
            "items": [{
                "status": {
                    "privacyStatus": "private",
                    "publishAt": slot.strftime("%Y-%m-%dT%H:%M:%SZ")
                }
            }]
        }
        mock_youtube.videos().list.return_value = mock_list_req

        mock_search_req = MagicMock()
        mock_search_req.execute.return_value = {"items": []}
        mock_youtube.search().list.return_value = mock_search_req

        with patch.object(self.upload_engine, "_is_test_mode", return_value=False),              patch("googleapiclient.discovery.build", return_value=mock_youtube),              patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=MagicMock()),              patch("googleapiclient.http.MediaFileUpload", return_value=MagicMock()):

            record = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)

            self.assertEqual(record.youtube_video_id, "MOCK_YT_VALID_123")
            self.assertEqual(record.status, "SCHEDULED")
            self.assertEqual(record.privacy_status, "private")
            self.assertEqual(job.state, JobState.SCHEDULED.value)

    def test_07_test_execution_cannot_transmit_to_youtube(self):
        """7. Test execution (_is_test_mode=True) stages records locally and never touches YouTube API."""
        job = Job(id="job_audit_test_01", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(
            id="rnd_test_mode_01",
            job_id=job.id,
            video_path="dummy_nonexistent.mp4",
            duration_sec=22.0,
            file_size_bytes=100
        )
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "Test Mode Guard Title", "description": "Desc", "tags": ["history"]}
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=4)

        with patch.object(self.upload_engine, "_is_test_mode", return_value=True),              patch("googleapiclient.discovery.build") as mock_build,              patch("googleapiclient.http.MediaFileUpload") as mock_media:

            rec = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)

            self.assertTrue(rec.youtube_video_id.startswith("TEST_SCHED_"))
            self.assertEqual(rec.status, "SCHEDULED")
            mock_build.assert_not_called()
            mock_media.assert_not_called()


if __name__ == "__main__":
    unittest.main()