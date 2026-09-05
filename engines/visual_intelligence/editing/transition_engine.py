"""
Transition Engine & Registry for AL-AMR.
Provides restrained, pacing-aware transitions between consecutive shots:
- Cut (default hard cut, 0.0s duration)
- Dissolves (Crossfade, Dip-to-Black, Dip-to-White, Blur Dissolve)
- Kinetic transitions (Whip Left, Whip Right, Zoom In, Slide Up, Flash)
- Anti-repetition & transition cooldown system (prevents flashy transition spam)
"""
import logging
from typing import Dict, Any, List, Optional
from .editing_models import TransitionType, TransitionSpec, EasingType

logger = logging.getLogger(__name__)


# Calibrated Transition Durations (seconds)
TRANSITION_DURATIONS: Dict[TransitionType, float] = {
    TransitionType.CUT: 0.0,
    TransitionType.CROSSFADE: 0.25,
    TransitionType.DIP_TO_BLACK: 0.30,
    TransitionType.DIP_TO_WHITE: 0.20,
    TransitionType.WHIP_LEFT: 0.25,
    TransitionType.WHIP_RIGHT: 0.25,
    TransitionType.ZOOM_IN: 0.25,
    TransitionType.SLIDE_UP: 0.25,
    TransitionType.BLUR_DISSOLVE: 0.30,
    TransitionType.FLASH: 0.15
}


class TransitionEngine:
    """Directorial transition selector with strict anti-repetition rules."""

    NON_CUT_COOLDOWN_SHOTS = 1      # Require at least 1 hard cut between non-cut transitions
    MAX_CONSECUTIVE_NON_CUT = 1

    def __init__(self):
        self._history: List[TransitionType] = []

    def reset(self):
        """Resets transition history for a new job."""
        self._history.clear()

    def select_transition(
        self,
        shot_index: int,
        narrative_role: str,
        previous_role: Optional[str] = None,
        pacing_urgency: str = "BALANCED",
        requested_type: Optional[TransitionType] = None
    ) -> TransitionSpec:
        """
        Deterministically selects an appropriate transition into shot_index.
        First shot (index 0) is ALWAYS a hard cut.
        """
        if shot_index == 0:
            chosen = TransitionType.CUT
            self._history.append(chosen)
            return TransitionSpec(transition_type=chosen, duration=0.0)

        # 1. Evaluate candidate transition
        candidate: TransitionType = TransitionType.CUT

        if requested_type and requested_type != TransitionType.CUT:
            candidate = requested_type
        elif narrative_role == "REVEAL" or previous_role == "ESCALATION":
            candidate = TransitionType.DIP_TO_BLACK
        elif pacing_urgency == "FAST_PACED" and narrative_role in ("ESCALATION", "IMPACT"):
            candidate = TransitionType.WHIP_LEFT if (shot_index % 2 == 0) else TransitionType.ZOOM_IN
        elif narrative_role == "OUTRO" or narrative_role == "LOOP_TWIST":
            candidate = TransitionType.CROSSFADE
        elif previous_role == "HOOK" and narrative_role == "SETUP":
            candidate = TransitionType.CUT
        else:
            # Subtle crossfade every 3rd or 4th shot, otherwise hard cut
            candidate = TransitionType.CROSSFADE if (shot_index % 3 == 0) else TransitionType.CUT

        # 2. Enforce Anti-Repetition & Cooldown
        final_trans = self._apply_cooldown(candidate)
        self._history.append(final_trans)
        
        dur = TRANSITION_DURATIONS.get(final_trans, 0.0)
        return TransitionSpec(
            transition_type=final_trans,
            duration=dur,
            easing=EasingType.EASE_IN_OUT
        )

    def _apply_cooldown(self, candidate: TransitionType) -> TransitionType:
        """Enforces that flashy transitions cannot repeat consecutively."""
        if candidate == TransitionType.CUT:
            return candidate

        # Rule: No two consecutive non-cut transitions
        if self._history and self._history[-1] != TransitionType.CUT:
            logger.debug(f"Transition {candidate.value} throttled by consecutive rule. Falling back to CUT.")
            return TransitionType.CUT

        # Rule: If same non-cut transition was used recently (within 2 shots), fallback to CUT
        if len(self._history) >= 2 and candidate in self._history[-2:]:
            return TransitionType.CUT

        return candidate

    def get_history(self) -> List[TransitionType]:
        return list(self._history)

    def get_transition_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for t in self._history:
            counts[t.value] = counts.get(t.value, 0) + 1
        return counts
