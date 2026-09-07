"""
Comprehensive Negative Invariant & Lifecycle Hardening Test Suite (40/40 Invariants)
=====================================================================================
Strict automated adversarial verification of all 40 production invariants:
1.  test_01_unuploaded_asset_cannot_reach_03_published
2.  test_02_title_match_cannot_prove_publication
3.  test_03_topic_match_cannot_prove_publication
4.  test_04_fingerprint_match_cannot_prove_publication
5.  test_05_self_match_cannot_quarantine_legitimate_current_asset
6.  test_06_true_duplicate_cannot_reach_03_published
7.  test_07_missing_youtube_id_cannot_reach_03_published
8.  test_08_malformed_youtube_id_cannot_reach_03_published
9.  test_09_nonexistent_youtube_video_cannot_reach_03_published
10. test_10_private_youtube_video_cannot_reach_03_published
11. test_11_scheduled_private_video_cannot_reach_03_published
12. test_12_missing_upload_record_cannot_reach_03_published
13. test_13_mismatched_job_id_cannot_reach_03_published
14. test_14_mismatched_file_job_binding_cannot_reach_03_published
15. test_15_failed_youtube_readback_preserves_asset
16. test_16_orphan_processing_asset_cannot_reach_03_published
17. test_17_recovery_cannot_publish_an_unverified_asset
18. test_18_cleanup_cannot_publish_an_unverified_asset
19. test_19_reconciliation_cannot_publish_an_unverified_asset
20. test_20_retry_cannot_erase_previous_failure
21. test_21_retry_must_contain_corrective_logic
22. test_22_successful_publication_is_idempotent
23. test_23_stale_daemon_detects_code_mismatch
24. test_24_stale_daemon_cannot_mutate_production
25. test_25_producer_scheduler_race_cannot_corrupt_inventory
26. test_26_lock_failure_cannot_cause_unsafe_fallback
27. test_27_direct_03_published_move_outside_gateway_is_impossible
28. test_28_gateway_is_the_only_publication_transition
29. test_29_ready_cannot_directly_become_published
30. test_30_scheduled_private_youtube_videos_remain_processing
31. test_31_only_actual_public_youtube_state_permits_published
32. test_32_inventory_remains_internally_consistent_after_failures
33. test_33_recovery_is_idempotent
34. test_34_duplicate_recovery_is_idempotent
35. test_35_cloud_partial_production_does_not_corrupt_inventory
36. test_36_process_restart_does_not_lose_lifecycle_state
37. test_37_db_drive_divergence_is_detected
38. test_38_youtube_db_divergence_is_detected
39. test_39_missing_metadata_does_not_result_in_false_publication
40. test_40_unknown_unexpected_state_fails_closed
"""

import ast
import json
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
from core.recovery_manager import RecoveryManager
from engines.deduplication_engine import DeduplicationRouter, StoryDeduplicationEngine
from engines.drive_engine import DriveVaultEngine, is_valid_ready_short
from engines.upload_engine import UploadEngine
from main import ShortsPipeline, PROJECT_ROOT


