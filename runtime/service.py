"""
Autonomous Runtime & Worker Service for AL-AMR.
Provides a persistent autonomous service coordinating:
  1. Periodic intelligence harvesting
  2. Idempotent production queue processing & crash resumption
  3. Scheduled YouTube publishing adhering to daily limits
  4. Automatic retry & recovery of eligible failed jobs
  5. Real-time telemetry connection to Mission Control
  6. Graceful shutdown with signal handling and concurrency locking
"""
import os
import sys
import time
import json
import signal
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from sqlalchemy.orm import Session

from config.settings import PROJECT_ROOT, TEST_MODE, LOCKS_DIR
from config.constants import JobState, DAILY_SHORTS_LIMIT, get_business_day_bounds_utc
from core.database import SessionLocal
from core.models import Job, Topic, UploadRecord, ScriptRecord
from core.state_machine import StateMachine
from core.lock import ProcessLock, ProcessLockError, is_pid_alive
from core.content_profile import get_active_profile, list_registered_profiles
from core.discovery_profile import get_active_discovery_profile
from engines.orchestrator import ProductionOrchestrator, ExecutionCapabilities, STATE_RANK
from engines.drive_engine import is_valid_ready_short
from runtime.config import RuntimeConfig
from dashboard.mission_control_service import mission_control_service

logger = logging.getLogger("AutonomousRuntime")


