"""
End-to-End Integration Test.
Renders a full 1080x1920 9:16 vertical historical YouTube Short,
runs automated QA, and validates output constraints.
"""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from main import ShortsPipeline
from core.database import SessionLocal
from core.models import Job, Topic, RenderOutput, QAReport, UploadRecord


class TestEndToEndPipeline(unittest.TestCase):

    def setUp(self):
        self.pipeline = ShortsPipeline()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_complete_short_production_cycle(self):
        # Create a test topic
        topic = Topic(
            id="test_top_zanzibar",
            title="The 38-Minute Anglo-Zanzibar War (1896)",
            summary="In 1896, the British Empire defeated a rebel sultan in the shortest war in recorded history.",
            category="Unusual Wars",
            score=52.0
        )
        self.db.merge(topic)
        self.db.commit()

        # Run single job
        success = self.pipeline.run_single_job(topic=topic)
        self.assertTrue(success, "Pipeline execution failed!")

        # Verify job and render record
        job = self.db.query(Job).filter(Job.topic_id == topic.id).order_by(Job.updated_at.desc()).first()
        self.assertIsNotNone(job)
        self.assertEqual(job.state, "PUBLISHED")

        render = self.db.query(RenderOutput).filter(RenderOutput.job_id == job.id).first()
        self.assertIsNotNone(render)
        self.assertEqual(render.width, 1080)
        self.assertEqual(render.height, 1920)
        self.assertTrue(21.0 <= render.duration_sec <= 25.5, f"Duration was {render.duration_sec}")

        video_path = Path(render.video_path)
        self.assertTrue(video_path.exists())
        self.assertGreater(video_path.stat().st_size, 500000)

        # Verify QA report
        qa = self.db.query(QAReport).filter(QAReport.job_id == job.id).first()
        self.assertIsNotNone(qa)
        self.assertTrue(qa.passed)
        self.assertTrue(qa.resolution_ok)
        self.assertTrue(qa.duration_ok)
        self.assertTrue(qa.audio_ok)
        self.assertTrue(qa.license_ok)

        # Verify Upload record (Test Mode)
        upload = self.db.query(UploadRecord).filter(UploadRecord.job_id == job.id).first()
        self.assertIsNotNone(upload)
        self.assertEqual(upload.status, "TEST_VERIFIED")


if __name__ == "__main__":
    unittest.main()
