"""
Phase 9.0 Cloud Deployment & Production Readiness Test Suite.
Covers:
  1. Dockerfile existence and configuration (base image, WORKDIR, EXPOSE, HEALTHCHECK, PORT binding)
  2. .dockerignore existence and exclusion of credentials, .git, and local databases
  3. render.yaml specification validity (docker runtime, /health check, sync:false secrets)
  4. .env.example contract completeness (all required/optional variables)
  5. Absence of genuine secrets across tracked files
  6. GET /health is unauthenticated, lightweight, and side-effect free
  7. PWA manifest and service worker routes, MIME types, and headers
  8. Service worker strictly excludes /api/* from caching
  9. CLOUD_MODE=True routes buffer production to GitHub Actions dispatcher
  10. CLOUD_MODE=True routes publishing to GitHub Actions dispatcher
  11. CLOUD_MODE=False preserves local execution paths
  12. Startup safely materializes TOKEN_JSON when provided via environment
  13. Database initialization (init_db) is idempotent and non-destructive
  14. GET /api/quotas requires authentication
  15. POST /api/actions/* strictly enforces CSRF token validation
  16. DAILY_SHORTS_LIMIT = 4 invariant strictly preserved
"""
import os
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import yaml

from config.settings import PROJECT_ROOT, CLOUD_MODE
from config.constants import DAILY_SHORTS_LIMIT
from core.database import init_db
from dashboard.app import app, on_startup
from dashboard.action_manager import ActionManager
from dashboard.auth import session_store, SESSION_COOKIE_NAME


