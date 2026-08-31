"""
Autonomous Recovery & Self-Healing Engine (Phase 6).
Provides:
  - Stale in-flight job detection and bounded retry recovery.
  - Stale 02_PROCESSING vault reconciliation (prevents orphan or duplicate uploads).
  - Read-first Drive Vault & SQLite state consistency reconciliation.
  - YouTube Data API scheduled status synchronization.
  - Genuine persisted recovery audit logging in JobLog.
"""
import re
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from config.constants import (
    JobState,
    MAX_JOB_RETRIES,
    MAX_UPLOAD_RETRIES,
    STALE_JOB_TIMEOUT_SEC,
    STALE_PROCESSING_TIMEOUT_SEC
)
from core.models import Job, JobLog, UploadRecord, RenderOutput, ScriptRecord
from core.state_machine import StateMachine
from core.lock import ProcessLock
from engines.drive_engine import DriveVaultEngine
from engines.upload_engine import UploadEngine

logger = logging.getLogger(__name__)


class RecoveryManager:
    """Coordinates autonomous self-healing, crash recovery, and consistency checks."""

    def __init__(self, drive_engine: Optional[DriveVaultEngine] = None, upload_engine: Optional[UploadEngine] = None):
        self.drive_engine = drive_engine or DriveVaultEngine()
        self.upload_engine = upload_engine or UploadEngine()

    def is_process_running_for_lock(self, lock_name: str) -> bool:
        """Checks if a ProcessLock is actively held by a live PID."""
        lock = ProcessLock(name=lock_name)
        return lock.is_locked()

    def recover_stale_jobs(self, db: Session, stale_timeout_sec: float = STALE_JOB_TIMEOUT_SEC) -> List[Dict[str, Any]]:
        """
        Scans for jobs stuck in transient active states with no live process holding the production lock.
        Safely retries within bounds or escalates to NEEDS_REVIEW.
        """
        cutoff = datetime.utcnow() - timedelta(seconds=stale_timeout_sec)
        transient_states = [
            JobState.RESEARCHING.value,
            JobState.FACT_CHECKING.value,
            JobState.SCRIPTING.value,
            JobState.VISUAL_PLANNING.value,
            JobState.VISUALS_SEARCHING.value,
            JobState.VOICE_GENERATING.value,
            JobState.AUDIO_READY.value,
            JobState.EDITING.value,
            JobState.QA.value,
            JobState.UPLOADING.value
        ]

        stale_jobs = db.query(Job).filter(
            Job.state.in_(transient_states),
            Job.updated_at <= cutoff
        ).all()

        recovered = []
        is_producer_active = self.is_process_running_for_lock("production")
        is_publisher_active = self.is_process_running_for_lock("publisher")

        for job in stale_jobs:
            # If a live process is actively holding the lock for this job type, skip recovery
            if job.state == JobState.UPLOADING.value and is_publisher_active:
                logger.info(f"Skipping recovery for uploading job {job.id}: Publisher process is actively running.")
                continue
            if job.state != JobState.UPLOADING.value and is_producer_active:
                logger.info(f"Skipping recovery for in-flight job {job.id}: Producer process is actively running.")
                continue

            prev_state = job.state
            age_sec = (datetime.utcnow() - (job.updated_at or datetime.utcnow())).total_seconds()

            # 1. Special handling for stale UPLOADING jobs: Perform orphan check first
            if prev_state == JobState.UPLOADING.value:
                existing_upl = db.query(UploadRecord).filter(
                    UploadRecord.job_id == job.id,
                    UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "SUCCESS"])
                ).first()
                if existing_upl and existing_upl.youtube_video_id:
                    job.state = JobState.SCHEDULED.value if existing_upl.status == "SCHEDULED" else JobState.PUBLISHED.value
                    job.updated_at = datetime.utcnow()
                    job.error_message = None
                    recovered.append({
                        "job_id": job.id,
                        "previous_state": prev_state,
                        "new_state": job.state,
                        "action": "RECONCILE_EXISTING_UPLOAD",
                        "youtube_video_id": existing_upl.youtube_video_id
                    })
                    continue

            # 2. Stage-aware asset preservation
            if (job.retry_count or 0) < MAX_JOB_RETRIES:
                job.retry_count = (job.retry_count or 0) + 1
                
                # Check for existing completed render output
                render = db.query(RenderOutput).filter(RenderOutput.job_id == job.id).order_by(RenderOutput.created_at.desc()).first()
                script = db.query(ScriptRecord).filter(ScriptRecord.topic_id == job.topic_id).first() if job.topic_id else None

                if render and render.video_path and Path(render.video_path).exists():
                    target_state = JobState.QA.value if prev_state == JobState.QA.value else JobState.READY_TO_UPLOAD.value
                    job.state = target_state
                    action_name = "RESUME_FROM_RENDER"
                elif script and script.full_text:
                    job.state = JobState.SCRIPT_READY.value
                    action_name = "RESUME_FROM_SCRIPT"
                else:
                    job.state = JobState.QUEUED.value
                    action_name = "RETRY_RESET"

                job.error_message = f"[AUTO_RECOVERED] Stale in state {prev_state} for {age_sec:.0f}s. Resumed to {job.state}."
                job.updated_at = datetime.utcnow()

                StateMachine.record_recovery_event(
                    db=db,
                    job_id=job.id,
                    action=f"STALE_JOB_{action_name}",
                    message=f"Job stale in {prev_state} for {age_sec:.0f}s. Resumed to {job.state} (Attempt {job.retry_count}/{MAX_JOB_RETRIES}).",
                    details={"previous_state": prev_state, "age_seconds": age_sec, "retry_count": job.retry_count, "resumed_state": job.state}
                )
                recovered.append({
                    "job_id": job.id,
                    "previous_state": prev_state,
                    "new_state": job.state,
                    "action": action_name,
                    "retry_count": job.retry_count
                })
            else:
                job.state = JobState.NEEDS_REVIEW.value
                job.error_message = f"[RETRY_EXHAUSTED] Stale in {prev_state} for {age_sec:.0f}s. Max retries ({MAX_JOB_RETRIES}) reached."
                job.updated_at = datetime.utcnow()

                StateMachine.record_recovery_event(
                    db=db,
                    job_id=job.id,
                    action="RECOVERY_BLOCKED_NEEDS_REVIEW",
                    message=f"Job {job.id} exhausted {MAX_JOB_RETRIES} retries after stale state {prev_state}. Flagged NEEDS_REVIEW.",
                    details={"previous_state": prev_state, "age_seconds": age_sec, "retry_count": job.retry_count}
                )
                recovered.append({
                    "job_id": job.id,
                    "previous_state": prev_state,
                    "new_state": "NEEDS_REVIEW",
                    "action": "ESCALATE_NEEDS_REVIEW",
                    "retry_count": job.retry_count
                })

        if recovered:
            db.commit()
            logger.info(f"[SELF_HEALING] Stale Job Recovery completed. Handled {len(recovered)} jobs.")

        return recovered

    def recover_stale_processing_vault(self, db: Session, stale_timeout_sec: float = STALE_PROCESSING_TIMEOUT_SEC) -> List[Dict[str, Any]]:
        """
        Inspects Drive '02_PROCESSING' folder.
        - If YouTube already published it -> move to 03_PUBLISHED.
        - If legitimately SCHEDULED -> keep in 02_PROCESSING.
        - If associated job is FAILED -> move to 04_FAILED.
        - If abandoned without active lock -> return to 01_READY or escalate to NEEDS_REVIEW.
        """
        actions_taken = []
        try:
            processing_files = self.drive_engine.list_files_in_folder("02_PROCESSING")
            if not processing_files:
                return actions_taken

            is_publisher_locked = self.is_process_running_for_lock("publisher")

            for file_info in processing_files:
                file_id = file_info["id"]
                file_name = file_info.get("name", "")
                props = file_info.get("properties", {}) or {}

                # Extract Job ID
                job_id = props.get("job_id")
                if not job_id:
                    m = re.search(r"short_(job_[a-f0-9]+)", file_name)
                    if m:
                        job_id = m.group(1)

                existing_upl = None
                if job_id:
                    existing_upl = db.query(UploadRecord).filter(
                        (UploadRecord.job_id == job_id) |
                        (UploadRecord.youtube_video_id == props.get("youtube_video_id"))
                    ).first()

                # Case 1: Already published on YouTube
                if existing_upl and existing_upl.status == "PUBLISHED":
                    self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
                    actions_taken.append({
                        "file_id": file_id,
                        "file_name": file_name,
                        "action": "MOVED_TO_PUBLISHED",
                        "reason": f"Video is already published on YouTube ({existing_upl.youtube_video_id})"
                    })
                    if job_id:
                        StateMachine.record_recovery_event(db, job_id, "DRIVE_STATE_RECONCILED", f"Moved {file_name} to 03_PUBLISHED.")
                    continue

                # Case 2: Legitimately SCHEDULED on YouTube
                if existing_upl and existing_upl.status == "SCHEDULED":
                    # Correct and valid state: keep in 02_PROCESSING until publication slot
                    continue

                # Case 3: Job is FAILED in SQLite
                job = db.query(Job).filter(Job.id == job_id).first() if job_id else None
                if job and job.state == JobState.FAILED.value:
                    self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="04_FAILED")
                    actions_taken.append({
                        "file_id": file_id,
                        "file_name": file_name,
                        "action": "MOVED_TO_FAILED",
                        "reason": f"Job {job_id} is in FAILED state."
                    })
                    StateMachine.record_recovery_event(db, job_id, "STALE_JOB_QUARANTINED", f"Segregated orphaned {file_name} to 04_FAILED.")
                    continue

                # Case 4: Abandoned file without active publisher process
                if not is_publisher_locked:
                    # Return safely to 01_READY so it can be claimed normally
                    self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="01_READY")
                    actions_taken.append({
                        "file_id": file_id,
                        "file_name": file_name,
                        "action": "RETURNED_TO_READY",
                        "reason": "Abandoned in 02_PROCESSING without active upload or publisher lock. Restored to 01_READY."
                    })
                    if job_id:
                        StateMachine.record_recovery_event(db, job_id, "STALE_JOB_RECOVERED", f"Restored {file_name} from 02_PROCESSING back to 01_READY.")

        except Exception as e:
            logger.error(f"[SELF_HEALING] Error inspecting 02_PROCESSING vault: {e}")

        return actions_taken

    def reconcile_drive_vault_and_db(self, db: Session) -> Dict[str, Any]:
        """
        Performs read-first consistency verification across Drive 4-folder vault and SQLite.
        Identifies orphan DB records or missing assets without performing destructive deletion.
        """
        results = {
            "ready_count": 0,
            "processing_count": 0,
            "published_count": 0,
            "failed_count": 0,
            "inconsistencies": []
        }

        try:
            for folder in ["01_READY", "02_PROCESSING", "03_PUBLISHED", "04_FAILED"]:
                files = self.drive_engine.list_files_in_folder(folder)
                results[f"{folder.lower()[3:]}_count"] = len(files)

            # Check if any job claims to be READY_TO_UPLOAD but has no file in 01_READY
            ready_files = self.drive_engine.list_files_in_folder("01_READY")
            processing_files = self.drive_engine.list_files_in_folder("02_PROCESSING")
            published_files = self.drive_engine.list_files_in_folder("03_PUBLISHED")

            def extract_job_ids(files):
                jids = set()
                for f in files:
                    props = f.get("properties", {}) or {}
                    jid = props.get("job_id")
                    if not jid:
                        m = re.search(r"short_(job_[a-f0-9]+)", f.get("name", ""))
                        if m:
                            jid = m.group(1)
                    if jid:
                        jids.add(jid)
                return jids

            ready_job_ids = extract_job_ids(ready_files)
            processing_job_ids = extract_job_ids(processing_files)
            published_job_ids = extract_job_ids(published_files)

            db_ready_jobs = db.query(Job).filter(Job.state == JobState.READY_TO_UPLOAD.value).all()
            for rj in db_ready_jobs:
                if rj.id in ready_job_ids:
                    continue
                elif rj.id in processing_job_ids:
                    logger.info(f"Job {rj.id} is currently in 02_PROCESSING. Skipping false-positive consistency alert.")
                    continue
                elif rj.id in published_job_ids:
                    logger.info(f"Job {rj.id} is already in 03_PUBLISHED. Reconciling status.")
                    rj.state = JobState.PUBLISHED.value
                    continue
                else:
                    results["inconsistencies"].append({
                        "job_id": rj.id,
                        "type": "MISSING_DRIVE_READY_FILE",
                        "message": f"Job {rj.id} has state READY_TO_UPLOAD but no corresponding file found in Drive vault."
                    })
                    StateMachine.flag_needs_review(
                        db,
                        rj,
                        reason="[CONSISTENCY_CHECK] Job marked READY_TO_UPLOAD but file missing from Drive vault."
                    )

        except Exception as e:
            logger.warning(f"[SELF_HEALING] Drive/DB reconciliation warning: {e}")

        return results

    def run_full_self_healing(self, db: Session) -> Dict[str, Any]:
        """
        Master self-healing entrypoint:
        1. Stale job recovery.
        2. Stale 02_PROCESSING vault recovery.
        3. YouTube scheduled upload reconciliation.
        4. Read-first Drive/DB consistency audit.
        """
        logger.info("[SELF_HEALING] Starting master autonomous self-healing cycle...")

        # 1. Stale Job Recovery
        stale_jobs = self.recover_stale_jobs(db)

        # 2. Stale Processing Vault Recovery
        vault_recoveries = self.recover_stale_processing_vault(db)

        # 3. YouTube Scheduled Uploads Sync
        reconciled_youtube = self.upload_engine.reconcile_scheduled_uploads(db)

        # 4. Read-first Drive/DB Consistency Audit
        drive_audit = self.reconcile_drive_vault_and_db(db)

        summary = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "stale_jobs_recovered_count": len(stale_jobs),
            "stale_jobs_details": stale_jobs,
            "vault_recoveries_count": len(vault_recoveries),
            "vault_recoveries_details": vault_recoveries,
            "youtube_reconciled_count": len(reconciled_youtube),
            "youtube_reconciled_details": reconciled_youtube,
            "drive_audit": drive_audit,
            "status": "HEALTHY" if not drive_audit.get("inconsistencies") else "DEGRADED"
        }

        logger.info(f"[SELF_HEALING] Self-healing cycle finished: {len(stale_jobs)} stale jobs handled, {len(vault_recoveries)} vault items recovered, {len(reconciled_youtube)} YouTube videos reconciled.")
        return summary