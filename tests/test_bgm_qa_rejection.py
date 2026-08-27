"""
Unit Test: BGM QA Identity Verification & False Positive Rejection Test.
Tests that QA strictly FAILS on wrong/noise audio and strictly PASSES on the genuine selected BGM.
"""
import unittest
import os
import subprocess
from pathlib import Path
from config.settings import FFMPEG_EXE, RENDERS_DIR
from engines.qa_engine import QAEngine


class TestBGMQAVerification(unittest.TestCase):

    def setUp(self):
        self.qa = QAEngine()
        self.voice_path = Path(r"C:\Users\jisha\OneDrive\Desktop\yt automation\data\voice\aud_38804dc2022b.wav")
        self.correct_bgm = Path(r"C:\Users\jisha\OneDrive\Desktop\yt automation\assets\music\No copyright Best Historical.wav")
        self.wrong_bgm = Path(r"C:\Users\jisha\OneDrive\Desktop\yt automation\assets\music\Empty - Emotional Sad Background.wav")
        
        self.test_mp4_correct = RENDERS_DIR / "test_qa_correct.mp4"
        self.test_mp4_noise = RENDERS_DIR / "test_qa_noise.mp4"
        self.test_mp4_wrong_bgm = RENDERS_DIR / "test_qa_wrong_bgm.mp4"
        self.stage_b_ref = RENDERS_DIR / "test_qa_stage_b_ref.wav"

        # 1. Generate Stage B Reference (Best Historical)
        cmd_b = [
            FFMPEG_EXE, "-y",
            "-i", str(self.correct_bgm),
            "-af", "aloop=loop=-1:size=2e+09,atrim=0:21.5,volume=0.22,afade=t=in:ss=0:d=0.8,afade=t=out:st=20.0:d=1.5",
            "-ar", "44100", "-ac", "2",
            str(self.stage_b_ref)
        ]
        subprocess.run(cmd_b, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 2. Build MP4 with Correct BGM
        cmd_mp4_correct = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=21.5:r=30",
            "-i", str(self.voice_path),
            "-i", str(self.stage_b_ref),
            "-filter_complex", "[1:a]aresample=44100,aformat=channel_layouts=stereo[v];[2:a]aformat=channel_layouts=stereo[m];[v][m]amix=inputs=2:duration=first:normalize=0[outa]",
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac",
            str(self.test_mp4_correct)
        ]
        subprocess.run(cmd_mp4_correct, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 3. Build MP4 with Synthetic Noise / Sine Tone (Simulating AI Noise bug)
        cmd_mp4_noise = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=21.5:r=30",
            "-i", str(self.voice_path),
            "-f", "lavfi", "-i", "sine=frequency=440:duration=21.5",
            "-filter_complex", "[1:a]aresample=44100,aformat=channel_layouts=stereo[v];[2:a]volume=0.22,aformat=channel_layouts=stereo[m];[v][m]amix=inputs=2:duration=first:normalize=0[outa]",
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac",
            str(self.test_mp4_noise)
        ]
        subprocess.run(cmd_mp4_noise, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 4. Build MP4 with Wrong BGM track
        cmd_mp4_wrong = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=21.5:r=30",
            "-i", str(self.voice_path),
            "-i", str(self.wrong_bgm),
            "-filter_complex", "[1:a]aresample=44100,aformat=channel_layouts=stereo[v];[2:a]aloop=loop=-1:size=2e+09,atrim=0:21.5,volume=0.22,aformat=channel_layouts=stereo[m];[v][m]amix=inputs=2:duration=first:normalize=0[outa]",
            "-map", "0:v", "-map", "[outa]",
            "-c:v", "libx264", "-c:a", "aac",
            str(self.test_mp4_wrong_bgm)
        ]
        subprocess.run(cmd_mp4_wrong, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def tearDown(self):
        for p in [self.test_mp4_correct, self.test_mp4_noise, self.test_mp4_wrong_bgm, self.stage_b_ref]:
            p.unlink(missing_ok=True)

    def test_correct_bgm_passes_qa(self):
        """Verify that genuine selected BGM receives score >= 0.65 and passes QA."""
        analysis = self.qa.analyze_audio_stream(self.test_mp4_correct, bgm_reference_path=self.stage_b_ref)
        self.assertTrue(analysis["bgm_identity_verified"], f"Expected PASS but got score {analysis['bgm_fingerprint_score']}")
        self.assertGreaterEqual(analysis["bgm_fingerprint_score"], 0.65)
        print(f"PASS TEST: Correct BGM Score = {analysis['bgm_fingerprint_score']:.4f} (VERIFIED)")

    def test_noise_audio_fails_qa(self):
        """Verify that synthetic AI noise receives score < 0.65 and FAILS QA."""
        analysis = self.qa.analyze_audio_stream(self.test_mp4_noise, bgm_reference_path=self.stage_b_ref)
        self.assertFalse(analysis["bgm_identity_verified"], f"Expected FAIL but got score {analysis['bgm_fingerprint_score']}")
        self.assertLess(analysis["bgm_fingerprint_score"], 0.65)
        print(f"FAIL TEST: Noise Audio Score = {analysis['bgm_fingerprint_score']:.4f} (REJECTED)")

    def test_wrong_bgm_track_fails_qa(self):
        """Verify that a different BGM track receives score < 0.65 and FAILS QA."""
        analysis = self.qa.analyze_audio_stream(self.test_mp4_wrong_bgm, bgm_reference_path=self.stage_b_ref)
        self.assertFalse(analysis["bgm_identity_verified"], f"Expected FAIL but got score {analysis['bgm_fingerprint_score']}")
        self.assertLess(analysis["bgm_fingerprint_score"], 0.65)
        print(f"FAIL TEST: Wrong BGM Score = {analysis['bgm_fingerprint_score']:.4f} (REJECTED)")


if __name__ == "__main__":
    unittest.main()
