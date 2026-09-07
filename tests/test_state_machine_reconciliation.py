"""
Tests for 02_PROCESSING Reconciliation and Publication Safety Gate Invariants.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Job, UploadRecord, RenderOutput, RenderedVideoRecord, Topic
from engines.drive_engine import is_valid_ready_short
from main import resolve_vault_file_metadata, ShortsPipeline


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_is_valid_ready_short_with_short_man_prefix(test_db):
    r = RenderedVideoRecord(
        id="rend_001",
        manifest_id="man_001",
        event_id="evt_test",
        script_id="scr_001",
        video_path="/data/renders/short_man_001.mp4",
        duration_seconds=23.5,
        qa_status="PASSED",
        voice_id="af_bella"
    )
    test_db.add(r)
    test_db.commit()

    cand = {
        "id": "file_123",
        "name": "short_man_001.mp4",
        "size": 25000000,
        "properties": {
            "manifest_id": "man_001",
            "voice": "af_bella",
            "qa_status": "PASSED"
        }
    }

    is_val, reason = is_valid_ready_short(cand, db=test_db)
    assert is_val is True
    assert "Valid" in reason


def test_is_valid_ready_short_rejects_non_authoritative_voice(test_db):
    cand = {
        "id": "file_124",
        "name": "short_man_002.mp4",
        "size": 25000000,
        "properties": {
            "manifest_id": "man_002",
            "voice": "af_sarah",
            "qa_status": "PASSED"
        }
    }
    is_val, reason = is_valid_ready_short(cand, db=test_db)
    assert is_val is False
    assert "af_bella required" in reason


def test_safety_gate_does_not_quarantine_on_slot_limit(test_db, tmp_path):
    pipeline = ShortsPipeline.__new__(ShortsPipeline)
    pipeline.drive_engine = MagicMock()
    pipeline.upload_engine = MagicMock()

    # Create dummy temp file
    dummy_file = tmp_path / "temp.mp4"
    dummy_file.write_bytes(b"0" * 1024)
    pipeline.drive_engine.download_file.return_value = dummy_file

    pipeline.upload_engine.evaluate_publication_safety_gate.return_value = (
        False, "Gate 11 Failed: Daily limit reached for 2026-09-07"
    )

    job = Job(id="job_test_01", state="READY_TO_UPLOAD")
    render = RenderOutput(
        id="rnd_01",
        job_id=job.id,
        video_path=str(dummy_file),
        duration_sec=23.0,
        file_size_bytes=1024000
    )
    test_db.add_all([job, render])
    test_db.commit()

    target_file = {
        "id": "drive_file_999",
        "name": "short_man_valid.mp4",
        "size": 25000000,
        "properties": {"job_id": "job_test_01"}
    }
    res = pipeline._schedule_single_drive_file(
        db=test_db,
        target_file=target_file,
        scheduled_slot=datetime(2026, 9, 8, 11, 0)
    )
    assert res is None

    # File MUST be moved back to 01_READY, NEVER to 04_FAILED
    pipeline.drive_engine.move_file_in_vault.assert_any_call(
        "drive_file_999", from_folder="02_PROCESSING", to_folder="01_READY"
    )
    for call in pipeline.drive_engine.move_file_in_vault.call_args_list:
        assert call[1].get("to_folder") != "04_FAILED"
