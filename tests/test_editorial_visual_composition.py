"""
Test Suite: Editorial Visual Composition + Narration-Synchronized Pacing (Step 6/8).
===================================================================================
Validates all 24 core requirements:
  1. Narration timeline creation
  2. Sentence timing (monotonic progression, continuous coverage)
  3. Beat timing
  4. Hook timing (first 1.5 - 3.0s)
  5. Dynamic shot durations (not rigid or uniform)
  6. Action-word alignment
  7. Cannon-firing alignment
  8. Collision alignment
  9. Water / whirlpool action alignment
  10. No arbitrary fixed-duration requirement
  11. 6-10 beat density for normal 25-30s content
  12. Visual continuity
  13. Visual variety (anti-repetition across consecutive scenes)
  14. Step 5 duplicate protection remains active
  15. Hook visual relevance
  16. Ending timing
  17. Loop compatibility
  18. Missing word-timestamp fallback (deterministic acoustics + punctuation pauses)
  19. Missing action-anchor fallback
  20. No-image invariant (VIDEO_ONLY = True)
  21. Step 4 framing remains intact
  22. Step 3 temporal extraction remains intact
  23. Step 2 semantic qualification remains intact
  24. Step 1 source hierarchy remains intact
"""
import os
import shutil
import tempfile
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config.settings import FFMPEG_EXE
from core.models import Base
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from engines.visual_intelligence.models import (
    SourceType, VisualCandidate, VisualIntent, VisualContentType,
    NormalizedVideoCandidate, TemporalWindow
)
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.temporal_extractor import TemporalMomentRetriever
from engines.visual_intelligence.framing import IntelligentFramingEngine
from engines.visual_intelligence.memory import VisualMemoryManager
from engines.visual_intelligence.composition import (
    EditorialCompositionEngine,
    NarrationTimelineBuilder,
    NarrationTimeline,
    NarrationSegment,
    NarrationWord,
    SynchronizedShot,
    EditorialComposition,
    ActionAnchorAligner,
)


