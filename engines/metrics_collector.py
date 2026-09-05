"""
Performance Metrics Collector & Scheduled Harvester Engine.
Queries YouTube Data API v3 and YouTube Analytics API for published Shorts.
Collects and appends immutable time-series snapshots (Views, APV, AVD, Subs Gained, Likes, Shares, Comments, Traffic).
Features:
  - Strict 24-hour maturation gate.
  - Idempotent harvesting (skips redundant snapshots within 20-hour window).
  - Graceful fallback when YouTube Analytics scope is missing (uses Data API v3 statistics).
  - Never overwrites or destroys historical snapshots.
"""
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT, TEST_MODE
from core.database import SessionLocal, init_db
from core.models import UploadRecord, PerformanceSnapshot, Job

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects multi-factor performance metrics from YouTube APIs."""

    def __init__(self):
        self.token_path = PROJECT_ROOT / "token.json"

    def get_youtube_clients(self):
        """Initializes YouTube Data API and YouTube Analytics API clients."""
        import os
        if TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes"):
            return None, None

        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials

            if not self.token_path.exists():
                logger.warning("token.json not found for live metrics collection.")
                return None, None

            creds = Credentials.from_authorized_user_file(str(self.token_path))
            yt_data = build("youtube", "v3", credentials=creds)

            # Check if yt-analytics.readonly scope is present in credentials
            has_analytics_scope = any(
                "yt-analytics" in s or "youtube.readonly" in s or s == "https://www.googleapis.com/auth/youtube"
                for s in (creds.scopes or [])
            )
            
            yt_analytics = None
            if has_analytics_scope:
                try:
                    yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
                except Exception as analytics_err:
                    logger.info(f"YouTube Analytics API initialization notice: {analytics_err}")
            else:
                logger.info("YouTube Analytics API scope (yt-analytics.readonly) not present in current token. Falling back to YouTube Data API v3 statistics.")

            return yt_data, yt_analytics
        except Exception as e:
            logger.warning(f"Could not initialize YouTube API clients: {e}")
            return None, None

    def get_oauth_scope_status(self) -> Dict[str, Any]:
        """
        Audits active OAuth scopes stored in token.json and reports explicit authorization status.
        """
        if not self.token_path.exists():
            return {
                "status": "TOKEN_MISSING",
                "scopes": [],
                "youtube_upload": False,
                "youtube_management": False,
                "drive": False,
                "youtube_analytics": False,
                "reauthorization_required": True,
                "command": "python auth_youtube.py"
            }

        try:
            data = json.loads(self.token_path.read_text(encoding="utf-8"))
            scopes = data.get("scopes", [])

            has_upload = any("youtube.upload" in s or s == "https://www.googleapis.com/auth/youtube" for s in scopes)
            has_yt = any(s == "https://www.googleapis.com/auth/youtube" for s in scopes)
            has_drive = any("drive" in s for s in scopes)
            has_analytics = any("yt-analytics" in s or "youtube.readonly" in s for s in scopes)

            reauth_needed = not has_analytics
            status = "FULL_ANALYTICS_ACTIVE" if has_analytics else "REAUTHORIZATION_REQUIRED"

            return {
                "status": status,
                "scopes": scopes,
                "youtube_upload": has_upload,
                "youtube_management": has_yt,
                "drive": has_drive,
                "youtube_analytics": has_analytics,
                "reauthorization_required": reauth_needed,
                "command": "python auth_youtube.py"
            }
        except Exception as e:
            logger.warning(f"Error auditing token scopes: {e}")
            return {
                "status": "ERROR",
                "scopes": [],
                "youtube_upload": False,
                "youtube_management": False,
                "drive": False,
                "youtube_analytics": False,
                "reauthorization_required": True,
                "command": "python auth_youtube.py"
            }

    def is_eligible_for_harvesting(
        self,
        db: Session,
        upload: UploadRecord,
        now: Optional[datetime] = None,
        min_hours: float = 24.0,
        idempotency_window_hours: float = 20.0
    ) -> Tuple[bool, str]:
        """
        Determines whether a video upload is eligible for a new performance snapshot.
        Rules:
          1. Must have a valid, non-empty YouTube video ID.
          2. Must have been published at least min_hours (24h) ago.
          3. Must not have an existing snapshot recorded within the idempotency window (20h).
        """
        if not upload.youtube_video_id or not upload.youtube_video_id.strip():
            return False, "MISSING_YOUTUBE_ID"

        if not now:
            now = datetime.utcnow()

        # 1. Publication age check
        if upload.published_at:
            hours_since = (now - upload.published_at).total_seconds() / 3600.0
            if hours_since < min_hours:
                return False, f"IMMATURE_VIDEO ({hours_since:.1f}h < {min_hours:.1f}h)"
        else:
            # Fallback to created_at if published_at was not recorded
            if upload.created_at:
                hours_since = (now - upload.created_at).total_seconds() / 3600.0
                if hours_since < min_hours:
                    return False, f"IMMATURE_VIDEO ({hours_since:.1f}h < {min_hours:.1f}h)"

        # 2. Idempotency window check
        recent_threshold = now - timedelta(hours=idempotency_window_hours)
        recent_snapshot = (
            db.query(PerformanceSnapshot)
            .filter(
                PerformanceSnapshot.upload_id == upload.id,
                PerformanceSnapshot.snapshot_time >= recent_threshold
            )
            .first()
        )
        if recent_snapshot:
            return False, f"IDEMPOTENT_SKIP (Snapshot already recorded at {recent_snapshot.snapshot_time.strftime('%Y-%m-%d %H:%M')})"

        return True, "ELIGIBLE"

    def collect_for_upload(
        self,
        db: Session,
        upload: UploadRecord,
        mock_data: Optional[Dict[str, Any]] = None,
        now: Optional[datetime] = None
    ) -> Optional[PerformanceSnapshot]:
        """
        Collects metrics for a single upload and records an immutable PerformanceSnapshot.
        """
        if not now:
            now = datetime.utcnow()

        hours_since = 0.0
        if upload.published_at:
            delta = now - upload.published_at
            hours_since = delta.total_seconds() / 3600.0
        elif upload.created_at:
            delta = now - upload.created_at
            hours_since = delta.total_seconds() / 3600.0

        if mock_data:
            # Used for unit/simulation tests
            views = mock_data.get("views", 0)
            likes = mock_data.get("likes", 0)
            comments = mock_data.get("comments", 0)
            shares = mock_data.get("shares", 0)
            subs_gained = mock_data.get("subscribers_gained", 0)
            subs_lost = mock_data.get("subscribers_lost", 0)
            avd = mock_data.get("average_view_duration_sec", 0.0)
            apv = mock_data.get("average_view_percentage", 0.0)
            est_minutes = mock_data.get("estimated_minutes_watched", 0.0)
            traffic_sources = mock_data.get("traffic_sources", {})

            total_interactions = likes + comments + shares
            engagement_rate = (total_interactions / views * 100.0) if views > 0 else 0.0

            snapshot = PerformanceSnapshot(
                upload_id=upload.id,
                youtube_video_id=upload.youtube_video_id,
                snapshot_time=now,
                hours_since_upload=hours_since,
                views=views,
                likes=likes,
                comments=comments,
                shares=shares,
                subscribers_gained=subs_gained,
                subscribers_lost=subs_lost,
                average_view_duration_sec=avd,
                average_view_percentage=apv,
                estimated_minutes_watched=est_minutes,
                engagement_rate=engagement_rate,
                traffic_sources_json=json.dumps(traffic_sources),
                raw_analytics_json=json.dumps(mock_data)
            )
            db.add(snapshot)
            db.commit()

            # Link snapshot to ExperimentRecord if one exists
            try:
                from engines.experiment_manager import ExperimentManager
                from engines.learning_engine import LearningEngine
                learner = LearningEngine()
                score = learner.normalize_performance(snapshot)
                exp_mgr = ExperimentManager(learning_engine=learner)
                exp_mgr.link_experiment_to_snapshot(db, upload_id=upload.id, snapshot_id=snapshot.id, score=score)
            except Exception as link_err:
                logger.debug(f"Could not link snapshot to experiment: {link_err}")

            return snapshot

        yt_data, yt_analytics = self.get_youtube_clients()
        views = 0
        likes = 0
        comments = 0
        shares = 0
        subs_gained = 0
        subs_lost = 0
        avd = None
        apv = None
        est_minutes = None
        traffic_sources = {}
        raw_data = {}

        if yt_data and upload.youtube_video_id and not upload.youtube_video_id.startswith("TEST_"):
            try:
                # 1. Fetch public video stats from Data API v3
                res = yt_data.videos().list(part="statistics", id=upload.youtube_video_id).execute()
                items = res.get("items", [])
                if items:
                    stats = items[0].get("statistics", {})
                    views = int(stats.get("viewCount", 0))
                    likes = int(stats.get("likeCount", 0))
                    comments = int(stats.get("commentCount", 0))
                    raw_data["statistics"] = stats
                else:
                    logger.warning(f"Video {upload.youtube_video_id} returned no items from Data API (may be private or deleted).")
            except Exception as e:
                logger.warning(f"Error fetching Data API stats for {upload.youtube_video_id}: {e}")

            # 2. Fetch Analytics API metrics (APV, AVD, Subs, Watch Time) if client is active
            if yt_analytics and (upload.published_at or upload.created_at):
                try:
                    pub_dt = upload.published_at or upload.created_at
                    start_date = pub_dt.strftime("%Y-%m-%d")
                    end_date = now.strftime("%Y-%m-%d")
                    metrics_query = (
                        "views,estimatedMinutesWatched,averageViewDuration,"
                        "averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares"
                    )
                    analytics_res = yt_analytics.reports().query(
                        ids="channel==MINE",
                        startDate=start_date,
                        endDate=end_date,
                        metrics=metrics_query,
                        filters=f"video=={upload.youtube_video_id}"
                    ).execute()

                    rows = analytics_res.get("rows", [])
                    if rows and len(rows) > 0:
                        row = rows[0]
                        # Map Analytics API columns
                        est_minutes = float(row[1]) if len(row) > 1 and row[1] is not None else None
                        avd = float(row[2]) if len(row) > 2 and row[2] is not None else None
                        apv = float(row[3]) if len(row) > 3 and row[3] is not None else None
                        subs_gained = int(row[4]) if len(row) > 4 and row[4] is not None else 0
                        subs_lost = int(row[5]) if len(row) > 5 and row[5] is not None else 0
                        shares = int(row[8]) if len(row) > 8 and row[8] is not None else 0
                        raw_data["analytics"] = analytics_res
                    else:
                        logger.info(f"Analytics API returned 0 rows for video {upload.youtube_video_id}. (Metrics marked UNAVAILABLE).")
                except Exception as e:
                    logger.warning(f"Analytics API query notice for {upload.youtube_video_id}: {e}. (Metrics marked UNAVAILABLE).")

        # Compute engagement rate
        total_interactions = likes + comments + shares
        engagement_rate = (total_interactions / views * 100.0) if views > 0 else 0.0

        snapshot = PerformanceSnapshot(
            upload_id=upload.id,
            youtube_video_id=upload.youtube_video_id,
            snapshot_time=now,
            hours_since_upload=hours_since,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            subscribers_gained=subs_gained,
            subscribers_lost=subs_lost,
            average_view_duration_sec=avd,
            average_view_percentage=apv,
            estimated_minutes_watched=est_minutes,
            engagement_rate=engagement_rate,
            traffic_sources_json=json.dumps(traffic_sources),
            raw_analytics_json=json.dumps(raw_data)
        )
        db.add(snapshot)
        db.commit()
        apv_display = f"{apv:.1f}%" if apv is not None else "UNAVAILABLE"
        logger.info(f"[+] Recorded Snapshot for '{upload.title}' ({upload.youtube_video_id}): {views} views | {apv_display} APV | {engagement_rate:.2f}% engagement")

        # Link snapshot to ExperimentRecord if one exists
        try:
            from engines.experiment_manager import ExperimentManager
            from engines.learning_engine import LearningEngine
            learner = LearningEngine()
            score = learner.normalize_performance(snapshot)
            exp_mgr = ExperimentManager(learning_engine=learner)
            exp_mgr.link_experiment_to_snapshot(db, upload_id=upload.id, snapshot_id=snapshot.id, score=score)
        except Exception as link_err:
            logger.debug(f"Could not link snapshot to experiment: {link_err}")

        return snapshot

    def harvest_all_eligible_shorts(
        self,
        db: Session,
        now: Optional[datetime] = None,
        auto_learn: bool = True
    ) -> Dict[str, Any]:
        """
        Main scheduled harvester entry point.
        Evaluates every published upload, filters for maturity and idempotency,
        and records new snapshots for eligible videos.
        If auto_learn=True and new snapshots are recorded, triggers the closed-loop learning cycle.
        """
        if not now:
            now = datetime.utcnow()

        uploads = db.query(UploadRecord).filter(UploadRecord.youtube_video_id.isnot(None)).all()
        harvested = []
        skipped_immature = []
        skipped_idempotent = []
        skipped_other = []

        logger.info(f"Starting Scheduled Analytics Harvest across {len(uploads)} published videos...")

        for upl in uploads:
            try:
                is_eligible, reason = self.is_eligible_for_harvesting(db, upl, now=now)
                if is_eligible:
                    snap = self.collect_for_upload(db, upl, now=now)
                    if snap:
                        harvested.append(snap)
                else:
                    if "IMMATURE" in reason:
                        skipped_immature.append((upl.title, reason))
                    elif "IDEMPOTENT" in reason:
                        skipped_idempotent.append((upl.title, reason))
                    else:
                        skipped_other.append((upl.title, reason))
            except Exception as single_err:
                logger.warning(f"Error harvesting metrics for upload {upl.id} ({upl.youtube_video_id}): {single_err}. Continuing with remaining uploads.")
                skipped_other.append((upl.title, f"HARVEST_ERROR: {single_err}"))

        summary = {
            "total_uploads_evaluated": len(uploads),
            "snapshots_harvested": len(harvested),
            "skipped_immature_count": len(skipped_immature),
            "skipped_idempotent_count": len(skipped_idempotent),
            "skipped_other_count": len(skipped_other),
            "harvest_timestamp": now.isoformat(),
            "learning_cycle_executed": False
        }

        # Auto-trigger closed-loop learning cycle if new snapshots were harvested
        if auto_learn and len(harvested) > 0:
            try:
                from engines.learning_engine import LearningEngine
                learner = LearningEngine()
                learning_summary = learner.run_learning_cycle(db, now=now)
                summary["learning_cycle_executed"] = True
                summary["learning_summary"] = learning_summary
                logger.info(f"Closed-loop learning cycle auto-executed: {learning_summary['weights_updated_count']} weights updated.")
            except Exception as learn_err:
                logger.warning(f"Could not auto-execute learning cycle: {learn_err}")

        logger.info(
            f"Analytics Harvesting Complete: {len(harvested)} snapshots recorded | "
            f"{len(skipped_idempotent)} already fresh | {len(skipped_immature)} immature (<24h)"
        )
        return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    init_db()
    db_session = SessionLocal()
    try:
        collector = MetricsCollector()
        results = collector.harvest_all_eligible_shorts(db_session)
        print(json.dumps(results, indent=2))
    finally:
        db_session.close()
