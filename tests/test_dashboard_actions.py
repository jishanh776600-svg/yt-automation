"""
Unit and Integration Tests for Real-World Dashboard Action Controls (App Phase 2).
Tests:
- Job retry mechanism (state transition FAILED/NEEDS_REVIEW -> QUEUED)
- Job quarantine mechanism (segregation to FAILED)
- ProcessLock inspection and safe stale/forced release
- Review queue retrieval
- FastAPI POST /api/actions/ endpoints validation and error handling
"""
import os
import uuid
import unittest
from datetime import datetime
from fastapi.testclient import TestClient

from core.database import get_db, SessionLocal
from core.models import Job, Topic, UploadRecord
from config.constants import JobState, DAILY_SHORTS_LIMIT
from core.lock import ProcessLock
from dashboard.app import app
from dashboard.action_manager import ActionManager


class TestDashboardActions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
        login_res = cls.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        cls.csrf_token = login_res.json().get("csrf_token", "")
        cls.manager = ActionManager()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        # Create a test job in NEEDS_REVIEW for testing
        self.test_topic = Topic(
            id=f"top_test_{uuid.uuid4().hex[:8]}",
            title="Test Action Topic",
            summary="Test summary",
            category="Documented Disasters",
            score=55.0,
            status="APPROVED"
        )
        self.test_job = Job(
            id=f"job_test_{uuid.uuid4().hex[:8]}",
            topic_id=self.test_topic.id,
            state=JobState.NEEDS_REVIEW.value,
            error_message="Test QA verification failed: low loudness",
            retry_count=0
        )
        self.db.add(self.test_topic)
        self.db.add(self.test_job)
        self.db.commit()

    def tearDown(self):
        # Clean up test records
        try:
            self.db.query(Job).filter(Job.id == self.test_job.id).delete()
            self.db.query(Topic).filter(Topic.id == self.test_topic.id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def test_01_retry_job_success(self):
        """Test 1: Verifies that retrying a NEEDS_REVIEW job transitions state to QUEUED."""
        result = self.manager.retry_job(self.db, self.test_job.id)
        self.assertTrue(result["success"])
        self.assertEqual(result["job_id"], self.test_job.id)
        self.assertEqual(result["previous_state"], JobState.NEEDS_REVIEW.value)
        self.assertEqual(result["new_state"], JobState.QUEUED.value)
        self.assertEqual(result["retry_count"], 1)

        # Confirm in DB
        reloaded = self.db.query(Job).filter(Job.id == self.test_job.id).first()
        self.assertEqual(reloaded.state, JobState.QUEUED.value)
        self.assertIsNone(reloaded.error_message)

    def test_02_retry_job_ineligible(self):
        """Test 2: Verifies that attempting to retry an active or published job is rejected."""
        self.test_job.state = JobState.PUBLISHED.value
        self.db.commit()

        result = self.manager.retry_job(self.db, self.test_job.id)
        self.assertFalse(result["success"])
        self.assertIn("not eligible for retry", result["error"])

    def test_03_quarantine_job(self):
        """Test 3: Verifies that quarantining a job moves it to FAILED with reason."""
        result = self.manager.quarantine_job(self.db, self.test_job.id, reason="Manual operator quarantine")
        self.assertTrue(result["success"])
        self.assertEqual(result["new_state"], "FAILED")

        # Confirm in DB
        reloaded = self.db.query(Job).filter(Job.id == self.test_job.id).first()
        self.assertEqual(reloaded.state, JobState.FAILED.value)
        self.assertIn("Manual operator quarantine", reloaded.error_message)

    def test_04_release_process_lock_stale_and_forced(self):
        """Test 4: Verifies releasing a mock stale/orphaned process lock."""
        lock = ProcessLock(name="production")
        # Create a mock lock file
        with open(lock.lock_file, "w", encoding="utf-8") as f:
            f.write('{"pid": 999999, "command": "mock_dead_process", "created_timestamp": 1000.0}')

        self.assertTrue(lock.lock_file.exists())

        # Release stale lock
        res = self.manager.release_process_lock("production", force=False)
        self.assertTrue(res["success"])
        self.assertTrue(res.get("was_stale", True))
        self.assertFalse(lock.lock_file.exists())

    def test_05_release_process_lock_active_protection(self):
        """Test 5: Verifies active PID lock cannot be released without force=True."""
        lock = ProcessLock(name="publisher")
        # Write our own live PID
        with open(lock.lock_file, "w", encoding="utf-8") as f:
            f.write(f'{{"pid": {os.getpid()}, "command": "test_process", "created_timestamp": {datetime.utcnow().timestamp()}}}')

        try:
            # Without force, should be rejected
            res_safe = self.manager.release_process_lock("publisher", force=False)
            self.assertFalse(res_safe["success"])
            self.assertIn("actively held", res_safe["error"])

            # With force=True, should succeed
            res_force = self.manager.release_process_lock("publisher", force=True)
            self.assertTrue(res_force["success"])
            self.assertTrue(res_force["forced"])
        finally:
            lock.lock_file.unlink(missing_ok=True)

    def test_06_review_queue_retrieval(self):
        """Test 6: Verifies review queue returns all NEEDS_REVIEW and FAILED jobs."""
        queue = self.manager.get_review_queue(self.db)
        self.assertIn("count", queue)
        self.assertIn("jobs", queue)
        self.assertGreaterEqual(queue["count"], 1)

        job_ids = [j["id"] for j in queue["jobs"]]
        self.assertIn(self.test_job.id, job_ids)

    def test_07_fastapi_action_endpoints_validation(self):
        """Test 7: Verifies FastAPI action routes handle payloads and enforce validations."""
        headers = {"X-CSRF-Token": self.csrf_token}

        # 1. Retry endpoint
        res = self.client.post("/api/actions/retry-job", json={"job_id": self.test_job.id}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # 2. Quarantine endpoint
        res = self.client.post("/api/actions/quarantine-job", json={"job_id": self.test_job.id, "reason": "Test"}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])

        # 3. Invalid lock name
        res = self.client.post("/api/actions/release-lock", json={"lock_name": "invalid_lock", "force": False}, headers=headers)
        self.assertEqual(res.status_code, 422)  # Pydantic validation error

        # 4. Valid lock name
        res = self.client.post("/api/actions/release-lock", json={"lock_name": "production", "force": True}, headers=headers)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])


if __name__ == "__main__":
    unittest.main()
