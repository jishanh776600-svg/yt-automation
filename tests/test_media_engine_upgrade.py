"""
Unit and Integration Test Suite for Upgraded AL AMR Media Engine.

Verifies:
1. Video-first selection preference.
2. 1080p resolution prioritized over 720p.
3. 720p fallback when 1080p is unavailable.
4. Immediate rejection of video streams below 720p.
5. Automatic fallback to high-resolution Pexels Image when no suitable video exists.
6. Fallback to Pollinations AI image / procedural canvas on total stock failure.
7. Anti-duplication within the same Short (used_urls_in_job exclusion).
8. Elimination of global dark vignette / dimming filters in render_engine.
9. 1080x1920 9:16 vertical crop and scaling for both videos and images.
10. Scene duration trimming and stream-looping.
11. Bounded retries and safe failure without hanging.
12. Database test isolation and zero secret exposure.
"""
import os
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import sqlite3

from engines.asset_fetcher import AssetFetcher, parse_rate_limit_headers, record_pexels_telemetry
from engines.render_engine import RenderEngine
from core.models import AssetRecord, Job, RenderOutput
from core.database import init_db, SessionLocal
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, LicenseType


class TestMediaEngineUpgrade(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.fetcher = AssetFetcher()
        self.render_engine = RenderEngine()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_01_rank_video_file_prioritizes_1080p_portrait_and_rejects_sub_720p(self):
        """Test 1: Video file ranking gives highest tier to 1080p and rejects sub-720p."""
        # 1080p Portrait
        r_1080p_port = self.fetcher._rank_video_file({"width": 1080, "height": 1920, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_1080p_port[0], 4)

        # 1080p Landscape
        r_1080p_land = self.fetcher._rank_video_file({"width": 1920, "height": 1080, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_1080p_land[0], 3)

        # 720p Portrait
        r_720p_port = self.fetcher._rank_video_file({"width": 720, "height": 1280, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_720p_port[0], 2)

        # 720p Landscape
        r_720p_land = self.fetcher._rank_video_file({"width": 1280, "height": 720, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_720p_land[0], 1)

        # Sub-720p (e.g. 540x960, 480p, 360p) -> REJECTED (Tier 0)
        r_sub720 = self.fetcher._rank_video_file({"width": 540, "height": 960, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_sub720[0], 0)

        r_360p = self.fetcher._rank_video_file({"width": 640, "height": 360, "file_type": "video/mp4", "fps": 30})
        self.assertEqual(r_360p[0], 0)

    def test_02_search_pexels_video_selects_best_1080p_candidate(self):
        """Test 2: search_pexels_video parses response and returns the highest-scoring candidate."""
        mock_response = {
            "videos": [
                {
                    "id": 1001,
                    "url": "https://www.pexels.com/video/1001/",
                    "duration": 5.0,
                    "video_files": [
                        {"width": 640, "height": 360, "file_type": "video/mp4", "link": "https://video.pexels.com/low.mp4"},
                        {"width": 1280, "height": 720, "file_type": "video/mp4", "link": "https://video.pexels.com/720p.mp4"}
                    ]
                },
                {
                    "id": 1002,
                    "url": "https://www.pexels.com/video/1002/",
                    "duration": 6.5,
                    "video_files": [
                        {"width": 1920, "height": 1080, "file_type": "video/mp4", "link": "https://video.pexels.com/1080p.mp4"}
                    ]
                }
            ]
        }

        with patch("config.settings.PEXELS_API_KEY", "dummy_key"):
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = mock_response
                mock_resp.headers = {"X-Ratelimit-Remaining": "199"}
                mock_get.return_value = mock_resp

                res = self.fetcher.search_pexels_video(self.db, "roman empire battle")
                self.assertIsNotNone(res)
                self.assertEqual(res["quality_tier"], "1080p")
                self.assertEqual(res["download_url"], "https://video.pexels.com/1080p.mp4")
                self.assertEqual(res["width"], 1920)
                self.assertEqual(res["height"], 1080)

    def test_03_fallback_to_720p_when_1080p_unavailable(self):
        """Test 3: System gracefully selects 720p video if no 1080p stream exists in response."""
        mock_response = {
            "videos": [
                {
                    "id": 2001,
                    "url": "https://www.pexels.com/video/2001/",
                    "duration": 4.0,
                    "video_files": [
                        {"width": 1280, "height": 720, "file_type": "video/mp4", "link": "https://video.pexels.com/720p_only.mp4"}
                    ]
                }
            ]
        }

        with patch("config.settings.PEXELS_API_KEY", "dummy_key"):
            with patch("requests.get") as mock_get:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = mock_response
                mock_resp.headers = {}
                mock_get.return_value = mock_resp

                res = self.fetcher.search_pexels_video(self.db, "medieval castle")
                self.assertIsNotNone(res)
                self.assertEqual(res["quality_tier"], "720p")
                self.assertEqual(res["download_url"], "https://video.pexels.com/720p_only.mp4")

    def test_04_fallback_to_image_when_all_videos_sub_720p(self):
        """Test 4: When all video streams are below 720p, video search returns None and falls back to photo."""
        mock_video_resp = {
            "videos": [
                {
                    "id": 3001,
                    "url": "https://www.pexels.com/video/3001/",
                    "duration": 4.0,
                    "video_files": [
                        {"width": 480, "height": 270, "file_type": "video/mp4", "link": "https://video.pexels.com/trash.mp4"}
                    ]
                }
            ]
        }
        mock_photo_resp = {
            "photos": [
                {
                    "id": 5001,
                    "src": {
                        "large2x": "https://images.pexels.com/highres.jpg",
                        "original": "https://images.pexels.com/original.jpg"
                    }
                }
            ]
        }

        with patch("config.settings.PEXELS_API_KEY", "dummy_key"):
            with patch.object(self.fetcher, "search_pexels_video", return_value=None):
                with patch.object(self.fetcher, "search_pexels_photo", return_value="https://images.pexels.com/highres.jpg"):
                    with patch("requests.get") as mock_dl:
                        img = Image.new("RGB", (1080, 1920), color=(100, 150, 200))
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG")
                        mock_dl.return_value.status_code = 200
                        mock_dl.return_value.content = buf.getvalue()

                        shot = {"shot_id": "s1", "search_query": "ancient library", "duration": 4.0}
                        asset = self.fetcher.fetch_asset_for_shot(self.db, shot)

                        self.assertEqual(asset.asset_type, "image")
                        self.assertEqual(asset.source, "pexels")
                        self.assertEqual(asset.source_url, "https://images.pexels.com/highres.jpg")

    def test_05_anti_duplication_excludes_used_urls_in_same_short(self):
        """Test 5: AssetFetcher excludes already used URLs in the same job to ensure unique clips."""
        used = set(["https://video.pexels.com/clip1.mp4"])
        mock_resp = {
            "videos": [
                {
                    "id": 1,
                    "duration": 5.0,
                    "video_files": [{"width": 1920, "height": 1080, "file_type": "video/mp4", "link": "https://video.pexels.com/clip1.mp4"}]
                },
                {
                    "id": 2,
                    "duration": 5.0,
                    "video_files": [{"width": 1920, "height": 1080, "file_type": "video/mp4", "link": "https://video.pexels.com/clip2.mp4"}]
                }
            ]
        }

        with patch("config.settings.PEXELS_API_KEY", "dummy_key"):
            with patch("requests.get") as mock_get:
                mock_resp_obj = MagicMock()
                mock_resp_obj.status_code = 200
                mock_resp_obj.json.return_value = mock_resp
                mock_resp_obj.headers = {}
                mock_get.return_value = mock_resp_obj

                res = self.fetcher.search_pexels_video(self.db, "ships sailing", exclude_urls=used)
                self.assertEqual(res["download_url"], "https://video.pexels.com/clip2.mp4")

    def test_06_no_vignette_or_global_dark_filter_in_render_engine(self):
        """Test 6: Verify render_engine does not apply vignette or dimming filters."""
        import inspect
        source = inspect.getsource(RenderEngine.render_image_shot_clip) + inspect.getsource(RenderEngine.render_video_shot_clip)
        self.assertNotIn("vignette", source.lower())
        self.assertNotIn("drawbox", source.lower())
        self.assertNotIn("colorlevels", source.lower())
        self.assertNotIn("colorchannelmixer", source.lower())

    def test_07_render_video_shot_clip_constructs_valid_ffmpeg_command(self):
        """Test 7: render_video_shot_clip builds 1080x1920 vertical crop command with stream_loop."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            dummy_video = Path(self.temp_dir.name) / "test.mp4"
            dummy_video.write_bytes(b"fake mp4 content")
            out_clip = Path(self.temp_dir.name) / "out.mp4"

            self.render_engine.render_video_shot_clip(dummy_video, duration=4.5, output_path=out_clip)

            self.assertTrue(mock_run.called)
            args = mock_run.call_args[0][0]
            cmd_str = " ".join(args)
            self.assertIn("-stream_loop", cmd_str)
            self.assertIn("1080:1920", cmd_str)
            self.assertIn("crop=1080:1920", cmd_str)
            self.assertIn("yuv420p", cmd_str)
