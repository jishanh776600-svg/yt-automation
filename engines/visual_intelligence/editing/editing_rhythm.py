"""
Editing Rhythm & Visual Pacing Engine.
Controls the temporal heartbeat of the video edit:
- Dynamic shot duration allocation based on story arc (Hook -> Setup -> Escalation -> Climax -> Twist)
- Urgency and information-density scaling
- Minimum and maximum duration constraints (1.8s - 4.2s per shot)
- Visual change rate and emphasis timing
"""
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class EditingRhythmEngine:
    """
    Directorial rhythm controller. Replaces monotonous uniform shot durations
    with an expressive, story-calibrated pacing curve.
    """

    MIN_SHOT_DURATION = 1.8         # Minimum duration for comprehension in Shorts
    MAX_SHOT_DURATION = 4.2         # Maximum duration before visual retention drops
    TARGET_AVG_DURATION = 2.6       # Sweet spot for high-retention vertical video

    def calculate_pacing_curve(
        self,
        total_duration: float,
        shot_count: int,
        narrative_roles: List[str],
        profile_urgency: str = "BALANCED",
        information_density: str = "MEDIUM"
    ) -> List[float]:
        """
        Allocates exact durations (seconds) across all shots so the sum
        equals total_duration, while honoring narrative weight and urgency.
        """
        if shot_count <= 0:
            return []
        if shot_count == 1:
            return [round(total_duration, 2)]

        # 1. Base weights per narrative stage
        weights: List[float] = []
        for role in narrative_roles:
            r = role.upper()
            if r == "HOOK":
                w = 0.85        # Punchy, fast hook
            elif r in ("SETUP", "CONTEXT"):
                w = 1.15        # Slightly longer to absorb historical scene
            elif r == "ESCALATION":
                w = 0.95        # Building speed
            elif r in ("REVEAL", "IMPACT", "CLIMAX"):
                w = 0.90        # Punchy impact
            elif r in ("OUTRO", "LOOP_TWIST"):
                w = 1.05        # Clear final takeaway
            else:
                w = 1.00
            weights.append(w)

        # 2. Adjust for urgency profile
        if profile_urgency in ("HIGH", "FAST_PACED", "FAST_BREAKING"):
            # Compress hook and escalation even further
            weights = [w * 0.9 if idx in (0, len(weights)-2) else w for idx, w in enumerate(weights)]
        elif information_density in ("HIGH", "ANALYTICAL"):
            # Expand middle documentary/data shots
            weights = [w * 1.1 if idx in range(1, len(weights)-1) else w for idx, w in enumerate(weights)]

        # 3. Normalize weights to total_duration
        total_weight = sum(weights)
        raw_durations = [(w / total_weight) * total_duration for w in weights]

        # 4. Clamp between MIN and MAX constraints
        clamped = []
        for d in raw_durations:
            c = max(self.MIN_SHOT_DURATION, min(self.MAX_SHOT_DURATION, d))
            clamped.append(c)

        # 5. Final adjustment pass to guarantee exact total_duration sum
        diff = total_duration - sum(clamped)
        # Distribute remainder across shots that aren't at hard bounds
        flexible_indices = [
            i for i, d in enumerate(clamped)
            if self.MIN_SHOT_DURATION < d < self.MAX_SHOT_DURATION
        ] or list(range(len(clamped)))

        adj_per_shot = diff / float(len(flexible_indices))
        for idx in flexible_indices:
            clamped[idx] += adj_per_shot

        # Round to 2 decimal places and assign residual rounding difference to last shot
        final_durations = [round(d, 2) for d in clamped]
        final_diff = round(total_duration - sum(final_durations), 2)
        final_durations[-1] = round(final_durations[-1] + final_diff, 2)

        logger.debug(
            f"Calculated pacing curve for {shot_count} shots (Total: {total_duration:.1f}s, "
            f"Range: {min(final_durations):.2f}s - {max(final_durations):.2f}s)"
        )
        return final_durations

    def get_pacing_metrics(self, durations: List[float]) -> Dict[str, float]:
        """Calculates variance and rhythm telemetry."""
        if not durations:
            return {"avg_duration": 0.0, "variance": 0.0, "min": 0.0, "max": 0.0}
        avg_d = sum(durations) / len(durations)
        variance = sum((d - avg_d) ** 2 for d in durations) / len(durations)
        return {
            "avg_duration": round(avg_d, 2),
            "variance": round(variance, 3),
            "min_duration": min(durations),
            "max_duration": max(durations),
            "change_rate_per_min": round((len(durations) / sum(durations)) * 60.0, 1)
        }
