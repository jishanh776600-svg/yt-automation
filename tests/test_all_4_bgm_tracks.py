"""
Test Suite: Controlled Verification of All 4 Approved BGM Tracks.
Tests that EACH of the 4 approved tracks:
1. Is discovered in assets/music/
2. Is decodable by FFmpeg
3. Can be selected by the intelligent mood classifier
4. Can be mixed in Stage B & Stage C
5. Can be rendered into a 1080x1920 MP4
6. Passes the FFT Cross-Correlation BGM Identity QA audit.
"""
import unittest
import os
import subprocess
from pathlib import Path

from config.settings import FFMPEG_EXE, MUSIC_DIR, RENDERS_DIR
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.qa_engine import QAEngine


class TestAllFourBGMTracks(unittest.TestCase):

    def setUp(self):
        self.mixer = AudioMixer()
        self.qa = QAEngine()
        self.voice_path = Path(__file__).resolve().parent.parent / "data" / "voice" / "aud_38804dc2022b.wav"
        self.test_renders = []

    def tearDown(self):
        for p in self.test_renders:
            p.unlink(missing_ok=True)

    def _test_single_track(self, track_key: str, topic_title: str, category: str, script_text: str):
        # 1. Selection & Discovery
        track_path, selected_key, mood, reason = self.mixer.select_bgm_track(
            category=category,
            title=topic_title,
            script_text=script_text
        )
        self.assertEqual(selected_key, track_key, f"Expected {track_key} but got {selected_key}")
        self.assertTrue(track_path.exists(), f"Track path {track_path} does not exist")
        self.assertGreater(track_path.stat().st_size, 50000, f"Track {track_path} is abnormally small")

        # 2. 3-Stage Mix
        job_id = f"test_bgm_{track_key}"
        master_audio = RENDERS_DIR / f"test_master_{track_key}.aac"
        self.test_renders.append(master_audio)

        master_path, bgm_only_path = self.mixer.mix_audio(
            voice_path=self.voice_path,
            music_path=track_path,
            output_path=master_audio,
            duration=21.5,
            job_id=job_id
        )
        self.test_renders.append(bgm_only_path)
        self.assertTrue(master_path.exists())
        self.assertTrue(bgm_only_path.exists())

        # 3. Render 1080x1920 MP4
        test_mp4 = RENDERS_DIR / f"test_render_{track_key}.mp4"
        self.test_renders.append(test_mp4)

        cmd_mp4 = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=21.5:r=30",
            "-i", str(master_path),
            "-c:v", "libx264", "-c:a", "aac",
            str(test_mp4)
        ]
        subprocess.run(cmd_mp4, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertTrue(test_mp4.exists())

        # 4. QA & FFT BGM Identity Verification
        analysis = self.qa.analyze_audio_stream(test_mp4, bgm_reference_path=bgm_only_path)
        self.assertTrue(
            analysis["bgm_identity_verified"],
            f"Track {track_key} failed BGM Identity Verification (Score: {analysis['bgm_fingerprint_score']:.4f})"
        )
        self.assertTrue(analysis["bgm_audible"], f"Track {track_key} failed audibility check")
        print(f"Track '{BGM_LIBRARY[track_key]['display_name']}': Score={analysis['bgm_fingerprint_score']:.4f} | Loudness={analysis['integrated_lufs']:.1f} LUFS -> PASS")

    def test_track_1_best_historical(self):
        """Test Track 1: No copyright Best Historical..."""
        self._test_single_track(
            track_key="best_historical",
            topic_title="The War of the Oaken Bucket (1325)",
            category="Unusual Wars",
            script_text="In 1325, two Italian city-states went to war over a wooden bucket taken from a well, resulting in thousands of casualties."
        )

    def test_track_2_emotional_sad(self):
        """Test Track 2: Empty - Emotional Sad Background..."""
        self._test_single_track(
            track_key="emotional_sad",
            topic_title="The Tragic Fate of the Pompeii Lovers",
            category="Documented Disasters",
            script_text="Two souls embraced in their final moments as volcanic ash consumed the city, a heartbreaking eternal symbol of grief and sorrow."
        )

    def test_track_3_flux_ambient(self):
        """Test Track 3: The Flux Beneath It All.mp3"""
        self._test_single_track(
            track_key="flux_ambient",
            topic_title="The Unsolved Mystery of the Voynich Manuscript",
            category="Historical Mysteries",
            script_text="Written in an unknown script with strange botanical illustrations, this cryptic centuries-old cipher remains an unsolved enigma."
        )

    def test_track_4_suspense_climax(self):
        """Test Track 4: No Copyright Background Music"""
        self._test_single_track(
            track_key="suspense_climax",
            topic_title="The Great Train Robbery Escape of 1963",
            category="Dramatic Escapes",
            script_text="In a daring race against time, masked bandits pulled off the heist of the century and fled into the night with millions."
        )


if __name__ == "__main__":
    unittest.main()
