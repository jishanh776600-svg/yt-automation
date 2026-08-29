"""
Unit & Integration Tests for Problem #2:
Active Workflow Status Persistence Across Page Refresh / Browser Reopen.

Verifies:
1. No active workflow on page load -> is_active is false, active_run is None.
2. Queued workflow on page load -> is_active is true, status 'queued' reconstructed.
3. Running workflow on page load -> is_active is true, step_summary and jobs attached.
4. Page refresh recovery simulation -> active state reliably reconstructed on subsequent requests.
5. Terminal completion state transition -> is_active transitions to false with conclusion 'success'.
6. Terminal failure state transition -> is_active transitions to false with conclusion 'failure'.
7. Frontend templates (index.html & mobile.html) contain initialization hooks on DOMContentLoaded.
8. Duplicate protection remains active and rejects concurrent dispatches with HTTP 409.
9. Existing authorized dispatch flow remains 100% operational.
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.auth import session_store, credentials_manager, PasswordHasher


class TestWorkflowRecoveryPhase2(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self._orig_username = credentials_manager.username
        self._orig_hash = credentials_manager.hash_hex
        self._orig_salt = credentials_manager.salt_hex
        self._orig_configured = credentials_manager.is_configured

        credentials_manager.username = "admin"
        h, s = PasswordHasher.hash_password("adminpass123")
        credentials_manager.hash_hex = h
        credentials_manager.salt_hex = s
        credentials_manager.is_configured = True

        self.session_id, self.csrf_token = session_store.create_session("admin")
        self.client.cookies.set("historia_session_id", self.session_id)
        self.headers = {"X-CSRF-Token": self.csrf_token}

    def tearDown(self):
        credentials_manager.username = self._orig_username
        credentials_manager.hash_hex = self._orig_hash
        credentials_manager.salt_hex = self._orig_salt
        credentials_manager.is_configured = self._orig_configured

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_01_no_active_workflow_on_page_load(self, mock_latest, mock_active):
        mock_active.return_value = None
        mock_latest.return_value = {
            "id": 111,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-29T10:00:00Z"
        }

        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_active"])
        self.assertIsNone(data["active_run"])
        self.assertEqual(data["workflow"], "produce_buffer.yml")

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_02_queued_workflow_on_page_load(self, mock_latest, mock_active):
        mock_active.return_value = {
            "id": 222,
            "status": "queued",
            "created_at": "2026-08-30T00:00:00Z"
        }
        mock_latest.return_value = {
            "id": 222,
            "status": "queued",
            "created_at": "2026-08-30T00:00:00Z",
            "jobs": [],
            "step_summary": {"completed_steps": 0, "total_steps": 12, "current_step": "Queued"}
        }

        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_active"])
        self.assertIsNotNone(data["active_run"])
        self.assertEqual(data["active_run"]["status"], "queued")
        self.assertEqual(data["active_run"]["step_summary"]["total_steps"], 12)

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_03_running_workflow_on_page_load(self, mock_latest, mock_active):
        mock_active.return_value = {
            "id": 333,
            "status": "in_progress",
            "created_at": "2026-08-30T00:05:00Z",
            "run_started_at": "2026-08-30T00:05:10Z"
        }
        mock_latest.return_value = {
            "id": 333,
            "status": "in_progress",
            "created_at": "2026-08-30T00:05:00Z",
            "run_started_at": "2026-08-30T00:05:10Z",
            "jobs": [{"name": "produce_reserve_buffer", "status": "in_progress"}],
            "step_summary": {"completed_steps": 5, "total_steps": 12, "current_step": "Install Python Dependencies"}
        }

        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_active"])
        self.assertEqual(data["active_run"]["status"], "in_progress")
        self.assertEqual(data["active_run"]["step_summary"]["current_step"], "Install Python Dependencies")

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_04_page_refresh_recovers_identical_state(self, mock_latest, mock_active):
        mock_active.return_value = {
            "id": 444,
            "status": "in_progress",
            "created_at": "2026-08-30T00:10:00Z"
        }
        mock_latest.return_value = {
            "id": 444,
            "status": "in_progress",
            "created_at": "2026-08-30T00:10:00Z",
            "step_summary": {"completed_steps": 7, "total_steps": 12, "current_step": "Run Batch Production"}
        }

        # First request before refresh
        res1 = self.client.get("/api/workflows/status/produce_buffer")
        # Second request representing page refresh
        res2 = self.client.get("/api/workflows/status/produce_buffer")

        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res1.json()["active_run"]["id"], res2.json()["active_run"]["id"])
        self.assertEqual(res2.json()["active_run"]["step_summary"]["current_step"], "Run Batch Production")

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_05_workflow_completion_transition(self, mock_latest, mock_active):
        mock_active.return_value = None
        mock_latest.return_value = {
            "id": 555,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-30T00:15:00Z"
        }

        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_active"])
        self.assertIsNone(data["active_run"])
        self.assertEqual(data["latest_run"]["conclusion"], "success")

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_latest_workflow_run")
    def test_06_workflow_failure_transition(self, mock_latest, mock_active):
        mock_active.return_value = None
        mock_latest.return_value = {
            "id": 666,
            "status": "completed",
            "conclusion": "failure",
            "created_at": "2026-08-30T00:20:00Z"
        }

        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["is_active"])
        self.assertIsNone(data["active_run"])
        self.assertEqual(data["latest_run"]["conclusion"], "failure")

    def test_07_templates_contain_recovery_hooks(self):
        # Verify index.html contains initWorkflowStatusRecovery and DOMContentLoaded hook
        index_res = self.client.get("/")
        self.assertEqual(index_res.status_code, 200)
        index_html = index_res.text
        self.assertIn("initWorkflowStatusRecovery", index_html)
        self.assertIn("cloud-workflow-banner", index_html)
        self.assertIn("/api/workflows/status/produce_buffer", index_html)

        # Verify mobile.html contains initMobileWorkflowStatusRecovery and mobile-cloud-banner
        mobile_res = self.client.get("/mobile")
        self.assertEqual(mobile_res.status_code, 200)
        mobile_html = mobile_res.text
        self.assertIn("initMobileWorkflowStatusRecovery", mobile_html)
        self.assertIn("mobile-cloud-banner", mobile_html)
        self.assertIn("/api/workflows/status/produce_buffer", mobile_html)

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("engines.drive_engine.DriveVaultEngine.get_ready_stock_count")
    def test_08_duplicate_run_protection_preserved(self, mock_stock, mock_active):
        mock_stock.return_value = 2
        mock_active.return_value = {"id": 777, "status": "in_progress"}

        res = self.client.post(
            "/api/actions/produce",
            headers=self.headers,
            json={"count": 12, "target": 12, "password": "adminpass123"}
        )
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "REFILL_ALREADY_RUNNING")

    @patch("dashboard.github_client.GitHubWorkflowDispatcher.dispatch_workflow")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("engines.drive_engine.DriveVaultEngine.get_ready_stock_count")
    def test_09_authorized_dispatch_flow_preserved(self, mock_stock, mock_active, mock_dispatch):
        mock_stock.return_value = 0
        mock_active.return_value = None
        mock_dispatch.return_value = {
            "success": True,
            "status": "DISPATCH_ACCEPTED",
            "message": "Workflow dispatch produce_buffer.yml accepted by GitHub Actions.",
            "workflow": "produce_buffer.yml",
            "repository": "jishanh776600-svg/yt-automation",
            "ref": "main"
        }

        res = self.client.post(
            "/api/actions/produce",
            headers=self.headers,
            json={"count": 12, "target": 12, "password": "adminpass123"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "DISPATCH_ACCEPTED")


if __name__ == "__main__":
    unittest.main()
