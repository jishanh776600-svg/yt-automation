"""
Test Suite: AL-AMR Hard Video-Only Visual Asset Policy (VIDEO_ONLY = True).
=============================================================================
Enforces and verifies the hard production invariant:
- VIDEO FOOTAGE ONLY.
- NO still images, photos, AI images, or Ken Burns still-frame fallbacks.
- Physical validation of containers, streams, codecs, and durations.
- Rejection of renamed image files and thumbnails.
- Rejection of image fallbacks across RealFootageEngine, AssetFetcher, StoryboardEngine, and RenderEngine.
- End-to-end valid video workflow preservation.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.settings import FFMPEG_EXE
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from core.models import AssetRecord
from engines.asset_fetcher import AssetFetcher
from engines.render_engine import RenderEngine
from engines.storyboard_engine import StoryboardEngine
from engines.visual_intelligence.real_footage_engine import (
    FootageCandidate,
    EventClaim,
    TemporalMomentRetriever,
    VisualClaimVerifier,
)


@pytest.fixture(scope="module")
def media_fixtures():
    """Generates small, deterministic test media files using FFmpeg and PIL."""
    td = tempfile.mkdtemp(prefix="video_policy_tests_")
    dir_path = Path(td)

    # 1. Valid MP4 (H.264 video stream, 2 seconds)
    mp4_path = dir_path / "valid_sample.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(mp4_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Valid WebM (VP8/VP9 video stream, 2 seconds)
    webm_path = dir_path / "valid_sample.webm"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-y", str(webm_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. JPEG image
    jpeg_path = dir_path / "sample.jpg"
    img = Image.new("RGB", (320, 240), color=(180, 50, 50))
    img.save(jpeg_path, "JPEG")

    # 4. PNG image
    png_path = dir_path / "sample.png"
    img.save(png_path, "PNG")

    # 5. WebP image
    webp_path = dir_path / "sample.webp"
    img.save(webp_path, "WEBP")

    # 6. GIF image
    gif_path = dir_path / "sample.gif"
    img.save(gif_path, "GIF")

    # 7. Renamed image (.jpg renamed to .mp4)
    renamed_mp4_path = dir_path / "fake_video_renamed.mp4"
    shutil.copyfile(jpeg_path, renamed_mp4_path)

    # 8. Audio-only container (no video stream)
    audio_only_path = dir_path / "audio_only.aac"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "sine=frequency=1000:duration=2",
        "-c:a", "aac", "-y", str(audio_only_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    yield {
        "mp4": mp4_path,
        "webm": webm_path,
        "jpeg": jpeg_path,
        "png": png_path,
        "webp": webp_path,
        "gif": gif_path,
        "renamed_mp4": renamed_mp4_path,
        "audio_only": audio_only_path,
    }

    shutil.rmtree(td, ignore_errors=True)


# ==============================================================================
# 1. MP4 video -> ACCEPT
# ==============================================================================
def test_01_mp4_video_accepted(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["mp4"])
    assert res.is_valid is True, f"Valid MP4 was rejected: {res.error_message}"
    assert res.duration >= 1.5
    assert res.width > 0 and res.height > 0
    assert res.codec in ["h264", "hevc", "mpeg4"]


# ==============================================================================
# 2. WebM video -> ACCEPT
# ==============================================================================
def test_02_webm_video_accepted(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["webm"])
    assert res.is_valid is True, f"Valid WebM was rejected: {res.error_message}"
    assert res.duration >= 1.5
    assert "vp" in res.codec or "webm" in res.format_name


# ==============================================================================
# 3. JPEG -> REJECT
# ==============================================================================
def test_03_jpeg_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["jpeg"])
    assert res.is_valid is False
    assert "image" in res.error_message.lower() or "prohibited" in res.error_message.lower()


# ==============================================================================
# 4. PNG -> REJECT
# ==============================================================================
def test_04_png_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["png"])
    assert res.is_valid is False
    assert "image" in res.error_message.lower() or "prohibited" in res.error_message.lower()


# ==============================================================================
# 5. WebP -> REJECT
# ==============================================================================
def test_05_webp_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["webp"])
    assert res.is_valid is False
    assert "image" in res.error_message.lower() or "prohibited" in res.error_message.lower()


# ==============================================================================
# 6. GIF -> REJECT
# ==============================================================================
def test_06_gif_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["gif"])
    assert res.is_valid is False
    assert "image" in res.error_message.lower() or "prohibited" in res.error_message.lower()


# ==============================================================================
# 7. Image URL -> REJECT
# ==============================================================================
def test_07_image_url_rejected():
    image_urls = [
        "https://images.pexels.com/photos/12345/pexels-photo-12345.jpeg?auto=compress",
        "https://upload.wikimedia.org/wikipedia/commons/3/3a/Ancient_Ruins.jpg",
        "https://cdn.example.com/assets/evidence_document.png",
        "https://image.pollinations.ai/prompt/historic_scene?width=1080&height=1920",
    ]
    for url in image_urls:
        assert PhysicalVideoValidator.is_image_url(url) is True, f"Failed to identify image URL: {url}"
        assert PhysicalVideoValidator.is_video_url(url) is False, f"Erroneously classified image URL as video: {url}"


# ==============================================================================
# 8. Thumbnail URL -> REJECT
# ==============================================================================
def test_08_thumbnail_url_rejected():
    thumbnail_urls = [
        "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a4/Ship.jpg/800px-Ship.jpg",
        "https://cdn.example.com/videos/previews/thumbnail_card.jpg",
    ]
    for url in thumbnail_urls:
        assert PhysicalVideoValidator.is_image_url(url) is True, f"Failed to reject thumbnail URL: {url}"
        assert PhysicalVideoValidator.is_video_url(url) is False


# ==============================================================================
# 9. Image renamed .mp4 -> REJECT
# ==============================================================================
def test_09_image_renamed_mp4_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["renamed_mp4"])
    assert res.is_valid is False, "Renamed JPEG masquerading as .mp4 was erroneously accepted!"
    assert "disguised" in res.error_message.lower() or "static image" in res.error_message.lower()


# ==============================================================================
# 10. Video with valid temporal stream -> ACCEPT
# ==============================================================================
def test_10_video_with_valid_temporal_stream_accepted(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["mp4"], min_duration=0.5)
    assert res.is_valid is True
    assert res.duration >= 1.5
    assert res.nb_frames > 1
    assert res.fps >= 20.0


# ==============================================================================
# 11. Candidate without video stream -> REJECT
# ==============================================================================
def test_11_candidate_without_video_stream_rejected(media_fixtures):
    res = PhysicalVideoValidator.validate_file(media_fixtures["audio_only"])
    assert res.is_valid is False, "Audio-only asset was erroneously accepted as video!"
    assert "no video stream" in res.error_message.lower() or "not video" in res.error_message.lower()


# ==============================================================================
# 12. Image-search fallback -> REJECT
# ==============================================================================
def test_12_image_search_fallback_rejected():
    fetcher = AssetFetcher()
    mock_db = MagicMock()
    # Invariant: search_pexels_photo must return None unconditionally
    result = fetcher.search_pexels_photo(mock_db, "ancient mystery ruins")
    assert result is None, "search_pexels_photo returned an asset under VIDEO_ONLY invariant!"

    # Invariant: generate_ai_image must return False unconditionally
    ai_result = fetcher.generate_ai_image("ancient document", Path("test.jpg"))
    assert ai_result is False, "generate_ai_image returned True under VIDEO_ONLY invariant!"


# ==============================================================================
# 13. Video-search failure does NOT invoke image fallback
# ==============================================================================
def test_13_video_search_failure_does_not_invoke_image_fallback():
    fetcher = AssetFetcher()
    mock_db = MagicMock()
    shot_data = {
        "shot_id": "shot_01",
        "search_query": "completely nonexistent query 99999",
        "visual_prompt": "Cinematic nonexistent event",
        "duration": 3.0
    }

    # Patch Pexels video search to return None (simulating complete video search failure)
    with patch.object(fetcher, "search_pexels_video", return_value=None):
        with patch.object(fetcher, "search_pexels_photo") as mock_photo:
            with patch.object(fetcher, "generate_ai_image") as mock_ai:
                # With cache empty, it must fail closed and NOT call photo or AI image
                with patch.object(Path, "glob", return_value=[]):
                    with pytest.raises(RuntimeError) as exc_info:
                        fetcher.fetch_asset_for_shot(mock_db, shot_data)

                    assert "VIDEO_ONLY" in str(exc_info.value) or "prohibited" in str(exc_info.value)
                    mock_photo.assert_not_called()
                    mock_ai.assert_not_called()


# ==============================================================================
# 14. TemporalMomentRetriever rejects non-video candidate
# ==============================================================================
def test_14_temporal_moment_retriever_rejects_non_video():
    retriever = TemporalMomentRetriever()

    # Candidate with media_type="image"
    image_cand = FootageCandidate(
        candidate_id="cand_img_01",
        title="Historical Photograph",
        source_platform="WikimediaCommons",
        source_url="https://commons.wikimedia.org/wiki/File:Photo.jpg",
        media_url_or_path="https://upload.wikimedia.org/Photo.jpg",
        duration_sec=3.0,
        media_type="image",
        is_video=False
    )
    with pytest.raises(ValueError) as exc_info:
        retriever.localize_moment(image_cand, target_duration=2.5)
    assert "rejected non-video" in str(exc_info.value).lower()

    # Candidate with image URL
    cand_img_url = FootageCandidate(
        candidate_id="cand_img_02",
        title="Fake Video pointing to JPG",
        source_platform="Pexels",
        source_url="https://pexels.com/photo/123",
        media_url_or_path="https://images.pexels.com/photos/123.jpg",
        duration_sec=3.0,
        media_type="video",
        is_video=True
    )
    with pytest.raises(ValueError) as exc_info2:
        retriever.localize_moment(cand_img_url, target_duration=2.5)
    assert "image url" in str(exc_info2.value).lower()


# ==============================================================================
# 15. Storyboard rejects image asset
# ==============================================================================
def test_15_storyboard_rejects_image_asset():
    # Scene specifying prohibited asset_type="image"
    invalid_scene_1 = {
        "shot_id": "shot_01",
        "asset_type": "image",
        "media_path": "assets/photo.jpg",
        "start_time": 0.0,
        "end_time": 3.0,
        "duration": 3.0
    }
    with pytest.raises(ValueError) as exc_1:
        StoryboardEngine.validate_storyboard_scene(invalid_scene_1)
    assert "prohibited asset_type" in str(exc_1.value).lower()

    # Scene referencing an image URL
    invalid_scene_2 = {
        "shot_id": "shot_02",
        "asset_type": "video",
        "media_url": "https://images.pexels.com/photos/999/scene.jpg",
        "start_time": 0.0,
        "end_time": 2.5,
        "duration": 2.5
    }
    with pytest.raises(ValueError) as exc_2:
        StoryboardEngine.validate_storyboard_scene(invalid_scene_2)
    assert "prohibited image" in str(exc_2.value).lower()


# ==============================================================================
# 16. FFmpeg composition refuses prohibited image evidence input
# ==============================================================================
def test_16_ffmpeg_composition_refuses_prohibited_image_input(media_fixtures):
    renderer = RenderEngine()
    out_clip = media_fixtures["jpeg"].parent / "out_test_clip.mp4"

    # Attempting to render a JPEG file must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        renderer.render_shot_clip(
            media_path=media_fixtures["jpeg"],
            duration=2.0,
            motion="none",
            output_path=out_clip
        )
    assert "prohibited image evidence input" in str(exc_info.value).lower()

    # Direct invocation of render_image_shot_clip must also raise ValueError
    with pytest.raises(ValueError) as exc_info2:
        renderer.render_image_shot_clip(
            image_path=media_fixtures["jpeg"],
            duration=2.0,
            motion="zoom_in",
            output_path=out_clip
        )
    assert "prohibited" in str(exc_info2.value).lower()


# ==============================================================================
# 17. Valid video pipeline end-to-end integration
# ==============================================================================
def test_17_valid_video_pipeline_end_to_end(media_fixtures):
    """Verifies that authentic video flows smoothly through all stages."""
    mp4_file = media_fixtures["mp4"]

    # 1. Validation
    assert PhysicalVideoValidator.is_valid_video(mp4_file) is True

    # 2. Candidate Creation & Temporal Moment Localization
    cand = FootageCandidate(
        candidate_id="cand_integration_01",
        title="Valid Archival Newsreel",
        source_platform="LocalVerifiedArchive",
        source_url=f"file:///{mp4_file.name}",
        media_url_or_path=str(mp4_file),
        duration_sec=2.0,
        media_type="video",
        is_video=True,
        confidence_score=0.90
    )
    retriever = TemporalMomentRetriever()
    start, end = retriever.localize_moment(cand, target_duration=1.5)
    assert start >= 0.0 and end > start

    # 3. Visual Claim Verification
    claim = EventClaim(
        claim_id="claim_01",
        sentence_text="The historic expedition arrived safely.",
        where=["expedition"]
    )
    verifier = VisualClaimVerifier()
    is_ver, score, details = verifier.verify_candidate(cand, claim)
    assert score > 0.5

    # 4. Storyboard Validation
    storyboard_scene = {
        "shot_id": "shot_01",
        "asset_type": "video",
        "media_path": str(mp4_file),
        "start_time": start,
        "end_time": end,
        "duration": round(end - start, 2)
    }
    assert StoryboardEngine.validate_storyboard_scene(storyboard_scene) is True

    # 5. FFmpeg Clip Rendering
    renderer = RenderEngine()
    out_clip = mp4_file.parent / "integration_render_test.mp4"
    rendered_output = renderer.render_shot_clip(
        media_path=mp4_file,
        duration=1.0,
        motion="none",
        output_path=out_clip
    )
    assert rendered_output.exists()
    assert rendered_output.stat().st_size > 1000
    assert PhysicalVideoValidator.is_valid_video(rendered_output) is True
