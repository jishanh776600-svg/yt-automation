"""
Targeted Verification Suite for BGM Intelligence, Theme Scoring, and SQLite Persistence.
Validates:
1. Historical/war topic selects best_historical.
2. Mystery/cipher topic selects flux_ambient.
3. Suspense/high-tension topic selects suspense_climax.
4. Tragedy/memorial topic selects emotional_sad.
5. Generic words ("discovered", "scientists", "history", "ancient") do not force flux_ambient.
6. Recent BGM usage persists across separate selector instances and processes via SQLite SystemConfig.
7. Anti-monotony: A compatible alternative track can beat a recently used track when comparable.
8. Existing BGM loudness targets (-30 LUFS bed, -14 LUFS master) remain untouched.
"""
import os
import json
import unittest
from pathlib import Path

from core.database import init_db, SessionLocal
from core.models import SystemConfig, Topic
from config.constants import TARGET_LUFS, TARGET_BGM_LUFS, BGM_MIX_VOLUME_DB
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.visual_intelligence.bgm_selector import BGMSelector, SYSTEM_CONFIG_KEY


class TestBGMIntelligenceAndPersistence(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        # Clean up any existing BGM test config in SQLite
        cfg = self.db.query(SystemConfig).filter(SystemConfig.key == SYSTEM_CONFIG_KEY).first()
        if cfg:
            self.db.delete(cfg)
            self.db.commit()

    def tearDown(self):
        # Clean up test config
        cfg = self.db.query(SystemConfig).filter(SystemConfig.key == SYSTEM_CONFIG_KEY).first()
        if cfg:
            self.db.delete(cfg)
            self.db.commit()
        self.db.close()

    def test_historical_war_topic_selects_best_historical(self):
        """Historical/warfare topic selects best_historical."""
        mixer = AudioMixer()
        _, track_key, _, reason = mixer.select_bgm_track(
            category="Warfare and Empires",
            title="The Fall of the Byzantine Empire",
            summary="Emperor Constantine XI led the defenders during the Ottoman siege.",
            script_text="Soldiers manned the walls as cannons breached the ancient gates of the capital."
        )
        self.assertEqual(track_key, "best_historical", f"Expected best_historical, got {track_key} ({reason})")

    def test_mystery_cipher_topic_selects_flux_ambient(self):
        """Mystery/cipher topic selects flux_ambient."""
        mixer = AudioMixer()
        _, track_key, _, reason = mixer.select_bgm_track(
            category="Historical Mysteries",
            title="The Voynich Manuscript Cipher",
            summary="A mysterious manuscript written in an unreadable cryptic script.",
            script_text="Cryptic ciphers and strange occult symbols continue to baffle linguists."
        )
        self.assertEqual(track_key, "flux_ambient", f"Expected flux_ambient, got {track_key} ({reason})")

    def test_suspense_high_tension_topic_selects_suspense_climax(self):
        """Suspense/high-tension topic selects suspense_climax."""
        mixer = AudioMixer()
        _, track_key, _, reason = mixer.select_bgm_track(
            category="High-Stakes Crises",
            title="The Great Prison Breakout Escape",
            summary="A high tension manhunt as detectives race against time to capture fugitives.",
            script_text="Sirens wailed in a thrilling chase as police pursued the dangerous escapee."
        )
        self.assertEqual(track_key, "suspense_climax", f"Expected suspense_climax, got {track_key} ({reason})")

    def test_tragedy_memorial_topic_selects_emotional_sad(self):
        """Tragedy/memorial topic selects emotional_sad."""
        mixer = AudioMixer()
        _, track_key, _, reason = mixer.select_bgm_track(
            category="Human Tragedy",
            title="The Devastating Sinking of the Ferry",
            summary="A heartbreaking loss of life as victims were trapped beneath the waves.",
            script_text="Families wept in mournful grief at the memorial for those who perished."
        )
        self.assertEqual(track_key, "emotional_sad", f"Expected emotional_sad, got {track_key} ({reason})")

    def test_generic_words_do_not_force_flux_ambient(self):
        """Generic words like 'discovered', 'scientists', 'history', 'ancient' do not force flux_ambient."""
        mixer = AudioMixer()
        _, track_key, _, reason = mixer.select_bgm_track(
            category="American History",
            title="How Scientists Discovered Ancient Agriculture",
            summary="In 1920, historians and scientists discovered how ancient farmers cultivated the plains.",
            script_text="The history of farming shows how crops were planted across centuries."
        )
        self.assertNotEqual(track_key, "flux_ambient", f"flux_ambient should not win on generic words alone: {reason}")
        self.assertEqual(track_key, "best_historical", f"Expected best_historical for American History: {reason}")

    def test_persistence_across_instances_and_processes(self):
        """Recent BGM usage persists across separate selector instances via SQLite SystemConfig."""
        selector_1 = BGMSelector()
        selected_1 = selector_1.select_track(
            category="Warfare",
            title="The Battle of Waterloo",
            script_text="Napoleon led his army against the British alliance."
        )
        self.assertEqual(selected_1, "best_historical")

        # Verify persisted in SQLite SystemConfig
        cfg = self.db.query(SystemConfig).filter(SystemConfig.key == SYSTEM_CONFIG_KEY).first()
        self.assertIsNotNone(cfg, "SystemConfig should contain recent_bgm_tracks")
        persisted_data = json.loads(cfg.value)
        self.assertIn("best_historical", persisted_data)

        # Create fresh selector instance (simulating a separate execution / GitHub Actions run)
        selector_2 = BGMSelector()
        recent_usage = selector_2.get_recent_usage()
        self.assertIn("best_historical", recent_usage, "New selector instance should load persisted history")
        self.assertEqual(recent_usage[-1], "best_historical")

    def test_anti_monotony_rotation_penalty(self):
        """A compatible alternative track can beat a recently used track when otherwise comparable."""
        selector = BGMSelector()
        # Story with dual compatibility (History + High Tension/Action)
        cat = "Unusual Wars"
        title = "The Ambush at Blackwood Ridge"
        script = "Soldiers launched an ambush in a deadly confrontation during the military campaign."

        # Run 1: with no recent usage, best_historical wins
        track_1 = selector.select_track(category=cat, title=title, script_text=script)
        self.assertEqual(track_1, "best_historical")

        # Run 2: best_historical was just used (recency index 0); suspense_climax should now beat it
        track_2 = selector.select_track(category=cat, title=title, script_text=script)
        self.assertEqual(track_2, "suspense_climax", f"Expected suspense_climax to rotate in due to penalty, got {track_2}")

    def test_loudness_and_mixing_invariants_preserved(self):
        """Existing BGM loudness targets (-30 LUFS bed, -14 LUFS master, -13 dB mix) remain unchanged."""
        self.assertEqual(TARGET_BGM_LUFS, -30.0)
        self.assertEqual(TARGET_LUFS, -14.0)
        self.assertEqual(BGM_MIX_VOLUME_DB, -13.0)


if __name__ == "__main__":
    unittest.main()
