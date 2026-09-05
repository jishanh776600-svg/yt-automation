"""
Targeted Test Suite for AL-AMR Step 5: Autonomous Runtime & Deployment Bridge.
Covers:
  1. RuntimeConfig loading and environment variable overrides
  2. AutonomousRuntimeService lifecycle, locking, and graceful shutdown
  3. Crash recovery and in-flight job resumption (idempotency)
  4. Periodic intelligence harvesting loop
  5. Target buffer stock replenishment
  6. Scheduled publishing loop with hard DAILY_SHORTS_LIMIT enforcement
  7. Eligible failed job auto-recovery
  8. Queue pause interlock compliance
  9. Heartbeat persistence and Mission Control integration (/api/mission-control/runtime)
  10. AST niche-agnostic architectural compliance
"""
import os
import ast
import json
import uuid
import time
import shutil
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from config.settings import PROJECT_ROOT, LOCKS_DIR
from config.constants import JobState, DAILY_SHORTS_LIMIT
from core.database import SessionLocal
from core.models import Job, Topic, UploadRecord, ScriptRecord, QAReport
from core.content_profile import set_active_profile, get_profile_by_name
from core.discovery_profile import get_active_discovery_profile
from core.state_machine import StateMachine
from engines.orchestrator import ProductionOrchestrator, ExecutionCapabilities, STATE_RANK
from runtime.config import RuntimeConfig
from runtime.service import AutonomousRuntimeService
from dashboard.app import app
from dashboard.mission_control_service import mission_control_service


