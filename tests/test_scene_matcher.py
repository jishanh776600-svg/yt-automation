"""
Tests for ChronologicalSceneMatcher.
Verifies narrative chronological windowing, scene ledger persistence,
and zero-mismatch timestamp calculation.
"""

import json
from pathlib import Path
import pytest
from intelligence.scene_matcher import ChronologicalSceneMatcher, SceneMatchResult
from engines.movie_script_engine import MovieBeat


def test_chronological_scene_matcher_proportional(tmp_path: Path):
    matcher = ChronologicalSceneMatcher(cache_dir=tmp_path)
    beats = [
        MovieBeat(beat_id="beat_01", sequence=1, text="Car driving down dirt road.", visual_description="Car driving", search_keywords=["car"], duration_estimate_sec=3.0, tension_level="HIGH"),
        MovieBeat(beat_id="beat_02", sequence=2, text="Barbed wire tears the tire.", visual_description="Barbed wire on tire", search_keywords=["wire"], duration_estimate_sec=3.0, tension_level="HIGH"),
        MovieBeat(beat_id="beat_03", sequence=3, text="They discover a rotting wooden cabin.", visual_description="Old wooden cabin", search_keywords=["cabin"], duration_estimate_sec=3.0, tension_level="HIGH"),
    ]

    # Non-existent movie path should gracefully return proportional results
    results = matcher.match_beats_to_movie(
        movie_path=Path("non_existent_movie.mp4"),
        beats=beats,
        part_number=1,
        total_parts=5,
        movie_title="Wrong Turn"
    )

    assert len(results) == 3
    assert results[0].beat_id == "beat_01"
    assert results[1].beat_id == "beat_02"
    assert results[2].beat_id == "beat_03"
    # Chronological progression: each subsequent beat timestamp must be >= previous
    assert results[0].matched_timestamp_sec <= results[1].matched_timestamp_sec <= results[2].matched_timestamp_sec


def test_scene_matcher_ledger_caching(tmp_path: Path):
    matcher = ChronologicalSceneMatcher(cache_dir=tmp_path)
    beats = [
        MovieBeat(beat_id="beat_01", sequence=1, text="Opening scene", visual_description="Opening", search_keywords=["open"], duration_estimate_sec=3.0, tension_level="HIGH"),
        MovieBeat(beat_id="beat_02", sequence=2, text="Second scene", visual_description="Second", search_keywords=["second"], duration_estimate_sec=3.0, tension_level="HIGH"),
    ]

    # Pre-populate ledger in cache
    ledger_file = tmp_path / "ledger_wrong_turn_pt1.json"
    ledger_data = [
        {"beat_id": "beat_01", "sequence": 1, "matched_timestamp_sec": 120.5, "confidence_score": 0.99, "visual_description": "Opening"},
        {"beat_id": "beat_02", "sequence": 2, "matched_timestamp_sec": 240.8, "confidence_score": 0.98, "visual_description": "Second"},
    ]
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump(ledger_data, f)

    results = matcher.match_beats_to_movie(
        movie_path=Path("dummy.mp4"),
        beats=beats,
        part_number=1,
        total_parts=5,
        movie_title="Wrong Turn"
    )

    assert len(results) == 2
    assert results[0].matched_timestamp_sec == 120.5
    assert results[1].matched_timestamp_sec == 240.8
    assert results[0].confidence_score == 0.99
