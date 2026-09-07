"""
Regression Test: Non-Negotiable Publication Invariant and Deduplication Safety
=============================================================================
Verifies that:
1. An asset in 01_READY without an authoritative YouTube video ID is NEVER moved
   to 03_PUBLISHED under any deduplication or self-matching condition.
2. A candidate in 01_READY matching its own PRODUCED topic does NOT trigger false
   deduplication rejection (self-matching prevented via exclude_topic_id).
3. An un-uploaded asset in 02_PROCESSING is NEVER moved to 03_PUBLISHED; it is
   either recovered to 01_READY or quarantined to 04_FAILED.
"""

import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from pathlib import Path
import tempfile
import shutil

from core.models import Base, Topic, UploadRecord, Job, RenderedVideoRecord
from main import ShortsPipeline
from engines.deduplication_engine import DeduplicationRouter, DeduplicationResult


class TestPreclaimDeduplicationInvariant(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_invariant.db"
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("main.CompositeLock")
    def test_unuploaded_ready_asset_never_moved_to_published(self, mock_lock_cls):
        """Invariant: An asset in 01_READY with no YouTube ID must NEVER move to 03_PUBLISHED."""
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        topic = Topic(
            id="top_tunguska_01",
            event_id="evt_hist_tunguska",
            title="The Tunguska Cosmic Blast of 1908",
            summary="A cosmic blast flattened 80 million trees in Siberia in 1908.",
            status="PRODUCED"
        )
        self.db.add(topic)
        self.db.commit()

        mock_candidate = {
            "id": "file_tunguska_drive_id",
            "name": "short_man_c85a0dd30bda.mp4",
            "properties": {
                "event_id": "evt_hist_tunguska",
                "topic_id": "top_tunguska_01",
                "title": "The Tunguska Cosmic Blast of 1908",
                "voice": "af_bella",
                "duration_seconds": "23.5"
            }
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = self.SessionLocal
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [mock_candidate] if f == "01_READY" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()
        pipeline.upload_engine = MagicMock()
        pipeline.upload_engine._is_test_mode.return_value = True
        pipeline.upload_engine.reconcile_scheduled_uploads.return_value = []
        pipeline.analytics_engine = MagicMock()

        with patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "OK")):
            pipeline.upload_engine.schedule_short = MagicMock()
            pipeline.schedule_ready_buffer(db=self.db, max_to_schedule=1)

        for call in pipeline.drive_engine.move_file_in_vault.call_args_list:
            args, kwargs = call
            to_folder = kwargs.get("to_folder") or (args[2] if len(args) > 2 else None)
            from_folder = kwargs.get("from_folder") or (args[1] if len(args) > 1 else None)
            if from_folder == "01_READY":
                self.assertNotEqual(
                    to_folder,
                    "03_PUBLISHED",
                    "VIOLATION: Asset in 01_READY with no YouTube ID was moved to 03_PUBLISHED!"
                )

    @patch("main.CompositeLock")
    def test_duplicate_story_in_ready_quarantined_not_published(self, mock_lock_cls):
        """Invariant: An asset in 01_READY that duplicates an existing story must be quarantined to 04_FAILED."""
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        past_upload = UploadRecord(
            id="upl_past_01",
            job_id="job_past_01",
            youtube_video_id="yt_already_pub",
            title="The Tunguska Cosmic Blast of 1908",
            description="A past video about the Tunguska cosmic blast.",
            status="PUBLISHED"
        )
        self.db.add(past_upload)
        self.db.commit()

        duplicate_candidate = {
            "id": "file_new_dup_id",
            "name": "short_man_dup.mp4",
            "properties": {
                "title": "The Tunguska Cosmic Blast of 1908",
                "voice": "af_bella"
            }
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = self.SessionLocal
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [duplicate_candidate] if f == "01_READY" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()
        pipeline.upload_engine = MagicMock()
        pipeline.upload_engine._is_test_mode.return_value = True
        pipeline.upload_engine.reconcile_scheduled_uploads.return_value = []
        pipeline.analytics_engine = MagicMock()

        with patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "OK")):
            pipeline.upload_engine.schedule_short = MagicMock()
            pipeline.schedule_ready_buffer(db=self.db, max_to_schedule=1)

        pipeline.drive_engine.move_file_in_vault.assert_called_with(
            "file_new_dup_id", from_folder="01_READY", to_folder="04_FAILED"
        )

    @patch("main.CompositeLock")
    def test_processing_orphan_without_youtube_id_recovered_to_ready(self, mock_lock_cls):
        """Invariant: An asset in 02_PROCESSING without a YouTube ID must NEVER move to 03_PUBLISHED."""
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        orphan_candidate = {
            "id": "file_proc_orphan",
            "name": "short_man_orphan.mp4",
            "properties": {
                "title": "The Tunguska Cosmic Blast of 1908",
                "voice": "af_bella"
            }
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = self.SessionLocal
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [orphan_candidate] if f == "02_PROCESSING" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()
        pipeline.upload_engine = MagicMock()
        pipeline.upload_engine._is_test_mode.return_value = True
        pipeline.upload_engine.reconcile_scheduled_uploads.return_value = []
        pipeline.analytics_engine = MagicMock()

        with patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "OK")):
            pipeline.schedule_ready_buffer(db=self.db, max_to_schedule=1)

        pipeline.drive_engine.move_file_in_vault.assert_called_with(
            "file_proc_orphan", from_folder="02_PROCESSING", to_folder="01_READY"
        )


if __name__ == "__main__":
    unittest.main()
