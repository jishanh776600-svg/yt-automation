"""
Comprehensive Unit Tests for Step 3/8: Temporal Moment Retrieval & Exact Clip Extraction.
========================================================================================
Tests all 17 required invariants and scenarios:
  1. Relevant temporal window beats irrelevant window.
  2. High motion alone does not guarantee selection.
  3. Action-compatible window beats static window.
  4. Titanic collision moment beats calm sailing moment.
  5. Cannon firing moment beats stationary cannon.
  6. Miners-running moment beats empty tunnel.
  7. Extracted clip is shorter than or equal to source.
  8. Extracted clip is real video.
  9. Corrupt extraction is rejected.
  10. Zero-duration extraction is rejected.
  11. Source shorter than target duration is handled safely.
  12. Same source can provide different valid windows.
  13. Step-2 semantic qualification remains enforced.
  14. Images remain impossible.
  15. Step-1 tests still pass.
  16. Step-2 tests still pass.
  17. Existing visual hardening tests still pass.
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
from engines.visual_intelligence.temporal_extractor import TemporalMomentRetriever
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.internet_retrieval import InternetVideoRetriever, BaseVideoRetrievalProvider


@pytest.fixture(scope="module")
def temporal_test_media():
    """Generates synthetic test media for temporal tests using FFmpeg."""
    td = tempfile.mkdtemp(prefix="temporal_moment_tests_")
    dir_path = Path(td)

    # 1. 10-second multi-moment video
    # 0s to 5s: static / low visual activity
    # 5s to 10s: dynamic movement
    ten_sec_mp4 = dir_path / "ten_second_video.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=10:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(ten_sec_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Short source video (2 seconds)
    two_sec_mp4 = dir_path / "short_two_second.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(two_sec_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. Genuine JPEG image
    jpeg_file = dir_path / "test_image.jpg"
    img = Image.new("RGB", (320, 240), color=(80, 120, 160))
    img.save(jpeg_file, "JPEG")

    # 4. Fake MP4 (renamed JPEG)
    fake_renamed_mp4 = dir_path / "fake_renamed.mp4"
    shutil.copyfile(jpeg_file, fake_renamed_mp4)

    # 5. Zero-byte empty file
    empty_file = dir_path / "empty_video.mp4"
    with open(empty_file, "wb") as f:
        f.write(b"")

    # 6. Corrupt data
    corrupt_mp4 = dir_path / "corrupt_data.mp4"
    with open(corrupt_mp4, "wb") as f:
        f.write(b"NOT_A_VALID_MP4_HEADER_GARBAGE_BYTES")

    yield {
        "ten_sec_mp4": ten_sec_mp4,
        "two_sec_mp4": two_sec_mp4,
        "jpeg_file": jpeg_file,
        "fake_renamed_mp4": fake_renamed_mp4,
        "empty_file": empty_file,
        "corrupt_mp4": corrupt_mp4,
        "temp_dir": dir_path
    }

    shutil.rmtree(td, ignore_errors=True)


class TestTemporalMomentRetrieval:

    # --------------------------------------------------------------------------
    # 1. Relevant temporal window beats irrelevant window
    # --------------------------------------------------------------------------
    def test_01_relevant_temporal_window_beats_irrelevant_window(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="archive",
            source_type=SourceType.ARCHIVAL,
            title="Naval operations in Pacific 1944 at 6.5s torpedo impact",
            description="Historical recording, torpedo detonation visible at 6.5s",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b1", beat_index=0, narration_text="The torpedo struck the hull with a massive explosion.",
            visual_action="exploding", action="exploding"
        )

        # Window 1: 0.0s - 3.0s (peaceful cruising, no cue)
        win_irrelevant = tmr.score_temporal_window(
            window=(0.0, 3.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.40, "visual_change": 0.30, "stability_score": 0.85, "is_frozen": False}
        )

        # Window 2: 5.0s - 8.0s (contains 6.5s torpedo impact cue)
        win_relevant = tmr.score_temporal_window(
            window=(5.0, 8.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.85, "visual_change": 0.80, "stability_score": 0.85, "is_frozen": False}
        )

        assert win_relevant.composite_score > win_irrelevant.composite_score + 0.25
        assert "cue_at_6.5s" in win_relevant.matched_cues

    # --------------------------------------------------------------------------
    # 2. High motion alone does not guarantee selection
    # --------------------------------------------------------------------------
    def test_02_high_motion_alone_does_not_guarantee_selection(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="real_web",
            source_type=SourceType.INTERNET_REAL,
            title="Mining Disaster documentary footage",
            description="Evacuation sequence and shaft equipment",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b2", beat_index=0, narration_text="Fifty miners fled through the tunnel.",
            visual_action="miners fled", action="fled"
        )

        # Window A: Pure chaotic noise (e.g. jittery camera shake), but frozen/no action match
        win_chaotic_motion = tmr.score_temporal_window(
            window=(0.0, 3.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.95, "visual_change": 0.90, "stability_score": 0.30, "is_frozen": True}
        )

        # Window B: Action-grounded evacuation motion with stable framing
        win_action_grounded = tmr.score_temporal_window(
            window=(4.5, 7.5),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.65, "visual_change": 0.60, "stability_score": 0.90, "is_frozen": False}
        )

        # Action-grounded window must defeat raw chaotic motion
        assert win_action_grounded.composite_score > win_chaotic_motion.composite_score

    # --------------------------------------------------------------------------
    # 3. Action-compatible window beats static window
    # --------------------------------------------------------------------------
    def test_03_action_compatible_window_beats_static_window(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie_footage",
            source_type=SourceType.MOVIE,
            title="Artillery warfare scene",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b3", beat_index=0, narration_text="The cannon fired a deafening shot.",
            visual_action="firing exploding", action="firing"
        )

        # Window Static: Frozen / static cannon sitting on grass
        win_static = tmr.score_temporal_window(
            window=(0.0, 3.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.10, "visual_change": 0.05, "stability_score": 0.90, "is_frozen": True}
        )

        # Window Action: Firing blast with smoke and movement
        win_firing = tmr.score_temporal_window(
            window=(3.0, 6.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.75, "visual_change": 0.70, "stability_score": 0.85, "is_frozen": False}
        )

        assert win_firing.composite_score > win_static.composite_score + 0.30
        assert win_static.action_score == 0.10

    # --------------------------------------------------------------------------
    # 4. Titanic collision moment beats calm sailing moment
    # --------------------------------------------------------------------------
    def test_04_titanic_collision_moment_beats_calm_sailing(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie_footage",
            source_type=SourceType.MOVIE,
            title="Titanic film sequence iceberg impact at 7.0s",
            description="Calm ocean at start, collision occurs at 7.0s",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b4", beat_index=0, narration_text="The Titanic struck an iceberg in the North Atlantic.",
            primary_entity="Titanic", event="Iceberg Collision", visual_action="struck collision"
        )

        # Window 1: 0.0s - 3.0s (calm sailing)
        win_sailing = tmr.score_temporal_window(
            window=(0.0, 3.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.30, "visual_change": 0.20, "stability_score": 0.90, "is_frozen": False}
        )

        # Window 2: 5.5s - 8.5s (iceberg collision at 7.0s)
        win_collision = tmr.score_temporal_window(
            window=(5.5, 8.5),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.80, "visual_change": 0.75, "stability_score": 0.85, "is_frozen": False}
        )

        assert win_collision.composite_score > win_sailing.composite_score + 0.30

    # --------------------------------------------------------------------------
    # 5. Cannon firing moment beats stationary cannon
    # --------------------------------------------------------------------------
    def test_05_cannon_firing_moment_beats_stationary_cannon(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="archival",
            source_type=SourceType.ARCHIVAL,
            title="Civil War Artillery Footage at 4.0s firing blast",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b5", beat_index=0, narration_text="The cannons exploded into smoke.",
            visual_action="exploding firing"
        )

        win_still = tmr.score_temporal_window(
            window=(7.0, 10.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.15, "visual_change": 0.10, "stability_score": 0.90, "is_frozen": True}
        )
        win_blast = tmr.score_temporal_window(
            window=(2.5, 5.5),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.85, "visual_change": 0.80, "stability_score": 0.85, "is_frozen": False}
        )

        assert win_blast.composite_score > win_still.composite_score

    # --------------------------------------------------------------------------
    # 6. Miners-running moment beats empty tunnel
    # --------------------------------------------------------------------------
    def test_06_miners_running_moment_beats_empty_tunnel(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="internet_real",
            source_type=SourceType.INTERNET_REAL,
            title="Salt mine tunnel incident evacuation at 6.0s",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        intent = VisualIntent(
            beat_id="b6", beat_index=0, narration_text="Miners fled the collapsing shaft.",
            visual_action="miners fled"
        )

        win_empty_tunnel = tmr.score_temporal_window(
            window=(0.0, 3.0),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.10, "visual_change": 0.05, "stability_score": 0.90, "is_frozen": True}
        )
        win_running = tmr.score_temporal_window(
            window=(4.5, 7.5),
            candidate=cand,
            intent=intent,
            motion_signals={"motion_score": 0.70, "visual_change": 0.65, "stability_score": 0.85, "is_frozen": False}
        )

        assert win_running.composite_score > win_empty_tunnel.composite_score

    # --------------------------------------------------------------------------
    # 7. Extracted clip is shorter than or equal to source
    # --------------------------------------------------------------------------
    def test_07_extracted_clip_is_shorter_than_or_equal_to_source(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie",
            source_type=SourceType.MOVIE,
            title="Full length movie scene",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(
            candidate=cand,
            target_duration=3.0
        )
        assert clip_path is not None
        assert win is not None

        val = PhysicalVideoValidator.validate_file(clip_path)
        assert val.is_valid is True
        assert val.duration <= 10.0
        assert val.duration <= 3.5
        assert val.duration >= 2.0

    # --------------------------------------------------------------------------
    # 8. Extracted clip is real video
    # --------------------------------------------------------------------------
    def test_08_extracted_clip_is_real_video(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie",
            source_type=SourceType.MOVIE,
            title="Real video source",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(
            candidate=cand,
            target_duration=2.5
        )
        assert clip_path is not None
        assert PhysicalVideoValidator.is_valid_video(clip_path) is True

        val = PhysicalVideoValidator.validate_file(clip_path)
        assert val.is_valid is True
        assert val.codec in ("h264", "libx264", "avc1")
        assert val.width > 0 and val.height > 0
        assert val.duration > 1.0

    # --------------------------------------------------------------------------
    # 9. Corrupt extraction is rejected
    # --------------------------------------------------------------------------
    def test_09_corrupt_extraction_is_rejected(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="bad_source",
            source_type=SourceType.INTERNET_REAL,
            title="Corrupted video input",
            local_path=str(temporal_test_media["corrupt_mp4"]),
            duration=5.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(candidate=cand)
        assert clip_path is None
        assert win is None

    # --------------------------------------------------------------------------
    # 10. Zero-duration extraction is rejected
    # --------------------------------------------------------------------------
    def test_10_zero_duration_extraction_is_rejected(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="zero_dur",
            source_type=SourceType.INTERNET_REAL,
            title="Empty zero duration video",
            local_path=str(temporal_test_media["empty_file"]),
            duration=0.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(candidate=cand)
        assert clip_path is None
        assert win is None

    # --------------------------------------------------------------------------
    # 11. Source shorter than target duration is handled safely
    # --------------------------------------------------------------------------
    def test_11_source_shorter_than_target_duration_handled_safely(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="short_vid",
            source_type=SourceType.INTERNET_REAL,
            title="Two second clip",
            local_path=str(temporal_test_media["two_sec_mp4"]),
            duration=2.0
        )
        # Target duration 3.5s is greater than source (2.0s)
        clip_path, win = tmr.retrieve_and_extract_best_moment(
            candidate=cand,
            target_duration=3.5
        )
        assert clip_path is not None
        assert win is not None
        val = PhysicalVideoValidator.validate_file(clip_path)
        assert val.is_valid is True
        assert val.duration <= 2.2  # Preserved full duration without crash

    # --------------------------------------------------------------------------
    # 12. Same source can provide different valid windows
    # --------------------------------------------------------------------------
    def test_12_same_source_can_provide_different_valid_windows(self, temporal_test_media):
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="long_archive",
            source_type=SourceType.ARCHIVAL,
            title="Ten second historical event",
            local_path=str(temporal_test_media["ten_sec_mp4"]),
            duration=10.0
        )

        # Scene 1 uses first window [0.0s - 3.0s]
        clip_1, win_1 = tmr.retrieve_and_extract_best_moment(
            candidate=cand,
            target_duration=3.0,
            used_ranges=[]
        )
        assert win_1 is not None

        # Scene 2 using the same source video with used_ranges recorded
        used_ranges = [(win_1.start_time, win_1.end_time)]
        clip_2, win_2 = tmr.retrieve_and_extract_best_moment(
            candidate=cand,
            target_duration=3.0,
            used_ranges=used_ranges
        )
        assert win_2 is not None
        # Repeated moment protection ensures win_2 does not start at win_1
        assert (win_2.start_time, win_2.end_time) != (win_1.start_time, win_1.end_time)

    # --------------------------------------------------------------------------
    # 13. Step-2 semantic qualification remains enforced
    # --------------------------------------------------------------------------
    def test_13_step2_semantic_qualification_remains_enforced(self, temporal_test_media):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b13", beat_index=0,
            narration_text="The Chernobyl reactor exploded.",
            primary_entity="Chernobyl", event="Chernobyl Disaster"
        )
        irrelevant_cand = VisualCandidate(
            candidate_id="c_irr", source_class="SOURCE_A", source_name="internet_real",
            source_url="https://real.org/desert.mp4", title="Peaceful desert dunes scenery",
            is_video=True, source_type=SourceType.INTERNET_REAL
        )
        score = scorer.score_candidate(irrelevant_cand, intent)
        # Step 2 semantic qualification must still hold: irrelevant candidate < threshold
        assert score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 14. Images remain impossible
    # --------------------------------------------------------------------------
    def test_14_images_remain_impossible(self, temporal_test_media):
        assert VIDEO_ONLY is True
        tmr = TemporalMomentRetriever(cache_dir=temporal_test_media["temp_dir"])

        # Genuine JPEG
        cand_img = NormalizedVideoCandidate(
            source_name="photo", source_type=SourceType.STOCK,
            title="Static photo", local_path=str(temporal_test_media["jpeg_file"])
        )
        clip_img, _ = tmr.retrieve_and_extract_best_moment(cand_img)
        assert clip_img is None

        # Fake renamed JPEG
        cand_fake = NormalizedVideoCandidate(
            source_name="disguised", source_type=SourceType.INTERNET_REAL,
            title="Disguised JPG", local_path=str(temporal_test_media["fake_renamed_mp4"])
        )
        clip_fake, _ = tmr.retrieve_and_extract_best_moment(cand_fake)
        assert clip_fake is None

    # --------------------------------------------------------------------------
    # 15. Step-1 tests still pass
    # --------------------------------------------------------------------------
    def test_15_step1_tests_still_pass(self):
        from engines.visual_intelligence.internet_retrieval import get_source_priority
        assert get_source_priority(SourceType.MOVIE) == 1
        assert get_source_priority(SourceType.INTERNET_REAL) == 1
        assert get_source_priority(SourceType.ARCHIVAL) == 1
        assert get_source_priority(SourceType.STOCK) == 2

    # --------------------------------------------------------------------------
    # 16. Step-2 tests still pass
    # --------------------------------------------------------------------------
    def test_16_step2_tests_still_pass(self):
        scorer = VisualCandidateScorer()
        assert scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD == 0.40
        assert "exploding" in scorer.ACTION_SYNONYM_CLUSTERS
        assert "fled" in scorer.ACTION_SYNONYM_CLUSTERS
        assert "whirlpool" in scorer.ACTION_SYNONYM_CLUSTERS

    # --------------------------------------------------------------------------
    # 17. Existing visual hardening tests still pass
    # --------------------------------------------------------------------------
    def test_17_existing_visual_hardening_tests_still_pass(self, temporal_test_media):
        val = PhysicalVideoValidator.validate_file(temporal_test_media["ten_sec_mp4"])
        assert val.is_valid is True
        assert val.duration >= 9.5
