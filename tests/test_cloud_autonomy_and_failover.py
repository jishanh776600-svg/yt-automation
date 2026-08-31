import os
import json
import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from config.settings import PROJECT_ROOT
from core.gemini_client import GeminiClient, GeminiQuotaExhaustedError
from core.database_sync import compute_sha256, verify_sqlite_integrity


class TestCloudAutonomyAndFailover:

    def test_01_workflow_secret_wiring_parity(self):
        required_secrets = [
            "GEMINI_API_KEY",
            "GEMINI_API_KEY_SECONDARY",
            "GROQ_API_KEY",
            "OPENROUTER_API_KEY",
            "TOKEN_JSON",
            "CLIENT_SECRET_JSON"
        ]
        workflows = ["produce_buffer.yml", "autopilot.yml", "harvest_analytics.yml"]
        for wf_name in workflows:
            wf_path = PROJECT_ROOT / ".github" / "workflows" / wf_name
            assert wf_path.exists(), f"Workflow {wf_name} missing"
            content = wf_path.read_text(encoding="utf-8")
            for sec in required_secrets:
                pattern = "${{ secrets." + sec + " }}"
                assert pattern in content, f"Workflow {wf_name} is missing secret reference {sec}"

    def test_02_cron_schedules_utc_alignment(self):
        p_wf = (PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml").read_text(encoding="utf-8")
        assert "0 2 * * *" in p_wf

        a_wf = (PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml").read_text(encoding="utf-8")
        assert "0 6,11,15 * * *" in a_wf

        h_wf = (PROJECT_ROOT / ".github" / "workflows" / "harvest_analytics.yml").read_text(encoding="utf-8")
        assert "0 3 * * *" in h_wf

    def test_03_ai_provider_cascade_routing_and_exhaustion(self):
        client = GeminiClient()
        mock_providers = [
            {"name": "primary", "type": "gemini", "api_key": "k_prim", "model": "gemini-3.6-flash"},
            {"name": "secondary", "type": "gemini", "api_key": "k_sec", "model": "gemini-3.6-flash"},
            {"name": "groq", "type": "groq", "api_key": "k_groq", "model": "llama-3.3-70b-versatile"},
            {"name": "openrouter", "type": "openrouter", "api_key": "k_open", "model": "meta-llama/llama-3.3-70b-instruct:free"}
        ]

        attempt_log = []

        def fake_gemini(api_key, model, contents, **kwargs):
            provider_name = kwargs.get("provider_name", "unknown")
            attempt_log.append(f"gemini_{provider_name}")
            raise GeminiQuotaExhaustedError(f"{provider_name} daily limit reached")

        def fake_groq(api_key, model, contents, **kwargs):
            attempt_log.append("groq")
            raise GeminiQuotaExhaustedError("groq rate limit reached")

        def fake_openrouter(api_key, model, contents, **kwargs):
            attempt_log.append("openrouter")
            raise GeminiQuotaExhaustedError("openrouter daily limit reached")

        with patch.object(client, "_get_configured_providers", return_value=mock_providers), \
             patch.object(client, "_execute_request", side_effect=fake_gemini), \
             patch.object(client, "_execute_groq_request", side_effect=fake_groq), \
             patch.object(client, "_execute_openrouter_request", side_effect=fake_openrouter):

            with pytest.raises(GeminiQuotaExhaustedError) as exc_info:
                client.generate_content(model="gemini-3.6-flash", contents="test prompt")

            assert "All configured AI providers" in str(exc_info.value)
            assert attempt_log == ["gemini_primary", "gemini_secondary", "groq", "openrouter"]

    def test_04_groq_fallback_response_formatting(self):
        client = GeminiClient()
        fake_json = json.dumps({
            "choices": [
                {"message": {"content": "This is generated content from Groq model."}}
            ]
        }).encode("utf-8")

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = io.BytesIO(fake_json)
        mock_cm.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_cm):
            res = client._execute_groq_request(
                api_key="fake_groq_key",
                model="llama-3.3-70b-versatile",
                contents="Generate a hook",
                max_retries=1
            )
            assert res is not None
            assert res.text == "This is generated content from Groq model."

    def test_05_openrouter_fallback_response_formatting(self):
        client = GeminiClient()
        fake_json = json.dumps({
            "choices": [
                {"message": {"content": "This is generated content from OpenRouter model."}}
            ]
        }).encode("utf-8")

        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = io.BytesIO(fake_json)
        mock_cm.__exit__.return_value = None

        with patch("urllib.request.urlopen", return_value=mock_cm):
            res = client._execute_openrouter_request(
                api_key="fake_openrouter_key",
                model="meta-llama/llama-3.3-70b-instruct:free",
                contents="Generate a hook",
                max_retries=1
            )
            assert res is not None
            assert res.text == "This is generated content from OpenRouter model."

    def test_06_database_sync_checksum_and_integrity_guard(self, tmp_path):
        valid_db = tmp_path / "valid.db"
        import sqlite3
        conn = sqlite3.connect(str(valid_db))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'ok')")
        conn.commit()
        conn.close()

        is_valid, msg = verify_sqlite_integrity(valid_db)
        assert is_valid is True
        assert msg == "ok"

        sha1 = compute_sha256(valid_db)
        assert len(sha1) == 64

        corrupt_db = tmp_path / "corrupt.db"
        corrupt_db.write_bytes(b"INVALID_HEADER_AND_CORRUPT_BYTES" * 100)
        is_corrupt_valid, corrupt_msg = verify_sqlite_integrity(corrupt_db)
        assert is_corrupt_valid is False

    def test_07_oauth_missing_analytics_scope_honesty(self):
        from engines.metrics_collector import MetricsCollector
        from core.models import UploadRecord

        collector = MetricsCollector()
        mock_upload = MagicMock(spec=UploadRecord)
        mock_upload.id = "upl_test_001"
        mock_upload.youtube_video_id = "REAL_YT_ID11"
        mock_upload.created_at = None
        mock_upload.published_at = None

        mock_yt_data = MagicMock()
        mock_yt_data.videos.return_value.list.return_value.execute.return_value = {
            "items": [{"statistics": {"viewCount": "1500", "likeCount": "85", "commentCount": "12"}}]
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch.object(collector, "get_youtube_clients", return_value=(mock_yt_data, None)):
            res = collector.collect_for_upload(mock_db, mock_upload)
            assert res is not None
            assert res.views == 1500
            assert res.likes == 85
            assert res.comments == 12
            assert res.average_view_percentage is None
            assert res.average_view_duration_sec is None
            assert res.estimated_minutes_watched is None

    def test_08_batch_production_failure_semantics_exit_codes(self):
        from main import ShortsPipeline
        from config.constants import JobState

        cli = ShortsPipeline()
        mock_db = MagicMock()
        mock_job = MagicMock()
        mock_job.id = "job_test_block"
        mock_job.state = JobState.QUEUED.value

        with patch.object(cli, "produce_single_to_vault", side_effect=GeminiQuotaExhaustedError("All providers exhausted")), \
             patch("main.StateMachine.transition"), \
             patch("main.StateMachine.flag_needs_review"), \
             patch("main.ProcessLock"):

            produced, summary = cli.produce_batch(count=1)
            assert produced == 0
            assert summary["outcome"] == "BLOCKED"
            assert summary["block_reason"] == "ALL_AI_PROVIDERS_EXHAUSTED"
