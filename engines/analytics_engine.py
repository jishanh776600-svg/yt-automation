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
        1. Harvests snapshots for mature, eligible uploads
        2. Links snapshots to ExperimentRecords with MEASURED status
        3. Recalculates StrategyWeights via LearningEngine
        4. Updates LEARNING_LOG.md
        """
        logger.info("Starting Closed-Loop Performance Analysis...")

        # 1. Collect latest metrics snapshots and auto-run learning cycle
        harvest_summary = self.collector.harvest_all_eligible_shorts(db, auto_learn=True)

        # 2. Run Learning cycle directly if not already triggered by new harvests
        learning_summary = harvest_summary.get("learning_summary")
        if not learning_summary:
            try:
                learning_summary = self.learner.run_learning_cycle(db)
            except Exception as e:
                logger.warning(f"Learning cycle notice: {e}")
                learning_summary = {}

        return {
            "snapshots_harvested": harvest_summary.get("snapshots_harvested", 0),
            "skipped_immature": harvest_summary.get("skipped_immature_count", 0),
            "skipped_idempotent": harvest_summary.get("skipped_idempotent_count", 0),
            "learning_cycle_executed": bool(learning_summary),
            "weights_updated_count": learning_summary.get("weights_updated_count", 0) if learning_summary else 0,
            "harvest_summary": harvest_summary,
            "learning_summary": learning_summary
        }
