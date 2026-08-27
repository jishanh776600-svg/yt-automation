"""
Tests for Database, State Machine, and License Tracker.
"""
import sys
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import init_db, SessionLocal
from core.models import Job, Topic, AssetRecord
from core.state_machine import StateMachine
from core.license_tracker import LicenseTracker
from config.constants import JobState, LicenseType


class TestCoreSystem(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_job_state_machine_transition(self):
        import uuid
        job_id = f"test_job_{uuid.uuid4().hex[:8]}"
        job = Job(id=job_id, state=JobState.QUEUED.value)
        self.db.add(job)
        self.db.commit()

        # Valid transition
        success = StateMachine.transition(self.db, job, JobState.RESEARCHING, "Starting research")
        self.assertTrue(success)
        self.assertEqual(job.state, JobState.RESEARCHING.value)

        # Flag needs review
        StateMachine.flag_needs_review(self.db, job, "Disputed historical date")
        self.assertEqual(job.state, JobState.NEEDS_REVIEW.value)

    def test_license_tracker_verification(self):
        # Valid asset
        valid_asset = AssetRecord(
            id="ast_valid",
            asset_type="image",
            source="pexels",
            license=LicenseType.PEXELS_LICENSE.value,
            commercial_use=True,
            local_path="sample.jpg"
        )
        is_valid, _ = LicenseTracker.verify_asset(valid_asset)
        self.assertTrue(is_valid)

        # Invalid asset with UNKNOWN license
        invalid_asset = AssetRecord(
            id="ast_invalid",
            asset_type="image",
            source="scraped_web",
            license=LicenseType.UNKNOWN.value,
            commercial_use=False,
            local_path="scraped.jpg"
        )
        is_valid, reason = LicenseTracker.verify_asset(invalid_asset)
        self.assertFalse(is_valid)


if __name__ == "__main__":
    unittest.main()
