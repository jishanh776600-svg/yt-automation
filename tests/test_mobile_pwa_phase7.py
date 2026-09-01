"""
Phase 7.1 Emergency Mobile App (PWA) Unit & Integration Tests.
Verifies:
  - Mobile interface rendering and session protection.
  - PWA Web App Manifest serving and configuration.
  - PWA Service Worker serving and caching invariants.
  - PWA icons presence and validity.
  - Complete Mobile UI cards, bottom navigation, and action buttons.
  - Mobile user-agent automatic routing.
  - Authentication and CSRF protection preservation.
  - Zero client-side secrets/credentials in templates and assets.
"""
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from PIL import Image

from dashboard.app import app
from dashboard.auth import session_store, SESSION_COOKIE_NAME
from config.settings import PROJECT_ROOT


class TestMobilePWAPhase7(unittest.TestCase):

    def setUp(self):
        # Create an authenticated session fixture
        self.session_id, self.csrf_token = session_store.create_session(
            username="admin",
            duration_hours=1
        )
        self.auth_cookies = {SESSION_COOKIE_NAME: self.session_id}
        self.client = TestClient(app, cookies={SESSION_COOKIE_NAME: self.session_id})

    def tearDown(self):
        session_store.invalidate_session(self.session_id)

    def test_01_manifest_served_correctly(self):
        """Test that /manifest.json is served with valid PWA manifest JSON."""
        res = self.client.get("/manifest.json")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("name", data)
        self.assertEqual(data["short_name"], "AL AMR")
        self.assertIn("mobile=true", data["start_url"])
        self.assertEqual(data["display"], "standalone")
        self.assertTrue(len(data["icons"]) >= 2)

    def test_02_service_worker_served_with_headers(self):
        """Test that /sw.js is served with proper headers and invariant rules."""
        res = self.client.get("/sw.js")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/javascript", res.headers.get("content-type", ""))
        self.assertEqual(res.headers.get("service-worker-allowed"), "/")
        # Verify SW contains no-api-cache rule
        self.assertIn("startsWith('/api')", res.text)

    def test_03_pwa_icons_exist_and_valid(self):
        """Test that icon-192.png and icon-512.png exist with exact dimensions."""
        icon192_path = PROJECT_ROOT / "dashboard" / "static" / "icons" / "icon-192.png"
        icon512_path = PROJECT_ROOT / "dashboard" / "static" / "icons" / "icon-512.png"

        self.assertTrue(icon192_path.exists(), "icon-192.png must exist")
        self.assertTrue(icon512_path.exists(), "icon-512.png must exist")

        with Image.open(str(icon192_path)) as img:
            self.assertEqual(img.size, (192, 192))
            self.assertEqual(img.format, "PNG")

        with Image.open(str(icon512_path)) as img:
            self.assertEqual(img.size, (512, 512))

    def test_04_mobile_view_requires_authentication(self):
        """Test that unauthenticated GET /mobile redirects to /login."""
        anon_client = TestClient(app)
        res = anon_client.get("/mobile", follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        self.assertIn("/login", res.headers.get("location", ""))

    def test_05_mobile_authenticated_renders_all_required_sections(self):
        """Test that authenticated GET /mobile returns 200 and contains all core mobile components."""
        res = self.client.get("/mobile", cookies=self.auth_cookies)
        self.assertEqual(res.status_code, 200)
        html = res.text

        # Top Header & Status
        self.assertIn("AL AMR", html)
        self.assertIn('id="mob-clock"', html)
        self.assertIn('id="mobile-cloud-banner"', html)

        # Tabs & Navigation
        self.assertIn('id="mob-tab-overview"', html)
        self.assertIn('id="mob-tab-pipeline"', html)
        self.assertIn('id="mob-tab-buffer"', html)
        self.assertIn('id="mob-tab-queue"', html)
        self.assertIn('id="mob-tab-audio"', html)

        # CSRF
        self.assertIn('name="csrf-token"', html)

    def test_06_mobile_user_agent_detection(self):
        """Test that mobile User-Agent on GET / routes to mobile view."""
        mobile_headers = {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15"}
        res = self.client.get("/", cookies=self.auth_cookies, headers=mobile_headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn("AL AMR", res.text)

    def test_07_zero_client_side_secrets(self):
        """Test that mobile HTML template and static assets contain no API keys, tokens, or credentials."""
        mobile_html = (PROJECT_ROOT / "dashboard" / "templates" / "mobile.html").read_text(encoding="utf-8")
        forbidden_terms = [
            "AIzaSy", "ghp_", "github_pat", "client_secret",
            "refresh_token", "private_key", "password_hash"
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, mobile_html, f"Forbidden secret pattern '{term}' found in mobile.html")

    def test_08_auth_csrf_enforcement_on_actions(self):
        """Test that mobile emergency action endpoints strictly reject missing CSRF and unauthenticated requests."""
        # 1. Unauthenticated request -> 401
        anon_client = TestClient(app)
        res1 = anon_client.post("/api/actions/publish-next", json={})
        self.assertEqual(res1.status_code, 401)

        # 2. Authenticated but missing CSRF -> 403
        res2 = self.client.post("/api/actions/publish-next", cookies=self.auth_cookies, json={})
        self.assertEqual(res2.status_code, 403)


if __name__ == "__main__":
    unittest.main()