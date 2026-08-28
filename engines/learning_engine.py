"""
Content Learning & Closed-Loop Strategy Weighting Engine.
Translates multi-factor performance snapshots into deterministic, explainable strategy weights.
Features:
  - Robust performance normalization (handles missing metrics, zero-values, and dampens viral outliers).
  - Feature attribution across Hook Archetypes, Duration Targets, BGM Moods, and Motion Styles.
  - Configurable evidence thresholds (Insufficient <3, Weak 3-4, Usable >=5).
  - Bounded weights [0.20, 2.00] with exploration/exploitation balance.
  - Learning-cycle idempotency (deterministic weights, no runaway compounding).
  - Persistent SQLite StrategyWeight storage and structured LEARNING_LOG.md appending.
"""
import uuid
import math
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT
from core.models import (
    StrategyWeight, PerformanceSnapshot, UploadRecord, Job, Topic, ScriptRecord, RenderOutput
)

logger = logging.getLogger(__name__)


class LearningEngine:
    """Deterministic closed-loop learning engine that updates content strategy weights."""

    def __init__(
        self,
        min_evidence_threshold: int = 3,
        usable_evidence_threshold: int = 5,
        min_weight: float = 0.20,
        max_weight: float = 2.00,
        learning_log_path: Optional[Path] = None
    ):
        self.min_evidence_threshold = min_evidence_threshold
        self.usable_evidence_threshold = usable_evidence_threshold
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.learning_log_path = learning_log_path or (PROJECT_ROOT / "data" / "LEARNING_LOG.md")

    def normalize_performance(self, snapshot: PerformanceSnapshot, channel_median_views: float = 1000.0) -> float:
        """
        Calculates a deterministic normalized performance score (0.0 to 100.0).
        Formula:
          Score = (0.45 * APV) + (0.35 * EngagementFactor) + (0.20 * LogViewFactor)
        Safeguards:
          - Missing/None metrics default to 0.0 or safe baselines.
          - Zero division is mathematically impossible.
          - Logarithmic scaling dampens single viral outliers.
        """
        if not snapshot:
            return 50.0

        views = max(0, snapshot.views or 0)
        apv = max(0.0, min(100.0, float(snapshot.average_view_percentage or 0.0)))
        eng = max(0.0, float(snapshot.engagement_rate or 0.0))

        # 1. Retention / APV Component (45 pts max)
        # If APV was not available via Analytics API, fallback to engagement-derived estimate
        if apv == 0.0 and views > 0:
            apv_component = min(100.0, max(20.0, eng * 10.0))
        else:
            apv_component = apv

        # 2. Engagement Rate Component (35 pts max: 5% engagement = 50 pts, 10% = 100 pts)
        eng_component = min(100.0, eng * 10.0)

        # 3. Log-Dampened View Component (20 pts max)
        # Uses log ratio vs channel median to prevent 1M view video from scoring 10000 pts
        ref_median = max(100.0, channel_median_views)
        if views > 0:
            log_ratio = math.log(1.0 + views) / math.log(1.0 + ref_median)
            view_component = min(100.0, max(0.0, log_ratio * 50.0))
        else:
            view_component = 0.0

        # Composite score
        composite = (0.45 * apv_component) + (0.35 * eng_component) + (0.20 * view_component)
        
        # Check for NaN / Infinity safeguards
        if math.isnan(composite) or math.isinf(composite):
            return 50.0

        return round(max(0.0, min(100.0, composite)), 2)

    def extract_video_features(self, db: Session, upload: UploadRecord) -> Dict[str, Optional[str]]:
        """
        Extracts strategic features (Hook, Duration, BGM, Motion, Category) from production records.
        """
        features: Dict[str, Optional[str]] = {
            "hook_archetype": None,
            "duration_target": None,
            "bgm_mood": None,
            "motion_style": None,
            "category": None
        }

        if not upload.job_id:
            return features

        job = db.query(Job).filter(Job.id == upload.job_id).first()
        if not job:
            return features

        # Topic & Category
        if job.topic:
            features["category"] = job.topic.category

        # Script Metadata
        script = db.query(ScriptRecord).filter(ScriptRecord.topic_id == job.topic_id).first() if job.topic_id else None
        if script:
            features["hook_archetype"] = script.hook_archetype
            features["duration_target"] = script.duration_target

        # Render Metadata
        render = db.query(RenderOutput).filter(RenderOutput.job_id == job.id).order_by(RenderOutput.created_at.desc()).first()
        if render:
            features["bgm_mood"] = render.bgm_mood
            features["motion_style"] = render.motion_style

        # Fallback to ExperimentRecord if any strategic feature is missing
        from core.models import ExperimentRecord
        exp = db.query(ExperimentRecord).filter(
            (ExperimentRecord.upload_id == upload.id) | 
            (ExperimentRecord.job_id == upload.job_id)
        ).first()
        if exp:
            features["hook_archetype"] = features["hook_archetype"] or exp.hook_archetype
            features["duration_target"] = features["duration_target"] or exp.duration_target
            features["bgm_mood"] = features["bgm_mood"] or exp.bgm_mood
            features["motion_style"] = features["motion_style"] or exp.motion_style
            features["category"] = features["category"] or exp.category

        return features

    def compute_strategy_weight(
        self,
        sample_count: int,
        performance_mean: float,
        baseline_performance: float
    ) -> Tuple[float, float, str, str]:
        """
        Computes deterministic, bounded strategy weight from sample count and relative lift.
        Returns: (weight, relative_lift, confidence_level, reason)
        """
        safe_baseline = max(1.0, baseline_performance)
        relative_lift = ((performance_mean - safe_baseline) / safe_baseline) * 100.0

        if sample_count < self.min_evidence_threshold:
            confidence = "INSUFFICIENT_EVIDENCE"
            weight = 1.00
            reason = f"Insufficient evidence (N={sample_count} < {self.min_evidence_threshold}). Weight held neutral at 1.00."
        elif sample_count < self.usable_evidence_threshold:
            confidence = "WEAK_EVIDENCE"
            # Dampened 50% update, bounded [-0.25, +0.25]
            dampened_delta = max(-0.25, min(0.25, (relative_lift / 100.0) * 0.5))
            weight = round(max(self.min_weight, min(self.max_weight, 1.00 + dampened_delta)), 3)
            reason = f"Weak evidence (N={sample_count}). Conservative weight adjustment ({relative_lift:+.1f}% lift)."
        else:
            confidence = "USABLE_EVIDENCE"
            # Full update, bounded [-0.50, +0.50]
            dampened_delta = max(-0.50, min(0.50, (relative_lift / 100.0)))
            weight = round(max(self.min_weight, min(self.max_weight, 1.00 + dampened_delta)), 3)
            reason = f"Usable evidence (N={sample_count}). Full weight adjustment ({relative_lift:+.1f}% lift)."

        return weight, round(relative_lift, 2), confidence, reason

    def run_learning_cycle(
        self,
        db: Session,
        min_age_hours: float = 24.0,
        min_views: int = 100,
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Executes a complete closed-loop learning cycle:
        1. Loads mature, non-test uploads with latest performance snapshots.
        2. Calculates normalized performance and channel baseline.
        3. Attributes performance to content features.
        4. Computes deterministic, bounded strategy weights.
        5. Persists StrategyWeight rows into SQLite.
        6. Appends structured cycle summary to LEARNING_LOG.md.
        """
        if not now:
            now = datetime.utcnow()

        # Query all uploads excluding mock/test IDs
        uploads = db.query(UploadRecord).filter(
            UploadRecord.youtube_video_id.isnot(None),
            ~UploadRecord.youtube_video_id.like("TEST_%")
        ).all()

        eligible_data = []
        all_views = []

        for upl in uploads:
            # Check maturation
            pub_time = upl.published_at or upl.created_at
            if pub_time:
                age_hours = (now - pub_time).total_seconds() / 3600.0
                if age_hours < min_age_hours:
                    continue

            # Get latest snapshot
            snap = (
                db.query(PerformanceSnapshot)
                .filter(PerformanceSnapshot.upload_id == upl.id)
                .order_by(PerformanceSnapshot.snapshot_time.desc())
                .first()
            )
            if not snap or (snap.views or 0) < min_views:
                continue

            all_views.append(snap.views)
            features = self.extract_video_features(db, upl)
            eligible_data.append({
                "upload": upl,
                "snapshot": snap,
                "features": features
            })

        # Determine channel median views
        sorted_views = sorted(all_views)
        median_views = sorted_views[len(sorted_views) // 2] if sorted_views else 1000.0

        # Calculate normalized score for each eligible video
        video_scores = []
        for item in eligible_data:
            score = self.normalize_performance(item["snapshot"], channel_median_views=median_views)
            item["score"] = score
            video_scores.append(score)

        # Baseline performance across channel
        channel_baseline = (sum(video_scores) / len(video_scores)) if video_scores else 50.0
        channel_baseline = round(channel_baseline, 2)

        # Group scores by (feature_type, feature_value)
        feature_scores: Dict[Tuple[str, str], List[float]] = {}
        for item in eligible_data:
            score = item["score"]
            for f_type, f_val in item["features"].items():
                if f_val and str(f_val).strip() and str(f_val).upper() != "NONE":
                    key = (f_type, str(f_val).strip())
                    if key not in feature_scores:
                        feature_scores[key] = []
                    feature_scores[key].append(score)

        # Update persistent StrategyWeight records
        updated_weights: List[StrategyWeight] = []
        log_entries = []

        for (f_type, f_val), scores in feature_scores.items():
            n = len(scores)
            p_mean = round(sum(scores) / n, 2)
            weight, lift, conf, reason = self.compute_strategy_weight(n, p_mean, channel_baseline)

            existing = (
                db.query(StrategyWeight)
                .filter(StrategyWeight.feature_type == f_type, StrategyWeight.feature_value == f_val)
                .first()
            )

            if not existing:
                sw_rec = StrategyWeight(
                    id=f"sw_{uuid.uuid4().hex[:12]}",
                    feature_type=f_type,
                    feature_value=f_val,
                    weight=weight,
                    sample_count=n,
                    performance_mean=p_mean,
                    baseline_performance=channel_baseline,
                    relative_lift=lift,
                    confidence_level=conf,
                    last_updated=now,
                    update_reason=reason
                )
                db.add(sw_rec)
                updated_weights.append(sw_rec)
            else:
                existing.weight = weight
                existing.sample_count = n
                existing.performance_mean = p_mean
                existing.baseline_performance = channel_baseline
                existing.relative_lift = lift
                existing.confidence_level = conf
                existing.last_updated = now
                existing.update_reason = reason
                updated_weights.append(existing)

            log_entries.append({
                "type": f_type,
                "value": f_val,
                "samples": n,
                "lift": lift,
                "confidence": conf,
                "weight": weight,
                "reason": reason
            })

        db.commit()

        # Append to LEARNING_LOG.md
        self._append_learning_cycle_log(
            now=now,
            videos_count=len(eligible_data),
            baseline=channel_baseline,
            entries=log_entries
        )

        summary = {
            "timestamp": now.isoformat(),
            "eligible_videos_evaluated": len(eligible_data),
            "channel_baseline_score": channel_baseline,
            "weights_updated_count": len(updated_weights),
            "weights": [
                {
                    "feature_type": w.feature_type,
                    "feature_value": w.feature_value,
                    "weight": w.weight,
                    "sample_count": w.sample_count,
                    "relative_lift": w.relative_lift,
                    "confidence_level": w.confidence_level
                }
                for w in updated_weights
            ]
        }

        logger.info(
            f"Learning Cycle Complete: {len(eligible_data)} mature videos evaluated | "
            f"Baseline: {channel_baseline:.1f} | {len(updated_weights)} strategy weights updated."
        )
        return summary

    def get_strategy_recommendation(
        self,
        db: Session,
        explore_prob: float = 0.20,
        deterministic: bool = False
    ) -> Dict[str, Any]:
        """
        Exposes structured strategy recommendations balancing exploitation of proven winners
        and exploration of under-tested features.
        """
        all_weights = db.query(StrategyWeight).all()
        by_type: Dict[str, List[StrategyWeight]] = {}
        for w in all_weights:
            if w.feature_type not in by_type:
                by_type[w.feature_type] = []
            by_type[w.feature_type].append(w)

        recommendations = {}
        reasoning = {}

        feature_defaults = {
            "hook_archetype": "DATE_TIME_ANCHOR",
            "duration_target": "SWEET_SPOT",
            "bgm_mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
            "motion_style": "DYNAMIC_ZOOM_PAN",
            "category": "Unusual Wars"
        }

        for f_type, default_val in feature_defaults.items():
            candidates = by_type.get(f_type, [])
            if not candidates:
                recommendations[f_type] = default_val
                reasoning[f_type] = "Default (no historical strategy weights recorded yet)."
                continue

            # Sort by weight descending
            sorted_candidates = sorted(candidates, key=lambda x: x.weight, reverse=True)
            best = sorted_candidates[0]

            if deterministic or random.random() > explore_prob or len(sorted_candidates) == 1:
                # Exploitation
                recommendations[f_type] = best.feature_value
                reasoning[f_type] = (
                    f"Exploitation: Highest weight {best.weight:.2f} "
                    f"({best.relative_lift:+.1f}% lift, N={best.sample_count}, {best.confidence_level})"
                )
            else:
                # Exploration: Weighted random choice among all candidates
                weights_list = [max(0.1, c.weight) for c in sorted_candidates]
                chosen = random.choices(sorted_candidates, weights=weights_list, k=1)[0]
                recommendations[f_type] = chosen.feature_value
                reasoning[f_type] = (
                    f"Exploration ({explore_prob*100:.0f}% chance): Selected '{chosen.feature_value}' "
                    f"(Weight: {chosen.weight:.2f}, N={chosen.sample_count})"
                )

        return {
            "recommendations": recommendations,
            "reasoning": reasoning,
            "timestamp": datetime.utcnow().isoformat(),
            "exploration_probability": explore_prob
        }

    def _append_learning_cycle_log(self, now: datetime, videos_count: int, baseline: float, entries: List[Dict[str, Any]]):
        """Appends a structured markdown record to data/LEARNING_LOG.md."""
        try:
            self.learning_log_path.parent.mkdir(parents=True, exist_ok=True)
            if not self.learning_log_path.exists():
                header = "# Closed-Loop Strategy Learning Log\n\n"
                self.learning_log_path.write_text(header, encoding="utf-8")

            date_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            lines = [
                f"\n## Learning Cycle — {date_str}\n",
                f"- **Mature Videos Evaluated**: {videos_count}",
                f"- **Channel Performance Baseline**: {baseline:.2f}/100\n",
                "| Feature Type | Feature Value | Samples | Rel Lift | Confidence | Weight | Update Reason |",
                "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |"
            ]

            for e in sorted(entries, key=lambda x: (x["type"], -x["weight"])):
                lines.append(
                    f"| `{e['type']}` | **{e['value']}** | {e['samples']} | `{e['lift']:+.1f}%` | "
                    f"`{e['confidence']}` | **{e['weight']:.2f}** | {e['reason']} |"
                )

            with open(self.learning_log_path, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

        except Exception as log_err:
            logger.warning(f"Could not append to LEARNING_LOG.md: {log_err}")
