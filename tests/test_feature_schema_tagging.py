"""
Unit & Integration Test Suite for Feature Schema Tagging (Self-Improvement Phase 1).
Validates:
1. Idempotent SQLite database migrations.
2. Backward-compatible querying of legacy records (handling NULL metadata).
3. Classification & persistence of hook_archetype on ScriptRecord.
4. Classification & persistence of duration_target on ScriptRecord.
5. Persistence of bgm_mood and motion_style on RenderOutput.
6. Safe serialization & retrieval across all pipeline records.
"""
import unittest
import uuid
from datetime import datetime
from core.database import init_db, SessionLocal
from core.models import ScriptRecord, RenderOutput, Topic, Job
from engines.script_engine import ScriptEngine
from engines.render_engine import RenderEngine


class TestFeatureSchemaTagging(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.script_engine = ScriptEngine()

    def tearDown(self):
        self.db.close()

    def test_database_initialization_and_migrations(self):
        """Verify init_db() applies idempotent column migrations without errors."""
        try:
            init_db()
            init_db()  # Call twice to prove idempotency
            success = True
        except Exception as e:
            success = False
        self.assertTrue(success, "Database schema migration must be idempotent and error-free.")

    def test_legacy_record_backward_compatibility(self):
        """Verify legacy ScriptRecord and RenderOutput without metadata can be queried without crashing."""
        # Query all existing scripts and renders
        scripts = self.db.query(ScriptRecord).all()
        renders = self.db.query(RenderOutput).all()

        for s in scripts:
            # Must safely access attributes without AttributeError
            self.assertTrue(hasattr(s, "hook_archetype"))
            self.assertTrue(hasattr(s, "duration_target"))

        for r in renders:
            self.assertTrue(hasattr(r, "bgm_mood"))
            self.assertTrue(hasattr(r, "motion_style"))

    def test_hook_archetype_classification(self):
        """Verify hook archetype classification logic across the standard taxonomy."""
        cases = [
            ("In 1858, toxic sewage in the River Thames overwhelmed Parliament.", "DATE_TIME_ANCHOR"),
            ("On August 27, 1896, the shortest war in history began.", "DATE_TIME_ANCHOR"),
            ("Three Royal Navy cruisers opened fire on the palace at dawn.", "IN_MEDIAS_RES"),
            ("A massive storage tank burst in Boston, releasing hot molasses.", "IN_MEDIAS_RES"),
            ("Imagine a European town where borders cut through living rooms.", "HYPOTHETICAL_CURIOSITY"),
            ("What if a single trespassing pig almost started a world war?", "HYPOTHETICAL_CURIOSITY"),
            ("In 1590, 115 English settlers vanished leaving only one carved word.", "DATE_TIME_ANCHOR"),
            ("The entire colony was lost in the woods without a trace.", "UNSOLVED_MYSTERY"),
            ("A bizarre legal contradiction almost sparked an armed war.", "CONTRADICTION_SHOCK"),
            ("General history fact without specific keywords.", "OTHER")
        ]

        for hook_text, expected_archetype in cases:
            classified = self.script_engine.classify_hook_archetype(hook_text)
            self.assertEqual(classified, expected_archetype, f"Failed for hook: '{hook_text}'")

    def test_duration_target_classification(self):
        """Verify duration target classification into standard brackets."""
        self.assertEqual(self.script_engine.classify_duration_target(21.5), "ULTRA_TIGHT")
        self.assertEqual(self.script_engine.classify_duration_target(22.4), "ULTRA_TIGHT")
        self.assertEqual(self.script_engine.classify_duration_target(22.8), "SWEET_SPOT")
        self.assertEqual(self.script_engine.classify_duration_target(23.5), "SWEET_SPOT")
        self.assertEqual(self.script_engine.classify_duration_target(24.2), "NARRATIVE_RICH")
        self.assertEqual(self.script_engine.classify_duration_target(26.0), "NARRATIVE_RICH")

    def test_script_record_metadata_persistence(self):
        """Verify newly created ScriptRecord persists hook_archetype and duration_target."""
        test_topic_id = f"top_test_{uuid.uuid4().hex[:8]}"
        topic = Topic(
            id=test_topic_id,
            title="The Test Historical Incident",
            summary="A test incident summary.",
            category="Documented Disasters",
            score=50.0
        )
        self.db.add(topic)
        self.db.commit()

        script_id = f"scr_test_{uuid.uuid4().hex[:8]}"
        script_rec = ScriptRecord(
            id=script_id,
            topic_id=test_topic_id,
            hook="In 1919, a massive tank burst in Boston.",
            context="Context test sentence with facts.",
            escalation="Escalation test sentence.",
            reveal="Reveal test sentence.",
            loop_twist="Loop twist ending.",
            full_text="In 1919, a massive tank burst in Boston. Context test sentence with facts. Escalation test sentence. Reveal test sentence. Loop twist ending.",
            word_count=23,
            estimated_duration_sec=22.8,
            hook_archetype="DATE_TIME_ANCHOR",
            duration_target="SWEET_SPOT",
            status="APPROVED"
        )
        self.db.add(script_rec)
        self.db.commit()

        # Query back from DB
        fetched = self.db.query(ScriptRecord).filter(ScriptRecord.id == script_id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.hook_archetype, "DATE_TIME_ANCHOR")
        self.assertEqual(fetched.duration_target, "SWEET_SPOT")

    def test_render_output_metadata_persistence(self):
        """Verify newly created RenderOutput persists bgm_mood and motion_style."""
        job_id = f"job_test_{uuid.uuid4().hex[:8]}"
        job = Job(id=job_id, state="READY_TO_UPLOAD")
        self.db.add(job)
        self.db.commit()

        rnd_id = f"rnd_test_{uuid.uuid4().hex[:8]}"
        render_rec = RenderOutput(
            id=rnd_id,
            job_id=job_id,
            video_path="/tmp/test_video.mp4",
            width=1080,
            height=1920,
            fps=30.0,
            duration_sec=23.1,
            video_codec="h264",
            audio_codec="aac",
            file_size_bytes=15000000,
            bgm_mood="Historical / Serious Documentary",
            motion_style="DYNAMIC_ZOOM_PAN"
        )
        self.db.add(render_rec)
        self.db.commit()

        # Query back from DB
        fetched = self.db.query(RenderOutput).filter(RenderOutput.id == rnd_id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.bgm_mood, "Historical / Serious Documentary")
        self.assertEqual(fetched.motion_style, "DYNAMIC_ZOOM_PAN")


if __name__ == "__main__":
    unittest.main()
