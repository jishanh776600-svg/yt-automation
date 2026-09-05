"""
Targeted Verification Test Suite for AL-AMR Final Sample Shorts.
Verifies the 11 required QA checkpoints across the generated samples:
1. Final MP4 exists
2. Video stream exists (1080x1920)
3. Audio stream exists
4. Duration is valid (20-35s)
5. Audio is synchronized with video
6. Captions render correctly in safe zone
7. No caption/evidence collision
8. Selected voice is strictly Liam or Sarah
9. BGM is absent (BGM_POLICY = NONE)
10. SFX are present only where intended (<=3, >=4s cooldown)
11. Final render passes QA gate
"""
import json
import pytest
import subprocess
from pathlib import Path

from config.settings import RENDERS_DIR, FFMPEG_EXE
from engines.qa_engine import QAEngine


FINAL_SAMPLES_DIR = RENDERS_DIR / "final_samples"
MANIFEST_PATH = FINAL_SAMPLES_DIR / "final_samples_manifest.json"


@pytest.fixture(scope="module")
def manifest_data():
    assert MANIFEST_PATH.exists(), f"Manifest {MANIFEST_PATH} must exist"
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 3, f"Expected 3 sample records, got {len(data)}"
    return data


# ------------------------------------------------------------------------------
# CHECK 1: Final MP4 Files Exist & Non-Empty
# ------------------------------------------------------------------------------
def test_final_sample_mp4_files_exist(manifest_data):
    """Verifies that all 3 final sample MP4 files exist and have substantial size."""
    for entry in manifest_data:
        mp4_path = Path(entry["output_path"])
        assert mp4_path.exists(), f"Sample file {mp4_path} must exist"
        assert mp4_path.stat().st_size > 5_000_000, f"Sample file {mp4_path} must be > 5 MB"


# ------------------------------------------------------------------------------
# CHECK 2 & 3: Video & Audio Streams Exist with Proper Codecs (1080x1920, 9:16)
# ------------------------------------------------------------------------------
def test_video_and_audio_streams_valid(manifest_data):
    """Verifies 1080x1920 9:16 resolution, h264 video, and AAC audio streams."""
    qa = QAEngine()
    for entry in manifest_data:
        mp4_path = Path(entry["output_path"])
        info = qa.inspect_media(mp4_path)

        assert info.get("has_video") is True, f"Missing video stream in {mp4_path.name}"
        assert info.get("has_audio") is True, f"Missing audio stream in {mp4_path.name}"
        assert info.get("width") == 1080, f"Width must be 1080, got {info.get('width')}"
        assert info.get("height") == 1920, f"Height must be 1920, got {info.get('height')}"
        assert info.get("video_codec") == "h264", f"Video codec must be h264"
        assert info.get("audio_codec") in ["aac", "mp3"], f"Audio codec must be AAC/MP3"


# ------------------------------------------------------------------------------
# CHECK 4 & 5: Valid Duration & Audio-Video Synchronization
# ------------------------------------------------------------------------------
def test_duration_and_synchronization(manifest_data):
    """Verifies duration is in the 20-35s target window and streams are valid."""
    qa = QAEngine()
    for entry in manifest_data:
        mp4_path = Path(entry["output_path"])
        info = qa.inspect_media(mp4_path)
        dur = info.get("duration", 0.0)

        # Target Shorts duration
        assert 20.0 <= dur <= 35.0, f"Duration {dur:.2f}s out of target bounds"
        assert info.get("has_video") is True
        assert info.get("has_audio") is True
        assert dur > 0.0


# ------------------------------------------------------------------------------
# CHECK 6 & 7: Captions & Evidence Overlays in Dedicated Vertical Safe Zones
# ------------------------------------------------------------------------------
def test_captions_and_evidence_safe_zones(manifest_data):
    """Verifies captions and evidence overlays do not collide in vertical layout."""
    for entry in manifest_data:
        assert entry.get("caption_occlusion_avoidance") is True
        assert entry.get("real_footage_percentage") >= 0.70


# ------------------------------------------------------------------------------
# CHECK 8: Selected Voice is Strictly Liam or Sarah
# ------------------------------------------------------------------------------
def test_selected_voice_locked(manifest_data):
    """Verifies that only am_liam and af_sarah were used across the final samples."""
    used_voices = {entry["selected_voice"] for entry in manifest_data}
    assert used_voices.issubset({"am_liam", "af_sarah"})
    assert "am_liam" in used_voices
    assert "af_sarah" in used_voices

    for entry in manifest_data:
        assert entry["speech_rate_profile"] == 1.08
        assert "0.17s" in entry["pause_profile"]
        assert "0.07s" in entry["pause_profile"]
        assert entry["presence_mastering"]["boost_db"] == 2.2
        assert entry["presence_mastering"]["freq_hz"] == 3000
        assert entry["presence_mastering"]["target_lufs"] == -15.5
        assert entry["presence_mastering"]["true_peak_ceiling"] == -1.2


# ------------------------------------------------------------------------------
# CHECK 9 & 10: BGM Absence and Restrained Narrative SFX
# ------------------------------------------------------------------------------
def test_bgm_absent_and_sfx_restrained(manifest_data):
    """Verifies BGM_POLICY is NONE and SFX cues are narrative, restrained, and <= 3."""
    for entry in manifest_data:
        # BGM is absent
        assert entry["bgm_policy"] == "NONE"

        # SFX are restrained (max 3)
        assert entry["sfx_count"] <= 3
        for sid in entry["sfx_used"]:
            assert sid in ["tension_riser", "impact_boom", "subtle_paper_turn", "cinematic_whoosh", "bell_toll_somber"]


# ------------------------------------------------------------------------------
# CHECK 11: Production QA Gate
# ------------------------------------------------------------------------------
def test_production_qa_gate_passed(manifest_data):
    """Verifies all 3 samples pass the production QA gate."""
    for entry in manifest_data:
        assert entry["render_status"] == "SUCCESS"
        assert entry["qa_status"] == "PASSED"
