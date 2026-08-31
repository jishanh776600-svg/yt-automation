"""
Targeted Verification Suite for AL AMR Final Hardening Pass:
- Section A: OpenRouter Adapter & Provider Chain (Gemini -> Groq -> OpenRouter)
- Section B: Script-to-Audio Timing & Complete Final Sentence
- Section C: Analytics Data Truth & Unavailable vs Zero Differentiation
- Section D: Performance Learning Feedback Loop
- Section E: Dashboard Data Truth & Real Inventory Metrics
- Section F: Obsidian Knowledge Brain & Google Drive Backup
"""
import os
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from config.settings import PROJECT_ROOT, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER
from core.gemini_client import (
    GeminiClient, GroqResponse, OpenRouterResponse, GeminiQuotaExhaustedError
)
from engines.script_engine import ScriptEngine, ScriptCritic
from engines.qa_engine import QAEngine
from engines.learning_engine import LearningEngine
from engines.metrics_collector import MetricsCollector
from core.knowledge_brain import KnowledgeBrain, KNOWLEDGE_VAULT_DIR
from core.models import PerformanceSnapshot, StrategyWeight, Job, RenderOutput, AssetRecord, QAReport


class TestFinalHardeningPass(unittest.TestCase):

    # =========================================================================
    # A. PROVIDER & OPENROUTER TESTS
    # =========================================================================

    def test_01_provider_hierarchy_gemini_groq_openrouter(self):
        """Verify strict provider hierarchy: Primary -> Secondary -> Groq -> OpenRouter."""
        client = GeminiClient(
            api_key="gem_1",
            secondary_api_key="gem_2",
            groq_api_key="groq_1",
            openrouter_api_key="openrouter_1",
            sleeper=MagicMock()
        )
        providers = client._get_configured_providers()
        names = [p["name"] for p in providers]
        self.assertEqual(names, ["primary", "secondary", "groq", "openrouter"])
        self.assertNotIn("deepseek", names)

    def test_02_openrouter_fallback_when_gemini_and_groq_exhausted(self):
        """Verify fallback proceeds to OpenRouter when Gemini and Groq are exhausted."""
        client = GeminiClient(
            api_key="gem_1",
            secondary_api_key="gem_2",
            groq_api_key="groq_1",
            openrouter_api_key="openrouter_1",
            sleeper=MagicMock()
        )
        client.mark_provider_exhausted("primary")
        client.mark_provider_exhausted("secondary")
        client.mark_provider_exhausted("groq")

        client._execute_openrouter_request = MagicMock(return_value=OpenRouterResponse("OpenRouter Success Output"))

        resp = client.generate_content("model", "test prompt")
        self.assertEqual(resp.text, "OpenRouter Success Output")
        self.assertEqual(client.active_provider, "openrouter")

    def test_03_openrouter_401_fails_fast_and_marks_exhausted(self):
        """Verify OpenRouter HTTP 401 fails fast and marks provider exhausted."""
        from urllib.error import HTTPError
        from io import BytesIO

        client = GeminiClient(
            api_key="", secondary_api_key="", groq_api_key="", openrouter_api_key="bad_key",
            sleeper=MagicMock()
        )

        def mock_401(*args, **kwargs):
            raise HTTPError(
                url="https://openrouter.ai/api/v1/chat/completions",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=BytesIO(b'{"error": {"message": "Invalid API Key"}}')
            )

        with patch("urllib.request.urlopen", side_effect=mock_401):
            with self.assertRaises(GeminiQuotaExhaustedError):
                client._execute_openrouter_request("bad_key", "model", "prompt")

        self.assertTrue(client.is_provider_exhausted("openrouter"))

    def test_04_openrouter_response_compatibility(self):
        """Verify OpenRouterResponse matches expected .text interface."""
        resp = OpenRouterResponse("Valid completion text")
        self.assertEqual(resp.text, "Valid completion text")
        self.assertIn("<OpenRouterResponse", repr(resp))

    # =========================================================================
    # B. SCRIPT RETENTION & TIMING TESTS
    # =========================================================================

    def test_05_qa_rejects_audio_exceeding_safe_video_boundary(self):
        """Verify QA rejects any video where voice duration exceeds (video_duration - 0.6s)."""
        qa = QAEngine()
        db_mock = MagicMock()
        db_mock.query().filter().count.return_value = 0
        job_mock = MagicMock(id="job_qa_timing_test")
        render_mock = MagicMock(video_path="test_video.mp4", duration_sec=23.0)

        # Voice asset is 22.8s, video is 23.0s -> only 0.2s margin (fails 0.6s required margin)
        voice_asset = MagicMock(asset_type="voice", duration_sec=22.8)
        assets = [voice_asset]

        qa.inspect_media = MagicMock(return_value={
            "width": 1080, "height": 1920, "duration": 23.0, "has_video": True, "has_audio": True
        })
        qa.analyze_audio_stream = MagicMock(return_value={
            "is_silent": False, "has_clipping": False, "integrated_lufs": -14.0,
            "bgm_identity_verified": True, "bgm_audible": True, "bgm_fingerprint_score": 0.90, "max_volume_db": -1.0
        })

        with patch("pathlib.Path.exists", return_value=True), patch("pathlib.Path.stat") as mock_stat:
            mock_stat.return_value = MagicMock(st_size=2_000_000)
            passed, report = qa.run_qa(db_mock, job_mock, render_mock, assets)

        self.assertFalse(passed)
        self.assertIn("Narration truncation risk", report.failure_reasons)

    def test_06_critic_evaluates_5_part_retention_structure(self):
        """Verify script critic evaluates 5-part retention structure including complete resolution."""
        critic = ScriptCritic()
        script = {
            "hook": "In 1896, the shortest war in history lasted thirty-eight minutes.",
            "context": "A rebel sultan seized power in Zanzibar against British orders.",
            "escalation": "Three Royal Navy warships bombarded the palace with explosive shells.",
            "reveal": "Five hundred defenders fell before the sultan fled the ruined harbor.",
            "loop_twist": "By morning tea, British forces had completely secured the island."
        }
        eval_res = critic.evaluate(script)
        self.assertTrue(eval_res.passed)
        self.assertGreater(eval_res.score, 70.0)

    # =========================================================================
    # C. ANALYTICS DATA TRUTH TESTS
    # =========================================================================

    def test_07_metrics_collector_preserves_none_for_unavailable_metrics(self):
        """Verify metrics collector sets None (not 0.0) when YouTube Analytics data is unavailable."""
        collector = MetricsCollector()
        db_mock = MagicMock()
        upload_mock = MagicMock(id="up_1", youtube_video_id="REAL_YT_ID", published_at=datetime.utcnow() - timedelta(days=2))

        mock_data_api = MagicMock()
        mock_data_api.videos().list().execute.return_value = {
            "items": [{"statistics": {"viewCount": "1250", "likeCount": "85", "commentCount": "12"}}]
        }

        # Mock yt_analytics as None (missing Analytics API scope)
        collector.get_youtube_clients = MagicMock(return_value=(mock_data_api, None))

        snapshot = collector.collect_for_upload(db_mock, upload_mock)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.views, 1250)
        self.assertEqual(snapshot.likes, 85)
        self.assertIsNone(snapshot.average_view_percentage)
        self.assertIsNone(snapshot.average_view_duration_sec)

    # =========================================================================
    # D. LEARNING FEEDBACK LOOP TESTS
    # =========================================================================

    def test_08_learning_engine_respects_evidence_thresholds(self):
        """Verify learning engine requires sufficient sample count before adjusting strategy weights."""
        learner = LearningEngine(min_evidence_threshold=3, usable_evidence_threshold=5)
        db_mock = MagicMock()

        # Weight with sample count = 1 (Insufficient evidence)
        w_insufficient = StrategyWeight(
            id="w1", feature_type="hook_archetype", feature_value="CONTRADICTION",
            sample_count=1, relative_lift=25.0, weight=1.0, confidence_level="INSUFFICIENT_EVIDENCE"
        )
        db_mock.query().filter().order_by().all.return_value = []

        profile = learner.get_learned_production_profile(db_mock)
        self.assertEqual(profile, "")

        # Weight with mature sample count >= 3
        w_mature = StrategyWeight(
            id="w2", feature_type="hook_archetype", feature_value="DATE_TIME_ANCHOR",
            sample_count=5, relative_lift=18.5, weight=1.35, confidence_level="HIGH_CONFIDENCE"
        )
        db_mock.query().filter().order_by().all.return_value = [w_mature]

        profile_mature = learner.get_learned_production_profile(db_mock)
        self.assertIn("DATE_TIME_ANCHOR", profile_mature)
        self.assertIn("Stayed-to-Watch", profile_mature)

    # =========================================================================
    # E. DASHBOARD DATA TRUTH TESTS
    # =========================================================================

    def test_09_dashboard_displays_real_inventory_and_published_counts(self):
        """Verify dashboard data provider sources metrics from verified records."""
        from dashboard.data_provider import SystemDataProvider
        dp = SystemDataProvider()
        dp.drive_engine = MagicMock()
        dp.drive_engine.get_ready_stock_count.return_value = 4

        buffer_status = dp.get_buffer_status()
        self.assertEqual(buffer_status["ready_stock"], 4)
        self.assertEqual(buffer_status["target_reserve"], 6)
        self.assertEqual(buffer_status["needed_replenishment"], 2)

    # =========================================================================
    # F. OBSIDIAN KNOWLEDGE BRAIN TESTS
    # =========================================================================

    def test_10_obsidian_knowledge_vault_generation_and_invariants(self):
        """Verify Obsidian knowledge brain generates structured Markdown notes with live invariants."""
        kb = KnowledgeBrain(vault_dir=PROJECT_ROOT / "data" / "knowledge")
        files = kb.build_all_knowledge_notes()

        self.assertTrue(len(files) >= 4)
        index_content = (PROJECT_ROOT / "data" / "knowledge" / "Index.md").read_text(encoding="utf-8")
        self.assertIn("af_bella", index_content)
        self.assertIn("Daily Publishing Limit", index_content)
        self.assertIn("Target Reserve Buffer", index_content)
        self.assertIn("OpenRouter", index_content)

        voice_content = (PROJECT_ROOT / "data" / "knowledge" / "Voice" / "af_bella_canonical.md").read_text(encoding="utf-8")
        self.assertIn("af_bella", voice_content)
        self.assertIn("Kokoro-v1.0 ONNX", voice_content)

    def test_11_obsidian_backup_excludes_credentials_and_binaries(self):
        """Verify Google Drive backup of Obsidian knowledge vault never includes credentials or binaries."""
        kb = KnowledgeBrain(vault_dir=PROJECT_ROOT / "data" / "knowledge")
        drive_mock = MagicMock()
        drive_mock.ensure_folder_exists.return_value = "folder_123"

        res = kb.backup_to_drive(drive_mock)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertTrue(len(res["files_backed_up"]) >= 4)

        # Verify all uploaded files are markdown/json and no secret files
        for f in res["files_backed_up"]:
            self.assertTrue(f.endswith(".md") or f.endswith(".json"))
            self.assertNotIn(".env", f)
            self.assertNotIn("token", f.lower())
            self.assertNotIn("secret", f.lower())

    def test_12_af_bella_canonical_voice_consistency(self):
        """Verify af_bella is the canonical voice across settings and TTS engine."""
        from engines.tts_engine import get_authoritative_voice
        self.assertEqual(KOKORO_VOICE, "af_bella")
        self.assertEqual(get_authoritative_voice(), "af_bella")


if __name__ == "__main__":
    unittest.main()
