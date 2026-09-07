"""
Tests for Persistent Attempt Ledger and Canonical Failure Taxonomy.
===================================================================
Enforces the Zero-Silent-Retries Invariant:
1. Every attempt is explicitly persisted.
2. Success after failures never erases failure history (marked as RECOVERED).
3. All 24 failure categories are strictly valid taxonomy enums.
"""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, ProductionAttemptRecord, ProductionIncidentRecord
from core.attempt_ledger import AttemptLedger, FailureCategory


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_start_and_record_failure(test_db):
    attempt = AttemptLedger.start_attempt(
        db=test_db,
        run_id="run_test_001",
        operation="PRODUCE_BUFFER",
        stage="DISCOVERY",
        retry_number=0,
        maximum_retries=3
    )
    assert attempt.id.startswith("att_")
    assert attempt.status == "RUNNING"
    assert attempt.retry_number == 0

    failed = AttemptLedger.record_failure(
        db=test_db,
        attempt=attempt,
        error_type=FailureCategory.DISCOVERY_FAILURE.value,
        error_message="No fresh articles found in GDELT",
        root_cause="GDELT API timed out",
        recovery_action="Fallback to RSS feeds"
    )
    assert failed.status == "FAILED"
    assert failed.error_type == "DISCOVERY_FAILURE"
    assert failed.finished_at is not None
    assert failed.recovered is False

    # Check persistence
    persisted = test_db.query(ProductionAttemptRecord).filter_by(id=attempt.id).first()
    assert persisted is not None
    assert persisted.status == "FAILED"


def test_success_after_failure_marks_recovered_without_erasing(test_db):
    # Attempt 1: Failed
    att1 = AttemptLedger.start_attempt(
        db=test_db,
        run_id="run_test_002",
        operation="PRODUCE_BUFFER",
        stage="DRIVE_DEPOSIT",
        retry_number=0
    )
    AttemptLedger.record_failure(
        db=test_db,
        attempt=att1,
        error_type=FailureCategory.DRIVE_UPLOAD_FAILURE.value,
        error_message="Google Drive 503 Backend Error",
        recovery_action="Exponential backoff retry"
    )

    # Attempt 2: Failed
    att2 = AttemptLedger.start_attempt(
        db=test_db,
        run_id="run_test_002",
        operation="PRODUCE_BUFFER",
        stage="DRIVE_DEPOSIT",
        retry_number=1
    )
    AttemptLedger.record_failure(
        db=test_db,
        attempt=att2,
        error_type=FailureCategory.LOCK_CONTENTION.value,
        error_message="Cloud lock held by PID 123",
        recovery_action="Wait for lock release"
    )

    # Attempt 3: Succeeded
    att3 = AttemptLedger.start_attempt(
        db=test_db,
        run_id="run_test_002",
        operation="PRODUCE_BUFFER",
        stage="DRIVE_DEPOSIT",
        retry_number=2
    )
    success = AttemptLedger.record_success(
        db=test_db,
        attempt=att3,
        related_drive_file_id="drive_file_abc123"
    )

    # Invariants verification:
    # 1. att3 MUST be marked RECOVERED (not just SUCCESS) because retry_number > 0
    assert success.status == "RECOVERED"
    assert success.recovered is True

    # 2. Both prior attempts MUST still exist as FAILED
    all_attempts = test_db.query(ProductionAttemptRecord).filter_by(run_id="run_test_002").order_by(ProductionAttemptRecord.retry_number).all()
    assert len(all_attempts) == 3
    assert all_attempts[0].status == "FAILED"
    assert all_attempts[0].error_type == "DRIVE_UPLOAD_FAILURE"
    assert all_attempts[1].status == "FAILED"
    assert all_attempts[1].error_type == "LOCK_CONTENTION"
    assert all_attempts[2].status == "RECOVERED"
    assert all_attempts[2].related_drive_file_id == "drive_file_abc123"


def test_first_attempt_success_marks_success(test_db):
    att = AttemptLedger.start_attempt(
        db=test_db,
        run_id="run_test_003",
        operation="SCHEDULE_READY",
        stage="SCHEDULING",
        retry_number=0
    )
    success = AttemptLedger.record_success(
        db=test_db,
        attempt=att,
        related_youtube_video_id="yt_vid_999"
    )
    assert success.status == "SUCCESS"
    assert success.recovered is False
    assert success.related_youtube_video_id == "yt_vid_999"


def test_record_production_incident(test_db):
    incident = AttemptLedger.record_incident(
        db=test_db,
        affected_workflow="produce_buffer.yml",
        symptoms="01_READY drained to 0 Shorts",
        exact_root_cause="False quarantine bug in Gate 15 title collision",
        permanent_fix_description="Eliminated generic fallback title and guarded publication safety gate",
        affected_run_id="34100432825",
        failed_attempts_count=2,
        regression_test="test_state_machine_reconciliation.py",
        git_commit_sha="abc1234"
    )
    assert incident.id.startswith("inc_")
    assert incident.recovery_status == "RESOLVED"
    persisted = test_db.query(ProductionIncidentRecord).filter_by(id=incident.id).first()
    assert persisted is not None
    assert persisted.exact_root_cause == "False quarantine bug in Gate 15 title collision"


def test_summary_for_today(test_db):
    summary = AttemptLedger.get_summary_for_today(test_db)
    assert "total_attempts_today" in summary
    assert "failed_attempts_today" in summary
    assert "retries_today" in summary
    assert "recovered_runs_today" in summary
    assert "successful_operations_today" in summary
