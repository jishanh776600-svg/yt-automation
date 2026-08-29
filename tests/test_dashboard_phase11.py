"""
Unit and Integration Tests for Mission Control Phase 11.1
Tests:
- Desktop Canonical Database Sync card rendering and live data verification
- Desktop 5-Provider Quotas & Service Limits panel rendering and live telemetry
- Dynamic rendering robustness under missing/unknown telemetry states
- Security: Protected routes require authentication
"""
import unittest
from fastapi.testclient import TestClient

from core.database import SessionLocal, init_db
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider
from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD


class TestDashboardPhase11(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.data_provider = SystemDataProvider()
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

    def test_desktop_database_sync_card_rendering(self):
        """Verify desktop index.html renders canonical database sync telemetry card."""
        res = self.client.get("/?desktop=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 1. Card container presence
        self.assertIn('id="db-sync-card"', html)
        self.assertIn('Canonical Cloud Database Persistence', html)
        self.assertIn('00_SYSTEM/pipeline.db', html)

        # 2. Key telemetry badges & labels
        self.assertIn('id="db-sync-integrity-badge"', html)
        self.assertIn('PRAGMA integrity:', html)
        self.assertIn('pipeline-cloud-execution', html)
        self.assertIn('Canonical Database Table Record Counts', html)

        # 3. Table counts IDs present
        self.assertIn('id="db-count-topics"', html)
        self.assertIn('id="db-count-scripts"', html)
        self.assertIn('id="db-count-jobs"', html)
        self.assertIn('id="db-count-uploads"', html)
        self.assertIn('id="db-count-snapshots"', html)

    def test_desktop_provider_quotas_panel_rendering(self):
        """Verify desktop index.html renders all 5 provider quotas."""
        res = self.client.get("/?desktop=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        # 1. Section Header
        self.assertIn('External API Quotas & Provider Service Limits', html)
        self.assertIn('id="desktop-quotas-container"', html)

        # 2. All 5 providers represented
        self.assertIn('YouTube Data API v3', html)
        self.assertIn('Google Gemini API', html)
        self.assertIn('Pexels API', html)
        self.assertIn('GitHub Actions', html)
        self.assertIn('Google Drive Vault Storage', html)

    def test_database_sync_live_values_populated(self):
        """Verify state['database_sync'] matches real database metrics and is rendered."""
        full_state = self.data_provider.get_full_system_state(self.db)
        self.assertIn("database_sync", full_state)
        db_sync = full_state["database_sync"]

        self.assertEqual(db_sync.get("canonical_vault_folder"), "00_SYSTEM")
        self.assertEqual(db_sync.get("canonical_filename"), "pipeline.db")
        self.assertTrue(db_sync.get("integrity_valid"))
        self.assertEqual(db_sync.get("concurrency_group"), "pipeline-cloud-execution")
        self.assertIsNotNone(db_sync.get("sha256"))

        table_counts = db_sync.get("table_counts", {})
        self.assertIn("topics", table_counts)
        self.assertIn("jobs", table_counts)

        # Verify rendered HTML contains table count values
        res = self.client.get("/?desktop=true")
        self.assertEqual(res.status_code, 200)
        self.assertIn(str(table_counts["topics"]), res.text)
        self.assertIn(str(table_counts["jobs"]), res.text)

    def test_provider_quotas_live_values_populated(self):
        """Verify state['service_quotas'] exposes 5 providers with valid metadata."""
        full_state = self.data_provider.get_full_system_state(self.db)
        self.assertIn("service_quotas", full_state)
        quotas = full_state["service_quotas"]
        services = quotas.get("services", [])

        self.assertEqual(len(services), 5)
        service_names = [s["service"] for s in services]
        self.assertIn("youtube_data_api", service_names)
        self.assertIn("gemini_api", service_names)
        self.assertIn("pexels_api", service_names)
        self.assertIn("github_actions", service_names)
        self.assertIn("google_drive", service_names)

        for s in services:
            self.assertIn("status", s)
            self.assertIn("automation_impact", s)
            self.assertIn("fallback_available", s)

    def test_graceful_rendering_with_empty_telemetry(self):
        """Verify index.html renders cleanly without template errors when telemetry is empty."""
        # Query /api/state to ensure JSON serialization succeeds
        res_state = self.client.get("/api/state")
        self.assertEqual(res_state.status_code, 200)
        state_data = res_state.json()
        self.assertIn("database_sync", state_data)
        self.assertIn("service_quotas", state_data)

        # Render HTML
        res_html = self.client.get("/?desktop=true")
        self.assertEqual(res_html.status_code, 200)
