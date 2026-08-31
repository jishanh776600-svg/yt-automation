"""
Targeted Production Reliability and Vault Repair Test Suite.
Tests canonical READY inventory validation, poison-pill quarantine,
refill calculations, Step 7 fail-fast behavior, voice parity for af_bella,
and narration completeness.
"""
import pytest
import uuid
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from core.database import SessionLocal, init_db
from core.models import Job, Topic, RenderOutput, UploadRecord, QAReport, SystemConfig
from engines.drive_engine import DriveVaultEngine, is_valid_ready_short, MIN_VALID_SHORT_BYTES
from engines.tts_engine import AVAILABLE_VOICES, get_active_voice, resolve_voice_config, set_active_voice
from engines.upload_engine import UploadEngine
from engines.qa_engine import QAEngine
from dashboard.action_manager import ActionManager
from dashboard.data_provider import SystemDataProvider
from config.constants import JobState, DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# 1. CANONICAL VALID READY INVENTORY TESTS
# ==============================================================================

def test_ready_validator_rejects_tiny_file(tmp_path):
    """Verifies that an MP4 file smaller than 5 MB is rejected as abnormally small."""
    tiny_mp4 = tmp_path / "short_tiny_1080x1920.mp4"
    tiny_mp4.write_bytes(b"0" * 1100)  # 1.1 KB (like the 9 files found in Drive)

    is_val, reason = is_valid_ready_short(tiny_mp4, allow_test_artifacts=False)
    assert not is_val
    assert "abnormally small" in reason


def test_ready_validator_rejects_test_artifact_filename(tmp_path):
    """Verifies that files with test/manifest prefixes are rejected when allow_test_artifacts=False."""
    test_mp4 = tmp_path / "test_render_1080x1920.mp4"
    test_mp4.write_bytes(b"0" * (6 * 1024 * 1024))  # 6 MB

    is_val, reason = is_valid_ready_short(test_mp4, allow_test_artifacts=False)
    assert not is_val
    assert "Test artifact filename" in reason


def test_ready_validator_drive_dict_evaluates_correctly(db_session):
    """Verifies that Google Drive file dict items are correctly accepted or rejected based on metadata."""
    # 1. Tiny test dummy (1,100 bytes)
    dummy_item = {
        "id": "drive_dummy_001",
        "name": "short_job_manifest_e582075b_1080x1920.mp4",
        "size": "1100",
        "properties": {"job_id": "job_test_123"}
    }
    is_val, reason = is_valid_ready_short(dummy_item, db=db_session, allow_test_artifacts=False)
    assert not is_val
    assert "Test artifact" in reason or "small" in reason

    # 2. Legitimate production video in Drive metadata (28 MB, real job)
    legit_item = {
        "id": "drive_legit_001",
        "name": "short_job_real_86d709dd_1080x1920.mp4",
        "size": str(28 * 1024 * 1024),
        "properties": {"job_id": "job_real_86d709dd", "topic_id": "top_krakatoa"}
    }
    is_val, reason = is_valid_ready_short(legit_item, db=db_session, allow_test_artifacts=False)
    assert is_val
    assert "Valid Google Drive READY Short" in reason

    # 3. Already-published job is rejected
    pub_record = UploadRecord(
        id="upl_test_pub",
        job_id="job_real_86d709dd",
        title="The Eruption of Krakatoa",
        description="Historic volcanic explosion",
        tags="history,volcano",
        privacy_status="public",
        status="PUBLISHED",
        youtube_video_id="yt_vid_abc123"
    )
    db_session.add(pub_record)
    db_session.commit()

    is_val_pub, reason_pub = is_valid_ready_short(legit_item, db=db_session, allow_test_artifacts=False)
    assert not is_val_pub
    assert "already published" in reason_pub


def test_inventory_count_rejects_poison_pills_and_calculates_true_deficit(monkeypatch):
    """
    Verifies that 1 valid READY file + 5 invalid/1KB dummy files results in:
    valid_stock = 1 / 6 (NOT 6 / 6), and deficit = 5 (NOT 0).
    """
    drive_engine = DriveVaultEngine()

    mock_drive_files = [
        {"id": "valid_01", "name": "short_job_001_1080x1920.mp4", "size": str(25 * 1024 * 1024), "properties": {"job_id": "job_001"}},
        {"id": "dummy_01", "name": "test_render_1080x1920.mp4", "size": "1050", "properties": {}},
        {"id": "dummy_02", "name": "short_job_manifest_1080x1920.mp4", "size": "1100", "properties": {}},
        {"id": "dummy_03", "name": "test_render_1080x1920.mp4", "size": "1050", "properties": {}},
        {"id": "dummy_04", "name": "short_job_manifest_1080x1920.mp4", "size": "1100", "properties": {}},
        {"id": "dummy_05", "name": "test_render_1080x1920.mp4", "size": "1050", "properties": {}},
    ]

    monkeypatch.setattr(drive_engine, "inspect_or_init_vault", lambda create_if_missing=False: {"01_READY": "f_ready"})
    monkeypatch.setattr(drive_engine, "list_files_in_folder", lambda folder: mock_drive_files)

    valid_stock = drive_engine.get_ready_stock_count(allow_test_artifacts=False)
    assert valid_stock == 1, f"Expected 1 valid stock, got {valid_stock}"

    deficit = max(0, TARGET_RESERVE_BUFFER - valid_stock)
    assert deficit == 5, f"Expected deficit 5, got {deficit}"


