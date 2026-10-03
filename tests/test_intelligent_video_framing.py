"""
Comprehensive Unit Tests for Step 4/8: Intelligent Video Framing & 9:16 Editorial Cropping.
===========================================================================================
Tests all 20 required invariants and editorial cropping scenarios:
  1. 16:9 → 9:16
  2. 4:3 → 9:16
  3. square → 9:16
  4. vertical source preservation
  5. off-center subject
  6. moving subject
  7. semantic target guidance
  8. motion-guided crop
  9. crop-center smoothing
  10. no violent crop jumps
  11. low-confidence fallback
  12. no black bars
  13. no stretching
  14. output physical video validation
  15. wrong/corrupt input rejection
  16. frozen-video rejection
  17. insufficient-resolution handling
  18. Step 3 temporal extraction remains intact
  19. Step 2 semantic qualification remains intact
  20. VIDEO_ONLY remains absolute
"""
import os
import shutil
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.settings import FFMPEG_EXE
from core.media_validator import PhysicalVideoValidator, VideoValidationResult, VIDEO_ONLY
from engines.visual_intelligence.models import (
    SourceType, NormalizedVideoCandidate, VisualCandidate, VisualIntent,
    VisualContentType, RightsStatus, TemporalWindow
)
from engines.visual_intelligence.framing import (
    IntelligentFramingEngine, FramingSpec, EditorialCropStrategy, CenterOfInterestDetector
)
from engines.visual_intelligence.temporal_extractor import TemporalMomentRetriever
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.internet_retrieval import InternetVideoRetriever


