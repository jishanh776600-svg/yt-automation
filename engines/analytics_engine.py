"""
Analytics & Continuous Learning Loop Orchestrator.
Runs the complete closed feedback loop:
MEASURE -> ANALYZE -> LEARN -> TEST -> REPORT.
"""
import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from core.models import UploadRecord, PerformanceSnapshot, VideoAnalysisRecord, ContentPattern, ExperimentRecord
from engines.metrics_collector import MetricsCollector
from engines.video_analyzer import VideoAnalyzer
from engines.learning_engine import LearningEngine
from engines.experiment_manager import ExperimentManager
from engines.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Orchestrates the continuous feedback loop across all published videos."""

    def __init__(self):
        self.collector = MetricsCollector()
        self.analyzer = VideoAnalyzer()
        self.learner = LearningEngine()
        self.exp_manager = ExperimentManager()
        self.reporter = ReportGenerator()

    def run_feedback_loop(self, db: Session, mock_dataset: bool = False) -> Dict[str, Any]:
        """
        Executes the end-to-end feedback loop:
        1. Collects snapshots
        2. Computes baselines & classifies videos
        3. Extracts structured root causes (Fact vs Hypothesis)
        4. Updates persistent ContentPattern database with confidence ratings
        5. Logs daily & weekly intelligence reports
        """
        logger.info("Starting Closed-Loop Performance Analysis...")

        # 1. Collect latest metrics snapshots
        snapshots = self.collector.collect_all_active_shorts(db)
        
        # 2. Compute channel rolling medians
        baselines = self.analyzer.compute_channel_baselines(db)

        # 3. Analyze each upload
        uploads = db.query(UploadRecord).filter(UploadRecord.youtube_video_id.isnot(None)).all()
        analyses = []
        for upl in uploads:
            an = self.analyzer.analyze_video(db, upl, baselines)
            analyses.append(an)

        # 4. Update persistent learning knowledge base
        patterns = self.learner.update_learning_database(db)

        # 5. Generate daily intelligence report
        daily_report = self.reporter.generate_daily_learning_report(db)
        logger.info("\n" + daily_report)

        return {
            "snapshots_collected": len(snapshots),
            "videos_analyzed": len(analyses),
            "patterns_active": len(patterns),
            "channel_baselines": baselines,
            "daily_report": daily_report
        }
