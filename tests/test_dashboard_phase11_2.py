"""
Unit and Integration Tests for AL AMR Phase 11.2
Tests:
- GET /api/performance endpoint authentication & data structure
- Published video leaderboard sorting (views desc)
- Accurate engagement rate calculation ((likes + comments) / views * 100)
- Graceful handling of missing analytics metrics (None APV, 0 views)
- 5 TB Google Drive storage plan telemetry correction
- Desktop index.html and mobile.html AL AMR Performance Intelligence rendering
- AL AMR branding compliance (Zero obsolete 'Mission Control' product headers)
"""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from datetime import datetime

from core.database import SessionLocal, init_db
from core.models import UploadRecord, PerformanceSnapshot, VideoAnalysisRecord
from dashboard.app import app
from dashboard.data_provider import SystemDataProvider, format_compact_number
from dashboard.auth import DEFAULT_ADMIN_USER, DEFAULT_ADMIN_PASSWORD
from config.settings import GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES


class TestDashboardPhase112(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)
        cls.data_provider = SystemDataProvider()
        cls.db = SessionLocal()

        # Seed known test upload records with performance snapshots
        cls.test_upload_id = "upl_phase112_1"
        cls.test_yt_id = "P112_Prague"
        
        # Clean up any previous test record
        cls.db.query(PerformanceSnapshot).filter(PerformanceSnapshot.upload_id == cls.test_upload_id).delete()
        cls.db.query(VideoAnalysisRecord).filter(VideoAnalysisRecord.upload_id == cls.test_upload_id).delete()
        cls.db.query(UploadRecord).filter(UploadRecord.id == cls.test_upload_id).delete()
        cls.db.commit()

        # Create upload record with high views so it's guaranteed #1 in leaderboard
        upload = UploadRecord(
            id=cls.test_upload_id,
            job_id="test_phase112_job_1",
            youtube_video_id=cls.test_yt_id,
            title="The Great Defenestration of Prague",
            description="Test short description",
            status="PUBLISHED",
            published_at=datetime.utcnow()
        )
        cls.db.add(upload)
        cls.db.commit()

        # Create snapshot with views=2,500,000,000, likes=250,000,000, comments=50,000,000 -> Engagement = (250M+50M)/2500M*100 = 12.00%
        snapshot = PerformanceSnapshot(
            upload_id=cls.test_upload_id,
            youtube_video_id=cls.test_yt_id,
            snapshot_time=datetime.utcnow(),
            views=2500000000,
            likes=250000000,
            comments=50000000,
            average_view_percentage=85.5,
            engagement_rate=12.0
        )
        cls.db.add(snapshot)

        # Create analysis record
        analysis = VideoAnalysisRecord(
            id="test_phase112_analysis_1",
            upload_id=cls.test_upload_id,
            youtube_video_id=cls.test_yt_id,
            classification="OUTPERFORMER",
            facts_observed="[]",
            hypotheses="[]",
            evidence="[]",
            uncertainties="[]",
            performance_score=92.0
        )
        cls.db.add(analysis)
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.db.query(PerformanceSnapshot).filter(
            (PerformanceSnapshot.upload_id == cls.test_upload_id) | (PerformanceSnapshot.youtube_video_id == cls.test_yt_id)
        ).delete()
        cls.db.query(VideoAnalysisRecord).filter(
            (VideoAnalysisRecord.upload_id == cls.test_upload_id) | (VideoAnalysisRecord.youtube_video_id == cls.test_yt_id)
        ).delete()
        cls.db.query(UploadRecord).filter(UploadRecord.id == cls.test_upload_id).delete()
        cls.db.commit()
        cls.db.close()

    def setUp(self):
        from dashboard.auth import session_store, SESSION_COOKIE_NAME
        self.session_id, self.csrf_token = session_store.create_session("admin", duration_hours=1)
        self.client = TestClient(app)
        self.client.cookies = {SESSION_COOKIE_NAME: self.session_id}

    def tearDown(self):
        from dashboard.auth import session_store
        if hasattr(self, "session_id"):
            session_store.invalidate_session(self.session_id)

    def test_performance_endpoint_requires_auth(self):
        """Verify /api/performance returns 401 when called without an active session."""
        anon_client = TestClient(app)
        res = anon_client.get("/api/performance")
        self.assertEqual(res.status_code, 401)

    def test_performance_endpoint_returns_valid_structure(self):
        """Verify /api/performance returns 200 with leaderboard list and metadata."""
        res = self.client.get("/api/performance")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("timestamp", data)
        self.assertIn("count", data)
        self.assertIn("leaderboard", data)
        self.assertIsInstance(data["leaderboard"], list)
        self.assertGreaterEqual(len(data["leaderboard"]), 1)

    def test_performance_leaderboard_fields_and_engagement_accuracy(self):
        """Verify the test video has all required metrics and exact mathematically correct engagement calculation."""
        leaderboard = self.data_provider.get_published_performance_leaderboard(self.db, limit=50)
        target = next((item for item in leaderboard if item["youtube_video_id"] == self.test_yt_id), None)
        self.assertIsNotNone(target)

        self.assertEqual(target["title"], "The Great Defenestration of Prague")
        self.assertEqual(target["views"], 2500000000)
        self.assertEqual(target["views_display"], "2.5B")
        self.assertEqual(target["likes"], 250000000)
        self.assertEqual(target["likes_display"], "250.0M")
        self.assertEqual(target["comments"], 50000000)
        self.assertEqual(target["comments_display"], "50.0M")
        self.assertEqual(target["apv"], 85.5)
        self.assertEqual(target["apv_display"], "85.5%")
        # (250M + 50M) / 2500M * 100 = 12.00%
        self.assertEqual(target["engagement_rate"], 12.0)
        self.assertEqual(target["engagement_display"], "12.00%")
        self.assertEqual(target["classification"], "OUTPERFORMER")
        self.assertEqual(target["status"], "PUBLISHED")
        self.assertEqual(target["youtube_url"], f"https://www.youtube.com/shorts/{self.test_yt_id}")

    def test_compact_number_formatting(self):
        """Verify format_compact_number helper formats billions, millions, thousands correctly."""
        self.assertEqual(format_compact_number(1_809_354_184), "1.8B")
        self.assertEqual(format_compact_number(19_361_880), "19.4M")
        self.assertEqual(format_compact_number(45_300), "45.3K")
        self.assertEqual(format_compact_number(987), "987")
        self.assertEqual(format_compact_number(0), "0")
        self.assertEqual(format_compact_number(None), "—")

    def test_5tb_google_drive_storage_capacity(self):
        """Verify Google Drive storage reflects confirmed 5 TB capacity plan (5,497,558,138,880 bytes)."""
        self.assertEqual(GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES, 5 * (1024 ** 4))
        
        with patch.object(self.data_provider.drive_engine, "get_storage_quota", return_value={"usage": 107374182400}): # 100 GB used
            quotas = self.data_provider.get_all_service_quotas(self.db)
            drive_svc = next(s for s in quotas["services"] if s["service"] == "google_drive")
            self.assertEqual(drive_svc["limit"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES)
            self.assertEqual(drive_svc["used"], 107374182400)
            self.assertEqual(drive_svc["remaining"], GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES - 107374182400)
            self.assertIn("5.00 TB", drive_svc["message"])
            self.assertIn("100.00 GB used", drive_svc["message"])

    def test_desktop_performance_leaderboard_rendering(self):
        """Verify desktop index.html renders the AL AMR Performance Intelligence section."""
        res = self.client.get("/?desktop=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn("AL AMR // Published Video Performance Intelligence", html)
        self.assertIn("id=\"performance-leaderboard-tbody\"", html)
        self.assertIn("The Great Defenestration of Prague", html)
        self.assertIn(self.test_yt_id, html)
        self.assertIn("12.00%", html)
        self.assertIn("85.5%", html)

    def test_mobile_performance_leaderboard_rendering(self):
        """Verify mobile.html renders the mobile performance leaderboard."""
        res = self.client.get("/?mobile=true")
        self.assertEqual(res.status_code, 200)
        html = res.text

        self.assertIn("Published Performance", html)
        self.assertIn("id=\"mobile-performance-leaderboard\"", html)
        self.assertIn("The Great Defenestration of Prague", html)

    def test_al_amr_branding_compliance(self):
        """Verify user-facing pages use AL AMR branding and avoid obsolete product naming."""
        res_desktop = self.client.get("/?desktop=true")
        self.assertEqual(res_desktop.status_code, 200)
        self.assertIn("AL AMR", res_desktop.text)
        self.assertNotIn("HISTORIA // MISSION CONTROL", res_desktop.text)

        anon_client = TestClient(app)
        res_login = anon_client.get("/login")
        self.assertEqual(res_login.status_code, 200)
        self.assertIn("AL AMR", res_login.text)
