"""
Negative Invariant Verification & Lifecycle Gateway Hard Barrier Test Suite
===========================================================================
Strict automated verification of 20 negative invariants:
1.  test_invariant_zero_unuploaded_short_can_reach_published
2.  test_published_requires_authoritative_youtube_id
3.  test_published_requires_matching_upload_record
4.  test_published_requires_youtube_readback
5.  test_private_scheduled_video_cannot_enter_published
6.  test_nonexistent_youtube_video_cannot_enter_published
7.  test_title_match_does_not_prove_publication
8.  test_duplicate_ready_asset_never_enters_published
9.  test_candidate_cannot_self_match
10. test_processing_orphan_never_enters_published
11. test_only_publication_gateway_can_transition_to_published
12. test_concurrent_producer_scheduler_cannot_corrupt_ready_inventory
13. test_stale_daemon_detects_version_mismatch
14. test_failed_publication_verification_preserves_asset
15. test_successful_publication_is_idempotent
16. test_previous_failure_is_not_erased_by_retry
17. test_attempt_ledger_records_every_attempt
18. test_attempt_ledger_records_every_failure_reason
19. test_retry_requires_corrective_logic
20. test_no_direct_published_move_exists_outside_gateway (AST Analysis)
"""

import ast
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, UploadRecord, Job, RenderedVideoRecord, ProductionAttemptRecord
from core.lifecycle_gateway import (
    vault_transition_to_published,
    is_valid_youtube_id,
    InvariantViolationError
)
from core.attempt_ledger import AttemptLedger, FailureCategory
from core.cloud_lock import CloudLockManager
from core.daemon_guard import DaemonIntegrityGuard, StaleDaemonError
from engines.deduplication_engine import DeduplicationRouter, StoryDeduplicationEngine
from engines.drive_engine import DriveVaultEngine
from main import ShortsPipeline, PROJECT_ROOT


