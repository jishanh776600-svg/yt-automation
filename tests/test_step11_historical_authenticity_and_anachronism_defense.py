import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.constants import VisualSourceType, HistoricalEventRelation, LicenseType
from core.models import AssetRecord
from engines.asset_fetcher import AssetFetcher, classify_visual_provenance
from engines.storyboard_engine import StoryboardEngine


class TestStep11HistoricalAuthenticityAndAnachronismDefense:

    def test_01_visual_source_type_taxonomy(self):
        # 1. Historical engraving query
        engraving_meta = classify_visual_provenance(
            query="London 1814 brewery disaster historical engraving",
            prompt="Vintage historical engraving of brewery",
            source="pexels"
        )
        assert engraving_meta["source_type"] == VisualSourceType.HISTORICAL_ENGRAVING.value
        assert engraving_meta["historical_confidence"] == "HIGH"
        assert engraving_meta["is_generated_reconstruction"] is False

        # 2. Historical map / document
        map_meta = classify_visual_provenance(
            query="19th century London city map historical document",
            prompt="Vintage map of London",
            source="pexels"
        )
        assert map_meta["source_type"] in (
            VisualSourceType.HISTORICAL_MAP.value, VisualSourceType.HISTORICAL_DOCUMENT.value
        )
        assert map_meta["historical_confidence"] == "HIGH"

        # 3. Modern contextual stock video
        video_meta = classify_visual_provenance(
            query="dark brewing beer liquid splashing motion",
            prompt="Dramatic slow motion beer vat",
            source="pexels_video",
            is_video=True
        )
        assert video_meta["source_type"] == VisualSourceType.MODERN_CONTEXTUAL_STOCK.value
        assert video_meta["is_generated_reconstruction"] is False

    def test_02_generated_reconstruction_is_never_labeled_archival(self):
        ai_meta = classify_visual_provenance(
            query="The Great Molasses Flood 1919 wave destruction",
            prompt="Historical documentary reconstruction of 1919 Boston molasses wave",
            source="pollinations_ai",
            is_video=False
        )

        assert ai_meta["source_type"] == VisualSourceType.GENERATED_RECONSTRUCTION.value
        assert ai_meta["is_generated_reconstruction"] is True
        assert ai_meta["historical_confidence"] == "PLAUSIBLE_RECONSTRUCTION"
        assert ai_meta["source_type"] != VisualSourceType.ARCHIVAL_PHOTO.value
        assert ai_meta["source_type"] != VisualSourceType.ARCHIVAL_VIDEO.value

    def test_03_historical_event_matching_and_era_context(self):
        # Specific historical event
        event_meta = classify_visual_provenance(
            query="London Beer Flood 1814 vat collapse",
            prompt="Historical brewery scene 1814",
            source="pexels"
        )
        assert event_meta["event_relevance"] == HistoricalEventRelation.EVENT_RELATED_HISTORICAL_CONTEXT.value

        # Era context
        era_meta = classify_visual_provenance(
            query="19th century vintage street cobblestone",
            prompt="Historical street in 19th century",
            source="pexels"
        )
        assert era_meta["event_relevance"] == HistoricalEventRelation.ERA_CONTEXT.value

    def test_04_anachronism_defense_detects_modern_contradictions(self):
        # Modern vehicle in historical prompt
        anachronistic_meta = classify_visual_provenance(
            query="1814 london streets with modern car and neon signs",
            prompt="Historical street with modern car",
            source="pexels"
        )
        assert anachronistic_meta["has_anachronism_risk"] is True
        assert "modern car" in anachronistic_meta["anachronisms_detected"]
        assert "neon" in anachronistic_meta["anachronisms_detected"]

        # Clean historical prompt
        clean_meta = classify_visual_provenance(
            query="1814 London Tottenham Court Road brewery wooden vat",
            prompt="Historical brewery scene with wooden barrels",
            source="pexels"
        )
        assert clean_meta["has_anachronism_risk"] is False
        assert len(clean_meta["anachronisms_detected"]) == 0

    def test_05_asset_metadata_json_persistence_in_database(self):
        fetcher = AssetFetcher()
        db = MagicMock()

        shot = {
            "shot_id": "shot_hist_01",
            "search_query": "London 1814 historical engraving brewery",
            "visual_prompt": "Vintage engraving of London brewery",
            "duration": 3.0
        }

        with patch.object(fetcher, "search_pexels_video", return_value=None), \
             patch.object(fetcher, "search_pexels_photo", return_value="https://pexels.com/photo_hist.jpg"), \
             patch("requests.get") as mock_get, \
             patch.object(fetcher, "crop_to_vertical_9_16") as mock_crop:

            mock_crop.return_value = Path("dummy_path.jpg")
            mock_get.return_value.content = b"fake_photo_bytes"

            asset_rec = fetcher.fetch_asset_for_shot(db, shot)

            assert asset_rec.metadata_json is not None
            parsed_meta = json.loads(asset_rec.metadata_json)
            assert "source_type" in parsed_meta
            assert "historical_confidence" in parsed_meta
            assert "event_relevance" in parsed_meta
            assert "is_generated_reconstruction" in parsed_meta
            assert parsed_meta["source_type"] == VisualSourceType.HISTORICAL_ENGRAVING.value

    def test_06_procedural_canvas_marked_abstract_atmospheric(self):
        procedural_meta = classify_visual_provenance(
            query="fallback procedural background",
            prompt="Abstract dark atmospheric background",
            source="procedural_canvas"
        )
        assert procedural_meta["source_type"] == VisualSourceType.ABSTRACT_ATMOSPHERIC.value
        assert procedural_meta["historical_confidence"] == "LOW"
        assert procedural_meta["is_generated_reconstruction"] is False
