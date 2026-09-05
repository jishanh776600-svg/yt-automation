"""
Targeted Test Suite for AL-AMR Step 7: Controlled Live-Cloud Canary.

Covers:
  1. Explicit opt-in requirement (canary_mode=True).
  2. Strictly bounded single production job (no batching).
  3. Prohibits automatic refill after canary.
  4. Pre-flight safety gate rejections (queue paused, safe mode, provider exhaustion, daily limits).
  5. Clean lock release on preflight failure or error.
  6. Canary cannot be re-run in same session (canary consumed gate).
  7. Idempotent crash recovery (resumes in-flight job without duplicate creation).
  8. Cloud confirmation requirement (validates deposit in 01_READY before claiming success).
  9. Prohibits automatic YouTube publishing (ends in 01_READY, allow_youtube_write=False).
  10. Full audit logging and Mission Control telemetry capture.
  11. AST niche-agnostic architectural compliance (zero hardcoded niche conditionals).
"""
import ast
import json
import os
import shutil
import time
import unittest
import uuid
from datetime import datetime, date, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.constants import DAILY_SHORTS_LIMIT, JobState
from config.settings import PROJECT_ROOT, LOCKS_DIR
from core.database import SessionLocal
from core.models import Job, Topic, UploadRecord, ScriptRecord, RenderOutput
from core.content_profile import get_active_profile
from core.discovery_profile import get_active_discovery_profile
from engines.drive_engine import DriveVaultEngine
from engines.orchestrator import ProductionOrchestrator, ExecutionCapabilities, ProductionJobReport, StageResult, STATE_RANK
from engines.scheduler_engine import PublicationScheduler
from runtime.config import RuntimeConfig
from runtime.service import AutonomousRuntimeService, PreflightGateError
from dashboard.mission_control_service import mission_control_service


