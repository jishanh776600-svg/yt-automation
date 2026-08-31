import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.constants import VisualSourceType, HistoricalEventRelation, LicenseType
from core.models import AssetRecord
from engines.asset_fetcher import AssetFetcher, generate_provenance_manifest


class TestStep12ArchivalIngestionAndVisualQuality3:

    def test_01_wikimedia_commons_archival_ingestion_priority(self):
        fetcher = AssetFetcher()
        db = MagicMock()
        db.query.return_value.all.return_value = []

        shot = {
            "shot_id": "shot_archival_01",
            "search_query": "London Beer Flood 1814 historical engraving brewery",
            "visual_prompt": "Vintage engraving of the 1814 London brewery disaster",
            "duration": 3.0
        }

        mock_wiki = {
            "download_url": "https://upload.wikimedia.org/wikipedia/commons/beer_flood_1814.jpg",
            "title": "File:Beer_flood_1814.jpg",
            "artist": "Thomas Rowlandson (1814)",
            "license": "Public Domain",
            "width": 1600,
            "height": 1200
        }

        with patch.object(fetcher, "search_wikimedia_commons", return_value=mock_wiki), \
             patch("requests.get") as mock_get, \
             patch.object(fetcher, "crop_to_vertical_9_16") as mock_crop:

            mock_crop.return_value = Path("dummy_crop.jpg")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"fake_archival_jpg_content_here_exceeding_5000_bytes" * 200
            mock_get.return_value = mock_resp

            asset = fetcher.fetch_asset_for_shot(db, shot)

            assert asset.source == "wikimedia_commons"
            assert asset.attribution_required is True
            assert "Rowlandson" in asset.attribution_text
            assert asset.metadata_json is not None
            prov = json.loads(asset.metadata_json)
            assert prov["source_type"] == VisualSourceType.HISTORICAL_ENGRAVING.value
            assert prov["historical_confidence"] == "HIGH"

    def test_02_wikimedia_search_rejects_non_commercial_licenses(self):
        fetcher = AssetFetcher()
        db = MagicMock()
        db.query.return_value.all.return_value = []

        fake_api_response = {
            "query": {
                "pages": {
                    "101": {
                        "title": "File:Restricted_Image.jpg",
                        "imageinfo": [{
                            "url": "https://upload.wikimedia.org/restricted.jpg",
                            "width": 1200,
                            "height": 1600,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC-BY-NC-4.0"},
                                "Artist": {"value": "Restricted Author"}
                            }
                        }]
                    }
                }
            }
        }

        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_api_response
            mock_get.return_value = mock_resp

            # Restricted NC license must be rejected and return None
            res = fetcher.search_wikimedia_commons(db, "London 1814 restricted")
            assert res is None

    def test_03_provenance_manifest_generation_and_checksums(self, tmp_path):
        manifest_path = tmp_path / "provenance_manifest_test.json"
        dummy_file = tmp_path / "sample_img.jpg"
        dummy_file.write_bytes(b"sample_test_image_data_bytes")

        ast1 = AssetRecord(
            id="ast_001",
            asset_type="image",
            source="wikimedia_commons",
            source_url="https://commons.wikimedia.org/sample.jpg",
            license="Public Domain / CC0",
            commercial_use=True,
            attribution_required=True,
            attribution_text="Historical Engraver (1814)",
            local_path=str(dummy_file),
            metadata_json=json.dumps({
                "source_type": VisualSourceType.HISTORICAL_ENGRAVING.value,
                "historical_confidence": "HIGH",
                "event_relevance": HistoricalEventRelation.EVENT_RELATED_HISTORICAL_CONTEXT.value,
                "is_generated_reconstruction": False
            })
        )

        ast2 = AssetRecord(
            id="ast_002",
            asset_type="video",
            source="pexels_video",
            source_url="https://pexels.com/sample_vid.mp4",
            license=LicenseType.PEXELS_LICENSE.value,
            commercial_use=True,
            local_path=str(dummy_file),
            metadata_json=json.dumps({
                "source_type": VisualSourceType.MODERN_CONTEXTUAL_STOCK.value,
                "historical_confidence": "MEDIUM",
                "event_relevance": HistoricalEventRelation.ERA_CONTEXT.value,
                "is_generated_reconstruction": False
            })
        )

        manifest = generate_provenance_manifest(
            job_id="job_manifest_test_01",
            assets_used=[ast1, ast2],
            output_path=manifest_path
        )

        assert manifest_path.exists()
        assert manifest["job_id"] == "job_manifest_test_01"
        assert manifest["total_assets_used"] == 2
        assert manifest["historical_source_count"] == 1
        assert manifest["modern_stock_count"] == 1
        assert len(manifest["manifest_entries"]) == 2
        assert manifest["manifest_entries"][0]["sha256"] is not None
        assert manifest["manifest_entries"][0]["source_type"] == VisualSourceType.HISTORICAL_ENGRAVING.value

    def test_04_archival_fallback_hierarchy(self):
        fetcher = AssetFetcher()
        db = MagicMock()
        db.query.return_value.all.return_value = []

        shot = {
            "shot_id": "shot_fb_01",
            "search_query": "abstract mysterious historical phenomenon",
            "visual_prompt": "Cinematic historical documentary scene",
            "duration": 3.0
        }

        mock_p_video = {
            "download_url": "https://pexels.com/video_1080p.mp4",
            "quality_tier": "1080p",
            "width": 1080,
            "height": 1920,
            "duration": 4.0
        }

        # If not explicit archival, Pexels video is primary
        with patch.object(fetcher, "search_pexels_video", return_value=mock_p_video), \
             patch("requests.get") as mock_get, \
             patch("pathlib.Path.stat") as mock_stat:

            mock_stat.return_value.st_size = 250000
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.iter_content.return_value = [b"video_bytes"]
            mock_get.return_value = mock_resp

            asset = fetcher.fetch_asset_for_shot(db, shot)
            assert asset.source == "pexels_video"
            assert asset.asset_type == "video"
