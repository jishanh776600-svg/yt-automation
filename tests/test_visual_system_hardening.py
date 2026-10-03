"""
Test Suite: Visual System Hardening & Compelling Real Moving Video Selection.
=============================================================================
Verifies all 20 required scenarios:
 1. Pexels candidate accepted when valid.
 2. Pixabay candidate accepted when valid.
 3. Pexels failure falls back correctly to Pixabay.
 4. Multiple candidates are collected for evaluation.
 5. Candidate scoring selects the stronger relevant candidate.
 6. High-motion candidate beats effectively static candidate when relevance is comparable.
 7. Highly relevant candidate beats generic candidate.
 8. High-quality candidate receives appropriate preference (1080p > 720p).
 9. Recent/reused candidate receives an appropriate penalty.
 10. Duplicate candidate is removed / disqualified.
 11. Image candidate is rejected.
 12. Renamed image is rejected by physical validation.
 13. Broken video is rejected.
 14. Zero-duration video is rejected.
 15. Empty provider result triggers fallback.
 16. All-provider failure fails closed.
 17. Scene-specific query requirement works.
 18. Generic one-word visual queries remain rejected.
 19. Existing storyboard schema remains compatible.
 20. Existing VIDEO_ONLY tests continue passing.
"""
import os
import json
import shutil
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from config.settings import FFMPEG_EXE
from core.database import get_db
from core.models import ScriptRecord, AssetRecord
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from engines.asset_fetcher import AssetFetcher
from engines.storyboard_engine import StoryboardEngine
from engines.visual_intelligence.models import VisualCandidate, VisualIntent, VisualContentType, RightsStatus
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.sources.pexels_adapter import PexelsAdapter
from engines.visual_intelligence.sources.pixabay_adapter import PixabayAdapter
from engines.visual_intelligence.source_router import SourceRouter


@pytest.fixture(scope="module")
def media_fixtures():
    """Generates small, deterministic test media files using FFmpeg and PIL."""
    td = tempfile.mkdtemp(prefix="visual_hardening_tests_")
    dir_path = Path(td)

    # 1. Valid MP4 (H.264 video stream, 2 seconds)
    mp4_path = dir_path / "valid_sample.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(mp4_path)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. JPEG image
    jpeg_path = dir_path / "sample.jpg"
    img = Image.new("RGB", (320, 240), color=(180, 50, 50))
    img.save(jpeg_path, "JPEG")

    # 3. Renamed image (.jpg renamed to .mp4)
    renamed_mp4_path = dir_path / "fake_video_renamed.mp4"
    shutil.copyfile(jpeg_path, renamed_mp4_path)

    # 4. Broken video
    broken_mp4_path = dir_path / "broken.mp4"
    with open(broken_mp4_path, "wb") as f:
        f.write(b"corrupt video stream bytes not a valid video file")

    # 5. Zero-duration / empty video
    zero_dur_path = dir_path / "zero_dur.mp4"
    with open(zero_dur_path, "wb") as f:
        f.write(b"")

    yield {
        "mp4": mp4_path,
        "jpeg": jpeg_path,
        "renamed_mp4": renamed_mp4_path,
        "broken_mp4": broken_mp4_path,
        "zero_dur": zero_dur_path,
    }

    shutil.rmtree(td, ignore_errors=True)


