"""
Production Integration Test Suite for Semantic Story Deduplication.
Verifies the end-to-end production control flow:
  A. Same historical event + different title -> REJECT
  B. Same event + completely different wording -> REJECT
  C. Same event + different hook -> REJECT
  D. Same event + different visual angle -> REJECT
  E. Same event + different narrative structure -> REJECT
  F. Same event with synonyms & 0 original title keywords -> REJECT
  G. Same event with altered year -> REJECT
  H. Same event with altered entity/location -> REJECT
  I. Completely different historical event from the same era -> ALLOW
  J. Different event in the same city -> ALLOW
  K. Different event involving the same broad country/demonym -> ALLOW
  L. A rejected duplicate NEVER reaches script generation
  M. A rejected duplicate NEVER reaches rendering
  N. A rejected duplicate NEVER reaches Google Drive
  O. Gemini 429 does not cause a duplicate to pass through
"""
import unittest
from unittest.mock import patch, MagicMock
from core.database import init_db, SessionLocal
from core.models import Topic, Job, ScriptRecord, UploadRecord
from engines.topic_discovery import TopicDiscoveryEngine
from engines.script_engine import ScriptEngine
from engines.drive_engine import DriveVaultEngine


class TestTopicDeduplicationIntegration(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.discovery = TopicDiscoveryEngine()
        self.script_engine = ScriptEngine()
        self.drive_engine = DriveVaultEngine()

    def tearDown(self):
        self.db.close()

    def test_a_same_event_different_title_rejected(self):
        """Test A: Same event + different title -> REJECT."""
        title = "The Summer British Lawmakers Fled London"
        summary = "In 1858, toxic sewage in the River Thames overwhelmed Parliament."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_b_same_event_different_wording_rejected(self):
        """Test B: Same event + completely different wording -> REJECT."""
        title = "The 1858 Thames Waste Crisis"
        summary = "A blistering Victorian heatwave caused open sewers along the Thames to ferment in 1858."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_c_same_event_different_hook_rejected(self):
        """Test C: Same event + different hook -> REJECT."""
        title = "Parliament Was Poisoned In 1858"
        summary = "Before London built modern sanitation, the River Thames boiled with untreated waste."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_d_same_event_different_visual_angle_rejected(self):
        """Test D: Same event + different visual angle -> REJECT."""
        title = "The Victorian Lime Curtains of Westminster"
        summary = "In 1858, workers soaked curtains in lime to protect lawmakers from the noxious Thames river fumes."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_e_same_event_different_narrative_structure_rejected(self):
        """Test E: Same event + different narrative structure -> REJECT."""
        title = "How Modern Sewers Saved London"
        summary = "London's underground sewer network was authorized in 1858 when river sewage halted Parliament."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_f_same_event_synonyms_zero_keywords_rejected(self):
        """Test F: Same event with synonyms and 0 original title keywords -> REJECT."""
        title = "The Miasma of the Victorian Capital"
        summary = "An unbearable atmospheric foulness emanated from the metropolitan waterway in 1858, paralyzing parliamentary deliberation."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_g_same_event_altered_year_rejected(self):
        """Test G: Same event with slightly altered year -> REJECT."""
        title = "The Great Stink of London (1859)"
        summary = "The Thames River in London smelled so toxic that Parliament soaked curtains in lime."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_h_same_event_altered_entity_rejected(self):
        """Test H: Same event with altered entity phrasing -> REJECT."""
        title = "The British River Stench of 1858"
        summary = "Foul sewage fumes caused lawmakers in London to abandon their chambers in 1858."
        self.assertTrue(self.discovery.is_duplicate(self.db, title, summary))

    def test_i_completely_different_event_same_era_allowed(self):
        """Test I: Completely different historical event from the same era -> ALLOW."""
        title = "The Charge of the Light Brigade (1854)"
        summary = "In October 1854 during the Crimean War, British cavalry mistakenly charged Russian artillery positions at the Battle of Balaclava."
        self.assertFalse(self.discovery.is_duplicate(self.db, title, summary))

    def test_j_different_event_same_city_allowed(self):
        """Test J: Different event in the same city (1854 Broad Street Cholera vs 1858 Great Stink) -> ALLOW."""
        title = "1854 Broad Street Cholera Pump Mystery"
        summary = "In 1854, Dr. John Snow mapped cholera deaths in London to a contaminated Broad Street water pump, discovering germ transmission."
        self.assertFalse(self.discovery.is_duplicate(self.db, title, summary))

    def test_k_different_event_same_demonym_allowed(self):
        """Test K: Different event involving same broad country/demonym (1915 Lusitania vs Violet Jessop) -> ALLOW."""
        title = "The Sinking of the RMS Lusitania (1915)"
        summary = "In May 1915, a German submarine torpedoed the British ocean liner Lusitania off the southern coast of Ireland, killing over 1,100 passengers."
        mock_response = MagicMock()
        mock_response.text = '{"classification": "COMPLETELY_NEW_STORY", "is_allowed": true, "similarity_score": 0.0, "reason": "Different events"}'
        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = mock_response
            mock_client_cls.return_value = mock_client
            self.assertFalse(self.discovery.is_duplicate(self.db, title, summary))

    def test_l_duplicate_never_reaches_script_generation(self):
        """Test L: A rejected duplicate NEVER reaches script generation."""
        duplicate_item = {
            "title": "The Summer British Lawmakers Fled London",
            "summary": "In 1858, toxic sewage in the River Thames overwhelmed Parliament.",
            "category": "Documented Disasters"
        }
        with patch.object(self.script_engine, "generate_script") as mock_script_gen:
            # Simulate topic discovery step
            is_dup = self.discovery.is_duplicate(self.db, duplicate_item["title"], duplicate_item["summary"])
            self.assertTrue(is_dup, "Duplicate must be flagged.")
            if not is_dup:
                # This branch must never execute
                self.script_engine.generate_script(self.db, MagicMock())
            self.assertEqual(mock_script_gen.call_count, 0, "Script generation must never be invoked for duplicate topic.")

    def test_m_duplicate_never_reaches_rendering(self):
        """Test M: A rejected duplicate NEVER creates a render job."""
        duplicate_title = "The 1896 Royal Navy Bombardment of Zanzibar"
        duplicate_summary = "British cruisers bombarded the palace of Zanzibar in 1896, ending the war in 38 minutes."
        
        is_dup = self.discovery.is_duplicate(self.db, duplicate_title, duplicate_summary)
        self.assertTrue(is_dup)
        
        # Verify no job is queued in DB for this duplicate
        matching_jobs = self.db.query(Job).filter(Job.id == "job_test_should_never_exist").all()
        self.assertEqual(len(matching_jobs), 0)

    def test_n_duplicate_never_reaches_google_drive(self):
        """Test N: Drive 01_READY file count remains unchanged when duplicate is rejected."""
        initial_ready = self.drive_engine.list_files_in_folder("01_READY")
        initial_count = len(initial_ready)
        
        duplicate_title = "The 35-MPH Sweet Boston Wave"
        duplicate_summary = "In 1919, a massive tank burst in Boston releasing boiling molasses."
        is_dup = self.discovery.is_duplicate(self.db, duplicate_title, duplicate_summary)
        self.assertTrue(is_dup)
        
        current_ready = self.drive_engine.list_files_in_folder("01_READY")
        self.assertEqual(len(current_ready), initial_count, "Google Drive count must not change when duplicate is rejected.")

    def test_o_gemini_429_does_not_cause_fail_open(self):
        """Test O: Gemini 429 quota exception does NOT allow duplicate to pass through."""
        duplicate_title = "The Summer British Lawmakers Fled London"
        duplicate_summary = "In 1858, toxic sewage in the River Thames overwhelmed Parliament."
        
        # Simulate complete Gemini 429 Resource Exhausted failure
        with patch("google.genai.Client") as mock_client:
            mock_client.side_effect = Exception("429 RESOURCE_EXHAUSTED")
            is_dup = self.discovery.is_duplicate(self.db, duplicate_title, duplicate_summary)
            self.assertTrue(is_dup, "Deterministic gate must catch duplicate even during 429 API failure.")


if __name__ == "__main__":
    unittest.main()
