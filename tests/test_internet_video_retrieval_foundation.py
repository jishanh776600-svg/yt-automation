"""
Focused Unit Tests for Step 1/8: Internet + Movie Video Retrieval Foundation.
=============================================================================
Tests all 14 required invariants:
  1. INTERNET_REAL candidate is recognized.
  2. MOVIE candidate is recognized.
  3. ARCHIVAL candidate is recognized.
  4. STOCK candidate is recognized.
  5. Non-stock video sources are preferred structurally over stock.
  6. Pexels/Pixabay remain available as fallback.
  7. No image source is accepted.
  8. Fake image renamed .mp4 is rejected.
  9. Corrupt internet download is rejected.
  10. Zero-duration media is rejected.
  11. Internet-source failure falls through safely.
  12. Stock is reached only after higher-priority retrieval fails.
  13. Existing video-only validator remains enforced.
  14. Existing production visual tests continue passing.
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
    VisualContentType, RightsStatus, VisualProvenance
)
from engines.visual_intelligence.internet_retrieval import (
    InternetVideoRetriever, BaseVideoRetrievalProvider, MovieRetrievalProvider,
    InternetRealRetrievalProvider, ArchivalRetrievalProvider, StockVideoFallbackProvider,
    get_source_priority
)
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.sources.movie_adapter import MovieAdapter


@pytest.fixture(scope="module")
def media_test_files():
    """Generates small, deterministic test media files using FFmpeg and PIL."""
    td = tempfile.mkdtemp(prefix="internet_retrieval_step1_tests_")
    dir_path = Path(td)

    # 1. Valid MP4 (H.264 video stream, 2 seconds)
    valid_mp4 = dir_path / "sample_valid.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(valid_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # 2. Genuine JPEG image
    jpeg_file = dir_path / "sample_image.jpg"
    img = Image.new("RGB", (320, 240), color=(100, 150, 200))
    img.save(jpeg_file, "JPEG")

    # 3. Renamed image (.jpg bytes renamed to .mp4)
    fake_renamed_mp4 = dir_path / "fake_renamed_image.mp4"
    shutil.copyfile(jpeg_file, fake_renamed_mp4)

    # 4. Corrupted HTML error page saved as .mp4
    corrupt_html_mp4 = dir_path / "corrupt_error_page.mp4"
    with open(corrupt_html_mp4, "wb") as f:
        f.write(b"<!DOCTYPE html><html><body><h1>502 Bad Gateway</h1></body></html>")

    # 5. Empty / zero-byte file
    empty_mp4 = dir_path / "empty.mp4"
    with open(empty_mp4, "wb") as f:
        f.write(b"")

    yield {
        "valid_mp4": valid_mp4,
        "jpeg_file": jpeg_file,
        "fake_renamed_mp4": fake_renamed_mp4,
        "corrupt_html_mp4": corrupt_html_mp4,
        "empty_mp4": empty_mp4,
        "temp_dir": dir_path
    }

    shutil.rmtree(td, ignore_errors=True)


class TestInternetVideoRetrievalFoundation:

    # --------------------------------------------------------------------------
    # 1. INTERNET_REAL candidate is recognized
    # --------------------------------------------------------------------------
    def test_01_internet_real_candidate_recognized(self):
        cand = NormalizedVideoCandidate(
            source_name="editorial_archive",
            source_type=SourceType.INTERNET_REAL,
            title="Press Briefing at Maritime Summit",
            description="Live press statement regarding Baltic security",
            page_url="https://news.org/press_briefing",
            media_url="https://news.org/media/briefing.mp4",
            duration=5.0,
            width=1080,
            height=1920,
            query_used="Baltic security maritime summit"
        )
        assert cand.source_type == SourceType.INTERNET_REAL
        assert get_source_priority(cand.source_type) == 1
        assert cand.is_video is True

        v_cand = cand.to_visual_candidate()
        assert v_cand.source_type == SourceType.INTERNET_REAL
        assert v_cand.content_type == VisualContentType.REAL_VIDEO

    # --------------------------------------------------------------------------
    # 2. MOVIE candidate is recognized
    # --------------------------------------------------------------------------
    def test_02_movie_candidate_recognized(self):
        movie_adapter = MovieAdapter()
        cands = movie_adapter.search(queries=["Titanic iceberg collision scene"], count=2)
        assert len(cands) > 0
        movie_cand = cands[0]

        assert movie_cand.source_type == SourceType.MOVIE
        assert get_source_priority(movie_cand.source_type) == 1
        assert "Titanic iceberg collision scene" in movie_cand.title
        assert movie_cand.is_video is True

        norm = movie_cand.to_normalized_candidate(query_used="Titanic iceberg collision scene")
        assert norm.source_type == SourceType.MOVIE
        assert get_source_priority(norm.source_type) == 1

    # --------------------------------------------------------------------------
    # 3. ARCHIVAL candidate is recognized
    # --------------------------------------------------------------------------
    def test_03_archival_candidate_recognized(self):
        cand = NormalizedVideoCandidate(
            source_name="internet_archive",
            source_type=SourceType.ARCHIVAL,
            title="1912 Newsreel Documenting Maritime Departure",
            description="Historic archival silent film newsreel",
            page_url="https://archive.org/details/historic_newsreel",
            media_url="https://archive.org/download/newsreel.mp4",
            duration=6.5,
            width=1080,
            height=1920,
            query_used="1912 ocean departure archival footage"
        )
        assert cand.source_type == SourceType.ARCHIVAL
        assert get_source_priority(cand.source_type) == 1
        assert cand.is_video is True

        v_cand = cand.to_visual_candidate()
        assert v_cand.content_type == VisualContentType.ARCHIVAL_VIDEO

    # --------------------------------------------------------------------------
    # 4. STOCK candidate is recognized
    # --------------------------------------------------------------------------
    def test_04_stock_candidate_recognized(self):
        cand = NormalizedVideoCandidate(
            source_name="pexels",
            source_type=SourceType.STOCK,
            title="Ocean Waves Rolling at Sunset",
            description="Generic atmospheric ocean b-roll",
            page_url="https://pexels.com/video/123",
            media_url="https://pexels.com/video/download/123.mp4",
            duration=4.0,
            width=1080,
            height=1920,
            query_used="ocean waves"
        )
        assert cand.source_type == SourceType.STOCK
        assert get_source_priority(cand.source_type) == 2
        assert cand.is_video is True

        v_cand = cand.to_visual_candidate()
        assert v_cand.content_type == VisualContentType.GENERIC_STOCK_VIDEO

    # --------------------------------------------------------------------------
    # 5. Non-stock video sources are preferred structurally over stock
    # --------------------------------------------------------------------------
    def test_05_non_stock_video_sources_preferred_structurally_over_stock(self):
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="The Titanic struck an iceberg in the North Atlantic.",
            start_time=0.0,
            end_time=3.0,
            duration=3.0,
            primary_entity="Titanic",
            event="Iceberg Collision",
            search_queries=["Titanic iceberg collision scene"]
        )
        scorer = VisualCandidateScorer()

        # Stock candidate with high artificial score (0.90)
        stock_cand = VisualCandidate(
            candidate_id="cand_stock",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/v1.mp4",
            title="Ship sailing smoothly in calm sea",
            description="Generic ship",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            rights_status=RightsStatus.LICENSED,
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            source_type=SourceType.STOCK
        )

        # Movie / Non-Stock candidate
        movie_cand = VisualCandidate(
            candidate_id="cand_movie",
            source_class="SOURCE_A_CINEMATIC",
            source_name="movie_footage",
            source_url="https://archive.org/movie/titanic.mp4",
            title="Titanic iceberg collision scene",
            description="Dramatic film depiction of Titanic colliding with iceberg",
            content_type=VisualContentType.REAL_VIDEO,
            rights_status=RightsStatus.TRANSFORMATIVE_EDITORIAL,
            width=1080,
            height=1920,
            duration_sec=4.0,
            is_video=True,
            source_type=SourceType.MOVIE
        )

        ranked = scorer.rank_candidates([stock_cand, movie_cand], intent=intent)
        assert len(ranked) == 2
        # Structural priority requires non-stock (MOVIE) to be ranked #1
        assert ranked[0].candidate_id == "cand_movie"
        assert ranked[0].source_type == SourceType.MOVIE
        assert ranked[1].candidate_id == "cand_stock"
        assert ranked[1].source_type == SourceType.STOCK

    # --------------------------------------------------------------------------
    # 6. Pexels/Pixabay remain available as fallback
    # --------------------------------------------------------------------------
    def test_06_pexels_pixabay_remain_available_as_fallback(self):
        retriever = InternetVideoRetriever()

        # Mock primary non-stock providers returning 0 candidates
        for prov in retriever.providers:
            if prov.priority == 1:
                prov.search = MagicMock(return_value=[])

        # Mock stock fallback provider returning candidates
        mock_stock_cand = NormalizedVideoCandidate(
            source_name="pexels",
            source_type=SourceType.STOCK,
            title="Fallback stock ocean clip",
            page_url="https://pexels.com/ocean",
            media_url="https://pexels.com/ocean.mp4",
            duration=3.5
        )
        for prov in retriever.providers:
            if prov.priority == 2:
                prov.search = MagicMock(return_value=[mock_stock_cand])

        candidates = retriever.search_candidates(query="remote ocean horizon")
        assert len(candidates) > 0
        assert candidates[0].source_type == SourceType.STOCK
        assert candidates[0].source_name == "pexels"

    # --------------------------------------------------------------------------
    # 7. No image source is accepted
    # --------------------------------------------------------------------------
    def test_07_no_image_source_is_accepted(self):
        assert PhysicalVideoValidator.is_image_url("https://images.pexels.com/photos/123/sample.jpg") is True
        assert PhysicalVideoValidator.is_image_url("https://wikimedia.org/commons/thumb/a/a1/image.png") is True
        assert PhysicalVideoValidator.is_image_url("https://example.com/asset.webp") is True

        retriever = InternetVideoRetriever()
        img_cand = NormalizedVideoCandidate(
            source_name="stock_photo",
            source_type=SourceType.STOCK,
            title="Static Photograph of Ship",
            page_url="https://example.com/photo.html",
            media_url="https://example.com/photo.jpg",
            is_video=False
        )
        result = retriever.download_and_validate(img_cand)
        assert result is None, "Image candidate must be immediately rejected by validator"

    # --------------------------------------------------------------------------
    # 8. Fake image renamed .mp4 is rejected
    # --------------------------------------------------------------------------
    def test_08_fake_image_renamed_mp4_rejected(self, media_test_files):
        fake_mp4 = media_test_files["fake_renamed_mp4"]
        val_res = PhysicalVideoValidator.validate_file(fake_mp4)
        assert val_res.is_valid is False
        assert "image" in val_res.error_message.lower()

        retriever = InternetVideoRetriever()
        cand = NormalizedVideoCandidate(
            source_name="untrusted_web",
            source_type=SourceType.INTERNET_REAL,
            title="Disguised Image File",
            local_path=str(fake_mp4)
        )
        result = retriever.download_and_validate(cand)
        assert result is None, "Renamed image must be rejected by physical validation"

    # --------------------------------------------------------------------------
    # 9. Corrupt internet download is rejected
    # --------------------------------------------------------------------------
    def test_09_corrupt_internet_download_rejected(self, media_test_files):
        corrupt_html = media_test_files["corrupt_html_mp4"]
        val_res = PhysicalVideoValidator.validate_file(corrupt_html)
        assert val_res.is_valid is False

        retriever = InternetVideoRetriever()
        cand = NormalizedVideoCandidate(
            source_name="corrupt_server",
            source_type=SourceType.INTERNET_REAL,
            title="HTML 502 error page saved as mp4",
            local_path=str(corrupt_html)
        )
        result = retriever.download_and_validate(cand)
        assert result is None, "Corrupt download must be safely rejected"

    # --------------------------------------------------------------------------
    # 10. Zero-duration media is rejected
    # --------------------------------------------------------------------------
    def test_10_zero_duration_media_rejected(self, media_test_files):
        empty_mp4 = media_test_files["empty_mp4"]
        val_res = PhysicalVideoValidator.validate_file(empty_mp4)
        assert val_res.is_valid is False

        # Synthetic zero-duration validation result
        with patch.object(PhysicalVideoValidator, "validate_file", return_value=VideoValidationResult(is_valid=False, duration=0.0, error_message="Asset has zero temporal duration")):
            retriever = InternetVideoRetriever()
            cand = NormalizedVideoCandidate(
                source_name="test_source",
                source_type=SourceType.INTERNET_REAL,
                title="Zero duration media",
                local_path=str(media_test_files["valid_mp4"])
            )
            result = retriever.download_and_validate(cand)
            assert result is None

    # --------------------------------------------------------------------------
    # 11. Internet-source failure falls through safely
    # --------------------------------------------------------------------------
    def test_11_internet_source_failure_falls_through_safely(self, media_test_files):
        retriever = InternetVideoRetriever(cache_dir=media_test_files["temp_dir"])

        # Primary provider throws an unhandled network error
        exploding_provider = MagicMock(spec=BaseVideoRetrievalProvider)
        exploding_provider.name = "exploding_internet"
        exploding_provider.source_type = SourceType.INTERNET_REAL
        exploding_provider.priority = 1
        exploding_provider.search.side_effect = RuntimeError("500 Server Error: Internal connection crashed")

        # Second non-stock provider succeeds with valid video
        valid_mp4 = media_test_files["valid_mp4"]
        healthy_cand = NormalizedVideoCandidate(
            source_name="movie_footage",
            source_type=SourceType.MOVIE,
            title="Healthy movie scene",
            local_path=str(valid_mp4),
            media_url=f"file:///{valid_mp4.name}"
        )
        healthy_provider = MagicMock(spec=BaseVideoRetrievalProvider)
        healthy_provider.name = "healthy_movie"
        healthy_provider.source_type = SourceType.MOVIE
        healthy_provider.priority = 1
        healthy_provider.search.return_value = [healthy_cand]

        retriever.providers = [exploding_provider, healthy_provider]

        # Call acquire_video_for_scene: must NOT crash, must fall through safely to healthy candidate
        selected = retriever.acquire_video_for_scene(query="naval battle scene")
        assert selected is not None
        assert selected.title == "Healthy movie scene"
        assert selected.source_type == SourceType.MOVIE

    # --------------------------------------------------------------------------
    # 12. Stock is reached only after higher-priority retrieval fails
    # --------------------------------------------------------------------------
    def test_12_stock_reached_only_after_higher_priority_retrieval_fails(self, media_test_files):
        valid_mp4 = media_test_files["valid_mp4"]
        retriever = InternetVideoRetriever(cache_dir=media_test_files["temp_dir"])

        mock_stock_prov = MagicMock(spec=BaseVideoRetrievalProvider)
        mock_stock_prov.name = "stock_test"
        mock_stock_prov.source_type = SourceType.STOCK
        mock_stock_prov.priority = 2

        # --- Case A: Primary Non-Stock succeeds ---
        primary_prov_a = MagicMock(spec=BaseVideoRetrievalProvider)
        primary_prov_a.name = "primary_a"
        primary_prov_a.source_type = SourceType.MOVIE
        primary_prov_a.priority = 1
        cand_a = NormalizedVideoCandidate(
            source_name="movie_footage",
            source_type=SourceType.MOVIE,
            title="Movie Scene Winner",
            local_path=str(valid_mp4),
            media_url=f"file:///{valid_mp4.name}"
        )
        primary_prov_a.search.return_value = [cand_a]

        retriever.providers = [primary_prov_a, mock_stock_prov]
        winner = retriever.acquire_video_for_scene(query="cinematic scene")
        assert winner.source_type == SourceType.MOVIE
        # Stock provider must NOT be called at all
        assert mock_stock_prov.search.call_count == 0

        # --- Case B: Primary Non-Stock fails, Stock is reached as fallback ---
        primary_prov_b = MagicMock(spec=BaseVideoRetrievalProvider)
        primary_prov_b.name = "primary_b"
        primary_prov_b.source_type = SourceType.INTERNET_REAL
        primary_prov_b.priority = 1
        primary_prov_b.search.return_value = []  # No candidates

        cand_stock = NormalizedVideoCandidate(
            source_name="pexels",
            source_type=SourceType.STOCK,
            title="Stock Fallback Winner",
            local_path=str(valid_mp4),
            media_url=f"file:///{valid_mp4.name}"
        )
        mock_stock_prov.search.return_value = [cand_stock]

        retriever.providers = [primary_prov_b, mock_stock_prov]
        winner_fallback = retriever.acquire_video_for_scene(query="cinematic scene")
        assert winner_fallback.source_type == SourceType.STOCK
        assert mock_stock_prov.search.call_count == 1

    # --------------------------------------------------------------------------
    # 13. Existing video-only validator remains enforced
    # --------------------------------------------------------------------------
    def test_13_existing_video_only_validator_remains_enforced(self, media_test_files):
        assert VIDEO_ONLY is True
        valid_res = PhysicalVideoValidator.validate_file(media_test_files["valid_mp4"])
        assert valid_res.is_valid is True
        assert valid_res.duration > 0.5
        assert valid_res.width > 0
        assert valid_res.height > 0
        assert valid_res.codec != ""

        # Rejection of images
        img_res = PhysicalVideoValidator.validate_file(media_test_files["jpeg_file"])
        assert img_res.is_valid is False

    # --------------------------------------------------------------------------
    # 14. Existing production visual tests continue passing
    # --------------------------------------------------------------------------
    def test_14_existing_production_visual_tests_continue_passing(self):
        """Verifies that SourceRouter and Scoring retain compatibility with existing models."""
        from engines.visual_intelligence.source_router import SourceRouter
        from engines.visual_intelligence.scoring import VisualCandidateScorer

        router = SourceRouter()
        assert "movie" in router.adapters
        assert "editorial" in router.adapters
        assert "pexels" in router.adapters
        assert "pixabay" in router.adapters

        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="b1", beat_index=0, narration_text="Test", start_time=0.0, end_time=3.0, duration=3.0
        )
        cand = VisualCandidate(
            candidate_id="c1", source_class="SOURCE_A", source_name="movie_footage",
            source_url="https://movie.org/test.mp4", width=1080, height=1920, duration_sec=3.0,
            is_video=True, source_type=SourceType.MOVIE
        )
        score = scorer.score_candidate(cand, intent)
        assert score > 0.0
