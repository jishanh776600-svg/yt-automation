"""
Unit & Integration Tests for Phase 6 VideoQAEngine.
===================================================
Verifies MP4 container inspection, 9:16 aspect ratio validation, duration tolerance,
AV sync alignment, black frame detection, and policy compliance.
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from config.settings import FFMPEG_EXE
from intelligence.asset_manifest import ProductionAssetManifest
from intelligence.video_qa import VideoQAEngine, VideoQAReport


@pytest.fixture
def qa_engine():
    return VideoQAEngine()


@pytest.fixture
def dummy_video_file(tmp_path):
    p = tmp_path / "test_video.mp4"
    p.write_bytes(b"Simulated MP4 container bytes for unit inspection" * 100)
    return p


def test_inspect_media_parsing(qa_engine, dummy_video_file):
    """Verifies regex extraction of resolution, codecs, and duration from FFmpeg stderr."""
    sample_ffmpeg_output = """
    Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'dummy.mp4':
      Duration: 00:00:24.50, start: 0.000000, bitrate: 4500 kb/s
      Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1080x1920 [SAR 1:1 DAR 9:16], 4300 kb/s, 30 fps
      Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo, fltp, 192 kb/s
    """
    mock_res = MagicMock()
    mock_res.stderr = sample_ffmpeg_output.encode("utf-8")

    with patch("subprocess.run", return_value=mock_res):
        info = qa_engine.inspect_media(dummy_video_file)

    assert info["width"] == 1080
    assert info["height"] == 1920
    assert abs(info["duration"] - 24.50) < 0.01
    assert info["video_codec"] == "h264"
    assert info["audio_codec"] == "aac"
    assert info["audio_channels"] == 2
    assert info["audio_sample_rate"] == 44100


def test_aspect_ratio_9_16_validation(qa_engine, dummy_video_file):
    """Ensures non-vertical resolutions (16:9, 1:1) fail the aspect ratio check."""
    # 1. Valid 1080x1920
    with patch.object(qa_engine, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 25.0, "audio_duration": 25.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100,
    }), patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is True
        assert rep.checks["aspect_ratio_9_16"] is True

    # 2. Invalid landscape 1920x1080
    with patch.object(qa_engine, "inspect_media", return_value={
        "width": 1920, "height": 1080, "duration": 25.0, "audio_duration": 25.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100,
    }), patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is False
        assert rep.checks["aspect_ratio_9_16"] is False
        assert any("does not match required vertical 9:16" in r for r in rep.failure_reasons)


def test_duration_tolerance_validation(qa_engine, dummy_video_file):
    """Verifies duration tolerance +/-0.5s against target."""
    base_info = {
        "width": 1080, "height": 1920, "duration": 25.4, "audio_duration": 25.4,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100,
    }

    # Within tolerance (+0.4s) -> Pass
    with patch.object(qa_engine, "inspect_media", return_value=base_info), \
         patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is True
        assert rep.checks["duration_in_tolerance"] is True

    # Out of tolerance (+0.8s) -> Fail
    base_info["duration"] = 25.8
    base_info["audio_duration"] = 25.8
    with patch.object(qa_engine, "inspect_media", return_value=base_info), \
         patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is False
        assert rep.checks["duration_in_tolerance"] is False
        assert any("deviates from target" in r for r in rep.failure_reasons)


def test_av_sync_tolerance(qa_engine, dummy_video_file):
    """Verifies AV sync drift exceeding 0.5s is flagged."""
    # Video duration 25.0s, Audio duration 24.2s (delta 0.8s > 0.5s limit)
    drift_info = {
        "width": 1080, "height": 1920, "duration": 25.0, "audio_duration": 24.2,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100,
    }
    with patch.object(qa_engine, "inspect_media", return_value=drift_info), \
         patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is False
        assert rep.checks["av_sync_in_tolerance"] is False
        assert any("sync delta" in r for r in rep.failure_reasons)


def test_black_frame_anomaly_detection(qa_engine, dummy_video_file):
    """Flags video if continuous black frames >= 0.5s are found."""
    valid_media = {
        "width": 1080, "height": 1920, "duration": 25.0, "audio_duration": 25.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100,
    }
    # Black frames detected: 1.2s duration
    with patch.object(qa_engine, "inspect_media", return_value=valid_media), \
         patch.object(qa_engine, "detect_black_frames", return_value=(True, 1.2, [{"start": 2.0, "end": 3.2, "duration": 1.2}])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is False
        assert rep.checks["no_black_screen"] is False
        assert any("Continuous black frames detected" in r for r in rep.failure_reasons)


def test_missing_stream_failure(qa_engine, dummy_video_file):
    """Fails when either video or audio stream is absent."""
    no_audio = {
        "width": 1080, "height": 1920, "duration": 25.0, "audio_duration": 0.0,
        "has_video": True, "has_audio": False, "video_codec": "h264", "audio_codec": "",
        "audio_channels": 0, "audio_sample_rate": 0,
    }
    with patch.object(qa_engine, "inspect_media", return_value=no_audio), \
         patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        rep = qa_engine.verify_video(dummy_video_file, expected_duration=25.0)
        assert rep.passed is False
        assert rep.checks["has_audio_stream"] is False


def test_real_ffmpeg_video_verification(qa_engine, tmp_path):
    """Renders a real 2-second test MP4 via FFmpeg and confirms VideoQAEngine inspects it."""
    real_mp4 = tmp_path / "real_test.mp4"

    cmd = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "color=c=#335588:s=1080x1920:d=2.0:r=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.0",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        str(real_mp4)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        pytest.skip(f"FFmpeg not available in environment: {res.stderr}")

    rep = qa_engine.verify_video(real_mp4, expected_duration=2.0)
    assert rep.passed is True
    assert rep.width == 1080
    assert rep.height == 1920
    assert rep.aspect_ratio == "9:16"
    assert rep.video_codec == "h264"
    assert rep.audio_codec == "aac"
    assert rep.checks["container_valid"] is True
    assert rep.checks["no_black_screen"] is True
