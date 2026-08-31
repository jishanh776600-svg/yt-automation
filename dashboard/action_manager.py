"""
Action Manager for Historia Pipeline Control Center (App Phase 2).
Executes real-world pipeline actions:
- Buffer production & replenishment
- Live YouTube publishing from Google Drive vault
- Job retry & review queue management
- Job quarantine & Drive vault segregation
- Process lock inspection & safe stale release
"""
import os
import sys
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session

from config.settings import LOCKS_DIR, LOCK_STALE_TIMEOUT_SEC, CLOUD_MODE
from config.constants import DAILY_SHORTS_LIMIT, JobState
from core.models import Job, UploadRecord, RenderOutput
from core.lock import ProcessLock, is_pid_alive
from engines.drive_engine import DriveVaultEngine
from dashboard.github_client import GitHubWorkflowDispatcher

logger = logging.getLogger(__name__)


class ActionManager:
    """
    Executes real-world operational controls against the pipeline.
    Zero mock responses: all actions mutate real state and verify results.
    """

    def __init__(self):
        self.drive_engine = DriveVaultEngine()
        self.github_dispatcher = GitHubWorkflowDispatcher()

    def trigger_buffer_production(
        self,
        db: Session,
        count: int = 1,
        target: int = 12,
        force_local: bool = False
    ) -> Dict[str, Any]:
        """
        Executes real buffer production or replenishment under production process lock.
        In CLOUD_MODE, performs stock-health check, checks for active duplicate runs,
        and requests produce_buffer.yml workflow dispatch on GitHub Actions.
        """
        # 1. Authoritative Stock Health Gate (Phase 6)
        try:
            current_stock = self.drive_engine.get_ready_stock_count(db=db)
        except Exception as d_err:
            logger.warning(f"Could not read live Drive stock before refill: {d_err}")
            current_stock = 0

        if current_stock >= target:
            logger.info(f"[ACTION] Buffer refill rejected: stock is healthy ({current_stock}/{target} Shorts in 01_READY).")
            return {
                "success": False,
                "status": "STOCK_HEALTHY",
                "error": f"Google Drive 01_READY stock is healthy ({current_stock}/{target} Shorts). Refill not required.",
                "current_stock": current_stock,
                "target": target,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

        # 2. Duplicate Refill Protection (Phase 5)
        active_run = self.github_dispatcher.get_active_workflow_run("produce_buffer.yml")
        if active_run:
            logger.warning(f"[ACTION] Buffer refill rejected: run {active_run['id']} is currently {active_run['status']}.")
            return {
                "success": False,
                "status": "REFILL_ALREADY_RUNNING",
                "error": f"A buffer refill workflow is already running on GitHub Actions (Run ID: {active_run['id']}, Status: {active_run['status']}).",
                "active_run_id": active_run["id"],
                "run_status": active_run["status"],
                "workflow": "produce_buffer.yml",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

        from config.settings import CLOUD_MODE
        if CLOUD_MODE and not force_local:
            from engines.tts_engine import get_active_voice
            active_v = get_active_voice(db)
            logger.info(f"[ACTION:CLOUD] CLOUD_MODE active. Dispatching produce_buffer.yml (Current Stock: {current_stock}/{target}, Voice: {active_v})...")
            batch_count = count if count == 1 else 0
            return self.github_dispatcher.dispatch_produce_buffer(
                target_buffer=target,
                batch_count=batch_count,
                active_voice=active_v
            )

        # Local execution fallback for offline development
        prod_lock = ProcessLock(name="production")
        if prod_lock.is_locked():
            info = prod_lock.get_lock_info()
            return {
                "success": False,
                "status": "LOCK_HELD",
                "error": f"Production lock is currently held by active PID {info.get('pid') if info else 'unknown'}.",
                "lock_active": True,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

        try:
            from main import ShortsPipeline
            pipeline = ShortsPipeline(voice=active_v)
            if count == 1:
                logger.info("[ACTION] Producing single Short...")
                job = pipeline.produce_single_to_vault()
                if job:
                    return {
                        "success": True,
                        "status": "PRODUCED_SINGLE",
                        "action": "PRODUCE_SINGLE",
                        "job_id": job.id,
                        "state": job.state,
                        "title": job.topic.title if job.topic else "Unknown Topic",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                else:
                    return {
                        "success": False,
                        "status": "PRODUCTION_FAILED",
                        "error": "Production completed but no job record was returned.",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
            else:
                logger.info(f"[ACTION] Maintaining buffer target of {target} Shorts...")
                produced_count = pipeline.maintain_buffer(target_stock=target)
                return {
                    "success": True,
                    "status": "BUFFER_MAINTAINED",
                    "action": "MAINTAIN_BUFFER",
                    "produced_count": produced_count,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
        except Exception as e:
            logger.error(f"[ACTION] Buffer production failed: {e}")
            return {
                "success": False,
                "status": "PRODUCTION_FAILED",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    def trigger_publish_next(self, db: Session, force: bool = False) -> Dict[str, Any]:
        """
        Publishes the next ready Short from Google Drive Vault to YouTube.
        Enforces DAILY_SHORTS_LIMIT = 4 ceiling unless force=True.
        In CLOUD_MODE, requests autopilot.yml workflow dispatch on GitHub Actions.
        """
        from config.settings import CLOUD_MODE
        if CLOUD_MODE:
            logger.info("[ACTION:CLOUD] CLOUD_MODE active. Dispatching autopilot.yml workflow...")
            return self.github_dispatcher.dispatch_autopilot()

        pub_lock = ProcessLock(name="publisher")
        if pub_lock.is_locked():
            info = pub_lock.get_lock_info()
            return {
                "success": False,
                "error": f"Publisher lock is currently held by active PID {info.get('pid') if info else 'unknown'}.",
                "lock_active": True
            }

        try:
            from main import ShortsPipeline
            pipeline = ShortsPipeline()
            success = pipeline.publish_next_from_vault(force=force)
            if success:
                latest_upload = db.query(UploadRecord).filter(
                    UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "TEST_VERIFIED"])
                ).order_by(UploadRecord.created_at.desc()).first()

                return {
                    "success": True,
                    "action": "SCHEDULE_OR_PUBLISH_NEXT",
                    "status": latest_upload.status if latest_upload else "SCHEDULED",
                    "youtube_video_id": latest_upload.youtube_video_id if latest_upload else None,
                    "title": latest_upload.title if latest_upload else "Scheduled Short",
                    "scheduled_publish_at": latest_upload.scheduled_publish_at.isoformat() + "Z" if (latest_upload and latest_upload.scheduled_publish_at) else None,
                    "youtube_url": f"https://youtube.com/shorts/{latest_upload.youtube_video_id}" if (latest_upload and latest_upload.youtube_video_id) else None,
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
            else:
                ready_stock = self.drive_engine.get_ready_stock_count()
                if ready_stock == 0:
                    return {
                        "success": False,
                        "error": "Google Drive 01_READY vault is currently empty. Replenish buffer first.",
                        "ready_stock": 0
                    }

                return {
                    "success": False,
                    "error": "No Short was scheduled or published (check Drive vault, daily ceilings, and logs).",
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                }
        except Exception as e:
            logger.error(f"[ACTION] Publish next failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    def trigger_sync_youtube(self, db: Session) -> Dict[str, Any]:
        """
        Executes real-time synchronization between YouTube, SQLite, and Google Drive Vault.
        Performs direct status reconciliation and syncs canonical state to Drive Vault.
        """
        try:
            from engines.upload_engine import UploadEngine
            uploader = UploadEngine()
            
            reconciled = uploader.reconcile_scheduled_uploads(db)
            
            moved_files = []
            if reconciled:
                try:
                    processing_files = self.drive_engine.list_files_in_folder("02_PROCESSING")
                    for rec_item in reconciled:
                        for pf in processing_files:
                            props = pf.get("properties", {}) or {}
                            if props.get("job_id") == rec_item["job_id"] or rec_item["job_id"] in pf.get("name", ""):
                                self.drive_engine.move_file_in_vault(pf["id"], from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
                                moved_files.append(pf["name"])
                except Exception as drive_err:
                    logger.warning(f"Drive file sync error during YouTube sync: {drive_err}")

                try:
                    from core.database_sync import upload_canonical_database
                    upload_canonical_database()
                except Exception:
                    pass

            return {
                "success": True,
                "action": "SYNC_YOUTUBE",
                "reconciled_count": len(reconciled),
                "reconciled_jobs": [r["job_id"] for r in reconciled],
                "drive_files_moved": moved_files,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            logger.error(f"[ACTION] YouTube sync failed: {e}")
            return {
                "success": False,
                "action": "SYNC_YOUTUBE",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    def retry_job(self, db: Session, job_id: str) -> Dict[str, Any]:
        """
        Resets a job in NEEDS_REVIEW or FAILED state back to QUEUED (or READY_TO_UPLOAD).
        """
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"success": False, "error": f"Job '{job_id}' not found in database."}

        if job.state not in [JobState.FAILED.value, JobState.NEEDS_REVIEW.value]:
            return {
                "success": False,
                "error": f"Job '{job_id}' is currently in state '{job.state}' and is not eligible for retry."
            }

        prev_state = job.state
        job.state = JobState.QUEUED.value
        job.error_message = None
        job.retry_count += 1
        job.updated_at = datetime.utcnow()
        db.commit()

        logger.info(f"[ACTION] Retried job {job_id} (State changed from {prev_state} -> QUEUED, retry #{job.retry_count})")
        return {
            "success": True,
            "job_id": job_id,
            "previous_state": prev_state,
            "new_state": job.state,
            "retry_count": job.retry_count,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def quarantine_job(self, db: Session, job_id: str, reason: str = "Quarantined by operator") -> Dict[str, Any]:
        """
        Moves a job to FAILED state and segregates any cloud Drive file into 04_FAILED.
        """
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"success": False, "error": f"Job '{job_id}' not found in database."}

        prev_state = job.state
        job.state = JobState.FAILED.value
        job.error_message = f"[QUARANTINED] {reason}"
        job.updated_at = datetime.utcnow()
        db.commit()

        # Check if file exists in 01_READY or 02_PROCESSING and move to 04_FAILED
        moved_file = None
        try:
            for folder in ["01_READY", "02_PROCESSING"]:
                files = self.drive_engine.list_files_in_folder(folder)
                for f in files:
                    if job_id in f.get("name", ""):
                        self.drive_engine.move_file_in_vault(f["id"], from_folder=folder, to_folder="04_FAILED")
                        moved_file = f["name"]
                        break
                if moved_file:
                    break
        except Exception as drive_err:
            logger.warning(f"Could not segregate Drive file for job {job_id}: {drive_err}")

        logger.info(f"[ACTION] Quarantined job {job_id} ({prev_state} -> FAILED, Drive moved: {moved_file})")
        return {
            "success": True,
            "job_id": job_id,
            "previous_state": prev_state,
            "new_state": "FAILED",
            "reason": reason,
            "moved_drive_file": moved_file,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def release_process_lock(self, lock_name: str, force: bool = False) -> Dict[str, Any]:
        """
        Safely inspects and releases a process lock if stale or if force=True.
        """
        if lock_name not in ["production", "publisher"]:
            return {"success": False, "error": f"Invalid lock name '{lock_name}'. Allowed: 'production', 'publisher'."}

        lock = ProcessLock(name=lock_name)
        info = lock.get_lock_info()
        lock_file = lock.lock_file

        if not lock_file.exists():
            return {
                "success": True,
                "message": f"Lock '{lock_name}' is already free (no lock file on disk).",
                "was_locked": False
            }

        pid = info.get("pid", 0) if info else 0
        created_ts = info.get("created_timestamp", 0) if info else 0
        age_sec = (datetime.utcnow().timestamp() - created_ts) if created_ts else 0

        is_alive = is_pid_alive(pid) if pid else False
        is_stale = (not is_alive) or (age_sec > LOCK_STALE_TIMEOUT_SEC)

        if not is_stale and not force:
            return {
                "success": False,
                "error": f"Lock '{lock_name}' is actively held by PID {pid} (Age: {age_sec:.1f}s). Set force=True to forcibly break.",
                "is_stale": False,
                "pid": pid,
                "age_seconds": round(age_sec, 1)
            }

        # Release the lock file
        try:
            lock_file.unlink(missing_ok=True)
            logger.info(f"[ACTION] Released lock '{lock_name}' (PID: {pid}, Stale: {is_stale}, Forced: {force})")
            return {
                "success": True,
                "message": f"Lock '{lock_name}' successfully released.",
                "was_stale": is_stale,
                "forced": force,
                "released_pid": pid,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to delete lock file: {str(e)}"}

    def get_review_queue(self, db: Session) -> Dict[str, Any]:
        """
        Returns all jobs currently requiring operator attention (NEEDS_REVIEW or FAILED).
        """
        jobs = db.query(Job).filter(
            Job.state.in_([JobState.NEEDS_REVIEW.value, JobState.FAILED.value])
        ).order_by(Job.updated_at.desc()).all()

        results = []
        for j in jobs:
            topic_title = j.topic.title if j.topic else "Unknown Topic"
            category = j.topic.category if j.topic else "General"
            results.append({
                "id": j.id,
                "state": j.state,
                "title": topic_title,
                "category": category,
                "error_message": j.error_message or "Unknown Error",
                "retry_count": j.retry_count,
                "created_at": j.created_at.isoformat() + "Z" if j.created_at else None,
                "updated_at": j.updated_at.isoformat() + "Z" if j.updated_at else None,
            })

        return {
            "count": len(results),
            "jobs": results,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def set_voice_preference(self, db: Session, voice_id: str) -> Dict[str, Any]:
        """
        Updates and persists active production voice setting in SQLite.
        """
        from engines.tts_engine import set_active_voice, AVAILABLE_VOICES
        try:
            set_active_voice(db, voice_id)
            voice_info = next((v for v in AVAILABLE_VOICES if v["id"] == voice_id), None)
            display_name = voice_info["display_name"] if voice_info else voice_id

            # Sync updated configuration to Google Drive canonical database if available
            try:
                from core.database_sync import upload_canonical_database
                upload_canonical_database()
                logger.info(f"[VOICE CONFIG] Canonical database successfully synced to Drive vault with voice '{voice_id}'.")
            except Exception as sync_err:
                logger.debug(f"[VOICE CONFIG] Cloud DB sync notice (skipped or offline): {sync_err}")

            return {
                "success": True,
                "message": f"Active production voice updated to {display_name} ({voice_id}).",
                "voice_id": voice_id,
                "voice_info": voice_info,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    def trigger_self_healing(self, db: Session) -> Dict[str, Any]:
        """
        Executes full autonomous self-healing, stale recovery, and vault reconciliation.
        """
        from core.recovery_manager import RecoveryManager
        try:
            recovery_mgr = RecoveryManager(self.drive_engine)
            summary = recovery_mgr.run_full_self_healing(db)
            return {
                "success": True,
                "message": f"Autonomous self-healing completed ({summary['stale_jobs_recovered_count']} stale jobs, {summary['vault_recoveries_count']} vault files, {summary['youtube_reconciled_count']} YouTube syncs).",
                "summary": summary,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            logger.error(f"Self-healing execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