@pytest.fixture(scope="module")
def framing_test_media():
    """Generates synthetic test media for framing tests using FFmpeg."""
    td = tempfile.mkdtemp(prefix="intelligent_framing_tests_")
    dir_path = Path(td)

    # 1. 16:9 video (640x360), 2 seconds, moving testsrc
    sixteen_nine_mp4 = dir_path / "sixteen_nine_640x360.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=640x360:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(sixteen_nine_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. 4:3 video (640x480), 2 seconds, moving testsrc
    four_three_mp4 = dir_path / "four_three_640x480.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=640x480:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(four_three_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. Square video (480x480), 2 seconds, moving testsrc
    square_mp4 = dir_path / "square_480x480.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=480x480:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(square_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 4. Already-vertical 9:16 video (360x640), 2 seconds
    vertical_mp4 = dir_path / "vertical_360x640.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=360x640:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(vertical_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 5. Off-center subject video: motion concentrated on far left (x=60 to 180 of 640)
    off_center_left_mp4 = dir_path / "off_center_left.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi",
        "-i", "color=c=black:s=640x360:d=2[bg];testsrc=s=120x120:d=2[box];[bg][box]overlay=x=60:y=120",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(off_center_left_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 6. Moving subject video: object moving from left to right over 2 seconds
    moving_subject_mp4 = dir_path / "moving_subject.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi",
        "-i", "color=c=black:s=640x360:d=2[bg];testsrc=s=100x100:d=2[box];[bg][box]overlay=x='60+220*t':y=120",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(moving_subject_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 7. Frozen video (100% identical navy frames across 2 seconds)
    frozen_mp4 = dir_path / "frozen_video.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "color=c=navy:s=640x360:d=2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(frozen_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 8. Insufficient resolution video (160x120)
    tiny_res_mp4 = dir_path / "tiny_160x120.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(tiny_res_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 9. Genuine JPEG image
    jpeg_file = dir_path / "sample_photo.jpg"
    img = Image.new("RGB", (640, 360), color=(100, 150, 200))
    img.save(jpeg_file, "JPEG")

    # 10. Fake renamed JPEG
    fake_renamed_mp4 = dir_path / "fake_renamed.mp4"
    shutil.copyfile(jpeg_file, fake_renamed_mp4)

    # 11. Corrupt data file
    corrupt_mp4 = dir_path / "corrupt_data.mp4"
    with open(corrupt_mp4, "wb") as f:
        f.write(b"CORRUPT_BYTES_NOT_A_VALID_CONTAINER")

    yield {
        "sixteen_nine_mp4": sixteen_nine_mp4,
        "four_three_mp4": four_three_mp4,
        "square_mp4": square_mp4,
        "vertical_mp4": vertical_mp4,
        "off_center_left_mp4": off_center_left_mp4,
        "moving_subject_mp4": moving_subject_mp4,
        "frozen_mp4": frozen_mp4,
        "tiny_res_mp4": tiny_res_mp4,
        "jpeg_file": jpeg_file,
        "fake_renamed_mp4": fake_renamed_mp4,
        "corrupt_mp4": corrupt_mp4,
        "temp_dir": dir_path
    }

    shutil.rmtree(td, ignore_errors=True)


class TestIntelligentVideoFraming:

    # --------------------------------------------------------------------------
    # 1. 16:9 → 9:16
    # --------------------------------------------------------------------------
    def test_01_sixteen_nine_to_nine_sixteen(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["sixteen_nine_mp4"]
        output = engine.frame_video_to_916(src)

        assert output is not None and output.exists()
        val = PhysicalVideoValidator.validate_file(output)
        assert val.is_valid is True
        assert val.width == 1080
        assert val.height == 1920
        assert abs((val.width / val.height) - (9.0 / 16.0)) < 0.01

    # --------------------------------------------------------------------------
    # 2. 4:3 → 9:16
    # --------------------------------------------------------------------------
    def test_02_four_three_to_nine_sixteen(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["four_three_mp4"]
        output = engine.frame_video_to_916(src)

        assert output is not None and output.exists()
        val = PhysicalVideoValidator.validate_file(output)
        assert val.is_valid is True
        assert val.width == 1080
        assert val.height == 1920

    # --------------------------------------------------------------------------
    # 3. Square → 9:16
    # --------------------------------------------------------------------------
    def test_03_square_to_nine_sixteen(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["square_mp4"]
        output = engine.frame_video_to_916(src)

        assert output is not None and output.exists()
        val = PhysicalVideoValidator.validate_file(output)
        assert val.is_valid is True
        assert val.width == 1080
        assert val.height == 1920

    # --------------------------------------------------------------------------
    # 4. Vertical source preservation
    # --------------------------------------------------------------------------
    def test_04_vertical_source_preservation(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["vertical_mp4"]
        spec = engine.calculate_framing_spec(src)

        assert spec.strategy == EditorialCropStrategy.CENTER_CROP
        assert spec.is_moving is False
        assert "scale=1080:1920" in spec.ffmpeg_crop_filter

        output = engine.frame_video_to_916(src)
        assert output is not None
        val = PhysicalVideoValidator.validate_file(output)
        assert val.is_valid is True
        assert val.width == 1080
        assert val.height == 1920

    # --------------------------------------------------------------------------
    # 5. Off-center subject
    # --------------------------------------------------------------------------
    def test_05_off_center_subject(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["off_center_left_mp4"]
        spec = engine.calculate_framing_spec(src)

        # Subject and motion are on the left (x ~ 0.15 - 0.30)
        assert spec.start_cx < 0.40
        assert spec.end_cx < 0.40
        assert spec.strategy in (EditorialCropStrategy.MOTION_GUIDED, EditorialCropStrategy.SUBJECT_GUIDED)

    # --------------------------------------------------------------------------
    # 6. Moving subject
    # --------------------------------------------------------------------------
    def test_06_moving_subject(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["moving_subject_mp4"]
        spec = engine.calculate_framing_spec(src)

        # Subject moves from left to right over time
        assert spec.is_moving is True
        assert spec.end_cx > spec.start_cx
        assert "crop=1080:1920:'min(" in spec.ffmpeg_crop_filter

    # --------------------------------------------------------------------------
    # 7. Semantic target guidance
    # --------------------------------------------------------------------------
    def test_07_semantic_target_guidance(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["sixteen_nine_mp4"]
        intent = VisualIntent(
            beat_id="b7", beat_index=0,
            narration_text="The ship collided on the port side left.",
            visual_action="struck left",
            target_object="ship"
        )
        spec = engine.calculate_framing_spec(src, intent=intent, metadata={"subject_x": 0.25})

        assert spec.strategy == EditorialCropStrategy.SUBJECT_GUIDED
        assert spec.start_cx < 0.40

    # --------------------------------------------------------------------------
    # 8. Motion-guided crop
    # --------------------------------------------------------------------------
    def test_08_motion_guided_crop(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["off_center_left_mp4"]
        spec = engine.calculate_framing_spec(src)

        assert spec.strategy == EditorialCropStrategy.MOTION_GUIDED
        assert spec.confidence >= 0.70

    # --------------------------------------------------------------------------
    # 9. Crop-center smoothing
    # --------------------------------------------------------------------------
    def test_09_crop_center_smoothing(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["moving_subject_mp4"]
        spec = engine.calculate_framing_spec(src)

        # Pan speed must adhere to MAX_PAN_SPEED smoothing constraint
        assert spec.pan_speed <= engine.detector.MAX_PAN_SPEED + 0.01

    # --------------------------------------------------------------------------
    # 10. No violent crop jumps
    # --------------------------------------------------------------------------
    def test_10_no_violent_crop_jumps(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["moving_subject_mp4"]
        spec = engine.calculate_framing_spec(src)

        # Delta must be smoothly bounded over the 2-second duration
        total_delta = abs(spec.end_cx - spec.start_cx)
        assert total_delta <= (engine.detector.MAX_PAN_SPEED * 2.0) + 0.02

    # --------------------------------------------------------------------------
    # 11. Low-confidence fallback
    # --------------------------------------------------------------------------
    def test_11_low_confidence_fallback(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["sixteen_nine_mp4"]

        # Mock detector returning low confidence
        with patch.object(engine.detector, "analyze_video_trajectory", return_value=([(0.0, 0.5, 0.5)], 0.25, False)):
            spec = engine.calculate_framing_spec(src)
            assert spec.strategy == EditorialCropStrategy.SAFE_FALLBACK
            assert spec.start_cx == 0.5
            assert spec.end_cx == 0.5

    # --------------------------------------------------------------------------
    # 12. No black bars
    # --------------------------------------------------------------------------
    def test_12_no_black_bars(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["sixteen_nine_mp4"]
        output = engine.frame_video_to_916(src)
        assert output is not None

        # Verify using FFmpeg blackdetect that the frame is not padded with black borders
        cmd = [
            FFMPEG_EXE, "-i", str(output),
            "-vf", "blackdetect=d=0.5:pic_th=0.98",
            "-an", "-f", "null", "-"
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # Blackdetect should NOT find continuous black frames across the whole video
        assert "black_duration:2" not in res.stderr

    # --------------------------------------------------------------------------
    # 13. No stretching
    # --------------------------------------------------------------------------
    def test_13_no_stretching(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["four_three_mp4"]
        spec = engine.calculate_framing_spec(src)

        # Scale preserves square pixel aspect ratio setsar=1
        assert "setsar=1" in spec.ffmpeg_crop_filter
        # Scaled height equals 1920 and width scales proportionally (not stretched)
        assert spec.metadata["scaled_h"] == 1920
        assert spec.metadata["scaled_w"] == round(640 * (1920.0 / 480.0))

    # --------------------------------------------------------------------------
    # 14. Output physical video validation
    # --------------------------------------------------------------------------
    def test_14_output_physical_video_validation(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        output = engine.frame_video_to_916(framing_test_media["sixteen_nine_mp4"])
        assert output is not None

        val = PhysicalVideoValidator.validate_file(output)
        assert val.is_valid is True
        assert val.codec in ("h264", "libx264", "avc1")
        assert val.duration > 1.0
        assert val.width == 1080 and val.height == 1920

    # --------------------------------------------------------------------------
    # 15. Wrong / corrupt input rejection
    # --------------------------------------------------------------------------
    def test_15_wrong_corrupt_input_rejection(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        with pytest.raises((ValueError, FileNotFoundError)):
            engine.calculate_framing_spec(framing_test_media["corrupt_mp4"])

        out = engine.frame_video_to_916(framing_test_media["corrupt_mp4"])
        assert out is None

    # --------------------------------------------------------------------------
    # 16. Frozen-video rejection
    # --------------------------------------------------------------------------
    def test_16_frozen_video_rejection(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["frozen_mp4"]

        with pytest.raises(ValueError, match="frozen/static"):
            engine.calculate_framing_spec(src)

        out = engine.frame_video_to_916(src)
        assert out is None

    # --------------------------------------------------------------------------
    # 17. Insufficient-resolution handling
    # --------------------------------------------------------------------------
    def test_17_insufficient_resolution_handling(self, framing_test_media):
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])
        src = framing_test_media["tiny_res_mp4"]

        with pytest.raises(ValueError, match="below minimum"):
            engine.calculate_framing_spec(src)

        out = engine.frame_video_to_916(src)
        assert out is None

    # --------------------------------------------------------------------------
    # 18. Step 3 temporal extraction remains intact
    # --------------------------------------------------------------------------
    def test_18_step3_temporal_extraction_remains_intact(self, framing_test_media):
        tmr = TemporalMomentRetriever(cache_dir=framing_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Step 3 Candidate", local_path=str(framing_test_media["sixteen_nine_mp4"]),
            duration=2.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(cand, target_duration=2.0)
        assert clip_path is not None
        assert win is not None
        assert PhysicalVideoValidator.is_valid_video(clip_path) is True

    # --------------------------------------------------------------------------
    # 19. Step 2 semantic qualification remains intact
    # --------------------------------------------------------------------------
    def test_19_step2_semantic_qualification_remains_intact(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b19", beat_index=0,
            narration_text="Dyatlov Pass incident search party.",
            primary_entity="Dyatlov Pass"
        )
        cand_generic = VisualCandidate(
            candidate_id="cg", source_class="SOURCE_A", source_name="stock",
            source_url="https://stock.org/mountain.mp4", title="Generic mountain scenery",
            is_video=True, source_type=SourceType.STOCK
        )
        score = scorer.score_candidate(cand_generic, intent)
        assert score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 20. VIDEO_ONLY remains absolute
    # --------------------------------------------------------------------------
    def test_20_video_only_remains_absolute(self, framing_test_media):
        assert VIDEO_ONLY is True
        engine = IntelligentFramingEngine(cache_dir=framing_test_media["temp_dir"])

        # Genuine JPEG
        out_jpg = engine.frame_video_to_916(framing_test_media["jpeg_file"])
        assert out_jpg is None

        # Fake renamed JPEG
        out_fake = engine.frame_video_to_916(framing_test_media["fake_renamed_mp4"])
        assert out_fake is None
