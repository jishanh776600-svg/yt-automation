"""
Phase 7: Persistent Production Attempt & Failure Ledger.
=========================================================
Implements the canonical failure taxonomy, persistent attempt ledger,
and zero-silent-retries invariant across all AL-AMR production pipelines.

Invariants:
  1. No silent retries: Every execution attempt must be recorded.
  2. Success after failures never erases failure history; marked as RECOVERED.
  3. Every failure is classified into one of the 24 canonical failure categories.
  4. Fully transaction-safe and compatible with SQLite / ephemeral runners.
"""

import enum
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from sqlalchemy.orm import Session

from core.database import SessionLocal
from core.models import ProductionAttemptRecord, ProductionIncidentRecord

logger = logging.getLogger("alamr.attempt_ledger")


class FailureCategory(str, enum.Enum):
    """Canonical 24 Failure Taxonomy Enums."""
    DISCOVERY_FAILURE = "DISCOVERY_FAILURE"
    CANDIDATE_REJECTION = "CANDIDATE_REJECTION"
    NICHE_GATE_FAILURE = "NICHE_GATE_FAILURE"
    DUPLICATE_REJECTION = "DUPLICATE_REJECTION"
    SCRIPT_FAILURE = "SCRIPT_FAILURE"
    TTS_FAILURE = "TTS_FAILURE"
    VISUAL_ASSET_FAILURE = "VISUAL_ASSET_FAILURE"
    RENDER_FAILURE = "RENDER_FAILURE"
    QA_FAILURE = "QA_FAILURE"
    DRIVE_UPLOAD_FAILURE = "DRIVE_UPLOAD_FAILURE"
    DRIVE_MOVE_FAILURE = "DRIVE_MOVE_FAILURE"
    DATABASE_SYNC_FAILURE = "DATABASE_SYNC_FAILURE"
    LOCK_CONTENTION = "LOCK_CONTENTION"
    LOCK_ORPHANED = "LOCK_ORPHANED"
    GITHUB_WORKFLOW_FAILURE = "GITHUB_WORKFLOW_FAILURE"
    YOUTUBE_UPLOAD_FAILURE = "YOUTUBE_UPLOAD_FAILURE"
    YOUTUBE_SCHEDULING_FAILURE = "YOUTUBE_SCHEDULING_FAILURE"
    METADATA_FAILURE = "METADATA_FAILURE"
    QUOTA_FAILURE = "QUOTA_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    AUTHENTICATION_FAILURE = "AUTHENTICATION_FAILURE"
    TIMEZONE_FAILURE = "TIMEZONE_FAILURE"
    STATE_RECONCILIATION_FAILURE = "STATE_RECONCILIATION_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AttemptLedger:
    """
    Manages persistent logging of production attempts and failures.
    Ensures that retried operations keep a permanent audit trail.
    """

    @staticmethod
    def start_attempt(
        db: Session,
        run_id: str,
        operation: str,
        stage: str,
        retry_number: int = 0,
        maximum_retries: int = 3,
        related_manifest_id: Optional[str] = None,
        related_drive_file_id: Optional[str] = None,
        related_youtube_video_id: Optional[str] = None,
    ) -> ProductionAttemptRecord:
        attempt = ProductionAttemptRecord(
            id=f"att_{uuid.uuid4().hex[:12]}",
            run_id=run_id,
            operation=operation,
            stage=stage,
            started_at=datetime.utcnow(),
            status="RUNNING",
            retry_number=retry_number,
            maximum_retries=maximum_retries,
            recovered=False,
            related_manifest_id=related_manifest_id,
            related_drive_file_id=related_drive_file_id,
            related_youtube_video_id=related_youtube_video_id,
        )
        db.add(attempt)
        db.commit()
        logger.info(
            f"[ATTEMPT_LEDGER] Started Attempt {attempt.id} "
            f"(Run: {run_id}, Op: {operation}, Stage: {stage}, Retry: {retry_number}/{maximum_retries})"
        )
        return attempt

    @staticmethod
    def record_failure(
        db: Session,
        attempt: ProductionAttemptRecord,
        error_type: str,
        error_message: str,
        root_cause: Optional[str] = None,
        recovery_action: Optional[str] = None,
    ) -> ProductionAttemptRecord:
        attempt.finished_at = datetime.utcnow()
        attempt.status = "FAILED"
        attempt.error_type = error_type
        attempt.error_message = str(error_message)[:2000]
        attempt.root_cause = str(root_cause or error_message)[:2000]
        attempt.recovery_action = recovery_action
        attempt.recovered = False
        db.commit()
        logger.warning(
            f"[ATTEMPT_LEDGER] Attempt {attempt.id} FAILED: "
            f"[{error_type}] {error_message[:120]} (Recovery Action: {recovery_action})"
        )
        return attempt

    @staticmethod
    def record_success(
        db: Session,
        attempt: ProductionAttemptRecord,
        related_drive_file_id: Optional[str] = None,
        related_youtube_video_id: Optional[str] = None,
    ) -> ProductionAttemptRecord:
        attempt.finished_at = datetime.utcnow()
        if attempt.retry_number > 0:
            attempt.status = "RECOVERED"
            attempt.recovered = True
        else:
            attempt.status = "SUCCESS"
            attempt.recovered = False

        if related_drive_file_id:
            attempt.related_drive_file_id = related_drive_file_id
        if related_youtube_video_id:
            attempt.related_youtube_video_id = related_youtube_video_id

        db.commit()
        logger.info(
            f"[ATTEMPT_LEDGER] Attempt {attempt.id} completed with status '{attempt.status}' "
            f"(Retry: {attempt.retry_number}, Recovered: {attempt.recovered})"
        )
        return attempt

    @staticmethod
    def record_incident(
        db: Session,
        affected_workflow: str,
        symptoms: str,
        exact_root_cause: str,
        permanent_fix_description: str,
        affected_run_id: Optional[str] = None,
        affected_assets_json: Optional[str] = None,
        failed_attempts_count: int = 0,
        recovery_status: str = "RESOLVED",
        verification_evidence: Optional[str] = None,
        regression_test: Optional[str] = None,
        git_commit_sha: Optional[str] = None,
    ) -> ProductionIncidentRecord:
        incident = ProductionIncidentRecord(
            id=f"inc_{uuid.uuid4().hex[:12]}",
            detected_at=datetime.utcnow(),
            affected_workflow=affected_workflow,
            affected_run_id=affected_run_id,
            affected_assets_json=affected_assets_json,
            symptoms=symptoms,
            exact_root_cause=exact_root_cause,
            failed_attempts_count=failed_attempts_count,
            recovery_status=recovery_status,
            permanent_fix_description=permanent_fix_description,
            verification_evidence=verification_evidence,
            regression_test=regression_test,
            git_commit_sha=git_commit_sha,
        )
        db.add(incident)
        db.commit()
        logger.info(f"[ATTEMPT_LEDGER] Recorded Production Incident {incident.id}: {symptoms[:100]}")
        return incident

    @staticmethod
    def get_summary_for_today(db: Session) -> Dict[str, Any]:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        attempts = db.query(ProductionAttemptRecord).filter(
            ProductionAttemptRecord.started_at >= today_start
        ).all()

        total = len(attempts)
        failures = sum(1 for a in attempts if a.status == "FAILED")
        retries = sum(1 for a in attempts if a.retry_number > 0)
        recovered = sum(1 for a in attempts if a.status == "RECOVERED")
        success = sum(1 for a in attempts if a.status in ["SUCCESS", "RECOVERED"])

        return {
            "total_attempts_today": total,
            "failed_attempts_today": failures,
            "retries_today": retries,
            "recovered_runs_today": recovered,
            "successful_operations_today": success,
            "latest_failure": next(
                ({"error_type": a.error_type, "root_cause": a.root_cause, "time": a.finished_at.isoformat() if a.finished_at else None}
                 for a in sorted(attempts, key=lambda x: x.started_at, reverse=True) if a.status == "FAILED"),
                None
            )
        }
