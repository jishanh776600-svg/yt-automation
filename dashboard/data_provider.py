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

from config.settings import PROJECT_ROOT, TEST_MODE, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, JobState
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
    (10, 0, "10:00 UTC (03:30 PM IST)"),
    (15, 0, "15:00 UTC (08:30 PM IST)"),
    (20, 0, "20:00 UTC (01:30 AM IST)"),
]

TARGET_RESERVE_BUFFER = 12


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
            for f in folders:
                file_list = self.drive_engine.list_files_in_folder(f)
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

    def get_publishing_status(self, db: Session) -> Dict[str, Any]:
        """Calculates today's published & scheduled count, remaining slots, and next release."""
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        published_records_today = db.query(UploadRecord).filter(
            UploadRecord.published_at >= today_start,
            UploadRecord.published_at < today_end,
            UploadRecord.status == "PUBLISHED"
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
        next_slot_info = {
            "slot_label": f"{next_unoccupied.strftime('%b %d, %Y')} at {next_unoccupied.strftime('%H:%M')} UTC",
            "slot_iso": next_unoccupied.isoformat() + "Z",
            "is_today": next_unoccupied.date() == today_start.date(),
            "time_until_display": f"{int((next_unoccupied - datetime.utcnow()).total_seconds() // 3600)}h {int(((next_unoccupied - datetime.utcnow()).total_seconds() % 3600) // 60)}m"
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

        return {
            "published_today": published_count_today,
            "scheduled_today": scheduled_count_today,
            "total_booked_today": total_booked_today,
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
        if ready_stock == 0:
            health = "DEPLETED"
        elif ready_stock < DAILY_SHORTS_LIMIT:
            health = "CRITICAL_LOW"
        elif ready_stock < target:
            health = "REPLENISHING"

        return {
            "ready_stock": ready_stock,
            "target_reserve": target,
            "health": health,
            "runway_days": runway_days,
            "runway_hours": runway_hours,
            "runway_display": f"{runway_days:.1f} days ({runway_hours:.0f} hours)",
            "needed_replenishment": max(0, target - ready_stock)
        }

    def get_learning_status(self, db: Session) -> Dict[str, Any]:
        """Reads real continuous learning feedback loop and pattern intelligence."""
        patterns = db.query(ContentPattern).order_by(
            ContentPattern.composite_effectiveness_score.desc()
        ).all()

        weights = db.query(StrategyWeight).order_by(
            StrategyWeight.feature_type, StrategyWeight.feature_value
        ).all()

        total_mature_snapshots = db.query(PerformanceSnapshot).count()
        total_experiments = db.query(ExperimentRecord).count()

        # Group weights by feature type
        grouped_weights: Dict[str, List[Dict[str, Any]]] = {}
        for w in weights:
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

        pattern_list = [
            {
                "pattern_type": p.pattern_type,
                "pattern_key": p.pattern_key,
                "sample_size": p.sample_size,
                "avg_apv": round(p.avg_percentage_viewed, 2) if p.avg_percentage_viewed is not None else None,
                "avg_engagement": round(p.avg_engagement_rate, 2) if p.avg_engagement_rate is not None else None,
                "score": round(p.composite_effectiveness_score, 2) if p.composite_effectiveness_score is not None else None,
                "confidence": p.confidence
            }
            for p in patterns
        ]

        # Calculate channel baseline score if video analyses or mature snapshots exist
        baseline_score = None
        analyses_scores = [a.performance_score for a in db.query(VideoAnalysisRecord).all() if a.performance_score is not None]
        if analyses_scores:
            baseline_score = round(sum(analyses_scores) / len(analyses_scores), 2)
        elif total_mature_snapshots > 0:
            apvs = [s.average_view_percentage for s in db.query(PerformanceSnapshot).all() if s.average_view_percentage is not None]
            if apvs:
                baseline_score = round(sum(apvs) / len(apvs), 2)

        return {
            "has_mature_data": total_mature_snapshots > 0,
            "total_mature_snapshots": total_mature_snapshots,
            "total_experiments": total_experiments,
            "channel_baseline_score": baseline_score if baseline_score is not None else "UNAVAILABLE (Accumulating 24h Telemetry)",
            "patterns": pattern_list,
            "strategy_weights": grouped_weights,
            "voice_configured": KOKORO_VOICE,
            "mode": "PROVEN_PATTERN (60%) / CONTROLLED_VARIATION (30%) / EXPLORATION (10%)"
        }

    def get_scheduled_queue(self, db: Session, limit: int = 20) -> Dict[str, Any]:
        """
        Retrieves the real YouTube scheduled publishing queue, upcoming slots,
        and reconciliation state across SQLite, YouTube, and Google Drive Vault.
        """
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

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
                    diff_sec = int((r.scheduled_publish_at - now).total_seconds())
                    if diff_sec > 0:
                        recon_state = "PENDING_RELEASE"
                        h = diff_sec // 3600
                        m = (diff_sec % 3600) // 60
                        time_until_str = f"in {h}h {m}m"
                        future_scheduled.append(r)
                        if today_start <= r.scheduled_publish_at < today_end:
                            scheduled_today.append(r)
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
        return {
            "active_voice_id": active_id,
            "active_voice": active_voice,
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
                "target": "Replenish 01_READY reserve to 12 Shorts",
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

        # 5. Google Drive Storage
        try:
            drive_quota = self.drive_engine.get_storage_quota()
            if drive_quota and drive_quota.get("limit") is not None:
                limit_b = drive_quota["limit"]
                used_b = drive_quota.get("usage", 0)
                rem_b = max(0, limit_b - used_b)
                used_gb = used_b / (1024 ** 3)
                limit_gb = limit_b / (1024 ** 3)
                pct = (used_b / limit_b) * 100 if limit_b > 0 else 0.0

                if rem_b < 200 * (1024 ** 2):  # < 200MB
                    drive_status = "CRITICAL"
                elif rem_b < 1 * (1024 ** 3):    # < 1GB
                    drive_status = "WARNING"
                else:
                    drive_status = "SAFE"

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
                    "message": f"{used_gb:.2f} GB used of {limit_gb:.2f} GB ({pct:.1f}% capacity)."
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

    def get_full_system_state(self, db: Session) -> Dict[str, Any]:
        """Provides a unified snapshot of the complete production system."""
        health = self.get_automation_health()
        locks = self.get_process_locks()
        inventory = self.get_drive_inventory()
        ready_count = inventory["counts"].get("01_READY", 0)
        publishing = self.get_publishing_status(db)
        buffer = self.get_buffer_status(ready_stock=ready_count)
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

        return {
            "data_mode": "LIVE_PRODUCTION_DATA",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "health": health,
            "locks": locks,
            "inventory": inventory,
            "publishing": publishing,
            "buffer": buffer,
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
            "database_summary": {
                "total_jobs": total_jobs,
                "needs_review_count": needs_review_count,
                "failed_jobs_count": failed_jobs_count,
                "recent_jobs": recent_jobs_data
            }
        }