class TestLifecycleNegativeInvariants(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.mock_drive = MagicMock(spec=DriveVaultEngine)
        self.mock_drive.move_file_in_vault.return_value = True
        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_123",
            "name": "short_job_123.mp4",
            "parents": ["02_PROCESSING"],
            "properties": {"job_id": "job_123"}
        }

        # Temp directory for DaemonIntegrityGuard tests
        self.temp_dir = tempfile.mkdtemp()
        self.sample_py = Path(self.temp_dir) / "main.py"
        self.sample_py.write_text("# Initial code", encoding="utf-8")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Zero un-uploaded Short can reach published
    def test_invariant_zero_unuploaded_short_can_reach_published(self):
        """Un-uploaded short with no YouTube video ID must NEVER reach 03_PUBLISHED."""
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_unuploaded_1",
                youtube_video_id=None,
                db=self.db,
                drive_engine=self.mock_drive
            )
        self.assertIn("Invalid or empty youtube_video_id", str(ctx.exception))

    # 2. Published requires authoritative YouTube ID format
    def test_published_requires_authoritative_youtube_id(self):
        """YouTube video ID must be valid 11-character base64 identifier."""
        invalid_ids = ["", "   ", "short", "invalid_id_longer_than_eleven", "invalid!@#$", "None", "null"]
        for invalid_id in invalid_ids:
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(InvariantViolationError):
                    vault_transition_to_published(
                        file_id="file_invalid_id",
                        youtube_video_id=invalid_id,
                        db=self.db,
                        drive_engine=self.mock_drive
                    )

    # 3. Published requires matching UploadRecord
    def test_published_requires_matching_upload_record(self):
        """Fails if no UploadRecord exists in SQLite for the video ID."""
        valid_id = "dQw4w9WgXcQ"
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_no_record",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive
            )
        self.assertIn("No authoritative UploadRecord found", str(ctx.exception))

    # 4. Published requires YouTube readback
    def test_published_requires_youtube_readback(self):
        """Fails if YouTube API read-back encounters an exception or fails."""
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_4",
            job_id="job_123",
            youtube_video_id=valid_id,
            title="Test Short 4",
            description="Test Description 4",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.side_effect = Exception("YouTube API 503 Backend Error")

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_123",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("read-back verification failed", str(ctx.exception))

    # 5. Private/scheduled video cannot enter published
    def test_private_scheduled_video_cannot_enter_published(self):
        """If YouTube API returns private/scheduled, transition must be refused."""
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_5",
            job_id="job_123",
            youtube_video_id=valid_id,
            title="Test Short 5",
            description="Test Description 5",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": valid_id,
                "status": {
                    "uploadStatus": "processed",
                    "privacyStatus": "private",
                    "publishAt": "2026-09-08T11:00:00Z"
                }
            }]
        }

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_123",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("NOT public (privacyStatus='private'", str(ctx.exception))

    # 6. Nonexistent YouTube video cannot enter published
    def test_nonexistent_youtube_video_cannot_enter_published(self):
        """If YouTube API returns empty items (404), transition must be refused."""
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_6",
            job_id="job_123",
            youtube_video_id=valid_id,
            title="Test Short 6",
            description="Test Description 6",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {"items": []}

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_123",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("DOES NOT EXIST on YouTube", str(ctx.exception))

    # 7. Title match does not prove publication
    def test_title_match_does_not_prove_publication(self):
        """Matching an older published title does not allow moving a new un-uploaded asset to 03_PUBLISHED."""
        rec = UploadRecord(
            id="upl_older_pub",
            job_id="job_older",
            title="The SS Ourang Medan Ghost Ship",
            description="Ghost ship mystery description",
            youtube_video_id="sd1TLvd08HM",
            status="PUBLISHED",
            privacy_status="public"
        )
        self.db.add(rec)
        self.db.commit()

        # A newly rendered file in 01_READY with same title but no youtube ID
        mock_candidate = {
            "id": "new_file_unuploaded",
            "name": "short_man_new123.mp4",
            "parents": ["01_READY"],
            "properties": {"title": "The SS Ourang Medan Ghost Ship"}
        }

        with self.assertRaises(InvariantViolationError):
            # Attempting to move file directly to 03_PUBLISHED must fail
            vault_transition_to_published(
                file_id=mock_candidate["id"],
                youtube_video_id="",
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 8. Duplicate ready asset never enters published
    @patch("main.CompositeLock")
    def test_duplicate_ready_asset_never_enters_published(self, mock_lock_cls):
        """When pre-claim dedup detects a story duplicate in 01_READY, it quarantines to 04_FAILED, never 03_PUBLISHED."""
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        # Prior published topic
        t_prior = Topic(
            id="top_prior_1",
            title="The Mystery of the Green Children of Woolpit",
            summary="Green children appeared in Woolpit speaking unknown language.",
            status="PUBLISHED"
        )
        self.db.add(t_prior)
        self.db.commit()

        # Candidate in 01_READY with duplicate story
        candidate_file = {
            "id": "file_dup_ready",
            "name": "short_man_dup.mp4",
            "properties": {
                "title": "The Mystery of the Green Children of Woolpit",
                "description": "Green children in Woolpit."
            }
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [candidate_file] if f == "01_READY" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        # Provide at least 1 vacant slot so scheduler enters processing loop
        future_slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        with patch("engines.upload_engine.UploadEngine.reconcile_scheduled_uploads", return_value=[]), \
             patch("engines.scheduler_engine.PublicationScheduler.get_vacant_slots_in_horizon", return_value=[future_slot]), \
             patch("engines.analytics_engine.AnalyticsEngine.run_feedback_loop", return_value=None):
            pipeline.schedule_ready_buffer(db=self.db)

        # Assert NEVER moved to 03_PUBLISHED
        for call_args in pipeline.drive_engine.move_file_in_vault.call_args_list:
            to_folder = call_args.kwargs.get("to_folder") or (call_args.args[2] if len(call_args.args) > 2 else None)
            self.assertNotEqual(to_folder, "03_PUBLISHED", "VIOLATION: Duplicate asset was moved to 03_PUBLISHED!")

        # Assert moved to 04_FAILED (quarantined)
        quarantine_calls = [
            call for call in pipeline.drive_engine.move_file_in_vault.call_args_list
            if (call.kwargs.get("to_folder") == "04_FAILED" or (len(call.args) > 2 and call.args[2] == "04_FAILED"))
        ]
        self.assertTrue(len(quarantine_calls) > 0, "Expected duplicate asset to be quarantined to 04_FAILED")

    # 9. Candidate cannot self match
    def test_candidate_cannot_self_match(self):
        """Candidate's own title and topic must not trigger duplicate rejection against itself."""
        title = "The Tunguska Cosmic Blast of 1908"
        t_self = Topic(
            id="top_tunguska_self",
            event_id="evt_tunguska_self",
            title=title,
            summary="Cosmic explosion in Siberia.",
            status="PRODUCED"
        )
        self.db.add(t_self)
        self.db.commit()

        router = DeduplicationRouter()
        res = router.evaluate_candidate(
            candidate_title=title,
            candidate_summary="Cosmic explosion in Siberia.",
            db=self.db,
            exclude_topic_id=t_self.id,
            exclude_title=title,
            exclude_event_id="evt_tunguska_self"
        )
        self.assertTrue(res.is_allowed, f"Candidate falsely self-matched: {res.reason}")

    # 10. Processing orphan never enters published
    @patch("main.CompositeLock")
    def test_processing_orphan_never_enters_published(self, mock_lock_cls):
        """Un-uploaded orphan in 02_PROCESSING is returned to 01_READY or quarantined, never 03_PUBLISHED."""
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        orphan_file = {
            "id": "file_orphan_proc",
            "name": "short_job_orphan.mp4",
            "properties": {"job_id": "job_orphan"}
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [orphan_file] if f == "02_PROCESSING" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        with patch("engines.upload_engine.UploadEngine.reconcile_scheduled_uploads", return_value=[]), \
             patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "Valid")), \
             patch("engines.scheduler_engine.PublicationScheduler.get_vacant_slots_in_horizon", return_value=[]), \
             patch("engines.analytics_engine.AnalyticsEngine.run_feedback_loop", return_value=None):
            pipeline.schedule_ready_buffer(db=self.db)

        for call_args in pipeline.drive_engine.move_file_in_vault.call_args_list:
            to_folder = call_args.kwargs.get("to_folder") or (call_args.args[2] if len(call_args.args) > 2 else None)
            self.assertNotEqual(to_folder, "03_PUBLISHED", "VIOLATION: Orphan in 02_PROCESSING moved to 03_PUBLISHED!")

        # Assert returned to 01_READY
        pipeline.drive_engine.move_file_in_vault.assert_called_with(
            "file_orphan_proc", from_folder="02_PROCESSING", to_folder="01_READY"
        )

    # 11. Only publication gateway can transition to published
    def test_only_publication_gateway_can_transition_to_published(self):
        """Direct call to move_file_in_vault with to_folder='03_PUBLISHED' without _from_gateway raises InvariantViolationError."""
        drive = DriveVaultEngine()
        with self.assertRaises(InvariantViolationError) as ctx:
            drive.move_file_in_vault("file_direct_hack", from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
        self.assertIn("HARD_BARRIER_VIOLATION", str(ctx.exception))

    # 12. Concurrent producer/scheduler lock conflict
    def test_concurrent_producer_scheduler_cannot_corrupt_ready_inventory(self):
        """When cloud_production is active, CloudLockManager for cloud_publisher refuses acquisition."""
        mock_drive = MagicMock()
        mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "sys_folder_id"}
        # Return an active cloud_production.lock file
        now_ts = datetime.now(timezone.utc).timestamp()
        mock_drive.list_files.return_value = [{
            "id": "prod_lock_id",
            "name": "cloud_production.lock",
            "properties": {"timestamp": str(now_ts), "run_id": "run_active_producer"}
        }]

        publisher_lock = CloudLockManager(
            drive_engine=mock_drive,
            lock_name="cloud_publisher",
            ttl_seconds=900.0
        )
        acquired = publisher_lock.acquire()
        self.assertFalse(acquired, "Publisher lock must refuse acquisition when cloud_production is active!")

    # 13. Stale daemon detects version mismatch
    def test_stale_daemon_detects_version_mismatch(self):
        """DaemonIntegrityGuard detects when codebase fingerprint changes on disk."""
        guard = DaemonIntegrityGuard(project_root=Path(self.temp_dir))
        # Initial check passes
        self.assertTrue(guard.verify_integrity()[0])

        # Modify a python file in project root
        test_py = Path(self.temp_dir) / "main.py"
        test_py.write_text("# Modified code on disk!", encoding="utf-8")

        is_valid, reason = guard.verify_integrity()
        self.assertFalse(is_valid)
        self.assertIn("Source code modified on disk since startup", reason)

        with self.assertRaises(StaleDaemonError):
            guard.enforce_integrity()

    # 14. Failed publication verification preserves asset
    def test_failed_publication_verification_preserves_asset(self):
        """If YouTube verification fails, asset remains in 02_PROCESSING without deletion."""
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_14",
            job_id="job_123",
            youtube_video_id=valid_id,
            title="Test Short 14",
            description="Test Description 14",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.side_effect = Exception("YouTube API Error")

        try:
            vault_transition_to_published(
                file_id="file_123",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        except InvariantViolationError:
            pass

        # Verify drive_engine.delete_file was NEVER called
        self.mock_drive.delete_file.assert_not_called()
        # Verify drive_engine.move_file_in_vault was NEVER called
        self.mock_drive.move_file_in_vault.assert_not_called()

    # 15. Successful publication is idempotent
    def test_successful_publication_is_idempotent(self):
        """Calling gateway on an already published file returns success cleanly."""
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_15",
            job_id="job_123",
            youtube_video_id=valid_id,
            title="Test Short 15",
            description="Test Description 15",
            status="PUBLISHED",
            privacy_status="public"
        )
        self.db.add(rec)
        self.db.commit()

        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_15",
            "parents": ["03_PUBLISHED"],
            "properties": {"youtube_video_id": valid_id, "job_id": "job_123"}
        }

        res = vault_transition_to_published(
            file_id="file_15",
            youtube_video_id=valid_id,
            db=self.db,
            drive_engine=self.mock_drive
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "ALREADY_PUBLISHED")

    # 16. Previous failure is not erased by retry
    def test_previous_failure_is_not_erased_by_retry(self):
        """AttemptLedger preserves all failed attempts when retry succeeds."""
        run_id = "run_ledger_16"
        # Attempt 1 fails
        att1 = AttemptLedger.start_attempt(
            db=self.db,
            run_id=run_id,
            stage="UPLOAD",
            operation="youtube.videos.insert",
            retry_number=0
        )
        AttemptLedger.record_failure(
            db=self.db,
            attempt=att1,
            error_type=FailureCategory.NETWORK_FAILURE.value,
            error_message="Socket timeout on chunk 3",
            root_cause="Transient network drop",
            recovery_action="Retry next cycle"
        )

        # Attempt 2 succeeds (recovered)
        att2 = AttemptLedger.start_attempt(
            db=self.db,
            run_id=run_id,
            stage="UPLOAD",
            operation="youtube.videos.insert",
            retry_number=1
        )
        AttemptLedger.record_success(
            db=self.db,
            attempt=att2,
            related_youtube_video_id="dQw4w9WgXcQ"
        )

        records = self.db.query(ProductionAttemptRecord).filter_by(run_id=run_id).order_by(ProductionAttemptRecord.retry_number).all()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].status, "FAILED")
        self.assertEqual(records[1].status, "RECOVERED")
        self.assertTrue(records[1].recovered)

    # 17. Attempt ledger records every attempt
    def test_attempt_ledger_records_every_attempt(self):
        """Every attempt produces a unique attempt record with distinct retry_number."""
        run_id = "run_multi_17"
        for i in range(3):
            att = AttemptLedger.start_attempt(
                db=self.db,
                run_id=run_id,
                stage="RENDER",
                operation=f"render_beat_{i}",
                retry_number=i
            )
            self.assertEqual(att.retry_number, i)

        count = self.db.query(ProductionAttemptRecord).filter_by(run_id=run_id).count()
        self.assertEqual(count, 3)

    # 18. Attempt ledger records every failure reason
    def test_attempt_ledger_records_every_failure_reason(self):
        """Failure reasons and categories are stored accurately."""
        run_id = "run_reason_18"
        att = AttemptLedger.start_attempt(
            db=self.db,
            run_id=run_id,
            stage="QA",
            operation="audio_qa_check",
            retry_number=0
        )
        AttemptLedger.record_failure(
            db=self.db,
            attempt=att,
            error_type=FailureCategory.QA_FAILURE.value,
            error_message="Audio silence gap exceeds 350ms threshold",
            root_cause="TTS pause calibration failure",
            recovery_action="Regenerate speech with tight pauses"
        )

        rec = self.db.query(ProductionAttemptRecord).filter_by(run_id=run_id).first()
        self.assertEqual(rec.error_type, FailureCategory.QA_FAILURE.value)
        self.assertEqual(rec.error_message, "Audio silence gap exceeds 350ms threshold")
        self.assertEqual(rec.root_cause, "TTS pause calibration failure")

    # 19. Retry requires corrective logic
    def test_retry_requires_corrective_logic(self):
        """AttemptLedger records explicit recovery action for failed operations."""
        run_id = "run_corrective_19"
        att = AttemptLedger.start_attempt(
            db=self.db,
            run_id=run_id,
            stage="UPLOAD",
            operation="schedule_slot",
            retry_number=0
        )
        AttemptLedger.record_failure(
            db=self.db,
            attempt=att,
            error_type=FailureCategory.QUOTA_FAILURE.value,
            error_message="Quota exceeded",
            root_cause="YouTube quota limit",
            recovery_action="Wait for next quota reset window and back off"
        )
        self.assertIsNotNone(att.recovery_action)
        self.assertIn("Wait for next quota reset", att.recovery_action)

    # 20. AST Static Analysis: No direct published move exists outside gateway
    def test_no_direct_published_move_exists_outside_gateway(self):
        """AST scans entire repository to verify that NO move_file_in_vault with 03_PUBLISHED exists outside gateway."""
        violating_call_sites = []
        exclude_dirs = {".git", "__pycache__", "venv", ".venv", "tests", "scratch"}

        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                if f.endswith(".py"):
                    fpath = Path(root) / f
                    rel_path = fpath.relative_to(PROJECT_ROOT)
                    # Exclude the gateway itself
                    if str(rel_path) in [r"core\lifecycle_gateway.py", "core/lifecycle_gateway.py"]:
                        continue

                    try:
                        tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(rel_path))
                    except Exception:
                        continue

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            func_name = ""
                            if isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr
                            elif isinstance(node.func, ast.Name):
                                func_name = node.func.id

                            if func_name == "move_file_in_vault":
                                # Check arguments
                                is_to_published = False
                                for arg in node.args:
                                    if isinstance(arg, ast.Constant) and arg.value == "03_PUBLISHED":
                                        is_to_published = True
                                for kw in node.keywords:
                                    if kw.arg == "to_folder" and isinstance(kw.value, ast.Constant) and kw.value.value == "03_PUBLISHED":
                                        is_to_published = True

                                if is_to_published:
                                    violating_call_sites.append(f"{rel_path}:{node.lineno}")

        self.assertEqual(
            violating_call_sites,
            [],
            f"STRUCTURAL VIOLATION: Direct move_file_in_vault to 03_PUBLISHED found at: {violating_call_sites}. "
            "All moves must be routed exclusively through vault_transition_to_published in core/lifecycle_gateway.py!"
        )


if __name__ == "__main__":
    unittest.main()
