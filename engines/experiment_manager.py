"""
Experiment Manager & Automated Strategy Execution Engine (Phase 4).
Connects closed-loop LearningEngine StrategyWeights into production strategy selection.
Features:
  - Controlled exploitation of winning strategies vs. intelligent exploration.
  - Strict validation against supported taxonomy values (never invents missing assets).
  - Multi-dimensional combination safety tracking (KNOWN, PARTIALLY_KNOWN, UNSEEN).
  - Complete experiment lifecycle tracking (PLANNED -> PRODUCED -> READY -> UPLOADED -> MEASURED / FAILED / CANCELLED).
  - Idempotent experiment creation & retry safety (never duplicates assignments).
  - Safe configuration & manual override mode (DEFAULT, LEARNED, EXPLORE).
  - Experiment-to-Upload and Experiment-to-Performance relational traceability.
"""
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from config.settings import SELF_IMPROVEMENT_ENABLED, STRATEGY_MODE, EXPLORATION_RATE
from core.models import ExperimentRecord, Topic, Job, UploadRecord, PerformanceSnapshot, StrategyWeight
from engines.learning_engine import LearningEngine

logger = logging.getLogger(__name__)


class ExperimentManager:
    """Orchestrates strategy selection and lifecycle tracking for content experiments."""

    # Supported and verified feature taxonomies
    VALID_HOOK_ARCHETYPES = [
        "DATE_TIME_ANCHOR",
        "CONTRADICTION_SHOCK",
        "HYPOTHETICAL_CURIOSITY",
        "IN_MEDIAS_RES",
        "UNSOLVED_MYSTERY",
        "OTHER"
    ]

    VALID_DURATION_TARGETS = [
        "ULTRA_TIGHT",
        "SWEET_SPOT",
        "NARRATIVE_RICH"
    ]

    VALID_BGM_MOODS = [
        "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
        "Mysterious / Tension / Disappearance / Cryptic Event / True Crime",
        "High Energy / Bizarre Incident / Absurd History / Action / Chaos",
        "Dramatic / Tragic / Emotional / Historical Downfall / Royal Scandals"
    ]

    VALID_MOTION_STYLES = [
        "DYNAMIC_ZOOM_PAN",
        "KEN_BURNS_STANDARD",
        "STATIC"
    ]

    # Valid lifecycle states
    VALID_STATUSES = [
        "PLANNED",
        "SELECTED",
        "PRODUCED",
        "READY",
        "UPLOADED",
        "MEASURED",
        "FAILED",
        "CANCELLED"
    ]

    def __init__(self, learning_engine: Optional[LearningEngine] = None):
        self.learning_engine = learning_engine or LearningEngine()

    def select_strategy(
        self,
        db: Session,
        topic: Optional[Topic] = None,
        explore_prob: Optional[float] = None,
        strategy_mode: Optional[str] = None,
        deterministic: bool = False
    ) -> Dict[str, Any]:
        """
        Selects a structured, validated production strategy.
        Respects:
          - Configuration switch (DEFAULT vs LEARNED vs EXPLORE).
          - Learned StrategyWeights from LearningEngine.
          - Feature combination safety & validation.
        """
        # Explicit strategy_mode argument takes precedence over the env-var SELF_IMPROVEMENT_ENABLED gate.
        # Only fall back to DEFAULT when SELF_IMPROVEMENT_ENABLED is False AND no explicit mode was given.
        explicit_mode = strategy_mode is not None
        mode = (strategy_mode or STRATEGY_MODE or "LEARNED").upper()
        prob = explore_prob if explore_prob is not None else EXPLORATION_RATE

        # 1. DEFAULT Fallback Mode
        # If caller explicitly passes strategy_mode, honour it even if SELF_IMPROVEMENT_ENABLED=False.
        if mode == "DEFAULT" or (not SELF_IMPROVEMENT_ENABLED and not explicit_mode):
            category = topic.category if topic else "General History"
            return {
                "hook_archetype": "DATE_TIME_ANCHOR",
                "duration_target": "SWEET_SPOT",
                "bgm_mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
                "motion_style": "DYNAMIC_ZOOM_PAN",
                "category": category,
                "selection_mode": "DEFAULT",
                "strategy_reason": "Baseline default strategy (Self-improvement disabled or DEFAULT mode).",
                "combination_type": "KNOWN",
                "strategy_recommendation": {}
            }

        # 2. EXPLORE Mode (Forced Exploration) — always uses random selection, always returns EXPLORATION
        if mode == "EXPLORE":
            rec = self.learning_engine.get_strategy_recommendation(db, explore_prob=1.0, deterministic=False)
            selection_mode = "EXPLORATION"
            reason = "Forced exploration mode across valid feature dimensions."
        else:
            # 3. LEARNED Mode (Exploitation with Controlled Exploration)
            rec = self.learning_engine.get_strategy_recommendation(db, explore_prob=prob, deterministic=deterministic)
            reasons = rec.get("reasoning", {})
            has_exploration = any("Exploration" in r for r in reasons.values())
            selection_mode = "EXPLORATION" if has_exploration else "EXPLOITATION"
            reason_parts = [f"{k}: {v}" for k, v in reasons.items()]
            reason = " | ".join(reason_parts) if reason_parts else "Learned strategy recommendation."

        raw_recs = rec.get("recommendations", {})

        # Validate and sanitize values against verified taxonomies
        hook = raw_recs.get("hook_archetype", "DATE_TIME_ANCHOR")
        if hook not in self.VALID_HOOK_ARCHETYPES:
            hook = "DATE_TIME_ANCHOR"

        duration = raw_recs.get("duration_target", "SWEET_SPOT")
        if duration not in self.VALID_DURATION_TARGETS:
            duration = "SWEET_SPOT"

        bgm = raw_recs.get("bgm_mood", "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities")
        if bgm not in self.VALID_BGM_MOODS:
            bgm = "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities"

        motion = raw_recs.get("motion_style", "DYNAMIC_ZOOM_PAN")
        if motion not in self.VALID_MOTION_STYLES:
            motion = "DYNAMIC_ZOOM_PAN"

        category = (topic.category if topic else None) or raw_recs.get("category", "General History")

        # Evaluate combination safety
        combination_type = self._evaluate_combination_type(db, hook, duration, bgm, motion)

        return {
            "hook_archetype": hook,
            "duration_target": duration,
            "bgm_mood": bgm,
            "motion_style": motion,
            "category": category,
            "selection_mode": selection_mode,
            "strategy_reason": reason,
            "combination_type": combination_type,
            "strategy_recommendation": rec
        }

    def _evaluate_combination_type(
        self,
        db: Session,
        hook: str,
        duration: str,
        bgm: str,
        motion: str
    ) -> str:
        """
        Determines if a feature combination is KNOWN, PARTIALLY_KNOWN, or UNSEEN.
        """
        exact_match = db.query(ExperimentRecord).filter(
            ExperimentRecord.hook_archetype == hook,
            ExperimentRecord.duration_target == duration,
            ExperimentRecord.bgm_mood == bgm,
            ExperimentRecord.motion_style == motion,
            ExperimentRecord.status.in_(["PRODUCED", "READY", "UPLOADED", "MEASURED"])
        ).first()

        if exact_match:
            return "KNOWN"

        partial_match = db.query(ExperimentRecord).filter(
            ExperimentRecord.hook_archetype == hook,
            ExperimentRecord.duration_target == duration,
            ExperimentRecord.status.in_(["PRODUCED", "READY", "UPLOADED", "MEASURED"])
        ).first()

        if partial_match:
            return "PARTIALLY_KNOWN"

        return "UNSEEN"

    def create_experiment(
        self,
        db: Session,
        job_id: str,
        topic_id: Optional[str],
        strategy: Dict[str, Any],
        experiment_group_id: Optional[str] = None,
        title: Optional[str] = None
    ) -> ExperimentRecord:
        """
        Persists a newly assigned production strategy.
        Idempotent: If an experiment already exists for job_id, returns it without creating a duplicate.
        """
        existing = db.query(ExperimentRecord).filter(ExperimentRecord.job_id == job_id).first()
        if existing:
            logger.info(f"Experiment record already exists for job_id={job_id} (id={existing.id}).")
            return existing

        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        exp = ExperimentRecord(
            id=exp_id,
            experiment_type="STRATEGY_ASSIGNMENT",
            experiment_group_id=experiment_group_id,
            title=title or f"Strategy Assignment for Job {job_id[:8]}",
            hypothesis=f"Applying {strategy.get('selection_mode', 'EXPLOITATION')} strategy to optimize retention and engagement.",
            control_variable="Baseline Pipeline Default",
            test_variable=f"{strategy.get('hook_archetype')}+{strategy.get('duration_target')}+{strategy.get('motion_style')}",
            job_id=job_id,
            topic_id=topic_id,
            hook_archetype=strategy.get("hook_archetype"),
            duration_target=strategy.get("duration_target"),
            bgm_mood=strategy.get("bgm_mood"),
            motion_style=strategy.get("motion_style"),
            category=strategy.get("category"),
            selection_mode=strategy.get("selection_mode", "EXPLOITATION"),
            strategy_reason=strategy.get("strategy_reason"),
            combination_type=strategy.get("combination_type", "KNOWN"),
            status="SELECTED",
            created_at=datetime.utcnow()
        )
        db.add(exp)
        db.commit()
        logger.info(f"Created ExperimentRecord id={exp_id} for job_id={job_id} ({strategy.get('selection_mode')}).")
        return exp

    def update_experiment_status(
        self,
        db: Session,
        job_id: str,
        status: str,
        failure_reason: Optional[str] = None,
        upload_id: Optional[str] = None,
        youtube_video_id: Optional[str] = None,
        snapshot_id: Optional[int] = None
    ) -> Optional[ExperimentRecord]:
        """
        Updates experiment lifecycle state (SELECTED -> PRODUCED -> READY -> UPLOADED -> MEASURED / FAILED / CANCELLED).
        """
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Invalid experiment status '{status}'. Must be one of {self.VALID_STATUSES}")

        exp = db.query(ExperimentRecord).filter(ExperimentRecord.job_id == job_id).first()
        if not exp:
            logger.warning(f"No ExperimentRecord found for job_id={job_id} to update to {status}.")
            return None

        exp.status = status
        if failure_reason:
            exp.failure_reason = failure_reason
        if upload_id:
            exp.upload_id = upload_id
        if youtube_video_id:
            exp.youtube_video_id = youtube_video_id
        if snapshot_id is not None:
            exp.outcome_snapshot_id = snapshot_id

        if status in ("MEASURED", "FAILED", "CANCELLED"):
            exp.concluded_at = datetime.utcnow()

        db.commit()
        return exp

    def link_experiment_to_upload(
        self,
        db: Session,
        job_id: str,
        upload_id: str,
        youtube_video_id: str
    ) -> Optional[ExperimentRecord]:
        """Links experiment to published YouTube upload record."""
        return self.update_experiment_status(
            db=db,
            job_id=job_id,
            status="UPLOADED",
            upload_id=upload_id,
            youtube_video_id=youtube_video_id
        )

    def link_experiment_to_snapshot(
        self,
        db: Session,
        upload_id: str,
        snapshot_id: int,
        score: float
    ) -> Optional[ExperimentRecord]:
        """Links experiment to mature performance snapshot and concludes measurement."""
        exp = db.query(ExperimentRecord).filter(ExperimentRecord.upload_id == upload_id).first()
        if not exp:
            return None

        exp.status = "MEASURED"
        exp.outcome_snapshot_id = snapshot_id
        exp.outcome_summary = f"Performance score: {score:.2f}/100"
        exp.concluded_at = datetime.utcnow()
        db.commit()
        return exp