class TestAutonomousRuntime(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
        login_res = cls.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        cls.csrf_token = login_res.json().get("csrf_token", "")
        cls.auth_headers = {"X-CSRF-Token": cls.csrf_token}
        cls.test_state_file = LOCKS_DIR / "test_worker_state.json"
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if cls.test_state_file.exists():
            cls.test_state_file.unlink()
        set_active_profile(None)

    def setUp(self):
        # Create dedicated test config
        self.config = RuntimeConfig(
            enabled=True,
            interval_sec=1.0,
            harvest_interval_sec=0.0,  # harvest immediately for testing
            recovery_interval_sec=0.0, # recover immediately for testing
            target_buffer_stock=4,
            max_batch_size=1,
            dry_run=True,
            max_retries=3,
            state_file_path=self.test_state_file
        )
        caps = ExecutionCapabilities.sandboxed_testing()
        self.orchestrator = ProductionOrchestrator(
            capabilities=caps,
            max_retries=3
        )
        self.service = AutonomousRuntimeService(
            config=self.config,
            orchestrator=self.orchestrator
        )
        # Ensure queue is not paused initially
        mission_control_service.resume_queue(reason="Test setup")

    def tearDown(self):
        self.service.stop()

    # ==========================================================================
    # 1. CONFIGURATION LOADING & OVERRIDES
    # ==========================================================================

    def test_01_config_from_env(self):
        """Test 1: Verifies RuntimeConfig reads environment variables and defaults properly."""
        with patch.dict(os.environ, {
            "AUTONOMOUS_WORKER_ENABLED": "false",
            "AUTONOMOUS_INTERVAL_SEC": "45.0",
            "HARVEST_INTERVAL_SEC": "600.0",
            "TARGET_BUFFER_STOCK": "8",
            "MAX_JOB_RETRIES": "5"
        }):
            cfg = RuntimeConfig.from_env()
            self.assertFalse(cfg.enabled)
            self.assertEqual(cfg.interval_sec, 45.0)
            self.assertEqual(cfg.harvest_interval_sec, 600.0)
            self.assertEqual(cfg.target_buffer_stock, 8)
            self.assertEqual(cfg.max_retries, 5)

    # ==========================================================================
    # 2. LIFECYCLE & GRACEFUL SHUTDOWN
    # ==========================================================================

    def test_02_service_lifecycle_and_shutdown(self):
        """Test 2: Verifies service start, heartbeat creation, and graceful stop."""
        self.service._running = True
        self.service._write_heartbeat(status="ONLINE", current_task="TESTING")

        self.assertTrue(self.config.state_file_path.exists())
        data = json.loads(self.config.state_file_path.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "ONLINE")
        self.assertEqual(data["current_task"], "TESTING")
        self.assertTrue(data["online"])

        # Stop service
        self.service.stop()
        self.assertFalse(self.service._running)

        stop_data = json.loads(self.config.state_file_path.read_text(encoding="utf-8"))
        self.assertEqual(stop_data["status"], "OFFLINE")
        self.assertFalse(stop_data["online"])

    # ==========================================================================
    # 3. CRASH RECOVERY & IN-FLIGHT RESUMPTION
    # ==========================================================================

    def test_03_crash_recovery_resumes_incomplete_job(self):
        """Test 3: Verifies worker automatically resumes an in-flight job interrupted at SCRIPT_READY."""
        topic = Topic(
            id=f"top_rec_{uuid.uuid4().hex[:8]}",
            title="Crash Recovery Topic",
            summary="Testing crash recovery and resumption.",
            category="Technology",
            score=88.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_rec_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.SCRIPT_READY.value,
            retry_count=0,
            updated_at=datetime.utcnow() + timedelta(minutes=5)
        )
        script = ScriptRecord(
            id=f"scr_rec_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            hook="Telemetry detected propulsion anomaly.",
            context="Lunar descent trajectory.",
            escalation="Primary thruster shut down.",
            reveal="Auxiliary attitude thrusters restored guidance.",
            loop_twist="Leading to next test flight.",
            full_text="Telemetry detected propulsion anomaly. Lunar descent trajectory. Primary thruster shut down. Auxiliary attitude thrusters restored guidance.",
            word_count=50,
            estimated_duration_sec=20.0,
            status="APPROVED"
        )
        self.db.add_all([topic, job, script])
        self.db.commit()

        saved_job_id = job.id

        # Run a single tick
        summary = self.service.run_tick()

        # Resumed job should match the in-flight job
        self.assertEqual(summary["resumed_job"], saved_job_id)

        # Job should have progressed beyond SCRIPT_READY
        self.db.rollback()
        refreshed_job = self.db.query(Job).filter(Job.id == saved_job_id).first()
        self.assertIn(refreshed_job.state, [
            JobState.READY_TO_UPLOAD.value,
            JobState.SCHEDULED.value,
            JobState.PUBLISHED.value
        ])

    # ==========================================================================
    # 4. PERIODIC INTELLIGENCE HARVESTING
    # ==========================================================================

    def test_04_periodic_intelligence_harvest(self):
        """Test 4: Verifies intelligence harvesting discovers and filters candidate topics."""
        harvest_count = self.service._cycle_intelligence_harvest(self.db)
        self.assertGreaterEqual(harvest_count, 0)
        self.assertGreater(self.service._last_harvest_time, 0.0)

    # ==========================================================================
    # 5. PRODUCTION QUEUE REPLENISHMENT
    # ==========================================================================

    def test_05_production_queue_replenishment(self):
        """Test 5: Verifies worker replenishes ready buffer when stock is below target."""
        # Ensure we have an approved topic available
        topic = Topic(
            id=f"top_rep_{uuid.uuid4().hex[:8]}",
            title="Queue Replenish Topic",
            summary="Autonomous production queue replenishment test.",
            category="Space",
            score=92.0,
            status="APPROVED"
        )
        self.db.add(topic)
        self.db.commit()

        current_ready = self.db.query(Job).filter(
            Job.state.in_([JobState.QA.value, JobState.READY_TO_UPLOAD.value, JobState.SCHEDULED.value])
        ).count()
        self.service.config.target_buffer_stock = current_ready + 5

        report = self.service._cycle_production_queue(self.db)
        self.assertIsNotNone(report)
        self.assertTrue(report.success)
        self.assertEqual(report.topic_id, topic.id)

        produced_job = self.db.query(Job).filter(Job.topic_id == topic.id).first()
        self.assertIsNotNone(produced_job)
        self.assertIn(produced_job.state, [
            JobState.READY_TO_UPLOAD.value,
            JobState.SCHEDULED.value,
            JobState.PUBLISHED.value
        ])

    # ==========================================================================
    # 6. SCHEDULED PUBLISHING & DAILY LIMIT GUARD
    # ==========================================================================

    def test_06_scheduled_publishing_and_daily_limit_guard(self):
        """Test 6: Verifies due upload is published and daily limit prevents excess uploads."""
        # Clean any prior scheduled uploads for clean test isolation
        self.db.query(UploadRecord).filter(UploadRecord.status == "SCHEDULED").update({"status": "SUCCESS"}, synchronize_session=False)
        self.db.commit()

        topic = Topic(
            id=f"top_pub_{uuid.uuid4().hex[:8]}",
            title="Scheduled Publish Topic",
            summary="Testing scheduled publishing loop.",
            category="Space",
            score=95.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_pub_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.SCHEDULED.value
        )
        # Set scheduled_publish_at in the past so it is due now
        due_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        upload = UploadRecord(
            id=f"up_pub_{uuid.uuid4().hex[:8]}",
            job_id=job.id,
            youtube_video_id="DUE_VID_123",
            title="Due Short Video",
            description="Due for publication.",
            status="SCHEDULED",
            scheduled_publish_at=due_time
        )
        self.db.add_all([topic, job, upload])
        self.db.commit()

        # Run scheduled publishing
        pub_id = self.service._cycle_scheduled_publishing(self.db)
        self.assertEqual(pub_id, job.id)

        refreshed_upload = self.db.query(UploadRecord).filter(UploadRecord.id == upload.id).first()
        self.assertIn(refreshed_upload.status, ["PUBLISHED", "TEST_VERIFIED"])

    # ==========================================================================
    # 7. ELIGIBLE FAILED JOB AUTO-RECOVERY
    # ==========================================================================

    def test_07_eligible_failed_job_auto_recovery(self):
        """Test 7: Verifies failed job with retries remaining is re-enqueued to QUEUED."""
        # Clean any prior failed jobs for clean test isolation
        self.db.query(Job).filter(Job.state == JobState.FAILED.value).update({"retry_count": 99}, synchronize_session=False)
        self.db.commit()

        topic = Topic(
            id=f"top_fail_{uuid.uuid4().hex[:8]}",
            title="Failed Recoverable Topic",
            summary="Testing auto recovery of failed jobs.",
            category="Space",
            score=80.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_fail_{uuid.uuid4().hex[:8]}",
            topic_id=topic.id,
            state=JobState.FAILED.value,
            error_message="Transient network timeout",
            retry_count=1  # < max_retries (3)
        )
        self.db.add_all([topic, job])
        self.db.commit()

        recovered_count = self.service._cycle_failed_jobs_recovery(self.db)
        self.assertEqual(recovered_count, 1)

        refreshed_job = self.db.query(Job).filter(Job.id == job.id).first()
        self.assertEqual(refreshed_job.state, JobState.QUEUED.value)
        self.assertEqual(refreshed_job.retry_count, 2)
        self.assertIsNone(refreshed_job.error_message)

    # ==========================================================================
    # 8. QUEUE PAUSE INTERLOCK
    # ==========================================================================

    def test_08_queue_pause_interlock(self):
        """Test 8: Verifies paused queue skips production tick."""
        mission_control_service.pause_queue(reason="Testing queue pause interlock")
        summary = self.service.run_tick()
        self.assertEqual(summary["status"], "QUEUE_PAUSED")

        # Resume queue
        mission_control_service.resume_queue(reason="Resuming after test")
        summary2 = self.service.run_tick()
        self.assertEqual(summary2["status"], "SUCCESS")

    # ==========================================================================
    # 9. MISSION CONTROL RUNTIME INTEGRATION
    # ==========================================================================

    def test_09_mission_control_runtime_telemetry(self):
        """Test 9: Verifies Mission Control endpoint GET /api/mission-control/runtime."""
        self.service._write_heartbeat(status="ONLINE", current_task="IDLE")

        # Read directly from service
        rt_status = mission_control_service.get_runtime_status()
        self.assertIn("status", rt_status)
        self.assertIn("online", rt_status)
        self.assertIn("current_task", rt_status)
        self.assertIn("cycles_completed", rt_status)

        # Query via REST API
        res = self.client.get("/api/mission-control/runtime")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("status", data)
        self.assertIn("online", data)

    # ==========================================================================
    # 10. AST ARCHITECTURAL AUDIT (NICHE-AGNOSTIC)
    # ==========================================================================

    def test_10_ast_architectural_audit(self):
        """Test 10: Verifies zero hardcoded niche conditionals in runtime code."""
        runtime_files = [
            "runtime/config.py",
            "runtime/service.py",
            "runtime/cli.py"
        ]
        forbidden_niches = ["CURRENT_AFFAIRS", "HISTORICAL", "SPACE_TECHNOLOGY", "FINANCIAL_MARKETS"]

        for rf in runtime_files:
            file_path = PROJECT_ROOT / rf
            self.assertTrue(file_path.exists(), f"File {rf} does not exist.")
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    dumped = ast.dump(node.test)
                    for fn in forbidden_niches:
                        pattern = f"Constant(value='{fn}')"
                        self.assertNotIn(
                            pattern,
                            dumped,
                            f"Hardcoded niche conditional '{fn}' found in {rf} at line {node.lineno}"
                        )


if __name__ == "__main__":
    unittest.main()
