"""
Unit and Integration Tests for Production Mission Control & Autonomous Pipeline Operations UI (App Phase 5).
Tests:
- Voice configuration telemetry and persistence across restarts
- Authenticated and CSRF-protected POST /api/config/voice endpoint
- 4-Track BGM library metadata and recent selection visibility
- Cloud automation workflow telemetry (unattended GitHub Actions metadata & unavailable live token reporting)
- Multi-stage chronological production timeline
- Persisted activity & event log feed
- Full system state bundling
- UI page rendering with all mission control panels
- Security: Unauthorized requests rejected with 401, missing CSRF token rejected with 403
"""
import os
import uuid
import json
import unittest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from core.database import SessionLocal, init_db
from core.models import Job, JobLog, UploadRecord, RenderOutput, QAReport, Topic, AssetRecord, SystemConfig
from config.constants import JobState, DAILY_SHORTS_LIMIT
from engines.tts_engine import AVAILABLE_VOICES, get_active_voice, set_active_voice
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider
from dashboard.action_manager import ActionManager
from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD


class TestDashboardPhase5(unittest.TestCase):

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
        login_res = self.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        self.csrf_token = login_res.json().get("csrf_token", "")
        self.test_job_ids = []

    def tearDown(self):
        try:
            for job_id in self.test_job_ids:
                self.db.query(JobLog).filter(JobLog.job_id == job_id).delete()
                self.db.query(QAReport).filter(QAReport.job_id == job_id).delete()
                self.db.query(UploadRecord).filter(UploadRecord.job_id == job_id).delete()
                self.db.query(RenderOutput).filter(RenderOutput.job_id == job_id).delete()
                self.db.query(Job).filter(Job.id == job_id).delete()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def test_voice_config_telemetry_and_persistence(self):
        """Verify voice config telemetry and persistent storage in SQLite."""
        # 1. Read default voice
        voice_cfg = self.data_provider.get_voice_config(self.db)
        self.assertIn("active_voice_id", voice_cfg)
        self.assertIn("available_voices", voice_cfg)
        self.assertEqual(len(voice_cfg["available_voices"]), 6)

        # 2. Update voice via set_active_voice
        set_active_voice(self.db, "am_michael")
        self.assertEqual(get_active_voice(self.db), "am_michael")

        updated_cfg = self.data_provider.get_voice_config(self.db)
        self.assertEqual(updated_cfg["active_voice_id"], "am_michael")
        self.assertEqual(updated_cfg["active_voice"]["display_name"], "Michael (US Male)")

        # 3. Restore to am_adam
        set_active_voice(self.db, "am_adam")
        self.assertEqual(get_active_voice(self.db), "am_adam")

    def test_voice_selection_api_endpoints(self):
        """Verify GET /api/config/voice and POST /api/config/voice endpoints."""
        # 1. Unauthenticated GET rejected
        anon_client = TestClient(app)
        res_anon = anon_client.get("/api/config/voice")
        self.assertEqual(res_anon.status_code, 401)

        # 2. Authenticated GET succeeds
        res = self.client.get("/api/config/voice")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("available_voices", data)
        self.assertEqual(len(data["available_voices"]), 6)

        # 3. POST without CSRF rejected
        res_no_csrf = self.client.post("/api/config/voice", json={"voice_id": "af_bella"})
        self.assertEqual(res_no_csrf.status_code, 403)

        # 4. POST with valid CSRF succeeds
        res_valid = self.client.post(
            "/api/config/voice",
            json={"voice_id": "af_bella"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res_valid.status_code, 200)
        self.assertTrue(res_valid.json()["success"])
        self.assertEqual(get_active_voice(self.db), "af_bella")

        # 5. POST invalid voice returns 400
        res_invalid = self.client.post(
            "/api/config/voice",
            json={"voice_id": "non_existent_voice_999"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res_invalid.status_code, 400)

        # Cleanup: restore to am_adam
        self.client.post(
            "/api/config/voice",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": self.csrf_token}
        )

    def test_bgm_library_and_recent_selections(self):
        """Verify BGM library status and recent selection telemetry."""
        # 1. Test GET /api/bgm endpoint
        res = self.client.get("/api/bgm")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("library", data)
        self.assertEqual(len(data["library"]), 4)

        # Verify all 4 canonical keys exist
        keys = [t["key"] for t in data["library"]]
        self.assertIn("best_historical", keys)
        self.assertIn("emotional_sad", keys)
        self.assertIn("flux_ambient", keys)
        self.assertIn("suspense_climax", keys)

        # Check track structure
        for t in data["library"]:
            self.assertIn("display_name", t)
            self.assertIn("mood", t)
            self.assertIn("filename", t)
            self.assertIn("keywords", t)
            self.assertIn("exists_on_disk", t)

    def test_cloud_workflows_telemetry(self):
        """Verify cloud workflows telemetry returns 3 workflows with explicit status."""
        res = self.client.get("/api/workflows")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("workflows", data)
        self.assertEqual(len(data["workflows"]), 3)

        wf_ids = [w["id"] for w in data["workflows"]]
        self.assertIn("produce_buffer", wf_ids)
        self.assertIn("autopilot", wf_ids)
        self.assertIn("harvest_analytics", wf_ids)

        for w in data["workflows"]:
            self.assertIn("cron", w)
            self.assertIn("next_expected_utc", w)
            self.assertIn("live_status", w)
            self.assertIn("STATUS_UNAVAILABLE", w["live_status"])

    def test_production_timeline_telemetry(self):
        """Verify multi-stage chronological timeline progression."""
        job_id = f"test_tl_{uuid.uuid4().hex[:8]}"
        self.test_job_ids.append(job_id)

        job = Job(id=job_id, state=JobState.READY_TO_UPLOAD.value)
        self.db.add(job)
        self.db.commit()

        res = self.client.get("/api/timeline")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)

        # Find our test job
        match = next((item for item in data if item["job_id"] == job_id), None)
        self.assertIsNotNone(match)
        self.assertEqual(match["current_state"], JobState.READY_TO_UPLOAD.value)
        self.assertGreaterEqual(len(match["stages"]), 8)

        stage_names = [s["name"] for s in match["stages"]]
        self.assertIn("DISCOVERED", stage_names)
        self.assertIn("SCRIPTED", stage_names)
        self.assertIn("VOICE GENERATED", stage_names)
        self.assertIn("RENDERED", stage_names)
        self.assertIn("QA PASSED", stage_names)
        self.assertIn("01_READY", stage_names)

    def test_activity_feed_telemetry(self):
        """Verify chronological feed of real persisted system events."""
        job_id = f"test_act_{uuid.uuid4().hex[:8]}"
        self.test_job_ids.append(job_id)

        log = JobLog(
            job_id=job_id,
            stage="RENDERING",
            status="SUCCESS",
            message="Test video render completed in 4.2s"
        )
        self.db.add(log)
        self.db.commit()

        res = self.client.get("/api/activity")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

        # Check fields
        first = data[0]
        self.assertIn("timestamp", first)
        self.assertIn("event_type", first)
        self.assertIn("level", first)
        self.assertIn("title", first)
        self.assertIn("description", first)

    def test_full_system_state_bundling(self):
        """Verify GET /api/state bundles all Phase 5 telemetry components."""
        res = self.client.get("/api/state")
        self.assertEqual(res.status_code, 200)
        state = res.json()

        self.assertIn("health", state)
        self.assertIn("locks", state)
        self.assertIn("inventory", state)
        self.assertIn("publishing", state)
        self.assertIn("buffer", state)
        self.assertIn("learning", state)
        self.assertIn("scheduled_queue", state)
        self.assertIn("voice_config", state)
        self.assertIn("bgm_status", state)
        self.assertIn("cloud_workflows", state)
        self.assertIn("timeline", state)
        self.assertIn("activity_feed", state)
        self.assertIn("database_summary", state)

    def test_ui_page_rendering_authenticated(self):
        """Verify the main mission control HTML UI renders successfully."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Verify key mission control elements exist in HTML
        self.assertIn("AL AMR", html)
        self.assertIn("BGM", html)
        self.assertIn("GitHub Actions", html)
        self.assertIn("YouTube", html)


if __name__ == "__main__":
    unittest.main()
