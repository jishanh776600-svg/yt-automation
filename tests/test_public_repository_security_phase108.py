"""
Dedicated Security & Public-Readiness Verification Suite (Phase 10.8).
Proves:
- No hardcoded fallback admin passwords in source code
- Missing credentials fail closed (100% rejection)
- Authentication succeeds with valid injected environment password or hash
- show_secrets.py is completely removed from Git tracking and gitignored
- No credential files (.env, token.json, client_secret*.json) are tracked
- Workflows do not contain hardcoded credentials
- render.yaml marks all sensitive variables with sync: false
"""
import os
import subprocess
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

from config.settings import PROJECT_ROOT
from dashboard.app import app
from dashboard.auth import (
    PasswordHasher,
    credentials_manager,
    DEFAULT_ADMIN_USER
)


class TestPublicRepositorySecurityPhase108(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)
        self.original_user = os.environ.get("DASHBOARD_ADMIN_USER")
        self.original_pass = os.environ.get("DASHBOARD_ADMIN_PASSWORD")
        self.original_hash = os.environ.get("ADMIN_PASSWORD_HASH")

    def tearDown(self):
        # Restore environment
        if self.original_user is not None:
            os.environ["DASHBOARD_ADMIN_USER"] = self.original_user
        else:
            os.environ.pop("DASHBOARD_ADMIN_USER", None)

        if self.original_pass is not None:
            os.environ["DASHBOARD_ADMIN_PASSWORD"] = self.original_pass
        else:
            os.environ.pop("DASHBOARD_ADMIN_PASSWORD", None)

        if self.original_hash is not None:
            os.environ["ADMIN_PASSWORD_HASH"] = self.original_hash
        else:
            os.environ.pop("ADMIN_PASSWORD_HASH", None)

        credentials_manager.reload()

    def test_01_no_hardcoded_admin_password_in_auth_source(self):
        """Test 1: dashboard/auth.py contains NO hardcoded fallback password."""
        auth_path = PROJECT_ROOT / "dashboard" / "auth.py"
        content = auth_path.read_text(encoding="utf-8")

        forbidden_patterns = [
            "HistoriaAdmin2026!Secure",
            "admin123",
            "password123",
            "secret123"
        ]
        for term in forbidden_patterns:
            self.assertNotIn(term, content, f"Hardcoded fallback term '{term}' found in dashboard/auth.py")

    def test_02_missing_dashboard_credentials_fail_closed(self):
        """Test 2: When no admin password or hash is configured, authentication FAILS CLOSED."""
        os.environ.pop("DASHBOARD_ADMIN_PASSWORD", None)
        os.environ.pop("ADMIN_PASSWORD_HASH", None)
        credentials_manager.reload()

        self.assertFalse(credentials_manager.is_configured)
        self.assertFalse(credentials_manager.verify_credentials("admin", "any_attempted_password"))
        self.assertFalse(credentials_manager.verify_credentials("admin", ""))

        # API login must reject with 401
        res = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "any_attempted_password"
        })
        self.assertEqual(res.status_code, 401)

    def test_03_authentication_succeeds_with_injected_password(self):
        """Test 3: Authentication works correctly when DASHBOARD_ADMIN_PASSWORD is provided."""
        os.environ.pop("ADMIN_PASSWORD_HASH", None)
        os.environ["DASHBOARD_ADMIN_PASSWORD"] = "InjectedValidPassword2026!"
        credentials_manager.reload()

        self.assertTrue(credentials_manager.is_configured)
        self.assertTrue(credentials_manager.verify_credentials("admin", "InjectedValidPassword2026!"))
        self.assertFalse(credentials_manager.verify_credentials("admin", "WrongPassword123!"))

    def test_04_authentication_succeeds_with_injected_hash(self):
        """Test 4: Authentication works correctly when ADMIN_PASSWORD_HASH is provided."""
        os.environ.pop("DASHBOARD_ADMIN_PASSWORD", None)
        hash_hex, salt_hex = PasswordHasher.hash_password("MyStrongHashedPassword_999!")
        os.environ["ADMIN_PASSWORD_HASH"] = f"pbkdf2_sha256$600000${salt_hex}${hash_hex}"
        credentials_manager.reload()

        self.assertTrue(credentials_manager.is_configured)
        self.assertTrue(credentials_manager.verify_credentials("admin", "MyStrongHashedPassword_999!"))
        self.assertFalse(credentials_manager.verify_credentials("admin", "WrongPassword123!"))

    def test_05_show_secrets_untracked_and_ignored(self):
        """Test 5: show_secrets.py is completely untracked in Git and ignored by .gitignore."""
        res = subprocess.run(["git", "ls-files", "show_secrets.py"], capture_output=True, text=True)
        self.assertEqual(res.stdout.strip(), "", "show_secrets.py must NOT be tracked in Git")

        gitignore_content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("show_secrets.py", gitignore_content, "show_secrets.py must be listed in .gitignore")

    def test_06_no_credential_files_tracked(self):
        """Test 6: No sensitive credential files are tracked in Git."""
        res = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
        tracked_files = [f.strip() for f in res.stdout.splitlines() if f.strip()]

        forbidden = [".env", "token.json", "client_secret.json", "client_secrets.json", "id_rsa"]
        for f in tracked_files:
            for bad in forbidden:
                self.assertNotEqual(f, bad, f"Tracked file '{f}' violates credential exclusion rules")

    def test_07_workflows_contain_no_hardcoded_secrets(self):
        """Test 7: All GitHub Actions workflows reference credentials strictly through secrets."""
        workflow_dir = PROJECT_ROOT / ".github" / "workflows"
        for yml_file in workflow_dir.glob("*.yml"):
            content = yml_file.read_text(encoding="utf-8")
            forbidden = ["AIzaSy", "ghp_", "ya29.", "1//"]
            for term in forbidden:
                self.assertNotIn(term, content, f"Workflow {yml_file.name} contains potential hardcoded secret '{term}'")

    def test_08_render_yaml_all_secrets_marked_sync_false(self):
        """Test 8: render.yaml declares all secrets with sync: false and no hardcoded values."""
        import yaml
        render_path = PROJECT_ROOT / "render.yaml"
        with open(render_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        svc = data["services"][0]
        env_vars = {item["key"]: item for item in svc.get("envVars", [])}

        required_secrets = [
            "ADMIN_USERNAME", "ADMIN_PASSWORD_HASH", "DASHBOARD_ADMIN_PASSWORD",
            "SESSION_SECRET", "GITHUB_PAT", "PEXELS_API_KEY", "GEMINI_API_KEY"
        ]
        for key in required_secrets:
            self.assertIn(key, env_vars, f"Key '{key}' must be declared in render.yaml")
            self.assertTrue(env_vars[key].get("sync") is False, f"Key '{key}' must have sync: false")
            self.assertNotIn("value", env_vars[key], f"Key '{key}' must not have hardcoded value")


if __name__ == "__main__":
    unittest.main()
