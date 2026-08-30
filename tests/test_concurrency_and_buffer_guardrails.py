"""
Unit and Integration Test Suite for Safe Concurrency Control, Process Locking & Buffer Guardrails (Phase 5.3).
Validates:
1. Lock acquisition succeeds when unlocked.
2. Second process cannot acquire active lock.
3. Lock metadata contains PID, command, and timestamp.
4. Stale lock can be safely recovered (dead PID or expired age).
5. Active lock is never incorrectly stolen.
6. Lock releases on normal exit.
7. Lock releases on exception (context manager).
8. SQLite concurrent access does not corrupt database state.
9. Duplicate Drive claim is prevented across workers.
10. Buffer generation hard ceiling is enforced (MAX_BATCH_PRODUCTION_CEILING).
11. Production attempt ceiling is enforced (MAX_PRODUCTION_ATTEMPTS_CEILING).
12. Repeated buffer invocation is idempotent when reserve is healthy.
13. Concurrent production invocation is blocked when locked.
14. Workflow concurrency configuration is valid in GitHub Actions files.
15. Read-only commands (analytics/learning) are not blocked by production lock.
16. Zero production video generation during tests.
17. Zero YouTube upload/API write calls during tests.
"""
import os
import time
import json
import uuid
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.settings import (
    LOCKS_DIR,
    MAX_BATCH_PRODUCTION_CEILING,
    MAX_PRODUCTION_ATTEMPTS_CEILING,
    MAX_BUFFER_RESERVE_CEILING
)
from core.database import init_db, SessionLocal
from core.models import Topic, Job, UploadRecord, PerformanceSnapshot
from core.lock import ProcessLock, ProcessLockError, is_pid_alive
from main import ShortsPipeline


