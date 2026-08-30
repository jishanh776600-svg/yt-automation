"""
Final Production Handoff Test Suite.
Verifies 15-point Publication Safety Gate, READY Vault Promotion,
Autonomous Scheduler Discovery, Slot Allocation, and Idempotency.
"""
import pytest
import uuid
import os
import json
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from core.database import SessionLocal, init_db
from core.models import Job, Topic, RenderOutput, UploadRecord, QAReport
from engines.upload_engine import UploadEngine
from engines.drive_engine import DriveVaultEngine
from engines.scheduler_engine import PublicationScheduler
from main import ShortsPipeline
from config.constants import JobState, DAILY_SHORTS_LIMIT


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# 1. 15-POINT PUBLICATION SAFETY GATE TESTS
# ==============================================================================

def test_publication_safety_gate_success(tmp_path, db_session: Session):
    """Verifies that a completely valid Short passes all 15 safety gates."""
    upload_engine = UploadEngine()

    dummy_mp4 = tmp_path / "valid_render_1080x1920.mp4"
    dummy_mp4.write_bytes(b"0" * (1024 * 1024))  # 1 MB

    job = Job(id="job_gate_ok", state=JobState.READY_TO_UPLOAD.value)
    db_session.add(job)
    render = RenderOutput(
        id="rnd_gate_ok",
        job_id=job.id,
        video_path=str(dummy_mp4),
        width=1080,
        height=1920,
        duration_sec=23.5,
        video_codec="h264",
        audio_codec="aac",
        file_size_bytes=dummy_mp4.stat().st_size
    )
    db_session.add(render)
    qa = QAReport(job_id=job.id, passed=True)
    db_session.add(qa)
    db_session.commit()

    metadata = {
        "title": "The Valid Historical Short",
        "description": "Historical story.",
        "tags": ["history", "shorts"]
    }

    # Pass in mock validation for FFmpeg probe in test
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(upload_engine, "validate_media_integrity", lambda p: None)
        mp.setattr(upload_engine, "_is_test_mode", lambda: True)

        passed, reason = upload_engine.evaluate_publication_safety_gate(
            db=db_session,
            job=job,
            render=render,
            metadata=metadata,
            scheduled_slot=datetime.utcnow() + timedelta(hours=3)
        )
        assert passed is True, f"Gate failed unexpectedly: {reason}"
        assert "passed successfully" in reason


def test_publication_safety_gate_blocks_missing_file(db_session: Session):
    """Gate 1: Missing file must block upload."""
    upload_engine = UploadEngine()
    job = Job(id="job_gate_nofile", state=JobState.READY_TO_UPLOAD.value)
    db_session.add(job)
    render = RenderOutput(
        id="rnd_nofile",
        job_id=job.id,
        video_path="non_existent_file.mp4",
        width=1080,
        height=1920,
        duration_sec=22.0,
        file_size_bytes=1000
    )
    db_session.add(render)
    db_session.commit()

    passed, reason = upload_engine.evaluate_publication_safety_gate(
        db=db_session,
        job=job,
        render=render,
        metadata={"title": "Test Title"}
    )
    assert passed is False
    assert "Gate 1 Failed" in reason


def test_publication_safety_gate_blocks_wrong_resolution(tmp_path, db_session: Session):
    """Gate 5: Non-1080x1920 resolution must block upload."""
    upload_engine = UploadEngine()
    dummy_mp4 = tmp_path / "bad_res.mp4"
    dummy_mp4.write_bytes(b"0" * (600 * 1024))

    job = Job(id="job_bad_res", state=JobState.READY_TO_UPLOAD.value)
    db_session.add(job)
    render = RenderOutput(
        id="rnd_bad_res",
        job_id=job.id,
        video_path=str(dummy_mp4),
        width=720,
        height=1280,
        duration_sec=22.0,
        video_codec="h264",
        file_size_bytes=600 * 1024
    )
    db_session.add(render)
    db_session.commit()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(upload_engine, "validate_media_integrity", lambda p: None)
        passed, reason = upload_engine.evaluate_publication_safety_gate(
            db=db_session,
            job=job,
            render=render,
            metadata={"title": "Test Title"}
        )
        assert passed is False
        assert "Gate 5 Failed" in reason


