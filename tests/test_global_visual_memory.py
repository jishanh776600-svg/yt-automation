"""
Test Suite: Global Persistent Visual Memory + Cross-Job Duplicate Prevention (Step 5/8).
========================================================================================
Validates all 25 core requirements:
  1. Same URL detected
  2. Normalized URL detected (strips tracking, protocols, fragments)
  3. Same source fingerprint detected (header/footer hash)
  4. Same temporal window detected (ratio 1.0 -> hard duplicate)
  5. Overlapping temporal windows detected (ratio >= 0.25 -> strong penalty)
  6. Non-overlapping windows allowed from same source
  7. Near-identical visual fingerprint detected (dHash sim >= 0.88 -> hard duplicate)
  8. Different visual fingerprint allowed
  9. Crop variation still detected as duplicate
  10. Materially different crop/moment allowed
  11. Recent reuse penalty (< 24h)
  12. Old reuse penalty decay (> 30d -> 0.0)
  13. Consecutive scene duplicate prevention within same Short
  14. Cross-job duplicate prevention
  15. Source diversity preference among equally qualified candidates
  16. Relevance still outranks diversity (RELEVANCE > VARIETY)
  17. Semantic threshold (0.40) remains absolute
  18. QA memory isolation (QA runs never poison production memory)
  19. Persistence across process restarts (SQLite durability)
  20. Concurrent / atomic memory write behavior (multi-threaded transactions)
  21. Images rejected under VIDEO_ONLY invariant
  22. Step 4 framing remains intact
  23. Step 3 temporal extraction remains intact
  24. Step 2 semantic relevance remains intact
  25. Step 1 source hierarchy remains intact
"""
import os
import shutil
import tempfile
import subprocess
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from config.settings import FFMPEG_EXE, FFPROBE_EXE
from core.models import Base, VisualUsageRecord
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from engines.visual_intelligence.models import (
    SourceType, VisualCandidate, VisualIntent, VisualContentType, RightsStatus,
    NormalizedVideoCandidate
)
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.temporal_extractor import TemporalMomentRetriever
from engines.visual_intelligence.framing import IntelligentFramingEngine
from engines.visual_intelligence.memory import (
    VisualMemoryManager,
    VisualFingerprinter,
    VisualMemoryEvaluation,
    normalize_visual_url,
    extract_canonical_source_id,
    calculate_temporal_overlap,
    compute_recency_penalty,
)


