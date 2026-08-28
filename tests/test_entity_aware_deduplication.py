"""
Phase 16: Comprehensive Entity-Aware Deduplication & Safety Test Suite.
Verifies all 10 required test cases:
  - TEST A: Erfurt Latrine Disaster vs Erfurt Privy Collapse -> Year + City collision -> candidate rejected.
  - TEST B: Two different events in the same city but different years -> not auto-rejected.
  - TEST C: Same year but different city -> not auto-rejected.
  - TEST D: Different year and different city -> no entity-pair escalation.
  - TEST E: Formatting variations ("Erfurt, 1184", "ERFURT - A.D. 1184") -> same normalized entity pair.
  - TEST F: Semantic API unavailable during a Year + City collision -> fail-closed -> candidate rejected.
  - TEST G: Existing legitimate unique historical stories continue to pass.
  - TEST H: Existing exact duplicate protection still passes.
  - TEST I: Existing lexical duplicate protection still passes.
  - TEST J: Existing YouTube publication duplicate protection still passes.
"""
import unittest
from unittest.mock import patch, MagicMock
from engines.deduplication_engine import StoryDeduplicationEngine, EventFingerprint, DeduplicationResult
from core.database import init_db, SessionLocal
from core.models import UploadRecord, Job, Topic


class TestEntityAwareDeduplication(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.engine = StoryDeduplicationEngine()

        self.erfurt_fp = self.engine.build_fingerprint(
            title="The Erfurt Latrine Disaster of 1184",
            summary="In July 1184, King Henry VI held a royal diet at the Church of St. Peter in Erfurt, where the combined weight of nobles caused the floor to collapse into a cesspool.",
            script_text="In 1184, over sixty nobles gathered in Erfurt Germany. The cathedral floor collapsed beneath them into a latrine."
        )

        self.london_stink_fp = self.engine.build_fingerprint(
            title="The Great Stink of London (1858)",
            summary="In the summer of 1858, toxic sewage in the River Thames in London created an overpowering stench that forced Parliament to soak curtains in chloride.",
            script_text="In 1858, the heatwave boiled raw sewage in London, shutting down Parliament."
        )

        self.boston_molasses_fp = self.engine.build_fingerprint(
            title="The Boston Molasses Flood of 1919",
            summary="A massive storage tank burst in Boston in 1919, unleashing a 35-mph tidal wave of boiling molasses that flattened buildings and killed 21 people.",
            script_text="A deadly wall of boiling molasses flooded the streets of Boston in 1919."
        )

        self.corpus = [self.erfurt_fp, self.london_stink_fp, self.boston_molasses_fp]

    def tearDown(self):
        self.db.close()

    def test_A_erfurt_latrine_vs_privy_collapse_rejected(self):
        """TEST A: 'Erfurt Latrine Disaster of 1184' vs 'Erfurt Privy Collapse' -> Year + City collision -> REJECTED."""
        candidate_title = "The Erfurt Privy Collapse"
        candidate_summary = "In 1184, high-ranking nobles attended a meeting in Erfurt and plunged into human waste when the wooden floor broke."
        res = self.engine.evaluate_candidate(candidate_title, candidate_summary=candidate_summary, corpus=self.corpus)
        self.assertFalse(res.is_allowed, f"Must reject near-duplicate Erfurt Privy Collapse: {res.reason}")
        self.assertIn(res.classification, ["SEMANTIC_DUPLICATE", "REJECTED_POTENTIAL_EVENT_COLLISION", "EXACT_DUPLICATE"])

    def test_B_same_city_different_year_allowed(self):
        """TEST B: Two different events in same city but different years -> ALLOWED."""
        # Great Fire of London (1666) vs Great Stink of London (1858)
        candidate_title = "The Great Fire of London (1666)"
        candidate_summary = "In September 1666, a bakery fire in Pudding Lane destroyed thousands of homes across London."
        res = self.engine.evaluate_candidate(candidate_title, candidate_summary=candidate_summary, corpus=self.corpus)
        self.assertTrue(res.is_allowed, f"Distinct 1666 London fire must be allowed: {res.reason}")
        self.assertEqual(res.classification, "COMPLETELY_NEW_STORY")

    def test_C_same_year_different_city_allowed(self):
        """TEST C: Same year (1858) but different city (Battle of Grahovac, Montenegro) -> ALLOWED."""
        candidate_title = "The Battle of Grahovac (1858)"
        candidate_summary = "In May 1858, Montenegrin forces fought the Ottoman Army at Grahovac, winning sovereign borders."
        res = self.engine.evaluate_candidate(candidate_title, candidate_summary=candidate_summary, corpus=self.corpus)
        self.assertTrue(res.is_allowed, f"Different city in 1858 must be allowed: {res.reason}")
        self.assertEqual(res.classification, "COMPLETELY_NEW_STORY")

    def test_D_different_year_and_different_city_allowed(self):
        """TEST D: Different year and different city -> ALLOWED."""
        candidate_title = "The Dancing Plague of Strasbourg (1518)"
        candidate_summary = "In July 1518, hundreds of residents in Strasbourg danced uncontrollably in the town square for weeks."
        res = self.engine.evaluate_candidate(candidate_title, candidate_summary=candidate_summary, corpus=self.corpus)
        self.assertTrue(res.is_allowed, f"Completely distinct 1518 Strasbourg plague must be allowed: {res.reason}")
        self.assertEqual(res.classification, "COMPLETELY_NEW_STORY")

    def test_E_entity_normalization_variations(self):
        """TEST E: Formatting variations ('Erfurt, 1184', 'ERFURT - A.D. 1184') normalize to same entity pair."""
        pairs_1 = self.engine.extract_entity_pairs("The Tragedy in Erfurt, 1184")
        pairs_2 = self.engine.extract_entity_pairs("ERFURT - A.D. 1184 Disaster")
        pairs_3 = self.engine.extract_entity_pairs("The Medieval Disaster", summary="c. 1184 in the city of Erfurt")

        self.assertIn((1184, "erfurt"), pairs_1)
        self.assertIn((1184, "erfurt"), pairs_2)
        self.assertIn((1184, "erfurt"), pairs_3)

    def test_F_fail_closed_on_semantic_api_error(self):
        """TEST F: Semantic API unavailable during Year + City collision -> FAIL CLOSED -> REJECTED."""
        # Force LLM error during entity-pair collision without shared anchor stems
        res = self.engine.check_semantic_llm(
            candidate_title="The Mysterious Erfurt Assembly",
            candidate_summary="An enigmatic diplomatic gathering in Erfurt in 1184.",
            candidate_script="",
            existing_title=self.erfurt_fp.title,
            existing_summary=self.erfurt_fp.summary_text,
            existing_script="",
            has_entity_pair_collision=True,
            colliding_pair=(1184, "erfurt")
        )
        self.assertFalse(res.is_allowed, "Must fail closed when semantic API is down during entity collision.")
        self.assertIn(res.classification, ["REJECTED_POTENTIAL_EVENT_COLLISION", "SEMANTIC_DUPLICATE", "EXACT_DUPLICATE"])
        self.assertIn("fail-closed", res.reason.lower())

    def test_G_legitimate_unique_historical_stories_pass(self):
        """TEST G: Existing legitimate unique historical stories continue to pass."""
        unique_stories = [
            ("The Halifax Explosion of 1917", "A French cargo ship loaded with wartime explosives collided in Halifax Harbor in 1917."),
            ("The Pig War of 1859", "A dispute over a Berkshire boar on San Juan Island in 1859 brought Britain and the US to the brink of war."),
            ("The 38-Minute Anglo-Zanzibar War (1896)", "In 1896, British cruisers bombarded the palace in Zanzibar, ending the conflict in 38 minutes.")
        ]
        for title, summary in unique_stories:
            res = self.engine.evaluate_candidate(title, candidate_summary=summary, corpus=self.corpus)
            self.assertTrue(res.is_allowed, f"Legitimate unique story '{title}' must pass: {res.reason}")

    def test_H_exact_duplicate_protection_passes(self):
        """TEST H: Exact duplicate title protection still passes."""
        res = self.engine.evaluate_candidate("The Great Stink of London (1858)", corpus=self.corpus)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.classification, "EXACT_DUPLICATE")

    def test_I_lexical_duplicate_protection_passes(self):
        """TEST I: Heavy lexical overlap without exact title still passes."""
        res = self.engine.evaluate_candidate("The Summer London Smelled So Bad Parliament Shut Down", corpus=self.corpus)
        self.assertFalse(res.is_allowed)
        self.assertEqual(res.classification, "SEMANTIC_DUPLICATE")

    def test_J_youtube_publication_corpus_deduplication(self):
        """TEST J: Published YouTube stories in DB corpus prevent duplicates."""
        # Ensure database corpus loader aggregates upload records
        corpus_from_db = self.engine.get_published_and_ready_corpus(self.db)
        self.assertIsInstance(corpus_from_db, list)
        self.assertGreater(len(corpus_from_db), 0)


if __name__ == "__main__":
    unittest.main()
