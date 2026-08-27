"""
Controlled Experiment Manager & Diversity Allocation Engine.
Enforces the 60% Proven Patterns / 30% Variations / 10% Pure Experiments content mix.
Maintains single-variable experiment records (Experiment A, B, C, D) to prevent confounding factors.
"""
import uuid
import random
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from core.models import ExperimentRecord, ContentPattern, Job

logger = logging.getLogger(__name__)


class ExperimentManager:
    """Designs, logs, and evaluates controlled content experiments."""

    def select_content_strategy(self, db: Session) -> Dict[str, Any]:
        """
        Applies the 60/30/10 diversity allocation to determine the generation strategy for the next Short.
        """
        rand_val = random.random()

        if rand_val < 0.60:
            strategy_type = "PROVEN_PATTERN"  # 60%
            description = "Using validated, high/medium-confidence historical categories and hook archetypes."
        elif rand_val < 0.90:
            strategy_type = "CONTROLLED_VARIATION"  # 30%
            description = "Testing a single variable change (e.g. new hook structure on a proven topic, or proven hook on a new category)."
        else:
            strategy_type = "PURE_EXPLORATION"  # 10%
            description = "Exploring an uncharted historical sub-genre or novel pacing format to discover new growth frontiers."

        return {
            "strategy_type": strategy_type,
            "description": description,
            "roll_value": round(rand_val, 3)
        }

    def plan_experiment(
        self,
        db: Session,
        experiment_type: str,
        title: str,
        hypothesis: str,
        control_variable: str,
        test_variable: str,
        control_job_id: Optional[str] = None
    ) -> ExperimentRecord:
        """
        Creates and logs a new controlled single-variable experiment.
        """
        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        exp = ExperimentRecord(
            id=exp_id,
            experiment_type=experiment_type,
            title=title,
            hypothesis=hypothesis,
            control_variable=control_variable,
            test_variable=test_variable,
            control_job_id=control_job_id,
            status="PLANNED",
            confidence="LOW_CONFIDENCE",
            created_at=datetime.utcnow()
        )
        db.add(exp)
        db.commit()
        logger.info(f"Planned Experiment [{experiment_type}]: '{title}' (Hypothesis: {hypothesis[:60]}...)")
        return exp

    def evaluate_experiment(self, db: Session, experiment_id: str, delta_apv: float, outcome_summary: str):
        """
        Concludes an experiment and records the measured delta and conclusion.
        """
        exp = db.query(ExperimentRecord).filter(ExperimentRecord.id == experiment_id).first()
        if not exp:
            return

        exp.status = "CONCLUDED"
        exp.measured_delta_apv = delta_apv
        exp.outcome_summary = outcome_summary
        exp.confidence = "MEDIUM_CONFIDENCE" if abs(delta_apv) >= 5.0 else "LOW_CONFIDENCE"
        exp.concluded_at = datetime.utcnow()
        db.commit()
        logger.info(f"Concluded Experiment {experiment_id}: Delta APV = {delta_apv:+.1f}%.")
