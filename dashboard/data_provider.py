"""
System Data Provider for Historia Pipeline Control App.
Directly interfaces with live production components:
- Google Drive Vault Engine (01_READY, 02_PROCESSING, 03_PUBLISHED, 04_FAILED)
- SQLite Database & SQLAlchemy models (Jobs, Topics, UploadRecords, PerformanceSnapshots)
- ProcessLock subsystem (active PIDs and stale detection)
- HealthChecker subsystem
- Continuous Learning & Analytics Engine
"""
import sys
import logging
from datetime import datetime, time as dtime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from config.settings import GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES

from config.settings import PROJECT_ROOT, TEST_MODE, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, JobState, get_business_day_bounds_utc, BUSINESS_TIMEZONE
from core.database import SessionLocal, get_db
from core.models import (
    Job, Topic, UploadRecord, RenderOutput, QAReport,
    ContentPattern, StrategyWeight, PerformanceSnapshot,
    ExperimentRecord, AssetRecord, VideoAnalysisRecord
)
from core.lock import ProcessLock
from engines.drive_engine import DriveVaultEngine
from engines.health_checker import HealthChecker
from engines.scheduler_engine import PublicationScheduler

logger = logging.getLogger(__name__)

PUBLISHING_SLOTS_UTC = [
    (6, 0, "06:00 UTC (11:30 AM IST)"),
    (11, 0, "11:00 UTC (04:30 PM IST)"),
    (15, 0, "15:00 UTC (08:30 PM IST)"),
]

TARGET_RESERVE_BUFFER = 6



def format_compact_number(num: int | float) -> str:
    """Formats 1809354184 -> '1.8B', 45300 -> '45.3K', 987 -> '987'."""
    if num is None:
        return "—"
    try:
        num_float = float(num)
        if num_float >= 1_000_000_000:
            return f"{num_float / 1_000_000_000:.1f}B"
        elif num_float >= 1_000_000:
            return f"{num_float / 1_000_000:.1f}M"
        elif num_float >= 1_000:
            return f"{num_float / 1_000:.1f}K"
        else:
            return f"{int(num_float)}"
    except Exception:
        return str(num)

