"""
Freshness & Temporal Velocity Scoring Engine.
Evaluates event recency, coverage velocity, and lifecycle stage
to prioritize breaking and rapidly developing world events.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import logging
from intelligence.models import EventCluster

logger = logging.getLogger(__name__)


class FreshnessScorer:
    """Calculates deterministic freshness scores and event lifecycle classifications."""

    def __init__(
        self,
        breaking_hours: float = 3.0,
        developing_hours: float = 12.0,
        fresh_hours: float = 24.0,
        recent_hours: float = 48.0,
        maturing_hours: float = 72.0
    ):
        self.breaking_hours = breaking_hours
        self.developing_hours = developing_hours
        self.fresh_hours = fresh_hours
        self.recent_hours = recent_hours
        self.maturing_hours = maturing_hours

    def calculate_age_hours(self, pub_date: Optional[datetime], reference_time: Optional[datetime] = None) -> float:
        """Computes age in hours from publication timestamp to reference time (defaults to utcnow)."""
        if not pub_date:
            # If no timestamp is provided, assume moderately fresh (e.g. 18 hours)
            return 18.0
        ref = reference_time or datetime.utcnow()
        # Ensure naive UTC comparison
        clean_pub = pub_date.replace(tzinfo=None) if pub_date.tzinfo else pub_date
        clean_ref = ref.replace(tzinfo=None) if ref.tzinfo else ref

        delta = clean_ref - clean_pub
        hours = delta.total_seconds() / 3600.0
        return max(0.0, hours)

    def evaluate_freshness(self, cluster: EventCluster, reference_time: Optional[datetime] = None) -> Tuple[float, str]:
        """
        Evaluates an EventCluster's freshness score (0.0 to 100.0) and temporal classification.
        Returns (freshness_score, lifecycle_classification).
        """
        most_recent_pub = cluster.last_published_at or cluster.first_published_at
        age_hours = self.calculate_age_hours(most_recent_pub, reference_time=reference_time)

        # 1. Base Age Score
        if age_hours <= self.breaking_hours:
            base_score = 100.0
            classification = "BREAKING"
        elif age_hours <= self.developing_hours:
            # Linear decay from 100 to 90
            ratio = (age_hours - self.breaking_hours) / (self.developing_hours - self.breaking_hours)
            base_score = 100.0 - (ratio * 10.0)
            classification = "DEVELOPING"
        elif age_hours <= self.fresh_hours:
            # Linear decay from 90 to 80
            ratio = (age_hours - self.developing_hours) / (self.fresh_hours - self.developing_hours)
            base_score = 90.0 - (ratio * 10.0)
            classification = "FRESH"
        elif age_hours <= self.recent_hours:
            # Linear decay from 80 to 60
            ratio = (age_hours - self.fresh_hours) / (self.recent_hours - self.fresh_hours)
            base_score = 80.0 - (ratio * 20.0)
            classification = "RECENT"
        elif age_hours <= self.maturing_hours:
            # Linear decay from 60 to 40
            ratio = (age_hours - self.recent_hours) / (self.maturing_hours - self.recent_hours)
            base_score = 60.0 - (ratio * 20.0)
            classification = "MATURING"
        else:
            # Exponential decay below 40 for older background developments
            decay_factor = max(0.1, 1.0 - ((age_hours - self.maturing_hours) / 120.0))
            base_score = max(15.0, 40.0 * decay_factor)
            classification = "BACKGROUND"

        # 2. Coverage Velocity Multiplier
        # If multiple sources broke coverage within a short window, boost score by up to 10%
        source_count = len(cluster.source_domains)
        if source_count >= 3 and age_hours <= self.fresh_hours:
            velocity_bonus = 5.0
            if source_count >= 4 and age_hours <= self.developing_hours:
                velocity_bonus = 10.0
            base_score = min(100.0, base_score + velocity_bonus)

        cluster.freshness_score = round(base_score, 2)
        return cluster.freshness_score, classification
