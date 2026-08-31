import os
import json
import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.settings import PROJECT_ROOT, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType, VIDEO_WIDTH, VIDEO_HEIGHT
from core.models import ScriptRecord, Topic, AssetRecord, Job
from engines.storyboard_engine import StoryboardEngine
from engines.editing_director import EditingDirector
from engines.asset_fetcher import AssetFetcher


class TestStep9EcosystemFusionAndVisualEngine2:

    def test_01_visual_engine_2_generates_minimum_seven_segments(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            id="sc_step9_01",
            hook="In 1814, a bizarre tidal wave of fermented beer swept through London.",
            context="At the Horse Shoe Brewery on Tottenham Court Road, a massive wooden vat held over six hundred tons of porter.",
            escalation="Without warning, the iron hoops snapped, causing neighboring vats to burst in a catastrophic chain reaction.",
            reveal="A fifteen-foot wall of beer blasted into the streets, completely flooding basements and demolishing brick houses.",
            loop_twist="It remains one of the strangest industrial disasters in history, all because of London's beer flood.",
            estimated_duration_sec=23.4
        )

        shots = storyboard_engine.create_storyboard(script)
        assert len(shots) >= 7
        assert 7 <= len(shots) <= 10

    def test_02_visual_engine_2_dynamic_duration_scaling(self):
        storyboard_engine = StoryboardEngine()

        script_21s = ScriptRecord(
            hook="Hook text here", context="Context text here", escalation="Escalation text here",
            reveal="Reveal text here", loop_twist="Twist text here", estimated_duration_sec=21.0
        )
        shots_21s = storyboard_engine.create_storyboard(script_21s)
        assert len(shots_21s) >= 7

        script_25s = ScriptRecord(
            hook="Hook text here", context="Context text here", escalation="Escalation text here",
            reveal="Reveal text here", loop_twist="Twist text here", estimated_duration_sec=25.0
        )
        shots_25s = storyboard_engine.create_storyboard(script_25s)
        assert len(shots_25s) >= 8

    def test_03_temporal_coverage_and_zero_visual_gaps(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            hook="A bizarre historical mystery unfolded in the desert.",
            context="Archaeologists discovered ancient structures buried deep under the sand dunes.",
            escalation="Strange inscriptions pointed to a forgotten civilization with advanced engineering.",
            reveal="The team uncovered a massive subterranean chamber filled with bronze mechanisms.",
            loop_twist="To this day, nobody knows who built this ancient desert mystery.",
            estimated_duration_sec=23.0
        )

        shots = storyboard_engine.create_storyboard(script)
        total_covered = sum(s["duration"] for s in shots)
        assert abs(total_covered - 23.0) < 0.05

        # Check contiguous timeline with zero gaps
        prev_end = 0.0
        for s in shots:
            assert abs(s["start_time"] - prev_end) < 0.05
            prev_end = s["end_time"]
        assert abs(prev_end - 23.0) < 0.05

    def test_04_historical_era_and_search_query_quality(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            hook="In 1932, Australia fought an unbelievable war against wild emus.",
            context="Farmers in Western Australia faced over twenty thousand crop-destroying birds.",
            escalation="The military deployed soldiers with Lewis machine guns into the desert.",
            reveal="The birds outmaneuvered the army using guerrilla warfare tactics.",
            loop_twist="The Great Emu War remains history's most hilarious military defeat.",
            estimated_duration_sec=24.0
        )

        shots = storyboard_engine.create_storyboard(script)
        for s in shots:
            assert len(s["search_query"]) > 5
            assert len(s["visual_prompt"]) > 10
            assert "camera_motion" in s
            assert s["min_resolution"] == "1080x1920"

    def test_05_editing_director_handles_visual_engine_2_shots(self):
        storyboard_engine = StoryboardEngine()
        director = EditingDirector()

        script = ScriptRecord(
            hook="The mystery of the Mary Celeste baffled investigators.",
            context="In 1872, the merchant brig was found drifting near the Azores.",
            escalation="All sails were set, cargo was intact, but every soul on board had vanished.",
            reveal="A warm meal and untouched logbook proved the crew abandoned ship in minutes.",
            loop_twist="It remains maritime history's most famous ghost ship puzzle.",
            estimated_duration_sec=23.5
        )
        shots = storyboard_engine.create_storyboard(script)
        topic = Topic(id="top_test", title="The Mary Celeste Ghost Ship", category="Historical Mysteries")

        plan = director._generate_deterministic_editing_plan(
            job_id="job_test_01",
            topic=topic,
            script=script,
            shots=shots,
            profile="MYSTERY"
        )

        assert len(plan.scenes) == len(shots)
        assert len(plan.scenes) >= 7
        assert plan.overall_profile == "MYSTERY"

    def test_06_visual_deduplication_and_distinct_queries(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            hook="The Liechtenstein Army miracle of 1866 remains unforgettable.",
            context="Eighty soldiers marched out to guard a quiet mountain pass in Italy.",
            escalation="They avoided all combat and simply enjoyed the scenic alpine passes.",
            reveal="When the war ended, eighty-one soldiers marched back home safely.",
            loop_twist="They made a good friend along the way, making it history's best war.",
            estimated_duration_sec=22.8
        )

        shots = storyboard_engine.create_storyboard(script)
        queries = [s["search_query"] for s in shots]
        # Verify queries are distinct across the 7+ shots
        unique_queries = set(queries)
        assert len(unique_queries) >= 7