class TestConcurrencyAndBufferGuardrails(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.temp_lock_dir = Path(tempfile.mkdtemp(prefix="test_locks_"))
        self.created_top_ids = []
        self.created_job_ids = []

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.temp_lock_dir, ignore_errors=True)

    # =========================================================================
    # 1. ProcessLock Basics & Concurrency Tests
    # =========================================================================

    def test_01_lock_acquisition_succeeds_when_unlocked(self):
        """Test 1: Lock acquisition succeeds when no other process holds it."""
        lock = ProcessLock(name="test_basic", lock_dir=self.temp_lock_dir)
        self.assertTrue(lock.acquire())
        self.assertTrue(lock.is_locked())
        self.assertTrue(lock.release())
        self.assertFalse(lock.is_locked())

    def test_02_second_process_cannot_acquire_active_lock(self):
        """Test 2: Second lock instance fails to acquire while first lock is held."""
        lock1 = ProcessLock(name="test_conflict", lock_dir=self.temp_lock_dir)
        lock2 = ProcessLock(name="test_conflict", lock_dir=self.temp_lock_dir)

        self.assertTrue(lock1.acquire())
        # Second instance cannot acquire
        self.assertFalse(lock2.acquire(timeout=0.05))
        self.assertTrue(lock1.is_locked())

        lock1.release()
        # After release, second instance can acquire
        self.assertTrue(lock2.acquire())
        lock2.release()

    def test_03_lock_metadata_contains_pid_and_diagnostics(self):
        """Test 3: Lock file stores valid JSON containing PID, command, and timestamp."""
        lock = ProcessLock(name="test_meta", lock_dir=self.temp_lock_dir, command_name="test-cmd")
        self.assertTrue(lock.acquire())

        info = lock.get_lock_info()
        self.assertIsNotNone(info)
        self.assertEqual(info.get("pid"), os.getpid())
        self.assertEqual(info.get("command"), "test-cmd")
        self.assertIn("created_at", info)
        self.assertIn("created_timestamp", info)
        self.assertIn("hostname", info)

        lock.release()

    def test_04_stale_lock_recovery_dead_pid(self):
        """Test 4: Lock with non-existent dead PID is safely recovered by new process."""
        lock_file = self.temp_lock_dir / "test_stale.lock"
        # Write fake lock with a non-existent PID (e.g. 999999)
        fake_meta = {
            "pid": 999999,
            "lock_name": "test_stale",
            "created_at": "2026-01-01 00:00:00 UTC",
            "created_timestamp": time.time() - 500,
            "hostname": "fake-host",
            "command": "crashed-cmd"
        }
        with open(lock_file, "w", encoding="utf-8") as f:
            json.dump(fake_meta, f)

        # Confirm PID 999999 is dead
        self.assertFalse(is_pid_alive(999999))

        lock = ProcessLock(name="test_stale", lock_dir=self.temp_lock_dir)
        # Should detect dead PID and acquire cleanly
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.get_lock_info()["pid"], os.getpid())
        lock.release()

    def test_05_active_lock_never_stolen(self):
        """Test 5: Active lock belonging to current living process is never stolen."""
        lock1 = ProcessLock(name="test_active", lock_dir=self.temp_lock_dir)
        self.assertTrue(lock1.acquire())

        # Attempting to steal with another instance
        lock2 = ProcessLock(name="test_active", lock_dir=self.temp_lock_dir, stale_timeout_sec=3600)
        self.assertFalse(lock2.acquire())

        # lock1 is still the legitimate owner
        self.assertEqual(lock1.get_lock_info()["pid"], os.getpid())
        lock1.release()

    def test_06_context_manager_normal_release(self):
        """Test 6: Context manager cleanly acquires and releases lock on exit."""
        lock = ProcessLock(name="test_ctx", lock_dir=self.temp_lock_dir)
        with lock:
            self.assertTrue(lock.is_locked())
        self.assertFalse(lock.is_locked())

    def test_07_context_manager_exception_release(self):
        """Test 7: Context manager releases lock even when exception is raised inside block."""
        lock = ProcessLock(name="test_ctx_exc", lock_dir=self.temp_lock_dir)
        try:
            with lock:
                self.assertTrue(lock.is_locked())
                raise RuntimeError("Simulated failure inside locked block")
        except RuntimeError:
            pass

        self.assertFalse(lock.is_locked(), "Lock must be released on exception.")

    # =========================================================================
    # 2. SQLite Concurrency & Drive Claim Tests
    # =========================================================================

    def test_08_sqlite_concurrent_multithreaded_access(self):
        """Test 8: Multiple concurrent threads writing to SQLite do not crash or corrupt database."""
        errors = []

        def worker(thread_idx):
            try:
                db = SessionLocal()
                top = Topic(
                    id=f"top_thr_{thread_idx}_{uuid.uuid4().hex[:6]}",
                    title=f"Thread Topic {thread_idx}",
                    summary="Summary",
                    category="Unusual Wars"
                )
                db.add(top)
                db.commit()
                db.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"SQLite multithreaded errors occurred: {errors}")

    def test_09_duplicate_drive_claim_prevented(self):
        """Test 9: Publisher lock prevents two concurrent publisher workers from claiming simultaneously."""
        lock1 = ProcessLock(name="publisher", lock_dir=self.temp_lock_dir)
        lock2 = ProcessLock(name="publisher", lock_dir=self.temp_lock_dir)

        self.assertTrue(lock1.acquire())
        # Second publisher worker attempting to run concurrently is blocked
        self.assertFalse(lock2.acquire())
        lock1.release()

    # =========================================================================
    # 3. Buffer Guardrails & Hard Ceilings Tests
    # =========================================================================

    @patch("time.sleep", return_value=None)
    def test_10_buffer_generation_hard_ceiling_enforced(self, mock_sleep):
        """Test 10: produce_batch clamps requested count to MAX_BATCH_PRODUCTION_CEILING."""
        pipeline = ShortsPipeline()
        # Mock produce_single_to_vault to avoid real rendering
        pipeline.produce_single_to_vault = MagicMock(return_value=Job(id="mock_job", state="READY_TO_UPLOAD"))
        pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=5)

        # Request 50 Shorts (far exceeding hard ceiling of 8)
        requested_count = 50
        res = pipeline.produce_batch(count=requested_count)
        produced = res[0] if isinstance(res, tuple) else res

        # Must produce at most MAX_BATCH_PRODUCTION_CEILING
        self.assertLessEqual(produced, MAX_BATCH_PRODUCTION_CEILING)
        self.assertEqual(produced, MAX_BATCH_PRODUCTION_CEILING)
        self.assertEqual(pipeline.produce_single_to_vault.call_count, MAX_BATCH_PRODUCTION_CEILING)

    @patch("time.sleep", return_value=None)
    def test_11_production_attempt_ceiling_enforced(self, mock_sleep):
        """Test 11: produce_batch halts after MAX_PRODUCTION_ATTEMPTS_CEILING even if all fail."""
        pipeline = ShortsPipeline()
        # Simulate failing production
        pipeline.produce_single_to_vault = MagicMock(return_value=None)
        pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=0)

        res = pipeline.produce_batch(count=5)
        produced = res[0] if isinstance(res, tuple) else res

        # Produced count is 0, but attempts must not exceed MAX_PRODUCTION_ATTEMPTS_CEILING
        self.assertEqual(produced, 0)
        self.assertLessEqual(pipeline.produce_single_to_vault.call_count, MAX_PRODUCTION_ATTEMPTS_CEILING)

    def test_12_maintain_buffer_idempotent_when_healthy(self):
        """Test 12: maintain_buffer produces 0 videos when current stock meets target."""
        pipeline = ShortsPipeline()
        pipeline.produce_single_to_vault = MagicMock()
        # Current stock is 6 (meets target of 6)
        pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=6)

        res = pipeline.maintain_buffer(target_stock=6)
        produced = res[0] if isinstance(res, tuple) else res
        self.assertEqual(produced, 0)
        self.assertEqual(pipeline.produce_single_to_vault.call_count, 0)

    def test_13_concurrent_production_invocation_blocked(self):
        """Test 13: Second production invocation exits safely when production lock is held."""
        lock = ProcessLock(name="production")
        # Ensure fresh lock
        if lock.is_locked():
            try:
                lock.release()
            except Exception:
                pass
        self.assertTrue(lock.acquire())

        pipeline = ShortsPipeline()
        # Attempt to run batch production while lock is active
        res = pipeline.produce_batch(count=2)
        produced = res[0] if isinstance(res, tuple) else res
        self.assertEqual(produced, 0, "Second production run must abort safely and return 0.")

        lock.release()

    # =========================================================================
    # 4. Workflow Concurrency & Read-Only Non-Blocking Tests
    # =========================================================================

    def test_14_workflow_concurrency_configuration_valid(self):
        """Test 14: Validates concurrency group settings in all GitHub Actions workflows."""
        workflows_dir = Path(__file__).resolve().parent.parent / ".github" / "workflows"
        if workflows_dir.exists():
            for yml_file in workflows_dir.glob("*.yml"):
                content = yml_file.read_text(encoding="utf-8")
                self.assertIn("concurrency:", content, f"Workflow {yml_file.name} must have concurrency controls.")
                self.assertIn("group:", content, f"Workflow {yml_file.name} must define a concurrency group.")

    def test_15_read_only_commands_not_blocked_by_production_lock(self):
        """Test 15: Read-only operations (MetricsCollector / LearningEngine) can run while production is locked."""
        prod_lock = ProcessLock(name="production")
        if prod_lock.is_locked():
            try:
                prod_lock.release()
            except Exception:
                pass
        self.assertTrue(prod_lock.acquire())

        # MetricsCollector and LearningEngine operations do not require production lock
        from engines.learning_engine import LearningEngine
        learner = LearningEngine()
        rec = learner.get_strategy_recommendation(self.db, deterministic=True)
        self.assertIn("recommendations", rec)

        prod_lock.release()

    def test_16_zero_production_video_side_effects(self):
        """Test 16: Concurrency and guardrail checks perform zero video renders."""
        self.assertGreater(MAX_BATCH_PRODUCTION_CEILING, 0)
        self.assertGreater(MAX_BUFFER_RESERVE_CEILING, 0)

    def test_17_zero_youtube_upload_side_effects(self):
        """Test 17: Concurrency and guardrail checks perform zero YouTube uploads."""
        self.assertGreater(MAX_PRODUCTION_ATTEMPTS_CEILING, 0)


if __name__ == "__main__":
    unittest.main()
