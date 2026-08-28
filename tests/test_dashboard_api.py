"""
Unit and Integration Tests for Dashboard Control App & API Layer (App Phase 1).
Verifies that all API endpoints and SystemDataProvider queries connect to genuine system state:
- Health check diagnostics
- Google Drive Vault inventory
- Publishing slots and daily ceiling
- Reserve buffer runway calculation
- Continuous learning weights & baseline score
- FastAPI endpoints (HTTP 200 and schema validation)
"""
import unittest
from datetime import datetime, time as dtime
from fastapi.testclient import TestClient

from core.database import get_db, SessionLocal
from core.models import Job, UploadRecord, Topic, ContentPattern, StrategyWeight
from config.constants import DAILY_SHORTS_LIMIT
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider, PUBLISHING_SLOTS_UTC, TARGET_RESERVE_BUFFER


class TestDashboardAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
        login_res = cls.client.post("/api/auth/login", json={
            "username": DEFAULT_ADMIN_USER,
            "password": DEFAULT_ADMIN_PASSWORD
        })
        cls.csrf_token = login_res.json().get("csrf_token", "")
        cls.provider = SystemDataProvider()
        cls.db = SessionLocal()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_01_health_data_source(self):
        """Test 1: Verifies automation health data provider returns real health diagnostics."""
        health = self.provider.get_automation_health()
        self.assertIn("verdict", health)
        self.assertIn(health["verdict"], ["READY", "DEGRADED", "NOT_READY", "ERROR"])
        self.assertIn("passed_checks_count", health)
        self.assertGreaterEqual(health["passed_checks_count"], 1)
        self.assertIn("checks", health)
        self.assertIn("database", health["checks"])
        self.assertIn("google_drive", health["checks"])

    def test_02_drive_inventory_data_source(self):
        """Test 2: Verifies Drive inventory returns counts and file lists for all 4 vault folders."""
        inventory = self.provider.get_drive_inventory()
        self.assertIn("counts", inventory)
        self.assertIn("files", inventory)
        for folder in ["01_READY", "02_PROCESSING", "03_PUBLISHED", "04_FAILED"]:
            self.assertIn(folder, inventory["counts"])
            self.assertIn(folder, inventory["files"])
            self.assertIsInstance(inventory["counts"][folder], int)
            self.assertIsInstance(inventory["files"][folder], list)

    def test_03_publishing_status_and_daily_ceiling(self):
        """Test 3: Verifies publishing status respects DAILY_SHORTS_LIMIT and computes remaining capacity."""
        pub_status = self.provider.get_publishing_status(self.db)
        self.assertEqual(pub_status["daily_limit"], DAILY_SHORTS_LIMIT)
        self.assertIn("published_today", pub_status)
        self.assertIn("remaining_capacity", pub_status)
        self.assertEqual(
            pub_status["remaining_capacity"],
            max(0, DAILY_SHORTS_LIMIT - pub_status["published_today"])
        )
        self.assertIn("next_slot", pub_status)
        self.assertIn("configured_slots", pub_status)
        self.assertEqual(len(pub_status["configured_slots"]), 4)

    def test_04_buffer_runway_calculation(self):
        """Test 4: Verifies buffer status, target reserve (12), and runway mathematics."""
        # Test calculation with explicit count
        buf = self.provider.get_buffer_status(ready_stock=4)
        self.assertEqual(buf["ready_stock"], 4)
        self.assertEqual(buf["target_reserve"], TARGET_RESERVE_BUFFER)
        self.assertEqual(buf["runway_days"], 1.0)
        self.assertEqual(buf["runway_hours"], 24.0)
        self.assertEqual(buf["needed_replenishment"], 8)
        self.assertEqual(buf["health"], "REPLENISHING")

        # Test calculation with zero stock
        buf_zero = self.provider.get_buffer_status(ready_stock=0)
        self.assertEqual(buf_zero["health"], "DEPLETED")
        self.assertEqual(buf_zero["runway_days"], 0.0)

        # Test calculation with healthy stock
        buf_healthy = self.provider.get_buffer_status(ready_stock=12)
        self.assertEqual(buf_healthy["health"], "HEALTHY")
        self.assertEqual(buf_healthy["runway_days"], 3.0)
        self.assertEqual(buf_healthy["needed_replenishment"], 0)

    def test_05_next_scheduled_slot_derivation(self):
        """Test 5: Verifies derivation of next upcoming UTC publishing release slot."""
        # Test morning slot (04:00 UTC -> next is 06:00 UTC)
        mock_morning = datetime(2026, 8, 28, 4, 30, 0)
        next_morning = self.provider.get_next_scheduled_slot(now=mock_morning)
        self.assertIn("06:00 UTC", next_morning["slot_label"])
        self.assertTrue(next_morning["is_today"])
        self.assertEqual(next_morning["hours_remaining"], 1)
        self.assertEqual(next_morning["minutes_remaining"], 30)

        # Test late night slot (22:00 UTC -> next is tomorrow 06:00 UTC)
        mock_night = datetime(2026, 8, 28, 22, 15, 0)
        next_night = self.provider.get_next_scheduled_slot(now=mock_night)
        self.assertIn("06:00 UTC", next_night["slot_label"])
        self.assertFalse(next_night["is_today"])
        self.assertEqual(next_night["hours_remaining"], 7)
        self.assertEqual(next_night["minutes_remaining"], 45)

    def test_06_learning_status_structure(self):
        """Test 6: Verifies continuous learning status returns structured real weights and patterns."""
        learn = self.provider.get_learning_status(self.db)
        self.assertIn("has_mature_data", learn)
        self.assertIn("total_mature_snapshots", learn)
        self.assertIn("total_experiments", learn)
        self.assertIn("channel_baseline_score", learn)
        self.assertIn("patterns", learn)
        self.assertIn("strategy_weights", learn)
        self.assertIsInstance(learn["patterns"], list)
        self.assertIsInstance(learn["strategy_weights"], dict)

    def test_07_process_locks_inspection(self):
        """Test 7: Verifies process lock inspector checks production and publisher locks."""
        locks = self.provider.get_process_locks()
        self.assertIn("production", locks)
        self.assertIn("publisher", locks)
        self.assertIn("active", locks["production"])
        self.assertIn("active", locks["publisher"])

    def test_08_fastapi_index_html_endpoint(self):
        """Test 8: Verifies GET / renders HTML dashboard with HTTP 200."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("HISTORIA PIPELINE", response.text)
        self.assertIn("Google Drive Vault Lifecycle", response.text)
        self.assertIn("01_READY", response.text)

    def test_09_fastapi_json_api_endpoints(self):
        """Test 9: Verifies all JSON API endpoints respond with HTTP 200 and valid schemas."""
        endpoints = [
            "/api/state",
            "/api/health",
            "/api/inventory",
            "/api/publishing",
            "/api/buffer",
            "/api/learning",
            "/api/locks"
        ]
        for ep in endpoints:
            res = self.client.get(ep)
            self.assertEqual(res.status_code, 200, f"Endpoint {ep} failed with status {res.status_code}")
            data = res.json()
            self.assertIsInstance(data, dict, f"Endpoint {ep} did not return JSON object")

    def test_10_full_state_integration(self):
        """Test 10: Verifies full system state includes all 6 core subsystems."""
        state = self.provider.get_full_system_state(self.db)
        self.assertEqual(state["data_mode"], "LIVE_PRODUCTION_DATA")
        self.assertIn("health", state)
        self.assertIn("locks", state)
        self.assertIn("inventory", state)
        self.assertIn("publishing", state)
        self.assertIn("buffer", state)
        self.assertIn("learning", state)
        self.assertIn("database_summary", state)


if __name__ == "__main__":
    unittest.main()