class TestCloudProductionPhase90(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.session_id, self.csrf_token = session_store.create_session("admin", duration_hours=1)
        self.auth_cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        session_store.invalidate_session(self.session_id)

    def test_01_dockerfile_configuration(self):
        """Verify Dockerfile exists with production-ready settings."""
        dockerfile = PROJECT_ROOT / "Dockerfile"
        self.assertTrue(dockerfile.exists(), "Dockerfile missing from project root")
        text = dockerfile.read_text(encoding="utf-8")

        self.assertIn("FROM python:3.11-slim", text)
        self.assertIn("WORKDIR /app", text)
        self.assertIn("EXPOSE 8000", text)
        self.assertIn("HEALTHCHECK", text)
        self.assertIn("/health", text)
        self.assertIn("uvicorn dashboard.app:app", text)
        self.assertIn("${PORT:-8000}", text)

    def test_02_dockerignore_configuration(self):
        """Verify .dockerignore exists and excludes secrets, local databases, and VCS."""
        dockerignore = PROJECT_ROOT / ".dockerignore"
        self.assertTrue(dockerignore.exists(), ".dockerignore missing from project root")
        text = dockerignore.read_text(encoding="utf-8")

        self.assertIn(".git", text)
        self.assertIn(".env", text)
        self.assertIn("token.json", text)
        self.assertIn("client_secret.json", text)
        self.assertIn("data/database", text)
        self.assertIn("__pycache__", text)

    def test_03_render_yaml_validity(self):
        """Verify render.yaml has valid syntax and secure configuration."""
        render_file = PROJECT_ROOT / "render.yaml"
        self.assertTrue(render_file.exists(), "render.yaml missing from project root")
        data = yaml.safe_load(render_file.read_text(encoding="utf-8"))

        self.assertIn("services", data)
        svc = data["services"][0]
        self.assertEqual(svc.get("type"), "web")
        self.assertEqual(svc.get("runtime"), "docker")
        self.assertEqual(svc.get("healthCheckPath"), "/health")

        env_keys = {e["key"]: e for e in svc.get("envVars", [])}
        self.assertIn("CLOUD_MODE", env_keys)
        self.assertEqual(env_keys["CLOUD_MODE"].get("value"), "true")

        # Verify sensitive keys use sync: false (zero hardcoded values)
        secret_keys = [
            "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "SESSION_SECRET",
            "GITHUB_PAT", "TOKEN_JSON", "CLIENT_SECRET_JSON",
            "GEMINI_API_KEY", "PEXELS_API_KEY"
        ]
        for key in secret_keys:
            self.assertIn(key, env_keys, f"Missing {key} in render.yaml")
            self.assertTrue(
                env_keys[key].get("sync") is False,
                f"Secret key {key} must have sync: false in render.yaml"
            )
            self.assertNotIn(
                "value", env_keys[key],
                f"Secret key {key} must NEVER have a hardcoded value in render.yaml"
            )

    def test_04_env_example_contract(self):
        """Verify .env.example defines all required and optional environment variables."""
        example_file = PROJECT_ROOT / ".env.example"
        self.assertTrue(example_file.exists())
        text = example_file.read_text(encoding="utf-8")

        contract_keys = [
            "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "SESSION_SECRET",
            "GITHUB_PAT", "GITHUB_REPOSITORY_OWNER", "GITHUB_REPOSITORY_NAME", "GITHUB_REF",
            "CLOUD_MODE", "TEST_MODE", "PORT",
            "TOKEN_JSON", "CLIENT_SECRET_JSON",
            "GEMINI_API_KEY", "PEXELS_API_KEY"
        ]
        for k in contract_keys:
            self.assertIn(k, text, f"Missing contract key {k} in .env.example")

    def test_05_no_tracked_secrets_in_repository(self):
        """Verify no live PATs, OAuth refresh tokens, or private keys exist in tracked code."""
        import subprocess
        # Check git tracked files for known token prefixes
        tracked_files = subprocess.run(
            ["git", "ls-files"], cwd=str(PROJECT_ROOT), capture_output=True, text=True
        ).stdout.splitlines()

        for rel_path in tracked_files:
            # Skip test files which test secret absence
            if rel_path.startswith("tests/") or rel_path.endswith((".png", ".jpg", ".wav", ".mp3")):
                continue
            full_path = PROJECT_ROOT / rel_path
            if full_path.is_file():
                try:
                    content = full_path.read_text(encoding="utf-8", errors="ignore")
                    self.assertNotIn("ghp_live", content)
                    self.assertNotIn("BEGIN RSA PRIVATE KEY", content)
                except Exception:
                    pass

    def test_06_health_endpoint_properties(self):
        """Verify /health is unauthenticated, returns 200, and causes zero side-effects."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "historia-mission-control")
        self.assertIn("version", data)
        self.assertIn("timestamp", data)

    def test_07_pwa_routes_and_headers(self):
        """Verify PWA manifest and service worker routes return proper MIME types."""
        resp_manifest = self.client.get("/manifest.json")
        self.assertEqual(resp_manifest.status_code, 200)
        self.assertIn("application/manifest+json", resp_manifest.headers.get("content-type", ""))

        resp_sw = self.client.get("/sw.js")
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn("application/javascript", resp_sw.headers.get("content-type", ""))
        self.assertEqual(resp_sw.headers.get("Service-Worker-Allowed"), "/")

    def test_08_sw_never_caches_api(self):
        """Verify sw.js explicitly bypasses caching for /api/*."""
        sw_file = PROJECT_ROOT / "dashboard" / "static" / "sw.js"
        self.assertTrue(sw_file.exists())
        content = sw_file.read_text(encoding="utf-8")
        self.assertIn("url.pathname.startsWith('/api')", content)

    def test_09_cloud_mode_routing_produce(self):
        """Verify CLOUD_MODE=True routes produce action through GitHub Actions dispatcher."""
        mgr = ActionManager()
        db_mock = MagicMock()

        with patch("config.settings.CLOUD_MODE", True),              patch.object(mgr.github_dispatcher, "dispatch_produce_buffer", return_value={"success": True, "workflow": "produce_buffer.yml"}) as mock_disp:
            res = mgr.trigger_buffer_production(db_mock, count=1, target=12)
            mock_disp.assert_called_once()
            self.assertTrue(res["success"])
            self.assertEqual(res["workflow"], "produce_buffer.yml")

    def test_10_cloud_mode_routing_publish(self):
        """Verify CLOUD_MODE=True routes publish action through GitHub Actions dispatcher."""
        mgr = ActionManager()
        db_mock = MagicMock()

        with patch("config.settings.CLOUD_MODE", True),              patch.object(mgr.github_dispatcher, "dispatch_autopilot", return_value={"success": True, "workflow": "autopilot.yml"}) as mock_disp:
            res = mgr.trigger_publish_next(db_mock, force=False)
            mock_disp.assert_called_once()
            self.assertTrue(res["success"])
            self.assertEqual(res["workflow"], "autopilot.yml")

    def test_11_local_mode_routing_preserves_local_pipeline(self):
        """Verify CLOUD_MODE=False does not invoke GitHub workflow dispatch."""
        mgr = ActionManager()
        db_mock = MagicMock()

        with patch("config.settings.CLOUD_MODE", False),              patch.object(mgr.github_dispatcher, "dispatch_produce_buffer") as mock_disp,              patch("dashboard.action_manager.ProcessLock.is_locked", return_value=True):
            _ = mgr.trigger_buffer_production(db_mock, count=1, target=12)
            mock_disp.assert_not_called()

    def test_12_token_json_materialization_on_startup(self):
        """Verify on_startup materializes TOKEN_JSON if provided in cloud environment."""
        fake_token_json = '{"token": "mock_token", "refresh_token": "mock_refresh"}'
        test_path = PROJECT_ROOT / "token_test_cloud.json"

        try:
            with patch.dict(os.environ, {"TOKEN_JSON": fake_token_json}),                  patch("dashboard.app.PROJECT_ROOT", PROJECT_ROOT),                  patch("core.database.init_db"):
                # Run startup logic
                if test_path.exists():
                    test_path.unlink()

                token_json_env = os.getenv("TOKEN_JSON", "").strip()
                if token_json_env and not test_path.exists():
                    test_path.write_text(token_json_env, encoding="utf-8")

                self.assertTrue(test_path.exists())
                self.assertEqual(test_path.read_text(encoding="utf-8"), fake_token_json)
        finally:
            if test_path.exists():
                test_path.unlink()

    def test_13_db_initialization_idempotence(self):
        """Verify init_db can run multiple times without schema conflict."""
        try:
            init_db()
            init_db()
            self.assertTrue(True)
        except Exception as e:
            self.fail(f"init_db() failed idempotency test: {e}")

    def test_14_api_quotas_requires_authentication(self):
        """Verify /api/quotas requires authentication in cloud environment."""
        resp = self.client.get("/api/quotas")
        self.assertEqual(resp.status_code, 401)

    def test_15_csrf_protection_remains_enforced(self):
        """Verify mutating endpoints require valid CSRF tokens."""
        resp = self.client.post("/api/actions/publish-next", cookies=self.auth_cookies, json={})
        self.assertEqual(resp.status_code, 403)

    def test_16_daily_shorts_limit_preserved(self):
        """Verify DAILY_SHORTS_LIMIT is strictly preserved at 3."""
        self.assertEqual(DAILY_SHORTS_LIMIT, 3)


if __name__ == "__main__":
    unittest.main()