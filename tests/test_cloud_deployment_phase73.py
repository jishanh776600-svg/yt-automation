"""
Phase 7.3 Cloud Deployment Configuration & Validation Tests.
Verifies:
  - Dockerfile structure, 0.0.0.0 binding, PORT variable, and zero secrets.
  - render.yaml blueprint structure, sync: false secret declarations, and zero hardcoded credentials.
  - .env.example template validity and placeholders.
  - Lightweight unauthenticated GET /health endpoint.
  - PWA endpoints (/manifest.json, /sw.js, /mobile).
  - Authentication, CSRF, and security preservation.
  - CLOUD_MODE dispatching vs local preservation.
  - Repository-wide secret leak prevention.
"""
import os
import unittest
from unittest.mock import patch, MagicMock
import yaml
from fastapi.testclient import TestClient

from config.settings import PROJECT_ROOT, CLOUD_MODE
from dashboard.app import app
from dashboard.auth import session_store, SESSION_COOKIE_NAME


class TestCloudDeploymentPhase73(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.session_id, self.csrf_token = session_store.create_session(
            username="admin",
            duration_hours=1
        )
        self.auth_cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        session_store.invalidate_session(self.session_id)

    # --------------------------------------------------------------------------
    # 1. DOCKERFILE VALIDATION
    # --------------------------------------------------------------------------
    def test_01_dockerfile_exists_and_valid(self):
        """Test that Dockerfile exists, uses supported Python base, and binds to 0.0.0.0."""
        dockerfile_path = PROJECT_ROOT / "Dockerfile"
        self.assertTrue(dockerfile_path.exists(), "Dockerfile must exist at project root")
        
        content = dockerfile_path.read_text(encoding="utf-8")
        self.assertIn("FROM python:3.11-slim", content)
        self.assertIn("0.0.0.0", content, "Dockerfile must bind to 0.0.0.0")
        self.assertIn("${PORT:-8000}", content, "Dockerfile must respect cloud PORT environment variable")
        self.assertIn("EXPOSE 8000", content)
        self.assertIn("/health", content, "Dockerfile HEALTHCHECK should reference /health")

    def test_02_dockerfile_zero_secrets(self):
        """Test that Dockerfile contains no credentials, API keys, or PATs."""
        content = (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8")
        forbidden = ["ghp_", "ya29.", "AIza", "client_secret", "refresh_token"]
        for term in forbidden:
            self.assertNotIn(term, content.lower(), f"Forbidden secret term '{term}' found in Dockerfile")

    # --------------------------------------------------------------------------
    # 2. RENDER.YAML VALIDATION
    # --------------------------------------------------------------------------
    def test_03_render_yaml_structure_and_healthcheck(self):
        """Test that render.yaml is valid YAML and defines a Docker web service."""
        render_path = PROJECT_ROOT / "render.yaml"
        self.assertTrue(render_path.exists(), "render.yaml must exist at project root")
        
        with open(render_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        self.assertIn("services", data)
        self.assertGreaterEqual(len(data["services"]), 1)
        
        svc = data["services"][0]
        self.assertEqual(svc["type"], "web")
        self.assertEqual(svc["runtime"], "docker")
        self.assertEqual(svc["healthCheckPath"], "/health")

    def test_04_render_yaml_zero_hardcoded_secrets(self):
        """Test that render.yaml marks all sensitive variables with sync: false."""
        with open(PROJECT_ROOT / "render.yaml", "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        svc = data["services"][0]
        env_vars = {item["key"]: item for item in svc.get("envVars", [])}
        
        secret_keys = [
            "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "SESSION_SECRET",
            "GITHUB_PAT", "GITHUB_REPOSITORY_OWNER", "GITHUB_REPOSITORY_NAME",
            "PEXELS_API_KEY", "GEMINI_API_KEY", "TOKEN_JSON", "CLIENT_SECRET_JSON"
        ]
        
        for key in secret_keys:
            self.assertIn(key, env_vars, f"Key '{key}' must be declared in render.yaml")
            self.assertTrue(env_vars[key].get("sync") is False, f"Key '{key}' must have 'sync: false'")
            self.assertNotIn("value", env_vars[key], f"Key '{key}' must not contain hardcoded value in render.yaml")

    # --------------------------------------------------------------------------
    # 3. .ENV.EXAMPLE VALIDATION
    # --------------------------------------------------------------------------
    def test_05_env_example_exists_and_contains_no_secrets(self):
        """Test that .env.example exists and contains placeholders only."""
        env_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(env_path.exists(), ".env.example must exist at project root")
        
        content = env_path.read_text(encoding="utf-8")
        self.assertIn("ADMIN_USERNAME=", content)
        self.assertIn("GITHUB_PAT=", content)
        self.assertIn("CLOUD_MODE=", content)
        self.assertNotIn("ghp_real", content)
        self.assertNotIn("AIzaSy", content)

    # --------------------------------------------------------------------------
    # 4. HEALTH ENDPOINT VALIDATION
    # --------------------------------------------------------------------------
    def test_06_unauthenticated_health_endpoint_returns_200(self):
        """Test that GET /health responds with 200 without requiring login cookies."""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "historia-mission-control")
        self.assertIn("timestamp", data)

    def test_07_health_endpoint_is_purely_lightweight(self):
        """Verify GET /health does not invoke Google Drive or YouTube APIs."""
        with patch("dashboard.app.data_provider.get_automation_health") as mock_health:
            resp = self.client.get("/health")
            self.assertEqual(resp.status_code, 200)
            mock_health.assert_not_called()

    # --------------------------------------------------------------------------
    # 5. PWA & STATIC ASSET VALIDATION
    # --------------------------------------------------------------------------
    def test_08_pwa_routes_served_correctly(self):
        """Test that /manifest.json and /sw.js are served with correct headers."""
        resp_m = self.client.get("/manifest.json")
        self.assertEqual(resp_m.status_code, 200)
        self.assertEqual(resp_m.headers.get("content-type"), "application/manifest+json")

        resp_sw = self.client.get("/sw.js")
        self.assertEqual(resp_sw.status_code, 200)
        self.assertIn("javascript", resp_sw.headers.get("content-type", ""))
        self.assertEqual(resp_sw.headers.get("service-worker-allowed"), "/")

    def test_09_mobile_route_auth_enforcement(self):
        """Test that /mobile redirects unauthenticated users and serves authenticated ones."""
        # Unauthenticated
        resp_unauth = self.client.get("/mobile", follow_redirects=False)
        self.assertIn(resp_unauth.status_code, [302, 303, 307])
        self.assertIn("/login", resp_unauth.headers.get("location", ""))

        # Authenticated
        resp_auth = self.client.get("/mobile", cookies=self.auth_cookies)
        self.assertEqual(resp_auth.status_code, 200)
        self.assertIn("AL AMR", resp_auth.text)

    # --------------------------------------------------------------------------
    # 6. AUTHENTICATION & CSRF SAFETY
    # --------------------------------------------------------------------------
    def test_10_csrf_enforcement_on_cloud_actions(self):
        """Test that action endpoints reject requests missing CSRF token."""
        resp = self.client.post(
            "/api/actions/produce",
            json={"count": 1, "target": 12},
            cookies=self.auth_cookies
        )
        self.assertEqual(resp.status_code, 403)
        self.assertIn("CSRF", resp.json().get("detail", ""))

    # --------------------------------------------------------------------------
    # 7. CLOUD_MODE ROUTING INTEGRATION
    # --------------------------------------------------------------------------
    def test_11_cloud_mode_routing_integration(self):
        """Test that POST /api/actions/produce dispatches workflow in CLOUD_MODE."""
        with patch("config.settings.CLOUD_MODE", True), \
             patch("dashboard.app.verify_major_action_auth", return_value=(True, None, "AUTHORIZED")), \
             patch("dashboard.action_manager.GitHubWorkflowDispatcher.dispatch_produce_buffer") as mock_dispatch:
            mock_dispatch.return_value = {
                "success": True,
                "action": "DISPATCH_ACCEPTED",
                "workflow": "produce_buffer.yml",
                "message": "Queued on GitHub Actions"
            }
            resp = self.client.post(
                "/api/actions/produce",
                json={"count": 1, "target": 12},
                headers={"X-CSRF-Token": self.csrf_token},
                cookies=self.auth_cookies
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["action"], "DISPATCH_ACCEPTED")
            mock_dispatch.assert_called_once()

    # --------------------------------------------------------------------------
    # 8. SECRET LEAK PREVENTION AUDIT
    # --------------------------------------------------------------------------
    def test_12_secret_leak_prevention_audit(self):
        """Scans templates, static assets, and manifest for accidental secrets."""
        static_dir = PROJECT_ROOT / "dashboard" / "static"
        templates_dir = PROJECT_ROOT / "dashboard" / "templates"

        for file_path in list(static_dir.rglob("*.*")) + list(templates_dir.rglob("*.html")):
            if file_path.suffix.lower() in [".html", ".js", ".json", ".css"]:
                content = file_path.read_text(encoding="utf-8")
                self.assertNotIn("ghp_", content, f"Leaked PAT in {file_path}")
                self.assertNotIn("client_secret", content.lower(), f"Leaked client secret in {file_path}")
                self.assertNotIn("aizasy", content, f"Leaked API key in {file_path}")


if __name__ == "__main__":
    unittest.main()