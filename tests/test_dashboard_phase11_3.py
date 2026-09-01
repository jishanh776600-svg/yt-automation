"""
Unit and Integration Tests for AL AMR Phase 11.3
Tests:
- Standardized DOM Meta-Tag CSRF Token Retrieval (<meta name="csrf-token">)
- Removal of window.CSRF_TOKEN across all templates
- Cloud Workflow In-Flight Status Banner DOM elements & mechanics
- State-changing POST endpoint CSRF verification
- Cloud dispatch response contracts (DISPATCH_ACCEPTED)
- AL AMR branding consistency (AL AMR / الأمر) across Desktop, Mobile, Login
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from datetime import datetime

from core.database import SessionLocal, init_db
from dashboard.app import app
from dashboard.auth import session_store, SESSION_COOKIE_NAME, DEFAULT_ADMIN_USER
from dashboard.action_manager import ActionManager
from dashboard.data_provider import SystemDataProvider


class TestDashboardPhase113(unittest.TestCase):

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
        self.session_id, self.csrf_token = session_store.create_session(
            username=DEFAULT_ADMIN_USER,
            duration_hours=1
        )
        self.client = TestClient(app)
        self.client.cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        if hasattr(self, "session_id"):
            session_store.invalidate_session(self.session_id)

    def test_01_csrf_meta_tag_present_in_desktop_and_mobile(self):
        """Verify <meta name="csrf-token" content="..."> is rendered in both desktop and mobile templates."""
        # Desktop
        res_desk = self.client.get("/?desktop=true")
        self.assertEqual(res_desk.status_code, 200)
        self.assertIn(f'<meta name="csrf-token" content="{self.csrf_token}">', res_desk.text)

        # Mobile
        res_mob = self.client.get("/?mobile=true")
        self.assertEqual(res_mob.status_code, 200)
        self.assertIn(f'<meta name="csrf-token" content="{self.csrf_token}">', res_mob.text)

    def test_02_get_csrf_token_helper_defined_in_templates(self):
        """Verify getCsrfToken() function exists and window.CSRF_TOKEN is absent."""
        res_desk = self.client.get("/?desktop=true")
        self.assertEqual(res_desk.status_code, 200)
        self.assertIn("function getCsrfToken()", res_desk.text)
        self.assertNotIn("window.CSRF_TOKEN =", res_desk.text)

        res_mob = self.client.get("/?mobile=true")
        self.assertEqual(res_mob.status_code, 200)
        self.assertIn("function getCsrfToken()", res_mob.text)
        self.assertNotIn("window.CSRF_TOKEN =", res_mob.text)

    def test_03_cloud_workflow_banner_elements_present_desktop(self):
        """Verify Desktop index.html contains persistent in-flight status banner elements."""
        res = self.client.get("/?desktop=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn('id="cloud-workflow-banner"', html)
        self.assertIn('id="cloud-banner-badge"', html)
        self.assertIn('id="cloud-banner-workflow"', html)
        self.assertIn('id="cloud-banner-msg"', html)
        self.assertIn('id="cloud-banner-time"', html)
        self.assertIn('id="cloud-banner-elapsed"', html)
        self.assertIn('dismissCloudBanner()', html)

    def test_04_cloud_workflow_banner_elements_present_mobile(self):
        """Verify Mobile mobile.html contains in-flight status banner elements."""
        res = self.client.get("/?mobile=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn('id="mobile-cloud-banner"', html)
        self.assertIn('id="mobile-cloud-badge"', html)
        self.assertIn('id="mobile-cloud-workflow"', html)
        self.assertIn('id="mobile-cloud-msg"', html)
        self.assertIn('dismissMobileCloudBanner()', html)

    def test_05_csrf_protection_rejects_missing_or_invalid_tokens(self):
        """Verify state-changing POST requests reject invalid CSRF tokens with 403."""
        # 1. Missing CSRF header
        res_no_csrf = self.client.post("/api/config/voice", json={"voice_id": "am_adam"})
        self.assertEqual(res_no_csrf.status_code, 403)

        # 2. Invalid CSRF header
        res_bad_csrf = self.client.post(
            "/api/config/voice",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": "invalid_fake_token_12345"}
        )
        self.assertEqual(res_bad_csrf.status_code, 403)

        # 3. Valid CSRF header succeeds
        res_valid = self.client.post(
            "/api/config/voice",
            json={"voice_id": "am_adam"},
            headers={"X-CSRF-Token": self.csrf_token}
        )
        self.assertEqual(res_valid.status_code, 200)
        self.assertTrue(res_valid.json().get("success"))

    def test_06_cloud_workflow_dispatch_contract(self):
        """Verify cloud mode actions return DISPATCH_ACCEPTED without falsely claiming instant completion."""
        mock_dispatch_response = {
            "success": True,
            "action": "DISPATCH_ACCEPTED",
            "workflow": "produce_buffer.yml",
            "workflow_name": "01 Buffer Producer",
            "repository": "test_owner/test_repo",
            "ref": "main",
            "message": "Cloud workflow '01 Buffer Producer' dispatch queued successfully on GitHub Actions.",
            "dispatch_requested_at": datetime.utcnow().isoformat() + "Z",
            "status_code": 204
        }

        with patch("config.settings.CLOUD_MODE", True):
            with patch.object(self.action_manager.github_dispatcher, "dispatch_produce_buffer", return_value=mock_dispatch_response):
                with patch.object(self.action_manager.github_dispatcher, "get_active_workflow_run", return_value=None):
                    res = self.action_manager.trigger_buffer_production(self.db, count=1, target=12)
                    self.assertTrue(res["success"])
                    self.assertEqual(res["action"], "DISPATCH_ACCEPTED")
                    self.assertEqual(res["workflow"], "produce_buffer.yml")
                    self.assertIn("queued successfully", res["message"])

    def test_07_al_amr_branding_consistency(self):
        """Verify AL AMR product name and logo identity is consistent across Desktop, Mobile, and Login."""
        # 1. Desktop
        res_desk = self.client.get("/?desktop=true")
        self.assertEqual(res_desk.status_code, 200)
        self.assertIn("AL AMR", res_desk.text)
        self.assertIn("al_amr_logo.svg", res_desk.text)
        self.assertNotIn("HISTORIA", res_desk.text)
        self.assertNotIn("Mission Control", res_desk.text)

        # 2. Mobile
        res_mob = self.client.get("/?mobile=true")
        self.assertEqual(res_mob.status_code, 200)
        self.assertIn("AL AMR", res_mob.text)
        self.assertIn("al_amr_logo.svg", res_mob.text)
        self.assertNotIn("HISTORIA", res_mob.text)
        self.assertNotIn("Mission Control", res_mob.text)

        # 3. Login
        anon_client = TestClient(app)
        res_login = anon_client.get("/login")
        self.assertEqual(res_login.status_code, 200)
        self.assertIn("AL AMR", res_login.text)
        self.assertIn("al_amr_logo.svg", res_login.text)
        self.assertNotIn("HISTORIA", res_login.text)
        self.assertNotIn("Mission Control", res_login.text)