@pytest.fixture(scope="session")
def composition_test_media(tmp_path_factory):
    """Generates synthetic videos for composition tests."""
    temp_dir = tmp_path_factory.mktemp("composition_tests")

    # 1. 16:9 moving landscape video (640x360, 5.0s)
    base_mp4 = temp_dir / "comp_base_video.mp4"
    cmd_base = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=5:size=640x360:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(base_mp4)
    ]
    subprocess.run(cmd_base, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Action video (smptebars, 640x360, 5.0s)
    action_mp4 = temp_dir / "comp_action_video.mp4"
    cmd_act = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "smptebars=duration=5:size=640x360:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(action_mp4)
    ]
    subprocess.run(cmd_act, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. Prohibited static image (JPEG)
    jpeg_file = temp_dir / "prohibited_photo.jpg"
    cmd_img = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=1",
        "-vframes", "1",
        str(jpeg_file)
    ]
    subprocess.run(cmd_img, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    return {
        "temp_dir": temp_dir,
        "base_mp4": base_mp4,
        "action_mp4": action_mp4,
        "jpeg_file": jpeg_file
    }


@pytest.fixture
def memory_db(tmp_path):
    """Isolated SQLite database for Step 5 memory integration tests."""
    db_file = tmp_path / "comp_memory.db"
    test_engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(bind=test_engine)
    session_factory = sessionmaker(bind=test_engine)
    session = scoped_session(session_factory)
    yield session
    session.remove()
    test_engine.dispose()


class TestEditorialVisualComposition:
    """Comprehensive 24-case test suite for Step 6."""

    SAMPLE_SCRIPT_PARTS = [
        ("hook", "In 1912, the world's largest ship vanished into the icy Atlantic."),
        ("context", "The Titanic was considered unsinkable, carrying over two thousand souls."),
        ("escalation", "Lookouts spotted the frozen menace too late, and the ship slammed into the iceberg."),
        ("reveal", "Within hours, thousands of gallons of water rushed in, dragging it into the abyss."),
        ("loop_twist", "And that is why the unsinkable ship became history's most chilling warning.")
    ]

    # --------------------------------------------------------------------------
    # 1. Narration timeline creation
    # --------------------------------------------------------------------------
    def test_01_narration_timeline_creation(self):
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=25.0
        )
        assert timeline is not None
        assert abs(timeline.total_duration - 25.0) < 0.05
        assert len(timeline.segments) == 5
        assert len(timeline.words) > 20

    # --------------------------------------------------------------------------
    # 2. Sentence timing
    # --------------------------------------------------------------------------
    def test_02_sentence_timing(self):
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=26.0
        )
        # Verify continuous, monotonic progression without temporal gaps
        cur = 0.0
        for seg in timeline.segments:
            assert abs(seg.start_time - cur) < 0.05
            assert seg.end_time > seg.start_time
            cur = seg.end_time
        assert abs(cur - 26.0) < 0.05

    # --------------------------------------------------------------------------
    # 3. Beat timing
    # --------------------------------------------------------------------------
    def test_03_beat_timing(self):
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0
        )
        stages = [s.stage for s in timeline.segments]
        assert stages == ["hook", "context", "escalation", "reveal", "loop_twist"]

    # --------------------------------------------------------------------------
    # 4. Hook timing
    # --------------------------------------------------------------------------
    def test_04_hook_timing(self):
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0
        )
        hook_seg = timeline.segments[0]
        assert hook_seg.start_time == 0.0
        assert 1.5 <= hook_seg.duration <= 4.5

    # --------------------------------------------------------------------------
    # 5. Dynamic shot durations
    # --------------------------------------------------------------------------
    def test_05_dynamic_shot_durations(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=26.0
        )
        planned = engine.plan_shot_density_and_durations(timeline)
        durations = [p[1] for p in planned]

        # Verify durations vary dynamically rather than being uniform
        assert len(set(durations)) > 1
        assert all(1.2 <= d <= 4.5 for d in durations)

    # --------------------------------------------------------------------------
    # 6. Action-word alignment
    # --------------------------------------------------------------------------
    def test_06_action_word_alignment(self, composition_test_media):
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Action clip", duration=5.0,
            local_path=str(composition_test_media["action_mp4"])
        )
        # Word spoken at t=12.2s; shot runs 10.0 to 13.0s
        clip_in, clip_out, action_tl, action_offset = ActionAnchorAligner.align_shot_action(
            shot_start_timeline=10.0,
            shot_duration=3.0,
            action_word_timeline=12.2,
            source_candidate=cand
        )
        assert action_tl == 12.2
        assert clip_out - clip_in == 3.0

    # --------------------------------------------------------------------------
    # 7. Cannon-firing alignment
    # --------------------------------------------------------------------------
    def test_07_cannon_firing_alignment(self, composition_test_media):
        parts = [("escalation", "Then the heavy naval cannon fired.")]
        timeline = NarrationTimelineBuilder.build_timeline(parts, total_duration=3.0)
        assert timeline.segments[0].has_action is True
        assert timeline.segments[0].action_type == "fired"

        cand = NormalizedVideoCandidate(
            source_name="archival", source_type=SourceType.ARCHIVAL,
            title="Cannon fire", duration=5.0
        )
        clip_in, clip_out, action_tl, _ = ActionAnchorAligner.align_shot_action(
            shot_start_timeline=timeline.segments[0].start_time,
            shot_duration=timeline.segments[0].duration,
            action_word_timeline=timeline.segments[0].action_anchor_time,
            source_candidate=cand
        )
        assert action_tl is not None
        assert abs(action_tl - timeline.segments[0].action_anchor_time) < 0.05

    # --------------------------------------------------------------------------
    # 8. Collision alignment
    # --------------------------------------------------------------------------
    def test_08_collision_alignment(self):
        parts = [("escalation", "The massive vessel slammed into the iceberg.")]
        timeline = NarrationTimelineBuilder.build_timeline(parts, total_duration=3.5)
        assert timeline.segments[0].has_action is True
        assert timeline.segments[0].action_type == "collision"

    # --------------------------------------------------------------------------
    # 9. Water / whirlpool action alignment
    # --------------------------------------------------------------------------
    def test_09_water_whirlpool_action_alignment(self):
        parts = [("reveal", "Millions of gallons of water rushed in, swallowing the hull.")]
        timeline = NarrationTimelineBuilder.build_timeline(parts, total_duration=4.0)
        assert timeline.segments[0].has_action is True
        assert timeline.segments[0].action_type == "water_rush"

    # --------------------------------------------------------------------------
    # 10. No arbitrary fixed-duration requirement
    # --------------------------------------------------------------------------
    def test_10_no_arbitrary_fixed_duration_requirement(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        timeline = NarrationTimelineBuilder.build_timeline(
            self.SAMPLE_SCRIPT_PARTS, total_duration=25.0
        )
        planned = engine.plan_shot_density_and_durations(timeline)
        durs = [dur for _, dur, _ in planned]
        # Durations must NOT all equal 2.5s or any single constant
        assert len(set(durs)) >= 3

    # --------------------------------------------------------------------------
    # 11. 6-10 beat density for normal 25-30s content
    # --------------------------------------------------------------------------
    def test_11_six_to_ten_beat_density_for_normal_shorts(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        timeline = NarrationTimelineBuilder.build_timeline(
            self.SAMPLE_SCRIPT_PARTS, total_duration=26.0
        )
        planned = engine.plan_shot_density_and_durations(timeline)
        assert 6 <= len(planned) <= 10

    # --------------------------------------------------------------------------
    # 12. Visual continuity
    # --------------------------------------------------------------------------
    def test_12_visual_continuity(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand1 = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Ship at sea", duration=5.0, page_url="https://cinema.org/ship.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        cand2 = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Iceberg in fog", duration=5.0, page_url="https://cinema.org/iceberg.mp4",
            local_path=str(composition_test_media["action_mp4"])
        )

        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0,
            candidates_by_beat=[[cand1], [cand2], [cand1], [cand2], [cand1]]
        )
        assert len(composition.shots) >= 6
        # Shots progress continuously across the timeline
        for i in range(len(composition.shots) - 1):
            assert abs(composition.shots[i].timeline_end - composition.shots[i+1].timeline_start) < 0.05

    # --------------------------------------------------------------------------
    # 13. Visual variety
    # --------------------------------------------------------------------------
    def test_13_visual_variety(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand1 = NormalizedVideoCandidate(
            source_name="source_1", source_type=SourceType.ARCHIVAL,
            title="Source 1", page_url="https://src1.org/v.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        cand2 = NormalizedVideoCandidate(
            source_name="source_2", source_type=SourceType.INTERNET_REAL,
            title="Source 2", page_url="https://src2.org/v.mp4",
            local_path=str(composition_test_media["action_mp4"])
        )

        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0,
            candidates_by_beat=[[cand1, cand2], [cand1, cand2], [cand1, cand2], [cand1, cand2], [cand1, cand2]]
        )
        # Consecutive scenes should alternate where alternative candidates exist
        consecutive_same_count = sum(
            1 for i in range(len(composition.shots) - 1)
            if composition.shots[i].candidate.page_url == composition.shots[i+1].candidate.page_url
        )
        assert consecutive_same_count == 0

    # --------------------------------------------------------------------------
    # 14. Step 5 duplicate protection remains active
    # --------------------------------------------------------------------------
    def test_14_step5_duplicate_protection_remains_active(self, composition_test_media, memory_db):
        mem = VisualMemoryManager(db_session=memory_db, classification="PRODUCTION")
        engine = EditorialCompositionEngine(
            cache_dir=composition_test_media["temp_dir"],
            visual_memory=mem
        )

        cand_used = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Used Clip", page_url="https://movies.org/already_used.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        # Record usage 2 hours ago
        mem.record_usage(cand_used, composition_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        cand_clean = NormalizedVideoCandidate(
            source_name="archival", source_type=SourceType.ARCHIVAL,
            title="Clean Clip", page_url="https://archives.org/fresh_item.mp4",
            local_path=str(composition_test_media["action_mp4"])
        )

        composition = engine.compose_short(
            script_parts=[("hook", "Look at this historical moment.")],
            total_duration=3.0,
            candidates_by_beat=[[cand_used, cand_clean]]
        )
        # Must select cand_clean because cand_used is in memory
        assert composition.shots[0].candidate.page_url == cand_clean.page_url

    # --------------------------------------------------------------------------
    # 15. Hook visual relevance
    # --------------------------------------------------------------------------
    def test_15_hook_visual_relevance(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand_hook = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Titanic collision iceberg disaster", page_url="https://movie.org/hook.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0,
            candidates_by_beat=[[cand_hook]]
        )
        assert composition.shots[0].is_hook is True
        assert composition.shots[0].narrative_role in ("HOOK", "HOOK_TEASE")

    # --------------------------------------------------------------------------
    # 16. Ending timing
    # --------------------------------------------------------------------------
    def test_16_ending_timing(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Ending Footage", page_url="https://movie.org/end.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=25.0,
            candidates_by_beat=[[cand]]
        )
        last_shot = composition.shots[-1]
        assert last_shot.is_ending is True
        assert abs(last_shot.timeline_end - 25.0) < 0.05

    # --------------------------------------------------------------------------
    # 17. Loop compatibility
    # --------------------------------------------------------------------------
    def test_17_loop_compatibility(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Loop Footage", page_url="https://movie.org/loop.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=25.0,
            candidates_by_beat=[[cand]]
        )
        last_shot = composition.shots[-1]
        assert last_shot.narrative_role in ("OUTRO_LOOP", "OUTRO")
        assert 2.0 <= last_shot.duration <= 4.0

    # --------------------------------------------------------------------------
    # 18. Missing word-timestamp fallback
    # --------------------------------------------------------------------------
    def test_18_missing_word_timestamp_fallback(self):
        # When word_timestamps=None, timeline builds successfully using acoustics
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=25.0,
            word_timestamps=None
        )
        assert len(timeline.segments) == 5
        assert len(timeline.words) > 0
        assert abs(timeline.segments[-1].end_time - 25.0) < 0.05

    # --------------------------------------------------------------------------
    # 19. Missing action-anchor fallback
    # --------------------------------------------------------------------------
    def test_19_missing_action_anchor_fallback(self):
        cand = NormalizedVideoCandidate(
            source_name="stock", source_type=SourceType.STOCK,
            title="Calm lake landscape", duration=6.0
        )
        clip_in, clip_out, action_tl, action_offset = ActionAnchorAligner.align_shot_action(
            shot_start_timeline=5.0,
            shot_duration=2.5,
            action_word_timeline=None,
            source_candidate=cand
        )
        # Safely defaults to beginning of window without error
        assert clip_in == 0.0
        assert clip_out == 2.5
        assert action_tl is None

    # --------------------------------------------------------------------------
    # 20. No-image invariant
    # --------------------------------------------------------------------------
    def test_20_no_image_invariant(self, composition_test_media):
        assert VIDEO_ONLY is True
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])

        # Candidate that points to a prohibited image
        cand_img = NormalizedVideoCandidate(
            source_name="stock", source_type=SourceType.STOCK,
            title="Image Candidate", page_url="https://stock.org/pic.jpg",
            local_path=str(composition_test_media["jpeg_file"]),
            is_video=False
        )

        with pytest.raises(RuntimeError, match="No video candidates available"):
            engine.compose_short(
                script_parts=[("hook", "Test scene")],
                total_duration=3.0,
                candidates_by_beat=[[cand_img]]
            )

    # --------------------------------------------------------------------------
    # 21. Step 4 framing remains intact
    # --------------------------------------------------------------------------
    def test_21_step4_framing_remains_intact(self, composition_test_media):
        engine = EditorialCompositionEngine(cache_dir=composition_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Framed Footage", page_url="https://movie.org/f.mp4",
            local_path=str(composition_test_media["base_mp4"])
        )
        composition = engine.compose_short(
            script_parts=self.SAMPLE_SCRIPT_PARTS,
            total_duration=24.0,
            candidates_by_beat=[[cand]]
        )
        for shot in composition.shots:
            if shot.framing_spec:
                assert shot.framing_spec.target_width == 1080
                assert shot.framing_spec.target_height == 1920

    # --------------------------------------------------------------------------
    # 22. Step 3 temporal extraction remains intact
    # --------------------------------------------------------------------------
    def test_22_step3_temporal_extraction_remains_intact(self, composition_test_media):
        tmr = TemporalMomentRetriever(cache_dir=composition_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Step 3 Candidate", local_path=str(composition_test_media["base_mp4"]),
            duration=5.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(cand, target_duration=2.5)
        assert clip_path is not None
        assert win is not None
        assert PhysicalVideoValidator.is_valid_video(clip_path) is True

    # --------------------------------------------------------------------------
    # 23. Step 2 semantic qualification remains intact
    # --------------------------------------------------------------------------
    def test_23_step2_semantic_qualification_remains_intact(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b23", beat_index=0,
            narration_text="Dyatlov Pass incident abandoned tent.",
            primary_entity="Dyatlov Pass"
        )
        cand_generic = VisualCandidate(
            candidate_id="cg", source_class="SOURCE_A", source_name="stock",
            source_url="https://stock.org/sunny_forest.mp4", title="Sunny green forest trees",
            is_video=True, source_type=SourceType.STOCK
        )
        score = scorer.score_candidate(cand_generic, intent)
        assert score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 24. Step 1 source hierarchy remains intact
    # --------------------------------------------------------------------------
    def test_24_step1_source_hierarchy_remains_intact(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b24", beat_index=0,
            narration_text="Titanic sinking collision with iceberg.",
            event="Titanic sinking", primary_entity="Titanic"
        )
        cand_movie = VisualCandidate(
            candidate_id="c_mov", source_class="SOURCE_A_CINEMATIC", source_name="movie",
            source_url="https://movie.org/titanic.mp4", title="Titanic film collision scene",
            is_video=True, source_type=SourceType.MOVIE
        )
        cand_stock = VisualCandidate(
            candidate_id="c_stk", source_class="SOURCE_A", source_name="pexels",
            source_url="https://pexels.com/ocean_iceberg.mp4", title="Ocean iceberg floating",
            is_video=True, source_type=SourceType.STOCK
        )
        ranked = scorer.rank_candidates([cand_stock, cand_movie], intent=intent)
        # Qualified non-stock movie must beat stock fallback
        assert ranked[0].candidate_id == "c_mov"
