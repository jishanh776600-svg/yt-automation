"""
Freshness & Temporal Velocity Scoring Engine.
Evaluates event recency, coverage velocity, and lifecycle stage
to prioritize breaking and rapidly developing world events.
"""
import calendar
import time
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, Tuple, Union
import logging
from dateutil import parser as date_parser

from intelligence.models import EventCluster
from core.discovery_profile import DiscoveryProfile, get_active_discovery_profile

logger = logging.getLogger(__name__)


class FreshnessTier(str, Enum):
    TIER_1 = "TIER_1"  # 0–6 hours (Breaking/Immediate)
    TIER_2 = "TIER_2"  # 6–24 hours (Daily Cycle)
    TIER_3 = "TIER_3"  # 24–72 hours (Recent Context)
    TIER_4 = "TIER_4"  # >72 hours (Older Background / Context)


def normalize_timestamp(
    raw_timestamp: Union[str, int, float, datetime, time.struct_time, None],
    now_utc: Optional[datetime] = None
) -> Optional[datetime]:
    """
    Normalizes any input timestamp to a UTC datetime (naive UTC representation).
    Handles:
      - timezone offsets (+02:00, -0500, EDT, GMT, etc.)
      - missing timezone (assumed UTC)
      - epoch timestamps (int/float, including milliseconds)
      - time.struct_time (feedparser)
      - malformed strings (returns None gracefully)
      - future timestamps (clamped to now_utc if exceeding 15 min clock skew)
      - impossible dates
    """
    if raw_timestamp is None:
        return None

    if now_utc is None:
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    elif now_utc.tzinfo is not None:
        now_utc = now_utc.astimezone(timezone.utc).replace(tzinfo=None)

    parsed_dt: Optional[datetime] = None

    # Case 1: time.struct_time (feedparser parsed dates)
    if isinstance(raw_timestamp, time.struct_time):
        try:
            timestamp_epoch = calendar.timegm(raw_timestamp)
            parsed_dt = datetime.fromtimestamp(timestamp_epoch, tz=timezone.utc).replace(tzinfo=None)
        except Exception as e:
            logger.warning(f"Error converting struct_time {raw_timestamp}: {e}")
            return None

    # Case 2: Numeric timestamp (int or float)
    elif isinstance(raw_timestamp, (int, float)):
        num_val = float(raw_timestamp)
        num_str = str(int(num_val)) if num_val.is_integer() else ""
        # Check if 14-digit GDELT integer: YYYYMMDDHHMMSS
        if len(num_str) == 14 and 19000000000000 <= int(num_str) <= 21000000000000:
            try:
                parsed_dt = datetime.strptime(num_str, "%Y%m%d%H%M%S")
            except ValueError:
                pass
        # Check if 8-digit YYYYMMDD integer
        elif len(num_str) == 8 and 19000000 <= int(num_str) <= 21000000:
            try:
                parsed_dt = datetime.strptime(num_str, "%Y%m%d")
            except ValueError:
                pass
        if parsed_dt is None:
            try:
                if num_val > 1e11:
                    num_val /= 1000.0
                parsed_dt = datetime.fromtimestamp(num_val, tz=timezone.utc).replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Error converting numeric timestamp {raw_timestamp}: {e}")
                return None

    # Case 3: Already a datetime
    elif isinstance(raw_timestamp, datetime):
        if raw_timestamp.tzinfo is not None:
            parsed_dt = raw_timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            parsed_dt = raw_timestamp

    # Case 4: String representation
    elif isinstance(raw_timestamp, str):
        clean_str = raw_timestamp.strip()
        if not clean_str:
            return None

        # Numeric string handling
        if clean_str.isdigit():
            if len(clean_str) == 14 and 19000000000000 <= int(clean_str) <= 21000000000000:
                try:
                    parsed_dt = datetime.strptime(clean_str, "%Y%m%d%H%M%S")
                except ValueError:
                    pass
            elif len(clean_str) == 8 and 19000000 <= int(clean_str) <= 21000000:
                try:
                    parsed_dt = datetime.strptime(clean_str, "%Y%m%d")
                except ValueError:
                    pass
            elif len(clean_str) in (10, 11):
                try:
                    parsed_dt = datetime.fromtimestamp(float(clean_str), tz=timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass
            elif len(clean_str) in (12, 13):
                try:
                    parsed_dt = datetime.fromtimestamp(float(clean_str) / 1000.0, tz=timezone.utc).replace(tzinfo=None)
                except Exception:
                    pass

        if parsed_dt is None:
            try:
                dt = date_parser.parse(clean_str)
                if dt.tzinfo is not None:
                    parsed_dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    parsed_dt = dt
            except (ValueError, TypeError, OverflowError) as e:
                logger.warning(f"Malformed timestamp string '{raw_timestamp}': {e}")
                return None
    else:
        return None

    if parsed_dt is None:
        return None

    if parsed_dt.year < 1900 or parsed_dt.year > 2100:
        logger.warning(f"Impossible date year detected: {parsed_dt}")
        return None

    allowed_drift = timedelta(minutes=15)
    if parsed_dt > now_utc + allowed_drift:
        logger.warning(f"Future timestamp detected ({parsed_dt} > now {now_utc}). Clamping to now.")
        parsed_dt = now_utc

    return parsed_dt


def classify_freshness(
    published_utc: Optional[datetime],
    reference_time: Optional[datetime] = None
) -> Tuple[FreshnessTier, float, bool]:
    """
    Classifies an article into recency tiers.
    Returns: (FreshnessTier, age_hours, is_production_fresh)
    TIER 1 (0-6h) and TIER 2 (6-24h) are approved for current-affairs production.
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc).replace(tzinfo=None)
    elif reference_time.tzinfo is not None:
        reference_time = reference_time.astimezone(timezone.utc).replace(tzinfo=None)

    if published_utc is None:
        return FreshnessTier.TIER_4, 9999.0, False

    if published_utc.tzinfo is not None:
        published_utc = published_utc.astimezone(timezone.utc).replace(tzinfo=None)

    age_seconds = (reference_time - published_utc).total_seconds()
    age_hours = max(0.0, age_seconds / 3600.0)

    if age_hours <= 6.0:
        return FreshnessTier.TIER_1, round(age_hours, 2), True
    elif age_hours <= 24.0:
        return FreshnessTier.TIER_2, round(age_hours, 2), True
    elif age_hours <= 72.0:
        return FreshnessTier.TIER_3, round(age_hours, 2), False
    else:
        return FreshnessTier.TIER_4, round(age_hours, 2), False


def calculate_freshness_score(
    published_utc: Optional[datetime],
    reference_time: Optional[datetime] = None
) -> float:
    """
    Computes a 0.0 to 100.0 score based on article recency.
    TIER 1 (0-6h): 85-100
    TIER 2 (6-24h): 70-85
    TIER 3 (24-72h): 30-70
    TIER 4 (>72h): 0-30
    """
    tier, age_hours, _ = classify_freshness(published_utc, reference_time)
    if tier == FreshnessTier.TIER_1:
        score = 100.0 - (age_hours / 6.0) * 15.0
    elif tier == FreshnessTier.TIER_2:
        score = 85.0 - ((age_hours - 6.0) / 18.0) * 15.0
    elif tier == FreshnessTier.TIER_3:
        score = 70.0 - ((age_hours - 24.0) / 48.0) * 40.0
    else:
        score = max(0.0, 30.0 - min(30.0, (age_hours - 72.0) / 72.0 * 30.0))

    return round(score, 2)


class FreshnessScorer:
    """Calculates deterministic freshness scores and event lifecycle classifications."""

    def __init__(
        self,
        breaking_hours: Optional[float] = None,
        developing_hours: Optional[float] = None,
        fresh_hours: Optional[float] = None,
        recent_hours: Optional[float] = None,
        maturing_hours: Optional[float] = None,
        profile: Optional[DiscoveryProfile] = None
    ):
        prof = profile or get_active_discovery_profile()
        self.breaking_hours = breaking_hours if breaking_hours is not None else prof.breaking_hours
        self.developing_hours = developing_hours if developing_hours is not None else prof.developing_hours
        self.fresh_hours = fresh_hours if fresh_hours is not None else prof.fresh_hours
        self.recent_hours = recent_hours if recent_hours is not None else prof.recent_hours
        self.maturing_hours = maturing_hours if maturing_hours is not None else prof.maturing_hours

    def calculate_age_hours(self, pub_date: Optional[datetime], reference_time: Optional[datetime] = None) -> float:
        """
        Computes age in hours from publication timestamp to reference time (defaults to utcnow).
        Deterministic future timestamp defense:
        - Minor future clock skew (<= 1 hour): clamped to 0.5 hours.
        - Excessive future dates (> 1 hour ahead): penalized to 72.0 hours (maturing) to prevent artificial inflation.
        """
        if not pub_date:
            # If no timestamp is provided, assume moderately fresh (e.g. 18 hours)
            return 18.0
        ref = reference_time or datetime.utcnow()
        # Ensure naive UTC comparison
        clean_pub = pub_date.replace(tzinfo=None) if pub_date.tzinfo else pub_date
        clean_ref = ref.replace(tzinfo=None) if ref.tzinfo else ref

        delta = clean_ref - clean_pub
        hours = delta.total_seconds() / 3600.0

        if hours < 0.0:
            future_offset = abs(hours)
            if future_offset <= 1.0:
                return 0.5
            else:
                logger.warning(f"[FRESHNESS] Article published_at is {future_offset:.1f}h in the future ({clean_pub}). Penalizing.")
                return 72.0

        return hours

    def evaluate_freshness(self, cluster: EventCluster, reference_time: Optional[datetime] = None) -> Tuple[float, str]:
        """
        Evaluates an EventCluster's freshness score (0.0 to 100.0) and temporal classification.
        Returns (freshness_score, lifecycle_classification).
        """
        # The event's freshness must be based on the underlying event timestamp where possible
        # (event_occurred_at or first_published_at), not simply the newest article publication time.
        # A newly published article about a three-week-old event must not become breaking.
        event_time = getattr(cluster, "event_occurred_at", None) or cluster.first_published_at or cluster.last_published_at
        age_hours = self.calculate_age_hours(event_time, reference_time=reference_time)

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
