import os
import json
import math
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.settings import PROJECT_ROOT, KOKORO_VOICE
from config.constants import (
    DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType, VIDEO_WIDTH, VIDEO_HEIGHT, LicenseType
)
from core.models import ScriptRecord, Topic, AssetRecord, Job, RenderOutput
from engines.storyboard_engine import StoryboardEngine
from engines.editing_director import EditingDirector
from engines.asset_fetcher import AssetFetcher
from engines.qa_engine import QAEngine


class TestStep10VisualQualityAndDiversity:

    def test_01_visual_pipeline_trace_and_component_contracts(self):
        storyboard_engine = StoryboardEngine()
        director = EditingDirector()

        script = ScriptRecord(
            id="sc_trace_01",
            hook="In 1908, a mysterious explosion flattened eighty million trees in Siberia.",
            context="The Tunguska event released energy equal to fifteen megatons of TNT.",
            escalation="Seismic stations across the world detected shockwaves traveling around the globe.",
            reveal="When expeditions finally reached the remote site, they found no impact crater at all.",
            loop_twist="The Siberian Tunguska explosion remains one of Earth's greatest cosmic mysteries.",
            estimated_duration_sec=23.5
        )

        shots = storyboard_engine.create_storyboard(script)
        assert len(shots) >= 7

        topic = Topic(id="top_trace", title="The Tunguska Cosmic Blast", category="Historical Mysteries")
        plan = director._generate_deterministic_editing_plan(
            job_id="job_trace_01",
            topic=topic,
            script=script,
            shots=shots,
            profile="MYSTERY"
        )
        assert len(plan.scenes) == len(shots)

    def test_02_visual_asset_diversity_and_duplicate_rejection(self):
        fetcher = AssetFetcher()
        db = MagicMock()
        db.query.return_value.all.return_value = []

        used_urls = set()
        shot1 = {"shot_id": "s1", "search_query": "Tunguska explosion forest", "duration": 3.0}
        shot2 = {"shot_id": "s2", "search_query": "Siberia wilderness antique", "duration": 3.0}

        # Mock Pexels responses with distinct download links
        mock_p1 = {"download_url": "https://pexels.com/vid1.mp4", "width": 1080, "height": 1920, "quality_tier": "1080p"}
        mock_p2 = {"download_url": "https://pexels.com/vid2.mp4", "width": 1080, "height": 1920, "quality_tier": "1080p"}

        with patch.object(fetcher, "search_pexels_video", side_effect=[mock_p1, mock_p2]), \
             patch("requests.get") as mock_get, \
             patch("pathlib.Path.stat") as mock_stat:

            mock_stat.return_value.st_size = 250000
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.iter_content.return_value = [b"fake_mp4_bytes"]
            mock_get.return_value = mock_resp

            a1 = fetcher.fetch_asset_for_shot(db, shot1, used_urls_in_job=used_urls)
            a2 = fetcher.fetch_asset_for_shot(db, shot2, used_urls_in_job=used_urls)

            assert a1.source_url != a2.source_url
            assert len(used_urls) == 2
            assert a1.source_url in used_urls
            assert a2.source_url in used_urls

    def test_03_visual_source_ranking_rejects_sub_720p(self):
        fetcher = AssetFetcher()

        # Tier 4: 1080p Portrait (1080x1920)
        t4 = fetcher._rank_video_file({"width": 1080, "height": 1920, "fps": 30, "file_type": "video/mp4"})
        assert t4[0] == 4

        # Tier 3: 1080p Landscape (1920x1080)
        t3 = fetcher._rank_video_file({"width": 1920, "height": 1080, "fps": 30, "file_type": "video/mp4"})
        assert t3[0] == 3

        # Tier 2: 720p Portrait (720x1280)
        t2 = fetcher._rank_video_file({"width": 720, "height": 1280, "fps": 30, "file_type": "video/mp4"})
        assert t2[0] == 2

        # Tier 1: 720p Landscape (1280x720)
        t1 = fetcher._rank_video_file({"width": 1280, "height": 720, "fps": 30, "file_type": "video/mp4"})
        assert t1[0] == 1

        # Tier 0: Sub-720p (480x854 or 360x640) -> REJECTED
        t0 = fetcher._rank_video_file({"width": 480, "height": 854, "fps": 30, "file_type": "video/mp4"})
        assert t0[0] == 0

        t0_small = fetcher._rank_video_file({"width": 360, "height": 640, "fps": 30, "file_type": "video/mp4"})
        assert t0_small[0] == 0

    def test_04_historical_era_prompt_formulation(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            hook="The Great Molasses Flood of 1919 struck Boston's North End.",
            context="A fifty-foot steel tank holding over two million gallons collapsed.",
            escalation="A giant wave of dark molasses rushed through the city at thirty-five miles per hour.",
            reveal="Twenty-one people lost their lives and the streets smelled of molasses for decades.",
            loop_twist="Boston's molasses tsunami remains one of the sweetest yet deadliest disasters.",
            estimated_duration_sec=23.2
        )

        shots = storyboard_engine.create_storyboard(script)
        for s in shots:
            assert s["era_compatibility"] == "HISTORICAL_AUTHENTIC"
            assert "historical" in s["visual_prompt"].lower() or "documentary" in s["visual_prompt"].lower() or "cinematic" in s["visual_prompt"].lower()

    def test_05_visual_pacing_and_duration_distribution(self):
        storyboard_engine = StoryboardEngine()
        script = ScriptRecord(
            hook="In 1872, the ghost ship Mary Celeste was found completely abandoned.",
            context="The merchant brig was discovered drifting in full sail near Portugal.",
            escalation="No damage was found, cargo was untouched, and food was still on the table.",
            reveal="The crew had vanished without a trace, leaving all personal belongings behind.",
            loop_twist="To this day, the true fate of the Mary Celeste remains an unsolved puzzle.",
            estimated_duration_sec=23.0
        )

        shots = storyboard_engine.create_storyboard(script)
        for s in shots:
            # Each beat should be approximately 2.0s to 3.5s for dynamic Shorts pacing
            assert 1.8 <= s["duration"] <= 4.0

    def test_06_temporal_coverage_and_outro_margin_calibration(self):
        shots = [
            {"shot_id": f"s_{i}", "duration": 2.5} for i in range(8)
        ]
        audio_duration = 22.4
        safety_margin = 0.6
        target_video_duration = round(audio_duration + safety_margin, 2)  # 23.0s

        current_shots_dur = sum(s["duration"] for s in shots)  # 20.0s
        diff = target_video_duration - current_shots_dur  # +3.0s

        if shots and abs(diff) > 0.05:
            shots[-1]["duration"] = max(2.5, round(shots[-1]["duration"] + diff, 2))

        calibrated_total = sum(s["duration"] for s in shots)
        assert abs(calibrated_total - target_video_duration) < 0.05
        # Ensure video duration exceeds audio duration by at least safety_margin
        assert calibrated_total >= audio_duration + 0.55

    def test_07_qa_engine_rejects_corrupted_or_sub_resolution_media(self):
        qa = QAEngine()
        db = MagicMock()
        db.query.return_value.filter.return_value.count.return_value = 0
        job = MagicMock(spec=Job)
        job.id = "job_test_qa"
        render = MagicMock(spec=RenderOutput)
        render.video_path = "non_existent_file.mp4"
        render.duration_sec = 23.0

        # Missing file rejected
        passed, report = qa.run_qa(db, job, render, assets_used=[])
        assert passed is False
        assert "missing or abnormally small" in report.failure_reasons
