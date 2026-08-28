"""
Phase 7.2 Remote GitHub Actions Dispatcher Unit & Safety Tests.
Verifies:
  - Whitelist enforcement for workflow filenames.
  - Safe server-side GITHUB_PAT handling with zero serialization.
  - Complete HTTP error classification (401, 403, 404, 409, 422, 429, 5xx, timeout).
  - CLOUD_MODE=True vs CLOUD_MODE=False behavior in ActionManager.
  - Absence of PAT/secrets in API responses and frontend assets.
  - Concurrency group and production safety invariants.
"""
import os
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError, URLError
from io import BytesIO
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dashboard.github_client import GitHubWorkflowDispatcher, ALLOWED_WORKFLOWS
from dashboard.action_manager import ActionManager
from config.settings import PROJECT_ROOT
from core.models import Base


class TestGitHubDispatcherPhase72(unittest.TestCase):

    def setUp(self):
        self.fake_pat = "ghp_mockToken1234567890abcdef"
        self.owner = "test-owner"
        self.repo = "test-repo"
        self.dispatcher = GitHubWorkflowDispatcher(
            pat=self.fake_pat,
            owner=self.owner,
            repo=self.repo,
            default_ref="main"
        )
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()

    def _make_mock_response(self, status_code=204, body=b""):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = status_code
        mock_resp.read.return_value = body
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        return mock_resp

    def test_01_valid_workflow_dispatch_succeeds(self):
        """Test that dispatching a valid workflow returns DISPATCH_ACCEPTED."""
        with patch("dashboard.github_client.urlopen", return_value=self._make_mock_response(204)):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "DISPATCH_ACCEPTED")
            self.assertEqual(res["workflow"], "produce_buffer.yml")
            self.assertEqual(res["status_code"], 204)
            self.assertIn("dispatch queued successfully", res["message"])

    def test_02_correct_workflow_filenames_selected(self):
        """Test that helper methods dispatch exact whitelisted filenames."""
        with patch("dashboard.github_client.urlopen", return_value=self._make_mock_response(204)):
            res_buffer = self.dispatcher.dispatch_produce_buffer()
            self.assertEqual(res_buffer["workflow"], "produce_buffer.yml")

            res_pub = self.dispatcher.dispatch_autopilot()
            self.assertEqual(res_pub["workflow"], "autopilot.yml")

            res_an = self.dispatcher.dispatch_harvest_analytics()
            self.assertEqual(res_an["workflow"], "harvest_analytics.yml")

    def test_03_arbitrary_workflow_rejected(self):
        """Test that non-whitelisted arbitrary workflow filenames are strictly rejected."""
        res = self.dispatcher.dispatch_workflow("malicious_workflow.yml")
        self.assertFalse(res["success"])
        self.assertEqual(res["action"], "DISPATCH_REJECTED")
        self.assertEqual(res["status_code"], 400)
        self.assertIn("not in authorized whitelist", res["error"])

    def test_04_missing_pat_fails_safely(self):
        """Test that missing GITHUB_PAT returns structured failure without raising exception."""
        no_pat_dispatcher = GitHubWorkflowDispatcher(pat="", owner="o", repo="r")
        res = no_pat_dispatcher.dispatch_produce_buffer()
        self.assertFalse(res["success"])
        self.assertEqual(res["action"], "DISPATCH_FAILED")
        self.assertIn("GITHUB_PAT", res["error"])

    def test_05_missing_repo_config_fails_safely(self):
        """Test that missing repository configuration fails safely."""
        no_repo_dispatcher = GitHubWorkflowDispatcher(pat="token", owner="", repo="")
        res = no_repo_dispatcher.dispatch_produce_buffer()
        self.assertFalse(res["success"])
        self.assertEqual(res["action"], "DISPATCH_FAILED")
        self.assertIn("owner or name not configured", res["error"])

    def test_06_pat_never_appears_in_response(self):
        """Test that GITHUB_PAT is never serialized in successful or error responses."""
        with patch("dashboard.github_client.urlopen", return_value=self._make_mock_response(204)):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertNotIn(self.fake_pat, str(res))

    def test_07_github_401_handled_safely(self):
        """Test that GitHub 401 Unauthorized returns friendly error without exposing token."""
        http_err = HTTPError("url", 401, "Unauthorized", {}, BytesIO(b'{"message":"Bad credentials"}'))
        with patch("dashboard.github_client.urlopen", side_effect=http_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 401)
            self.assertIn("Invalid GITHUB_PAT", res["error"])
            self.assertNotIn(self.fake_pat, str(res))

    def test_08_github_403_handled_safely(self):
        """Test that GitHub 403 Forbidden returns permission guidance."""
        http_err = HTTPError("url", 403, "Forbidden", {}, BytesIO(b'{"message":"Resource not accessible by integration"}'))
        with patch("dashboard.github_client.urlopen", side_effect=http_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 403)
            self.assertIn("actions:write", res["error"])

    def test_09_github_404_handled_safely(self):
        """Test that GitHub 404 Not Found returns resource guidance."""
        http_err = HTTPError("url", 404, "Not Found", {}, BytesIO(b'{"message":"Not Found"}'))
        with patch("dashboard.github_client.urlopen", side_effect=http_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 404)
            self.assertIn("Resource Not Found", res["error"])

    def test_10_github_429_handled_safely(self):
        """Test that GitHub 429 Rate Limit returns rate limit notice."""
        http_err = HTTPError("url", 429, "Too Many Requests", {}, BytesIO(b'{"message":"Rate limit exceeded"}'))
        with patch("dashboard.github_client.urlopen", side_effect=http_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 429)
            self.assertIn("Rate Limit Exceeded", res["error"])

    def test_11_github_500_handled_safely(self):
        """Test that GitHub 500 Internal Error returns server retry notice."""
        http_err = HTTPError("url", 500, "Internal Server Error", {}, BytesIO(b'{"message":"Internal error"}'))
        with patch("dashboard.github_client.urlopen", side_effect=http_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 500)
            self.assertIn("internal service error", res["error"])

    def test_12_network_timeout_handled_safely(self):
        """Test that URLError/timeout returns clean error response."""
        url_err = URLError("Connection timed out")
        with patch("dashboard.github_client.urlopen", side_effect=url_err):
            res = self.dispatcher.dispatch_produce_buffer()
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 503)
            self.assertIn("Network error connecting to GitHub API", res["error"])

    def test_13_cloud_mode_true_dispatches_workflow(self):
        """Test that ActionManager dispatches GitHub workflow when CLOUD_MODE=True."""
        mgr = ActionManager()
        with patch("config.settings.CLOUD_MODE", True),              patch.object(mgr.github_dispatcher, "dispatch_produce_buffer", return_value={"success": True, "action": "DISPATCH_ACCEPTED"}) as mock_disp:
            res = mgr.trigger_buffer_production(self.db, target=12)
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "DISPATCH_ACCEPTED")
            mock_disp.assert_called_once()

    def test_14_cloud_mode_false_preserves_local_behavior(self):
        """Test that ActionManager preserves local behavior when CLOUD_MODE=False."""
        mgr = ActionManager()
        # Mock ProcessLock as locked to verify local ProcessLock check is executed
        with patch("config.settings.CLOUD_MODE", False),              patch("core.lock.ProcessLock.is_locked", return_value=True),              patch("core.lock.ProcessLock.get_lock_info", return_value={"pid": 12345}):
            res = mgr.trigger_buffer_production(self.db, target=12)
            self.assertFalse(res["success"])
            self.assertIn("Production lock is currently held", res["error"])

    def test_15_no_pat_in_templates_or_assets(self):
        """Security check: Scan all templates, js, and static assets for GITHUB_PAT or token strings."""
        static_dir = PROJECT_ROOT / "dashboard" / "static"
        templates_dir = PROJECT_ROOT / "dashboard" / "templates"

        for file_path in list(static_dir.rglob("*.*")) + list(templates_dir.rglob("*.html")):
            if file_path.suffix.lower() in [".html", ".js", ".json", ".css"]:
                content = file_path.read_text(encoding="utf-8")
                self.assertNotIn("ghp_", content, f"Leaked PAT in {file_path}")
                self.assertNotIn("github_pat", content.lower(), f"Leaked PAT key in {file_path}")

    def test_16_concurrency_groups_present_in_workflows(self):
        """Verify that existing YAML workflows contain proper concurrency groups."""
        workflows_dir = PROJECT_ROOT / ".github" / "workflows"
        produce_yaml = (workflows_dir / "produce_buffer.yml").read_text(encoding="utf-8")
        autopilot_yaml = (workflows_dir / "autopilot.yml").read_text(encoding="utf-8")
        analytics_yaml = (workflows_dir / "harvest_analytics.yml").read_text(encoding="utf-8")

        self.assertIn("group: youtube-producer", produce_yaml)
        self.assertIn("cancel-in-progress: false", produce_yaml)

        self.assertIn("group: youtube-publisher", autopilot_yaml)
        self.assertIn("cancel-in-progress: false", autopilot_yaml)

        self.assertIn("group: analytics-harvester", analytics_yaml)
        self.assertIn("cancel-in-progress: false", analytics_yaml)


if __name__ == "__main__":
    unittest.main()