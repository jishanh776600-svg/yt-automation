import unittest
from unittest.mock import patch, MagicMock
from core.database import SessionLocal, init_db
from core.models import Job, SystemConfig, AssetRecord
from engines.tts_engine import (
    TTSEngine,
    AVAILABLE_VOICES,
    resolve_voice_config,
    get_active_voice,
    set_active_voice
)


class TestCanonicalVoiceRegistry(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.db = SessionLocal()
        cls.tts = TTSEngine()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def setUp(self):
        set_active_voice(self.db, "am_adam")

    def tearDown(self):
        set_active_voice(self.db, "am_adam")

    def test_01_canonical_registry_structure_and_completeness(self):
        """Verify all 6 supported voices have complete, distinct metadata and provider IDs."""
        self.assertEqual(len(AVAILABLE_VOICES), 6)
        voice_ids = [v["id"] for v in AVAILABLE_VOICES]
        self.assertEqual(len(voice_ids), len(set(voice_ids)), "Voice IDs must be strictly unique.")

        for v in AVAILABLE_VOICES:
            self.assertIn("id", v)
            self.assertIn("display_name", v)
            self.assertIn("gender", v)
            self.assertIn("accent", v)
            self.assertIn("kokoro_voice", v)
            self.assertIn("edge_voice", v)
            self.assertTrue(len(v["kokoro_voice"]) > 0)
            self.assertTrue(len(v["edge_voice"]) > 0)

    def test_02_all_fallbacks_are_strictly_distinct_and_accent_matched(self):
        """Verify no two distinct voices map to the same Edge-TTS fallback voice."""
        edge_voices = [v["edge_voice"] for v in AVAILABLE_VOICES]
        self.assertEqual(len(edge_voices), len(set(edge_voices)), "Edge-TTS fallback voices must be unique per voice ID.")

        # George must map to a British English voice
        george_cfg = resolve_voice_config("bm_george")
        self.assertTrue(george_cfg["edge_voice"].startswith("en-GB-"), "George must map to a British Edge-TTS voice.")
        self.assertEqual(george_cfg["accent"], "British")

        # Adam, Michael, Christopher must have distinct American voices
        adam_cfg = resolve_voice_config("am_adam")
        michael_cfg = resolve_voice_config("am_michael")
        chris_cfg = resolve_voice_config("en-US-ChristopherNeural")

        self.assertNotEqual(adam_cfg["edge_voice"], michael_cfg["edge_voice"])
        self.assertNotEqual(adam_cfg["edge_voice"], chris_cfg["edge_voice"])
        self.assertNotEqual(michael_cfg["edge_voice"], chris_cfg["edge_voice"])

    def test_03_resolve_voice_config_handles_valid_and_invalid_ids(self):
        """Verify resolve_voice_config retrieves correct entry or falls back safely to default."""
        # Valid ID
        cfg = resolve_voice_config("af_sarah")
        self.assertEqual(cfg["id"], "af_sarah")
        self.assertEqual(cfg["display_name"], "Sarah (US Female)")
        self.assertEqual(cfg["edge_voice"], "en-US-AriaNeural")

        # Invalid ID falls back safely to canonical default (Adam)
        invalid_cfg = resolve_voice_config("nonexistent_voice_404")
        self.assertEqual(invalid_cfg["id"], "am_adam")

    def test_04_preview_and_production_resolve_identical_voice_in_fallback(self):
        """Verify that when Kokoro is unavailable, preview and production call the exact same Edge voice."""
        with patch.object(self.tts, "generate_kokoro_audio", return_value=(False, 0.0)):
            with patch.object(self.tts, "_generate_edge_tts_async", return_value=(True, 4.5)) as mock_edge:
                for v in AVAILABLE_VOICES:
                    v_id = v["id"]
                    expected_edge = v["edge_voice"]

                    # 1. Preview call
                    mock_edge.reset_mock()
                    self.tts.generate_preview_sample(v_id, "Sample test text")
                    preview_voice_called = mock_edge.call_args[1].get("voice") or mock_edge.call_args[0][2]
                    self.assertEqual(preview_voice_called, expected_edge, f"Preview for {v_id} did not use {expected_edge}")

                    # 2. Production call
                    set_active_voice(self.db, v_id)
                    mock_edge.reset_mock()
                    self.tts.generate_narration(self.db, "Sample test text")
                    prod_voice_called = mock_edge.call_args[1].get("voice") or mock_edge.call_args[0][2]
                    self.assertEqual(prod_voice_called, expected_edge, f"Production for {v_id} did not use {expected_edge}")

                    # Invariant: Preview == Production
                    self.assertEqual(preview_voice_called, prod_voice_called)

    def test_05_production_narration_consumes_active_voice_from_db(self):
        """Verify production narration strictly respects the DB-persisted active voice."""
        set_active_voice(self.db, "af_bella")
        self.assertEqual(get_active_voice(self.db), "af_bella")

        with patch.object(self.tts, "generate_kokoro_audio", return_value=(True, 4.2)) as mock_kokoro:
            self.tts.generate_narration(self.db, "Testing voiceover delivery")
            voice_passed = mock_kokoro.call_args[1].get("voice") or mock_kokoro.call_args[0][2]
            self.assertEqual(voice_passed, "af_bella")

        set_active_voice(self.db, "bm_george")
        self.assertEqual(get_active_voice(self.db), "bm_george")

        with patch.object(self.tts, "generate_kokoro_audio", return_value=(True, 4.8)) as mock_kokoro:
            self.tts.generate_narration(self.db, "Testing voiceover delivery")
            voice_passed = mock_kokoro.call_args[1].get("voice") or mock_kokoro.call_args[0][2]
            self.assertEqual(voice_passed, "bm_george")


if __name__ == "__main__":
    unittest.main()