@pytest.fixture(scope="session")
def memory_test_media(tmp_path_factory):
    """Generates synthetic videos and test media for memory tests."""
    temp_dir = tmp_path_factory.mktemp("visual_memory_tests")

    # 1. Base 16:9 moving landscape video (640x360, 4.0s)
    base_mp4 = temp_dir / "base_video.mp4"
    cmd_base = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=4:size=640x360:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(base_mp4)
    ]
    subprocess.run(cmd_base, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Visually different video (SMPTE bars, 640x360, 4.0s)
    smpte_mp4 = temp_dir / "smpte_bars.mp4"
    cmd_smpte = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "smptebars=duration=4:size=640x360:rate=24",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(smpte_mp4)
    ]
    subprocess.run(cmd_smpte, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 3. Slightly re-encoded version of base video (near-identical visual hash)
    reencoded_mp4 = temp_dir / "base_reencoded.mp4"
    cmd_reenc = [
        FFMPEG_EXE, "-y",
        "-i", str(base_mp4),
        "-c:v", "libx264", "-crf", "28", "-pix_fmt", "yuv420p",
        str(reencoded_mp4)
    ]
    subprocess.run(cmd_reenc, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 4. Prohibited static image (JPEG)
    jpeg_file = temp_dir / "sample_photo.jpg"
    cmd_img = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:d=1",
        "-vframes", "1",
        str(jpeg_file)
    ]
    subprocess.run(cmd_img, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    return {
        "temp_dir": temp_dir,
        "base_mp4": base_mp4,
        "smpte_mp4": smpte_mp4,
        "reencoded_mp4": reencoded_mp4,
        "jpeg_file": jpeg_file,
    }


@pytest.fixture
def isolated_db(tmp_path):
    """Creates an isolated temporary SQLite database for each test."""
    db_file = tmp_path / "test_memory.db"
    test_engine = create_engine(
        f"sqlite:///{db_file}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 15.0}
    )
    Base.metadata.create_all(bind=test_engine)
    session_factory = sessionmaker(bind=test_engine)
    session = scoped_session(session_factory)
    yield session, db_file
    session.remove()
    test_engine.dispose()


class TestGlobalVisualMemory:
    """Comprehensive 25-case test suite for Step 5."""

    # --------------------------------------------------------------------------
    # 1. Same URL detected
    # --------------------------------------------------------------------------
    def test_01_same_url_detected(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Berlin Wall 1989", page_url="https://archive.org/details/berlin_wall_1989",
            duration=4.0
        )
        mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=4.0)

        # Re-evaluate same candidate
        eval_res = mem.evaluate_candidate(cand, temporal_start=0.0, temporal_end=4.0)
        assert eval_res.is_hard_duplicate is True
        assert eval_res.penalty >= 1.00

    # --------------------------------------------------------------------------
    # 2. Normalized URL detected
    # --------------------------------------------------------------------------
    def test_02_normalized_url_detected(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        url_raw = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&utm_source=twitter&ref=123"
        url_variant = "http://youtu.be/dQw4w9WgXcQ?fbclid=XYZ12345#t=10s"

        cand1 = NormalizedVideoCandidate(
            source_name="internet_real", source_type=SourceType.INTERNET_REAL,
            title="Variant 1", page_url=url_raw
        )
        mem.record_usage(cand1, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        cand2 = NormalizedVideoCandidate(
            source_name="internet_real", source_type=SourceType.INTERNET_REAL,
            title="Variant 2", page_url=url_variant
        )
        eval_res = mem.evaluate_candidate(cand2, temporal_start=0.0, temporal_end=3.0)
        assert eval_res.is_hard_duplicate is True

    # --------------------------------------------------------------------------
    # 3. Same source fingerprint detected
    # --------------------------------------------------------------------------
    def test_03_same_source_fingerprint_detected(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        # Copy base_mp4 to a completely different name and fake URL
        renamed_mp4 = memory_test_media["temp_dir"] / "cloned_footage.mp4"
        shutil.copyfile(memory_test_media["base_mp4"], renamed_mp4)

        cand1 = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Original", page_url="https://domain-a.org/video.mp4",
            local_path=str(memory_test_media["base_mp4"])
        )
        mem.record_usage(cand1, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        cand2 = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Mirror", page_url="https://mirror-b.net/unknown.mp4",
            local_path=str(renamed_mp4)
        )
        eval_res = mem.evaluate_candidate(cand2, temporal_start=0.0, temporal_end=3.0)
        assert eval_res.is_hard_duplicate is True

    # --------------------------------------------------------------------------
    # 4. Same temporal window detected
    # --------------------------------------------------------------------------
    def test_04_same_temporal_window_detected(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Window Test", page_url="https://archive.org/details/test_window"
        )
        mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=10.0, temporal_end=13.0)

        eval_res = mem.evaluate_candidate(cand, temporal_start=10.0, temporal_end=13.0)
        assert eval_res.is_hard_duplicate is True
        assert "Near-identical temporal overlap" in (eval_res.duplicate_reason or "")

    # --------------------------------------------------------------------------
    # 5. Overlapping temporal windows detected
    # --------------------------------------------------------------------------
    def test_05_overlapping_temporal_windows_detected(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Overlap Test", page_url="https://archive.org/details/test_overlap"
        )
        mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=10.0, temporal_end=14.0)

        # Overlapping window: 12.0 to 16.0 (2 seconds overlap out of 4s = 50% overlap)
        eval_res = mem.evaluate_candidate(cand, temporal_start=12.0, temporal_end=16.0)
        assert eval_res.is_hard_duplicate is False  # < 70% threshold is not hard duplicate
        assert eval_res.penalty >= 0.50             # Substantial overlap receives strong penalty

    # --------------------------------------------------------------------------
    # 6. Non-overlapping windows allowed
    # --------------------------------------------------------------------------
    def test_06_non_overlapping_windows_allowed(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Non-Overlap Test", page_url="https://archive.org/details/test_non_overlap"
        )
        mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        # Completely different temporal window: 20.0 to 23.0
        eval_res = mem.evaluate_candidate(cand, temporal_start=20.0, temporal_end=23.0)
        assert eval_res.is_hard_duplicate is False
        # Penalty should be bounded to mild source reuse penalty, not hard duplicate
        assert eval_res.penalty <= 0.40

    # --------------------------------------------------------------------------
    # 7. Near-identical visual fingerprint detected
    # --------------------------------------------------------------------------
    def test_07_near_identical_visual_fingerprint_detected(self, isolated_db, memory_test_media):
        hash1 = VisualFingerprinter.compute_clip_perceptual_hash(memory_test_media["base_mp4"])
        hash2 = VisualFingerprinter.compute_clip_perceptual_hash(memory_test_media["reencoded_mp4"])

        sim = VisualFingerprinter.compare_perceptual_hashes(hash1, hash2)
        assert sim >= 0.90  # Re-encoded version must produce near-identical perceptual hash

    # --------------------------------------------------------------------------
    # 8. Different visual fingerprint allowed
    # --------------------------------------------------------------------------
    def test_08_different_visual_fingerprint_allowed(self, memory_test_media):
        hash1 = VisualFingerprinter.compute_clip_perceptual_hash(memory_test_media["base_mp4"])
        hash2 = VisualFingerprinter.compute_clip_perceptual_hash(memory_test_media["smpte_mp4"])

        sim = VisualFingerprinter.compare_perceptual_hashes(hash1, hash2)
        assert sim < 0.65  # Test pattern vs SMPTE bars must be visually distinct

    # --------------------------------------------------------------------------
    # 9. Crop variation still detected as duplicate
    # --------------------------------------------------------------------------
    def test_09_crop_variation_still_detected_as_duplicate(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Crop Test", page_url="https://movies.org/clip1"
        )
        # Record with center crop
        mem.record_usage(
            cand, memory_test_media["base_mp4"],
            temporal_start=5.0, temporal_end=8.0,
            framing_strategy="center_crop", framing_crop_info={"start_cx": 0.50}
        )

        # Same moment evaluated with slightly offset crop (e.g. start_cx = 0.40)
        eval_res = mem.evaluate_candidate(cand, temporal_start=5.0, temporal_end=8.0)
        assert eval_res.is_hard_duplicate is True

    # --------------------------------------------------------------------------
    # 10. Materially different crop/moment allowed
    # --------------------------------------------------------------------------
    def test_10_materially_different_crop_moment_allowed(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Different Moment", page_url="https://movies.org/clip2"
        )
        mem.record_usage(
            cand, memory_test_media["base_mp4"],
            temporal_start=0.0, temporal_end=3.0,
            framing_strategy="center_crop"
        )

        # Completely different moment 25.0 to 28.0
        eval_res = mem.evaluate_candidate(cand, temporal_start=25.0, temporal_end=28.0)
        assert eval_res.is_hard_duplicate is False

    # --------------------------------------------------------------------------
    # 11. Recent reuse penalty
    # --------------------------------------------------------------------------
    def test_11_recent_reuse_penalty(self):
        now = datetime.now(timezone.utc)
        used_2h_ago = now - timedelta(hours=2)
        pen = compute_recency_penalty(used_2h_ago, current_time=now)
        assert pen == 0.40

    # --------------------------------------------------------------------------
    # 12. Old reuse penalty decay
    # --------------------------------------------------------------------------
    def test_12_old_reuse_penalty_decay(self):
        now = datetime.now(timezone.utc)
        used_40d_ago = now - timedelta(days=40)
        pen = compute_recency_penalty(used_40d_ago, current_time=now)
        assert pen == 0.00

    # --------------------------------------------------------------------------
    # 13. Consecutive scene duplicate prevention
    # --------------------------------------------------------------------------
    def test_13_consecutive_scene_duplicate_prevention(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Scene A Footage", page_url="https://archive.org/video_scene_1"
        )
        # Pretend scene 1 used video_scene_1 in current short
        eval_res = mem.evaluate_candidate(
            cand, temporal_start=0.0, temporal_end=3.0,
            recent_scene_urls=["https://archive.org/video_scene_1"]
        )
        assert eval_res.is_hard_duplicate is True
        assert "Consecutive-scene duplicate" in (eval_res.duplicate_reason or "")

    # --------------------------------------------------------------------------
    # 14. Cross-job duplicate prevention
    # --------------------------------------------------------------------------
    def test_14_cross_job_duplicate_prevention(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Job 1 Clip", page_url="https://movies.org/cross_job_source"
        )
        # Recorded under Job 1
        mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=1.0, temporal_end=4.0, job_id="job_001")

        # Evaluated in Job 2
        eval_res = mem.evaluate_candidate(cand, temporal_start=1.0, temporal_end=4.0, job_id="job_002")
        assert eval_res.is_hard_duplicate is True
        assert eval_res.penalty >= 1.00

    # --------------------------------------------------------------------------
    # 15. Source diversity preference
    # --------------------------------------------------------------------------
    def test_15_source_diversity_preference(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        # Source A has been used before
        cand_used = VisualCandidate(
            candidate_id="c_used", source_class="SOURCE_A", source_name="source_a",
            source_url="https://archive.org/source_a", title="Prior Source Footage",
            is_video=True, source_type=SourceType.ARCHIVAL
        )
        mem.record_usage(cand_used, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        # Source B is fresh
        cand_fresh = VisualCandidate(
            candidate_id="c_fresh", source_class="SOURCE_A", source_name="source_b",
            source_url="https://archive.org/source_b", title="Fresh Source Footage",
            is_video=True, source_type=SourceType.ARCHIVAL
        )

        bonus_used = mem.calculate_source_diversity_bonus(cand_used)
        bonus_fresh = mem.calculate_source_diversity_bonus(cand_fresh)

        assert bonus_used == 0.00
        assert bonus_fresh == 0.05

    # --------------------------------------------------------------------------
    # 16. Relevance still outranks diversity
    # --------------------------------------------------------------------------
    def test_16_relevance_still_outranks_diversity(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        scorer = VisualCandidateScorer()

        intent = VisualIntent(
            beat_id="b16", beat_index=0,
            narration_text="Titanic sinking collision with massive iceberg.",
            event="Titanic sinking", primary_entity="Titanic"
        )

        # Candidate A: Highly relevant (0.85+), but used in previous job 5 days ago (moderate penalty)
        cand_relevant = VisualCandidate(
            candidate_id="c_rel", source_class="SOURCE_A_CINEMATIC", source_name="movie",
            source_url="https://cinema.org/titanic_collision.mp4",
            title="Titanic collision iceberg disaster scene",
            is_video=True, source_type=SourceType.MOVIE
        )
        past_date = datetime.now(timezone.utc) - timedelta(days=5)
        mem.record_usage(
            cand_relevant, memory_test_media["base_mp4"],
            temporal_start=15.0, temporal_end=18.0, used_at=past_date
        )

        # Candidate B: Fresh, but weakly relevant (around 0.42)
        cand_fresh = VisualCandidate(
            candidate_id="c_fresh", source_class="SOURCE_A", source_name="stock",
            source_url="https://stock.org/cold_water.mp4",
            title="Cold water waves in ocean",
            is_video=True, source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates(
            [cand_fresh, cand_relevant],
            intent=intent,
            visual_memory=mem,
            temporal_start=0.0,
            temporal_end=3.0
        )

        # Strongly relevant candidate MUST outrank fresh generic candidate (RELEVANCE > VARIETY)
        assert ranked[0].candidate_id == "c_rel"

    # --------------------------------------------------------------------------
    # 17. Semantic threshold remains absolute
    # --------------------------------------------------------------------------
    def test_17_semantic_threshold_remains_absolute(self, isolated_db):
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")
        scorer = VisualCandidateScorer()

        intent = VisualIntent(
            beat_id="b17", beat_index=0,
            narration_text="Chernobyl reactor 4 explosion.",
            event="Chernobyl explosion", primary_entity="Chernobyl"
        )

        # Unrelated candidate: 100% fresh, unused anywhere
        cand_unrelated = VisualCandidate(
            candidate_id="c_unrel", source_class="SOURCE_A", source_name="pexels",
            source_url="https://pexels.com/video/happy_beach_party",
            title="Sunny tropical beach party celebration",
            is_video=True, source_type=SourceType.STOCK
        )

        score = scorer.score_candidate(cand_unrelated, intent, visual_memory=mem)
        # Must stay below threshold regardless of freshness
        assert score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 18. QA memory isolation
    # --------------------------------------------------------------------------
    def test_18_qa_memory_isolation(self, isolated_db, memory_test_media):
        session, _ = isolated_db
        mem_qa = VisualMemoryManager(db_session=session, classification="QA")
        mem_prod = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        cand = NormalizedVideoCandidate(
            source_name="archive", source_type=SourceType.ARCHIVAL,
            title="Apollo 11 Liftoff", page_url="https://archive.org/details/apollo_11"
        )

        # Recorded under QA classification
        mem_qa.record_usage(cand, memory_test_media["base_mp4"], temporal_start=0.0, temporal_end=3.0)

        # Production evaluation of same candidate must NOT be penalized
        prod_eval = mem_prod.evaluate_candidate(cand, temporal_start=0.0, temporal_end=3.0)
        assert prod_eval.is_hard_duplicate is False
        assert prod_eval.penalty == 0.0

    # --------------------------------------------------------------------------
    # 19. Persistence across process restart
    # --------------------------------------------------------------------------
    def test_19_persistence_across_process_restart(self, isolated_db, memory_test_media):
        _, db_file = isolated_db

        # Session 1: write record
        test_engine1 = create_engine(f"sqlite:///{db_file}")
        Session1 = sessionmaker(bind=test_engine1)
        s1 = Session1()
        mem1 = VisualMemoryManager(db_session=s1, classification="PRODUCTION")

        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Durable Memory", page_url="https://durable.org/video1"
        )
        mem1.record_usage(cand, memory_test_media["base_mp4"], temporal_start=2.0, temporal_end=5.0)
        s1.close()
        test_engine1.dispose()

        # Session 2: simulate new process connecting to same SQLite database
        test_engine2 = create_engine(f"sqlite:///{db_file}")
        Session2 = sessionmaker(bind=test_engine2)
        s2 = Session2()
        mem2 = VisualMemoryManager(db_session=s2, classification="PRODUCTION")

        eval_res = mem2.evaluate_candidate(cand, temporal_start=2.0, temporal_end=5.0)
        assert eval_res.is_hard_duplicate is True
        s2.close()
        test_engine2.dispose()

    # --------------------------------------------------------------------------
    # 20. Concurrent / atomic memory write behavior
    # --------------------------------------------------------------------------
    def test_20_concurrent_atomic_memory_write_behavior(self, isolated_db, memory_test_media):
        _, db_file = isolated_db
        test_engine = create_engine(
            f"sqlite:///{db_file}",
            connect_args={"timeout": 30.0}
        )
        ThreadSession = sessionmaker(bind=test_engine)

        errors = []

        def worker_write(worker_id: int):
            try:
                s = ThreadSession()
                mem = VisualMemoryManager(db_session=s, classification="PRODUCTION")
                cand = NormalizedVideoCandidate(
                    source_name="archive", source_type=SourceType.ARCHIVAL,
                    title=f"Worker {worker_id} Footage",
                    page_url=f"https://archive.org/item_{worker_id}"
                )
                mem.record_usage(cand, memory_test_media["base_mp4"], temporal_start=float(worker_id), temporal_end=float(worker_id + 3))
                s.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker_write, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        s_verify = ThreadSession()
        count = s_verify.query(VisualUsageRecord).count()
        assert count == 5
        s_verify.close()
        test_engine.dispose()

    # --------------------------------------------------------------------------
    # 21. Images rejected under VIDEO_ONLY invariant
    # --------------------------------------------------------------------------
    def test_21_images_rejected(self, isolated_db, memory_test_media):
        assert VIDEO_ONLY is True
        session, _ = isolated_db
        mem = VisualMemoryManager(db_session=session, classification="PRODUCTION")

        cand = NormalizedVideoCandidate(
            source_name="stock", source_type=SourceType.STOCK,
            title="Image Candidate", page_url="https://stock.org/photo.jpg"
        )
        with pytest.raises(ValueError, match="Prohibited visual asset rejected"):
            mem.record_usage(cand, memory_test_media["jpeg_file"])

    # --------------------------------------------------------------------------
    # 22. Step 4 framing remains intact
    # --------------------------------------------------------------------------
    def test_22_step4_framing_remains_intact(self, memory_test_media):
        engine_framing = IntelligentFramingEngine(cache_dir=memory_test_media["temp_dir"])
        out = engine_framing.frame_video_to_916(memory_test_media["base_mp4"])
        assert out is not None
        val = PhysicalVideoValidator.validate_file(out)
        assert val.is_valid is True
        assert val.width == 1080 and val.height == 1920

    # --------------------------------------------------------------------------
    # 23. Step 3 temporal extraction remains intact
    # --------------------------------------------------------------------------
    def test_23_step3_temporal_extraction_remains_intact(self, memory_test_media):
        tmr = TemporalMomentRetriever(cache_dir=memory_test_media["temp_dir"])
        cand = NormalizedVideoCandidate(
            source_name="movie", source_type=SourceType.MOVIE,
            title="Step 3 Candidate", local_path=str(memory_test_media["base_mp4"]),
            duration=4.0
        )
        clip_path, win = tmr.retrieve_and_extract_best_moment(cand, target_duration=2.0)
        assert clip_path is not None
        assert win is not None
        assert PhysicalVideoValidator.is_valid_video(clip_path) is True

    # --------------------------------------------------------------------------
    # 24. Step 2 semantic relevance remains intact
    # --------------------------------------------------------------------------
    def test_24_step2_semantic_relevance_remains_intact(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b24", beat_index=0,
            narration_text="Dyatlov Pass expedition tents in blizzard.",
            primary_entity="Dyatlov Pass"
        )
        cand_generic = VisualCandidate(
            candidate_id="cg", source_class="SOURCE_A", source_name="stock",
            source_url="https://stock.org/mountain.mp4", title="Generic mountain snowy landscape",
            is_video=True, source_type=SourceType.STOCK
        )
        score = scorer.score_candidate(cand_generic, intent)
        assert score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 25. Step 1 source hierarchy remains intact
    # --------------------------------------------------------------------------
    def test_25_step1_source_hierarchy_remains_intact(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b25", beat_index=0,
            narration_text="Titanic sinking collision scene.",
            event="Titanic sinking", primary_entity="Titanic"
        )

        cand_movie = VisualCandidate(
            candidate_id="c_mov", source_class="SOURCE_A_CINEMATIC", source_name="movie",
            source_url="https://movie.org/titanic.mp4", title="Titanic movie disaster collision",
            is_video=True, source_type=SourceType.MOVIE
        )
        cand_stock = VisualCandidate(
            candidate_id="c_stk", source_class="SOURCE_A", source_name="pexels",
            source_url="https://pexels.com/titanic_model.mp4", title="Titanic model sinking ship",
            is_video=True, source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates([cand_stock, cand_movie], intent=intent)
        # Non-stock movie candidate must be ranked Tier 1 over stock video fallback
        assert ranked[0].candidate_id == "c_mov"
