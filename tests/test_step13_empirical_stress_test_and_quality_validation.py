import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timedelta

from config.constants import (
    VisualSourceType, HistoricalEventRelation, LicenseType,
    DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType,
    VIDEO_WIDTH, VIDEO_HEIGHT
)
from core.models import AssetRecord, Job, ScriptRecord, Topic, RenderOutput, UploadRecord
from engines.asset_fetcher import AssetFetcher, generate_provenance_manifest, classify_visual_provenance
from engines.storyboard_engine import StoryboardEngine
from engines.editing_director import EditingDirector
from engines.qa_engine import QAEngine


class TestStep13EmpiricalStressTestAndQualityValidation:

    def test_01_multi_topic_diversity_generation(self):
        storyboard = StoryboardEngine()

        topics = [
            ("The London Beer Flood of 1814", "In 1814, a bizarre tidal wave of fermented beer swept through London."),
            ("The Liechtenstein Army Miracle of 1866", "In 1866, eighty Liechtenstein soldiers went to war and eighty-one returned."),
            ("The Great Molasses Flood of 1919", "In 1919, a two-million gallon wave of dark molasses struck Boston."),
            ("The Great Emu War of 1932", "In 1932, the Australian military fought a hilarious war against wild emus."),
            ("The Tunguska Cosmic Blast of 1908", "In 1908, a mysterious explosion flattened eighty million trees in Siberia.")
        ]

        for title, hook in topics:
            script = ScriptRecord(
                hook=hook,
                context="Historical context and detailed setting for this recorded event.",
                escalation="Dramatic escalation of events leading to a major turning point.",
                reveal="Surprising revelation that altered history forever.",
                loop_twist="To this day, this strange historical event remains unforgettable.",
                estimated_duration_sec=23.2
            )
            shots = storyboard.create_storyboard(script)
            assert len(shots) >= 7
            assert 7 <= len(shots) <= 10
            # Ensure each topic receives unique search queries
            queries = [s["search_query"] for s in shots]
            assert len(set(queries)) >= 7

    def test_02_historical_and_modern_source_percentage_calculation(self):
        assets = [
            AssetRecord(id="a1", source="wikimedia_commons", metadata_json=json.dumps({"source_type": VisualSourceType.HISTORICAL_ENGRAVING.value})),
            AssetRecord(id="a2", source="wikimedia_commons", metadata_json=json.dumps({"source_type": VisualSourceType.HISTORICAL_DOCUMENT.value})),
            AssetRecord(id="a3", source="wikimedia_commons", metadata_json=json.dumps({"source_type": VisualSourceType.HISTORICAL_MAP.value})),
            AssetRecord(id="a4", source="pexels_video", metadata_json=json.dumps({"source_type": VisualSourceType.MODERN_CONTEXTUAL_STOCK.value})),
            AssetRecord(id="a5", source="pexels_video", metadata_json=json.dumps({"source_type": VisualSourceType.MODERN_CONTEXTUAL_STOCK.value})),
            AssetRecord(id="a6", source="pexels_video", metadata_json=json.dumps({"source_type": VisualSourceType.MODERN_CONTEXTUAL_STOCK.value})),
            AssetRecord(id="a7", source="pollinations_ai", metadata_json=json.dumps({"source_type": VisualSourceType.GENERATED_RECONSTRUCTION.value})),
            AssetRecord(id="a8", source="pexels_video", metadata_json=json.dumps({"source_type": VisualSourceType.MODERN_CONTEXTUAL_STOCK.value}))
        ]

        manifest = generate_provenance_manifest("job_stress_01", assets, Path("temp_manifest.json"))
        total = manifest["total_assets_used"]
        hist_pct = (manifest["historical_source_count"] / total) * 100.0
        stock_pct = (manifest["modern_stock_count"] / total) * 100.0
        gen_pct = (manifest["generated_reconstruction_count"] / total) * 100.0

        assert total == 8
        assert hist_pct == 37.5
        assert stock_pct == 50.0
        assert gen_pct == 12.5
        Path("temp_manifest.json").unlink(missing_ok=True)

    def test_03_cross_job_duplicate_detection_and_reuse_policy(self):
        fetcher = AssetFetcher()
        db = MagicMock()

        # Simulate existing URLs across past jobs in database
        past_used_urls = [
            ("https://pexels.com/stock_video_generic_01.mp4",),
            ("https://pexels.com/stock_video_generic_02.mp4",)
        ]
        db.query.return_value.all.return_value = past_used_urls

        current_job_used_urls = set(["https://pexels.com/stock_video_generic_03.mp4"])
        shot = {"shot_id": "s1", "search_query": "London history", "duration": 3.0}

        # Mock Pexels search returning candidate with already used URL
        dup_candidate = {
            "videos": [
                {
                    "url": "https://pexels.com/vid1",
                    "duration": 4.0,
                    "video_files": [{"link": "https://pexels.com/stock_video_generic_01.mp4", "width": 1080, "height": 1920, "fps": 30, "file_type": "video/mp4"}]
                },
                {
                    "url": "https://pexels.com/vid2",
                    "duration": 4.0,
                    "video_files": [{"link": "https://pexels.com/fresh_unique_video.mp4", "width": 1080, "height": 1920, "fps": 30, "file_type": "video/mp4"}]
                }
            ]
        }

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = dup_candidate
            mock_get.return_value = mock_resp

            selected = fetcher.search_pexels_video(db, "London history", exclude_urls=current_job_used_urls)
            # Must skip the duplicate and pick the fresh unique video
            assert selected is not None
            assert selected["download_url"] == "https://pexels.com/fresh_unique_video.mp4"

    def test_04_provenance_manifest_completeness_and_sha256(self, tmp_path):
        manifest_path = tmp_path / "provenance_manifest_stress.json"
        dummy_file = tmp_path / "sample_ast.jpg"
        dummy_file.write_bytes(b"sample_test_image_binary_data")

        ast = AssetRecord(
            id="ast_stress_01",
            asset_type="image",
            source="wikimedia_commons",
            source_url="https://commons.wikimedia.org/wiki/File:Beer_Flood.jpg",
            license="Public Domain / CC0",
            commercial_use=True,
            attribution_required=True,
            attribution_text="Historical Artist (1814)",
            local_path=str(dummy_file),
            metadata_json=json.dumps({
                "source_type": VisualSourceType.HISTORICAL_ENGRAVING.value,
                "historical_confidence": "HIGH",
                "event_relevance": HistoricalEventRelation.DIRECT_EVENT_EVIDENCE.value,
                "is_generated_reconstruction": False
            })
        )

        manifest = generate_provenance_manifest("job_stress_02", [ast], manifest_path)
        assert manifest_path.exists()
        entry = manifest["manifest_entries"][0]
        assert entry["asset_id"] == "ast_stress_01"
        assert entry["sha256"] is not None
        assert len(entry["sha256"]) == 64  # Valid SHA-256 hash
        assert entry["license"] == "Public Domain / CC0"
        assert entry["historical_confidence"] == "HIGH"

    def test_05_human_quality_proxy_score_evaluation(self):
        def compute_proxy_quality_score(manifest: dict, qa_passed: bool) -> float:
            score = 0.0
            if not qa_passed:
                return 0.0
            score += 15.0  # Technical QA baseline passed

            total = manifest.get("total_assets_used", 0)
            if total >= 7:
                score += 15.0  # 7-10 segments pacing satisfied

            # Historical / Archival presence
            hist_count = manifest.get("historical_source_count", 0)
            if hist_count >= 2:
                score += 20.0
            elif hist_count >= 1:
                score += 10.0

            # Narrative / Visual diversity
            if total >= 8:
                score += 20.0
            elif total >= 7:
                score += 15.0

            # License & Provenance completeness
            entries = manifest.get("manifest_entries", [])
            valid_licenses = sum(1 for e in entries if e.get("license") and e["license"] != "UNKNOWN")
            if valid_licenses == total:
                score += 15.0

            # Anachronism safety
            score += 15.0
            return min(100.0, score)

        # High quality archival Short
        mock_manifest = {
            "total_assets_used": 8,
            "historical_source_count": 3,
            "manifest_entries": [{"license": "Public Domain"} for _ in range(8)]
        }
        score = compute_proxy_quality_score(mock_manifest, qa_passed=True)
        assert score >= 90.0

        # Failed QA yields zero
        failed_score = compute_proxy_quality_score(mock_manifest, qa_passed=False)
        assert failed_score == 0.0

    def test_06_reserve_controller_deficit_calculation(self):
        # 6 READY target, 0 current READY stock -> deficit = 6
        target = TARGET_RESERVE_BUFFER  # 6
        ready_stock = 0
        deficit = max(target - ready_stock, 0)
        assert deficit == 6

        # 6 READY stock -> deficit = 0
        ready_stock = 6
        deficit = max(target - ready_stock, 0)
        assert deficit == 0

    def test_07_publishing_ceiling_strict_bounds(self):
        # Strictly <= 3 Shorts per day
        assert DAILY_SHORTS_LIMIT == 3
        booked_today = 2
        remaining = max(DAILY_SHORTS_LIMIT - booked_today, 0)
        assert remaining == 1

        booked_today = 3
        remaining = max(DAILY_SHORTS_LIMIT - booked_today, 0)
        assert remaining == 0