class TestVisualSystemHardening:

    # --------------------------------------------------------------------------
    # 1. Pexels candidate accepted when valid
    # --------------------------------------------------------------------------
    def test_01_pexels_candidate_accepted_when_valid(self, media_fixtures):
        fetcher = AssetFetcher()
        db = next(get_db())
        mock_pexels_meta = {
            "download_url": "https://api.pexels.com/video/download/12345.mp4",
            "quality_tier": "1080p",
            "width": 1080,
            "height": 1920,
            "duration": 4.5,
            "score": 350
        }

        with patch.object(fetcher, "search_pexels_video", return_value=mock_pexels_meta):
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                with open(media_fixtures["mp4"], "rb") as f:
                    valid_bytes = f.read()
                mock_resp.iter_content = lambda chunk_size=65536: [valid_bytes]
                mock_get.return_value = mock_resp

                shot = {"shot_id": "shot_01", "search_query": "medieval soldiers marching"}
                asset = fetcher.fetch_asset_for_shot(db, shot)
                assert asset is not None
                assert asset.source == "pexels_video"
                assert asset.asset_type == "video"
                assert Path(asset.local_path).exists()
                assert PhysicalVideoValidator.is_valid_video(asset.local_path)

    # --------------------------------------------------------------------------
    # 2. Pixabay candidate accepted when valid
    # --------------------------------------------------------------------------
    def test_02_pixabay_candidate_accepted_when_valid(self, media_fixtures):
        fetcher = AssetFetcher()
        db = next(get_db())
        mock_pb_meta = {
            "download_url": "https://pixabay.com/videos/download/pb_999.mp4",
            "quality_tier": "1080p",
            "width": 1080,
            "height": 1920,
            "duration": 5.0,
            "score": 350
        }

        # Pexels returns None, Pixabay returns valid
        with patch.object(fetcher, "search_pexels_video", return_value=None):
            with patch.object(fetcher, "search_pixabay_video", return_value=mock_pb_meta):
                with patch("requests.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 200
                    with open(media_fixtures["mp4"], "rb") as f:
                        valid_bytes = f.read()
                    mock_resp.iter_content = lambda chunk_size=65536: [valid_bytes]
                    mock_get.return_value = mock_resp

                    shot = {"shot_id": "shot_02", "search_query": "passenger ship sailing through violent ocean storm"}
                    asset = fetcher.fetch_asset_for_shot(db, shot)
                    assert asset is not None
                    assert asset.source == "pixabay_video"
                    assert asset.asset_type == "video"
                    assert PhysicalVideoValidator.is_valid_video(asset.local_path)

    # --------------------------------------------------------------------------
    # 3. Pexels failure falls back correctly to Pixabay
    # --------------------------------------------------------------------------
    def test_03_pexels_failure_falls_back_correctly_to_pixabay(self, media_fixtures):
        fetcher = AssetFetcher()
        db = next(get_db())
        mock_pb_meta = {
            "download_url": "https://pixabay.com/videos/download/pb_888.mp4",
            "quality_tier": "720p",
            "width": 720,
            "height": 1280,
            "duration": 4.0,
            "score": 210
        }

        # Pexels search raises exception, Pixabay succeeds
        with patch.object(fetcher, "search_pexels_video", side_effect=Exception("Pexels 500 error")):
            with patch.object(fetcher, "search_pixabay_video", return_value=mock_pb_meta):
                with patch("requests.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 200
                    with open(media_fixtures["mp4"], "rb") as f:
                        valid_bytes = f.read()
                    mock_resp.iter_content = lambda chunk_size=65536: [valid_bytes]
                    mock_get.return_value = mock_resp

                    shot = {"shot_id": "shot_03", "search_query": "steam locomotive emerging through dense smoke"}
                    asset = fetcher.fetch_asset_for_shot(db, shot)
                    assert asset is not None
                    assert asset.source == "pixabay_video"
                    assert PhysicalVideoValidator.is_valid_video(asset.local_path)

    # --------------------------------------------------------------------------
    # 4. Multiple candidates are collected for evaluation
    # --------------------------------------------------------------------------
    def test_04_multiple_candidates_collected(self):
        router = SourceRouter(pexels_api_key="test_key", pixabay_api_key="test_key")
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="Battleships exchanged cannon fire across the North Sea.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
            primary_entity="Battleships",
            event="Naval Battle",
            search_queries=["battleships firing artillery in rough ocean", "naval combat heavy warships"]
        )

        mock_px_cands = [
            VisualCandidate(
                candidate_id="c_px_1",
                source_class="SOURCE_A",
                source_name="pexels",
                source_url="https://pexels.com/v1.mp4",
                title="Battleships firing artillery in rough ocean",
                description="Heavy warship cannon firing in ocean storm",
                content_type=VisualContentType.GENERIC_STOCK_VIDEO,
                rights_status=RightsStatus.LICENSED,
                license_name="Pexels",
                width=1920,
                height=1080,
                duration_sec=4.0,
                is_video=True
            )
        ]
        mock_pb_cands = [
            VisualCandidate(
                candidate_id="c_pb_1",
                source_class="SOURCE_A",
                source_name="pixabay",
                source_url="https://pixabay.com/v2.mp4",
                title="Warships sailing through ocean combat",
                description="Naval combat fleet moving through waves",
                content_type=VisualContentType.GENERIC_STOCK_VIDEO,
                rights_status=RightsStatus.LICENSED,
                license_name="Pixabay",
                width=1080,
                height=1920,
                duration_sec=4.0,
                is_video=True
            )
        ]

        with patch.object(router.adapters["pexels"], "search", return_value=mock_px_cands):
            with patch.object(router.adapters["pixabay"], "search", return_value=mock_pb_cands):
                cands = router.acquire_candidates(intent=intent, count_per_tier=2)
                assert len(cands) >= 2
                sources = {c.source_name for c in cands}
                assert "pexels" in sources
                assert "pixabay" in sources

    # --------------------------------------------------------------------------
    # 5. Candidate scoring selects the stronger relevant candidate
    # --------------------------------------------------------------------------
    def test_05_candidate_scoring_selects_stronger_relevant_candidate(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="Detectives discovered an ancient handwritten manuscript hidden in the library vault.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
            primary_entity="ancient manuscript",
            search_queries=["detective examining mysterious handwritten document"]
        )

        strong_cand = VisualCandidate(
            candidate_id="c_strong",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/manuscript.mp4",
            title="Detective examining ancient handwritten manuscript in archive",
            description="Close up of detective turning pages of mysterious handwritten document",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            entity_tags=["ancient manuscript", "detective"]
        )

        weak_cand = VisualCandidate(
            candidate_id="c_weak",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/generic.mp4",
            title="Generic city street at night",
            description="Cars driving through modern city avenue",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            entity_tags=["city", "street"]
        )

        ranked = scorer.rank_candidates([weak_cand, strong_cand], intent=intent)
        assert ranked[0].candidate_id == "c_strong"
        assert strong_cand.final_score > weak_cand.final_score

    # --------------------------------------------------------------------------
    # 6. High-motion candidate beats effectively static candidate
    # --------------------------------------------------------------------------
    def test_06_high_motion_candidate_beats_static_candidate(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="Infantry marched into the muddy battlefield during the heavy storm.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
            search_queries=["soldiers marching through storm"]
        )

        motion_cand = VisualCandidate(
            candidate_id="c_motion",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/marching.mp4",
            title="Soldiers marching rapidly through heavy storm waves",
            description="Action movement of soldiers marching through muddy battlefield",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            entity_tags=["soldiers", "storm"]
        )

        static_cand = VisualCandidate(
            candidate_id="c_static",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/static.mp4",
            title="Soldiers standing still motionless portrait",
            description="Statue still locked off stationary pose of soldier in rain",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            entity_tags=["soldiers", "storm"]
        )

        scorer.score_candidate(motion_cand, intent)
        scorer.score_candidate(static_cand, intent)
        assert motion_cand.final_score > static_cand.final_score

    # --------------------------------------------------------------------------
    # 7. Highly relevant candidate beats generic candidate
    # --------------------------------------------------------------------------
    def test_07_highly_relevant_candidate_beats_generic(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="The royal sovereign surrendered his golden crown to allied forces.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
            primary_entity="royal sovereign",
            action="surrendered crown"
        )

        specific_cand = VisualCandidate(
            candidate_id="c_specific",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/surrender.mp4",
            title="Royal sovereign surrendered crown ceremony",
            description="Historic crown surrendered to allied military commander",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            entity_tags=["royal sovereign"]
        )

        generic_cand = VisualCandidate(
            candidate_id="c_generic",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/generic_crowd.mp4",
            title="Crowd walking in public plaza",
            description="People gathering in public city square",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True
        )

        scorer.score_candidate(specific_cand, intent)
        scorer.score_candidate(generic_cand, intent)
        assert specific_cand.final_score > generic_cand.final_score

    # --------------------------------------------------------------------------
    # 8. High-quality candidate receives appropriate preference (1080p > 720p)
    # --------------------------------------------------------------------------
    def test_08_high_quality_receives_preference(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="The fleet advanced across open water.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0
        )

        cand_1080p = VisualCandidate(
            candidate_id="c_1080",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/fleet_1080.mp4",
            title="Warships sailing across open water",
            description="Naval ships moving in ocean",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True
        )

        cand_720p = VisualCandidate(
            candidate_id="c_720",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/fleet_720.mp4",
            title="Warships sailing across open water",
            description="Naval ships moving in ocean",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=720,
            height=1280,
            duration_sec=4.0,
            is_video=True
        )

        scorer.score_candidate(cand_1080p, intent)
        scorer.score_candidate(cand_720p, intent)
        assert cand_1080p.final_score > cand_720p.final_score

    # --------------------------------------------------------------------------
    # 9. Recent/reused candidate receives an appropriate penalty
    # --------------------------------------------------------------------------
    def test_09_recent_candidate_receives_penalty(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="Soldiers crossed the river under artillery fire.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0
        )

        cand_fresh = VisualCandidate(
            candidate_id="c_fresh",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/fresh.mp4",
            title="Soldiers crossing river",
            description="Troops wading through water",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True
        )

        cand_reused = VisualCandidate(
            candidate_id="c_reused",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/reused.mp4",
            title="Soldiers crossing river",
            description="Troops wading through water",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True
        )

        recent_usage = {"https://pexels.com/reused.mp4": 3}
        scorer.score_candidate(cand_fresh, intent, recent_usage_counts=recent_usage)
        scorer.score_candidate(cand_reused, intent, recent_usage_counts=recent_usage)
        assert cand_fresh.final_score > cand_reused.final_score

    # --------------------------------------------------------------------------
    # 10. Duplicate candidate is removed / disqualified
    # --------------------------------------------------------------------------
    def test_10_duplicate_candidate_disqualified(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_2",
            beat_index=1,
            narration_text="The captain charted a new course into the storm.",
            start_time=3.0,
            end_time=6.0,
            duration=3.0
        )

        cand = VisualCandidate(
            candidate_id="c_dup",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/already_used_clip.mp4",
            title="Ship captain steering wheel",
            description="Captain navigation during storm",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.LICENSED,
            license_name="Pexels",
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True
        )

        job_used = {"https://pexels.com/already_used_clip.mp4"}
        score = scorer.score_candidate(cand, intent, job_used_urls=job_used)
        assert score < 0.0

    # --------------------------------------------------------------------------
    # 11. Image candidate is rejected
    # --------------------------------------------------------------------------
    def test_11_image_candidate_rejected(self):
        assert PhysicalVideoValidator.is_image_url("https://images.pexels.com/photos/123/image.jpg")
        assert PhysicalVideoValidator.is_image_url("https://upload.wikimedia.org/thumb/file.png")
        assert PhysicalVideoValidator.is_image_url("https://pollinations.ai/prompt/test.webp")

    # --------------------------------------------------------------------------
    # 12. Renamed image is rejected by physical validation
    # --------------------------------------------------------------------------
    def test_12_renamed_image_rejected_by_physical_validation(self, media_fixtures):
        res = PhysicalVideoValidator.validate_file(media_fixtures["renamed_mp4"])
        assert not res.is_valid
        assert "static image payload" in (res.error_message or "").lower()

    # --------------------------------------------------------------------------
    # 13. Broken video is rejected
    # --------------------------------------------------------------------------
    def test_13_broken_video_rejected(self, media_fixtures):
        res = PhysicalVideoValidator.validate_file(media_fixtures["broken_mp4"])
        assert not res.is_valid

    # --------------------------------------------------------------------------
    # 14. Zero-duration video is rejected
    # --------------------------------------------------------------------------
    def test_14_zero_duration_video_rejected(self, media_fixtures):
        res = PhysicalVideoValidator.validate_file(media_fixtures["zero_dur"])
        assert not res.is_valid

    # --------------------------------------------------------------------------
    # 15. Empty provider result triggers fallback
    # --------------------------------------------------------------------------
    def test_15_empty_provider_result_triggers_fallback(self, media_fixtures):
        fetcher = AssetFetcher()
        db = next(get_db())
        mock_pb = {
            "download_url": "https://pixabay.com/v_fallback.mp4",
            "quality_tier": "1080p",
            "width": 1080,
            "height": 1920,
            "duration": 4.0,
            "score": 300
        }

        # Pexels returns None, Pixabay fallback provides asset
        with patch.object(fetcher, "search_pexels_video", return_value=None):
            with patch.object(fetcher, "search_pixabay_video", return_value=mock_pb):
                with patch("requests.get") as mock_get:
                    mock_resp = MagicMock()
                    mock_resp.status_code = 200
                    with open(media_fixtures["mp4"], "rb") as f:
                        valid_bytes = f.read()
                    mock_resp.iter_content = lambda chunk_size=65536: [valid_bytes]
                    mock_get.return_value = mock_resp

                    shot = {"shot_id": "shot_fb", "search_query": "detective examining mysterious handwritten document"}
                    asset = fetcher.fetch_asset_for_shot(db, shot)
                    assert asset is not None
                    assert asset.source == "pixabay_video"

    # --------------------------------------------------------------------------
    # 16. All-provider failure fails closed
    # --------------------------------------------------------------------------
    def test_16_all_provider_failure_fails_closed(self):
        fetcher = AssetFetcher()
        db = next(get_db())

        with patch.object(fetcher, "search_pexels_video", return_value=None):
            with patch.object(fetcher, "search_pixabay_video", return_value=None):
                with patch.object(fetcher, "search_wikimedia_commons", return_value=None):
                    with patch("pathlib.Path.glob", return_value=[]):
                        shot = {"shot_id": "shot_fail", "search_query": "completely unobtainable visual scene"}
                        with pytest.raises(RuntimeError) as exc_info:
                            fetcher.fetch_asset_for_shot(db, shot)
                        assert "VIDEO_ONLY policy" in str(exc_info.value)

    # --------------------------------------------------------------------------
    # 17. Scene-specific query requirement works
    # --------------------------------------------------------------------------
    def test_17_scene_specific_query_requirement_works(self):
        engine = StoryboardEngine()
        valid_scene = {
            "shot_id": "shot_ok",
            "search_query": "medieval soldiers marching through muddy battlefield",
            "asset_type": "video",
            "start_time": 0.0,
            "end_time": 3.0
        }
        assert engine.validate_storyboard_scene(valid_scene) is True

    # --------------------------------------------------------------------------
    # 18. Generic one-word visual queries remain rejected
    # --------------------------------------------------------------------------
    def test_18_generic_one_word_queries_rejected(self):
        engine = StoryboardEngine()
        for bad_query in ["war", "soldier", "ship", "city", "mystery", "history"]:
            bad_scene = {
                "shot_id": "shot_bad",
                "search_query": bad_query,
                "asset_type": "video",
                "start_time": 0.0,
                "end_time": 3.0
            }
            with pytest.raises(ValueError):
                engine.validate_storyboard_scene(bad_scene)

    # --------------------------------------------------------------------------
    # 19. Existing storyboard schema remains compatible
    # --------------------------------------------------------------------------
    def test_19_existing_storyboard_schema_compatible(self):
        engine = StoryboardEngine()
        script = ScriptRecord(
            id="scr_compat_test",
            topic_id="top_test",
            hook="One cannon shot ended an entire European war.",
            context="Warships advanced under full sail to break a harbor blockade.",
            escalation="Defending soldiers aimed and fired a single warning blast.",
            reveal="The cannonball struck only an ordinary brass soup kettle.",
            loop_twist="Commanders surrendered before any soldiers died on either side.",
            estimated_duration_sec=22.5
        )
        shots = engine.create_storyboard(script)
        assert len(shots) >= 8
        required_keys = {"shot_id", "shot_index", "start_time", "end_time", "duration", "search_query", "asset_type"}
        for s in shots:
            assert required_keys.issubset(s.keys())
            assert s["asset_type"] == "video"
            assert len(s["search_query"].split()) >= 2

    # --------------------------------------------------------------------------
    # 20. Existing VIDEO_ONLY tests continue passing
    # --------------------------------------------------------------------------
    def test_20_video_only_invariant_preserved(self):
        assert VIDEO_ONLY is True
        fetcher = AssetFetcher()
        assert fetcher.search_pexels_photo(MagicMock(), "test") is None
        assert fetcher.generate_ai_image("test", Path("test.jpg")) is False