class PreflightGateError(RuntimeError):
    """Raised when one or more pre-flight safety gates fail during canary execution."""
    def __init__(self, gate_name: str, reason: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(f"Canary pre-flight gate '{gate_name}' failed: {reason}")
        self.gate_name = gate_name
        self.reason = reason
        self.details = details or {}


class AutonomousRuntimeService:
    """
    Persistent Autonomous Runtime Service.
    Coordinates continuous Shorts intelligence, queue replenishment,
    lifecycle orchestration, crash recovery, and scheduled publishing.
    """

    def __init__(
        self,
        config: Optional[RuntimeConfig] = None,
        orchestrator: Optional[ProductionOrchestrator] = None
    ):
        self.config = config or RuntimeConfig.from_env()
        self.orchestrator = orchestrator or self._init_orchestrator()
        self.lock = ProcessLock(name="autonomous_worker", command_name="autonomous-runtime-worker")

        self._running: bool = False
        self._stopping: bool = False
        self._last_harvest_time: float = 0.0
        self._last_recovery_time: float = 0.0
        self._cycles_completed: int = 0
        self._jobs_produced_count: int = 0
        self._jobs_published_count: int = 0
        self._jobs_recovered_count: int = 0
        self._errors_count: int = 0
        self._last_successful_run: Optional[str] = None
        self._current_task: str = "IDLE"
        self._current_job_id: Optional[str] = None
        self._last_error: Optional[str] = None
        self._canary_consumed: bool = False
        self._canary_telemetry: Optional[Dict[str, Any]] = None

    def _init_orchestrator(self) -> ProductionOrchestrator:
        """Initializes the production orchestrator adhering to configured capabilities."""
        if self.config.dry_run or TEST_MODE:
            caps = ExecutionCapabilities.sandboxed_testing()
        elif self.config.canary_mode:
            caps = ExecutionCapabilities.live_canary()
        else:
            caps = ExecutionCapabilities.production()
        return ProductionOrchestrator(
            content_profile=get_active_profile(),
            discovery_profile=get_active_discovery_profile(),
            capabilities=caps,
            max_retries=self.config.max_retries
        )

    # ==========================================================================
    # LIFECYCLE MANAGEMENT & SIGNAL HANDLING
    # ==========================================================================

    def start(self, run_once: bool = False):
        """
        Starts the autonomous worker service.
        Acquires process lock, registers signal handlers, and enters execution loop.
        """
        if not self.lock.acquire():
            logger.warning("[RUNTIME] Another autonomous worker is already active. Aborting start.")
            raise ProcessLockError("Autonomous worker process lock is currently held.")

        self._running = True
        self._stopping = False
        self._register_signals()

        mission_control_service.log_event(
            category="RUNTIME",
            message=f"Autonomous runtime service started (PID: {os.getpid()}, DryRun: {self.config.dry_run})",
            severity="INFO",
            metadata={"pid": os.getpid(), "dry_run": self.config.dry_run, "interval": self.config.interval_sec}
        )

        logger.info(f"[RUNTIME] Autonomous runtime service started (PID: {os.getpid()})")
        self._write_heartbeat(status="ONLINE", current_task="INITIALIZING")

        try:
            if run_once:
                self.run_tick()
            else:
                self.run_forever()
        finally:
            self.stop()

    def stop(self, signum: Optional[int] = None, frame: Any = None):
        """
        Gracefully terminates the autonomous worker service.
        Flushes telemetry, updates state file, and releases process lock.
        """
        if self._stopping:
            return
        self._stopping = True
        self._running = False

        logger.info("[RUNTIME] Shutting down autonomous runtime worker...")
        self._current_task = "STOPPING"
        self._write_heartbeat(status="OFFLINE", current_task="SHUTDOWN")

        mission_control_service.log_event(
            category="RUNTIME",
            message=f"Autonomous runtime service shut down cleanly (Cycles: {self._cycles_completed})",
            severity="INFO",
            metadata={"cycles_completed": self._cycles_completed, "jobs_produced": self._jobs_produced_count}
        )

        self.lock.release()
        logger.info("[RUNTIME] Autonomous runtime worker stopped.")

    def _register_signals(self):
        """Attaches graceful termination handlers for standard system signals."""
        try:
            signal.signal(signal.SIGINT, self.stop)
            signal.signal(signal.SIGTERM, self.stop)
            if hasattr(signal, "SIGBREAK"):  # Windows break signal
                signal.signal(signal.SIGBREAK, self.stop)
        except (ValueError, AttributeError):
            pass

    # ==========================================================================
    # HEARTBEAT & PERSISTENT STATE BRIDGE
    # ==========================================================================

    def _write_heartbeat(self, status: str = "ONLINE", current_task: Optional[str] = None):
        """
        Persists runtime heartbeat and operational metrics to disk for Mission Control.
        """
        if current_task is not None:
            self._current_task = current_task

        now_iso = datetime.now(timezone.utc).isoformat()
        next_run_iso = (datetime.now(timezone.utc) + timedelta(seconds=self.config.interval_sec)).isoformat()
        prof = get_active_profile()

        state_payload = {
            "pid": os.getpid(),
            "status": status,
            "online": (status == "ONLINE"),
            "started_at": getattr(self, "_started_at", now_iso),
            "last_heartbeat": now_iso,
            "current_task": self._current_task,
            "current_job_id": self._current_job_id,
            "active_niche": prof.name if prof else "DEFAULT",
            "last_successful_run": self._last_successful_run,
            "next_scheduled_run": next_run_iso,
            "cycles_completed": self._cycles_completed,
            "jobs_produced": self._jobs_produced_count,
            "jobs_published": self._jobs_published_count,
            "jobs_recovered": self._jobs_recovered_count,
            "errors_count": self._errors_count,
            "last_error": self._last_error,
            "dry_run": self.config.dry_run,
            "canary_mode": self.config.canary_mode,
            "canary_consumed": self._canary_consumed,
            "canary_telemetry": self._canary_telemetry
        }

        try:
            self.config.state_file_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.config.state_file_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
            temp_path.replace(self.config.state_file_path)
        except Exception as e:
            logger.warning(f"[RUNTIME] Failed to write heartbeat: {e}")

    # ==========================================================================
    # EXECUTION TICK & PERIODIC LOOPS
    # ==========================================================================

    def run_tick(self) -> Dict[str, Any]:
        """
        Executes a single end-to-end autonomous cycle across all 4 subsystems:
          1. Check operational mode & queue pause
          2. Crash recovery & incomplete job resumption
          3. Intelligence harvesting (if interval elapsed)
          4. Production queue replenishment (if buffer stock low)
          5. Scheduled publication dispatch (if slot reached)
          6. Eligible failed job auto-recovery (if interval elapsed)
        """
        tick_summary: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resumed_job": None,
            "harvested_count": 0,
            "produced_job": None,
            "published_job": None,
            "recovered_count": 0,
            "status": "SUCCESS"
        }

        # Check if Mission Control has paused queue
        if mission_control_service.is_queue_paused():
            logger.info("[RUNTIME] Queue is paused by Mission Control operator. Skipping production tick.")
            self._write_heartbeat(status="ONLINE", current_task="QUEUE_PAUSED")
            tick_summary["status"] = "QUEUE_PAUSED"
            return tick_summary

        db: Session = SessionLocal()
        try:
            # 1. First Priority: Incomplete Job Resumption (Crash-Safe Recovery)
            self._current_task = "CRASH_RECOVERY_CHECK"
            self._write_heartbeat()
            resumed = self._resume_incomplete_job(db)
            if resumed:
                tick_summary["resumed_job"] = resumed.job_id
                self._jobs_produced_count += 1
                self._last_successful_run = datetime.now(timezone.utc).isoformat()
                return tick_summary

            # 2. Intelligence Harvesting Loop
            now_ts = time.time()
            if (now_ts - self._last_harvest_time) >= self.config.harvest_interval_sec:
                self._current_task = "HARVESTING_INTELLIGENCE"
                self._write_heartbeat()
                harvest_count = self._cycle_intelligence_harvest(db)
                tick_summary["harvested_count"] = harvest_count
                self._last_harvest_time = now_ts

            # 3. Scheduled Publishing Loop
            self._current_task = "CHECKING_SCHEDULED_PUBLISHING"
            self._write_heartbeat()
            pub_job_id = self._cycle_scheduled_publishing(db)
            if pub_job_id:
                tick_summary["published_job"] = pub_job_id
                self._jobs_published_count += 1

            # 4. Production Queue Replenishment
            self._current_task = "PROCESSING_PRODUCTION_QUEUE"
            self._write_heartbeat()
            produced_report = self._cycle_production_queue(db)
            if produced_report and produced_report.success:
                tick_summary["produced_job"] = produced_report.job_id
                self._jobs_produced_count += 1
                self._last_successful_run = datetime.now(timezone.utc).isoformat()

            # 5. Failed Job Auto-Recovery Loop
            if (now_ts - self._last_recovery_time) >= self.config.recovery_interval_sec:
                self._current_task = "RECOVERING_FAILED_JOBS"
                self._write_heartbeat()
                rec_count = self._cycle_failed_jobs_recovery(db)
                tick_summary["recovered_count"] = rec_count
                self._last_recovery_time = now_ts

            self._cycles_completed += 1
            self._current_task = "IDLE"
            self._current_job_id = None
            self._write_heartbeat()

        except Exception as tick_err:
            self._errors_count += 1
            self._last_error = str(tick_err)
            self._current_task = "ERROR"
            self._write_heartbeat()
            logger.error(f"[RUNTIME] Error in autonomous cycle tick: {tick_err}", exc_info=True)
            tick_summary["status"] = "ERROR"
            tick_summary["error"] = str(tick_err)
            mission_control_service.log_event(
                category="FAILURE",
                message=f"Autonomous runtime cycle failed: {tick_err}",
                severity="ERROR",
                metadata={"error": str(tick_err)}
            )
        finally:
            db.close()

        return tick_summary

    def run_forever(self):
        """Main persistent service loop executing ticks on interval."""
        logger.info(f"[RUNTIME] Starting continuous loop (Interval: {self.config.interval_sec}s)")
        while self._running and not self._stopping:
            self.run_tick()
            # Sleep in small increments for responsive shutdown signal
            elapsed = 0.0
            sleep_chunk = 1.0
            while elapsed < self.config.interval_sec and self._running and not self._stopping:
                time.sleep(sleep_chunk)
                elapsed += sleep_chunk

    # ==========================================================================
    # SUBSYSTEM 1: CRASH RECOVERY & IN-FLIGHT RESUMPTION
    # ==========================================================================

    def _resume_incomplete_job(self, db: Session) -> Optional[Any]:
        """
        Discovers any in-flight production job interrupted by process termination
        and resumes execution from its exact intermediate stage.
        """
        # Exclude terminal states and post-production states awaiting publishing:
        # PUBLISHED, FAILED, NEEDS_REVIEW, QUEUED, READY_TO_UPLOAD, SCHEDULED
        in_flight_states = [
            s for s in STATE_RANK.keys()
            if s not in [
                JobState.PUBLISHED.value,
                JobState.FAILED.value,
                JobState.NEEDS_REVIEW.value,
                JobState.QUEUED.value,
                JobState.READY_TO_UPLOAD.value,
                JobState.SCHEDULED.value,
            ]
        ]

        cutoff = datetime.utcnow() - timedelta(hours=24)
        query = db.query(Job).join(Topic, Job.topic_id == Topic.id).filter(
            Job.state.in_(in_flight_states),
            Job.updated_at >= cutoff
        )
        if not (self.config.dry_run or TEST_MODE):
            query = query.filter(~Topic.id.like("test_%"))
        incomplete_job = query.order_by(Job.updated_at.desc()).first()
        if not incomplete_job:
            return None

        topic = db.query(Topic).filter(Topic.id == incomplete_job.topic_id).first() if incomplete_job.topic_id else None
        logger.info(f"[RUNTIME_RECOVERY] Found incomplete job {incomplete_job.id} at state '{incomplete_job.state}'. Resuming...")
        self._current_job_id = incomplete_job.id
        self._write_heartbeat(current_task=f"RESUMING_JOB_{incomplete_job.id}")

        mission_control_service.log_event(
            category="RECOVERY",
            message=f"Resuming incomplete job {incomplete_job.id} from stage '{incomplete_job.state}'",
            severity="WARN",
            metadata={"job_id": incomplete_job.id, "state": incomplete_job.state, "topic": topic.title if topic else None}
        )

        report = self.orchestrator.produce_job(topic=topic, job_id=incomplete_job.id, db=db)
        if report.success:
            mission_control_service.log_event(
                category="PRODUCTION",
                message=f"Successfully recovered and completed job {incomplete_job.id}",
                severity="SUCCESS",
                metadata={"job_id": incomplete_job.id, "final_state": report.final_state}
            )
        return report

    # ==========================================================================
    # SUBSYSTEM 2: PERIODIC INTELLIGENCE HARVESTING
    # ==========================================================================

    def _cycle_intelligence_harvest(self, db: Session) -> int:
        """
        Gathers candidate topics dynamically via DiscoveryProfile strategy.
        Applies multi-source evidence filtering and persists valid candidates.
        """
        allow_net_read = getattr(self.orchestrator.capabilities, "allow_network_read", True)
        is_test = self.config.dry_run or TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")
        if not allow_net_read or is_test:
            logger.debug("[RUNTIME_HARVEST] Offline / sandboxed mode: skipping external intelligence harvest.")
            self._last_harvest_time = time.time()
            return 0

        logger.info("[RUNTIME_HARVEST] Initiating periodic intelligence harvest...")
        self._last_harvest_time = time.time()
        try:
            raw_candidates = self.orchestrator.stage_discover(db, limit=10)
            if not raw_candidates:
                logger.info("[RUNTIME_HARVEST] No new intelligence candidates found.")
                return 0

            ranked = self.orchestrator.stage_filter_and_rank(db, raw_candidates)
            logger.info(f"[RUNTIME_HARVEST] Harvested and verified {len(ranked)} candidate topics.")

            mission_control_service.log_event(
                category="DISCOVERY",
                message=f"Harvested {len(ranked)} candidate topics across intelligence feeds",
                severity="INFO",
                metadata={"count": len(ranked), "profile": self.orchestrator.discovery_profile.name}
            )
            return len(ranked)
        except Exception as harvest_err:
            logger.warning(f"[RUNTIME_HARVEST] Intelligence harvest notice: {harvest_err}")
            return 0

    def reconcile_reserve(self, db: Session) -> Dict[str, Any]:
        """
        Authoritative Google Drive reserve reconciliation (Step 6).
        - Production with allow_network_read=True: reads actual Google Drive reserve.
        - Sandboxed/test/dry-run mode: calculates deterministic local reserve with 0 network calls.
        - Only '01_READY' counts toward the reserve.
        - '02_PROCESSING' does NOT count.
        - Target reserve = 6 verified Shorts (or configured target_buffer_stock).
        - Calculates deficit = max(target_reserve - ready_count, 0).
        """
        target = self.config.target_buffer_stock
        allow_test = self.config.dry_run or TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")
        allow_net_read = getattr(self.orchestrator.capabilities, "allow_network_read", True)

        ready_count = 0
        processing_count = 0

        # Authoritative Cloud Drive reconciliation ONLY if live network read is explicitly permitted
        # and we are NOT in dry_run or offline test mode
        if allow_net_read and not self.config.dry_run and not allow_test:
            cloud_recon = self.orchestrator.drive_engine.reconcile_cloud_reserve(
                db=db,
                target_reserve=target,
                allow_test_artifacts=allow_test
            )
            ready_count = cloud_recon["ready_count"]
            processing_count = cloud_recon.get("processing_count", 0)
        else:
            # Deterministic local / sandboxed reserve calculation
            local_vault_ready = self.orchestrator.drive_engine.get_ready_stock_count(
                db=db,
                allow_test_artifacts=True,
                offline_only=True
            )
            if local_vault_ready > 0:
                ready_count = local_vault_ready
            else:
                db_ready = db.query(Job).filter(
                    Job.state.in_([JobState.QA.value, JobState.READY_TO_UPLOAD.value, JobState.SCHEDULED.value])
                ).count()
                ready_count = db_ready

        deficit = max(target - ready_count, 0)
        return {
            "ready_count": ready_count,
            "processing_count": processing_count,
            "target_reserve": target,
            "deficit": deficit,
            "is_healthy": (deficit == 0)
        }

    # ==========================================================================
    # SUBSYSTEM 3: PRODUCTION QUEUE REPLENISHMENT (AUTONOMOUS REFILL)
    # ==========================================================================

    def _cycle_production_queue(self, db: Session) -> Optional[Any]:
        """
        Evaluates Google Drive reserve. If reserve < 6 (or target_buffer_stock),
        executes sequential autonomous refill producing one Short at a time up to the required deficit.
        Reconciles cloud state after each production, and halts cleanly on any stop condition.
        """
        recon = self.reconcile_reserve(db)
        ready_count = recon["ready_count"]
        deficit = recon["deficit"]

        if deficit <= 0:
            logger.debug(f"[RUNTIME_QUEUE] Reserve stock healthy ({ready_count}/{self.config.target_buffer_stock}). Deficit is 0.")
            return None

        logger.info(f"[RUNTIME_QUEUE] Reserve stock deficit detected: {ready_count}/{self.config.target_buffer_stock} (Deficit: {deficit}). Initiating sequential refill...")

        # Sequential refill: produce one Short at a time up to deficit (bounded by max_batch_size per tick)
        refill_budget = min(deficit, self.config.max_batch_size)
        last_report = None
        in_cycle_topic_ids = set()

        for item_idx in range(refill_budget):
            # Check stop conditions before each sequential item:
            # 1. Queue pause interlock
            if mission_control_service.is_queue_paused():
                logger.warning("[RUNTIME_QUEUE] Queue is PAUSED by Mission Control. Halting refill cycle.")
                break

            # 2. Service shutdown
            if self._stopping:
                logger.info("[RUNTIME_QUEUE] Worker shutdown requested. Halting refill cycle.")
                break

            # 3. Provider cascade exhaustion check
            try:
                from core.gemini_client import GeminiClient
                client = GeminiClient()
                if client.is_provider_exhausted("openrouter"):
                    logger.warning("[RUNTIME_QUEUE] AI provider cascade exhausted. Halting refill cycle.")
                    break
            except Exception:
                pass

            # 4. Stop if reserve has already reached target
            curr_recon = self.reconcile_reserve(db)
            if curr_recon["deficit"] <= 0:
                logger.info(f"[RUNTIME_QUEUE] Reserve reached target ({curr_recon['ready_count']}/6). Stopping refill.")
                break

            # Select candidate topic with deduplication check
            existing_topic_ids = {
                j.topic_id for j in db.query(Job.topic_id).filter(Job.state != JobState.FAILED.value).all()
                if j.topic_id
            }
            existing_topic_ids.update(in_cycle_topic_ids)

            candidate_topic = db.query(Topic).filter(
                Topic.status.in_(["APPROVED", "VERIFIED"]),
                ~Topic.id.in_(existing_topic_ids)
            ).order_by(Topic.score.desc()).first()

            if candidate_topic:
                in_cycle_topic_ids.add(candidate_topic.id)

            if not candidate_topic:
                logger.info("[RUNTIME_QUEUE] Approved topic pool empty. Discovering fresh candidate...")
                discovered = self.orchestrator.stage_discover(db, limit=3, exclude_topic_ids=existing_topic_ids)
                filtered = self.orchestrator.stage_filter_and_rank(db, discovered)
                if filtered:
                    candidate_topic = filtered[0]

            if not candidate_topic:
                logger.info("[RUNTIME_QUEUE] No eligible candidate topics available for production. Halting refill.")
                break

            logger.info(f"[RUNTIME_QUEUE] [Sequential {item_idx+1}/{refill_budget}] Producing Short for: '{candidate_topic.title}' (Score: {candidate_topic.score})")
            self._current_job_id = f"job_pending_{candidate_topic.id[:8]}"
            self._write_heartbeat(current_task=f"PRODUCING_JOB_{candidate_topic.title[:20]}")

            mission_control_service.log_event(
                category="PRODUCTION",
                message=f"Starting autonomous production for topic '{candidate_topic.title}' (Deficit: {deficit})",
                severity="INFO",
                metadata={"topic_id": candidate_topic.id, "title": candidate_topic.title, "deficit": deficit}
            )

            # Produce job through pipeline & QA
            report = self.orchestrator.produce_job(topic=candidate_topic, db=db)
            last_report = report

            # Check production and QA outcome
            if not report.success:
                logger.warning(f"[RUNTIME_QUEUE] Production or QA failed for job {report.job_id}: {report.error_message}. Stopping refill cycle.")
                mission_control_service.log_event(
                    category="FAILURE",
                    message=f"Production failed for job {report.job_id}: {report.error_message}. Stopping refill.",
                    severity="ERROR",
                    metadata={"job_id": report.job_id, "error": report.error_message}
                )
                # STOP CONDITION: production/QA failure halts refill immediately
                break

            # Reconcile Drive state after production
            post_recon = self.reconcile_reserve(db)
            post_ready_count = post_recon["ready_count"]

            # Confirm cloud state deposit before claiming success
            if self.orchestrator.capabilities.allow_drive_write:
                if post_ready_count <= curr_recon["ready_count"]:
                    logger.error(f"[RUNTIME_QUEUE] Cloud deposit unconfirmed: ready stock did not increment ({post_ready_count} <= {curr_recon['ready_count']}). Halting refill.")
                    mission_control_service.log_event(
                        category="FAILURE",
                        message=f"Cloud verification failed: 01_READY stock did not increment after producing {report.job_id}",
                        severity="ERROR",
                        metadata={"job_id": report.job_id, "ready_count": post_ready_count}
                    )
                    # STOP CONDITION: required cloud operation failed
                    break

            # Success confirmed by resulting state
            mission_control_service.log_event(
                category="PRODUCTION",
                message=f"Successfully produced and verified job {report.job_id} (Reserve: {post_ready_count}/6)",
                severity="SUCCESS",
                metadata={"job_id": report.job_id, "final_state": report.final_state, "ready_count": post_ready_count}
            )

            # Check stop condition: reserve reaches 6
            if post_ready_count >= 6:
                logger.info(f"[RUNTIME_QUEUE] Google Drive reserve has reached target of 6 verified Shorts ({post_ready_count}/6). Stopping refill.")
                break

        return last_report

    # ==========================================================================
    # SUBSYSTEM 4: SCHEDULED PUBLISHING WITH DAILY LIMIT GUARD
    # ==========================================================================

    def _cycle_scheduled_publishing(self, db: Session) -> Optional[str]:
        """
        Identifies scheduled uploads whose assigned release slot has arrived,
        reads authoritative YouTube publication state and capacity,
        enforces the hard DAILY_SHORTS_LIMIT ceiling, and triggers publication.
        """
        now = datetime.now(timezone.utc)
        today = now.date()

        # Read actual YouTube publication state / capacity using existing integration
        try:
            occupied_slots, day_counts, slot_details = self.orchestrator.scheduler.get_authoritative_schedule_state(db)
            used_today = day_counts.get(today, 0)
        except Exception as yt_err:
            logger.warning(f"[RUNTIME_PUBLISH] Authoritative YouTube inventory query notice: {yt_err}")
            today_start, today_end = get_business_day_bounds_utc(now)
            used_today = db.query(UploadRecord).filter(
                UploadRecord.status.in_(["PUBLISHED", "SUCCESS"]),
                UploadRecord.published_at >= today_start,
                UploadRecord.published_at <= today_end
            ).count()

        # STOP CONDITION: daily YouTube publication capacity is exhausted
        if used_today >= DAILY_SHORTS_LIMIT:
            logger.info(f"[RUNTIME_PUBLISH] Daily YouTube publication capacity exhausted for {today} ({used_today}/{DAILY_SHORTS_LIMIT}). Stopping publishing.")
            return None

        # Find scheduled jobs ready to publish
        due_upload = db.query(UploadRecord).join(Job, Job.id == UploadRecord.job_id).filter(
            UploadRecord.status == "SCHEDULED",
            UploadRecord.scheduled_publish_at <= now,
            Job.state == JobState.SCHEDULED.value
        ).order_by(UploadRecord.scheduled_publish_at.asc()).first()

        if not due_upload:
            return None

        job = db.query(Job).filter(Job.id == due_upload.job_id).first()
        if not job:
            return None

        logger.info(f"[RUNTIME_PUBLISH] Publishing due Short {due_upload.id} for job {job.id}...")
        self._write_heartbeat(current_task=f"PUBLISHING_JOB_{job.id}")

        mission_control_service.log_event(
            category="PUBLISHING",
            message=f"Publishing scheduled Short for job {job.id}",
            severity="INFO",
            metadata={"job_id": job.id, "upload_id": due_upload.id}
        )

        success = self.orchestrator.stage_publish(db, job, due_upload)
        if success:
            mission_control_service.log_event(
                category="PUBLISHING",
                message=f"Short published successfully for job {job.id}",
                severity="SUCCESS",
                metadata={"job_id": job.id, "youtube_video_id": due_upload.youtube_video_id}
            )
            return job.id
        return None

    # ==========================================================================
    # SUBSYSTEM 5: ELIGIBLE FAILED JOB AUTO-RECOVERY
    # ==========================================================================

    def _cycle_failed_jobs_recovery(self, db: Session) -> int:
        """
        Finds failed jobs with retry_count < max_retries and transitions them
        back to QUEUED so they can be idempotently resumed on next cycle.
        """
        eligible_failed = db.query(Job).filter(
            Job.state == JobState.FAILED.value,
            Job.retry_count < self.config.max_retries
        ).all()

        recovered_count = 0
        for job in eligible_failed:
            job.retry_count = (job.retry_count or 0) + 1
            job.error_message = None
            StateMachine.transition(db, job, JobState.QUEUED, f"Autonomous auto-recovery (Retry #{job.retry_count})")
            recovered_count += 1

            mission_control_service.log_event(
                category="RECOVERY",
                message=f"Auto-recovered failed job {job.id} (Retry attempt #{job.retry_count})",
                severity="INFO",
                metadata={"job_id": job.id, "retry_count": job.retry_count}
            )

        if recovered_count > 0:
            logger.info(f"[RUNTIME_RECOVERY] Successfully auto-recovered {recovered_count} failed jobs.")
            self._jobs_recovered_count += recovered_count

        return recovered_count

    # ==========================================================================
    # SUBSYSTEM 6: CONTROLLED LIVE-CLOUD CANARY (AL-AMR STEP 7)
    # ==========================================================================

    def run_preflight_gates(self, db: Session) -> Dict[str, Any]:
        """
        Evaluates the 8 pre-flight safety gates required for canary execution:
          Gate 1: Worker process lock is available.
          Gate 2: Mission Control queue is NOT paused and NOT in SAFE_MODE.
          Gate 3: Required AI provider credentials present and unexhausted.
          Gate 4: Google Drive vault is reachable and verified.
          Gate 5: YouTube schedule/publication state is readable.
          Gate 6: Cloud reserve state is readable.
          Gate 7: Daily publication limit has not been reached (< DAILY_SHORTS_LIMIT).
          Gate 8: Canary has not already been run in this session.
        """
        gates: Dict[str, Dict[str, Any]] = {}
        all_passed = True
        first_failure_gate: Optional[str] = None
        first_failure_reason: Optional[str] = None

        def record_gate(name: str, passed: bool, reason: str, details: Optional[Dict[str, Any]] = None):
            nonlocal all_passed, first_failure_gate, first_failure_reason
            gates[name] = {
                "passed": passed,
                "reason": reason,
                "details": details or {}
            }
            if not passed and all_passed:
                all_passed = False
                first_failure_gate = name
                first_failure_reason = reason

        # Gate 1: Worker process lock is available
        info = self.lock.get_lock_info()
        if info:
            owner_pid = info.get("pid")
            if owner_pid and owner_pid != os.getpid() and is_pid_alive(owner_pid):
                record_gate("process_lock", False, f"Worker process lock is held by another live process (PID: {owner_pid})")
            else:
                record_gate("process_lock", True, "Worker process lock is available or held by current process")
        else:
            record_gate("process_lock", True, "Worker process lock is available")

        # Gate 2: Mission Control queue is NOT paused and NOT in SAFE_MODE
        op_state = mission_control_service.get_operational_state()
        is_paused = mission_control_service.is_queue_paused()
        mode = op_state.get("mode", "AUTONOMOUS")
        if is_paused or mode in ("PAUSED", "SAFE_MODE", "STOPPED", "ERROR", "NEEDS_REVIEW"):
            record_gate(
                "queue_interlock",
                False,
                f"Queue interlock active (Mode: {mode}, Paused: {is_paused})",
                {"mode": mode, "queue_paused": is_paused}
            )
        else:
            record_gate("queue_interlock", True, f"Queue is active and operational mode is {mode}")

        # Gate 3: Required AI provider credentials are present and unexhausted
        try:
            from core.gemini_client import get_gemini_client
            gemini_client = get_gemini_client()
            avail_providers = gemini_client.get_available_providers()
            if not avail_providers and not (self.config.dry_run or TEST_MODE):
                record_gate("ai_providers", False, "No unexhausted AI providers available in cascade (Primary -> Secondary -> Groq -> OpenRouter)")
            else:
                prov_names = [p["name"] for p in avail_providers]
                record_gate(
                    "ai_providers",
                    True,
                    f"AI providers available: {prov_names or ['SANDBOX_MOCK']}",
                    {"providers": prov_names}
                )
        except Exception as ai_err:
            if not (self.config.dry_run or TEST_MODE):
                record_gate("ai_providers", False, f"AI provider check failed: {ai_err}")
            else:
                record_gate("ai_providers", True, f"Sandboxed AI mode active ({ai_err})")

        # Gate 4: Google Drive vault reachable and verified
        allow_network = getattr(self.orchestrator.capabilities, "allow_network_read", True)
        is_test_env = self.config.dry_run or TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")
        if not allow_network or is_test_env:
            record_gate("drive_vault", True, "Sandboxed local vault active (test/dry-run mode)")
        else:
            try:
                vault = self.orchestrator.drive_engine.inspect_or_init_vault(create_if_missing=False)
                has_vault = bool(vault and (vault.get("root") or vault.get("vault_root_id")) and vault.get("01_READY"))
                if not has_vault:
                    record_gate("drive_vault", False, "Google Drive vault unreachable or 01_READY folder missing")
                else:
                    record_gate("drive_vault", True, "Google Drive vault reachable and verified")
            except Exception as ve:
                record_gate("drive_vault", False, f"Google Drive vault inspection error: {ve}")

        # Gate 5: YouTube schedule/publication state readable
        day_counts: Dict[Any, int] = {}
        try:
            occupied_slots, day_counts, slot_details = self.orchestrator.scheduler.get_authoritative_schedule_state(db)
            record_gate(
                "youtube_state",
                True,
                "Authoritative YouTube schedule state successfully queried",
                {"total_occupied_slots": len(occupied_slots)}
            )
        except Exception as ye:
            record_gate("youtube_state", False, f"Unable to read authoritative YouTube schedule state: {ye}")

        # Gate 6: Cloud reserve state readable
        try:
            recon = self.reconcile_reserve(db)
            ready_stock = recon.get("ready_count")
            if ready_stock is None:
                record_gate("reserve_state", False, "Cloud reserve reconciliation returned empty count")
            else:
                record_gate(
                    "reserve_state",
                    True,
                    f"Cloud reserve state verified: {ready_stock}/6 verified Shorts (Deficit: {recon.get('deficit')})",
                    recon
                )
        except Exception as re_err:
            record_gate("reserve_state", False, f"Cloud reserve reconciliation failed: {re_err}")

        # Gate 7: Daily publication limit has not been reached
        now = datetime.now(timezone.utc)
        today = now.date()
        used_today = day_counts.get(today, 0)
        if used_today >= DAILY_SHORTS_LIMIT:
            record_gate(
                "daily_limit",
                False,
                f"Daily YouTube publication capacity reached for {today} ({used_today}/{DAILY_SHORTS_LIMIT})",
                {"used_today": used_today, "limit": DAILY_SHORTS_LIMIT}
            )
        else:
            record_gate(
                "daily_limit",
                True,
                f"Daily YouTube publication capacity available ({used_today}/{DAILY_SHORTS_LIMIT})",
                {"used_today": used_today, "limit": DAILY_SHORTS_LIMIT}
            )

        # Gate 8: Canary has not already been run
        if self._canary_consumed:
            record_gate("canary_consumed", False, "Canary has already been executed in this session and cannot be re-run")
        else:
            record_gate("canary_consumed", True, "Canary has not yet been executed in this session")

        return {
            "all_passed": all_passed,
            "failed_gate": first_failure_gate,
            "reason": first_failure_reason,
            "gates": gates,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    def run_canary(self) -> Dict[str, Any]:
        """
        Executes a strictly bounded production canary run (AL-AMR Step 7):
          - Enforces explicit opt-in (canary_mode=True).
          - Prohibits batch production (max_batch_size = 1 strictly).
          - Prohibits parallel production.
          - Acquires worker process lock.
          - Evaluates all 8 pre-flight safety gates.
          - Resumes in-flight job if one exists, else selects exactly 1 candidate topic.
          - Executes job through canonical orchestrator.
          - Confirms artifact deposited into Google Drive 01_READY and verified.
          - Prohibits automatic YouTube publishing (canary ends in 01_READY).
          - Prohibits automatic refill after canary.
          - Releases process lock cleanly.
        """
        if not self.config.canary_mode:
            raise RuntimeError("Canary execution requires explicit opt-in (canary_mode=True or --canary).")

        if self._canary_consumed:
            raise RuntimeError("Canary has already been executed in this session and cannot be re-run.")

        # Ensure orchestrator has canary capabilities
        if not hasattr(self.orchestrator, "capabilities") or self.orchestrator.capabilities is None:
            if self.config.dry_run or TEST_MODE:
                self.orchestrator.capabilities = ExecutionCapabilities.sandboxed_testing()
            else:
                self.orchestrator.capabilities = ExecutionCapabilities.live_canary()
        # Non-bypassable safety boundary: canary strictly prohibits YouTube publishing & scheduling
        self.orchestrator.capabilities.allow_youtube_write = False
        self.orchestrator.capabilities.allow_schedule = False

        # Acquire lock
        if not self.lock.acquire():
            logger.warning("[CANARY] Worker process lock is currently held by another process. Aborting.")
            raise ProcessLockError("Autonomous worker process lock is currently held.")

        telemetry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "canary_mode": True,
            "status": "INITIALIZING",
            "preflight": None,
            "job_id": None,
            "topic_title": None,
            "resumed_in_flight": False,
            "stages_completed": [],
            "drive_file_id": None,
            "verified_in_ready": False,
            "post_canary_reserve": None,
            "error": None
        }

        self._canary_telemetry = telemetry
        self._write_heartbeat(status="ONLINE", current_task="CANARY_STARTING")

        db = SessionLocal()
        try:
            # 1. Run Pre-flight Safety Gates
            preflight = self.run_preflight_gates(db)
            telemetry["preflight"] = preflight
            if not preflight["all_passed"]:
                fail_reason = f"Gate '{preflight['failed_gate']}' failed: {preflight['reason']}"
                logger.error(f"[CANARY] Pre-flight check failed: {fail_reason}")
                telemetry["status"] = "PREFLIGHT_FAILED"
                telemetry["error"] = fail_reason
                mission_control_service.log_event(
                    category="CANARY",
                    message=f"Canary pre-flight safety check failed: {fail_reason}",
                    severity="ERROR",
                    metadata={"failed_gate": preflight["failed_gate"], "reason": preflight["reason"]}
                )
                self._current_task = "PREFLIGHT_FAILED"
                self._write_heartbeat()
                return telemetry

            logger.info("[CANARY] All 8 pre-flight safety gates PASSED. Proceeding to canary production...")
            mission_control_service.log_event(
                category="CANARY",
                message="All 8 pre-flight safety gates PASSED. Proceeding with single production job.",
                severity="INFO",
                metadata={"gates": list(preflight["gates"].keys())}
            )

            # Record baseline cloud reserve
            initial_recon = self.reconcile_reserve(db)

            # 2. Check for in-flight job resumption (Crash recovery idempotency)
            in_flight_states = [
                s for s in STATE_RANK.keys()
                if s not in [
                    JobState.PUBLISHED.value,
                    JobState.FAILED.value,
                    JobState.NEEDS_REVIEW.value,
                    JobState.QUEUED.value,
                    JobState.READY_TO_UPLOAD.value,
                    JobState.SCHEDULED.value,
                ]
            ]
            cutoff = datetime.utcnow() - timedelta(hours=24)
            query = db.query(Job).join(Topic, Job.topic_id == Topic.id).filter(
                Job.state.in_(in_flight_states),
                Job.updated_at >= cutoff
            )
            if not (self.config.dry_run or TEST_MODE):
                query = query.filter(~Topic.id.like("test_%"))
            target_job = query.order_by(Job.updated_at.desc()).first()

            if target_job:
                telemetry["resumed_in_flight"] = True
                target_topic = db.query(Topic).filter(Topic.id == target_job.topic_id).first() if target_job.topic_id else None
                logger.info(f"[CANARY] Discovered in-flight job {target_job.id} at stage '{target_job.state}'. Resuming rather than duplicating...")
            else:
                existing_topic_ids = {
                    j.topic_id for j in db.query(Job.topic_id).filter(Job.state != JobState.FAILED.value).all()
                    if j.topic_id
                }
                candidate_topic = db.query(Topic).filter(
                    Topic.status.in_(["APPROVED", "VERIFIED"]),
                    ~Topic.id.in_(existing_topic_ids)
                ).order_by(Topic.score.desc()).first()

                if not candidate_topic:
                    logger.info("[CANARY] No approved candidate topics. Discovering 1 fresh candidate...")
                    discovered = self.orchestrator.stage_discover(db, limit=1, exclude_topic_ids=existing_topic_ids)
                    filtered = self.orchestrator.stage_filter_and_rank(db, discovered)
                    if filtered:
                        candidate_topic = filtered[0]

                if not candidate_topic:
                    raise RuntimeError("No candidate topics available for canary production.")

                target_topic = candidate_topic
                target_job = None

            # Execute single production job
            self._current_task = f"CANARY_PRODUCING_{target_topic.title[:20] if target_topic else 'JOB'}"
            self._write_heartbeat()

            if target_job:
                telemetry["job_id"] = target_job.id
                telemetry["topic_title"] = target_topic.title if target_topic else "Unknown Topic"
                report = self.orchestrator.produce_job(topic=target_topic, job_id=target_job.id, db=db)
            else:
                telemetry["topic_title"] = target_topic.title
                report = self.orchestrator.produce_job(topic=target_topic, db=db)
                telemetry["job_id"] = report.job_id

            # 3. Verify Production & QA Outcome
            if not report.success:
                fail_msg = f"Canary production failed at stage '{report.final_state}': {report.error_message}"
                logger.error(f"[CANARY] {fail_msg}")
                telemetry["status"] = "FAILED"
                telemetry["error"] = report.error_message
                self._canary_consumed = True
                self._current_task = "CANARY_FAILED"
                self._write_heartbeat()
                mission_control_service.log_event(
                    category="CANARY",
                    message=fail_msg,
                    severity="ERROR",
                    metadata={"job_id": report.job_id, "error": report.error_message, "final_state": report.final_state}
                )
                return telemetry

            # 4. Cloud Confirmation in Google Drive 01_READY
            post_recon = self.reconcile_reserve(db)
            post_ready = post_recon.get("ready_count", 0)
            telemetry["post_canary_reserve"] = post_ready

            drive_file = None
            try:
                vault_files = self.orchestrator.drive_engine.list_files_in_folder("01_READY")
                for vf in vault_files:
                    vf_props = vf.get("properties", {}) or {}
                    if vf_props.get("job_id") == report.job_id or report.job_id in vf.get("name", ""):
                        is_val, _ = is_valid_ready_short(vf, db=db, allow_test_artifacts=self.config.dry_run or TEST_MODE)
                        if is_val:
                            drive_file = vf
                            break
            except Exception as dfe:
                logger.warning(f"[CANARY] Notice querying Drive 01_READY files: {dfe}")

            if self.orchestrator.capabilities.allow_drive_write:
                if not drive_file and post_ready <= initial_recon.get("ready_count", 0):
                    err_msg = f"Canary cloud confirmation failed: Short for job {report.job_id} not verified in 01_READY"
                    logger.error(f"[CANARY] {err_msg}")
                    telemetry["status"] = "CLOUD_CONFIRMATION_FAILED"
                    telemetry["error"] = err_msg
                    self._canary_consumed = True
                    mission_control_service.log_event(
                        category="CANARY",
                        message=err_msg,
                        severity="ERROR",
                        metadata={"job_id": report.job_id, "ready_count": post_ready}
                    )
                    return telemetry

            if drive_file:
                telemetry["drive_file_id"] = drive_file.get("id")
                telemetry["verified_in_ready"] = True
            elif not self.orchestrator.capabilities.allow_drive_write:
                telemetry["verified_in_ready"] = True

            # Reconcile DB job state matches cloud state
            job_rec = db.query(Job).filter(Job.id == report.job_id).first()
            if job_rec and job_rec.state != JobState.READY_TO_UPLOAD.value:
                StateMachine.transition(db, job_rec, JobState.READY_TO_UPLOAD, "Canary deposit confirmed in 01_READY")

            # 5. Success Finalization (Strictly NO automatic publishing & NO refill)
            telemetry["status"] = "SUCCESS"
            self._canary_consumed = True
            self._jobs_produced_count += 1
            self._last_successful_run = datetime.now(timezone.utc).isoformat()
            self._current_task = "CANARY_COMPLETED"
            self._write_heartbeat()

            mission_control_service.log_event(
                category="CANARY",
                message=f"Canary production and cloud verification SUCCEEDED for job {report.job_id} (Reserve: {post_ready}/6)",
                severity="SUCCESS",
                metadata={
                    "job_id": report.job_id,
                    "drive_file_id": telemetry.get("drive_file_id"),
                    "reserve_count": post_ready,
                    "verified_in_ready": telemetry["verified_in_ready"],
                    "final_state": JobState.READY_TO_UPLOAD.value
                }
            )

            logger.info(f"[CANARY] Canary execution completed successfully for job {report.job_id}. Reserve count: {post_ready}/6. Terminating canary.")
            return telemetry

        except Exception as e:
            logger.error(f"[CANARY] Unexpected error during canary execution: {e}", exc_info=True)
            telemetry["status"] = "ERROR"
            telemetry["error"] = str(e)
            self._canary_consumed = True
            self._current_task = "CANARY_ERROR"
            self._write_heartbeat()
            mission_control_service.log_event(
                category="CANARY",
                message=f"Canary execution encountered error: {e}",
                severity="ERROR",
                metadata={"error": str(e)}
            )
            return telemetry
        finally:
            db.close()
            self.lock.release()
            logger.info("[CANARY] Worker lock released cleanly.")


# Global singleton instance
autonomous_runtime_service = AutonomousRuntimeService()
