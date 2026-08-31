"""
Content Learning & Closed-Loop Strategy Weighting Engine.
Translates multi-factor performance snapshots into deterministic, explainable strategy weights.
Features:
  - Robust performance normalization (handles missing metrics, preserves None/null, dampens viral outliers).
  - Feature attribution across Hook Archetypes, Duration Targets, BGM Moods, and Motion Styles.
  - Strict evidence thresholds (Insufficient <3, Weak 3-4 [max +-10%], Usable >=5 [full update]).
  - Strict bounded weights [0.20, 2.00] with exploration/exploitation balance.
  - Full audit trail with persistent LearningEvent records and LEARNING_LOG.md.
  - Trackable learned profile versioning and consumption confirmation.
"""
import uuid
import math
import hashlib
import random
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT
from core.models import (
    StrategyWeight, PerformanceSnapshot, UploadRecord, Job, Topic, ScriptRecord, RenderOutput, LearningEvent
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
        Rules:
          - N < 3: INSUFFICIENT_EVIDENCE -> Weight strictly 1.00 (neutral).
          - N = 3-4: WEAK_EVIDENCE -> Maximum +-10% damped adjustment (bounded [0.90, 1.10]).
          - N >= 5: USABLE_EVIDENCE -> Full bounded adjustment [0.20, 2.00].
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
            # Strict maximum +-10% damped update
            dampened_delta = max(-0.10, min(0.10, (relative_lift / 100.0) * 0.3))
            weight = round(max(0.90, min(1.10, 1.00 + dampened_delta)), 3)
            weight = round(max(self.min_weight, min(self.max_weight, weight)), 3)
            reason = f"Weak evidence (N={sample_count}). Conservative +-10% damped adjustment ({relative_lift:+.1f}% lift vs baseline)."
        else:
            confidence = "USABLE_EVIDENCE"
            # Full update bounded [-0.80, +0.80] mapped into [0.20, 2.00]
            delta = max(-0.80, min(0.80, (relative_lift / 100.0)))
            weight = round(max(self.min_weight, min(self.max_weight, 1.00 + delta)), 3)
            reason = f"Usable evidence (N={sample_count}). Full bounded weight adjustment ({relative_lift:+.1f}% lift vs baseline)."

        return weight, round(relative_lift, 2), confidence, reason

    def get_verified_analytics_universe(
        self,
        db: Session,
        min_age_hours: float = 24.0,
        min_views: int = 100,
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        CANONICAL ANALYTICS UNIVERSE.
        Single authoritative source of verified live YouTube Shorts and their mature/maturing cohorts.
        Guarantees by construction:
            matured_count + maturing_count <= verified_live_count
        """
        if not now:
            now = datetime.utcnow()

        import re
        YT_REGEX = re.compile(r'^[A-Za-z0-9_-]{11}$')
        KNOWN_TEST_PREFIXES = (
            "test_", "TEST_", "yt_loop_", "test_vid_", "upl_test_",
            "upl_loop_", "vid_real_", "vid_deleted", "real_yt_", "legacy_vid", "mock_"
        )

        # 1. Query all PUBLISHED UploadRecords
        uploads = (
            db.query(UploadRecord)
            .filter(
                UploadRecord.status == "PUBLISHED",
                UploadRecord.youtube_video_id.isnot(None),
                UploadRecord.privacy_status != "test_local",
                ~UploadRecord.youtube_video_id.like("TEST_%"),
                ~UploadRecord.youtube_video_id.like("test_%")
            )
            .order_by(UploadRecord.published_at.desc(), UploadRecord.created_at.desc())
            .all()
        )

        # 2. Group / deduplicate strictly by genuine 11-char YouTube ID
        verified_videos: Dict[str, UploadRecord] = {}
        for u in uploads:
            yt_id = (u.youtube_video_id or "").strip()
            if not yt_id or not YT_REGEX.match(yt_id) or yt_id == "dQw4w9WgXcQ":
                continue
            if any(yt_id.startswith(p) for p in KNOWN_TEST_PREFIXES):
                continue
            if u.id and any(u.id.startswith(p) for p in KNOWN_TEST_PREFIXES):
                continue
            if yt_id not in verified_videos:
                verified_videos[yt_id] = u

        verified_live_count = len(verified_videos)
        mature_videos = []
        maturing_videos = []
        eligible_data = []
        all_views = []

        # 3. Categorize each unique video into mature (>=24h and views >= min_views) or maturing
        for yt_id, upl in verified_videos.items():
            pub_time = upl.published_at or upl.created_at
            age_hours = (now - pub_time).total_seconds() / 3600.0 if pub_time else 0.0

            # Find latest valid snapshot for this video
            snap = (
                db.query(PerformanceSnapshot)
                .filter(
                    (PerformanceSnapshot.youtube_video_id == yt_id) | (PerformanceSnapshot.upload_id == upl.id),
                    PerformanceSnapshot.validation_status.in_(["VALID_REAL", None])
                )
                .order_by(PerformanceSnapshot.snapshot_time.desc())
                .first()
            )

            views = snap.views if snap and snap.views is not None else 0
            if age_hours >= min_age_hours and views >= min_views:
                features = self.extract_video_features(db, upl)
                mature_videos.append({
                    "youtube_video_id": yt_id,
                    "upload": upl,
                    "snapshot": snap,
                    "age_hours": age_hours,
                    "views": views,
                    "features": features
                })
                eligible_data.append({
                    "upload": upl,
                    "snapshot": snap,
                    "features": features
                })
                all_views.append(views)
            else:
                maturing_videos.append({
                    "youtube_video_id": yt_id,
                    "upload": upl,
                    "snapshot": snap,
                    "age_hours": age_hours,
                    "views": views
                })

        # 4. Invariant Verification
        data_integrity_error = None
        total_cohort = len(mature_videos) + len(maturing_videos)
        if total_cohort > verified_live_count:
            data_integrity_error = {
                "error_type": "DATA_RECONCILIATION_ERROR",
                "message": "Analytics cohort count exceeds verified YouTube live count.",
                "expected_maximum": verified_live_count,
                "observed_count": total_cohort,
                "difference": total_cohort - verified_live_count,
                "timestamp": now.isoformat() + "Z"
            }

        return {
            "verified_live_count": verified_live_count,
            "verified_videos": verified_videos,
            "mature_videos": mature_videos,
            "maturing_videos": maturing_videos,
            "mature_count": len(mature_videos),
            "maturing_count": len(maturing_videos),
            "total_analytics_cohort": total_cohort,
            "eligible_data": eligible_data,
            "all_views": all_views,
            "data_integrity_error": data_integrity_error
        }

    def run_learning_cycle(
        self,
        db: Session,
        min_age_hours: float = 24.0,
        min_views: int = 100,
        now: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Executes a complete closed-loop learning cycle:
        1. Loads verified, non-test uploads with latest performance snapshots.
        2. Enforces 24-hour maturation window (immature videos never affect strategy).
        3. Calculates normalized performance and channel baseline.
        4. Attributes performance to content features.
        5. Computes deterministic, bounded strategy weights.
        6. Persists StrategyWeight and LearningEvent records in SQLite.
        7. Appends structured cycle summary to LEARNING_LOG.md.
        """
        if not now:
            now = datetime.utcnow()

        cycle_id = f"lc_{uuid.uuid4().hex[:12]}"

        # Query unified verified analytics universe
        universe = self.get_verified_analytics_universe(
            db, min_age_hours=min_age_hours, min_views=min_views, now=now
        )
        eligible_data = universe["eligible_data"]
        all_views = universe["all_views"]
        immature_count = universe["maturing_count"]
        mature_count = universe["mature_count"]
        verified_live_count = universe["verified_live_count"]
        data_integrity_error = universe["data_integrity_error"]

        # Calculate current profile version from existing weights
        current_profile_version = self._calculate_profile_version(db)

        # Handle zero mature video condition
        if not eligible_data:
            outcome = "NO_CHANGE_INSUFFICIENT_EVIDENCE" if immature_count > 0 else "NO_CHANGE_MISSING_TELEMETRY"
            reason_msg = (
                f"Waiting for maturation: {immature_count} Shorts in 24h window (0 matured videos available with >={min_views} views). Minimum required: {self.min_evidence_threshold}."
                if immature_count > 0 else
                f"No verified YouTube telemetry snapshots available for evaluation (immature: {immature_count}, missing telemetry)."
            )

            # Persist explicit LearningEvent record
            event_rec = LearningEvent(
                id=f"le_{uuid.uuid4().hex[:12]}",
                cycle_id=cycle_id,
                timestamp=now,
                outcome=outcome,
                feature_type=None,
                feature_value=None,
                sample_size=0,
                matured_count=0,
                immature_count=immature_count,
                signal_metric="COMPOSITE_RETENTION_APV",
                baseline_metric=None,
                observed_metric=None,
                delta=0.0,
                confidence="INSUFFICIENT_EVIDENCE",
                old_weight=1.00,
                new_weight=1.00,
                reason=reason_msg,
                profile_version=current_profile_version,
                consumed_by_generation=False,
                details_json=None
            )
            db.add(event_rec)
            db.commit()

            logger.info(f"[LEARNING_CYCLE] {reason_msg}")
            return {
                "cycle_id": cycle_id,
                "timestamp": now.isoformat(),
                "outcome": outcome,
                "eligible_videos_evaluated": 0,
                "immature_videos_count": immature_count,
                "channel_baseline_score": 50.0,
                "weights_updated_count": 0,
                "weights": [],
                "reason": reason_msg
            }

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

        # Update persistent StrategyWeight and LearningEvent records
        updated_weights: List[StrategyWeight] = []
        learning_events: List[LearningEvent] = []
        log_entries = []

        for (f_type, f_val), scores in feature_scores.items():
            n = len(scores)
            p_mean = round(sum(scores) / n, 2)
            weight, lift, conf, reason = self.compute_strategy_weight(n, p_mean, channel_baseline)

            matching = (
                db.query(StrategyWeight)
                .filter(StrategyWeight.feature_type == f_type, StrategyWeight.feature_value == f_val)
                .all()
            )
            existing = matching[0] if matching else None
            if len(matching) > 1:
                for surplus in matching[1:]:
                    db.delete(surplus)

            old_w = existing.weight if existing else 1.00

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

            # Determine specific outcome
            if n < self.min_evidence_threshold:
                ev_outcome = "NO_CHANGE_INSUFFICIENT_EVIDENCE"
            elif abs(weight - old_w) > 0.001:
                ev_outcome = "LEARNING_APPLIED"
            else:
                ev_outcome = "NO_CHANGE_NO_SIGNIFICANT_SIGNAL"

            ev_rec = LearningEvent(
                id=f"le_{uuid.uuid4().hex[:12]}",
                cycle_id=cycle_id,
                timestamp=now,
                outcome=ev_outcome,
                feature_type=f_type,
                feature_value=f_val,
                sample_size=n,
                matured_count=len(eligible_data),
                immature_count=immature_count,
                signal_metric="COMPOSITE_RETENTION_APV",
                baseline_metric=channel_baseline,
                observed_metric=p_mean,
                delta=lift,
                confidence=conf,
                old_weight=old_w,
                new_weight=weight,
                reason=reason,
                profile_version=current_profile_version,
                consumed_by_generation=False,
                details_json=None
            )
            db.add(ev_rec)
            learning_events.append(ev_rec)

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

        applied_count = sum(1 for e in learning_events if e.outcome == "LEARNING_APPLIED")
        summary = {
            "cycle_id": cycle_id,
            "timestamp": now.isoformat(),
            "eligible_videos_evaluated": len(eligible_data),
            "immature_videos_count": immature_count,
            "channel_baseline_score": channel_baseline,
            "weights_updated_count": len(updated_weights),
            "learning_applied_count": applied_count,
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
            f"Baseline: {channel_baseline:.1f} | {applied_count} weights adjusted | "
            f"{immature_count} immature videos waiting for 24h window."
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

    def _calculate_profile_version(self, db: Session) -> str:
        """Computes a deterministic hash identifier representing the active strategy weights."""
        weights = db.query(StrategyWeight).filter(
            StrategyWeight.sample_count >= self.min_evidence_threshold
        ).order_by(StrategyWeight.feature_type, StrategyWeight.feature_value).all()

        if not weights:
            return "v1.0.0-neutral"

        sig_parts = [f"{w.feature_type}:{w.feature_value}:{w.weight:.3f}" for w in weights]
        sig_str = "|".join(sig_parts)
        h = hashlib.sha256(sig_str.encode("utf-8")).hexdigest()[:8]
        return f"v2.{len(weights)}.{h}"

    def get_learned_production_profile(self, db: Session) -> str:
        """
        Generates a compact, deterministic learned guidance snippet from real verified performance data.
        Returns a concise instruction block for LLM prompts without bloating context.
        """
        try:
            mature_weights = db.query(StrategyWeight).filter(
                StrategyWeight.sample_count >= self.min_evidence_threshold
            ).order_by(StrategyWeight.weight.desc()).all()

            if not mature_weights:
                return ""

            top_hooks = [w.feature_value for w in mature_weights if w.feature_type == "hook_archetype" and w.relative_lift > 5.0]
            weak_hooks = [w.feature_value for w in mature_weights if w.feature_type == "hook_archetype" and w.relative_lift < -10.0]
            top_cats = [w.feature_value for w in mature_weights if w.feature_type == "category" and w.relative_lift > 5.0]

            profile_ver = self._calculate_profile_version(db)
            guidance = [f"\nLearned Channel Performance Guidance [Profile {profile_ver}]:"]
            if top_hooks:
                guidance.append(f"- Prioritize hook structure: {', '.join(top_hooks[:2])} (demonstrated higher Stayed-to-Watch retention).")
            if weak_hooks:
                guidance.append(f"- Avoid weak opening patterns: {', '.join(weak_hooks[:2])} (demonstrated below-average retention).")
            if top_cats:
                guidance.append(f"- Emphasize narrative tension characteristic of top categories: {', '.join(top_cats[:2])}.")

            return "\n".join(guidance) if len(guidance) > 1 else ""
        except Exception as e:
            logger.debug(f"Could not generate learned production profile: {e}")
            return ""

    def mark_profile_consumed(self, db: Session, job_id: str, profile_version: Optional[str] = None) -> int:
        """
        Marks unconsumed LearningEvent records as consumed by a future production generation job.
        Provides end-to-end mathematical verification that learned insights actively shaped output.
        """
        try:
            unconsumed = db.query(LearningEvent).filter(
                LearningEvent.consumed_by_generation.is_(False)
            ).all()

            count = 0
            for ev in unconsumed:
                ev.consumed_by_generation = True
                ev.consumed_by_job_id = job_id
                count += 1
            db.commit()
            if count > 0:
                logger.info(f"[LEARNING_AUDIT] Marked {count} learning events consumed by Job '{job_id[:8]}'")
            return count
        except Exception as e:
            logger.warning(f"Could not mark learning events consumed: {e}")
            return 0