# ==============================================================================
# 2. STEP 7 FAIL-FAST AND DEEPSEEK 401 EXHAUSTION
# ==============================================================================

def test_deepseek_401_fails_fast_and_marks_exhausted(monkeypatch):
    """Verifies that an HTTP 401 on DeepSeek immediately marks the provider exhausted."""
    from core.gemini_client import GeminiClient, GeminiQuotaExhaustedError
    import urllib.error

    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy_key")
    client = GeminiClient()
    assert not client.is_provider_exhausted("deepseek")

    # Simulate HTTP 401 error
    err_fp = MagicMock()
    err_fp.read.return_value = b'{"status":401,"title":"Unauthorized","detail":"Authentication failed"}'
    http_401 = urllib.error.HTTPError(
        url="https://api.deepseek.com/chat/completions",
        code=401,
        msg="Unauthorized",
        hdrs={},
        fp=err_fp
    )

    with patch("urllib.request.urlopen", side_effect=http_401):
        with pytest.raises(GeminiQuotaExhaustedError) as exc_info:
            client._execute_deepseek_request(
                api_key="dummy_key",
                contents=[{"role": "user", "parts": [{"text": "Reply with test"}]}],
                model="deepseek-chat",
                temperature=0.7,
                max_tokens=100
            )

    assert "401" in str(exc_info.value)
    # The crucial check: provider must now be marked exhausted permanently for this session
    assert client.is_provider_exhausted("deepseek")


# ==============================================================================
# 3. POISON PILL QUARANTINE (NO RETURN TO 01_READY)
# ==============================================================================

def test_publication_safety_gate_failure_quarantines_to_04_failed(tmp_path, db_session):
    """Verifies that an invalid file blocked by the safety gate is moved to 04_FAILED, never back to 01_READY."""
    from main import ShortsPipeline
    pipeline = ShortsPipeline()

    mock_drive = MagicMock()
    pipeline.drive_engine = mock_drive

    # Create dummy 1KB file in processing
    dummy_path = tmp_path / "dummy_1080x1920.mp4"
    dummy_path.write_bytes(b"0" * 1100)
    mock_drive.download_video_from_vault.return_value = dummy_path

    # Call _schedule_single_drive_file
    future_slot = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)
    target_file = {"id": "drive_corrupt_file_99", "name": "short_corrupt_1080x1920.mp4"}
    res = pipeline._schedule_single_drive_file(
        db=db_session,
        target_file=target_file,
        scheduled_slot=future_slot,
        current_folder="02_PROCESSING"
    )

    assert res is None
    # Crucial check: must have moved to 04_FAILED, NOT 01_READY
    mock_drive.move_file_in_vault.assert_called_with(
        "drive_corrupt_file_99",
        from_folder="02_PROCESSING",
        to_folder="04_FAILED"
    )


# ==============================================================================
# 4. PERMANENT CANONICAL VOICE af_bella PARITY
# ==============================================================================

def test_voice_registry_af_bella_parity(db_session):
    """
    Verifies that af_bella is the top voice, canonical default,
    and resolves consistently across DB, TTS, and settings.
    """
    # 1. First voice in registry is af_bella
    assert AVAILABLE_VOICES[0]["id"] == "af_bella"
    assert AVAILABLE_VOICES[0]["kokoro_voice"] == "af_bella"

    # 2. Default resolver fallback is af_bella
    resolved = resolve_voice_config("unknown_voice_id")
    assert resolved["id"] == "af_bella"

    # 3. get_active_voice defaults to af_bella when no DB config exists
    assert get_active_voice(db_session) == "af_bella"

    # 4. Setting and retrieving active voice in DB works and persists
    set_active_voice(db_session, "af_bella")
    assert get_active_voice(db_session) == "af_bella"


# ==============================================================================
# 5. NARRATION COMPLETENESS & SAFETY MARGIN QA CHECK
# ==============================================================================

def test_qa_rejects_audio_extending_beyond_video(tmp_path, db_session):
    """Verifies that QAEngine rejects video when voice duration extends beyond safe margin."""
    qa = QAEngine()

    dummy_video = tmp_path / "test_video.mp4"
    dummy_video.write_bytes(b"0" * (10 * 1024 * 1024))

    job = Job(id="job_narr_test", state=JobState.QA.value)
    db_session.add(job)

    render = RenderOutput(
        id="rnd_narr_test",
        job_id=job.id,
        video_path=str(dummy_video),
        width=1080,
        height=1920,
        duration_sec=23.0,
        file_size_bytes=dummy_video.stat().st_size
    )
    db_session.add(render)

    # Voice narration duration = 23.2s (exceeds video duration 23.0s!)
    from core.models import AssetRecord
    voice_asset = AssetRecord(
        id="asset_voice_001",
        asset_type="voice",
        source="kokoro",
        local_path=str(dummy_video),
        duration_sec=23.2
    )
    music_asset = AssetRecord(
        id="asset_music_001",
        asset_type="music",
        source="local",
        local_path=str(dummy_video),
        duration_sec=25.0
    )

    with patch.object(qa, "inspect_media", return_value={"width": 1080, "height": 1920, "duration": 23.0, "has_video": True, "has_audio": True}):
        passed, report = qa.run_qa(
            db=db_session,
            job=job,
            render=render,
            assets_used=[voice_asset, music_asset],
            force=True
        )

    assert not passed
    assert "Narration truncation risk" in report.failure_reasons
