"""
Targeted Test Suite for AL-AMR Step 6: Unattended Cloud Production Validation.

Covers:
  1. Reserve deficit calculation: max(6 - ready_count, 0)
  2. 01_READY-only counting (02_PROCESSING does NOT count)
  3. Sequential refill (produces only deficit, one Short at a time)
  4. Reconciliation after production (cloud state confirms deposit before claiming success)
  5. Stop-at-6 behavior (halts refill cleanly when reserve reaches 6)
  6. YouTube capacity stop (halts publishing when daily 3/3 capacity is exhausted)
  7. Provider failover cascade (Primary -> Secondary -> Groq -> OpenRouter -> Clean Failure; no DeepSeek)
  8. Production/QA failure clean stop (halts immediately without infinite-retrying)
  9. Duplicate prevention (blocks duplicate topics from entering refill pipeline)
  10. Clean recovery after interruption (in-flight jobs resumed safely)
  11. AST niche-agnostic architectural compliance (zero hardcoded niche conditionals)
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
from core.models import Job, Topic, UploadRecord, ScriptRecord
from core.content_profile import get_active_profile
from core.discovery_profile import get_active_discovery_profile
from engines.drive_engine import DriveVaultEngine
from engines.orchestrator import ProductionOrchestrator, ExecutionCapabilities, ProductionJobReport, StageResult
from engines.scheduler_engine import PublicationScheduler
from runtime.config import RuntimeConfig
from runtime.service import AutonomousRuntimeService
from dashboard.mission_control_service import mission_control_service


class TestCloudProductionValidation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_locks_dir = LOCKS_DIR
        cls.test_locks_dir.mkdir(parents=True, exist_ok=True)
        # Ensure queue is not paused
        mission_control_service.resume_queue(reason="Step 6 Test Setup")

    def setUp(self):
        self.db = SessionLocal()
        self.config = RuntimeConfig(
            enabled=True,
            interval_sec=10.0,
            target_buffer_stock=6,
            max_batch_size=3,
            dry_run=True,
            state_file_path=self.test_locks_dir / "step6_test_worker_state.json"
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
        self.service._running = True
        mission_control_service.resume_queue(reason="Test setup")

    def tearDown(self):
        self.service.stop()
        self.db.close()
        if self.config.state_file_path.exists():
            try:
                self.config.state_file_path.unlink()
            except Exception:
                pass

    # ==========================================================================
    # 1. REAL RESERVE RECONCILIATION & DEFICIT CALCULATION
    # ==========================================================================

    def test_01_reserve_deficit_calculation(self):
        """
        Test 1: Verifies reserve deficit calculation: max(6 - ready_count, 0).
        Evaluates boundary conditions: 0, 2, 5, 6, 8 ready items.
        """
        vault_engine = DriveVaultEngine()

        test_cases = [
            (0, 6),  # Empty reserve -> Deficit of 6
            (2, 4),  # Partial reserve -> Deficit of 4
            (5, 1),  # Near target -> Deficit of 1
            (6, 0),  # Exact target -> Deficit of 0
            (8, 0),  # Surplus reserve -> Deficit clamped to 0
        ]

        for ready_val, expected_deficit in test_cases:
            with patch.object(vault_engine, "get_ready_stock_count", return_value=ready_val):
                recon = vault_engine.reconcile_cloud_reserve(db=self.db, target_reserve=6)
                self.assertEqual(recon["ready_count"], ready_val)
                self.assertEqual(recon["target_reserve"], 6)
                self.assertEqual(recon["deficit"], expected_deficit)
                self.assertEqual(recon["is_healthy"], (expected_deficit == 0))

    # ==========================================================================
    # 2. 01_READY-ONLY COUNTING (02_PROCESSING DOES NOT COUNT)
    # ==========================================================================

    def test_02_ready_only_counting_ignores_processing_and_published(self):
        """
        Test 2: Proves only '01_READY' counts toward the reserve.
        '02_PROCESSING', '03_PUBLISHED', and '04_FAILED' files do NOT count.
        """
        vault_engine = DriveVaultEngine()

        ready_files = [
            {"id": "file_r1", "name": "READY_short_job_a1.mp4", "size": 15000000, "parents": ["01_READY"]},
            {"id": "file_r2", "name": "READY_short_job_a2.mp4", "size": 16000000, "parents": ["01_READY"]}
        ]
        processing_files = [
            {"id": "file_p1", "name": "PROC_short_job_b1.mp4", "size": 15000000, "parents": ["02_PROCESSING"]},
            {"id": "file_p2", "name": "PROC_short_job_b2.mp4", "size": 15000000, "parents": ["02_PROCESSING"]},
            {"id": "file_p3", "name": "PROC_short_job_b3.mp4", "size": 15000000, "parents": ["02_PROCESSING"]}
        ]
        published_files = [
            {"id": "file_pub1", "name": "PUB_short_job_c1.mp4", "size": 15000000, "parents": ["03_PUBLISHED"]}
        ]

        def mock_list_files(folder_name, limit=50):
            if folder_name == "01_READY":
                return ready_files
            elif folder_name == "02_PROCESSING":
                return processing_files
            elif folder_name == "03_PUBLISHED":
                return published_files
            return []

        with patch.object(vault_engine, "inspect_or_init_vault", return_value={"01_READY": "f_ready", "02_PROCESSING": "f_proc"}), \
             patch.object(vault_engine, "list_files_in_folder", side_effect=mock_list_files), \
             patch("engines.drive_engine.is_valid_ready_short", return_value=(True, "Valid")):

            recon = vault_engine.reconcile_cloud_reserve(db=self.db, target_reserve=6)

            self.assertEqual(recon["ready_count"], 2)
            self.assertEqual(recon["processing_count"], 3)
            self.assertEqual(recon["deficit"], 4)

    # ==========================================================================
    # 3. SEQUENTIAL REFILL (ONE SHORT AT A TIME)
    # ==========================================================================

    def test_03_sequential_refill_one_at_a_time(self):
        """
        Test 3: Verifies that when reserve < 6, production occurs sequentially
        one Short at a time until the deficit budget is satisfied.
        """
        topics = []
        for i in range(3):
            t = Topic(
                id=f"top_seq_{i}_{uuid.uuid4().hex[:6]}",
                title=f"Sequential Refill Story {i+1}",
                summary=f"Summary for sequential production verification {i+1}",
                category="Technology",
                score=7000.0 + i,
                status="APPROVED"
            )
            self.db.add(t)
            topics.append(t)
        self.db.commit()

        call_count = 0
        def mock_reconcile(db):
            nonlocal call_count
            ready = min(4 + call_count, 6)
            return {
                "ready_count": ready,
                "target_reserve": 6,
                "deficit": max(6 - ready, 0),
                "is_healthy": (ready >= 6)
            }

        produced_topics = []
        def mock_produce_job(topic, db=None, job_id=None):
            nonlocal call_count
            call_count += 1
            produced_topics.append(topic.id)
            return ProductionJobReport(
                job_id=f"job_{topic.id}",
                topic_id=topic.id,
                topic_title=topic.title,
                niche="DEFAULT",
                final_state="READY_TO_UPLOAD",
                success=True
            )

        self.service.config.max_batch_size = 2
        with patch.object(self.service, "reconcile_reserve", side_effect=mock_reconcile), \
             patch.object(self.orchestrator, "produce_job", side_effect=mock_produce_job):

            self.service._cycle_production_queue(self.db)

            self.assertEqual(len(produced_topics), 2)
            self.assertEqual(produced_topics[0], topics[2].id)
            self.assertEqual(produced_topics[1], topics[1].id)

    # ==========================================================================
    # 4. RECONCILIATION CONFIRMS CLOUD DEPOSIT BEFORE SUCCESS
    # ==========================================================================

    def test_04_reconciliation_confirms_cloud_deposit_before_success(self):
        """
        Test 4: Proves system never claims success unless the resulting cloud state confirms it.
        If post-production ready count fails to increment, the refill cycle halts and logs error.
        """
        topic = Topic(
            id=f"top_dep_{uuid.uuid4().hex[:6]}",
            title="Cloud Deposit Verification Topic",
            summary="Verifying cloud state confirmation before success.",
            category="History",
            score=90.0,
            status="APPROVED"
        )
        self.db.add(topic)
        self.db.commit()

        recon_static = {
            "ready_count": 3,
            "target_reserve": 6,
            "deficit": 3,
            "is_healthy": False
        }

        mock_report = ProductionJobReport(
            job_id=f"job_{topic.id}",
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            final_state="READY_TO_UPLOAD",
            success=True
        )

        self.orchestrator.capabilities.allow_drive_write = True

        with patch.object(self.service, "reconcile_reserve", return_value=recon_static), \
             patch.object(self.orchestrator, "produce_job", return_value=mock_report), \
             patch.object(mission_control_service, "log_event") as mock_log:

            self.service._cycle_production_queue(self.db)

            failure_events = [
                call for call in mock_log.call_args_list
                if call.kwargs.get("category") == "FAILURE"
            ]
            self.assertTrue(len(failure_events) > 0)
            self.assertIn("Cloud verification failed", failure_events[0].kwargs.get("message"))

    # ==========================================================================
    # 5. STOP CONDITIONS: STOP-AT-6 BEHAVIOR
    # ==========================================================================

    def test_05_stop_at_6_behavior(self):
        """
        Test 5: Verifies that when Google Drive reserve reaches 6,
        production stops immediately with 0 unnecessary jobs created.
        """
        topic = Topic(
            id=f"top_stop6_{uuid.uuid4().hex[:6]}",
            title="Stop at Six Topic",
            summary="Verifying immediate halt when reserve is 6.",
            category="History",
            score=99.0,
            status="APPROVED"
        )
        self.db.add(topic)
        self.db.commit()

        with patch.object(self.service, "reconcile_reserve", return_value={
            "ready_count": 6,
            "target_reserve": 6,
            "deficit": 0,
            "is_healthy": True
        }), patch.object(self.orchestrator, "produce_job") as mock_produce:

            report = self.service._cycle_production_queue(self.db)

            mock_produce.assert_not_called()
            self.assertIsNone(report)

    # ==========================================================================
    # 6. STOP CONDITIONS: YOUTUBE PUBLICATION CAPACITY EXHAUSTED
    # ==========================================================================

    def test_06_youtube_capacity_stop(self):
        """
        Test 6: Verifies publishing cycle halts cleanly when daily YouTube capacity
        (DAILY_SHORTS_LIMIT = 3) is exhausted, without attempting any uploads.
        """
        now = datetime.now(timezone.utc)
        today = now.date()

        for i in range(DAILY_SHORTS_LIMIT):
            job = Job(id=f"job_lim_{i}_{uuid.uuid4().hex[:4]}", state=JobState.PUBLISHED.value)
            upl = UploadRecord(
                id=f"upl_lim_{i}_{uuid.uuid4().hex[:4]}",
                job_id=job.id,
                title=f"Published Today Short {i+1}",
                description=f"Published description {i+1}",
                status="PUBLISHED",
                published_at=datetime.utcnow()
            )
            self.db.add_all([job, upl])
        self.db.commit()

        day_counts = {today: DAILY_SHORTS_LIMIT}
        with patch.object(self.orchestrator.scheduler, "get_authoritative_schedule_state",
                          return_value=(set(), day_counts, {})), \
             patch.object(self.orchestrator, "stage_publish") as mock_publish:

            res = self.service._cycle_scheduled_publishing(self.db)

            self.assertIsNone(res)
            mock_publish.assert_not_called()

    # ==========================================================================
    # 7. PROVIDER FAILOVER CASCADE (PRIMARY -> SECONDARY -> GROQ -> OPENROUTER -> CLEAN FAILURE)
    # ==========================================================================

    def test_07_provider_failover_cascade_without_deepseek(self):
        """
        Test 7: Proves deterministic provider failover:
        Gemini Primary -> Gemini Secondary -> Groq -> OpenRouter -> Clean Failure.
        Strictly confirms DeepSeek is NOT in the active provider cascade.
        """
        from core.gemini_client import GeminiClient, GeminiQuotaExhaustedError

        client = GeminiClient(
            api_key="gem_prim_key",
            secondary_api_key="gem_sec_key",
            groq_api_key="groq_key",
            openrouter_api_key="or_key",
            deepseek_api_key="deepseek_key_should_be_ignored"
        )

        providers = client._get_configured_providers()
        provider_names = [p["name"] for p in providers]

        self.assertEqual(provider_names, ["primary", "secondary", "groq", "openrouter"])
        self.assertNotIn("deepseek", provider_names)

        for name in provider_names:
            client.mark_provider_exhausted(name)

        with self.assertRaises(GeminiQuotaExhaustedError) as cm:
            client.generate_content(model="gemini-2.5-flash", contents="Test prompt")
        self.assertIn("exhausted daily API quotas", str(cm.exception))

    # ==========================================================================
    # 8. STOP CONDITIONS: PRODUCTION / QA FAILURE CLEAN STOP
    # ==========================================================================

    def test_08_production_qa_failure_halts_cycle_without_infinite_retry(self):
        """
        Test 8: Verifies that if QA or Critic fails during production,
        the refill cycle stops immediately without looping or retry amplification.
        """
        topic = Topic(
            id=f"top_qa_fail_{uuid.uuid4().hex[:6]}",
            title="QA Failure Topic",
            summary="Testing immediate clean halt on QA rejection.",
            category="History",
            score=87.0,
            status="APPROVED"
        )
        self.db.add(topic)
        self.db.commit()

        failed_report = ProductionJobReport(
            job_id=f"job_{topic.id}",
            topic_id=topic.id,
            topic_title=topic.title,
            niche="DEFAULT",
            final_state="NEEDS_REVIEW",
            error_message="QA Gate Failed: Loudness -18 LUFS exceeds -30 LUFS BGM spec",
            success=False
        )

        produce_calls = 0
        def mock_produce(topic, db=None, job_id=None):
            nonlocal produce_calls
            produce_calls += 1
            return failed_report

        with patch.object(self.service, "reconcile_reserve", return_value={"ready_count": 4, "target_reserve": 6, "deficit": 2, "is_healthy": False}), \
             patch.object(self.orchestrator, "produce_job", side_effect=mock_produce):

            report = self.service._cycle_production_queue(self.db)

            self.assertEqual(produce_calls, 1)
            self.assertFalse(report.success)
            self.assertEqual(report.final_state, "NEEDS_REVIEW")

    # ==========================================================================
    # 9. DUPLICATE PREVENTION DURING REFILL
    # ==========================================================================

    def test_09_duplicate_prevention_during_refill(self):
        """
        Test 9: Verifies that topics already associated with active jobs
        are never duplicated during autonomous refill cycles.
        """
        topic_existing = Topic(
            id=f"top_dup_{uuid.uuid4().hex[:6]}",
            title="Existing Active Short Story",
            summary="Story that already has a job.",
            category="Technology",
            score=9999.0,
            status="APPROVED"
        )
        job_existing = Job(
            id=f"job_dup_{uuid.uuid4().hex[:6]}",
            topic_id=topic_existing.id,
            state=JobState.READY_TO_UPLOAD.value
        )
        topic_fresh = Topic(
            id=f"top_fresh_{uuid.uuid4().hex[:6]}",
            title="Fresh Unproduced Story",
            summary="New candidate story.",
            category="Technology",
            score=8888.0,
            status="APPROVED"
        )
        self.db.add_all([topic_existing, job_existing, topic_fresh])
        self.db.commit()

        produced_topics = []
        def mock_produce(topic, db=None, job_id=None):
            produced_topics.append(topic.id)
            return ProductionJobReport(
                job_id=f"job_{topic.id}",
                topic_id=topic.id,
                topic_title=topic.title,
                niche="DEFAULT",
                final_state="READY_TO_UPLOAD",
                success=True
            )

        with patch.object(self.service, "reconcile_reserve", return_value={"ready_count": 4, "target_reserve": 6, "deficit": 1, "is_healthy": False}), \
             patch.object(self.orchestrator, "produce_job", side_effect=mock_produce):

            self.service._cycle_production_queue(self.db)

            self.assertEqual(produced_topics, [topic_fresh.id])

    # ==========================================================================
    # 10. CLEAN RECOVERY AFTER INTERRUPTION
    # ==========================================================================

    def test_10_clean_recovery_after_interruption(self):
        """
        Test 10: Verifies that an interrupted in-flight job is resumed
        and completed before starting any new refill topics.
        """
        topic = Topic(
            id=f"top_int_{uuid.uuid4().hex[:6]}",
            title="Interrupted Crash Job Topic",
            summary="Testing crash recovery prioritization.",
            category="Space",
            score=91.0,
            status="APPROVED"
        )
        job = Job(
            id=f"job_int_{uuid.uuid4().hex[:6]}",
            topic_id=topic.id,
            state=JobState.SCRIPT_READY.value,
            updated_at=datetime.utcnow() + timedelta(minutes=10)
        )
        self.db.add_all([topic, job])
        self.db.commit()

        summary = self.service.run_tick()

        self.assertEqual(summary.get("resumed_job"), job.id)

    # ==========================================================================
    # 11. AST ARCHITECTURAL AUDIT (100% NICHE-AGNOSTIC)
    # ==========================================================================

    def test_11_ast_niche_agnostic_compliance(self):
        """
        Test 11: Static AST inspection confirming zero hardcoded niche conditionals
        in the runtime service and drive engine reconcile additions.
        """
        service_file = PROJECT_ROOT / "runtime" / "service.py"
        drive_file = PROJECT_ROOT / "engines" / "drive_engine.py"

        forbidden_niche_literals = {
            "current_affairs",
            "american_history",
            "ancient_history",
            "historical_documentaries",
            "space_technology",
            "financial_markets"
        }

        for fpath in [service_file, drive_file]:
            tree = ast.parse(fpath.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    test_dump = ast.dump(node.test).lower()
                    for literal in forbidden_niche_literals:
                        if f"'{literal}'" in test_dump or f'"{literal}"' in test_dump:
                            self.fail(f"AST violation: hardcoded niche conditional '{literal}' in {fpath.name}")


if __name__ == "__main__":
    unittest.main()
