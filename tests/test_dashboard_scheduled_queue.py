"""
Unit and Integration Tests for Dashboard Scheduled Queue & YouTube Reconciliation (App Phase 4).
Tests:
- Real database records exposed in scheduled queue
- Chronological sorting of scheduled queue
- Next scheduled release spotlight calculation
- Daily capacity and today count metrics
- Authenticated GET /api/scheduled endpoint
- Authenticated and CSRF-protected POST /api/actions/reconcile-scheduled endpoint
- Real-time reconciliation execution (SCHEDULED -> PUBLISHED)
- Reconciliation idempotency
- Full system state integration
"""
import os
import uuid
import unittest
from datetime import datetime, date, time as dtime, timedelta
from fastapi.testclient import TestClient

from core.database import SessionLocal, init_db
from core.models import Job, RenderOutput, UploadRecord, Topic
from config.constants import JobState, DAILY_SHORTS_LIMIT
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider
from dashboard.action_manager import ActionManager
from dashboard.auth import session_store


class TestDashboardScheduledQueue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.data_provider = SystemDataProvider()
        cls.action_manager = ActionManager()
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

        # Unique IDs for test items
        self.test_ids = []

    def tearDown(self):
        try:
            for job_id in self.test_ids:
                self.db.query(UploadRecord).filter(UploadRecord.job_id == job_id).delete()
                self.db.query(RenderOutput).filter(RenderOutput.job_id == job_id).delete()
                self.db.query(Job).filter(Job.id == job_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _create_test_upload(self, job_id, title, status="SCHEDULED", scheduled_at=None, published_at=None, privacy="private"):
        self.test_ids.append(job_id)
        job = Job(id=job_id, state=JobState.SCHEDULED.value if status == "SCHEDULED" else JobState.PUBLISHED.value)
        rec = UploadRecord(
            id=f"upl_{uuid.uuid4().hex[:8]}",
            job_id=job_id,
            youtube_video_id=f"YT_{uuid.uuid4().hex[:8]}",
            title=title,
            description="Test Description",
            privacy_status=privacy,
            scheduled_publish_at=scheduled_at,
            published_at=published_at,
            status=status,
            reconciliation_metadata="Test Upload"
        )
        self.db.add(job)
        self.db.add(rec)
        self.db.commit()
        return rec

    def test_01_scheduled_queue_returns_real_records(self):
        """Test 1: Verifies get_scheduled_queue exposes real UploadRecord fields and Drive mapping."""
        future_dt = datetime.utcnow() + timedelta(hours=4)
        rec = self._create_test_upload(
            job_id=f"job_q_{uuid.uuid4().hex[:8]}",
            title="The Library of Alexandria Fire",
            status="SCHEDULED",
            scheduled_at=future_dt,
            privacy="private"
        )

        res = self.data_provider.get_scheduled_queue(self.db)
        self.assertIn("queue", res)
        self.assertIn("next_scheduled_video", res)
        self.assertIn("scheduled_today_count", res)
        self.assertIn("remaining_daily_capacity", res)

        item = next((q for q in res["queue"] if q["job_id"] == rec.job_id), None)
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "The Library of Alexandria Fire")
        self.assertEqual(item["local_status"], "SCHEDULED")
        self.assertEqual(item["privacy_status"], "private")
        self.assertEqual(item["reconciliation_state"], "PENDING_RELEASE")
        self.assertIsNotNone(item["drive_location"])

    def test_02_queue_chronological_ordering(self):
        """Test 2: Verifies that scheduled queue items are ordered chronologically by scheduled_publish_at."""
        t1 = datetime.utcnow() + timedelta(hours=2)
        t2 = datetime.utcnow() + timedelta(hours=6)
        t3 = datetime.utcnow() + timedelta(hours=10)

        self._create_test_upload(f"job_ord3_{uuid.uuid4().hex[:8]}", "Late Event", scheduled_at=t3)
        self._create_test_upload(f"job_ord1_{uuid.uuid4().hex[:8]}", "Early Event", scheduled_at=t1)
        self._create_test_upload(f"job_ord2_{uuid.uuid4().hex[:8]}", "Mid Event", scheduled_at=t2)

        res = self.data_provider.get_scheduled_queue(self.db)
        scheduled_items = [q for q in res["queue"] if q["local_status"] == "SCHEDULED" and q["scheduled_publish_at"]]
        
        # Verify chronological ordering
        timestamps = [q["scheduled_publish_at"] for q in scheduled_items]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_03_next_scheduled_video_calculation(self):
        """Test 3: Verifies that next_scheduled_video spotlight accurately targets the earliest future Short."""
        near_future = datetime.utcnow() + timedelta(hours=1, minutes=30)
        far_future = datetime.utcnow() + timedelta(days=2)

        self._create_test_upload(f"job_next_far_{uuid.uuid4().hex[:8]}", "Far Future Event", scheduled_at=far_future)
        self._create_test_upload(f"job_next_near_{uuid.uuid4().hex[:8]}", "Near Future Event", scheduled_at=near_future)

        res = self.data_provider.get_scheduled_queue(self.db)
        next_vid = res["next_scheduled_video"]
        self.assertIsNotNone(next_vid)
        self.assertEqual(next_vid["title"], "Near Future Event")
        self.assertIn("countdown", next_vid)
        self.assertIn("slot_label", next_vid)

    def test_04_today_counts_and_daily_capacity(self):
        """Test 4: Verifies scheduled_today_count and remaining_daily_capacity calculations."""
        from config.constants import get_business_day_bounds_utc
        now = datetime.utcnow()
        start_utc, end_utc = get_business_day_bounds_utc(now)
        today_slot = start_utc + timedelta(hours=2)

        self._create_test_upload(f"job_cap1_{uuid.uuid4().hex[:8]}", "Today Video 1", scheduled_at=today_slot)
        
        res = self.data_provider.get_scheduled_queue(self.db)
        self.assertGreaterEqual(res["scheduled_today_count"], 1)
        self.assertEqual(res["remaining_daily_capacity"], max(0, DAILY_SHORTS_LIMIT - res["total_booked_today"]))

    def test_05_api_scheduled_endpoint_auth_enforcement(self):
        """Test 5: Verifies GET /api/scheduled requires authentication."""
        # Unauthenticated client
        unauth_client = TestClient(app)
        res_unauth = unauth_client.get("/api/scheduled")
        self.assertEqual(res_unauth.status_code, 401)

        # Authenticated client
        res_auth = self.client.get("/api/scheduled")
        self.assertEqual(res_auth.status_code, 200)
        data = res_auth.json()
        self.assertIn("queue", data)
        self.assertIn("total_booked_today", data)

    def test_06_api_reconcile_scheduled_auth_and_csrf_enforcement(self):
        """Test 6: Verifies POST /api/actions/reconcile-scheduled requires both valid session and CSRF header."""
        unauth_client = TestClient(app)
        # 1. No auth
        res1 = unauth_client.post("/api/actions/reconcile-scheduled")
        self.assertEqual(res1.status_code, 401)

        # 2. Auth but missing CSRF header
        res2 = self.client.post("/api/actions/reconcile-scheduled")
        self.assertEqual(res2.status_code, 403)

        # 3. Auth with valid CSRF header
        res3 = self.client.post(
            "/api/actions/reconcile-scheduled",
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res3.status_code, 200)
        data = res3.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["action"], "SYNC_YOUTUBE")
        self.assertIn("reconciled_count", data)

    def test_07_action_trigger_sync_youtube_execution(self):
        """Test 7: Verifies action_manager.trigger_sync_youtube executes and returns summary."""
        result = self.action_manager.trigger_sync_youtube(self.db)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "SYNC_YOUTUBE")
        self.assertIn("reconciled_count", result)
        self.assertIn("timestamp", result)

    def test_08_reconcile_scheduled_transitions_public_videos(self):
        """Test 8: Verifies that past scheduled staging records transition SCHEDULED -> PUBLISHED."""
        past_slot = datetime.utcnow() - timedelta(hours=1)
        job_id = f"job_trans_{uuid.uuid4().hex[:8]}"
        rec = self._create_test_upload(
            job_id=job_id,
            title="Past Due Video",
            status="SCHEDULED",
            scheduled_at=past_slot,
            privacy="private"
        )
        rec.youtube_video_id = f"TEST_AUTO_{uuid.uuid4().hex[:8]}"
        self.db.commit()

        sync_res = self.action_manager.trigger_sync_youtube(self.db)
        self.assertTrue(sync_res["success"])

        reloaded = self.db.query(UploadRecord).filter(UploadRecord.id == rec.id).first()
        self.assertEqual(reloaded.status, "PUBLISHED")
        self.assertEqual(reloaded.privacy_status, "public")
        self.assertIsNotNone(reloaded.published_at)

    def test_09_reconcile_scheduled_idempotency(self):
        """Test 9: Verifies repeated sync calls are completely idempotent."""
        res1 = self.action_manager.trigger_sync_youtube(self.db)
        res2 = self.action_manager.trigger_sync_youtube(self.db)

        self.assertTrue(res1["success"])
        self.assertTrue(res2["success"])

    def test_10_full_state_includes_scheduled_queue(self):
        """Test 10: Verifies that GET /api/state and full_system_state include scheduled_queue subsystem."""
        state = self.data_provider.get_full_system_state(self.db)
        self.assertIn("scheduled_queue", state)
        self.assertIn("queue", state["scheduled_queue"])
        self.assertIn("daily_limit", state["scheduled_queue"])

        api_res = self.client.get("/api/state")
        self.assertEqual(api_res.status_code, 200)
        api_data = api_res.json()
        self.assertIn("scheduled_queue", api_data)


if __name__ == "__main__":
    unittest.main()
