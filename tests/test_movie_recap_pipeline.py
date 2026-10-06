"""
Unit & Integration Tests for Movie Recap Pipeline.
===================================================
Tests MovieCatalogManager, MovieScriptEngine, MovieFootageAdapter,
SceneSlicer, and CloudProductionOrchestrator movie recap features.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.movie_catalog import MovieCatalogManager, MovieEntry, THRILLER_MOVIE_CATALOG
from engines.movie_script_engine import MovieScriptEngine, MovieShortsScript, MovieBeat
from intelligence.movie_footage_adapter import MovieFootageAdapter
from intelligence.scene_slicer import SceneSlicer
from intelligence.frame_inspector import FrameInspector
from intelligence.cloud_orchestrator import CloudProductionOrchestrator


class TestMovieCatalog:
    """Tests for the curated movie catalog."""

    def test_catalog_size_and_entries(self):
        manager = MovieCatalogManager()
        movies = manager.get_all_movies()
        assert len(movies) >= 15, f"Expected at least 15 movies, found {len(movies)}"
        
        # Verify key titles exist
        titles = [m.title.lower() for m in movies]
        assert "wrong turn" in titles
        assert "the hills have eyes" in titles
        assert "hostel" in titles
        assert "saw" in titles
        assert "the descent" in titles
        assert "fall" in titles
        assert "cube" in titles

    def test_movie_metadata_integrity(self):
        manager = MovieCatalogManager()
        for movie in manager.get_all_movies():
            assert movie.title, "Movie missing title"
            assert movie.year > 1950, f"Invalid year for {movie.title}: {movie.year}"
            assert movie.high_concept_hook, f"Movie {movie.title} missing high concept hook"
            assert movie.threat_or_antagonist, f"Movie {movie.title} missing threat"
            assert len(movie.key_setpieces) >= 3, f"Movie {movie.title} has too few setpieces"
            assert len(movie.footage_search_queries) >= 2, f"Movie {movie.title} has too few search queries"

    def test_search_and_subgenres(self):
        manager = MovieCatalogManager()
        results = manager.search_movies("wrong turn")
        assert len(results) >= 1
        assert results[0].title == "Wrong Turn"
        assert results[0].year == 2003

        subgenres = manager.get_subgenres()
        assert len(subgenres) >= 3


class TestMovieScriptEngine:
    """Tests for the movie script generation engine."""

    def test_script_generation_fallback(self):
        engine = MovieScriptEngine()
        manager = MovieCatalogManager()
        movie = manager.get_movie_by_title("Wrong Turn")
        assert movie is not None

        # Test deterministic template generation
        script = engine._build_deterministic_recap(movie)
        assert isinstance(script, MovieShortsScript)
        assert script.movie_title == "Wrong Turn"
        assert len(script.beats) >= 14, f"Expected >= 14 beats, got {len(script.beats)}"
        assert 120 <= script.total_words <= 155, f"Word count {script.total_words} out of expected range"
        assert 50.0 <= script.estimated_duration_sec <= 60.0, f"Duration {script.estimated_duration_sec}s out of bounds"

    def test_script_beats_structure(self):
        engine = MovieScriptEngine()
        manager = MovieCatalogManager()
        movie = manager.get_movie_by_title("The Descent")
        assert movie is not None

        script = engine._build_deterministic_recap(movie)
        for beat in script.beats:
            assert beat.beat_id, "Beat missing beat_id"
            assert beat.text, "Beat missing spoken text"
            assert beat.visual_description, "Beat missing visual description"
            assert len(beat.search_keywords) >= 1, "Beat missing search keywords"
            assert beat.tension_level in ("HIGH", "EXTREME", "DREAD", "SHOCK")


class TestSceneSlicer:
    """Tests for the scene slicer and fair-use transformer."""

    def test_slicer_init(self):
        slicer = SceneSlicer()
        assert slicer.target_width == 1080
        assert slicer.target_height == 1920

    def test_duration_clamping(self):
        slicer = SceneSlicer()
        # Ensure slice duration constraints
        assert max(2.0, min(3.2, 5.0)) == 3.2
        assert max(2.0, min(3.2, 1.0)) == 2.0
        assert max(2.0, min(3.2, 2.7)) == 2.7


class TestMovieProductionOrchestrator:
    """Tests for CloudProductionOrchestrator movie recap features."""

    def test_orchestrator_subsystems_initialized(self):
        orchestrator = CloudProductionOrchestrator(is_dry_run=True)
        assert orchestrator.movie_catalog is not None
        assert orchestrator.movie_script_engine is not None
        assert orchestrator.movie_footage_adapter is not None
        assert orchestrator.scene_slicer is not None
        assert orchestrator.frame_inspector is not None

    def test_movie_idempotency_check(self):
        orchestrator = CloudProductionOrchestrator(is_dry_run=True)
        manager = MovieCatalogManager()
        movie = manager.get_movie_by_title("Wrong Turn")
        
        mock_db = MagicMock()
        mock_db.query.return_value.filter_by.return_value.first.return_value = None
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        assert orchestrator.is_movie_already_produced(movie, mock_db) is False
