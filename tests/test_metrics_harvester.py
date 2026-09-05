"""
Unit & Integration Test Suite for Scheduled Analytics Harvester (Self-Improvement Phase 2).
Validates:
1. Mature-video eligibility (published >= 24 hours ago).
2. Immature-video exclusion (published < 24 hours ago).
3. Missing / blank YouTube ID exclusion.
4. Correct metric parsing from Data API & Analytics API responses.
5. Immutable PerformanceSnapshot creation & database persistence.
6. Idempotent harvesting (skips redundant snapshots within 20-hour window).
7. Graceful fallback when Analytics API scope is missing.
8. API error resilience (404 not found, transient network errors).
9. GitHub Actions workflow structure & YAML syntax.
"""
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from pathlib import Path
import yaml
from core.database import init_db, SessionLocal
from core.models import UploadRecord, PerformanceSnapshot, Job, Topic
from engines.metrics_collector import MetricsCollector


class TestMetricsHarvester(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.collector = MetricsCollector()

    def tearDown(self):
        self.db.close()

    def test_01_mature_video_eligibility(self):
        """Test 1: Video published > 24 hours ago with valid ID is ELIGIBLE."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        pub_time = datetime.utcnow() - timedelta(hours=36)
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_mature",
            youtube_video_id="dQw4w9WgXcQ",
            title="Mature Test Video",
            description="Description",
            published_at=pub_time,
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        is_eligible, reason = self.collector.is_eligible_for_harvesting(self.db, upload)
        self.assertTrue(is_eligible, f"Mature video must be eligible. Reason: {reason}")
        self.assertEqual(reason, "ELIGIBLE")

    def test_02_immature_video_exclusion(self):
        """Test 2: Video published < 24 hours ago is EXCLUDED as IMMATURE."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        pub_time = datetime.utcnow() - timedelta(hours=4)  # Only 4 hours old
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_immature",
            youtube_video_id="dQw4w9WgXcQ",
            title="Immature Test Video",
            description="Description",
            published_at=pub_time,
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        is_eligible, reason = self.collector.is_eligible_for_harvesting(self.db, upload)
        self.assertFalse(is_eligible, "Video < 24h must be excluded.")
        self.assertIn("IMMATURE_VIDEO", reason)

    def test_03_missing_youtube_id_exclusion(self):
        """Test 3: Video without YouTube Video ID is EXCLUDED."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_noid",
            youtube_video_id=None,
            title="No ID Video",
            description="Description",
            published_at=datetime.utcnow() - timedelta(hours=48),
            status="PENDING"
        )
        self.db.add(upload)
        self.db.commit()

        is_eligible, reason = self.collector.is_eligible_for_harvesting(self.db, upload)
        self.assertFalse(is_eligible)
        self.assertEqual(reason, "MISSING_YOUTUBE_ID")

    def test_04_metric_response_parsing(self):
        """Test 4: Accurate metric calculation and engagement rate calculation."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_parse",
            youtube_video_id="test_vid_123",
            title="Parsing Test Video",
            description="Description",
            published_at=datetime.utcnow() - timedelta(hours=48),
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        mock_payload = {
            "views": 5000,
            "likes": 250,
            "comments": 50,
            "shares": 20,
            "subscribers_gained": 35,
            "subscribers_lost": 2,
            "average_view_duration_sec": 21.2,
            "average_view_percentage": 92.5,
            "estimated_minutes_watched": 176.6,
            "traffic_sources": {"SHORTS": 85.0, "SEARCH": 10.0, "DIRECT": 5.0}
        }

        snap = self.collector.collect_for_upload(self.db, upload, mock_data=mock_payload)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.views, 5000)
        self.assertEqual(snap.likes, 250)
        self.assertEqual(snap.comments, 50)
        self.assertEqual(snap.shares, 20)
        self.assertEqual(snap.subscribers_gained, 35)
        self.assertEqual(snap.average_view_percentage, 92.5)
        # Engagement = (250 + 50 + 20) / 5000 * 100 = 6.4%
        self.assertAlmostEqual(snap.engagement_rate, 6.4, places=2)

    def test_05_performance_snapshot_persistence(self):
        """Test 5: PerformanceSnapshot records are saved immutably to SQLite."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_persist",
            youtube_video_id="test_vid_persist",
            title="Persist Test Video",
            description="Description",
            published_at=datetime.utcnow() - timedelta(hours=50),
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        snap = self.collector.collect_for_upload(self.db, upload, mock_data={"views": 1200, "likes": 60})
        self.assertIsNotNone(snap.id)

        # Query back from DB session
        fetched = self.db.query(PerformanceSnapshot).filter(PerformanceSnapshot.id == snap.id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.views, 1200)
        self.assertEqual(fetched.likes, 60)

    def test_06_idempotent_harvesting_behavior(self):
        """Test 6: Harvester skips recording if a snapshot was already recorded within 20 hours."""
        upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
        upload = UploadRecord(
            id=upl_id,
            job_id="job_test_idem",
            youtube_video_id="test_vid_idem",
            title="Idempotent Test Video",
            description="Description",
            published_at=datetime.utcnow() - timedelta(hours=72),
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        # Record 1st snapshot
        now = datetime.utcnow()
        snap1 = self.collector.collect_for_upload(self.db, upload, mock_data={"views": 1000}, now=now)
        self.assertIsNotNone(snap1)

        # 2nd run 2 hours later -> Must be marked IDEMPOTENT_SKIP
        run2_time = now + timedelta(hours=2)
        is_eligible, reason = self.collector.is_eligible_for_harvesting(self.db, upload, now=run2_time)
        self.assertFalse(is_eligible)
        self.assertIn("IDEMPOTENT_SKIP", reason)

        # 3rd run 22 hours later -> Must be ELIGIBLE again
        run3_time = now + timedelta(hours=22)
        is_eligible, reason = self.collector.is_eligible_for_harvesting(self.db, upload, now=run3_time)
        self.assertTrue(is_eligible)
        self.assertEqual(reason, "ELIGIBLE")

    def test_07_missing_analytics_scope_fallback(self):
        """Test 7: When Analytics API scope is absent, Data API v3 statistics still succeed."""
        with patch.object(self.collector, "get_youtube_clients") as mock_get_clients:
            mock_yt_data = MagicMock()
            mock_yt_data.videos().list().execute.return_value = {
                "items": [{"statistics": {"viewCount": "3400", "likeCount": "120", "commentCount": "15"}}]
            }
            # Analytics client is None because scope was missing
            mock_get_clients.return_value = (mock_yt_data, None)

            upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
            upload = UploadRecord(
                id=upl_id,
                job_id="job_test_scope",
                youtube_video_id="vid_real_id",
                title="Scope Fallback Video",
                description="Description",
                published_at=datetime.utcnow() - timedelta(hours=48),
                status="SUCCESS"
            )
            self.db.add(upload)
            self.db.commit()

            snap = self.collector.collect_for_upload(self.db, upload)
            self.assertIsNotNone(snap)
            self.assertEqual(snap.views, 3400)
            self.assertEqual(snap.likes, 120)
            self.assertEqual(snap.comments, 15)
            self.assertEqual(snap.average_view_percentage, 0.0)  # Graceful default without crashing

    def test_08_api_error_handling(self):
        """Test 8: Video returning 404 or empty results logs warning and saves zero snapshot safely."""
        with patch.object(self.collector, "get_youtube_clients") as mock_get_clients:
            mock_yt_data = MagicMock()
            # Video deleted or private
            mock_yt_data.videos().list().execute.return_value = {"items": []}
            mock_get_clients.return_value = (mock_yt_data, None)

            upl_id = f"upl_test_{uuid.uuid4().hex[:8]}"
            upload = UploadRecord(
                id=upl_id,
                job_id="job_test_404",
                youtube_video_id="vid_deleted_404",
                title="Deleted Video",
                description="Description",
                published_at=datetime.utcnow() - timedelta(hours=48),
                status="SUCCESS"
            )
            self.db.add(upload)
            self.db.commit()

            snap = self.collector.collect_for_upload(self.db, upload)
            self.assertIsNotNone(snap)
            self.assertEqual(snap.views, 0)

    def test_09_github_actions_workflow_syntax(self):
        """Test 9: Verify .github/workflows/harvest_analytics.yml is valid YAML and has 03:00 UTC schedule."""
        workflow_path = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "harvest_analytics.yml"
        self.assertTrue(workflow_path.exists(), "harvest_analytics.yml workflow must exist.")
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            
        self.assertIn("name", data)
        self.assertEqual(data["name"], "Scheduled YouTube Analytics Harvester")
        # In PyYAML 1.1, unquoted 'on' parses as boolean True
        trigger_data = data.get("on") or data.get(True)
        self.assertIsNotNone(trigger_data)
        cron_expr = trigger_data["schedule"][0]["cron"]
        self.assertEqual(cron_expr, "0 3 * * *")


if __name__ == "__main__":
    unittest.main()
