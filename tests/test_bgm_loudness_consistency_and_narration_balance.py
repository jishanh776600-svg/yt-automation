"""
Targeted Test Suite: BGM Loudness Consistency & Narration Dominance.
Verifies:
A. Normal-loudness BGM balance
B. Unusually loud BGM source handling
C. Unusually quiet BGM source handling
D. Multiple different BGM tracks producing consistent relative balance
E. Final master LUFS and peak requirements
F. Narration remaining dominant over BGM
"""
import re
import pytest
import subprocess
import numpy as np
import soundfile as sf
from pathlib import Path

from config.settings import FFMPEG_EXE, MUSIC_DIR, RENDERS_DIR
from config.constants import (
    AUDIO_SAMPLE_RATE, TARGET_LUFS, TARGET_BGM_LUFS,
    MIN_AUDIO_LOUDNESS_LUFS, MAX_AUDIO_LOUDNESS_LUFS, MAX_TRUE_PEAK_DBTP
)
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.qa_engine import QAEngine


@pytest.fixture(scope="module")
def audio_fixtures(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("bgm_loudness_test")
    sample_rate = 44100
    duration = 21.5
    t = np.linspace(0, duration, int(sample_rate * duration), False)

    # 1. Standard Voice Track (~ -18.2 LUFS)
    voice_sig = 0.25 * np.sin(2 * np.pi * 220.0 * t) + 0.12 * np.sin(2 * np.pi * 440.0 * t) + 0.06 * np.sin(2 * np.pi * 880.0 * t)
    voice_path = tmp_dir / "test_voice.wav"
    sf.write(str(voice_path), voice_sig, sample_rate)

    # 2. Unusually Loud BGM Source (~ -6.0 LUFS)
    loud_bgm_sig = 0.92 * (np.sin(2 * np.pi * 320.0 * t) + np.sin(2 * np.pi * 640.0 * t)) / 2.0
    loud_bgm_path = tmp_dir / "unusually_loud_bgm.wav"
    sf.write(str(loud_bgm_path), loud_bgm_sig, sample_rate)

    # 3. Unusually Quiet BGM Source (~ -36.0 LUFS)
    quiet_bgm_sig = 0.008 * np.sin(2 * np.pi * 320.0 * t)
    quiet_bgm_path = tmp_dir / "unusually_quiet_bgm.wav"
    sf.write(str(quiet_bgm_path), quiet_bgm_sig, sample_rate)

    mixer = AudioMixer()
    qa = QAEngine()

    return {
        "tmp_dir": tmp_dir,
        "sample_rate": sample_rate,
        "duration": duration,
        "voice_path": voice_path,
        "loud_bgm_path": loud_bgm_path,
        "quiet_bgm_path": quiet_bgm_path,
        "mixer": mixer,
        "qa": qa
    }


class TestBGMLoudnessConsistencyAndNarrationBalance:

    def _render_and_analyze(self, fixtures, music_path, tag):
        tmp_dir = fixtures["tmp_dir"]
        duration = fixtures["duration"]
        master_out = tmp_dir / f"master_{tag}.aac"
        test_mp4 = tmp_dir / f"test_{tag}.mp4"

        master_path, bgm_only_path = fixtures["mixer"].mix_audio(
            voice_path=fixtures["voice_path"],
            music_path=music_path,
            output_path=master_out,
            duration=duration,
            job_id=tag
        )

        cmd_mp4 = [
            FFMPEG_EXE, "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=1080x1920:d={duration}:r=30",
            "-i", str(master_path),
            "-c:v", "libx264", "-c:a", "aac",
            str(test_mp4)
        ]
        subprocess.run(cmd_mp4, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        analysis = fixtures["qa"].analyze_audio_stream(test_mp4, bgm_reference_path=bgm_only_path)
        return analysis, bgm_only_path, master_path

    def test_01_normal_loudness_bgm_balance(self, audio_fixtures):
        """A. Normal-loudness BGM: Verify standard BGM sits cleanly in background."""
        normal_bgm = MUSIC_DIR / "No copyright Best Historical.wav"
        if not normal_bgm.exists():
            normal_bgm = MUSIC_DIR / "No copyright Best Historical.mp3"

        analysis, stage_b, master = self._render_and_analyze(audio_fixtures, normal_bgm, "normal_bgm")

        assert analysis["integrated_lufs"] >= MIN_AUDIO_LOUDNESS_LUFS
        assert analysis["integrated_lufs"] <= MAX_AUDIO_LOUDNESS_LUFS
        assert abs(analysis["integrated_lufs"] - TARGET_LUFS) <= 1.5
        assert analysis["max_volume_db"] <= 0.0
        assert analysis["bgm_identity_verified"] is True
        assert analysis["bgm_audible"] is True

    def test_02_unusually_loud_bgm_source_contained(self, audio_fixtures):
        """B. Unusually loud BGM source: Verify heavily amplified source cannot overpower voice."""
        loud_bgm = audio_fixtures["loud_bgm_path"]
        analysis, stage_b, master = self._render_and_analyze(audio_fixtures, loud_bgm, "loud_bgm")

        assert abs(analysis["integrated_lufs"] - TARGET_LUFS) <= 1.5
        assert analysis["max_volume_db"] <= 0.0
        assert analysis["bgm_identity_verified"] is True

        cmd_stage_b_lufs = [FFMPEG_EXE, "-i", str(stage_b), "-af", "ebur128=peak=true", "-f", "null", "-"]
        res = subprocess.run(cmd_stage_b_lufs, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        output = res.stderr.decode("utf-8", errors="ignore")
        
        i_matches = re.findall(r"I:\s*(-?[\d\.]+)\s*LUFS", output)
        if i_matches:
            stage_b_lufs = float(i_matches[-1])
            assert stage_b_lufs <= -27.0, f"Stage B BGM bed {stage_b_lufs} LUFS is too loud!"

    def test_03_unusually_quiet_bgm_source_standardized(self, audio_fixtures):
        """C. Unusually quiet BGM source: Verify quiet source is standardized to audible bed."""
        quiet_bgm = audio_fixtures["quiet_bgm_path"]
        analysis, stage_b, master = self._render_and_analyze(audio_fixtures, quiet_bgm, "quiet_bgm")

        assert abs(analysis["integrated_lufs"] - TARGET_LUFS) <= 1.5
        assert analysis["bgm_identity_verified"] is True
        assert analysis["bgm_audible"] is True

    def test_04_multiple_different_bgm_tracks_consistent_relative_balance(self, audio_fixtures):
        """D. Multiple different BGM tracks: Verify all 4 core tracks produce uniform master loudness."""
        results = {}
        for key, info in BGM_LIBRARY.items():
            for fname in info["primary_files"]:
                cand = MUSIC_DIR / fname
                if cand.exists():
                    analysis, stage_b, master = self._render_and_analyze(audio_fixtures, cand, f"lib_{key}")
                    results[key] = analysis
                    break

        assert len(results) == 4, f"Expected 4 library tracks tested, got {len(results)}"
        lufs_values = [r["integrated_lufs"] for r in results.values()]
        
        max_diff = max(lufs_values) - min(lufs_values)
        assert max_diff <= 0.5, f"BGM tracks produced inconsistent master loudness variance: {max_diff} LUFS ({lufs_values})"

    def test_05_final_master_lufs_and_peak_requirements(self, audio_fixtures):
        """E. Final master LUFS & peak: Master must satisfy -14.0 LUFS and peak <= 0.0 dBTP."""
        sample_bgm = MUSIC_DIR / "The Flux Beneath It All.wav"
        if not sample_bgm.exists():
            sample_bgm = MUSIC_DIR / "The Flux Beneath It All.mp3"

        analysis, stage_b, master = self._render_and_analyze(audio_fixtures, sample_bgm, "master_specs")
        assert analysis["integrated_lufs"] >= MIN_AUDIO_LOUDNESS_LUFS
        assert analysis["integrated_lufs"] <= MAX_AUDIO_LOUDNESS_LUFS
        assert analysis["max_volume_db"] <= 0.0
        assert analysis["has_clipping"] is False

    def test_06_narration_dominance_over_bgm(self, audio_fixtures):
        """F. Narration dominance: Verify voice narration energy dominates BGM bed across all tracks."""
        for key in ["best_historical", "suspense_climax"]:
            info = BGM_LIBRARY[key]
            bgm_path = None
            for fname in info["primary_files"]:
                cand = MUSIC_DIR / fname
                if cand.exists():
                    bgm_path = cand
                    break
            assert bgm_path is not None

            analysis, stage_b, master = self._render_and_analyze(audio_fixtures, bgm_path, f"dom_{key}")

            voice_data, _ = sf.read(str(audio_fixtures["voice_path"]))
            bgm_data, _ = sf.read(str(stage_b))

            voice_rms = float(np.sqrt(np.mean(voice_data ** 2)))
            bgm_rms = float(np.sqrt(np.mean(bgm_data ** 2)))

            rms_ratio = voice_rms / (bgm_rms + 1e-9)
            assert rms_ratio >= 3.0, f"Voice to BGM RMS ratio {rms_ratio:.2f} is insufficient for track {key}!"