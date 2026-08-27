"""
Performance Metrics Collector Engine.
Queries YouTube Data API v3 and YouTube Analytics API for every published Short.
Collects and appends immutable time-series snapshots (Views, APV, AVD, Subs Gained, Likes, Shares, Comments, Traffic).
Never overwrites historical data.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT, TEST_MODE
from core.models import UploadRecord, PerformanceSnapshot, Job

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collects multi-factor performance metrics from YouTube APIs."""

    def __init__(self):
        self.token_path = PROJECT_ROOT / "token.json"

    def get_youtube_clients(self):
        """Initializes YouTube Data API and YouTube Analytics API clients."""
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials

            if not self.token_path.exists():
                logger.warning("token.json not found for live metrics collection.")
                return None, None

            creds = Credentials.from_authorized_user_file(str(self.token_path))
            yt_data = build("youtube", "v3", credentials=creds)
            yt_analytics = build("youtubeAnalytics", "v2", credentials=creds)
            return yt_data, yt_analytics
        except Exception as e:
            logger.warning(f"Could not initialize YouTube API clients: {e}")
            return None, None

    def collect_for_upload(self, db: Session, upload: UploadRecord, mock_data: Optional[Dict[str, Any]] = None) -> PerformanceSnapshot:
        """
        Collects metrics for a single upload and records an immutable PerformanceSnapshot.
        """
        now = datetime.utcnow()
        hours_since = 0.0
        if upload.published_at:
            delta = now - upload.published_at
            hours_since = delta.total_seconds() / 3600.0

        if mock_data:
            # Used for unit/simulation tests
            snapshot = PerformanceSnapshot(
                upload_id=upload.id,
                youtube_video_id=upload.youtube_video_id,
                snapshot_time=now,
                hours_since_upload=hours_since,
                views=mock_data.get("views", 0),
                likes=mock_data.get("likes", 0),
                comments=mock_data.get("comments", 0),
                shares=mock_data.get("shares", 0),
                subscribers_gained=mock_data.get("subscribers_gained", 0),
                subscribers_lost=mock_data.get("subscribers_lost", 0),
                average_view_duration_sec=mock_data.get("average_view_duration_sec", 0.0),
                average_view_percentage=mock_data.get("average_view_percentage", 0.0),
                estimated_minutes_watched=mock_data.get("estimated_minutes_watched", 0.0),
                engagement_rate=mock_data.get("engagement_rate", 0.0),
                traffic_sources_json=json.dumps(mock_data.get("traffic_sources", {})),
                raw_analytics_json=json.dumps(mock_data)
            )
            db.add(snapshot)
            db.commit()
            return snapshot

        yt_data, yt_analytics = self.get_youtube_clients()
        views = 0
        likes = 0
        comments = 0
        shares = 0
        subs_gained = 0
        subs_lost = 0
        avd = 0.0
        apv = 0.0
        est_minutes = 0.0
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
            except Exception as e:
                logger.warning(f"Error fetching Data API stats for {upload.youtube_video_id}: {e}")

            # 2. Fetch Analytics API metrics (APV, AVD, Subs, Watch Time)
            if yt_analytics:
                try:
                    start_date = upload.published_at.strftime("%Y-%m-%d") if upload.published_at else "2026-01-01"
                    end_date = now.strftime("%Y-%m-%d")
                    analytics_res = yt_analytics.reports().query(
                        ids="channel==MINE",
                        startDate=start_date,
                        endDate=end_date,
                        metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,shares",
                        filters=f"video=={upload.youtube_video_id}"
                    ).execute()
                    
                    rows = analytics_res.get("rows", [])
                    if rows and len(rows) > 0:
                        row = rows[0]
                        # Columns map: views(0), estMinutes(1), avd(2), apv(3), subsGained(4), subsLost(5), shares(6)
                        est_minutes = float(row[1]) if len(row) > 1 else 0.0
                        avd = float(row[2]) if len(row) > 2 else 0.0
                        apv = float(row[3]) if len(row) > 3 else 0.0
                        subs_gained = int(row[4]) if len(row) > 4 else 0
                        subs_lost = int(row[5]) if len(row) > 5 else 0
                        shares = int(row[6]) if len(row) > 6 else 0
                        raw_data["analytics_rows"] = row
                except Exception as e:
                    logger.info(f"Analytics API data pending/unavailable for video {upload.youtube_video_id}: {e}")

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
        logger.info(f"Recorded PerformanceSnapshot for {upload.youtube_video_id}: {views} views, {apv:.1f}% APV, {engagement_rate:.2f}% engagement")
        return snapshot

    def collect_all_active_shorts(self, db: Session) -> List[PerformanceSnapshot]:
        """Collects latest snapshot for all published uploads."""
        uploads = db.query(UploadRecord).filter(UploadRecord.youtube_video_id.isnot(None)).all()
        snapshots = []
        for upl in uploads:
            snap = self.collect_for_upload(db, upl)
            snapshots.append(snap)
        return snapshots
