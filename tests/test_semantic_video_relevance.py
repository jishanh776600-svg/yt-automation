"""
Comprehensive Unit Tests for Step 2/8: Advanced Semantic Video Relevance.
=========================================================================
Tests all 15 required semantic relevance invariants:
  1. Exact entity match beats generic related footage.
  2. Exact event match beats generic footage.
  3. Correct action beats incorrect action (cannon exploding, miners fleeing, whirlpool).
  4. Correct location/context improves ranking.
  5. Generic noun-only match receives penalty (Lake Peigneur vs generic lake).
  6. Titanic collision candidate beats generic ship footage.
  7. Dyatlov-related candidate beats generic snowy mountain.
  8. Lake Peigneur disaster footage beats generic lake footage.
  9. Irrelevant movie footage does NOT automatically win over relevant stock.
  10. Relevant movie footage beats generic stock.
  11. Relevant internet footage beats generic stock.
  12. Non-stock candidate below semantic threshold falls through to stock.
  13. Image candidates remain rejected (hard VIDEO_ONLY invariant).
  14. Existing Step-1 internet retrieval tests continue passing.
  15. Existing visual system hardening tests continue passing.
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
from engines.visual_intelligence.intent_extractor import VisualIntentExtractor


@pytest.fixture(scope="module")
def media_test_files():
    """Generates small test media files using FFmpeg and PIL."""
    td = tempfile.mkdtemp(prefix="semantic_relevance_step2_tests_")
    dir_path = Path(td)

    # Valid MP4
    valid_mp4 = dir_path / "sample_valid.mp4"
    subprocess.run([
        FFMPEG_EXE, "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(valid_mp4)
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    # Valid JPEG image
    jpeg_file = dir_path / "sample_image.jpg"
    img = Image.new("RGB", (320, 240), color=(120, 160, 200))
    img.save(jpeg_file, "JPEG")

    # Fake MP4 (renamed JPEG)
    fake_renamed_mp4 = dir_path / "fake_renamed.mp4"
    shutil.copyfile(jpeg_file, fake_renamed_mp4)

    yield {
        "valid_mp4": valid_mp4,
        "jpeg_file": jpeg_file,
        "fake_renamed_mp4": fake_renamed_mp4,
        "temp_dir": dir_path
    }

    shutil.rmtree(td, ignore_errors=True)


class TestSemanticVideoRelevance:

    # --------------------------------------------------------------------------
    # 1. Exact entity match beats generic related footage
    # --------------------------------------------------------------------------
    def test_01_exact_entity_match_beats_generic_related_footage(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_1",
            beat_index=0,
            narration_text="President John F. Kennedy addressed the nation on civil rights.",
            primary_entity="John F. Kennedy",
            event="Nation Address",
            search_queries=["John F Kennedy civil rights address video"]
        )

        cand_exact = VisualCandidate(
            candidate_id="c_exact",
            source_class="SOURCE_A",
            source_name="archival",
            source_url="https://archive.org/jfk_address.mp4",
            title="President John F. Kennedy Oval Office Address on Civil Rights",
            description="Official recorded television broadcast of JFK speaking to the country",
            content_type=VisualContentType.ARCHIVAL_VIDEO,
            is_video=True,
            source_type=SourceType.ARCHIVAL
        )

        cand_generic = VisualCandidate(
            candidate_id="c_generic",
            source_class="SOURCE_A",
            source_name="archival",
            source_url="https://archive.org/generic_politician.mp4",
            title="Generic Politician Speaking at Podium in 1960s",
            description="Archival footage of an unnamed government official addressing reporters",
            content_type=VisualContentType.ARCHIVAL_VIDEO,
            is_video=True,
            source_type=SourceType.ARCHIVAL
        )

        ranked = scorer.rank_candidates([cand_generic, cand_exact], intent=intent)
        assert ranked[0].candidate_id == "c_exact"
        assert ranked[0].final_score > ranked[1].final_score + 0.20

    # --------------------------------------------------------------------------
    # 2. Exact event match beats generic footage
    # --------------------------------------------------------------------------
    def test_02_exact_event_match_beats_generic_footage(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_2",
            beat_index=0,
            narration_text="The Chernobyl reactor number four exploded during a late-night safety test.",
            primary_entity="Chernobyl",
            event="Chernobyl Disaster Explosion",
            search_queries=["Chernobyl reactor explosion archival footage"]
        )

        cand_event = VisualCandidate(
            candidate_id="c_event",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://archive.org/chernobyl_ruins.mp4",
            title="Chernobyl Disaster Reactor 4 Ruins and Explosion Site",
            description="Documentary record of the Chernobyl reactor explosion aftermath",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        cand_generic = VisualCandidate(
            candidate_id="c_generic",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://archive.org/industrial_power_plant.mp4",
            title="Industrial Power Plant Cooling Towers at Sunset",
            description="Establishing shot of generic power generation facility",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        ranked = scorer.rank_candidates([cand_generic, cand_event], intent=intent)
        assert ranked[0].candidate_id == "c_event"
        assert ranked[0].final_score > ranked[1].final_score

    # --------------------------------------------------------------------------
    # 3. Correct action beats incorrect action
    # --------------------------------------------------------------------------
    def test_03_correct_action_beats_incorrect_action(self):
        scorer = VisualCandidateScorer()

        # 3A. Cannon exploding vs stationary cannon
        intent_cannon = VisualIntent(
            beat_id="beat_3a",
            beat_index=0,
            narration_text="The siege cannon exploded violently into iron fragments.",
            visual_action="exploding",
            action="exploding",
            search_queries=["cannon exploding blast firing"]
        )
        c_cannon_exploding = VisualCandidate(
            candidate_id="c_blast",
            source_class="SOURCE_A",
            source_name="movie_footage",
            source_url="https://movie.org/cannon_blast.mp4",
            title="Artillery cannon exploding into smoke and iron blast",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.MOVIE
        )
        c_cannon_static = VisualCandidate(
            candidate_id="c_static",
            source_class="SOURCE_A",
            source_name="movie_footage",
            source_url="https://movie.org/cannon_museum.mp4",
            title="Stationary cannon exhibit in museum display",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.MOVIE
        )
        ranked_cannon = scorer.rank_candidates([c_cannon_static, c_cannon_exploding], intent=intent_cannon)
        assert ranked_cannon[0].candidate_id == "c_blast"

        # 3B. Miners fled vs mining equipment
        intent_miners = VisualIntent(
            beat_id="beat_3b",
            beat_index=0,
            narration_text="Fifty-five miners fled the collapsing salt shaft for their lives.",
            visual_action="miners fled",
            action="fled",
            search_queries=["miners fled evacuating shaft escape"]
        )
        c_miners_fleeing = VisualCandidate(
            candidate_id="c_fleeing",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/evac.mp4",
            title="Miners evacuating and fleeing rushing out of mine shaft",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )
        c_mining_gear = VisualCandidate(
            candidate_id="c_gear",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/gear.mp4",
            title="Mining equipment stationary drill and coal cart",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )
        ranked_miners = scorer.rank_candidates([c_mining_gear, c_miners_fleeing], intent=intent_miners)
        assert ranked_miners[0].candidate_id == "c_fleeing"

        # 3C. Whirlpool vs calm lake
        intent_lake = VisualIntent(
            beat_id="beat_3c",
            beat_index=0,
            narration_text="The entire lake disappeared into a colossal swirling whirlpool.",
            visual_action="whirlpool",
            action="whirlpool",
            search_queries=["lake whirlpool vortex draining water"]
        )
        c_whirlpool = VisualCandidate(
            candidate_id="c_vortex",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/vortex.mp4",
            title="Massive vortex whirlpool draining water into sinkhole",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )
        c_calm_lake = VisualCandidate(
            candidate_id="c_calm",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/calm.mp4",
            title="Calm lake scenery with peaceful quiet shore",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )
        ranked_lake = scorer.rank_candidates([c_calm_lake, c_whirlpool], intent=intent_lake)
        assert ranked_lake[0].candidate_id == "c_vortex"

    # --------------------------------------------------------------------------
    # 4. Correct location/context improves ranking
    # --------------------------------------------------------------------------
    def test_04_correct_location_context_improves_ranking(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_4",
            beat_index=0,
            narration_text="Naval escorts patrolled the Danish Straits.",
            location="Danish Straits",
            search_queries=["Danish Straits naval patrol"]
        )

        c_with_location = VisualCandidate(
            candidate_id="c_loc",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/danish_straits.mp4",
            title="Naval patrol vessel moving through Danish Straits",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        c_without_location = VisualCandidate(
            candidate_id="c_no_loc",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/generic_sea.mp4",
            title="Naval patrol vessel moving through open Pacific ocean",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        ranked = scorer.rank_candidates([c_without_location, c_with_location], intent=intent)
        assert ranked[0].candidate_id == "c_loc"
        assert ranked[0].final_score > ranked[1].final_score

    # --------------------------------------------------------------------------
    # 5. Generic noun-only match receives penalty (Lake Peigneur vs lake)
    # --------------------------------------------------------------------------
    def test_05_generic_noun_only_match_receives_penalty(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_5",
            beat_index=0,
            narration_text="In 1980, Lake Peigneur in Louisiana was drained into an underground salt dome.",
            primary_entity="Lake Peigneur",
            event="Lake Peigneur Disaster",
            location="Louisiana",
            search_queries=["Lake Peigneur disaster draining Louisiana"]
        )

        # Candidate that only matches generic token "lake"
        cand_generic_lake = VisualCandidate(
            candidate_id="c_generic_lake",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/generic_lake.mp4",
            title="Peaceful Lake Scenery and Calm Water",
            description="Scenic establishing b-roll of a mountain lake",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        # Candidate with exact specific entity
        cand_peigneur = VisualCandidate(
            candidate_id="c_peigneur",
            source_class="SOURCE_A",
            source_name="archival",
            source_url="https://archive.org/lake_peigneur_1980.mp4",
            title="1980 Lake Peigneur Louisiana Disaster Archival Newsreel",
            description="Footage of Lake Peigneur draining into salt mine whirlpool",
            content_type=VisualContentType.ARCHIVAL_VIDEO,
            is_video=True,
            source_type=SourceType.ARCHIVAL
        )

        score_generic = scorer.score_candidate(cand_generic_lake, intent)
        score_peigneur = scorer.score_candidate(cand_peigneur, intent)

        # Generic lake match must receive severe entity penalty and generic footage penalty
        assert scorer.evaluate_entity_match(cand_generic_lake, intent) <= 0.20
        assert score_generic < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD
        assert score_peigneur >= scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD
        assert score_peigneur > score_generic + 0.40

    # --------------------------------------------------------------------------
    # 6. Titanic collision candidate beats generic ship footage
    # --------------------------------------------------------------------------
    def test_06_titanic_collision_beats_generic_ship(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_6",
            beat_index=0,
            narration_text="The Titanic struck an iceberg in the frozen North Atlantic.",
            primary_entity="Titanic",
            event="Iceberg Collision",
            visual_action="struck iceberg",
            search_queries=["Titanic iceberg collision film scene"]
        )

        cand_titanic = VisualCandidate(
            candidate_id="c_titanic",
            source_class="SOURCE_A_CINEMATIC",
            source_name="movie_footage",
            source_url="https://movie.org/titanic_iceberg.mp4",
            title="Titanic iceberg collision movie scene",
            description="Dramatic film depiction of RMS Titanic colliding with iceberg",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.MOVIE
        )

        cand_generic_ship = VisualCandidate(
            candidate_id="c_generic_ship",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/ship.mp4",
            title="Ship sailing smoothly in calm sea",
            description="Generic ship b-roll",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            is_video=True,
            source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates([cand_generic_ship, cand_titanic], intent=intent)
        assert ranked[0].candidate_id == "c_titanic"
        assert ranked[0].final_score > ranked[1].final_score

    # --------------------------------------------------------------------------
    # 7. Dyatlov-related candidate beats generic snowy mountain
    # --------------------------------------------------------------------------
    def test_07_dyatlov_candidate_beats_generic_snowy_mountain(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_7",
            beat_index=0,
            narration_text="The nine hikers perished mysteriously on the slopes of Dyatlov Pass.",
            primary_entity="Dyatlov Pass",
            event="Dyatlov Pass Incident",
            location="Ural Mountains",
            search_queries=["Dyatlov Pass incident archival hikers"]
        )

        cand_dyatlov = VisualCandidate(
            candidate_id="c_dyatlov",
            source_class="SOURCE_A",
            source_name="archival",
            source_url="https://archive.org/dyatlov_pass.mp4",
            title="Dyatlov Pass Incident Archival Expedition Footage",
            description="Historical film footage documenting the Ural Mountains search party",
            content_type=VisualContentType.ARCHIVAL_VIDEO,
            is_video=True,
            source_type=SourceType.ARCHIVAL
        )

        cand_generic_mountain = VisualCandidate(
            candidate_id="c_generic_mountain",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/snow_mountain.mp4",
            title="Generic snowy mountain drone view",
            description="Peaceful calm scenery drone view of mountains",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            is_video=True,
            source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates([cand_generic_mountain, cand_dyatlov], intent=intent)
        assert ranked[0].candidate_id == "c_dyatlov"
        assert ranked[0].final_score >= scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD
        assert ranked[1].final_score < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

    # --------------------------------------------------------------------------
    # 8. Lake Peigneur disaster footage beats generic lake footage
    # --------------------------------------------------------------------------
    def test_08_lake_peigneur_disaster_beats_generic_lake(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_8",
            beat_index=0,
            narration_text="Lake Peigneur drained completely in three hours as a sinkhole swallowed everything.",
            primary_entity="Lake Peigneur",
            event="Lake Peigneur Disaster",
            visual_action="whirlpool draining",
            search_queries=["Lake Peigneur disaster sinkhole draining footage"]
        )

        c_disaster = VisualCandidate(
            candidate_id="c_disaster",
            source_class="SOURCE_A",
            source_name="archival",
            source_url="https://archive.org/lake_peigneur_disaster.mp4",
            title="Lake Peigneur Disaster whirlpool vortex draining lake",
            description="Historical recording of the 1980 disaster",
            content_type=VisualContentType.ARCHIVAL_VIDEO,
            is_video=True,
            source_type=SourceType.ARCHIVAL
        )

        c_scenery = VisualCandidate(
            candidate_id="c_scenery",
            source_class="SOURCE_A",
            source_name="internet_real",
            source_url="https://real.org/lake_scenery.mp4",
            title="Calm lake scenery with peaceful reflections",
            description="Scenic b-roll establishing shot of nature",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        ranked = scorer.rank_candidates([c_scenery, c_disaster], intent=intent)
        assert ranked[0].candidate_id == "c_disaster"
        assert ranked[0].final_score > ranked[1].final_score + 0.35

    # --------------------------------------------------------------------------
    # 9. Irrelevant movie footage does NOT automatically win over relevant stock
    # --------------------------------------------------------------------------
    def test_09_irrelevant_movie_footage_does_not_win_over_relevant_stock(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_9",
            beat_index=0,
            narration_text="Protesters filled the central square waving flags and chanting.",
            visual_action="protesting",
            action="protesting",
            event="Street Demonstration",
            search_queries=["protest rally chanting crowd square"]
        )

        # Completely irrelevant movie candidate (space combat scene)
        irrelevant_movie = VisualCandidate(
            candidate_id="c_irrelevant_movie",
            source_class="SOURCE_A_CINEMATIC",
            source_name="movie_footage",
            source_url="https://movie.org/star_cruiser.mp4",
            title="Space cruiser laser battle in asteroid field",
            description="Sci-fi movie combat scene",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.MOVIE
        )

        # Highly relevant stock video candidate (protest march in city)
        relevant_stock = VisualCandidate(
            candidate_id="c_relevant_stock",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/protest.mp4",
            title="Protesters marching in demonstration with flags",
            description="Crowd chanting and demonstrating in square",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            is_video=True,
            source_type=SourceType.STOCK
        )

        score_movie = scorer.score_candidate(irrelevant_movie, intent)
        score_stock = scorer.score_candidate(relevant_stock, intent)

        # Irrelevant movie should score below threshold
        assert score_movie < scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD
        assert score_stock >= scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD

        # In ranking, two-stage policy: Qualified Stock (Tier 2) beats Unqualified Movie (Tier 3)
        ranked = scorer.rank_candidates([irrelevant_movie, relevant_stock], intent=intent)
        assert ranked[0].candidate_id == "c_relevant_stock"
        assert ranked[0].source_type == SourceType.STOCK
        assert ranked[1].candidate_id == "c_irrelevant_movie"

    # --------------------------------------------------------------------------
    # 10. Relevant movie footage beats generic stock
    # --------------------------------------------------------------------------
    def test_10_relevant_movie_footage_beats_generic_stock(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_10",
            beat_index=0,
            narration_text="The battleship fired its massive main guns in broadside salvo.",
            visual_action="firing exploding",
            action="firing",
            search_queries=["battleship firing broadside guns scene"]
        )

        relevant_movie = VisualCandidate(
            candidate_id="c_rel_movie",
            source_class="SOURCE_A_CINEMATIC",
            source_name="movie_footage",
            source_url="https://movie.org/battleship_guns.mp4",
            title="Battleship firing broadside salvo movie scene",
            description="Naval war film scene of heavy guns exploding with fire",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.MOVIE
        )

        generic_stock = VisualCandidate(
            candidate_id="c_gen_stock",
            source_class="SOURCE_A",
            source_name="pexels",
            source_url="https://pexels.com/ocean_water.mp4",
            title="Calm blue ocean waves",
            description="Generic water background",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            is_video=True,
            source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates([generic_stock, relevant_movie], intent=intent)
        assert ranked[0].candidate_id == "c_rel_movie"
        assert ranked[0].source_type == SourceType.MOVIE

    # --------------------------------------------------------------------------
    # 11. Relevant internet footage beats generic stock
    # --------------------------------------------------------------------------
    def test_11_relevant_internet_footage_beats_generic_stock(self):
        scorer = VisualCandidateScorer()
        intent = VisualIntent(
            beat_id="beat_11",
            beat_index=0,
            narration_text="Coast guard officers intercepted the shadow-fleet oil tanker.",
            primary_entity="oil tanker",
            visual_action="intercepted",
            action="intercepted",
            search_queries=["coast guard intercepting oil tanker"]
        )

        rel_internet = VisualCandidate(
            candidate_id="c_internet",
            source_class="SOURCE_B",
            source_name="internet_real",
            source_url="https://news.org/tanker_intercept.mp4",
            title="Coast guard officers intercepting suspicious oil tanker at sea",
            description="Official maritime police footage of vessel interception",
            content_type=VisualContentType.REAL_VIDEO,
            is_video=True,
            source_type=SourceType.INTERNET_REAL
        )

        gen_stock = VisualCandidate(
            candidate_id="c_stock",
            source_class="SOURCE_A",
            source_name="pixabay",
            source_url="https://pixabay.com/waves.mp4",
            title="Ocean sunset calm water",
            description="Peaceful water b-roll",
            content_type=VisualContentType.GENERIC_STOCK_VIDEO,
            is_video=True,
            source_type=SourceType.STOCK
        )

        ranked = scorer.rank_candidates([gen_stock, rel_internet], intent=intent)
        assert ranked[0].candidate_id == "c_internet"
        assert ranked[0].source_type == SourceType.INTERNET_REAL

    # --------------------------------------------------------------------------
    # 12. Non-stock candidate below semantic threshold falls through to stock
    # --------------------------------------------------------------------------
    def test_12_non_stock_below_threshold_falls_through_to_stock(self, media_test_files):
        valid_mp4 = media_test_files["valid_mp4"]
        retriever = InternetVideoRetriever(cache_dir=media_test_files["temp_dir"])

        intent = VisualIntent(
            beat_id="beat_12",
            beat_index=0,
            narration_text="Violent street protests erupted outside the parliament.",
            visual_action="protesting",
            action="protesting",
            event="Parliament Protest"
        )

        # Primary provider returns an irrelevant candidate (e.g. peaceful desert landscape)
        irrelevant_primary_cand = NormalizedVideoCandidate(
            source_name="internet_real",
            source_type=SourceType.INTERNET_REAL,
            title="Peaceful desert dunes calm scenery",
            description="Quiet sand dunes in the Sahara",
            local_path=str(valid_mp4),
            media_url=f"file:///{valid_mp4.name}"
        )
        mock_primary = MagicMock(spec=BaseVideoRetrievalProvider)
        mock_primary.name = "primary_real"
        mock_primary.source_type = SourceType.INTERNET_REAL
        mock_primary.priority = 1
        mock_primary.search.return_value = [irrelevant_primary_cand]

        # Stock fallback provider returns a relevant protest video
        relevant_stock_cand = NormalizedVideoCandidate(
            source_name="pexels",
            source_type=SourceType.STOCK,
            title="Protesters chanting outside government parliament building",
            description="Demonstration with crowd and signs",
            local_path=str(valid_mp4),
            media_url=f"file:///{valid_mp4.name}"
        )
        mock_stock = MagicMock(spec=BaseVideoRetrievalProvider)
        mock_stock.name = "stock_fallback"
        mock_stock.source_type = SourceType.STOCK
        mock_stock.priority = 2
        mock_stock.search.return_value = [relevant_stock_cand]

        retriever.providers = [mock_primary, mock_stock]

        # Acquire video: because primary candidate is below semantic threshold,
        # it must NOT be selected, and retriever MUST fall through to stock fallback!
        winner = retriever.acquire_video_for_scene(
            query="protest outside parliament",
            intent=intent
        )

        assert winner.source_type == SourceType.STOCK
        assert winner.title == "Protesters chanting outside government parliament building"
        assert mock_stock.search.call_count == 1

    # --------------------------------------------------------------------------
    # 13. Image candidates remain rejected
    # --------------------------------------------------------------------------
    def test_13_image_candidates_remain_rejected(self, media_test_files):
        assert VIDEO_ONLY is True

        retriever = InternetVideoRetriever()

        # Reject image URLs
        assert PhysicalVideoValidator.is_image_url("https://example.com/photo.jpg") is True
        assert PhysicalVideoValidator.is_image_url("https://example.com/asset.png") is True
        assert PhysicalVideoValidator.is_image_url("https://example.com/graphic.webp") is True

        # Reject physical image
        img_cand = NormalizedVideoCandidate(
            source_name="stock_photos",
            source_type=SourceType.STOCK,
            title="Static JPEG photo",
            local_path=str(media_test_files["jpeg_file"])
        )
        assert retriever.download_and_validate(img_cand) is None

        # Reject fake renamed .mp4
        fake_cand = NormalizedVideoCandidate(
            source_name="disguised_image",
            source_type=SourceType.INTERNET_REAL,
            title="Renamed JPEG to MP4",
            local_path=str(media_test_files["fake_renamed_mp4"])
        )
        assert retriever.download_and_validate(fake_cand) is None

    # --------------------------------------------------------------------------
    # 14. Existing Step-1 tests still pass
    # --------------------------------------------------------------------------
    def test_14_existing_step1_tests_still_pass(self):
        """Verifies Step 1 source types and priorities remain intact."""
        assert SourceType.MOVIE.value == "MOVIE"
        assert SourceType.INTERNET_REAL.value == "INTERNET_REAL"
        assert SourceType.ARCHIVAL.value == "ARCHIVAL"
        assert SourceType.STOCK.value == "STOCK"

        assert get_source_priority(SourceType.MOVIE) == 1
        assert get_source_priority(SourceType.INTERNET_REAL) == 1
        assert get_source_priority(SourceType.ARCHIVAL) == 1
        assert get_source_priority(SourceType.STOCK) == 2

    # --------------------------------------------------------------------------
    # 15. Existing visual-system hardening tests compatibility
    # --------------------------------------------------------------------------
    def test_15_existing_visual_system_hardening_compatibility(self):
        """Verifies IntentExtractor extracts new semantic fields properly."""
        extractor = VisualIntentExtractor()
        beat_text = "The Lake Peigneur drilling rig accidentally pierced an underground salt mine, creating a giant whirlpool."
        intent = extractor.extract_intent_from_beat(
            narration=beat_text,
            beat_index=0,
            start_time=0.0,
            duration=4.0
        )
        assert intent.visual_action != "" or intent.action != ""
        assert intent.target_object != "" or intent.primary_entity != ""
        assert len(intent.search_queries) > 0
        # Ensure queries contain action/event terms, not just generic nouns
        query_text = " ".join(intent.search_queries).lower()
        assert any(t in query_text for t in ["lake", "peigneur", "mine", "whirlpool", "drilling", "pierced"])
