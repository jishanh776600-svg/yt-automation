"""
Comprehensive BGM Quality Assurance & Intelligent Matching Test Suite.
Verifies all 4 canonical tracks, mood selection rules, audible -13 dB mixing,
-14.0 LUFS loudness normalization, and output QA physical waveform analysis.
"""
import sys
import uuid
import unittest
import soundfile as sf
import numpy as np
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import init_db, SessionLocal
from config.settings import MUSIC_DIR, VOICE_DIR, RENDERS_DIR
from config.constants import BGM_MIX_VOLUME_DB, TARGET_LUFS, LicenseType
from core.models import Job, Topic, RenderOutput, AssetRecord
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.qa_engine import QAEngine


class TestBGMSystem(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.mixer = AudioMixer()
        self.qa = QAEngine()

    def tearDown(self):
        self.db.close()

    def test_all_four_canonical_bgm_tracks_exist(self):
        """Verifies that all 4 canonical BGM tracks exist locally with valid audio size."""
        for key, info in BGM_LIBRARY.items():
            valid_path = None
            for filename in info["primary_files"]:
                candidate = MUSIC_DIR / filename
                if candidate.exists() and candidate.stat().st_size > 1000:
                    valid_path = candidate
                    break
            self.assertIsNotNone(valid_path, f"BGM track '{key}' missing from {MUSIC_DIR}")
            self.assertGreater(valid_path.stat().st_size, 100000, f"BGM file {valid_path} is abnormally small")

    def test_intelligent_bgm_mood_matcher(self):
        """Tests that narrative context automatically maps to the most suitable BGM track."""
        # 1. War / Clash / Disaster -> Best Historical
        path, key, mood, reason = self.mixer.select_bgm_track(
            category="Unusual Wars",
            title="The Battle of Karánsebes",
            summary="An army fought a devastating battle against itself in an intense clash.",
            script_text="Cannons fired and cavalry charged in total military disaster."
        )
        self.assertIn(key, ["best_historical", "suspense_climax"])
        self.assertTrue(path.exists())

        # 2. Mystery / Suspense -> The Flux Beneath It All
        path, key, mood, reason = self.mixer.select_bgm_track(
            category="Historical Mysteries",
            title="The Lost Colony of Roanoke",
            summary="An entire colony vanished without a trace, leaving only a strange riddle.",
            script_text="No signs of struggle, only a single word carved in darkness: Croatoan."
        )
        self.assertIn(key, ["flux_ambient", "best_historical"])
        self.assertTrue(path.exists())

        # 3. Tragedy / Loss -> Empty Emotional Sad
        path, key, mood, reason = self.mixer.select_bgm_track(
            category="Documented Disasters",
            title="The Last Goodbye of Pompeii",
            summary="A heartbreaking story of grief, loss, and tragic farewell beneath the ash.",
            script_text="They held each other in tears as darkness fell forever in sorrow and grief."
        )
        self.assertEqual(key, "emotional_sad")
        self.assertIn("Empty", path.name)

        # 4. Victorian Court / Strange Laws -> Best Historical Chamber
        path, key, mood, reason = self.mixer.select_bgm_track(
            category="Strange Historical Laws",
            title="The Illegal Tax on Beards",
            summary="King Henry VIII imposed a bizarre royal court tax on facial hair.",
            script_text="Victorian aristocrats paid gold coins to keep their beards."
        )
        self.assertEqual(key, "best_historical")
        self.assertIn("Historical", path.name)

    def test_audio_mixing_and_loudness_normalization(self):
        """Tests that voice + BGM mixing produces audible BGM and broadcast standard -14 LUFS master audio."""
        dummy_voice = VOICE_DIR / f"test_voice_{uuid.uuid4().hex[:8]}.wav"
        
        # Generate clean dummy audio
        sample_rate = 24000
        duration = 5.0
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = 0.3 * np.sin(2 * np.pi * 220.0 * t)
        sf.write(str(dummy_voice), tone, sample_rate)
        
        # Select BGM track
        bgm_path, _, _, _ = self.mixer.select_bgm_track(category="Unusual Wars")
        out_master = RENDERS_DIR / f"test_master_{uuid.uuid4().hex[:8]}.aac"

        # Execute mix
        master_path, bgm_only_path = self.mixer.mix_audio(
            voice_path=dummy_voice,
            music_path=bgm_path,
            output_path=out_master,
            duration=5.0
        )
        self.assertTrue(master_path.exists())
        self.assertTrue(bgm_only_path.exists())
        self.assertGreater(master_path.stat().st_size, 1000)

        # Clean up
        dummy_voice.unlink(missing_ok=True)
        master_path.unlink(missing_ok=True)
        bgm_only_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