def test_publication_safety_gate_blocks_already_published_job(tmp_path, db_session: Session):
    """Gate 10: Already published job must block duplicate upload."""
    upload_engine = UploadEngine()
    dummy_mp4 = tmp_path / "already_pub.mp4"
    dummy_mp4.write_bytes(b"0" * (600 * 1024))

    job = Job(id="job_already_pub", state=JobState.READY_TO_UPLOAD.value)
    db_session.add(job)
    render = RenderOutput(
        id="rnd_alr_pub",
        job_id=job.id,
        video_path=str(dummy_mp4),
        width=1080,
        height=1920,
        duration_sec=22.0,
        video_codec="h264",
        file_size_bytes=600 * 1024
    )
    db_session.add(render)
    upl = UploadRecord(
        id="upl_alr_pub",
        job_id=job.id,
        youtube_video_id="YT_EXISTING_123",
        title="Existing Video",
        description="Existing Video Description",
        tags="history,shorts",
        status="PUBLISHED"
    )
    db_session.add(upl)
    db_session.commit()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(upload_engine, "validate_media_integrity", lambda p: None)
        passed, reason = upload_engine.evaluate_publication_safety_gate(
            db=db_session,
            job=job,
            render=render,
            metadata={"title": "New Title"}
        )
        assert passed is False
        assert "Gate 10 Failed" in reason


# ==============================================================================
# 2. READY VAULT PROMOTION & MANIFEST INTEGRITY
# ==============================================================================

def test_ready_vault_manifest_generation(tmp_path):
    """Verifies that READY staging writes both MP4 and complete .meta.json companion manifest."""
    drive_engine = DriveVaultEngine()
    dummy_mp4 = tmp_path / f"short_job_manifest_{uuid.uuid4().hex[:8]}_1080x1920.mp4"
    dummy_mp4.write_bytes(b"mp4 content" * 100)

    props = {
        "job_id": "job_manifest_001",
        "topic_id": "top_manifest_001",
        "title": "The Krakatoa Tsunami",
        "tags": "history,volcano,shorts",
        "voice": "af_bella",
        "bgm_track": "The Flux Beneath It All",
        "duration_sec": 23.4,
        "editing_profile": "DISASTER",
        "sfx_events": 2
    }

    res = drive_engine.upload_video_to_vault(
        local_path=dummy_mp4,
        target_folder="01_READY",
        metadata_properties=props
    )
    assert res is not None

    ready_files = drive_engine.list_files_in_folder("01_READY")
    matching = [f for f in ready_files if f["name"] == dummy_mp4.name]
    assert len(matching) == 1
    assert matching[0]["properties"].get("voice") == "af_bella"
    assert matching[0]["properties"].get("editing_profile") == "DISASTER"


# ==============================================================================
# 3. SCHEDULER DISCOVERY & SLOT BEHAVIOR
# ==============================================================================

def test_scheduler_slot_calculation_preserves_production_slots(db_session: Session):
    """Verifies that PublicationScheduler only allocates 06:00, 11:00, or 15:00 UTC slots."""
    scheduler = PublicationScheduler()
    slot = scheduler.calculate_next_available_slot(db_session)
    assert slot.hour in [6, 11, 15]
    assert slot.minute == 0
    assert slot.second == 0
    # Must be in future
    assert slot > datetime.utcnow()


def test_schedule_ready_buffer_respects_daily_limit(db_session: Session):
    """Verifies that scheduler never exceeds DAILY_SHORTS_LIMIT = 3."""
    pipeline = ShortsPipeline()
    res = pipeline.schedule_ready_buffer(db=db_session)
    assert isinstance(res, dict)
    assert res.get("published_today", 0) + res.get("scheduled_today", 0) <= DAILY_SHORTS_LIMIT
