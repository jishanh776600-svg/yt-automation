"""
Job State Machine and Crash Recovery Manager.
Ensures idempotency, atomic transitions, and failure resilience.
"""
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from core.models import Job, JobLog
from config.constants import JobState

logger = logging.getLogger(__name__)


class StateMachine:
    """Manages lifecycle state transitions for video production jobs."""

    VALID_TRANSITIONS = {
        JobState.QUEUED: [JobState.RESEARCHING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.RESEARCHING: [JobState.RESEARCHED, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.RESEARCHED: [JobState.FACT_CHECKING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.FACT_CHECKING: [JobState.FACT_CHECKED, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.FACT_CHECKED: [JobState.SCRIPTING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.SCRIPTING: [JobState.SCRIPT_READY, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.SCRIPT_READY: [JobState.VISUAL_PLANNING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.VISUAL_PLANNING: [JobState.VISUALS_SEARCHING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.VISUALS_SEARCHING: [JobState.VISUALS_READY, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.VISUALS_READY: [JobState.VOICE_GENERATING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.VOICE_GENERATING: [JobState.VOICE_READY, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.VOICE_READY: [JobState.AUDIO_READY, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.AUDIO_READY: [JobState.EDITING, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.EDITING: [JobState.QA, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.QA: [JobState.READY_TO_UPLOAD, JobState.NEEDS_REVIEW, JobState.FAILED],
        JobState.READY_TO_UPLOAD: [JobState.UPLOADING, JobState.SCHEDULED, JobState.NEEDS_REVIEW, JobState.FAILED],
        JobState.UPLOADING: [JobState.SCHEDULED, JobState.PUBLISHED, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.SCHEDULED: [JobState.PUBLISHED, JobState.FAILED, JobState.NEEDS_REVIEW],
        JobState.PUBLISHED: [],
        JobState.FAILED: [JobState.QUEUED],
        JobState.NEEDS_REVIEW: [JobState.QUEUED, JobState.READY_TO_UPLOAD, JobState.FAILED],
    }

    @classmethod
    def transition(cls, db: Session, job: Job, target_state: JobState, message: str = "", details: Optional[Dict[str, Any]] = None) -> bool:
        """Executes atomic transition with state validation and structured audit log."""
        current_state = JobState(job.state) if isinstance(job.state, str) else job.state
        allowed = cls.VALID_TRANSITIONS.get(current_state, [])

        if target_state not in allowed and target_state not in [JobState.FAILED, JobState.NEEDS_REVIEW]:
            logger.error(f"Illegal state transition: {current_state} -> {target_state} for job {job.id}")
            return False

        job.state = target_state.value
        job.updated_at = datetime.utcnow()
        if target_state == JobState.PUBLISHED:
            job.published_at = datetime.utcnow()

        log_entry = JobLog(
            job_id=job.id,
            stage=target_state.value,
            status="SUCCESS" if target_state != JobState.FAILED else "ERROR",
            message=message,
            details_json=json.dumps(details or {}, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        logger.info(f"Job {job.id} state -> {target_state.value} ({message})")
        return True

    @classmethod
    def flag_needs_review(cls, db: Session, job: Job, reason: str, details: Optional[Dict[str, Any]] = None):
        """Transitions job to NEEDS_REVIEW safely."""
        job.state = JobState.NEEDS_REVIEW.value
        job.error_message = reason
        job.updated_at = datetime.utcnow()

        log_entry = JobLog(
            job_id=job.id,
            stage=JobState.NEEDS_REVIEW.value,
            status="WARNING",
            message=reason,
            details_json=json.dumps(details or {}, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        logger.warning(f"Job {job.id} moved to NEEDS_REVIEW: {reason}")

    @classmethod
    def record_recovery_event(cls, db: Session, job_id: str, action: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Records a genuine persisted recovery event in JobLog."""
        log_entry = JobLog(
            job_id=job_id,
            stage="RECOVERY",
            status=action,
            message=message,
            details_json=json.dumps(details or {}, ensure_ascii=False),
            created_at=datetime.utcnow()
        )
        db.add(log_entry)
        db.commit()
        logger.info(f"[RECOVERY_LOG] Job {job_id} -> {action}: {message}")