class TestControlledLiveCanary(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_locks_dir = LOCKS_DIR
        cls.test_locks_dir.mkdir(parents=True, exist_ok=True)
        mission_control_service.resume_queue(reason="Step 7 Canary Test Setup")

    def setUp(self):
        self.db = SessionLocal()
        self.config = RuntimeConfig(
            enabled=True,
            interval_sec=10.0,
            target_buffer_stock=6,
            max_batch_size=1,
            dry_run=True,
            canary_mode=True,
            state_file_path=self.test_locks_dir / "step7_test_canary_state.json"
        )
        self.caps = ExecutionCapabilities.sandboxed_testing()
        self.orchestrator = ProductionOrchestrator(
            content_profile=get_active_profile(),
            discovery_profile=get_active_discovery_profile(),
            capabilities=self.caps,
            max_retries=2
        )
        self.service = AutonomousRuntimeService(
            config=self.config,
            orchestrator=self.orchestrator
        )
        self.service.lock.release()
        mission_control_service.resume_queue(reason="Test setup")

        # Clean residual in-flight jobs to ensure strict test isolation
        in_flight_states = [
            s for s in STATE_RANK.keys()
            if s not in [
                JobState.PUBLISHED.value,
                JobState.FAILED.value,
                JobState.NEEDS_REVIEW.value,
                JobState.QUEUED.value,
                JobState.READY_TO_UPLOAD.value,
                JobState.SCHEDULED.value,
            ]
        ]
        self.db.query(Job).filter(Job.state.in_(in_flight_states)).update(
            {"state": JobState.NEEDS_REVIEW.value}, synchronize_session=False
        )
        self.db.commit()

    def tearDown(self):
        self.service.lock.release()
        # Clean up any jobs created during test
        in_flight_states = [
            s for s in STATE_RANK.keys()
            if s not in [
                JobState.PUBLISHED.value,
                JobState.FAILED.value,
                JobState.NEEDS_REVIEW.value,
                JobState.QUEUED.value,
                JobState.READY_TO_UPLOAD.value,
                JobState.SCHEDULED.value,
            ]
        ]
        self.db.query(Job).filter(Job.state.in_(in_flight_states)).update(
            {"state": JobState.NEEDS_REVIEW.value}, synchronize_session=False
        )
        self.db.commit()
        self.db.close()
        if self.config.state_file_path.exists():
            try:
                self.config.state_file_path.unlink()
            except Exception:
                pass

    # ==========================================================================
    # 1. EXPLICIT OPT-IN REQUIREMENT
    # ==========================================================================

    def test_01_canary_mode_explicit_opt_in_required(self):
        """
        Test 1: Canary execution requires explicit opt-in (canary_mode=True).
        Fails fast if canary_mode is False.
        """
        self.service.config.canary_mode = False
        with self.assertRaises(RuntimeError) as ctx:
            self.service.run_canary()
        self.assertIn("explicit opt-in", str(ctx.exception).lower())

    # ==========================================================================
    # 2. EXACTLY-ONE-JOB ENFORCEMENT & NO REFILL
    # ==========================================================================

    def test_02_canary_enforces_single_production_job(self):
        """
        Test 2: Canary executes exactly ONE production job, records telemetry, and terminates.
        """
        topic = Topic(
            id=f"top_canary_{uuid.uuid4().hex[:8]}",
            title="Canary Historical Event Test",
            summary="A test canary topic",
            category="History",
            status="APPROVED",
            score=9999.0
        )
        self.db.add(topic)
        self.db.commit()

        fake_job_id = f"job_canary_{uuid.uuid4().hex[:8]}"
        mock_report = ProductionJobReport(
            job_id=fake_job_id,
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            success=True,
            final_state=JobState.READY_TO_UPLOAD.value
        )
        self.orchestrator.produce_job = MagicMock(return_value=mock_report)

        self.service.reconcile_reserve = MagicMock(return_value={
            "ready_count": 1,
            "target_reserve": 6,
            "deficit": 5,
            "is_healthy": False
        })

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "SUCCESS")
        self.assertEqual(telemetry["job_id"], fake_job_id)
        self.assertEqual(self.orchestrator.produce_job.call_count, 1)
        self.assertTrue(self.service._canary_consumed)
        self.assertFalse(self.service.lock.is_locked())

    def test_03_canary_prohibits_automatic_refill(self):
        """
        Test 3: Canary does not attempt to refill the remaining reserve deficit.
        Even when ready_count=0 and deficit=6, exactly 1 job is produced and refill is not triggered.
        """
        topic = Topic(
            id=f"top_norefill_{uuid.uuid4().hex[:8]}",
            title="No Refill Canary Test",
            summary="Topic testing refill prohibition",
            category="History",
            status="APPROVED",
            score=9999.0
        )
        self.db.add(topic)
        self.db.commit()

        fake_job_id = f"job_norefill_{uuid.uuid4().hex[:8]}"
        mock_report = ProductionJobReport(
            job_id=fake_job_id,
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            success=True,
            final_state=JobState.READY_TO_UPLOAD.value
        )
        self.orchestrator.produce_job = MagicMock(return_value=mock_report)

        self.service.reconcile_reserve = MagicMock(return_value={
            "ready_count": 0,
            "target_reserve": 6,
            "deficit": 6,
            "is_healthy": False
        })

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "SUCCESS")
        self.assertEqual(self.orchestrator.produce_job.call_count, 1)
        self.assertEqual(self.service._jobs_produced_count, 1)

    # ==========================================================================
    # 3. PRE-FLIGHT SAFETY GATES
    # ==========================================================================

    def test_04_preflight_queue_paused_or_safemode_rejection(self):
        """
        Test 4: Pre-flight gate fails immediately if Mission Control queue is paused or in SAFE_MODE.
        """
        mission_control_service.pause_queue(reason="Canary test pause")

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "PREFLIGHT_FAILED")
        self.assertEqual(telemetry["preflight"]["failed_gate"], "queue_interlock")
        self.assertFalse(self.service.lock.is_locked(), "Process lock must be cleanly released on preflight failure")

        mission_control_service.resume_queue()
        mission_control_service.set_operational_mode("SAFE_MODE", reason="Testing safe mode gate")

        telemetry2 = self.service.run_canary()
        self.assertEqual(telemetry2["status"], "PREFLIGHT_FAILED")
        self.assertEqual(telemetry2["preflight"]["failed_gate"], "queue_interlock")

        mission_control_service.set_operational_mode("AUTONOMOUS", reason="Restore autonomous mode")
        mission_control_service.resume_queue()

    def test_05_preflight_daily_publication_limit_rejection(self):
        """
        Test 5: Pre-flight gate fails if daily YouTube publication limit is reached.
        """
        today = datetime.now(timezone.utc).date()
        self.orchestrator.scheduler.get_authoritative_schedule_state = MagicMock(return_value=(
            ["slot_1", "slot_2", "slot_3"],
            {today: DAILY_SHORTS_LIMIT},
            {}
        ))

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "PREFLIGHT_FAILED")
        self.assertEqual(telemetry["preflight"]["failed_gate"], "daily_limit")
        self.assertFalse(self.service.lock.is_locked())

    def test_06_preflight_worker_lock_held_rejection(self):
        """
        Test 6: Pre-flight gate fails if worker process lock is held by another process.
        """
        with patch.object(self.service.lock, "acquire", return_value=False):
            with self.assertRaises(Exception):
                self.service.run_canary()

    def test_07_canary_cannot_be_rerun_in_same_session(self):
        """
        Test 7: Once a canary has executed, subsequent execution attempts in the same session are blocked.
        """
        self.service._canary_consumed = True
        with self.assertRaises(RuntimeError) as ctx:
            self.service.run_canary()
        self.assertIn("already been executed", str(ctx.exception).lower())

    # ==========================================================================
    # 4. IDEMPOTENT CRASH RECOVERY RESUMPTION
    # ==========================================================================

    def test_08_canary_idempotent_in_flight_resumption(self):
        """
        Test 8: Canary resumes existing in-flight job instead of creating a duplicate job.
        """
        topic = Topic(
            id=f"top_inflight_{uuid.uuid4().hex[:8]}",
            title="In Flight Canary Resumption Test",
            summary="Testing crash recovery during canary",
            category="History",
            status="APPROVED",
            score=9999.0
        )
        self.db.add(topic)
        self.db.commit()

        inflight_job = Job(
            id=f"job_inflight_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.SCRIPT_READY.value
        )
        self.db.add(inflight_job)
        self.db.commit()

        mock_report = ProductionJobReport(
            job_id=inflight_job.id,
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            success=True,
            final_state=JobState.READY_TO_UPLOAD.value
        )
        self.orchestrator.produce_job = MagicMock(return_value=mock_report)

        self.service.reconcile_reserve = MagicMock(return_value={
            "ready_count": 1,
            "target_reserve": 6,
            "deficit": 5,
            "is_healthy": False
        })

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "SUCCESS")
        self.assertEqual(telemetry["job_id"], inflight_job.id)
        self.assertTrue(telemetry["resumed_in_flight"])
        self.assertEqual(self.orchestrator.produce_job.call_count, 1)
        self.assertEqual(self.orchestrator.produce_job.call_args[1].get("job_id"), inflight_job.id)

    # ==========================================================================
    # 5. CLOUD CONFIRMATION & NO PUBLISHING
    # ==========================================================================

    def test_09_canary_requires_cloud_confirmation_when_live(self):
        """
        Test 9: Live canary requires artifact verified in Drive 01_READY before claiming success.
        If Drive 01_READY does not contain the file, fails closed.
        """
        topic = Topic(
            id=f"top_cloud_{uuid.uuid4().hex[:8]}",
            title="Cloud Confirmation Test",
            summary="Testing cloud confirmation",
            category="History",
            status="APPROVED",
            score=9999.0
        )
        self.db.add(topic)
        self.db.commit()

        fake_job_id = f"job_cloud_{uuid.uuid4().hex[:8]}"
        mock_report = ProductionJobReport(
            job_id=fake_job_id,
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            success=True,
            final_state=JobState.READY_TO_UPLOAD.value
        )
        self.orchestrator.produce_job = MagicMock(return_value=mock_report)

        # Force live canary capabilities (allow_drive_write = True)
        self.orchestrator.capabilities = ExecutionCapabilities.live_canary()

        # Mock drive_engine listing: file NOT present in 01_READY
        self.orchestrator.drive_engine.list_files_in_folder = MagicMock(return_value=[])
        self.service.reconcile_reserve = MagicMock(return_value={
            "ready_count": 0,
            "target_reserve": 6,
            "deficit": 6,
            "is_healthy": False
        })

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "CLOUD_CONFIRMATION_FAILED")
        self.assertIn("not verified in 01_READY", telemetry["error"])

    def test_10_canary_prohibits_automatic_youtube_publishing(self):
        """
        Test 10: Canary capabilities strictly prohibit YouTube publishing and scheduling.
        allow_youtube_write and allow_schedule must be False.
        """
        canary_caps = ExecutionCapabilities.live_canary()
        self.assertTrue(canary_caps.allow_network_read)
        self.assertTrue(canary_caps.allow_ai)
        self.assertTrue(canary_caps.allow_tts)
        self.assertTrue(canary_caps.allow_render)
        self.assertTrue(canary_caps.allow_drive_write)
        self.assertFalse(canary_caps.allow_youtube_write, "Canary must never allow YouTube publishing")
        self.assertFalse(canary_caps.allow_schedule, "Canary must never allow YouTube scheduling")

    # ==========================================================================
    # 6. AUDIT TELEMETRY & HEARTBEAT
    # ==========================================================================

    def test_11_canary_audit_telemetry_and_heartbeat(self):
        """
        Test 11: Full canary audit telemetry is written and exposed in heartbeat.
        """
        topic = Topic(
            id=f"top_telemetry_{uuid.uuid4().hex[:8]}",
            title="Telemetry Canary Test",
            summary="Testing telemetry structure",
            category="History",
            status="APPROVED",
            score=9999.0
        )
        self.db.add(topic)
        self.db.commit()

        fake_job_id = f"job_telem_{uuid.uuid4().hex[:8]}"
        mock_report = ProductionJobReport(
            job_id=fake_job_id,
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            success=True,
            final_state=JobState.READY_TO_UPLOAD.value
        )
        self.orchestrator.produce_job = MagicMock(return_value=mock_report)

        self.service.reconcile_reserve = MagicMock(return_value={
            "ready_count": 3,
            "target_reserve": 6,
            "deficit": 3,
            "is_healthy": False
        })

        telemetry = self.service.run_canary()

        self.assertEqual(telemetry["status"], "SUCCESS")
        self.assertEqual(telemetry["job_id"], fake_job_id)
        self.assertIn("preflight", telemetry)
        self.assertEqual(len(telemetry["preflight"]["gates"]), 8)

        # Check heartbeat file
        self.assertTrue(self.config.state_file_path.exists())
        hb_data = json.loads(self.config.state_file_path.read_text(encoding="utf-8"))
        self.assertTrue(hb_data.get("canary_mode"))
        self.assertTrue(hb_data.get("canary_consumed"))
        self.assertIsNotNone(hb_data.get("canary_telemetry"))

    # ==========================================================================
    # 7. NICHE-AGNOSTIC ARCHITECTURAL COMPLIANCE
    # ==========================================================================

    def test_12_ast_niche_agnostic_compliance(self):
        """
        Test 12: Scans all new and modified Step 7 code using AST to verify zero hardcoded niche conditionals.
        """
        files_to_check = [
            PROJECT_ROOT / "runtime" / "service.py",
            PROJECT_ROOT / "runtime" / "config.py",
            PROJECT_ROOT / "runtime" / "cli.py",
            PROJECT_ROOT / "engines" / "orchestrator.py"
        ]

        forbidden_niche_identifiers = ["history", "stoicism", "finance", "horror", "scifi", "tech", "geopolitics"]

        for file_path in files_to_check:
            self.assertTrue(file_path.exists(), f"File {file_path} must exist.")
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    for subnode in ast.walk(node.test):
                        if isinstance(subnode, ast.Constant) and isinstance(subnode.value, str):
                            val = subnode.value.lower()
                            for niche in forbidden_niche_identifiers:
                                self.assertNotIn(
                                    niche,
                                    val,
                                    f"Hardcoded niche conditional '{niche}' discovered in {file_path.name} line {subnode.lineno}"
                                )


if __name__ == "__main__":
    unittest.main()
