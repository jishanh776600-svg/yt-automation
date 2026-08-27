"""
Content Learning & Pattern Intelligence Engine.
Maintains persistent pattern database (Hooks, Categories, Durations, CTAs, Pacing).
Applies strict Anti-Overfitting Rules with Confidence Levels (LOW, MEDIUM, HIGH).
Prevents optimizing purely for vanity views by balancing retention and subscriber conversion.
"""
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from core.models import ContentPattern, VideoAnalysisRecord, PerformanceSnapshot, UploadRecord, Job, Topic, ScriptRecord

logger = logging.getLogger(__name__)


class LearningEngine:
    """Aggregates multi-video performance into persistent, confidence-weighted patterns."""

    def update_learning_database(self, db: Session) -> List[ContentPattern]:
        """
        Scans all completed video analyses and updates ContentPattern knowledge base.
        """
        analyses = db.query(VideoAnalysisRecord).filter(VideoAnalysisRecord.classification != "INSUFFICIENT_DATA").all()
        
        # Group stats by (pattern_type, pattern_key)
        pattern_aggregates: Dict[tuple, Dict[str, Any]] = {}

        def record_metric(ptype: str, pkey: str, apv: float, eng: float, subs: int, is_success: bool, is_underperform: bool):
            key = (ptype, pkey)
            if key not in pattern_aggregates:
                pattern_aggregates[key] = {
                    "sample_size": 0,
                    "apv_sum": 0.0,
                    "eng_sum": 0.0,
                    "subs_sum": 0,
                    "success_count": 0,
                    "underperform_count": 0
                }
            pattern_aggregates[key]["sample_size"] += 1
            pattern_aggregates[key]["apv_sum"] += apv
            pattern_aggregates[key]["eng_sum"] += eng
            pattern_aggregates[key]["subs_sum"] += subs
            if is_success:
                pattern_aggregates[key]["success_count"] += 1
            if is_underperform:
                pattern_aggregates[key]["underperform_count"] += 1

        for an in analyses:
            upl = db.query(UploadRecord).filter(UploadRecord.id == an.upload_id).first()
            if not upl:
                continue
            
            job = db.query(Job).filter(Job.id == upl.job_id).first() if upl.job_id else None
            topic = job.topic if job else None
            script = db.query(ScriptRecord).filter(ScriptRecord.topic_id == topic.id).first() if topic else None
            
            latest_snap = (
                db.query(PerformanceSnapshot)
                .filter(PerformanceSnapshot.upload_id == upl.id)
                .order_by(PerformanceSnapshot.snapshot_time.desc())
                .first()
            )
            if not latest_snap or latest_snap.views < 50:
                continue

            apv = latest_snap.average_view_percentage
            eng = latest_snap.engagement_rate
            subs = latest_snap.subscribers_gained
            is_success = (an.classification == "OUTPERFORMER")
            is_underperform = (an.classification == "UNDERPERFORMER")

            # 1. Track Category Pattern
            if topic and topic.category:
                record_metric("category", topic.category, apv, eng, subs, is_success, is_underperform)

            # 2. Track Duration Bracket Pattern
            if script and script.estimated_duration_sec:
                dur = script.estimated_duration_sec
                if dur < 22.5:
                    dur_bracket = "21.0-22.4s (Ultra Tight)"
                elif dur <= 23.8:
                    dur_bracket = "22.5-23.8s (Optimal Sweet Spot)"
                else:
                    dur_bracket = "23.9-25.0s (Narrative Rich)"
                record_metric("duration_bracket", dur_bracket, apv, eng, subs, is_success, is_underperform)

            # 3. Track Hook Archetype Pattern
            if script and script.hook:
                hook_lower = script.hook.lower()
                if "what if" in hook_lower or "imagine" in hook_lower:
                    hook_type = "Hypothetical Curiosity"
                elif any(w in hook_lower for w in ["in 1", "in 2", "on august", "on july", "on june"]):
                    hook_type = "Date/Time Anchor"
                elif any(w in hook_lower for w in ["war", "clash", "fight", "battle"]):
                    hook_type = "High-Stakes Conflict"
                elif any(w in hook_lower for w in ["vanish", "disappear", "mystery", "secret"]):
                    hook_type = "Unsolved Mystery"
                else:
                    hook_type = "Contradiction / Shock Fact"
                record_metric("hook_archetype", hook_type, apv, eng, subs, is_success, is_underperform)

        # Update ContentPattern database rows with Anti-Overfitting Confidence Rules
        updated_patterns = []
        for (ptype, pkey), data in pattern_aggregates.items():
            n = data["sample_size"]
            avg_apv = data["apv_sum"] / n if n > 0 else 0.0
            avg_eng = data["eng_sum"] / n if n > 0 else 0.0
            avg_subs = data["subs_sum"] / n if n > 0 else 0.0

            # Confidence Level determination
            if n == 1:
                confidence = "LOW_CONFIDENCE"
            elif 2 <= n <= 4:
                confidence = "MEDIUM_CONFIDENCE"
            else:
                confidence = "HIGH_CONFIDENCE"

            # Composite Score (0 - 100)
            score = (avg_apv * 0.50) + (min(avg_eng * 5.0, 30.0)) + (min(avg_subs * 10.0, 20.0))
            score = max(10.0, min(score, 100.0))

            status = "ACTIVE"
            if n >= 3 and score >= 70.0:
                status = "PROVEN"
            elif n >= 3 and score <= 38.0:
                status = "UNDERPERFORMING_REVISE"

            existing = (
                db.query(ContentPattern)
                .filter(ContentPattern.pattern_type == ptype, ContentPattern.pattern_key == pkey)
                .first()
            )

            if not existing:
                pattern_rec = ContentPattern(
                    id=f"pat_{uuid.uuid4().hex[:12]}",
                    pattern_type=ptype,
                    pattern_key=pkey,
                    description=f"{ptype} '{pkey}' tracked across {n} Shorts",
                    sample_size=n,
                    success_count=data["success_count"],
                    underperform_count=data["underperform_count"],
                    avg_percentage_viewed=avg_apv,
                    avg_engagement_rate=avg_eng,
                    avg_subscriber_conversion=avg_subs,
                    composite_effectiveness_score=score,
                    confidence=confidence,
                    status=status,
                    last_updated=datetime.utcnow()
                )
                db.add(pattern_rec)
                updated_patterns.append(pattern_rec)
            else:
                existing.sample_size = n
                existing.success_count = data["success_count"]
                existing.underperform_count = data["underperform_count"]
                existing.avg_percentage_viewed = avg_apv
                existing.avg_engagement_rate = avg_eng
                existing.avg_subscriber_conversion = avg_subs
                existing.composite_effectiveness_score = score
                existing.confidence = confidence
                existing.status = status
                existing.last_updated = datetime.utcnow()
                updated_patterns.append(existing)

        db.commit()
        logger.info(f"Updated {len(updated_patterns)} ContentPattern intelligence records.")
        return updated_patterns

    def get_strategy_guidance(self, db: Session) -> Dict[str, Any]:
        """Returns actionable intelligence for topic and script generation."""
        patterns = db.query(ContentPattern).all()
        
        best_categories = sorted(
            [p for p in patterns if p.pattern_type == "category"],
            key=lambda x: x.composite_effectiveness_score,
            reverse=True
        )
        best_hooks = sorted(
            [p for p in patterns if p.pattern_type == "hook_archetype"],
            key=lambda x: x.composite_effectiveness_score,
            reverse=True
        )
        best_durations = sorted(
            [p for p in patterns if p.pattern_type == "duration_bracket"],
            key=lambda x: x.composite_effectiveness_score,
            reverse=True
        )

        return {
            "top_categories": [p.pattern_key for p in best_categories[:3]],
            "weak_categories": [p.pattern_key for p in best_categories if p.status == "UNDERPERFORMING_REVISE"],
            "top_hooks": [p.pattern_key for p in best_hooks[:3]],
            "optimal_duration_bracket": best_durations[0].pattern_key if best_durations else "22.5-23.8s (Optimal Sweet Spot)",
            "total_patterns_tracked": len(patterns)
        }
