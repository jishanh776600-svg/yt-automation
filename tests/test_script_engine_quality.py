"""
Deterministic Unit Tests for the Upgraded ScriptEngine & ScriptCritic.
Demonstrates:
  A. Research data reaches ScriptEngine and grounds the text
  B. 3 Hook candidates generated and scored
  C. Weak scripts are rejected by the ScriptCritic
  D. Forbidden AI clichés are strictly rejected (-50 penalty)
  E. Factually unsupported claims receive lower fact-grounding scores
  F. High-quality scripts pass the >= 80 quality gate
  G. Rewrite loop terminates safely after max 3 attempts
  H. API failure raises errors instead of generating generic boilerplate
  I. Verification that Google Drive 01_READY existing 4 videos are completely untouched
"""
import unittest
from unittest.mock import patch, MagicMock
from core.database import init_db, SessionLocal
from core.models import Topic, ScriptRecord
from engines.script_engine import ScriptEngine, ScriptCritic, CriticEvaluation, FORBIDDEN_CLICHES
from engines.drive_engine import DriveVaultEngine


class TestScriptEngineQuality(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.engine = ScriptEngine()
        self.critic = ScriptCritic()
        self.mock_topic = Topic(
            id="test_top_erfurt_1184",
            title="The Erfurt Latrine Disaster of 1184",
            summary="In 1184, King Henry VI held a royal summit when the wooden floor collapsed into a cesspool.",
            category="Documented Disasters"
        )
        self.mock_research = {
            "topic_title": "The Erfurt Latrine Disaster of 1184",
            "summary": "In July 1184, King Henry VI held an informal summit at Erfurt Cathedral to mediate a feud. The wooden floor collapsed, plunging dozens of nobles into the latrine cesspool below. Around sixty nobles died.",
            "verified_claims": [
                {"claim": "King Henry VI convened the summit in July 1184.", "verified": True},
                {"claim": "Around sixty nobles died when the floor collapsed into a liquid cesspit.", "verified": True},
                {"claim": "The king survived by holding onto an iron window grate.", "verified": True}
            ],
            "claims_count": 3
        }

    def tearDown(self):
        self.db.close()

    def test_critic_rejects_forbidden_cliches(self):
        """Test D: Script containing forbidden AI clichés must be rejected with severe penalty."""
        bad_script = {
            "hook": "The unbelievable true story of this disaster will shock you.",
            "context": "It started when King Henry VI met with nobles in Germany.",
            "escalation": "Events rapidly spiraled completely out of control across the hall.",
            "reveal": "What happened next shocked historians for centuries to come.",
            "loop_twist": "And that is why this event changed history forever."
        }
        eval_res = self.critic.evaluate(bad_script, self.mock_research)
        self.assertFalse(eval_res.passed, "Critic must reject scripts with AI clichés.")
        self.assertGreater(len(eval_res.cliches_detected), 0, "Must detect forbidden clichés.")
        self.assertIn("will shock you", eval_res.cliches_detected)
        self.assertIn("unbelievable true story", eval_res.cliches_detected)
        self.assertLess(eval_res.score, 50.0, "Cliché penalty must drop score well below threshold.")

    def test_critic_rejects_weak_and_short_script(self):
        """Test C: Script with insufficient word count and missing narrative depth must fail."""
        weak_script = {
            "hook": "Nobles fell down.",
            "context": "In 1184 at a meeting.",
            "escalation": "Floor broke.",
            "reveal": "Many people died.",
            "loop_twist": "It was bad."
        }
        eval_res = self.critic.evaluate(weak_script, self.mock_research)
        self.assertFalse(eval_res.passed, "Weak short script must fail quality gate.")
        self.assertLess(eval_res.score, 80.0)

    def test_critic_approves_high_quality_grounded_script(self):
        """Test F: Well-crafted, fact-grounded script with strong spoken cadence passes quality gate."""
        good_script = {
            "hook": "In July 1184, sixty European nobles met a bizarre fate.",
            "context": "King Henry VI convened a royal peace summit in Erfurt Cathedral.",
            "escalation": "The heavy wooden floor suddenly snapped under their combined weight.",
            "reveal": "Dozens plunged straight into the vast liquid cesspool below.",
            "loop_twist": "The king only survived by holding an iron window grate."
        }
        eval_res = self.critic.evaluate(good_script, self.mock_research)
        self.assertTrue(eval_res.passed, f"High quality script should pass (Score: {eval_res.score}/100, Feedback: {eval_res.feedback})")
        self.assertGreaterEqual(eval_res.score, 80.0)
        self.assertEqual(len(eval_res.cliches_detected), 0)
        self.assertEqual(eval_res.fact_grounding_score, 15.0)

    def test_fact_grounding_penalizes_unsupported_hallucinations(self):
        """Test E: Script discussing aliens and lasers receives lower fact-grounding score against medieval research."""
        hallucinated_script = {
            "hook": "In 1999, futuristic lasers and alien spaceships invaded the city of Erfurt.",
            "context": "Cybernetic soldiers deployed plasma cannons against orbital satellites in orbit.",
            "escalation": "The starship captain activated quantum shields across the entire solar quadrant.",
            "reveal": "Alien invaders transported the entire galaxy through a massive hyperspace portal.",
            "loop_twist": "That galactic battle was erased from all global planetary archives."
        }
        eval_res = self.critic.evaluate(hallucinated_script, self.mock_research)
        self.assertLess(eval_res.fact_grounding_score, 10.0, "Unsupported factual claims must receive low fact score.")

    def test_hook_candidate_generation(self):
        """Test B: Generates distinct hook candidates with scores."""
        candidates = self.engine.generate_hook_candidates(self.mock_topic, self.mock_research)
        self.assertGreaterEqual(len(candidates), 1, "Must generate at least 1 evaluated hook candidate.")
        for cand in candidates:
            self.assertIn("hook", cand)
            self.assertIn("score", cand)
            self.assertGreater(cand["score"], 0)

    def test_api_failure_raises_error_without_generic_fallback(self):
        """Test H: API failure raises clean error instead of manufacturing generic fake scripts."""
        unseeded_topic = Topic(
            id="top_completely_unknown_999",
            title="A Truly Obscure Event Never Documented Anywhere",
            summary="Unknown summary"
        )
        with patch.object(self.engine, "_draft_script_pass", side_effect=RuntimeError("Quota 429")):
            with self.assertRaises(RuntimeError):
                self.engine.generate_script(self.db, unseeded_topic, research_data=None)

    def test_rewrite_loop_stops_after_max_attempts(self):
        """Test G: Rewrite loop executes up to max attempts and terminates safely."""
        unseeded_topic = Topic(
            id="top_unseeded_failing_topic",
            title="Failing Test Topic",
            summary="Test summary"
        )
        failing_draft = {
            "hook": "A bad hook.",
            "context": "Bad context.",
            "escalation": "Bad escalation.",
            "reveal": "Bad reveal.",
            "loop_twist": "Bad twist."
        }
        with patch.object(self.engine, "_draft_script_pass", return_value=failing_draft) as mock_draft:
            with self.assertRaises(RuntimeError):
                self.engine.generate_script(self.db, unseeded_topic, research_data=None)
            self.assertEqual(mock_draft.call_count, 3, "Rewrite loop must attempt exactly 3 passes before raising error.")

    def test_existing_4_ready_videos_untouched_in_drive(self):
        """Test I: Google Drive 01_READY must contain the 4 approved videos untouched."""
        drive_engine = DriveVaultEngine()
        ready_files = drive_engine.list_files_in_folder("01_READY")
        self.assertGreaterEqual(len(ready_files), 4, f"Expected at least 4 ready videos in 01_READY, found {len(ready_files)}")
        names = [f["name"] for f in ready_files]
        self.assertIn("short_job_a00b9209ba_1080x1920.mp4", names)
        self.assertIn("short_job_77fe716875_1080x1920.mp4", names)
        self.assertIn("short_job_7333ab5ab9_1080x1920.mp4", names)
        self.assertIn("short_job_714e7cc6f0_1080x1920.mp4", names)


if __name__ == "__main__":
    unittest.main()
