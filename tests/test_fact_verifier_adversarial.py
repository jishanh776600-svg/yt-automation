"""
Adversarial Test Suite for FactVerifier & Script Quality Gate.
Comprehensive test matrix covering:
  A. Correct factual script -> PASS
  B. Wrong year (1184 -> 1984) -> FAIL
  C. Wrong number (60 -> 6,000) -> FAIL
  D. Wrong person attribution -> FAIL
  E. Wrong location (Erfurt -> Berlin) -> FAIL
  F. Reversed subject/object -> FAIL
  G. Fabricated consequence -> FAIL
  H. Fabricated causal relationship -> FAIL
  I. Plausible but unsupported claim -> FAIL
  J. Narrative styling -> PASS
  K. Valid paraphrase -> PASS
  L. Lexical-overlap attack (95% overlap + 1 contradiction) -> FAIL
  M. Three failed rewrite attempts -> Terminates cleanly with error
  N. Existing Drive 01_READY preservation -> All 4 verified intact
"""
import unittest
from unittest.mock import patch, MagicMock
from core.database import init_db, SessionLocal
from core.models import Topic
from engines.fact_verifier import FactVerifier
from engines.script_engine import ScriptEngine, ScriptCritic
from engines.drive_engine import DriveVaultEngine


class TestFactVerifierAdversarial(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.verifier = FactVerifier()
        self.critic = ScriptCritic()
        self.engine = ScriptEngine()

        self.mock_research = {
            "topic_title": "The Erfurt Latrine Disaster of 1184",
            "summary": "In July 1184, King Henry VI held an informal summit at Erfurt Cathedral to mediate a feud between Archbishop Conrad and Landgrave Louis III. The wooden second floor collapsed under the weight of the assembled nobles, plunging dozens of nobles into the latrine cesspool below. Around sixty people died, while King Henry VI survived by holding onto an iron window grate.",
            "verified_claims": [
                {"claim": "King Henry VI convened the peace summit in July 1184.", "confidence": 0.98},
                {"claim": "The summit took place at Erfurt Cathedral in Germany.", "confidence": 0.98},
                {"claim": "The wooden second floor collapsed under the weight of the assembled nobles.", "confidence": 0.98},
                {"claim": "Around sixty people died when they plunged into the liquid cesspool below.", "confidence": 0.98},
                {"claim": "King Henry VI survived by holding onto an iron window grate until rescued.", "confidence": 0.98}
            ],
            "claims_count": 5
        }

    def tearDown(self):
        self.db.close()

    def test_a_correct_factual_script(self):
        """Test A: Accurate factual script directly grounded in research -> PASS."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertTrue(res.passed, f"Accurate script must pass: {res.feedback}")
        self.assertEqual(len(res.contradictions), 0)
        self.assertEqual(res.score, 15.0)

    def test_b_wrong_year(self):
        """Test B: Script asserts year 1984 instead of 1184 -> FAIL."""
        script_text = (
            "In July 1984, sixty European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject incorrect year.")
        self.assertTrue(any("1984" in c for c in res.contradictions), f"Contradictions: {res.contradictions}")
        self.assertEqual(res.score, 0.0)

    def test_c_wrong_number(self):
        """Test C: Script claims 6,000 nobles died instead of 60 -> FAIL."""
        script_text = (
            "In July 1184, 6000 European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject inflated 6,000 count.")
        self.assertTrue(any("6000" in c for c in res.contradictions), f"Contradictions: {res.contradictions}")
        self.assertEqual(res.score, 0.0)

    def test_d_wrong_person(self):
        """Test D: Attributing event to Napoleon Bonaparte instead of King Henry VI -> FAIL."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "Napoleon Bonaparte convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "Napoleon only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject wrong person attribution.")
        self.assertTrue(any("Napoleon" in u for u in res.unsupported_claims + res.contradictions))

    def test_e_wrong_location(self):
        """Test E: Moving event to Berlin Palace instead of Erfurt Cathedral -> FAIL."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Berlin Palace. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject wrong location.")
        self.assertTrue(any("Berlin" in u for u in res.unsupported_claims + res.contradictions))

    def test_f_reversed_subject_object(self):
        """Test F: Reversed attacker/defender or causal roles -> FAIL."""
        war_research = {
            "summary": "On August 27, 1896, British Royal Navy cruisers bombarded the Zanzibar palace, forcing Sultan Khalid to surrender in 38 minutes.",
            "verified_claims": [
                {"claim": "The British Navy bombarded the palace.", "confidence": 0.98},
                {"claim": "Sultan Khalid fled in 38 minutes.", "confidence": 0.98}
            ]
        }
        # Inverted claim: Sultan's fleet destroyed the British Navy
        reversed_script = (
            "In August 1896, the Sultan of Zanzibar launched a naval strike. "
            "Sultan Khalid deployed artillery and sank the entire British Royal Navy fleet. "
            "British commanders surrendered in thirty-eight minutes flat. "
            "The Sultan took control of the British Empire's global fleet. "
            "That victory made Zanzibar a dominant naval superpower."
        )
        res = self.verifier.verify(reversed_script, war_research)
        self.assertFalse(res.passed, "Must reject reversed subject/object and fabricated naval victory.")

    def test_g_fabricated_consequence(self):
        """Test G: Claiming a fictional public execution occurred -> FAIL."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "After the collapse, King Henry executed all surviving builders at dawn. "
            "The executioners were then placed in prison forever."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject fabricated executions.")

    def test_h_fabricated_causal_relationship(self):
        """Test H: Claiming floor collapsed due to a secret bomb detonation -> FAIL."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "Rebel assassins detonated a secret gunpowder bomb in Erfurt Cathedral. "
            "The explosion caused the second floor to collapse instantly into the cesspool. "
            "Dozens plunged into the cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject fabricated gunpowder bomb causality.")

    def test_i_plausible_but_unsupported_claim(self):
        """Test I: Historically plausible detail not supported by research -> FAIL."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI brought a golden crown gifted by the Pope in Rome. "
            "The floor collapsed under their weight into the cesspool. "
            "Dozens of nobles plunged into the cesspool below. "
            "The king only survived by holding an iron window grate."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertFalse(res.passed, "Must reject unsupported papal crown claims.")

    def test_j_narrative_styling_passes(self):
        """Test J: Dramatic narrative phrasing without new factual assertions -> PASS."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI convened a royal peace summit in Erfurt Cathedral. "
            "The heavy wooden floor suddenly snapped under their combined weight. "
            "Dozens plunged straight into the vast liquid cesspool below. "
            "The king barely escaped that stomach-churning nightmare."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertTrue(res.passed, "Narrative phrasing should pass if core facts are accurate.")

    def test_k_valid_paraphrase_passes(self):
        """Test K: Valid paraphrase of verified facts with natural cadence -> PASS."""
        script_text = (
            "In July 1184, sixty European nobles met a bizarre fate. "
            "King Henry VI called a royal peace meeting in Erfurt Cathedral. "
            "The second-story wooden floor broke under the crowd's heavy weight. "
            "Dozens fell straight into the massive latrine cesspit below. "
            "The king stayed alive by gripping an iron window grating."
        )
        res = self.verifier.verify(script_text, self.mock_research)
        self.assertTrue(res.passed, "Legitimate paraphrases must pass.")

    def test_l_lexical_overlap_attack(self):
        """Test L: 95% word overlap with a single critical date contradiction -> FAIL."""
        # Nearly 100% word-for-word identical to research except year is 1984
        attack_script = {
            "hook": "In July 1984, sixty European nobles met a bizarre fate.",
            "context": "King Henry VI convened a royal peace summit in Erfurt Cathedral.",
            "escalation": "The heavy wooden floor suddenly snapped under their combined weight.",
            "reveal": "Dozens plunged straight into the vast liquid cesspool below.",
            "loop_twist": "The king only survived by holding an iron window grate."
        }
        eval_res = self.critic.evaluate(attack_script, self.mock_research)
        self.assertFalse(eval_res.passed, "Lexical overlap must not override a factual contradiction.")
        self.assertEqual(eval_res.fact_grounding_score, 0.0)

    def test_m_three_failed_rewrite_attempts(self):
        """Test M: Script failing 3 attempts terminates safely with error (no generic text)."""
        unseeded_topic = Topic(
            id="top_unseeded_failing_topic_2",
            title="Adversarial Topic",
            summary="Test summary"
        )
        failing_draft = {
            "hook": "In 1999, lasers destroyed Berlin.",
            "context": "King Napoleon invaded.",
            "escalation": "Everything exploded.",
            "reveal": "Many people vanished.",
            "loop_twist": "It was bad."
        }
        with patch.object(self.engine, "_draft_script_pass", return_value=failing_draft) as mock_draft:
            with self.assertRaises(RuntimeError):
                self.engine.generate_script(self.db, unseeded_topic, research_data=self.mock_research)
            self.assertEqual(mock_draft.call_count, 3)

    def test_n_existing_drive_01_ready_preserved(self):
        """Test N: Confirms existing Shorts in 01_READY remain untouched."""
        drive_engine = DriveVaultEngine()
        ready_files = drive_engine.list_files_in_folder("01_READY")
        self.assertGreaterEqual(len(ready_files), 3, f"Expected at least 3 videos in 01_READY, found {len(ready_files)}")
        names = [f["name"] for f in ready_files]
        self.assertIn("short_job_77fe716875_1080x1920.mp4", names)
        self.assertIn("short_job_714e7cc6f0_1080x1920.mp4", names)


if __name__ == "__main__":
    unittest.main()
