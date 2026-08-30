"""
Unit tests for Pipeline Engines (Topic, Research, Script, Storyboard).
"""
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import init_db, SessionLocal
from core.models import Topic
from engines.topic_discovery import TopicDiscoveryEngine
from engines.research_engine import ResearchEngine
from engines.script_engine import ScriptEngine
from engines.storyboard_engine import StoryboardEngine


class TestPipelineEngines(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.topic_engine = TopicDiscoveryEngine()
        self.research_engine = ResearchEngine()
        self.script_engine = ScriptEngine()
        self.storyboard_engine = StoryboardEngine()

    def tearDown(self):
        self.db.close()

    def test_topic_discovery_and_scoring(self):
        topics = self.topic_engine.discover_topics(self.db, limit=2)
        self.assertGreater(len(topics), 0)
        self.assertTrue(topics[0].score >= 0.0)

    def test_research_and_fact_check(self):
        import uuid
        topic_id = f"test_topic_{uuid.uuid4().hex[:8]}"
        topic = Topic(
            id=topic_id,
            title="The Great Stink of London (1858)",
            summary="In 1858 the Thames river smelled so bad Parliament soaked curtains in lime.",
            category="Documented Disasters",
            score=50.0
        )
        self.db.add(topic)
        self.db.commit()

        res = self.research_engine.research_topic(self.db, topic)
        self.assertTrue(res["verified"])
        self.assertGreater(res["claims_count"], 0)

    def test_script_generation_constraints(self):
        topic = self.db.query(Topic).first()
        script = self.script_engine.generate_script(self.db, topic)
        self.assertIsNotNone(script)
        self.assertTrue(45 <= script.word_count <= 65)
        self.assertTrue(20.0 <= script.estimated_duration_sec <= 26.0)

    def test_storyboard_breakdown(self):
        topic = self.db.query(Topic).first()
        script = self.script_engine.generate_script(self.db, topic)
        shots = self.storyboard_engine.create_storyboard(script)
        self.assertEqual(len(shots), 5)
        self.assertIn("zoom", shots[0]["camera_motion"])


if __name__ == "__main__":
    unittest.main()
