"""
Production Hardening Regression Test Suite.
Tests:
1. Duplicate Short prevention (Job-level idempotency, title dedup, Drive pre-flight filtering).
2. BGM selection diversity (All 4 library tracks evaluated and selected appropriately, metadata recorded).
3. Hard schedule-only publishing (Rejection of immediate public uploads, future publishAt enforcement).
"""
import unittest
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Job, Topic, ScriptRecord, AssetRecord, RenderOutput, UploadRecord
from config.constants import JobState, LicenseType
from config.settings import MUSIC_DIR
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.upload_engine import UploadEngine
from engines.scheduler_engine import PublicationScheduler


class TestProductionHardening(unittest.TestCase):

    def setUp(self):
        from sqlalchemy.pool import StaticPool
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Dummy render file
        self.test_render_file = Path("data/renders/test_hardening_sample.mp4")
        self.test_render_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.test_render_file.exists():
            self.test_render_file.write_bytes(b"dummy_mp4_content_for_test")

        self.upload_engine = UploadEngine()
        self._test_mode_patcher = patch("engines.upload_engine.UploadEngine._is_test_mode", return_value=True)
        self._test_mode_patcher.start()

    def tearDown(self):
        self._test_mode_patcher.stop()
        self.db.close()
        if self.test_render_file.exists():
            try:
                self.test_render_file.unlink()
            except Exception:
                pass

    # =========================================================================
    # 1. DUPLICATE SHORT PREVENTION TESTS
    # =========================================================================

    def test_01_job_level_idempotency_returns_existing_record(self):
        """Test 1: Calling schedule_short with an already scheduled Job returns existing record without duplicate."""
        job = Job(id="job_hard_001", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(
            id="rnd_001",
            job_id=job.id,
            video_path=str(self.test_render_file),
            duration_sec=22.0,
            file_size_bytes=1024000
        )
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "The Strange London Fog of 1952", "description": "Desc", "tags": ["history"]}
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=4)

        rec1 = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)
        rec2 = self.upload_engine.schedule_short(self.db, job, render, metadata, slot)

        self.assertEqual(rec1.id, rec2.id)
        self.assertEqual(rec1.youtube_video_id, rec2.youtube_video_id)

        # Confirm exactly 1 record in database
        count = self.db.query(UploadRecord).filter(UploadRecord.job_id == job.id).count()
        self.assertEqual(count, 1)

    def test_02_title_level_duplicate_protection(self):
        """Test 2: Calling schedule_short with a duplicate title returns existing record."""
        job1 = Job(id="job_title_001", state=JobState.READY_TO_UPLOAD.value)
        job2 = Job(id="job_title_002", state=JobState.READY_TO_UPLOAD.value)
        self.db.add_all([job1, job2])
        self.db.commit()

        render1 = RenderOutput(id="rnd_t1", job_id=job1.id, video_path=str(self.test_render_file), duration_sec=22.0, file_size_bytes=1024000)
        render2 = RenderOutput(id="rnd_t2", job_id=job2.id, video_path=str(self.test_render_file), duration_sec=22.0, file_size_bytes=1024000)
        self.db.add_all([render1, render2])
        self.db.commit()

        metadata = {"title": "The Dancing Plague of Strasbourg", "description": "Desc", "tags": ["history"]}
        slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=6)

        rec1 = self.upload_engine.schedule_short(self.db, job1, render1, metadata, slot)
        rec2 = self.upload_engine.schedule_short(self.db, job2, render2, metadata, slot)

        self.assertEqual(rec1.id, rec2.id)
        count = self.db.query(UploadRecord).count()
        self.assertEqual(count, 1)

    def test_03_preclaim_deduplication_filters_published_and_scheduled_files(self):
        """Test 3: publish_next_from_vault filters out already published/scheduled files from 01_READY."""
        from main import ShortsPipeline

        # Populate SQLite with existing upload records
        upl_pub = UploadRecord(
            id="upl_pub_01",
            job_id="job_erfurt_1184",
            youtube_video_id="yt_erfurt_1184",
            title="The Erfurt Latrine Disaster",
            description="desc",
            status="PUBLISHED"
        )
        upl_sched = UploadRecord(
            id="upl_sched_01",
            job_id="job_smell_1858",
            youtube_video_id="yt_smell_1858",
            title="The Great Stink of London",
            description="desc",
            status="SCHEDULED"
        )
        self.db.add_all([upl_pub, upl_sched])
        self.db.commit()

        # Mock Drive vault with 3 files in 01_READY: 1 published, 1 scheduled, 1 fresh
        mock_ready_files = [
            {
                "id": "file_pub_01",
                "name": "short_job_erfurt_1184_1080x1920.mp4",
                "properties": {"job_id": "job_erfurt_1184", "title": "The Erfurt Latrine Disaster"}
            },
            {
                "id": "file_sched_01",
                "name": "short_job_smell_1858_1080x1920.mp4",
                "properties": {"job_id": "job_smell_1858", "title": "The Great Stink of London"}
            },
            {
                "id": "file_fresh_01",
                "name": "short_job_fresh_1896_1080x1920.mp4",
                "properties": {"job_id": "job_fresh_1896", "title": "The 38-Minute Anglo-Zanzibar War"}
            }
        ]

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda folder: mock_ready_files if folder == "01_READY" else []
        def mock_download(file_id, dest_path):
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(b"dummy_download_content")
        pipeline.drive_engine.download_video_from_vault.side_effect = mock_download
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        with patch.object(pipeline, "upload_engine", self.upload_engine):
            with patch("config.settings.TEST_MODE", True):
                res = pipeline.publish_next_from_vault()

        self.assertTrue(res)
        # Verify that file_pub_01 was moved directly to 03_PUBLISHED
        pipeline.drive_engine.move_file_in_vault.assert_any_call("file_pub_01", from_folder="01_READY", to_folder="03_PUBLISHED")
        # Verify that file_sched_01 was moved to 02_PROCESSING
        pipeline.drive_engine.move_file_in_vault.assert_any_call("file_sched_01", from_folder="01_READY", to_folder="02_PROCESSING")
        # Verify that only the fresh file was claimed for scheduling
        pipeline.drive_engine.move_file_in_vault.assert_any_call("file_fresh_01", from_folder="01_READY", to_folder="02_PROCESSING")

    # =========================================================================
    # 2. BGM SELECTION & METADATA TESTS
    # =========================================================================

    def test_04_bgm_selection_covers_all_four_library_tracks(self):
        """Test 4: Diverse content profiles select all 4 configured tracks appropriately."""
        mixer = AudioMixer()

        # Disable AI to test the deterministic semantic keyword classifier
        mixer.classify_story_mood_ai = MagicMock(return_value=None)

        test_cases = [
            {
                "category": "Ancient History & Oddities",
                "title": "The Medieval Erfurt Latrine Collapse of 1184",
                "summary": "Nobles fell through floor into sewage during a royal diet",
                "script": "In 1184, King Henry held court when the floor collapsed into a privy disaster, killing dozens of knights in a bizarre medieval royal scandal.",
                "expected_key": "best_historical"
            },
            {
                "category": "Human Tragedies & Sacrifices",
                "title": "The Poignant Grief of the Lost Children of Eyam",
                "summary": "Villagers quarantined themselves to save neighboring towns during fatal plague",
                "script": "A heart-wrenching tragedy of sacrifice, tears, and mourning as the entire village perished in sorrow.",
                "expected_key": "emotional_sad"
            },
            {
                "category": "Unexplained Historical Mysteries",
                "title": "The Baffling Secret of the Voynich Manuscript",
                "summary": "An ancient cryptic book written in an unknown code that no cryptographer has solved",
                "script": "A dark ancient enigma of hidden alchemy and unsolved curiosity that remains a scientific puzzle.",
                "expected_key": "flux_ambient"
            },
            {
                "category": "High-Stakes Escapes & Heists",
                "title": "The Great Train Robbery Manhunt and Escape",
                "summary": "A high-tension race against time as police pursued masked fugitives in a deadly chase",
                "script": "A thrilling countdown, panic in the streets, and a dangerous manhunt in a race against the clock.",
                "expected_key": "suspense_climax"
            }
        ]

        selected_tracks = set()
        for tc in test_cases:
            path, key, mood, reason = mixer.select_bgm_track(
                category=tc["category"],
                title=tc["title"],
                summary=tc["summary"],
                script_text=tc["script"]
            )
            self.assertEqual(key, tc["expected_key"], f"Failed for {tc['title']}: got {key}, expected {tc['expected_key']} (Reason: {reason})")
            self.assertTrue(path.exists(), f"BGM file {path} does not exist on disk!")
            selected_tracks.add(key)

        # All 4 tracks must be covered
        self.assertEqual(len(selected_tracks), 4)

    def test_05_bgm_metadata_serialized_to_asset_record(self):
        """Test 5: get_background_music persists full BGM metadata JSON into AssetRecord."""
        mixer = AudioMixer()
        mixer.classify_story_mood_ai = MagicMock(return_value=None)

        asset = mixer.get_background_music(
            db=self.db,
            category="Unexplained Mysteries",
            title="The Lost Colony of Roanoke Mystery",
            summary="115 colonists vanished into thin air leaving only a cryptic carving",
            script_text="An unexplained phenomenon and ancient secret in early America."
        )

        self.assertIsNotNone(asset)
        self.assertIsNotNone(asset.metadata_json)

        meta = json.loads(asset.metadata_json)
        self.assertEqual(meta["bgm_track"], "flux_ambient")
        self.assertIn("reason", meta)
        self.assertIn("mood", meta)
        self.assertIn("filename", meta)

    # =========================================================================
    # 3. HARD SCHEDULE-ONLY PUBLISHING TESTS
    # =========================================================================

    def test_06_immediate_public_upload_raises_runtime_error_in_production(self):
        """Test 6: upload_short with privacy_status='public' raises RuntimeError when not in test mode."""
        job = Job(id="job_prod_guard_001", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(
            id="rnd_guard_001",
            job_id=job.id,
            video_path=str(self.test_render_file),
            duration_sec=22.0,
            file_size_bytes=1024000
        )
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "Test Title", "description": "desc", "tags": []}

        with patch.object(self.upload_engine, "_is_test_mode", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                self.upload_engine.upload_short(self.db, job, render, metadata, privacy_status="public")
            self.assertIn("Immediate public publishing is disabled in production", str(ctx.exception))

    def test_07_schedule_short_rejects_past_or_immediate_publish_at(self):
        """Test 7: schedule_short rejects timestamps that are in the past or immediately present."""
        job = Job(id="job_slot_past_001", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(id="rnd_p01", job_id=job.id, video_path=str(self.test_render_file), duration_sec=22.0, file_size_bytes=1024000)
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "Test Title", "description": "desc", "tags": []}
        past_slot = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)

        with self.assertRaises(ValueError) as ctx:
            self.upload_engine.schedule_short(self.db, job, render, metadata, past_slot)
        self.assertIn("Must be a future slot", str(ctx.exception))

    def test_08_schedule_short_enforces_private_and_future_utc_slot(self):
        """Test 8: schedule_short produces private privacy_status and future RFC3339 UTC timestamp."""
        job = Job(id="job_slot_valid_001", state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        render = RenderOutput(id="rnd_v01", job_id=job.id, video_path=str(self.test_render_file), duration_sec=22.0, file_size_bytes=1024000)
        self.db.add(render)
        self.db.commit()

        metadata = {"title": "The Siege of Malta (1565)", "description": "desc", "tags": ["history"]}
        future_slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)

        with patch.object(self.upload_engine, "_is_test_mode", return_value=True):
            rec = self.upload_engine.schedule_short(self.db, job, render, metadata, future_slot)
        self.assertEqual(rec.privacy_status, "private")
        self.assertEqual(rec.status, "SCHEDULED")
        self.assertEqual(rec.scheduled_publish_at, future_slot.replace(microsecond=0))


if __name__ == "__main__":
    unittest.main()
