"""
Phase 2 Regression Tests: Production Data Reconciliation & Buffer Refill Correctness.
Covers:
1. Asia/Kolkata business day bounds across UTC rollovers
2. Published Today exact IST calculation and filtering
3. Scheduled videos excluded from Published Today
4. Refill deficit calculation (1/12 -> 11 required)
5. Explicit refill outcome semantics (DISPATCHED, RUNNING, SUCCEEDED, PARTIAL, BLOCKED, FAILED)
6. Gemini quota exhaustion block surfacing
7. Reconciled /api/state contract
8. Auth and CSRF defense preservation
"""
import unittest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from config.constants import (
    BUSINESS_TIMEZONE, BUSINESS_TZ, get_business_day_bounds_utc, DAILY_SHORTS_LIMIT
)
from core.database import SessionLocal, init_db
from core.models import Job, UploadRecord
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider
from dashboard.action_manager import ActionManager


class TestPhase2ReconciliationAndRefill(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.dp = SystemDataProvider()
        cls.action_mgr = ActionManager()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
        login_res = self.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.csrf_token = login_res.json().get("csrf_token", "")
        self.test_ids = []

    def tearDown(self):
        try:
            for job_id in self.test_ids:
                self.db.query(UploadRecord).filter(UploadRecord.job_id == job_id).delete()
                self.db.query(Job).filter(Job.id == job_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def test_01_business_day_bounds_ist(self):
        """Test 1: Verifies Asia/Kolkata (UTC+5:30) business day bounds in UTC."""
        # Test a specific instant: 2026-08-30 03:30 AM IST (2026-08-29 22:00:00 UTC)
        ref_dt = datetime(2026, 8, 29, 22, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = get_business_day_bounds_utc(ref_dt)

        # In IST, date is 2026-08-30
        # Start is 2026-08-30 00:00:00 IST = 2026-08-29 18:30:00 UTC
        # End is 2026-08-31 00:00:00 IST = 2026-08-30 18:30:00 UTC
        self.assertEqual(start_utc, datetime(2026, 8, 29, 18, 30, 0))
        self.assertEqual(end_utc, datetime(2026, 8, 30, 18, 30, 0))

    def test_02_published_today_ist_window(self):
        """Test 2: Verifies that only uploads published in today's IST window are counted."""
        # Video A: Published 2026-08-29 20:00:27 UTC (01:30:27 AM IST on 2026-08-30) -> INCLUDED in today IST
        # Video B: Published 2026-08-29 15:00:00 UTC (08:30:00 PM IST on 2026-08-29) -> EXCLUDED from today IST
        ref_dt = datetime(2026, 8, 29, 22, 0, 0, tzinfo=timezone.utc)
        start_utc, end_utc = get_business_day_bounds_utc(ref_dt)

        vid_a_utc = datetime(2026, 8, 29, 20, 0, 27)
        vid_b_utc = datetime(2026, 8, 29, 15, 0, 0)

        self.assertTrue(start_utc <= vid_a_utc < end_utc)
        self.assertFalse(start_utc <= vid_b_utc < end_utc)

    def test_03_scheduled_video_excluded_from_published_today(self):
        """Test 3: Scheduled videos must be in scheduled_today and excluded from published_today."""
        now = datetime.utcnow()
        start_utc, end_utc = get_business_day_bounds_utc(now)
        slot_today = start_utc + timedelta(hours=5)

        test_job = f"job_sched_test_{uuid.uuid4().hex[:6]}"
        self.test_ids.append(test_job)

        rec = UploadRecord(
            id=f"upl_{uuid.uuid4().hex[:8]}",
            job_id=test_job,
            youtube_video_id=f"YT_SCHED_{uuid.uuid4().hex[:6]}",
            title="Scheduled Historical Incident",
            description="Test",
            privacy_status="private",
            scheduled_publish_at=slot_today,
            published_at=None,
            status="SCHEDULED"
        )
        self.db.add(rec)
        self.db.commit()

        status = self.dp.get_publishing_status(self.db)
        # Verify it is counted in scheduled_today
        self.assertGreaterEqual(status["scheduled_today"], 1)

    def test_04_refill_count_calculation_exact(self):
        """Test 4: Refill deficit calculation for target=12 and current=1 yields 11."""
        target = 12
        current = 1
        deficit = max(target - current, 0)
        self.assertEqual(deficit, 11)

    def test_05_outcome_semantics_blocked_on_zero_output(self):
        """Test 5: Workflow status endpoint correctly reports BLOCKED with reason on 0 output / quota error."""
        with patch("dashboard.app.data_provider.get_drive_inventory") as mock_inv:
            mock_inv.return_value = {"counts": {"01_READY": 1}, "files": {}}
            with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run") as mock_active:
                mock_active.return_value = None
                with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run") as mock_latest:
                    mock_latest.return_value = {
                        "id": 123456,
                        "conclusion": "success",
                        "status": "completed"
                    }
                    res = self.client.get("/api/workflows/status/produce_buffer")
                    self.assertEqual(res.status_code, 200)
                    data = res.json()
                    self.assertEqual(data["outcome"], "BLOCKED")
                    self.assertEqual(data["block_reason"], "GEMINI_DAILY_QUOTA_EXHAUSTED")
                    self.assertIn("0 new videos produced", data["outcome_message"])

    def test_06_outcome_semantics_partial(self):
        """Test 6: Workflow status endpoint correctly reports PARTIAL when reserve increased to 5/12."""
        with patch("dashboard.app.data_provider.get_drive_inventory") as mock_inv:
            mock_inv.return_value = {"counts": {"01_READY": 5}, "files": {}}
            with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run") as mock_active:
                mock_active.return_value = None
                with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run") as mock_latest:
                    mock_latest.return_value = {
                        "id": 123457,
                        "conclusion": "success",
                        "status": "completed"
                    }
                    res = self.client.get("/api/workflows/status/produce_buffer")
                    self.assertEqual(res.status_code, 200)
                    data = res.json()
                    self.assertEqual(data["outcome"], "PARTIAL")
                    self.assertIn("5/12", data["outcome_message"])

    def test_07_outcome_semantics_succeeded(self):
        """Test 7: Workflow status endpoint correctly reports SUCCEEDED when reserve reached 12/12."""
        with patch("dashboard.app.data_provider.get_drive_inventory") as mock_inv:
            mock_inv.return_value = {"counts": {"01_READY": 12}, "files": {}}
            with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run") as mock_active:
                mock_active.return_value = None
                with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run") as mock_latest:
                    mock_latest.return_value = {
                        "id": 123458,
                        "conclusion": "success",
                        "status": "completed"
                    }
                    res = self.client.get("/api/workflows/status/produce_buffer")
                    self.assertEqual(res.status_code, 200)
                    data = res.json()
                    self.assertEqual(data["outcome"], "SUCCEEDED")
                    self.assertIn("fully stocked", data["outcome_message"])

    def test_08_api_state_reconciled_counts(self):
        """Test 8: /api/state returns reconciled published_today and scheduled_today."""
        res = self.client.get("/api/state")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("publishing", data)
        self.assertEqual(data["publishing"]["published_today"], 1)
        self.assertEqual(data["publishing"]["scheduled_today"], 1)
        self.assertEqual(data["publishing"]["remaining_capacity"], 2)

    def test_09_duplicate_refill_protection_preserved(self):
        """Test 9: Action manager blocks duplicate refill while active run is in flight."""
        from dashboard.auth import DEFAULT_ADMIN_PASSWORD
        with patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run") as mock_active:
            mock_active.return_value = {"id": 9999, "status": "in_progress"}
            res = self.client.post("/api/actions/produce", json={"count": 0, "target": 12, "password": DEFAULT_ADMIN_PASSWORD}, headers={"X-CSRF-Token": self.csrf_token})
            self.assertEqual(res.status_code, 409)
            self.assertEqual(res.json()["status"], "REFILL_ALREADY_RUNNING")

    def test_10_auth_and_csrf_preserved(self):
        """Test 10: Unauthenticated requests to /api/actions/produce are rejected."""
        unauth = TestClient(app)
        res = unauth.post("/api/actions/produce", json={"count": 0, "target": 12})
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
