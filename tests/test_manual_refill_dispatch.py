"""
Unit tests for Manual Buffer Refill Dispatch, Security Gate, Stock Health, and Duplicate Protection (App Phase 12).
"""
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from dashboard.app import app
from dashboard.auth import session_store, credentials_manager, PasswordHasher
from dashboard.github_client import GitHubWorkflowDispatcher


class TestManualRefillDispatch(unittest.TestCase):
    """Verifies all failure and success paths for the manual buffer refill pipeline."""

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

    def tearDown(self):
        credentials_manager.username = self._orig_username
        credentials_manager.hash_hex = self._orig_hash
        credentials_manager.salt_hex = self._orig_salt
        credentials_manager.is_configured = self._orig_configured

    def test_01_unauthenticated_major_action_requires_password(self):
        res = self.client.post(
            "/api/actions/produce",
            headers={"X-CSRF-Token": self.csrf_token},
            json={"count": 12, "target": 12}
        )
        self.assertEqual(res.status_code, 401)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "AUTH_REQUIRED")
        self.assertIn("password", data["error"].lower())

    def test_02_incorrect_password_rejected(self):
        res = self.client.post(
            "/api/actions/produce",
            headers={"X-CSRF-Token": self.csrf_token},
            json={"count": 12, "target": 12, "password": "wrong_password"}
        )
        self.assertEqual(res.status_code, 403)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "AUTH_FAILED")

    @patch("dashboard.action_manager.DriveVaultEngine.list_files_in_folder")
    def test_03_stock_healthy_rejects_refill(self, mock_list_files):
        mock_list_files.return_value = [{"id": f"file_{i}", "name": f"short_{i}.mp4"} for i in range(12)]

        res = self.client.post(
            "/api/actions/produce",
            headers={"X-CSRF-Token": self.csrf_token},
            json={"count": 12, "target": 12, "password": "adminpass123"}
        )
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "STOCK_HEALTHY")
        self.assertIn("healthy", data["error"].lower())
        self.assertEqual(data["current_stock"], 12)

    @patch("dashboard.action_manager.DriveVaultEngine.list_files_in_folder")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    def test_04_duplicate_refill_rejected_when_running(self, mock_active_run, mock_list_files):
        mock_list_files.return_value = [{"id": "file_1"}, {"id": "file_2"}]
        mock_active_run.return_value = {
            "id": 99912345,
            "status": "in_progress",
            "name": "YouTube Shorts Cloud Buffer Producer"
        }

        res = self.client.post(
            "/api/actions/produce",
            headers={"X-CSRF-Token": self.csrf_token},
            json={"count": 12, "target": 12, "password": "adminpass123"}
        )
        self.assertEqual(res.status_code, 409)
        data = res.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["status"], "REFILL_ALREADY_RUNNING")
        self.assertEqual(data["active_run_id"], 99912345)

    @patch("dashboard.action_manager.DriveVaultEngine.list_files_in_folder")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.get_active_workflow_run")
    @patch("dashboard.github_client.GitHubWorkflowDispatcher.dispatch_workflow")
    def test_05_successful_dispatch_contract(self, mock_dispatch, mock_active_run, mock_list_files):
        mock_list_files.return_value = [{"id": "file_1"}, {"id": "file_2"}]
        mock_active_run.return_value = None
        mock_dispatch.return_value = {
            "success": True,
            "status": "DISPATCH_ACCEPTED",
            "action": "DISPATCH_ACCEPTED",
            "workflow": "produce_buffer.yml",
            "workflow_name": "01 Buffer Producer",
            "repository": "jishanh776600-svg/yt-automation",
            "ref": "main",
            "message": "Cloud workflow '01 Buffer Producer' dispatch accepted by GitHub Actions.",
            "dispatch_requested_at": "2026-08-29T21:00:00Z",
            "status_code": 204
        }

        res = self.client.post(
            "/api/actions/produce",
            headers={"X-CSRF-Token": self.csrf_token},
            json={"count": 12, "target": 12, "password": "adminpass123"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["status"], "DISPATCH_ACCEPTED")
        self.assertEqual(data["workflow"], "produce_buffer.yml")

    def test_06_missing_github_pat_returns_explicit_failure(self):
        dispatcher = GitHubWorkflowDispatcher(pat="")
        res = dispatcher.dispatch_workflow("produce_buffer.yml")
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "DISPATCH_FAILED")
        self.assertEqual(res["status_code"], 500)
        self.assertIn("PAT", res["error"])

    def test_07_invalid_workflow_file_rejected(self):
        dispatcher = GitHubWorkflowDispatcher(pat="valid_pat_123", owner="owner", repo="repo")
        res = dispatcher.dispatch_workflow("malicious_workflow.yml")
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "DISPATCH_REJECTED")
        self.assertEqual(res["status_code"], 400)
        self.assertIn("whitelist", res["error"].lower())

    def test_08_workflow_status_endpoint_returns_valid_structure(self):
        res = self.client.get("/api/workflows/status/produce_buffer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["workflow"], "produce_buffer.yml")
        self.assertIn("is_active", data)
        self.assertIn("latest_run", data)


if __name__ == "__main__":
    unittest.main()