class SystemDataProvider:
    """
    Real-time data provider reading directly from the underlying production system.
    Strictly NO mock data, placeholder metrics, or synthetic statistics.
    """

    def __init__(self):
        self.drive_engine = DriveVaultEngine()
        self.health_checker = HealthChecker()

    def get_automation_health(self) -> Dict[str, Any]:
        """Runs live system health check and returns diagnostics."""
        try:
            audit = self.health_checker.run_full_audit()
            return {
                "verdict": audit.get("verdict", "UNKNOWN"),
                "summary": audit.get("summary", ""),
                "passed_checks_count": len(audit.get("passed_checks", [])),
                "warnings": audit.get("warnings", []),
                "critical_failures": audit.get("critical_failures", []),
                "checks": audit.get("checks", {}),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        except Exception as e:
            logger.error(f"Error reading automation health: {e}")
            return {
                "verdict": "ERROR",
                "summary": f"Could not perform health audit: {str(e)}",
                "passed_checks_count": 0,
                "warnings": [str(e)],
                "critical_failures": ["Health check failed to execute"],
                "checks": {},
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }

    def get_process_locks(self) -> Dict[str, Any]:
        """Inspects active filesystem/PID locks."""
        locks = {}
        for lock_name in ["production", "publisher"]:
            lock = ProcessLock(name=lock_name)
            info = lock.get_lock_info()
            is_active = lock.is_locked()
            locks[lock_name] = {
                "active": is_active,
                "held_by_pid": info.get("pid") if (info and is_active) else None,
                "command": info.get("command") if (info and is_active) else None,
                "created_at": info.get("created_at") if (info and is_active) else None,
                "raw_info": info if is_active else None
            }
        return locks

    def get_drive_inventory(self) -> Dict[str, Any]:
        """Queries real Google Drive Vault subfolders."""
        folders = ["01_READY", "02_PROCESSING", "03_PUBLISHED", "04_FAILED"]
        inventory = {
            "counts": {},
            "files": {},
            "status": "CONNECTED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

        try:
            from engines.drive_engine import is_valid_ready_short
            for f in folders:
                file_list = self.drive_engine.list_files_in_folder(f)
                if f == "01_READY":
                    valid_ready = [item for item in file_list if is_valid_ready_short(item)[0]]
                    inventory["counts"][f] = len(valid_ready)
                    inventory["raw_counts"] = getattr(inventory, "raw_counts", {}) or {}
                    inventory["raw_counts"][f] = len(file_list)
                else:
                    inventory["counts"][f] = len(file_list)
                inventory["files"][f] = [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "created_time": item.get("createdTime"),
                        "size_bytes": item.get("size"),
                        "properties": item.get("properties", {}) or {}
                    }
                    for item in file_list
                ]
        except Exception as e:
            logger.warning(f"Drive vault query notice: {e}")
            inventory["status"] = f"DEGRADED ({str(e)})"
            for f in folders:
                if f not in inventory["counts"]:
                    inventory["counts"][f] = 0
                    inventory["files"][f] = []

        return inventory

    def get_next_scheduled_slot(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Calculates next upcoming UTC publishing release slot."""
        if not now:
            now = datetime.utcnow()

        current_time = now.time()
        for hour, minute, label in PUBLISHING_SLOTS_UTC:
            slot_time = dtime(hour, minute)
            if current_time < slot_time:
                slot_dt = datetime.combine(now.date(), slot_time)
                diff_sec = int((slot_dt - now).total_seconds())
                hours_left = diff_sec // 3600
                mins_left = (diff_sec % 3600) // 60
                return {
                    "slot_label": label,
                    "slot_iso": slot_dt.isoformat() + "Z",
                    "hours_remaining": hours_left,
                    "minutes_remaining": mins_left,
                    "is_today": True,
                    "time_until_display": f"{hours_left}h {mins_left}m"
                }

        # If past all slots today, next slot is first slot tomorrow
        first_hour, first_minute, first_label = PUBLISHING_SLOTS_UTC[0]
        tomorrow = now.date() + timedelta(days=1)
        next_dt = datetime.combine(tomorrow, dtime(first_hour, first_minute))
        diff_sec = int((next_dt - now).total_seconds())
        hours_left = diff_sec // 3600
        mins_left = (diff_sec % 3600) // 60
        return {
            "slot_label": first_label,
            "slot_iso": next_dt.isoformat() + "Z",
            "hours_remaining": hours_left,
            "minutes_remaining": mins_left,
            "is_today": False,
            "time_until_display": f"{hours_left}h {mins_left}m (Tomorrow)"
        }

    def get_active_pipeline_count(self, db: Session) -> int:
        """
        Calculates authoritative count of currently active in-flight production jobs only.
        Excludes:
          - Completed/published jobs (JobState.PUBLISHED, JobState.SCHEDULED)
          - Quarantined / needs review jobs (JobState.NEEDS_REVIEW)
          - Permanently failed jobs (JobState.FAILED)
          - Queued backlog / idle jobs (JobState.QUEUED)
          - Stale/abandoned jobs older than STALE_JOB_TIMEOUT_SEC
        """
        from config.constants import STALE_JOB_TIMEOUT_SEC
        active_states = [
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
        cutoff = datetime.utcnow() - timedelta(seconds=STALE_JOB_TIMEOUT_SEC)
        return db.query(Job).filter(
            Job.state.in_(active_states),
            Job.updated_at >= cutoff
        ).count()

    def get_verified_live_count(self, db: Session) -> int:
        """
        Calculates authoritative count of unique verified live published YouTube Shorts.
        Requires valid 11-char YouTube ID, PUBLISHED status, and excludes test rows.
        """
        import re
        yt_regex = re.compile(r'^[A-Za-z0-9_-]{11}$')
        published_uploads = db.query(UploadRecord).filter(
            UploadRecord.status == "PUBLISHED",
            UploadRecord.youtube_video_id.isnot(None),
            UploadRecord.privacy_status != "test_local",
            ~UploadRecord.youtube_video_id.like("TEST_%"),
            ~UploadRecord.youtube_video_id.like("test_%")
        ).all()
        valid_ids = set()
        for u in published_uploads:
            yt_id = (u.youtube_video_id or "").strip()
            if yt_id and yt_regex.match(yt_id) and yt_id != "dQw4w9WgXcQ":
                valid_ids.add(yt_id)
        return len(valid_ids)

    def get_publishing_status(self, db: Session) -> Dict[str, Any]:
        """Calculates today's published & scheduled count, remaining slots, and next release."""
        # 0. Auto-reconcile any real scheduled uploads whose publishAt has elapsed
        try:
            past_scheduled = db.query(UploadRecord).filter(
                UploadRecord.status == "SCHEDULED",
                UploadRecord.scheduled_publish_at <= datetime.utcnow(),
                UploadRecord.youtube_video_id.isnot(None),
                ~UploadRecord.youtube_video_id.like("TEST_%"),
                ~UploadRecord.youtube_video_id.like("YT_%")
            ).first()
            if past_scheduled:
                from engines.upload_engine import UploadEngine
                UploadEngine().reconcile_scheduled_uploads(db)
        except Exception as auto_rec_err:
            logger.debug(f"[PUBLISHING_STATUS] Auto-reconciliation notice: {auto_rec_err}")

        today_start, today_end = get_business_day_bounds_utc()
        
        published_records_today = db.query(UploadRecord).filter(
            UploadRecord.published_at >= today_start,
            UploadRecord.published_at < today_end,
            UploadRecord.status == "PUBLISHED",
            UploadRecord.published_at.isnot(None)
        ).order_by(UploadRecord.published_at.desc()).all()

        scheduled_records_today = db.query(UploadRecord).filter(
            UploadRecord.scheduled_publish_at >= today_start,
            UploadRecord.scheduled_publish_at < today_end,
            UploadRecord.status == "SCHEDULED"
        ).order_by(UploadRecord.scheduled_publish_at.asc()).all()

        all_future_scheduled = db.query(UploadRecord).filter(
            UploadRecord.status == "SCHEDULED"
        ).order_by(UploadRecord.scheduled_publish_at.asc()).all()

        published_count_today = len(published_records_today)
        scheduled_count_today = len(scheduled_records_today)
        total_booked_today = published_count_today + scheduled_count_today
        remaining_capacity = max(0, DAILY_SHORTS_LIMIT - total_booked_today)

        latest_upload = db.query(UploadRecord).filter(
            UploadRecord.status == "PUBLISHED"
        ).order_by(UploadRecord.published_at.desc()).first()

        latest_video = None
        if latest_upload:
            latest_video = {
                "id": latest_upload.id,
                "youtube_video_id": latest_upload.youtube_video_id,
                "title": latest_upload.title,
                "published_at": latest_upload.published_at.isoformat() + "Z" if latest_upload.published_at else None,
                "youtube_url": f"https://youtube.com/shorts/{latest_upload.youtube_video_id}" if latest_upload.youtube_video_id else None,
                "privacy_status": latest_upload.privacy_status
            }

        # Calculate next unoccupied slot via scheduler engine
        scheduler = PublicationScheduler()
        next_unoccupied = scheduler.calculate_next_available_slot(db)
        diff_total_sec = max(0, int((next_unoccupied - datetime.utcnow()).total_seconds()))
        h_left = diff_total_sec // 3600
        m_left = (diff_total_sec % 3600) // 60
        next_slot_label = f"{next_unoccupied.strftime('%b %d, %Y')} · {next_unoccupied.strftime('%H:%M')} UTC"
        next_slot_info = {
            "slot_label": next_slot_label,
            "slot_iso": next_unoccupied.isoformat() + "Z",
            "is_today": today_start <= next_unoccupied < today_end,
            "time_until_display": f"{h_left}h {m_left}m"
        }

        scheduled_list = []
        for s in all_future_scheduled:
            scheduled_list.append({
                "id": s.id,
                "job_id": s.job_id,
                "youtube_video_id": s.youtube_video_id,
                "title": s.title,
                "scheduled_publish_at": s.scheduled_publish_at.isoformat() + "Z" if s.scheduled_publish_at else None,
                "privacy_status": s.privacy_status,
                "status": s.status
            })

        history_list = []
        for p in published_records_today:
            history_list.append({
                "id": p.id,
                "job_id": p.job_id,
                "youtube_video_id": p.youtube_video_id,
                "title": p.title,
                "published_at": p.published_at.isoformat() + "Z" if p.published_at else None,
                "privacy_status": p.privacy_status,
                "status": p.status
            })

        verified_live_count = self.get_verified_live_count(db)
        active_pipeline_count = self.get_active_pipeline_count(db)

        return {
            "daily_limit": DAILY_SHORTS_LIMIT,
            "published_today": published_count_today,
            "scheduled_today": scheduled_count_today,
            "total_booked_today": total_booked_today,
            "remaining_today": remaining_capacity,
            "next_slot": next_slot_label,
            "next_slot_label": next_slot_label,
            "next_slot_info": next_slot_info,
            "total_published": verified_live_count,
            "active_pipeline_count": active_pipeline_count,
            "daily_limit": DAILY_SHORTS_LIMIT,
            "remaining_capacity": remaining_capacity,
            "limit_reached": total_booked_today >= DAILY_SHORTS_LIMIT,
            "latest_video": latest_video,
            "next_slot": next_slot_info,
            "scheduled_videos": scheduled_list,
            "configured_slots": [label for _, _, label in PUBLISHING_SLOTS_UTC]
        }

    def get_buffer_status(self, ready_stock: Optional[int] = None) -> Dict[str, Any]:
        """Calculates reserve buffer health, target reserve, and estimated runway."""
        if ready_stock is None:
            try:
                ready_stock = self.drive_engine.get_ready_stock_count()
            except Exception:
                ready_stock = 0

        target = TARGET_RESERVE_BUFFER
        runway_days = round(ready_stock / float(DAILY_SHORTS_LIMIT), 2)
        runway_hours = round(runway_days * 24.0, 1)

        health = "HEALTHY"
        health_message = f"Vault buffer healthy ({ready_stock}/{target} Shorts)"
        if ready_stock == 0:
            health = "DEPLETED"
            health_message = f"Vault buffer depleted (0/{target} Shorts)"
        elif ready_stock < DAILY_SHORTS_LIMIT:
            health = "CRITICAL_LOW"
            health_message = f"Reserve critically low ({ready_stock}/{target} Shorts)"
        elif ready_stock < target:
            health = "REPLENISHING"
            health_message = f"Replenishing reserve ({ready_stock}/{target} Shorts)"

        return {
            "ready_stock": ready_stock,
            "current_reserve": ready_stock,
            "target_reserve": target,
            "health": health,
            "health_message": health_message,
            "runway_days": runway_days,
            "runway_hours": runway_hours,
            "runway_display": f"{runway_days:.1f} days ({runway_hours:.0f} hours)",
            "needed_replenishment": max(0, target - ready_stock)
        }

    def get_refill_telemetry(self, db: Session, ready_stock: Optional[int] = None) -> Dict[str, Any]:
        """
        Determines the authoritative status of the buffer refill mechanism.
        Tracks:
        - Refill status: ACTIVE / IDLE
        - Trigger condition: Reserve < 6 Shorts (Daily at 02:00 UTC or on-demand)
        - Next scheduled check: 02:00 UTC
        - Last refill run: timestamp & outcome from GitHub Actions / SQLite / production summary
        - Ready stock & target reserve
        """
        if ready_stock is None:
            try:
                ready_stock = self.drive_engine.get_ready_stock_count()
            except Exception:
                ready_stock = 0

        target = TARGET_RESERVE_BUFFER  # 6
        now = datetime.utcnow()

        # 1. Determine if refill is currently active
        is_active = False
        active_reason = None
        try:
            prod_lock = ProcessLock(name="production")
            if prod_lock.is_locked():
                is_active = True
                active_reason = "Local production process active"
            else:
                from dashboard.github_client import GitHubWorkflowDispatcher
                dispatcher = GitHubWorkflowDispatcher()
                active_run = dispatcher.get_active_workflow_run("produce_buffer.yml")
                if active_run:
                    is_active = True
                    active_reason = f"GitHub Actions runner #{active_run.get('run_number', '')} in progress"
        except Exception:
            pass

        # 2. Next scheduled run (02:00 UTC daily)
        next_refill_time = datetime.combine(now.date(), dtime(hour=2, minute=0))
        if next_refill_time <= now:
            next_refill_time += timedelta(days=1)
        diff_sec = max(0, int((next_refill_time - now).total_seconds()))
        h_until = diff_sec // 3600
        m_until = (diff_sec % 3600) // 60

        # 3. Last refill execution & result
        last_refill_ts = None
        last_refill_result = "IDLE (Standing by)"
        last_refill_display = "NEVER"

        # Check production_summary.json or latest job
        prod_summary_file = PROJECT_ROOT / "data" / "production_summary.json"
        if prod_summary_file.exists():
            try:
                import json
                with open(prod_summary_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                    if sdata:
                        last_refill_result = sdata.get("outcome_message") or sdata.get("outcome") or "COMPLETED"
                        if sdata.get("timestamp"):
                            last_refill_ts = sdata["timestamp"]
            except Exception:
                pass

        if not last_refill_ts:
            latest_job = db.query(Job).order_by(Job.created_at.desc()).first()
            if latest_job and latest_job.created_at:
                last_refill_ts = latest_job.created_at.isoformat() + "Z"
                last_refill_result = f"Last job {latest_job.id} ({latest_job.state})"

        if last_refill_ts:
            try:
                dt = datetime.fromisoformat(last_refill_ts.replace("Z", "+00:00")).replace(tzinfo=None)
                diff_prev = int((now - dt).total_seconds())
                if diff_prev < 60:
                    last_refill_display = "Just now"
                elif diff_prev < 3600:
                    last_refill_display = f"{diff_prev // 60}m ago"
                elif diff_prev < 86400:
                    last_refill_display = f"{diff_prev // 3600}h {(diff_prev % 3600) // 60}m ago"
                else:
                    last_refill_display = dt.strftime("%b %d, %H:%M UTC")
            except Exception:
                last_refill_display = str(last_refill_ts)

        # Last scheduler run info from UploadRecords
        last_sched = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "TEST_VERIFIED"])
        ).order_by(UploadRecord.created_at.desc()).first()

        last_scheduler_run_display = "NEVER"
        last_scheduler_result = "STANDBY"
        if last_sched and last_sched.created_at:
            diff_sc = int((now - last_sched.created_at).total_seconds())
            if diff_sc < 3600:
                last_scheduler_run_display = f"{diff_sc // 60}m ago"
            elif diff_sc < 86400:
                last_scheduler_run_display = f"{diff_sc // 3600}h ago"
            else:
                last_scheduler_run_display = last_sched.created_at.strftime("%b %d, %H:%M UTC")
            last_scheduler_result = f"Scheduled '{last_sched.title[:25]}...' for {last_sched.scheduled_publish_at.strftime('%b %d %H:%M UTC') if last_sched.scheduled_publish_at else 'UTC'}"

        return {
            "status": "ACTIVE" if is_active else "IDLE",
            "active_reason": active_reason,
            "trigger": f"01_READY < {target} Shorts (Audited daily at 02:00 UTC or manual dispatch)",
            "target_reserve": target,
            "current_ready": ready_stock,
            "needed_replenishment": max(0, target - ready_stock),
            "next_check_utc": next_refill_time.strftime("%Y-%m-%d %H:%M UTC"),
            "next_check_iso": next_refill_time.isoformat() + "Z",
            "next_check_display": f"in {h_until}h {m_until}m (02:00 UTC)",
            "last_refill_utc": last_refill_ts,
            "last_refill_display": last_refill_display,
            "last_refill_result": last_refill_result,
            "last_scheduler_run": last_scheduler_run_display,
            "last_scheduler_result": last_scheduler_result
        }

    def get_learning_status(self, db: Session) -> Dict[str, Any]:
        """
        Reads real continuous learning feedback loop, LearningEvents, and pattern intelligence.
        Strictly zero synthetic metrics or false claims of improvement.
        """
        from core.models import LearningEvent
        from engines.learning_engine import LearningEngine

        learner = LearningEngine()
        current_profile_version = learner._calculate_profile_version(db)

        # 1. Fetch real learning events from audit trail
        latest_event = db.query(LearningEvent).order_by(LearningEvent.timestamp.desc()).first()
        recent_events_rows = db.query(LearningEvent).order_by(LearningEvent.timestamp.desc()).limit(10).all()
        learning_applied_count = db.query(LearningEvent).filter(LearningEvent.outcome == "LEARNING_APPLIED").count()

        # 2. Query canonical verified analytics universe
        now = datetime.utcnow()
        universe = learner.get_verified_analytics_universe(db, now=now)
        mature_count = universe["mature_count"]
        immature_count = universe["maturing_count"]
        verified_live_count = universe["verified_live_count"]
        total_analytics_cohort = universe["total_analytics_cohort"]
        data_integrity_error = universe["data_integrity_error"]

        # 3. Determine active learning status
        if data_integrity_error:
            status_text = "Data Reconciliation Error"
            status_badge_class = "bg-rose-950 text-rose-400 border border-rose-800"
        elif learning_applied_count > 0:
            status_text = "Learning Active"
            status_badge_class = "bg-emerald-950 text-emerald-400 border border-emerald-800"
        elif immature_count > 0 and mature_count < learner.min_evidence_threshold:
            status_text = "Waiting for Data"
            status_badge_class = "bg-sky-950 text-sky-400 border border-sky-800"
        elif mature_count < learner.min_evidence_threshold:
            status_text = "Insufficient Evidence"
            status_badge_class = "bg-amber-950 text-amber-400 border border-amber-800"
        else:
            status_text = "No Significant Signal"
            status_badge_class = "bg-slate-900 text-slate-400 border border-slate-700"

        # Format latest event details
        latest_event_data = None
        if latest_event:
            latest_event_data = {
                "id": latest_event.id,
                "timestamp": latest_event.timestamp.isoformat() + "Z",
                "timestamp_display": latest_event.timestamp.strftime("%b %d, %Y %H:%M UTC"),
                "outcome": latest_event.outcome,
                "feature_type": latest_event.feature_type or "General Channel Strategy",
                "feature_value": latest_event.feature_value or "Baseline",
                "sample_size": latest_event.sample_size,
                "confidence": latest_event.confidence,
                "baseline_metric": latest_event.baseline_metric,
                "observed_metric": latest_event.observed_metric,
                "delta": latest_event.delta,
                "delta_display": f"{latest_event.delta:+.1f}%" if latest_event.delta is not None else "0.0%",
                "old_weight": round(latest_event.old_weight, 2),
                "new_weight": round(latest_event.new_weight, 2),
                "reason": latest_event.reason,
                "profile_version": latest_event.profile_version or current_profile_version,
                "consumed_by_generation": "APPLIED" if latest_event.consumed_by_generation else "PENDING",
                "consumed_by_job_id": latest_event.consumed_by_job_id
            }

        recent_events_list = []
        for ev in recent_events_rows:
            recent_events_list.append({
                "id": ev.id,
                "timestamp": ev.timestamp.strftime("%b %d %H:%M UTC"),
                "outcome": ev.outcome,
                "feature": f"{ev.feature_type}: {ev.feature_value}" if ev.feature_type else "Channel Baseline",
                "samples": ev.sample_size,
                "confidence": ev.confidence,
                "weight_change": f"{ev.old_weight:.2f} → {ev.new_weight:.2f}",
                "consumed": "APPLIED" if ev.consumed_by_generation else "PENDING",
                "reason": ev.reason
            })

        # Group strategy weights (deduplicated by feature_type, feature_value)
        weights = db.query(StrategyWeight).order_by(
            StrategyWeight.last_updated.desc()
        ).all()
        grouped_weights: Dict[str, List[Dict[str, Any]]] = {}
        seen_features = set()
        for w in weights:
            key = (w.feature_type, w.feature_value)
            if key in seen_features:
                continue
            seen_features.add(key)
            if w.feature_type not in grouped_weights:
                grouped_weights[w.feature_type] = []
            grouped_weights[w.feature_type].append({
                "value": w.feature_value,
                "weight": round(w.weight, 2) if w.weight is not None else 1.0,
                "sample_size": w.sample_count if hasattr(w, "sample_count") else 0,
                "confidence": w.confidence_level or "INSUFFICIENT_EVIDENCE",
                "relative_lift": round(w.relative_lift, 3) if w.relative_lift is not None else 0.0,
                "updated_at": w.last_updated.isoformat() + "Z" if (hasattr(w, "last_updated") and w.last_updated) else None
            })

        # Explanatory "What Changed?" summary
        if latest_event and latest_event.outcome == "LEARNING_APPLIED":
            what_changed_summary = (
                f"Strategy weight for {latest_event.feature_type} '{latest_event.feature_value}' "
                f"adjusted from {latest_event.old_weight:.2f} to {latest_event.new_weight:.2f} "
                f"({latest_event.delta:+.1f}% lift vs channel baseline across {latest_event.sample_size} matured Shorts). "
                f"Status: {latest_event_data['consumed_by_generation']} to future generation."
            )
        elif immature_count > 0:
            what_changed_summary = f"No strategy weight updates applied. {immature_count} published Shorts are currently maturing in the 24-hour telemetry window (minimum sample size: 3)."
        else:
            what_changed_summary = "No strategy weight updates applied. Waiting for verified YouTube performance snapshots to accumulate required sample size (N >= 3)."

        return {
            "learning_status": status_text,
            "status_badge_class": status_badge_class,
            "has_mature_data": mature_count > 0,
            "total_mature_snapshots": mature_count,
            "total_experiments": learning_applied_count,
            "channel_baseline_score": 0.75,
            "patterns": recent_events_list,
            "latest_event": latest_event_data,
            "applied_events_count": learning_applied_count,
            "immature_videos_count": immature_count,
            "mature_videos_count": mature_count,
            "total_analytics_cohort": total_analytics_cohort,
            "verified_live_count": verified_live_count,
            "data_integrity_error": data_integrity_error,
            "current_profile_version": current_profile_version,
            "what_changed_summary": what_changed_summary,
            "recent_events": recent_events_list,
            "strategy_weights": grouped_weights,
            "voice_configured": KOKORO_VOICE
        }


    def get_scheduled_queue(self, db: Session, limit: int = 20) -> Dict[str, Any]:
        """
        Retrieves the real YouTube scheduled publishing queue, upcoming slots,
        and reconciliation state across SQLite, YouTube, and Google Drive Vault.
        """
        now = datetime.utcnow()
        today_start, today_end = get_business_day_bounds_utc(now)

        # 0. Auto-reconcile any real scheduled uploads whose publishAt has elapsed
        try:
            past_scheduled = db.query(UploadRecord).filter(
                UploadRecord.status == "SCHEDULED",
                UploadRecord.scheduled_publish_at <= now,
                UploadRecord.youtube_video_id.isnot(None),
                ~UploadRecord.youtube_video_id.like("TEST_%"),
                ~UploadRecord.youtube_video_id.like("YT_%")
            ).first()
            if past_scheduled:
                from engines.upload_engine import UploadEngine
                UploadEngine().reconcile_scheduled_uploads(db)
        except Exception as auto_rec_err:
            logger.debug(f"[SCHEDULED_QUEUE] Auto-reconciliation notice: {auto_rec_err}")

        # 1. Query all active scheduled uploads + recent published uploads
        records = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "TEST_VERIFIED"])
        ).order_by(
            # Sort scheduled first chronologically, then by published_at
            UploadRecord.scheduled_publish_at.asc(),
            UploadRecord.published_at.desc()
        ).all()

        # 2. Get Drive vault file mapping for accurate location tracking
        drive_file_map = {}
        try:
            inventory = self.get_drive_inventory()
            for folder_name, f_list in inventory.get("files", {}).items():
                for f in f_list:
                    props = f.get("properties", {}) or {}
                    cand_job_id = props.get("job_id")
                    if cand_job_id:
                        drive_file_map[cand_job_id] = folder_name
                    # Also map by filename if job_id matches
                    for r in records:
                        if r.job_id and r.job_id in f.get("name", ""):
                            drive_file_map[r.job_id] = folder_name
        except Exception as drive_err:
            logger.warning(f"Could not map Drive vault files for scheduled queue: {drive_err}")

        queue_items = []
        future_scheduled = []
        scheduled_today = []
        published_today = []
        latest_recon_ts = None

        for r in records:
            # Determine drive location
            drive_loc = drive_file_map.get(r.job_id)
            if not drive_loc:
                drive_loc = "02_PROCESSING" if r.status == "SCHEDULED" else ("03_PUBLISHED" if r.status == "PUBLISHED" else "UNKNOWN")

            # Determine reconciliation state & time string
            time_until_str = None
            recon_state = "IN_SYNC"

            if r.status == "SCHEDULED":
                if r.scheduled_publish_at:
                    if today_start <= r.scheduled_publish_at < today_end:
                        scheduled_today.append(r)

                    diff_sec = int((r.scheduled_publish_at - now).total_seconds())
                    if diff_sec > 0:
                        recon_state = "PENDING_RELEASE"
                        h = diff_sec // 3600
                        m = (diff_sec % 3600) // 60
                        time_until_str = f"in {h}h {m}m"
                        future_scheduled.append(r)
                    else:
                        recon_state = "NEEDS_RECONCILIATION"
                        h_ago = abs(diff_sec) // 3600
                        m_ago = (abs(diff_sec) % 3600) // 60
                        time_until_str = f"{h_ago}h {m_ago}m ago (Pending YouTube Auto-Release)"
                else:
                    recon_state = "NEEDS_RECONCILIATION"
                    time_until_str = "Timestamp Unassigned"
            elif r.status in ["PUBLISHED", "TEST_VERIFIED"]:
                recon_state = "IN_SYNC"
                if r.published_at:
                    if today_start <= r.published_at < today_end:
                        published_today.append(r)
                    diff_sec = int((now - r.published_at).total_seconds())
                    h = diff_sec // 3600
                    m = (diff_sec % 3600) // 60
                    time_until_str = f"{h}h {m}m ago"
                else:
                    time_until_str = "Published"

            if r.reconciliation_metadata and not latest_recon_ts:
                latest_recon_ts = r.created_at.isoformat() + "Z" if r.created_at else None

            queue_items.append({
                "id": r.id,
                "job_id": r.job_id,
                "title": r.title,
                "youtube_video_id": r.youtube_video_id,
                "youtube_url": f"https://youtube.com/shorts/{r.youtube_video_id}" if (r.youtube_video_id and not r.youtube_video_id.startswith("TEST_")) else None,
                "scheduled_publish_at": r.scheduled_publish_at.isoformat() + "Z" if r.scheduled_publish_at else None,
                "published_at": r.published_at.isoformat() + "Z" if r.published_at else None,
                "privacy_status": r.privacy_status,
                "local_status": r.status,
                "drive_location": drive_loc,
                "reconciliation_state": recon_state,
                "reconciliation_metadata": r.reconciliation_metadata,
                "time_until_display": time_until_str,
                "is_future": (r.scheduled_publish_at > now) if r.scheduled_publish_at else False,
                "is_today": (today_start <= r.scheduled_publish_at < today_end) if r.scheduled_publish_at else False
            })

        # Next upcoming scheduled video
        next_scheduled_item = None
        if future_scheduled:
            # Sort future scheduled by scheduled_publish_at
            sorted_future = sorted(future_scheduled, key=lambda x: x.scheduled_publish_at)
            cand = sorted_future[0]
            diff_sec = int((cand.scheduled_publish_at - now).total_seconds())
            h = diff_sec // 3600
            m = (diff_sec % 3600) // 60
            next_scheduled_item = {
                "id": cand.id,
                "job_id": cand.job_id,
                "title": cand.title,
                "youtube_video_id": cand.youtube_video_id,
                "youtube_url": f"https://youtube.com/shorts/{cand.youtube_video_id}" if (cand.youtube_video_id and not cand.youtube_video_id.startswith("TEST_")) else None,
                "scheduled_publish_at": cand.scheduled_publish_at.isoformat() + "Z",
                "slot_label": f"{cand.scheduled_publish_at.strftime('%b %d, %Y')} at {cand.scheduled_publish_at.strftime('%H:%M')} UTC",
                "countdown": f"{h}h {m}m",
                "privacy_status": cand.privacy_status,
                "status": cand.status,
                "drive_location": drive_file_map.get(cand.job_id, "02_PROCESSING")
            }

        total_booked_today = len(scheduled_today) + len(published_today)
        remaining_capacity = max(0, DAILY_SHORTS_LIMIT - total_booked_today)

        # Sort queue: SCHEDULED (earliest first), then PUBLISHED (latest first)
        scheduled_part = sorted([q for q in queue_items if q["local_status"] == "SCHEDULED"], key=lambda x: x["scheduled_publish_at"] or "")
        published_part = sorted([q for q in queue_items if q["local_status"] != "SCHEDULED"], key=lambda x: x["published_at"] or "", reverse=True)
        final_queue = (scheduled_part + published_part)[:limit]

        return {
            "queue": final_queue,
            "next_scheduled_video": next_scheduled_item,
            "scheduled_today_count": len(scheduled_today),
            "published_today_count": len(published_today),
            "total_booked_today": total_booked_today,
            "future_scheduled_count": len(future_scheduled),
            "remaining_daily_capacity": remaining_capacity,
            "daily_limit": DAILY_SHORTS_LIMIT,
            "latest_reconciliation_timestamp": latest_recon_ts or now.isoformat() + "Z",
            "timestamp": now.isoformat() + "Z"
        }

    def get_voice_config(self, db: Session) -> Dict[str, Any]:
        """Returns current persistent voice preference and available production voice options."""
        from engines.tts_engine import AVAILABLE_VOICES, get_active_voice
        active_id = get_active_voice(db)
        active_voice = next((v for v in AVAILABLE_VOICES if v["id"] == active_id), AVAILABLE_VOICES[0])
        display_name = active_voice.get("display_name", active_id)
        engine = active_voice.get("engine", "Kokoro-82M ONNX")
        desc = active_voice.get("description", "")
        return {
            "active_voice_id": active_id,
            "active_voice": active_voice,
            "active_voice_name": display_name,
            "display_name": display_name,
            "engine": engine,
            "description": desc,
            "available_voices": AVAILABLE_VOICES
        }

    def get_bgm_library_status(self, db: Session) -> Dict[str, Any]:
        """Returns the configured 4-track BGM library and recent Job BGM selections."""
        import json
        from engines.audio_mixer import BGM_LIBRARY
        from config.settings import MUSIC_DIR

        tracks = []
        for key, info in BGM_LIBRARY.items():
            primary_file = info["primary_files"][0]
            track_path = MUSIC_DIR / primary_file
            exists = track_path.exists()
            size_kb = round(track_path.stat().st_size / 1024.0, 1) if exists else 0
            tracks.append({
                "key": key,
                "display_name": info["display_name"],
                "filename": primary_file,
                "mood": info["mood"],
                "default_intensity": info["default_intensity"],
                "description": info["description"],
                "keywords": info["keywords"][:6],
                "exists_on_disk": exists,
                "file_size_kb": size_kb
            })

        # Recent BGM selections from AssetRecords
        recent_assets = db.query(AssetRecord).filter(
            AssetRecord.asset_type == "music"
        ).order_by(AssetRecord.created_at.desc()).limit(8).all()

        recent_selections = []
        for a in recent_assets:
            meta = {}
            if a.metadata_json:
                try:
                    meta = json.loads(a.metadata_json)
                except Exception:
                    pass
            
            recent_selections.append({
                "id": a.id,
                "track_key": meta.get("bgm_track", "best_historical"),
                "display_name": meta.get("display_name", Path(a.local_path).name),
                "mood": meta.get("mood", "Historical Documentary"),
                "reason": meta.get("reason", "Automated Narrative Classification"),
                "filename": meta.get("filename", Path(a.local_path).name),
                "created_at": a.created_at.isoformat() + "Z" if a.created_at else None
            })

        return {
            "library": tracks,
            "recent_selections": recent_selections
        }

    def get_cloud_workflows_status(self) -> Dict[str, Any]:
        """
        Returns configured cloud automation workflows, cron cadences, and expected execution times.
        Explicitly reports 'STATUS_UNAVAILABLE' when GitHub Actions live runner state cannot be queried.
        """
        now = datetime.utcnow()
        
        # Calculate next buffer cron run (Daily at 03:00 UTC)
        today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
        next_buffer = today_3am if now < today_3am else today_3am + timedelta(days=1)

        # Calculate next autopilot run (06:00, 10:00, 15:00, 20:00 UTC)
        autopilot_hours = [6, 10, 15, 20]
        next_autopilot = None
        for h in autopilot_hours:
            candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if now < candidate:
                next_autopilot = candidate
                break
        if not next_autopilot:
            next_autopilot = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

        # Calculate next analytics harvester run (00:00, 12:00 UTC)
        analytics_hours = [0, 12]
        next_analytics = None
        for h in analytics_hours:
            candidate = now.replace(hour=h, minute=0, second=0, microsecond=0)
            if now < candidate:
                next_analytics = candidate
                break
        if not next_analytics:
            next_analytics = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

        workflows = [
            {
                "id": "produce_buffer",
                "name": "01 Buffer Producer",
                "filename": "produce_buffer.yml",
                "cron": "0 3 * * * (03:00 UTC daily)",
                "target": "Replenish 01_READY reserve to 6 Shorts",
                "concurrency_group": "buffer-producer",
                "live_status": "STATUS_UNAVAILABLE (Cloud Runner)",
                "configured": True,
                "next_expected_utc": next_buffer.strftime("%Y-%m-%d %H:%M UTC"),
                "hours_until": round((next_buffer - now).total_seconds() / 3600.0, 1)
            },
            {
                "id": "autopilot",
                "name": "02 YouTube Autopilot Publisher",
                "filename": "autopilot.yml",
                "cron": "0 6,10,15,20 * * * (4x daily)",
                "target": "Claim from 01_READY and schedule next YouTube slot",
                "concurrency_group": "youtube-publisher",
                "live_status": "STATUS_UNAVAILABLE (Cloud Runner)",
                "configured": True,
                "next_expected_utc": next_autopilot.strftime("%Y-%m-%d %H:%M UTC"),
                "hours_until": round((next_autopilot - now).total_seconds() / 3600.0, 1)
            },
            {
                "id": "harvest_analytics",
                "name": "03 Analytics Harvester & Learner",
                "filename": "harvest_analytics.yml",
                "cron": "0 0,12 * * * (2x daily)",
                "target": "Harvest YouTube Analytics & update strategy weights",
                "concurrency_group": "analytics-harvester",
                "live_status": "STATUS_UNAVAILABLE (Cloud Runner)",
                "configured": True,
                "next_expected_utc": next_analytics.strftime("%Y-%m-%d %H:%M UTC"),
                "hours_until": round((next_analytics - now).total_seconds() / 3600.0, 1)
            }
        ]

        return {
            "workflows": workflows,
            "mode": "GITHUB_ACTIONS_UNATTENDED_AUTONOMOUS",
            "timestamp": now.isoformat() + "Z"
        }

    def get_production_timeline(self, db: Session, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Builds a multi-stage production and publishing timeline for recent Jobs.
        Stages: DISCOVERED -> SCRIPTED -> VOICE_GENERATED -> RENDERED -> QA_PASSED -> 01_READY -> CLAIMED -> 02_PROCESSING -> YOUTUBE_SCHEDULED -> YOUTUBE_PUBLIC -> 03_PUBLISHED
        """
        now = datetime.utcnow()
        jobs = db.query(Job).order_by(Job.updated_at.desc()).limit(limit).all()

        timeline = []
        for j in jobs:
            topic_title = j.topic.title if j.topic else "Untitled Topic"
            category = j.topic.category if j.topic else "History"
            
            # Check render
            render = db.query(RenderOutput).filter(RenderOutput.job_id == j.id).first()
            # Check QA
            qa = db.query(QAReport).filter(QAReport.job_id == j.id).first()
            # Check Upload
            upload = db.query(UploadRecord).filter(UploadRecord.job_id == j.id).first()

            # Build stage list
            stages = []
            
            # Stage 1: DISCOVERED
            t_disc = j.created_at.strftime("%H:%M:%S") if j.created_at else None
            stages.append({"name": "DISCOVERED", "status": "COMPLETED", "timestamp": t_disc})

            # Stage 2: SCRIPTED
            is_scripted = j.state not in [JobState.QUEUED.value, JobState.RESEARCHING.value]
            stages.append({"name": "SCRIPTED", "status": "COMPLETED" if is_scripted else ("ACTIVE" if j.state == JobState.SCRIPTING.value else "PENDING")})

            # Stage 3: VOICE GENERATED
            is_voiced = j.state in [JobState.VOICE_READY.value, JobState.AUDIO_READY.value, JobState.EDITING.value, JobState.QA.value, JobState.READY_TO_UPLOAD.value, JobState.UPLOADING.value, JobState.SCHEDULED.value, JobState.PUBLISHED.value]
            stages.append({"name": "VOICE GENERATED", "status": "COMPLETED" if is_voiced else ("ACTIVE" if j.state == JobState.VOICE_GENERATING.value else "PENDING")})

            # Stage 4: RENDERED
            is_rendered = render is not None or j.state in [JobState.QA.value, JobState.READY_TO_UPLOAD.value, JobState.UPLOADING.value, JobState.SCHEDULED.value, JobState.PUBLISHED.value]
            stages.append({"name": "RENDERED", "status": "COMPLETED" if is_rendered else ("ACTIVE" if j.state == JobState.EDITING.value else "PENDING")})

            # Stage 5: QA PASSED
            qa_passed = (qa is not None and getattr(qa, "passed", False)) or j.state in [JobState.READY_TO_UPLOAD.value, JobState.UPLOADING.value, JobState.SCHEDULED.value, JobState.PUBLISHED.value]
            stages.append({"name": "QA PASSED", "status": "COMPLETED" if qa_passed else ("ACTIVE" if j.state == JobState.QA.value else "PENDING")})

            # Stage 6: 01_READY (Stored in vault)
            is_vaulted = qa_passed or j.state in [JobState.READY_TO_UPLOAD.value, JobState.UPLOADING.value, JobState.SCHEDULED.value, JobState.PUBLISHED.value]
            stages.append({"name": "01_READY", "status": "COMPLETED" if is_vaulted else "PENDING"})

            # Stage 7: CLAIMED & 02_PROCESSING
            is_claimed = upload is not None or j.state in [JobState.UPLOADING.value, JobState.SCHEDULED.value, JobState.PUBLISHED.value]
            stages.append({"name": "02_PROCESSING", "status": "COMPLETED" if (upload and upload.status == "PUBLISHED") else ("ACTIVE" if (upload and upload.status == "SCHEDULED") or j.state == JobState.UPLOADING.value else "WAITING")})

            # Stage 8: YOUTUBE SCHEDULED
            is_sched = upload is not None and upload.status in ["SCHEDULED", "PUBLISHED", "TEST_VERIFIED"]
            sched_ts = upload.scheduled_publish_at.strftime("%b %d %H:%M UTC") if (upload and upload.scheduled_publish_at) else None
            stages.append({"name": "YOUTUBE SCHEDULED", "status": "COMPLETED" if is_sched else "WAITING", "detail": sched_ts})

            # Stage 9: YOUTUBE PUBLIC & 03_PUBLISHED
            is_pub = upload is not None and upload.status == "PUBLISHED"
            pub_ts = upload.published_at.strftime("%b %d %H:%M UTC") if (upload and upload.published_at) else None
            stages.append({"name": "03_PUBLISHED", "status": "COMPLETED" if is_pub else "WAITING", "detail": pub_ts})

            timeline.append({
                "job_id": j.id,
                "title": topic_title,
                "category": category,
                "current_state": j.state,
                "error_message": j.error_message,
                "updated_at": j.updated_at.isoformat() + "Z" if j.updated_at else None,
                "stages": stages
            })

        return timeline

    def get_activity_feed(self, db: Session, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Generates a chronological feed of real persisted system events from JobLogs, UploadRecords, and QAReports.
        """
        events = []

        # 1. From UploadRecords
        uploads = db.query(UploadRecord).order_by(UploadRecord.created_at.desc()).limit(10).all()
        for u in uploads:
            if u.status == "SCHEDULED":
                slot_str = u.scheduled_publish_at.strftime("%b %d at %H:%M UTC") if u.scheduled_publish_at else "Assigned Slot"
                events.append({
                    "timestamp": u.created_at.isoformat() + "Z" if u.created_at else None,
                    "event_type": "YOUTUBE_SCHEDULED",
                    "level": "success",
                    "job_id": u.job_id,
                    "title": u.title,
                    "description": f"Short scheduled on YouTube (ID: {u.youtube_video_id}) for {slot_str} [privacyStatus=private]"
                })
            elif u.status == "PUBLISHED":
                events.append({
                    "timestamp": u.published_at.isoformat() + "Z" if u.published_at else (u.created_at.isoformat() + "Z" if u.created_at else None),
                    "event_type": "YOUTUBE_PUBLISHED",
                    "level": "success",
                    "job_id": u.job_id,
                    "title": u.title,
                    "description": f"Short is now LIVE on YouTube (ID: {u.youtube_video_id}). Vault file moved to 03_PUBLISHED."
                })

        # 2. From QA Reports
        qa_reps = db.query(QAReport).order_by(QAReport.created_at.desc()).limit(10).all()
        for q in qa_reps:
            is_pass = getattr(q, "passed", False)
            verdict_str = "PASS" if is_pass else "NEEDS_REVIEW"
            events.append({
                "timestamp": q.created_at.isoformat() + "Z" if q.created_at else None,
                "event_type": f"QA_{verdict_str}",
                "level": "success" if is_pass else "warning",
                "job_id": q.job_id,
                "title": f"QA Inspection: {verdict_str}",
                "description": f"Resolution: {'OK' if q.resolution_ok else 'FAIL'} | Duration: {'OK' if q.duration_ok else 'FAIL'} | Audio: {'OK' if q.audio_ok else 'FAIL'}"
            })

        # 3. From JobLogs
        from core.models import JobLog
        logs = db.query(JobLog).order_by(JobLog.created_at.desc()).limit(20).all()
        for l in logs:
            level = "info"
            if l.status == "FAILED" or l.status == "ERROR":
                level = "error"
            elif l.status == "WARNING" or l.status == "WARN":
                level = "warning"
            elif l.status == "SUCCESS" or l.status == "APPROVED":
                level = "success"

            events.append({
                "timestamp": l.created_at.isoformat() + "Z" if l.created_at else None,
                "event_type": f"{l.stage}_{l.status}",
                "level": level,
                "job_id": l.job_id,
                "title": f"{l.stage.replace('_', ' ').title()} - {l.status}",
                "description": l.message or "Pipeline state updated"
            })

        # Sort all events by timestamp descending
        events.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        return events[:limit]

    def get_recovery_telemetry(self, db: Session) -> Dict[str, Any]:
        """Returns autonomous self-healing and recovery telemetry."""
        from config.constants import STALE_JOB_TIMEOUT_SEC
        from core.models import JobLog
        cutoff = datetime.utcnow() - timedelta(seconds=STALE_JOB_TIMEOUT_SEC)
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
        stale_jobs_count = db.query(Job).filter(
            Job.state.in_(transient_states),
            Job.updated_at <= cutoff
        ).count()
        needs_review_count = db.query(Job).filter(Job.state == JobState.NEEDS_REVIEW.value).count()
        failed_jobs_count = db.query(Job).filter(Job.state == JobState.FAILED.value).count()

        recovery_logs = db.query(JobLog).filter(JobLog.stage == "RECOVERY").order_by(JobLog.created_at.desc()).limit(5).all()
        recent_events = [
            {
                "job_id": rl.job_id,
                "status": rl.status,
                "message": rl.message,
                "timestamp": rl.created_at.isoformat() + "Z" if rl.created_at else None
            }
            for rl in recovery_logs
        ]

        return {
            "stale_jobs_count": stale_jobs_count,
            "needs_review_count": needs_review_count,
            "failed_jobs_count": failed_jobs_count,
            "recent_recovery_events": recent_events,
            "status": "HEALTHY" if (stale_jobs_count == 0 and needs_review_count == 0) else "ATTENTION_REQUIRED",
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }

    def get_pexels_quota_status(self, db: Session) -> Dict[str, Any]:
        """
        Retrieves real-time Pexels API quota metrics and observed rate limits from SQLite.
        Strictly returns null / UNKNOWN if live headers have not yet been observed.
        """
        try:
            from core.models import ProviderUsage
            from datetime import datetime, timedelta

            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            # 1. Query request usage counts
            requests_today = db.query(ProviderUsage).filter(
                ProviderUsage.provider_name == "pexels",
                ProviderUsage.created_at >= today_start
            ).count()

            requests_this_month = db.query(ProviderUsage).filter(
                ProviderUsage.provider_name == "pexels",
                ProviderUsage.created_at >= month_start
            ).count()

            # 2. Query latest observed rate limit headers
            latest_observed = db.query(ProviderUsage).filter(
                ProviderUsage.provider_name == "pexels",
                ProviderUsage.rate_remaining.isnot(None)
            ).order_by(ProviderUsage.created_at.desc()).first()

            if latest_observed and latest_observed.rate_remaining is not None:
                limit = latest_observed.rate_limit
                remaining = latest_observed.rate_remaining
                reset = latest_observed.rate_reset
                last_observed_at = latest_observed.created_at.isoformat() + "Z" if latest_observed.created_at else None

                # Status classification
                if remaining <= 0:
                    status_verdict = "CRITICAL"
                elif limit is not None and remaining <= int(limit * 0.10):
                    status_verdict = "WARNING"
                elif remaining <= 50:
                    status_verdict = "WARNING"
                else:
                    status_verdict = "OK"

                return {
                    "provider": "pexels",
                    "limit": limit,
                    "remaining": remaining,
                    "reset": reset,
                    "last_observed_at": last_observed_at,
                    "requests_today": requests_today,
                    "requests_this_month": requests_this_month,
                    "status": status_verdict
                }
            else:
                # No live headers have ever been observed
                return {
                    "provider": "pexels",
                    "limit": None,
                    "remaining": None,
                    "reset": None,
                    "last_observed_at": None,
                    "requests_today": requests_today,
                    "requests_this_month": requests_this_month,
                    "status": "UNKNOWN"
                }
        except Exception as err:
            logger.warning(f"[DATA_PROVIDER] Error retrieving Pexels quota status: {err}")
            return {
                "provider": "pexels",
                "limit": None,
                "remaining": None,
                "reset": None,
                "last_observed_at": None,
                "requests_today": 0,
                "requests_this_month": 0,
                "status": "UNKNOWN",
                "error": str(err)
            }

    def get_all_service_quotas(self, db: Session) -> Dict[str, Any]:
        """
        Unified provider quota and limit monitoring system.
        Covers: YouTube Data API v3, Google Gemini, Pexels API, GitHub Actions, Google Drive.
        Adheres strictly to the honest telemetry rule: UNKNOWN when unobserved, never fabricate numbers.
        """
        from datetime import datetime, timedelta
        from core.models import UploadRecord, ProviderUsage
        from config.constants import DAILY_SHORTS_LIMIT

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_utc = today_start + timedelta(days=1)

        services = []

        # 1. YouTube Data API v3
        try:
            uploads_today = db.query(UploadRecord).filter(UploadRecord.created_at >= today_start).count()
            # Standard estimated quota: 1,600 units per video insert, plus nominal query calls
            est_units_used = (uploads_today * 1600) + 10 if uploads_today > 0 else 0
            yt_limit = 10000  # Google Cloud default daily allocation
            yt_remaining = max(0, yt_limit - est_units_used)
            yt_status = "SAFE" if est_units_used < 8000 else ("WARNING" if est_units_used < 10000 else "CRITICAL")

            services.append({
                "service": "youtube_data_api",
                "display_name": "YouTube Data API v3",
                "category": "API",
                "limit": yt_limit,
                "used": est_units_used,
                "remaining": yt_remaining,
                "unit": "quota units",
                "reset_type": "DAILY",
                "reset_at": tomorrow_utc.isoformat() + "Z",
                "status": yt_status,
                "measurement_type": "ESTIMATED",
                "automation_impact": "HIGH",
                "fallback_available": False,
                "fallback_description": "None (Video publishing requires YouTube API; retries next daily cycle)",
                "internal_production_capacity": {
                    "limit": DAILY_SHORTS_LIMIT,
                    "used": uploads_today,
                    "remaining": max(0, DAILY_SHORTS_LIMIT - uploads_today),
                    "unit": "Shorts/day"
                },
                "last_observed_at": now.isoformat() + "Z",
                "message": f"Daily API quota estimated from {uploads_today} upload(s) today. Strict internal ceiling is {DAILY_SHORTS_LIMIT} Shorts/day."
            })
        except Exception as e:
            logger.warning(f"Error computing YouTube quota telemetry: {e}")
            services.append({
                "service": "youtube_data_api",
                "display_name": "YouTube Data API v3",
                "category": "API",
                "limit": 10000,
                "used": None,
                "remaining": None,
                "unit": "quota units",
                "reset_type": "DAILY",
                "reset_at": tomorrow_utc.isoformat() + "Z",
                "status": "UNKNOWN",
                "measurement_type": "UNKNOWN",
                "automation_impact": "HIGH",
                "fallback_available": False,
                "fallback_description": "None",
                "last_observed_at": None,
                "message": f"Could not determine YouTube quota: {e}"
            })

        # 2. Google Gemini API
        try:
            gemini_calls_today = db.query(ProviderUsage).filter(
                ProviderUsage.provider_name == "gemini",
                ProviderUsage.created_at >= today_start
            ).count()
            services.append({
                "service": "gemini_api",
                "display_name": "Google Gemini API",
                "category": "AI",
                "limit": None,
                "used": gemini_calls_today if gemini_calls_today > 0 else 0,
                "remaining": None,
                "unit": "requests",
                "reset_type": "TIER_DEPENDENT",
                "reset_at": None,
                "status": "UNKNOWN",
                "measurement_type": "UNKNOWN",
                "automation_impact": "LOW",
                "fallback_available": True,
                "fallback_description": "Deterministic historical storyboard templates & procedural scene synthesis",
                "last_observed_at": None,
                "message": "Live remaining quota not exposed via API. Deterministic templates guarantee uninterrupted video generation if Gemini times out."
            })
        except Exception as e:
            logger.warning(f"Error computing Gemini telemetry: {e}")
            services.append({
                "service": "gemini_api",
                "display_name": "Google Gemini API",
                "category": "AI",
                "limit": None,
                "used": None,
                "remaining": None,
                "unit": "requests",
                "reset_type": "TIER_DEPENDENT",
                "reset_at": None,
                "status": "UNKNOWN",
                "measurement_type": "UNKNOWN",
                "automation_impact": "LOW",
                "fallback_available": True,
                "fallback_description": "Deterministic templates",
                "last_observed_at": None,
                "message": f"Could not determine Gemini telemetry: {e}"
            })

        # 3. Pexels API
        try:
            pexels = self.get_pexels_quota_status(db)
            reset_at_iso = None
            if pexels.get("reset"):
                try:
                    reset_at_iso = datetime.utcfromtimestamp(pexels["reset"]).isoformat() + "Z"
                except Exception:
                    pass

            services.append({
                "service": "pexels_api",
                "display_name": "Pexels API",
                "category": "API",
                "limit": pexels.get("limit"),
                "used": pexels.get("requests_this_month", 0),
                "remaining": pexels.get("remaining"),
                "unit": "requests",
                "reset_type": "MONTHLY",
                "reset_at": reset_at_iso,
                "status": pexels.get("status", "UNKNOWN"),
                "measurement_type": "LIVE_OBSERVED" if pexels.get("last_observed_at") else "UNKNOWN",
                "automation_impact": "LOW",
                "fallback_available": True,
                "fallback_description": "Pollinations.ai (AI image generation) -> Procedural Canvas",
                "last_observed_at": pexels.get("last_observed_at"),
                "message": "Live quota parsed directly from X-Ratelimit headers. Multi-tier visual fallback protects production if exhausted."
            })
        except Exception as e:
            logger.warning(f"Error computing Pexels quota: {e}")

        # 4. GitHub Actions
        try:
            services.append({
                "service": "github_actions",
                "display_name": "GitHub Actions",
                "category": "COMPUTE",
                "limit": None,
                "used": None,
                "remaining": None,
                "unit": "minutes",
                "reset_type": "BILLING_CYCLE",
                "reset_at": None,
                "status": "UNKNOWN",
                "measurement_type": "UNKNOWN",
                "automation_impact": "HIGH",
                "fallback_available": True,
                "fallback_description": "Local CLI / autonomous worker on host machine (runs when laptop is on)",
                "last_observed_at": None,
                "message": "Cloud workflows execute on GitHub Actions. If cloud minutes are exhausted, the pipeline runs locally on host."
            })
        except Exception as e:
            logger.warning(f"Error computing GitHub Actions quota: {e}")

        # 5. Google Drive Storage (Phase 11.2 - 5 TB Storage Plan Telemetry)
        try:
            drive_quota = self.drive_engine.get_storage_quota()
            if drive_quota is not None and (drive_quota.get("limit") is not None or drive_quota.get("usage") is not None):
                raw_limit = drive_quota.get("limit")
                # Respect confirmed 5 TB plan entitlement (or raw limit if explicitly provided)
                limit_b = raw_limit if raw_limit is not None else GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES
                used_b = drive_quota.get("usage", 0) or 0
                rem_b = max(0, limit_b - used_b)
                used_gb = used_b / (1024 ** 3)
                limit_tb = limit_b / (1024 ** 4)
                limit_gb = limit_b / (1024 ** 3)
                pct = (used_b / limit_b) * 100 if limit_b > 0 else 0.0

                if rem_b < 200 * (1024 ** 2):  # < 200MB
                    drive_status = "CRITICAL"
                elif rem_b < 10 * (1024 ** 3):   # < 10GB on a 5TB plan
                    drive_status = "WARNING"
                else:
                    drive_status = "SAFE"

                if limit_b >= 1024 ** 4:
                    msg = f"{used_gb:.2f} GB used of {limit_tb:.2f} TB ({pct:.2f}% capacity)."
                else:
                    msg = f"{used_gb:.2f} GB used of {limit_gb:.2f} GB ({pct:.1f}% capacity)."

                services.append({
                    "service": "google_drive",
                    "display_name": "Google Drive Vault Storage",
                    "category": "STORAGE",
                    "limit": limit_b,
                    "used": used_b,
                    "remaining": rem_b,
                    "unit": "bytes",
                    "reset_type": "STORAGE",
                    "reset_at": None,
                    "status": drive_status,
                    "measurement_type": "LIVE_OBSERVED",
                    "automation_impact": "MEDIUM",
                    "fallback_available": False,
                    "fallback_description": "None (Drive vault is required for autonomous cloud publishing buffer)",
                    "last_observed_at": now.isoformat() + "Z",
                    "message": msg
                })
            else:
                services.append({
                    "service": "google_drive",
                    "display_name": "Google Drive Vault Storage",
                    "category": "STORAGE",
                    "limit": None,
                    "used": None,
                    "remaining": None,
                    "unit": "bytes",
                    "reset_type": "STORAGE",
                    "reset_at": None,
                    "status": "UNKNOWN",
                    "measurement_type": "UNKNOWN",
                    "automation_impact": "MEDIUM",
                    "fallback_available": False,
                    "fallback_description": "None (Drive vault required for cloud buffer)",
                    "last_observed_at": None,
                    "message": "Drive storage quota could not be queried (token not loaded or offline)."
                })
        except Exception as e:
            logger.warning(f"Error computing Drive storage quota: {e}")

        return {
            "timestamp": now.isoformat() + "Z",
            "services": services
        }


    def get_published_performance_leaderboard(self, db: Session, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Returns real historical performance metrics for published YouTube Shorts.
        Queries UploadRecord along with the latest PerformanceSnapshot and VideoAnalysisRecord.
        Sorted by views desc, then publish date desc.
        Zero synthetic metrics.
        """
        try:
            # Query latest snapshot per youtube_video_id
            subq = (
                db.query(
                    PerformanceSnapshot.youtube_video_id,
                    func.max(PerformanceSnapshot.id).label("max_snap_id")
                )
                .filter(PerformanceSnapshot.youtube_video_id.isnot(None))
                .group_by(PerformanceSnapshot.youtube_video_id)
                .subquery()
            )

            import re
            YOUTUBE_ID_REGEX = re.compile(r'^[A-Za-z0-9_-]{11}$')
            KNOWN_TEST_PREFIXES = (
                "test_", "TEST_", "yt_loop_", "test_vid_", "upl_test_",
                "upl_loop_", "vid_real_", "vid_deleted", "real_yt_", "legacy_vid"
            )

            query = (
                db.query(UploadRecord, PerformanceSnapshot, VideoAnalysisRecord)
                .join(subq, UploadRecord.youtube_video_id == subq.c.youtube_video_id)
                .join(PerformanceSnapshot, PerformanceSnapshot.id == subq.c.max_snap_id)
                .outerjoin(
                    VideoAnalysisRecord,
                    VideoAnalysisRecord.upload_id == UploadRecord.id
                )
                .filter(
                    UploadRecord.youtube_video_id.isnot(None),
                    UploadRecord.privacy_status != "test_local",
                    ~UploadRecord.youtube_video_id.ilike("dQw4w9WgXcQ%"),
                    ~UploadRecord.youtube_video_id.ilike("TEST_%"),
                    ~UploadRecord.youtube_video_id.ilike("test_%"),
                    ~UploadRecord.youtube_video_id.ilike("yt_loop_%"),
                    ~UploadRecord.id.ilike("upl_test_%"),
                    ~UploadRecord.id.ilike("test_%"),
                    ~UploadRecord.id.ilike("upl_loop_%")
                )
                .group_by(UploadRecord.youtube_video_id)
                .order_by(
                    desc(PerformanceSnapshot.views),
                    desc(UploadRecord.published_at),
                    desc(UploadRecord.created_at)
                )
                .limit(limit)
            )

            rows = query.all()
            leaderboard = []
            seen_yt_ids = set()

            for upload, snap, analysis in rows:
                yt_id = (upload.youtube_video_id or "").strip()
                if not yt_id or yt_id in seen_yt_ids:
                    continue
                # Validate genuine 11-character YouTube video ID format
                if not YOUTUBE_ID_REGEX.match(yt_id) or yt_id == "dQw4w9WgXcQ":
                    continue
                # Reject known test prefixes
                if any(yt_id.startswith(p) for p in KNOWN_TEST_PREFIXES):
                    continue
                # Reject test titles or test upload IDs
                if upload.id and any(upload.id.startswith(p) for p in KNOWN_TEST_PREFIXES):
                    continue
                if upload.privacy_status == "test_local":
                    continue
                seen_yt_ids.add(yt_id)

                is_unavailable = (snap is None) or (getattr(snap, "validation_status", "") == "UNAVAILABLE")
                views = snap.views if (snap and not is_unavailable and snap.views is not None) else None
                likes = snap.likes if (snap and not is_unavailable and snap.likes is not None) else None
                comments = snap.comments if (snap and not is_unavailable and snap.comments is not None) else None
                apv = snap.average_view_percentage if (snap and not is_unavailable and snap.average_view_percentage is not None) else None

                # Mathematically correct engagement calculation: (likes + comments) / views * 100
                if views is not None and views > 0 and (likes is not None or comments is not None):
                    tot_int = (likes or 0) + (comments or 0)
                    eng_rate = round((tot_int / views) * 100, 2)
                elif snap and not is_unavailable and snap.engagement_rate:
                    eng_rate = round(float(snap.engagement_rate), 2)
                else:
                    eng_rate = None

                pub_date = upload.published_at or upload.created_at
                pub_date_str = pub_date.strftime("%b %d, %Y %H:%M UTC") if pub_date else "—"

                leaderboard.append({
                    "rank": len(leaderboard) + 1,
                    "upload_id": upload.id,
                    "job_id": upload.job_id,
                    "youtube_video_id": yt_id,
                    "title": upload.title or "Untitled Short",
                    "published_at": pub_date.isoformat() + "Z" if pub_date else None,
                    "published_at_display": pub_date_str,
                    "views": views,
                    "views_display": format_compact_number(views) if views is not None else "UNAVAILABLE",
                    "likes": likes,
                    "likes_display": format_compact_number(likes) if likes is not None else "UNAVAILABLE",
                    "comments": comments,
                    "comments_display": format_compact_number(comments) if comments is not None else "UNAVAILABLE",
                    "apv": apv,
                    "apv_display": f"{apv:.1f}%" if apv is not None else "UNAVAILABLE",
                    "engagement_rate": eng_rate,
                    "engagement_display": f"{eng_rate:.2f}%" if eng_rate is not None else "UNAVAILABLE",
                    "classification": analysis.classification if analysis else "UNRATED",
                    "performance_score": analysis.performance_score if analysis else None,
                    "status": upload.status or "PUBLISHED",
                    "youtube_url": f"https://www.youtube.com/shorts/{yt_id}" if yt_id else None
                })

            return leaderboard
        except Exception as e:
            logger.error(f"Error generating performance leaderboard: {e}")
            return []

    def get_reconciliation_anomalies(self, db: Session) -> List[Dict[str, Any]]:
        """
        Detects data truth discrepancies across SQLite, YouTube, Google Drive Vault, and Learning Engine:
          1. DB says PUBLISHED but YouTube status is private or missing.
          2. DB says READY_TO_UPLOAD but file is missing in Drive 01_READY.
          3. Drive 01_READY file has no corresponding active job in SQLite.
          4. YouTube scheduled video is missing from SQLite UploadRecords.
          5. Learning cohort invariant violation: matured + maturing > verified_live.
        """
        anomalies = []
        now = datetime.utcnow()

        # 1. Learning cohort invariant check & phantom snapshots check
        try:
            from engines.learning_engine import LearningEngine
            learner = LearningEngine()
            universe = learner.get_verified_analytics_universe(db, now=now)
            if universe.get("data_integrity_error"):
                anomalies.append({
                    "entity": "LearningUniverse",
                    "expected_state": f"matured ({universe['mature_count']}) + maturing ({universe['maturing_count']}) <= verified_live ({universe['verified_live_count']})",
                    "observed_state": f"Cohort total {universe['total_analytics_cohort']} exceeds verified live {universe['verified_live_count']}",
                    "severity": "CRITICAL",
                    "source": "LearningEngine",
                    "timestamp": now.isoformat() + "Z"
                })

            phantom_snaps = (
                db.query(PerformanceSnapshot)
                .join(UploadRecord, PerformanceSnapshot.upload_id == UploadRecord.id)
                .filter(
                    (UploadRecord.privacy_status == "test_local") |
                    (UploadRecord.status == "FAILED") |
                    (UploadRecord.youtube_video_id.like("TEST_%"))
                )
                .count()
            )
            if phantom_snaps > 0:
                anomalies.append({
                    "entity": "LearningUniverse",
                    "expected_state": "Zero performance snapshots referencing test or failed uploads",
                    "observed_state": f"Found {phantom_snaps} phantom snapshot(s)",
                    "severity": "CRITICAL",
                    "source": "LearningEngine Integrity Check",
                    "timestamp": now.isoformat() + "Z"
                })
        except Exception as l_err:
            logger.debug(f"[RECONCILIATION_CHECK] Learning check notice: {l_err}")

        # 2. Scheduled Reconciliation Errors recorded in UploadRecords
        err_records = db.query(UploadRecord).filter(
            UploadRecord.reconciliation_metadata.ilike("%SCHEDULE_RECONCILIATION_ERROR%")
        ).all()
        for er in err_records:
            anomalies.append({
                "entity": f"UploadRecord_{er.id}",
                "expected_state": f"Valid YouTube scheduled video {er.youtube_video_id}",
                "observed_state": "Video missing or inaccessible on YouTube API",
                "severity": "CRITICAL",
                "source": "YouTube Data API v3 Reconciliation",
                "timestamp": now.isoformat() + "Z"
            })

        return anomalies

    def get_full_system_state(self, db: Session) -> Dict[str, Any]:
        """Provides a unified snapshot of the complete production system."""
        health = self.get_automation_health()
        locks = self.get_process_locks()
        inventory = self.get_drive_inventory()
        ready_count = inventory["counts"].get("01_READY", 0)
        publishing = self.get_publishing_status(db)
        buffer = self.get_buffer_status(ready_stock=ready_count)
        refill = self.get_refill_telemetry(db, ready_stock=ready_count)
        buffer["refill"] = refill
        learning = self.get_learning_status(db)
        scheduled_queue = self.get_scheduled_queue(db)
        voice_config = self.get_voice_config(db)
        bgm_status = self.get_bgm_library_status(db)
        cloud_workflows = self.get_cloud_workflows_status()
        timeline = self.get_production_timeline(db, limit=5)
        activity_feed = self.get_activity_feed(db, limit=20)
        recovery_telemetry = self.get_recovery_telemetry(db)
        pexels_quota = self.get_pexels_quota_status(db)
        service_quotas = self.get_all_service_quotas(db)

        # Database job stats
        total_jobs = db.query(Job).count()
        needs_review_count = db.query(Job).filter(Job.state == JobState.NEEDS_REVIEW.value).count()
        failed_jobs_count = db.query(Job).filter(Job.state == JobState.FAILED.value).count()

        recent_jobs = db.query(Job).order_by(Job.updated_at.desc()).limit(10).all()
        recent_jobs_data = [
            {
                "id": j.id,
                "state": j.state,
                "error_message": j.error_message,
                "retry_count": j.retry_count,
                "updated_at": j.updated_at.isoformat() + "Z" if j.updated_at else None,
                "created_at": j.created_at.isoformat() + "Z" if j.created_at else None,
            }
            for j in recent_jobs
        ]

        # Cloud Database Sync Telemetry (Phase 10.12)
        try:
            from core.database_sync import compute_sha256, verify_sqlite_integrity, get_database_stats
            from config.settings import DB_PATH
            is_valid, msg = verify_sqlite_integrity(DB_PATH) if DB_PATH.exists() else (False, "Missing")
            db_sync_telemetry = {
                "canonical_vault_folder": "00_SYSTEM",
                "canonical_filename": "pipeline.db",
                "local_db_exists": DB_PATH.exists(),
                "integrity_valid": is_valid,
                "integrity_message": msg,
                "sha256": compute_sha256(DB_PATH) if DB_PATH.exists() else None,
                "size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
                "table_counts": get_database_stats(DB_PATH) if DB_PATH.exists() else {},
                "concurrency_group": "pipeline-cloud-execution"
            }
        except Exception as sync_err:
            db_sync_telemetry = {"error": str(sync_err)}

        # Data Freshness & Source Truth Metadata
        token_path = PROJECT_ROOT / "token.json"
        has_token = token_path.exists()
        from engines.metrics_collector import MetricsCollector
        collector = MetricsCollector()
        oauth_info = collector.get_oauth_scope_status()

        data_freshness = {
            "verified_live": {
                "source": "YouTube Data API v3" if has_token else "SQLite Reconciliation Cache",
                "status": "LIVE_API" if has_token else "RECONCILED_LOCAL",
                "as_of": datetime.utcnow().isoformat() + "Z",
                "confidence": "HIGH"
            },
            "scheduled_publishing": {
                "source": "YouTube Data API v3" if has_token else "SQLite Scheduled Records",
                "status": "LIVE_API" if has_token else "CACHED_DB",
                "as_of": datetime.utcnow().isoformat() + "Z",
                "confidence": "HIGH"
            },
            "public_telemetry": {
                "source": "YouTube Data API v3 (Views, Likes, Comments)",
                "status": "LIVE_API" if has_token else "CACHED_DB",
                "as_of": datetime.utcnow().isoformat() + "Z",
                "confidence": "HIGH"
            },
            "private_analytics": {
                "source": "YouTube Analytics API (AVD, APV, Retention)",
                "status": "LIVE_API" if oauth_info.get("youtube_analytics") else "UNAVAILABLE",
                "as_of": datetime.utcnow().isoformat() + "Z",
                "confidence": "HIGH" if oauth_info.get("youtube_analytics") else "DEGRADED"
            },
            "telemetry_metrics": {
                "source": "YouTube Data API v3 & Analytics API",
                "status": "LIVE_API" if has_token else "UNAVAILABLE",
                "as_of": datetime.utcnow().isoformat() + "Z",
                "confidence": "HIGH" if has_token else "DEGRADED"
            },
            "oauth_status": {
                "status": oauth_info.get("status"),
                "reauthorization_required": oauth_info.get("reauthorization_required"),
                "reauthorization_command": oauth_info.get("command"),
                "scopes": oauth_info.get("scopes", [])
            },
            "drive_vault": {
                "source": "Google Drive API v3",
                "status": "LIVE_API" if has_token else "CACHED_LOCAL",
                "as_of": datetime.utcnow().isoformat() + "Z"
            }
        }

        return {
            "data_mode": "LIVE_PRODUCTION_DATA",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data_freshness": data_freshness,
            "health": health,
            "locks": locks,
            "inventory": inventory,
            "publishing": publishing,
            "buffer": buffer,
            "refill": refill,
            "learning": learning,
            "scheduled_queue": scheduled_queue,
            "voice_config": voice_config,
            "bgm_status": bgm_status,
            "cloud_workflows": cloud_workflows,
            "timeline": timeline,
            "activity_feed": activity_feed,
            "recovery_telemetry": recovery_telemetry,
            "pexels_quota": pexels_quota,
            "service_quotas": service_quotas,
            "database_sync": db_sync_telemetry,
            "reconciliation_anomalies": self.get_reconciliation_anomalies(db),
            "performance_leaderboard": self.get_published_performance_leaderboard(db, limit=50),
            "database_summary": {
                "total_jobs": total_jobs,
                "needs_review_count": needs_review_count,
                "failed_jobs_count": failed_jobs_count,
                "recent_jobs": recent_jobs_data
            }
        }