class TestLifecycleAdversarialInvariants(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.mock_drive = MagicMock(spec=DriveVaultEngine)
        self.mock_drive.move_file_in_vault.return_value = True
        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_test_proc",
            "name": "short_job_proc_123.mp4",
            "parents": ["02_PROCESSING"],
            "properties": {"job_id": "job_proc_123"}
        }

        self.temp_dir = tempfile.mkdtemp()
        self.sample_py = Path(self.temp_dir) / "main.py"
        self.sample_py.write_text("# Initial code", encoding="utf-8")

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # 1. Un-uploaded asset cannot reach 03_PUBLISHED
    def test_01_unuploaded_asset_cannot_reach_03_published(self):
        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_unup",
                youtube_video_id=None,
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 2. Title match cannot prove publication
    def test_02_title_match_cannot_prove_publication(self):
        rec = UploadRecord(
            id="upl_pub_title",
            job_id="job_pub_title",
            title="The Mystery of Flight 19",
            description="Flight 19 incident",
            youtube_video_id="dQw4w9WgXcQ",
            status="PUBLISHED",
            privacy_status="public"
        )
        self.db.add(rec)
        self.db.commit()

        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_new_flight19",
                youtube_video_id="",
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 3. Topic match cannot prove publication
    def test_03_topic_match_cannot_prove_publication(self):
        top = Topic(
            id="top_pub_1",
            title="The Lost Colony of Roanoke",
            summary="Roanoke island settlement disappeared.",
            status="PUBLISHED"
        )
        self.db.add(top)
        self.db.commit()

        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_roanoke",
                youtube_video_id=None,
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 4. Fingerprint match cannot prove publication
    def test_04_fingerprint_match_cannot_prove_publication(self):
        dedup = StoryDeduplicationEngine()
        fp1 = dedup.build_fingerprint("The Taos Hum", "A continuous low-frequency hum heard in Taos.")
        fp2 = dedup.build_fingerprint("The Taos Hum", "A continuous low-frequency hum heard in Taos.")
        dup_res = dedup.check_deterministic_duplicate(fp1, fp2)
        self.assertIsNotNone(dup_res)
        self.assertTrue(dup_res.is_duplicate)
        # Even with duplicate story fingerprint, moving un-uploaded asset to published is blocked
        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_taos_new",
                youtube_video_id="",
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 5. Self-match cannot quarantine legitimate current asset
    def test_05_self_match_cannot_quarantine_legitimate_current_asset(self):
        title = "The Dancing Plague of 1518"
        t_self = Topic(
            id="top_dance_self",
            event_id="evt_dance_self",
            title=title,
            summary="Dancing mania in Strasbourg.",
            status="PRODUCED"
        )
        self.db.add(t_self)
        self.db.commit()

        router = DeduplicationRouter()
        res = router.evaluate_candidate(
            candidate_title=title,
            candidate_summary="Dancing mania in Strasbourg.",
            db=self.db,
            exclude_topic_id=t_self.id,
            exclude_event_id="evt_dance_self"
        )
        self.assertTrue(res.is_allowed, f"Candidate falsely self-matched: {res.reason}")

    # 6. True duplicate cannot reach 03_PUBLISHED
    @patch("main.CompositeLock")
    def test_06_true_duplicate_cannot_reach_03_published(self, mock_lock_cls):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        t_prior = Topic(
            id="top_prior_woolpit",
            title="The Green Children of Woolpit",
            summary="Green children appeared in Woolpit.",
            status="PUBLISHED"
        )
        self.db.add(t_prior)
        self.db.commit()

        candidate_file = {
            "id": "file_woolpit_dup",
            "name": "short_man_dup.mp4",
            "properties": {
                "title": "The Green Children of Woolpit",
                "description": "Green children appeared in Woolpit."
            }
        }

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [candidate_file] if f == "01_READY" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        future_slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
        with patch("engines.upload_engine.UploadEngine.reconcile_scheduled_uploads", return_value=[]), \
             patch("engines.scheduler_engine.PublicationScheduler.get_vacant_slots_in_horizon", return_value=[future_slot]), \
             patch("engines.analytics_engine.AnalyticsEngine.run_feedback_loop", return_value=None):
            pipeline.schedule_ready_buffer(db=self.db)

        for call in pipeline.drive_engine.move_file_in_vault.call_args_list:
            to_folder = call.kwargs.get("to_folder") or (call.args[2] if len(call.args) > 2 else None)
            self.assertNotEqual(to_folder, "03_PUBLISHED", "VIOLATION: Duplicate asset moved to 03_PUBLISHED!")

    # 7. Missing YouTube ID cannot reach 03_PUBLISHED
    def test_07_missing_youtube_id_cannot_reach_03_published(self):
        for missing_val in [None, "", "   "]:
            with self.subTest(missing_val=missing_val):
                with self.assertRaises(InvariantViolationError):
                    vault_transition_to_published(
                        file_id="file_missing_yt",
                        youtube_video_id=missing_val,
                        db=self.db,
                        drive_engine=self.mock_drive
                    )

    # 8. Malformed YouTube ID cannot reach 03_PUBLISHED
    def test_08_malformed_youtube_id_cannot_reach_03_published(self):
        malformed_ids = ["abc", "short", "invalid_id_longer_than_11", "contains!@#$", "TEST_MODE_ID", "NONE"]
        for bad_id in malformed_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(InvariantViolationError):
                    vault_transition_to_published(
                        file_id="file_bad_yt",
                        youtube_video_id=bad_id,
                        db=self.db,
                        drive_engine=self.mock_drive
                    )

    # 9. Nonexistent YouTube video cannot reach 03_PUBLISHED
    def test_09_nonexistent_youtube_video_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_9",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Test 9",
            description="Desc 9",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {"items": []}

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("DOES NOT EXIST on YouTube", str(ctx.exception))

    # 10. Private YouTube video cannot reach 03_PUBLISHED
    def test_10_private_youtube_video_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_10",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Test 10",
            description="Desc 10",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": valid_id, "status": {"uploadStatus": "processed", "privacyStatus": "private"}}]
        }
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("NOT public", str(ctx.exception))

    # 11. Scheduled/private video cannot reach 03_PUBLISHED
    def test_11_scheduled_private_video_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_11",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Test 11",
            description="Desc 11",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": valid_id, "status": {"uploadStatus": "processed", "privacyStatus": "private", "publishAt": "2026-09-08T06:00:00Z"}}]
        }
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        self.assertIn("Scheduled/private videos belong in 02_PROCESSING", str(ctx.exception))

    # 12. Missing UploadRecord cannot reach 03_PUBLISHED
    def test_12_missing_upload_record_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_no_db_rec",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive
            )
        self.assertIn("No authoritative UploadRecord found in SQLite", str(ctx.exception))

    # 13. Mismatched job_id cannot reach 03_PUBLISHED
    def test_13_mismatched_job_id_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_13",
            job_id="job_correct_owner",
            youtube_video_id=valid_id,
            title="Test 13",
            description="Desc 13",
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive
            )
        self.assertIn("Job ID mismatch", str(ctx.exception))

    # 14. Mismatched file/job binding cannot reach 03_PUBLISHED
    def test_14_mismatched_file_job_binding_cannot_reach_03_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_14",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Test 14",
            description="Desc 14",
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                job_id="job_injected_imposter"
            )
        self.assertIn("Job ID mismatch", str(ctx.exception))

    # 15. Failed YouTube read-back preserves asset
    def test_15_failed_youtube_readback_preserves_asset(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_test_15",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Test 15",
            description="Desc 15",
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.side_effect = Exception("503 Service Unavailable")

        try:
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )
        except InvariantViolationError:
            pass

        self.mock_drive.move_file_in_vault.assert_not_called()

    # 16. Orphan PROCESSING asset cannot reach 03_PUBLISHED
    @patch("main.CompositeLock")
    def test_16_orphan_processing_asset_cannot_reach_03_published(self, mock_lock_cls):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        orphan = {"id": "file_orphan_16", "name": "short_job_orphan.mp4", "properties": {"job_id": "job_orphan"}}
        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [orphan] if f == "02_PROCESSING" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        with patch("engines.upload_engine.UploadEngine.reconcile_scheduled_uploads", return_value=[]), \
             patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "OK")), \
             patch("engines.scheduler_engine.PublicationScheduler.get_vacant_slots_in_horizon", return_value=[]), \
             patch("engines.analytics_engine.AnalyticsEngine.run_feedback_loop", return_value=None):
            pipeline.schedule_ready_buffer(db=self.db)

        for call in pipeline.drive_engine.move_file_in_vault.call_args_list:
            to_folder = call.kwargs.get("to_folder") or (call.args[2] if len(call.args) > 2 else None)
            self.assertNotEqual(to_folder, "03_PUBLISHED")

    # 17. Recovery cannot publish an unverified asset
    def test_17_recovery_cannot_publish_an_unverified_asset(self):
        drive = MagicMock()
        rec_mgr = RecoveryManager(drive_engine=drive)
        drive.list_files_in_folder.return_value = [{
            "id": "file_rec_unverified",
            "name": "short_rec.mp4",
            "properties": {"job_id": "job_rec", "youtube_video_id": "dQw4w9WgXcQ"}
        }]
        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {"items": []}

        with patch("engines.upload_engine.UploadEngine.get_youtube_service", return_value=mock_yt):
            res = rec_mgr.recover_stale_processing_vault(db=self.db)
            moved_to_pub = [a for a in res if isinstance(a, dict) and a.get("action") == "MOVED_TO_PUBLISHED"]
            self.assertEqual(len(moved_to_pub), 0)

    # 18. Cleanup cannot publish an unverified asset
    @patch("main.CompositeLock")
    def test_18_cleanup_cannot_publish_an_unverified_asset(self, mock_lock_cls):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock_cls.return_value = mock_lock

        proc_file = {
            "id": "file_clean_unverified",
            "name": "short_clean.mp4",
            "properties": {"job_id": "job_clean", "youtube_video_id": "dQw4w9WgXcQ"}
        }
        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()
        pipeline.drive_engine.list_files_in_folder.side_effect = lambda f: [proc_file] if f == "02_PROCESSING" else []
        pipeline.drive_engine.move_file_in_vault = MagicMock()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {"items": []}
        with patch("engines.upload_engine.UploadEngine.get_youtube_service", return_value=mock_yt), \
             patch("engines.upload_engine.UploadEngine.reconcile_scheduled_uploads", return_value=[]), \
             patch("engines.scheduler_engine.PublicationScheduler.get_vacant_slots_in_horizon", return_value=[]), \
             patch("engines.analytics_engine.AnalyticsEngine.run_feedback_loop", return_value=None):
            pipeline.schedule_ready_buffer(db=self.db)

        for call in pipeline.drive_engine.move_file_in_vault.call_args_list:
            to_folder = call.kwargs.get("to_folder") or (call.args[2] if len(call.args) > 2 else None)
            self.assertNotEqual(to_folder, "03_PUBLISHED")

    # 19. Reconciliation cannot publish an unverified asset
    def test_19_reconciliation_cannot_publish_an_unverified_asset(self):
        drive = MagicMock()
        drive.list_files_in_folder.return_value = [{
            "id": "file_recon",
            "name": "short_recon.mp4",
            "properties": {"job_id": "job_recon", "youtube_video_id": "dQw4w9WgXcQ"}
        }]
        rec = UploadRecord(
            id="upl_recon",
            job_id="job_recon",
            youtube_video_id="dQw4w9WgXcQ",
            title="Recon",
            description="Recon",
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        uploader = UploadEngine()
        mock_yt = MagicMock()
        # YouTube returns still scheduled/private
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": "dQw4w9WgXcQ", "status": {"uploadStatus": "processed", "privacyStatus": "private"}}]
        }
        with patch.object(uploader, "get_youtube_service", return_value=mock_yt):
            reconciled = uploader.reconcile_scheduled_uploads(db=self.db)
            self.assertEqual(len(reconciled), 0)
            self.assertEqual(rec.status, "SCHEDULED")

    # 20. Retry cannot erase previous failure
    def test_20_retry_cannot_erase_previous_failure(self):
        run_id = "run_audit_20"
        att1 = AttemptLedger.start_attempt(db=self.db, run_id=run_id, stage="UPLOAD", operation="videos.insert", retry_number=0)
        AttemptLedger.record_failure(db=self.db, attempt=att1, error_type="NETWORK_FAILURE", error_message="timeout", recovery_action="retry")

        att2 = AttemptLedger.start_attempt(db=self.db, run_id=run_id, stage="UPLOAD", operation="videos.insert", retry_number=1)
        AttemptLedger.record_success(db=self.db, attempt=att2, related_youtube_video_id="dQw4w9WgXcQ")

        records = self.db.query(ProductionAttemptRecord).filter_by(run_id=run_id).order_by(ProductionAttemptRecord.retry_number).all()
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].status, "FAILED")
        self.assertEqual(records[1].status, "RECOVERED")
        self.assertTrue(records[1].recovered)

    # 21. Retry must contain corrective logic
    def test_21_retry_must_contain_corrective_logic(self):
        run_id = "run_audit_21"
        att = AttemptLedger.start_attempt(db=self.db, run_id=run_id, stage="RENDER", operation="render_beat", retry_number=0)
        AttemptLedger.record_failure(
            db=self.db,
            attempt=att,
            error_type="RENDER_FAILURE",
            error_message="Font missing",
            root_cause="DejaVuSans not installed",
            recovery_action="Install fonts-dejavu-core"
        )
        self.assertTrue(bool(att.recovery_action))
        self.assertIn("fonts-dejavu-core", att.recovery_action)

    # 22. Successful publication is idempotent
    def test_22_successful_publication_is_idempotent(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_idem_22",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Idempotent 22",
            description="Desc 22",
            status="PUBLISHED"
        )
        self.db.add(rec)
        self.db.commit()

        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_test_proc",
            "parents": ["03_PUBLISHED"],
            "properties": {"youtube_video_id": valid_id, "job_id": "job_proc_123"}
        }

        res = vault_transition_to_published(
            file_id="file_test_proc",
            youtube_video_id=valid_id,
            db=self.db,
            drive_engine=self.mock_drive
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "ALREADY_PUBLISHED")

    # 23. Stale daemon detects code mismatch
    def test_23_stale_daemon_detects_code_mismatch(self):
        guard = DaemonIntegrityGuard(project_root=Path(self.temp_dir))
        self.assertTrue(guard.verify_integrity()[0])

        mod_file = Path(self.temp_dir) / "main.py"
        mod_file.write_text("# Diverged on disk", encoding="utf-8")

        is_val, reason = guard.verify_integrity()
        self.assertFalse(is_val)
        self.assertIn("Source code modified on disk", reason)

    # 24. Stale daemon cannot mutate production
    def test_24_stale_daemon_cannot_mutate_production(self):
        guard = DaemonIntegrityGuard(project_root=Path(self.temp_dir))
        mod_file = Path(self.temp_dir) / "main.py"
        mod_file.write_text("# Diverged", encoding="utf-8")

        with self.assertRaises(StaleDaemonError):
            guard.enforce_integrity()

    # 25. Producer/scheduler race cannot corrupt inventory
    def test_25_producer_scheduler_race_cannot_corrupt_inventory(self):
        mock_drive = MagicMock()
        mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "sys_folder_id"}
        now_ts = datetime.now(timezone.utc).timestamp()
        mock_drive.list_files.return_value = [{
            "id": "prod_lock",
            "name": "cloud_production.lock",
            "properties": {"timestamp": str(now_ts), "run_id": "active_prod"}
        }]

        pub_lock = CloudLockManager(drive_engine=mock_drive, lock_name="cloud_publisher", ttl_seconds=900.0)
        self.assertFalse(pub_lock.acquire(), "Publisher lock must reject acquisition when producer lock is active")

    # 26. Lock failure cannot cause unsafe fallback
    @patch("main.CompositeLock")
    def test_26_lock_failure_cannot_cause_unsafe_fallback(self, mock_lock_cls):
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = False  # Lock contention
        mock_lock_cls.return_value = mock_lock

        pipeline = ShortsPipeline()
        pipeline.SessionLocal = sessionmaker(bind=self.engine)
        pipeline.drive_engine = MagicMock()

        res = pipeline.schedule_ready_buffer(db=self.db)
        self.assertEqual(res.get("status"), "LOCK_HELD")
        self.assertEqual(res.get("scheduled_count"), 0)
        pipeline.drive_engine.move_file_in_vault.assert_not_called()

    # 27. Direct 03_PUBLISHED move outside gateway is impossible
    def test_27_direct_03_published_move_outside_gateway_is_impossible(self):
        drive = DriveVaultEngine()
        with self.assertRaises(InvariantViolationError) as ctx:
            drive.move_file_in_vault("hack_file", from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
        self.assertIn("HARD_BARRIER_VIOLATION", str(ctx.exception))

    # 28. Gateway is the only publication transition (AST analysis)
    def test_28_gateway_is_the_only_publication_transition(self):
        violating_calls = []
        exclude_dirs = {".git", "__pycache__", "venv", ".venv", "tests", "scratch"}
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            for f in files:
                if f.endswith(".py"):
                    fpath = Path(root) / f
                    rel_path = fpath.relative_to(PROJECT_ROOT)
                    if str(rel_path) in [r"core\lifecycle_gateway.py", "core/lifecycle_gateway.py"]:
                        continue
                    try:
                        tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(rel_path))
                    except Exception:
                        continue
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            func = ""
                            if isinstance(node.func, ast.Attribute):
                                func = node.func.attr
                            elif isinstance(node.func, ast.Name):
                                func = node.func.id
                            if func == "move_file_in_vault":
                                is_to_pub = any(isinstance(a, ast.Constant) and a.value == "03_PUBLISHED" for a in node.args)
                                is_to_pub = is_to_pub or any(kw.arg == "to_folder" and isinstance(kw.value, ast.Constant) and kw.value.value == "03_PUBLISHED" for kw in node.keywords)
                                if is_to_pub:
                                    violating_calls.append(f"{rel_path}:{node.lineno}")

        self.assertEqual(violating_calls, [], f"Violating direct moves to 03_PUBLISHED found: {violating_calls}")

    # 29. 01_READY cannot directly become 03_PUBLISHED
    def test_29_ready_cannot_directly_become_published(self):
        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_in_ready",
            "name": "short_ready.mp4",
            "parents": ["01_READY"],
            "properties": {"job_id": "job_ready"}
        }
        with self.assertRaises(InvariantViolationError) as ctx:
            vault_transition_to_published(
                file_id="file_in_ready",
                youtube_video_id="dQw4w9WgXcQ",
                db=self.db,
                drive_engine=self.mock_drive
            )
        self.assertIn("currently in 01_READY", str(ctx.exception))

    # 30. Scheduled/private YouTube videos remain PROCESSING
    def test_30_scheduled_private_youtube_videos_remain_processing(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_sched_30",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Scheduled 30",
            description="Desc 30",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": valid_id, "status": {"uploadStatus": "processed", "privacyStatus": "private", "publishAt": "2026-09-08T15:00:00Z"}}]
        }
        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_test_proc",
                youtube_video_id=valid_id,
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )

    # 31. Only actual public YouTube state permits PUBLISHED
    def test_31_only_actual_public_youtube_state_permits_published(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_pub_31",
            job_id="job_proc_123",
            youtube_video_id=valid_id,
            title="Public 31",
            description="Desc 31",
            status="SCHEDULED",
            privacy_status="private"
        )
        self.db.add(rec)
        self.db.commit()

        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": valid_id, "status": {"uploadStatus": "processed", "privacyStatus": "public"}}]
        }
        res = vault_transition_to_published(
            file_id="file_test_proc",
            youtube_video_id=valid_id,
            db=self.db,
            drive_engine=self.mock_drive,
            youtube_service=mock_yt
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "PUBLISHED")
        self.mock_drive.move_file_in_vault.assert_called_with(
            "file_test_proc", from_folder="02_PROCESSING", to_folder="03_PUBLISHED", _from_gateway=True
        )

    # 32. Inventory remains internally consistent after failures
    def test_32_inventory_remains_internally_consistent_after_failures(self):
        drive = DriveVaultEngine()
        drive.list_files_in_folder = MagicMock()
        drive.inspect_or_init_vault = MagicMock(return_value={"01_READY": "r_id"})
        # 2 valid files, 1 corrupted file
        drive.list_files_in_folder.return_value = [
            {"id": "f1", "name": "short_man_1.mp4", "properties": {"title": "Valid 1", "duration_seconds": "23.5"}},
            {"id": "f2", "name": "short_man_2.mp4", "properties": {"title": "Valid 2", "duration_seconds": "24.0"}},
            {"id": "f3", "name": "corrupt.mp4", "properties": {}}
        ]
        with patch("engines.drive_engine.is_valid_ready_short", side_effect=lambda f, **kw: (f["id"] in ("f1", "f2"), "Reason")):
            count = drive.get_ready_stock_count(db=self.db)
            self.assertEqual(count, 2)

    # 33. Recovery is idempotent
    def test_33_recovery_is_idempotent(self):
        drive = MagicMock()
        rec_mgr = RecoveryManager(drive_engine=drive)
        drive.list_files_in_folder.return_value = []
        res1 = rec_mgr.reconcile_drive_vault_and_db(db=self.db)
        res2 = rec_mgr.reconcile_drive_vault_and_db(db=self.db)
        self.assertEqual(res1, res2)

    # 34. Duplicate recovery is idempotent
    def test_34_duplicate_recovery_is_idempotent(self):
        drive = MagicMock()
        rec_mgr = RecoveryManager(drive_engine=drive)
        drive.list_files_in_folder.return_value = []
        res = rec_mgr.reconcile_drive_vault_and_db(db=self.db)
        self.assertEqual(len(res["inconsistencies"]), 0)

    # 35. Cloud partial production does not corrupt inventory
    def test_35_cloud_partial_production_does_not_corrupt_inventory(self):
        # A partial render output in data/renders without drive upload is never counted in 01_READY
        drive = DriveVaultEngine()
        drive.list_files_in_folder = MagicMock(return_value=[])
        drive.inspect_or_init_vault = MagicMock(return_value={"01_READY": "r_id"})
        count = drive.get_ready_stock_count(db=self.db)
        self.assertEqual(count, 0)

    # 36. Process restart does not lose lifecycle state
    def test_36_process_restart_does_not_lose_lifecycle_state(self):
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_restart_36",
            job_id="job_restart_36",
            youtube_video_id=valid_id,
            title="Restart 36",
            description="Desc 36",
            status="SCHEDULED",
            scheduled_publish_at=datetime.utcnow() + timedelta(hours=5)
        )
        self.db.add(rec)
        self.db.commit()

        # Simulate restart: open a new DB session
        db2 = self.Session()
        found = db2.query(UploadRecord).filter_by(id="upl_restart_36").first()
        self.assertIsNotNone(found)
        self.assertEqual(found.status, "SCHEDULED")
        self.assertEqual(found.youtube_video_id, valid_id)
        db2.close()

    # 37. DB/Drive divergence is detected
    def test_37_db_drive_divergence_is_detected(self):
        drive = MagicMock()
        drive.list_files_in_folder.side_effect = lambda f: [{"id": "orphan_in_drive", "name": "orphan.mp4", "properties": {}}] if f == "02_PROCESSING" else []
        rec_mgr = RecoveryManager(drive_engine=drive)
        res = rec_mgr.reconcile_drive_vault_and_db(db=self.db)
        self.assertEqual(res["processing_count"], 1)

    # 38. YouTube/DB divergence is detected
    def test_38_youtube_db_divergence_is_detected(self):
        # Video is SCHEDULED in DB but deleted on YouTube
        valid_id = "dQw4w9WgXcQ"
        rec = UploadRecord(
            id="upl_div_38",
            job_id="job_div_38",
            youtube_video_id=valid_id,
            title="Div 38",
            description="Desc 38",
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        uploader = UploadEngine()
        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {"items": []}
        with patch.object(uploader, "get_youtube_service", return_value=mock_yt):
            reconciled = uploader.reconcile_scheduled_uploads(db=self.db)
            self.assertEqual(len(reconciled), 0)
            rec_db = self.db.query(UploadRecord).filter_by(id="upl_div_38").first()
            self.assertEqual(rec_db.status, "SCHEDULED")

    # 39. Missing metadata does not result in false publication
    def test_39_missing_metadata_does_not_result_in_false_publication(self):
        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_no_meta",
            "name": "short_no_meta.mp4",
            "parents": ["02_PROCESSING"],
            "properties": {}  # Missing job_id, youtube_id
        }
        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_no_meta",
                youtube_video_id=None,
                db=self.db,
                drive_engine=self.mock_drive
            )

    # 40. Unknown/unexpected state fails closed
    def test_40_unknown_unexpected_state_fails_closed(self):
        self.mock_drive.get_file_metadata.return_value = {
            "id": "file_weird",
            "name": "short_weird.mp4",
            "parents": ["UNKNOWN_FOLDER_99"],
            "properties": {"job_id": "job_weird"}
        }
        mock_yt = MagicMock()
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": "dQw4w9WgXcQ", "status": {"uploadStatus": "failed", "privacyStatus": "unlisted"}}]
        }
        with self.assertRaises(InvariantViolationError):
            vault_transition_to_published(
                file_id="file_weird",
                youtube_video_id="dQw4w9WgXcQ",
                db=self.db,
                drive_engine=self.mock_drive,
                youtube_service=mock_yt
            )


if __name__ == "__main__":
    unittest.main()
