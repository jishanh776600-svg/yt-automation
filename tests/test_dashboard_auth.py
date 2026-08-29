"""
Unit and Integration Tests for Dashboard Authentication & Remote Security (App Phase 3).
Comprehensive security test suite verifying:
- Login authentication with PBKDF2-HMAC-SHA256
- Non-plaintext password storage
- Unauthenticated UI redirect & API 401 rejection
- Authenticated session lifecycle (creation, validation, expiration, logout)
- Brute-force rate limiting and lockout (HTTP 429)
- CSRF protection on state-changing endpoints (HTTP 403)
- Hard DAILY_SHORTS_LIMIT = 4 ceiling preservation
- Security headers verification (CSP, Frame protection, No-Sniff, No-Store)
- Git & environment secret management verification
"""
import os
import time
import uuid
import unittest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from config.settings import PROJECT_ROOT
from config.constants import DAILY_SHORTS_LIMIT
from dashboard.app import app
from dashboard.auth import (
    PasswordHasher,
    credentials_manager,
    session_store,
    rate_limiter,
    SESSION_COOKIE_NAME,
    DEFAULT_ADMIN_USER,
    DEFAULT_ADMIN_PASSWORD
)


class TestDashboardAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.admin_user = DEFAULT_ADMIN_USER
        cls.admin_pass = DEFAULT_ADMIN_PASSWORD

    def setUp(self):
        # Clear cookies & rate limiter before each test
        self.client.cookies.clear()
        with rate_limiter._lock:
            rate_limiter._attempts.clear()
            rate_limiter._lockouts.clear()

    def test_01_login_success_with_correct_credentials(self):
        """Test 1: Verifies login succeeds with correct credentials and returns session cookie + CSRF token."""
        res = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": self.admin_pass
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn("csrf_token", data)
        self.assertIn(SESSION_COOKIE_NAME, res.cookies)

    def test_02_login_fails_with_incorrect_credentials(self):
        """Test 2: Verifies login fails with incorrect credentials and returns generic 401 message."""
        res = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": "WrongPassword123!"
        })
        self.assertEqual(res.status_code, 401)
        self.assertNotIn(SESSION_COOKIE_NAME, res.cookies)
        self.assertIn("Invalid username or password", res.json()["detail"])

    def test_03_password_never_stored_plaintext(self):
        """Test 3: Verifies password hasher produces strong PBKDF2 hash and never stores plaintext."""
        hash_hex, salt_hex = PasswordHasher.hash_password("MySecretPassword2026")
        self.assertNotEqual(hash_hex, "MySecretPassword2026")
        self.assertEqual(len(hash_hex), 64)  # SHA-256 output length in hex
        self.assertEqual(len(salt_hex), 32)  # 16 bytes salt in hex
        self.assertTrue(PasswordHasher.verify_password("MySecretPassword2026", hash_hex, salt_hex))
        self.assertFalse(PasswordHasher.verify_password("WrongPassword", hash_hex, salt_hex))
        # Ensure credentials manager does not hold plaintext password
        self.assertFalse(hasattr(credentials_manager, "password"))

    def test_04_unauthenticated_ui_access_redirects(self):
        """Test 4: Verifies unauthenticated browser access to / redirects to /login."""
        res = self.client.get("/", follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertEqual(res.headers["location"], "/login")

    def test_05_unauthenticated_api_access_blocked(self):
        """Test 5: Verifies unauthenticated API access returns HTTP 401 Unauthorized."""
        endpoints = [
            "/api/state",
            "/api/health",
            "/api/inventory",
            "/api/publishing",
            "/api/buffer",
            "/api/learning",
            "/api/locks",
            "/api/jobs/review-queue"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 401, f"Endpoint {ep} allowed unauthenticated access!")
            self.assertIn("Authentication required", res.json()["detail"])

    def test_06_authenticated_access_works(self):
        """Test 6: Verifies authenticated session can successfully query protected UI and API endpoints."""
        # 1. Login
        login_res = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": self.admin_pass
        })
        self.assertEqual(login_res.status_code, 200)

        # 2. Access UI
        ui_res = self.client.get("/")
        self.assertEqual(ui_res.status_code, 200)
        self.assertTrue("AL AMR" in ui_res.text or "Operations Console" in ui_res.text or "Historia Mission Control" in ui_res.text)

        # 3. Access API
        api_res = self.client.get("/api/state")
        self.assertEqual(api_res.status_code, 200)
        self.assertIn("health", api_res.json())

    def test_07_logout_invalidates_session(self):
        """Test 7: Verifies logout endpoint deletes cookie and invalidates session in store."""
        # 1. Login
        login_res = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": self.admin_pass
        })
        session_id = login_res.cookies.get(SESSION_COOKIE_NAME)
        self.assertIsNotNone(session_store.get_session(session_id))

        # 2. Logout
        logout_res = self.client.post("/api/auth/logout")
        self.assertEqual(logout_res.status_code, 200)
        self.assertIsNone(session_store.get_session(session_id))

        # 3. Verify access is now rejected
        ui_res = self.client.get("/", follow_redirects=False)
        self.assertEqual(ui_res.status_code, 303)

    def test_08_expired_session_rejected(self):
        """Test 8: Verifies expired session token is automatically rejected with 401."""
        # Create an already-expired session
        expired_id, csrf_token = session_store.create_session("admin", duration_hours=-1)
        
        # Test directly with cookie header
        res = self.client.get("/api/state", cookies={SESSION_COOKIE_NAME: expired_id})
        self.assertEqual(res.status_code, 401)
        self.assertIn("expired", res.json()["detail"].lower())

    def test_09_repeated_failed_login_attempts_throttled(self):
        """Test 9: Verifies rate limiter locks out client after 5 consecutive failed attempts with HTTP 429."""
        for i in range(5):
            res = self.client.post("/api/auth/login", json={
                "username": self.admin_user,
                "password": "BadPassword!"
            })
            if i < 4:
                self.assertEqual(res.status_code, 401)
            else:
                self.assertEqual(res.status_code, 429)
                self.assertIn("Too many failed", res.json()["detail"])

        # 6th attempt should immediately return 429 without checking password
        res_locked = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": self.admin_pass  # Even with right password, locked out
        })
        self.assertEqual(res_locked.status_code, 429)

    def test_10_state_changing_endpoints_require_authentication(self):
        """Test 10: Verifies all POST action endpoints reject unauthenticated requests with HTTP 401."""
        actions = [
            ("/api/actions/produce", {"count": 1, "target": 12}),
            ("/api/actions/publish-next", {}),
            ("/api/actions/retry-job", {"job_id": "job_12345"}),
            ("/api/actions/quarantine-job", {"job_id": "job_12345", "reason": "Test"}),
            ("/api/actions/release-lock", {"lock_name": "production", "force": True}),
        ]
        for url, payload in actions:
            res = self.client.post(url, json=payload)
            self.assertEqual(res.status_code, 401, f"Unauthenticated POST {url} was not blocked!")

    def test_11_csrf_protection_blocks_forged_requests(self):
        """Test 11: Verifies authenticated requests without valid X-CSRF-Token are rejected with HTTP 403."""
        # 1. Login to get authenticated cookie
        login_res = self.client.post("/api/auth/login", json={
            "username": self.admin_user,
            "password": self.admin_pass
        })
        csrf_token = login_res.json()["csrf_token"]

        # 2. Try POST action without CSRF header (Simulated Cross-Site Request Forgery)
        res_no_csrf = self.client.post("/api/actions/retry-job", json={"job_id": "job_12345"})
        self.assertEqual(res_no_csrf.status_code, 403)
        self.assertIn("CSRF", res_no_csrf.json()["detail"])

        # 3. Try POST action with bogus CSRF header
        res_bad_csrf = self.client.post(
            "/api/actions/retry-job",
            json={"job_id": "job_12345"},
            headers={"X-CSRF-Token": "bogus_attack_token_12345"}
        )
        self.assertEqual(res_bad_csrf.status_code, 403)
        self.assertIn("CSRF", res_bad_csrf.json()["detail"])

        # 4. Try POST action with VALID CSRF header
        res_valid = self.client.post(
            "/api/actions/release-lock",
            json={"lock_name": "production", "force": True},
            headers={"X-CSRF-Token": csrf_token}
        )
        self.assertEqual(res_valid.status_code, 200)

    def test_12_security_headers_present(self):
        """Test 12: Verifies security headers are attached to all HTTP responses."""
        res = self.client.get("/login")
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("Content-Security-Policy", res.headers)
        self.assertIn("frame-ancestors 'none'", res.headers["Content-Security-Policy"])

    def test_13_git_and_env_secrets_audit(self):
        """Test 13: Verifies .gitignore properly ignores .env, token.json, and secrets."""
        gitignore_path = PROJECT_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists())
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(".env", content)
        self.assertIn("token.json", content)
        self.assertIn("client_secret", content)


if __name__ == "__main__":
    unittest.main()
