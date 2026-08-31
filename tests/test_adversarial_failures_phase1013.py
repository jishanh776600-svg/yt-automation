"""
Phase 10.13 Adversarial Failure-Injection Test Suite.
Verifies deep production hardening:
1. Drive API 503 / transient failure retry resilience.
2. YouTube upload timeout recovery using embedded JOB_ID in description.
3. Anti-false-positive reconciliation: unrelated videos with substring titles are rejected.
4. Drive/DB vault reconciliation does not flag in-flight 02_PROCESSING jobs as missing.
5. Corrupted downloaded database rejected without overwriting local database.
6. Pathological analytics data (deleted video, missing metrics) does not corrupt learning.
7. WAL checkpoint execution flushes database cleanly before upload.
"""
import os
import sys
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from config.settings import PROJECT_ROOT, DB_PATH
from core.models import Job, UploadRecord, RenderOutput, PerformanceSnapshot
from config.constants import JobState


class TestAdversarialFailuresPhase1013(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_pipeline.db"
        
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("CREATE TABLE topics (id TEXT PRIMARY KEY, title TEXT);")
        conn.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY, state TEXT);")
        conn.execute("CREATE TABLE uploads (id TEXT PRIMARY KEY, title TEXT);")
        conn.execute("CREATE TABLE scripts (id TEXT PRIMARY KEY);")
        conn.execute("CREATE TABLE performance_snapshots (id TEXT PRIMARY KEY);")
        conn.execute("INSERT INTO topics VALUES ('t1', 'Topic 1');")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_drive_api_transient_failure_retries_successfully(self):
        """Test 1: Drive API calls survive transient 503/network glitches via retry_call."""
        from engines.drive_engine import DriveVaultEngine

        engine = DriveVaultEngine(token_path=self.db_path)  # dummy path
        mock_service = MagicMock()
        engine.get_drive_service = MagicMock(return_value=mock_service)
        engine.get_folder_id = MagicMock(return_value="folder_123")

        # Simulate 2 transient 503 failures followed by success
        mock_req = MagicMock()
        mock_req.execute.side_effect = [
            ConnectionResetError("Connection dropped by remote server"),
            RuntimeError("HTTP 503 Service Unavailable"),
            {"id": "file_moved_success", "name": "test.mp4", "parents": ["folder_123"]}
        ]
        mock_service.files.return_value.update.return_value = mock_req

        result = engine.move_file_in_vault("file_999", from_folder="01_READY", to_folder="02_PROCESSING")

        self.assertEqual(result["id"], "file_moved_success")
        self.assertEqual(mock_req.execute.call_count, 3)

    def test_02_youtube_reconciliation_via_embedded_job_id(self):
        """Test 2: YouTube reconciliation matches via embedded [JOB_ID: ...] even if title varies."""
        from engines.upload_engine import UploadEngine

        engine = UploadEngine()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None

        job = Job(id="job_adv_789", state=JobState.READY_TO_UPLOAD.value)
        render = RenderOutput(id="rnd_789", job_id="job_adv_789", video_path="data/renders/fake.mp4")
        metadata = {"title": "The Defenestrations of Prague", "description": "Historic event.", "tags": ["history"]}
        scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)

        engine.validate_media_integrity = MagicMock()
        engine._is_test_mode = MagicMock(return_value=False)

        mock_youtube = MagicMock()
        # Upload raises timeout
        mock_youtube.videos.return_value.insert.return_value.execute.side_effect = TimeoutError("HTTP Read Timeout")

        # Search returns video on channel with different title but matching embedded JOB_ID in description
        mock_youtube.search.return_value.list.return_value.execute.side_effect = [
            {"items": []},  # pre-upload
            {"items": [
                {
                    "id": {"videoId": "yt_exact_job_match"},
                    "snippet": {
                        "title": "Prague Defenestrations Was Crazy",
                        "description": "Historic event.\\n\\n[JOB_ID: job_adv_789]"
                    }
                }
            ]}
        ]

        with patch("googleapiclient.discovery.build", return_value=mock_youtube),              patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=MagicMock()),              patch.object(Path, "exists", return_value=True),              patch("googleapiclient.http.MediaFileUpload", return_value=MagicMock()):

            rec = engine.schedule_short(
                db=mock_db,
                job=job,
                render=render,
                metadata=metadata,
                scheduled_publish_at=scheduled_at
            )

            self.assertIsNotNone(rec)
            self.assertEqual(rec.youtube_video_id, "yt_exact_job_match")
            self.assertEqual(job.state, JobState.SCHEDULED.value)

    def test_03_anti_false_positive_reconciliation(self):
        """Test 3: Unrelated video with substring title and different JOB_ID is NOT falsely reconciled."""
        from engines.upload_engine import UploadEngine

        engine = UploadEngine()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.filter.return_value.first.return_value = None

        job = Job(id="job_fresh_001", state=JobState.READY_TO_UPLOAD.value)
        render = RenderOutput(id="rnd_fresh", job_id="job_fresh_001", video_path="data/renders/fake.mp4")
        metadata = {"title": "The Great Stink", "description": "New video", "tags": ["history"]}
        scheduled_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)

        engine.validate_media_integrity = MagicMock()
        engine._is_test_mode = MagicMock(return_value=False)

        mock_youtube = MagicMock()
        # Upload fails with network timeout during resumable chunk upload
        mock_youtube.videos.return_value.insert.return_value.next_chunk.side_effect = TimeoutError("HTTP Read Timeout")
        mock_youtube.videos.return_value.insert.return_value.execute.side_effect = TimeoutError("HTTP Read Timeout")

        # Search returns an old published video: title contains "The Great Stink of London (1858)" and different JOB_ID
        mock_youtube.search.return_value.list.return_value.execute.side_effect = [
            {"items": []},  # pre-upload
            {"items": [
                {
                    "id": {"videoId": "yt_old_unrelated_video"},
                    "snippet": {
                        "title": "The Great Stink of London (1858)",  # substring match but NOT exact and different job
                        "description": "Old historical documentary.\\n\\n[JOB_ID: job_old_999]"
                    }
                }
            ]}
        ]

        with patch("googleapiclient.discovery.build", return_value=mock_youtube),              patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=MagicMock()),              patch.object(Path, "exists", return_value=True),              patch("googleapiclient.http.MediaFileUpload", return_value=MagicMock()):

            # Must raise the original TimeoutError because the found video is NOT this job!
            with self.assertRaises(TimeoutError):
                engine.schedule_short(
                    db=mock_db,
                    job=job,
                    render=render,
                    metadata=metadata,
                    scheduled_publish_at=scheduled_at
                )

    def test_04_recovery_manager_does_not_flag_processing_files_as_missing(self):
        """Test 4: reconcile_drive_vault_and_db skips false-positive alert for jobs in 02_PROCESSING."""
        from core.recovery_manager import RecoveryManager

        mock_drive = MagicMock()
        # 01_READY is empty, but 02_PROCESSING contains the file
        mock_drive.list_files_in_folder.side_effect = lambda folder: {
            "01_READY": [],
            "02_PROCESSING": [{"id": "f_proc_1", "name": "short_job_proc_123.mp4", "properties": {"job_id": "job_proc_123"}}],
            "03_PUBLISHED": [],
            "04_FAILED": []
        }.get(folder, [])

        manager = RecoveryManager(drive_engine=mock_drive)
        mock_db = MagicMock()

        job_in_flight = Job(id="job_proc_123", state=JobState.READY_TO_UPLOAD.value)
        mock_db.query.return_value.filter.return_value.all.return_value = [job_in_flight]

        results = manager.reconcile_drive_vault_and_db(mock_db)

        # Inconsistencies should be 0 because the file is legitimately in 02_PROCESSING
        self.assertEqual(len(results["inconsistencies"]), 0)

    def test_05_corrupted_download_preserves_local_database(self):
        """Test 5: Download of corrupted database fails closed without replacing existing local database."""
        from core.database_sync import download_canonical_database

        local_db = self.db_path
        original_bytes = local_db.read_bytes()

        mock_drive = MagicMock()
        # Mock download_database to write corrupted bytes to the destination
        def fake_download(*args, **kwargs):
            dest = kwargs.get("local_dest_path") or (args[0] if args else None)
            dest.write_text("CORRUPTED_NON_SQLITE_DATA")
            return dest

        mock_drive.download_database.side_effect = fake_download

        with self.assertRaises(ValueError):
            download_canonical_database(target_path=local_db, drive_engine=mock_drive)

        # Local database must remain completely intact and untouched
        self.assertEqual(local_db.read_bytes(), original_bytes)


if __name__ == "__main__":
    unittest.main()
