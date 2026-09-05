"""
Directorial Style Selection Engine.
Provides deterministic, intelligence-driven selection of:
- EditingStyleProfile for overarching video pacing and density
- SubtitleStyleType per narrative beat, enforcing anti-chaos constraints:
  * Minimum style persistence (1 beat)
  * Maximum consecutive repetition (max 2 beats for specialized styles)
  * Cooldown enforcement (2-beat cooldown before re-using high-impact styles)
  * Multi-style diversity within the same Short
"""
import re
import logging
from typing import List, Dict, Any, Optional, Set
from collections import Counter

from .editing_models import SubtitleStyleType, EditingStyleProfile
from ..models import VisualIntent

logger = logging.getLogger(__name__)


class SubtitleStyleSelector:
    """
    Directorial controller that maps narrative beat characteristics to typographic styles.
    Ensures high-impact editorial moments receive custom typography while preventing
    visual chaos and unreadable rapid cycling.
    """

    # High-impact specialized styles that must be throttled
    SPECIALIZED_STYLES = {
        SubtitleStyleType.QUESTION,
        SubtitleStyleType.QUOTE,
        SubtitleStyleType.STATISTIC,
        SubtitleStyleType.IMPACT,
        SubtitleStyleType.EMPHASIS,
        SubtitleStyleType.EVIDENCE,
        SubtitleStyleType.REACTION
    }

    MAX_CONSECUTIVE_SPECIALIZED = 2
    SPECIALIZED_COOLDOWN_BEATS = 2

    def __init__(self):
        # Tracks style history for the active Short: list of chosen styles
        self._history: List[SubtitleStyleType] = []

    def reset(self):
        """Resets history for a new video job."""
        self._history.clear()

    def select_style_for_beat(
        self,
        beat_index: int,
        narrative_role: str,
        narration_text: str,
        visual_intent: Optional[VisualIntent] = None,
        evidence_overlay_present: bool = False,
        intensity: str = "MEDIUM",
        primary_entity_present: bool = False
    ) -> SubtitleStyleType:
        """
        Deterministically selects an appropriate subtitle style for a narrative beat.
        Applies narrative classification, followed by anti-chaos filtering.
        """
        text = narration_text.strip() if narration_text else ""
        role = narrative_role.upper()
        inten = intensity.upper()
        
        # 1. Candidate preference calculation
        preferred: SubtitleStyleType

        # Hook / Opening interrogative
        if beat_index == 0:
            if "?" in text or text.lower().startswith(("why", "how", "what", "who", "when", "could", "did")):
                preferred = SubtitleStyleType.QUESTION
            else:
                preferred = SubtitleStyleType.PUNCH

        # Direct quote statement
        elif any(c in text for c in ['"', '“', '”', "‘", "’"]) or any(k in text.lower() for k in ["quoted", "declared", "said", "testified"]):
            preferred = SubtitleStyleType.QUOTE

        # Numeric statistics / data facts
        elif any(char.isdigit() for char in text) and any(k in text.lower() for k in ["percent", "%", "million", "billion", "thousand", "dollars", "$", "years", "tons"]):
            preferred = SubtitleStyleType.STATISTIC

        # Documentary evidence / court record / treaty
        elif evidence_overlay_present or (visual_intent and getattr(visual_intent, "evidence_required", False)):
            preferred = SubtitleStyleType.EVIDENCE

        # Climax / Extreme Impact Peak
        elif inten == "CLIMAX" or role in ("CLIMAX", "IMPACT", "REVEAL"):
            preferred = SubtitleStyleType.IMPACT

        # Entity Introduction Callout
        elif primary_entity_present and beat_index <= 2:
            preferred = SubtitleStyleType.KEYWORD_CALLOUT

        # Critical Turning Point / Escalation
        elif inten == "HIGH" or role == "ESCALATION":
            preferred = SubtitleStyleType.KINETIC

        # Contextual reaction or meme beat
        elif visual_intent and getattr(visual_intent, "visual_intent", "") == "REACTION":
            preferred = SubtitleStyleType.REACTION

        # Standard narration baseline
        else:
            # Alternate baseline between WORD_HIGHLIGHT and CLEAN to prevent monotony
            preferred = SubtitleStyleType.WORD_HIGHLIGHT if (beat_index % 2 == 0) else SubtitleStyleType.CLEAN

        # 2. Anti-Chaos & Cooldown Gating
        final_style = self._apply_anti_chaos_rules(preferred, beat_index)
        self._history.append(final_style)
        return final_style

    def _apply_anti_chaos_rules(
        self,
        candidate: SubtitleStyleType,
        beat_index: int
    ) -> SubtitleStyleType:
        """
        Guarantees:
        - Max 2 consecutive specialized styles of the exact same type
        - 2-beat cooldown before re-using the same specialized style
        """
        if candidate not in self.SPECIALIZED_STYLES:
            return candidate

        # Rule A: Check consecutive repetition
        if len(self._history) >= self.MAX_CONSECUTIVE_SPECIALIZED:
            if all(s == candidate for s in self._history[-self.MAX_CONSECUTIVE_SPECIALIZED:]):
                logger.debug(f"Subtitle style {candidate.value} hit consecutive cap. Falling back to WORD_HIGHLIGHT.")
                return SubtitleStyleType.WORD_HIGHLIGHT

        # Rule B: Check cooldown (was this exact specialized style used within last N beats?)
        recent_window = self._history[-self.SPECIALIZED_COOLDOWN_BEATS:] if self._history else []
        if candidate in recent_window:
            # If the immediate previous was this style, allowed once if under consecutive cap,
            # but if it was 2 beats ago, enforce cooldown to promote variety.
            if len(self._history) >= 2 and self._history[-2] == candidate and self._history[-1] != candidate:
                return SubtitleStyleType.KINETIC if candidate == SubtitleStyleType.IMPACT else SubtitleStyleType.WORD_HIGHLIGHT

        return candidate

    def get_style_history(self) -> List[SubtitleStyleType]:
        """Returns ordered list of styles selected for the current job."""
        return list(self._history)

    def get_style_diversity_summary(self) -> Dict[str, Any]:
        """Audits style variety across the active video."""
        counts = Counter(s.value for s in self._history)
        transitions = sum(1 for i in range(1, len(self._history)) if self._history[i] != self._history[i-1])
        return {
            "total_beats": len(self._history),
            "distinct_styles_count": len(counts),
            "styles_used": list(counts.keys()),
            "style_transitions": transitions,
            "style_distribution": dict(counts)
        }


class EditingStyleSelector:
    """
    Directorial classifier that selects the overarching EditingStyleProfile.
    Controls default pacing, cut frequency, zoom aggressiveness, and BGM tension.
    """

    def select_profile(
        self,
        category: str,
        title: str,
        script_text: str = ""
    ) -> EditingStyleProfile:
        """
        Selects an EditingStyleProfile based on story characteristics.
        Niche-agnostic: matches structural storytelling archetypes.
        """
        combined = f"{category} {title} {script_text}".lower()

        # Investigative journalism
        if "investigat" in combined or any(k in combined for k in ["undercover", "whistleblower probe"]):
            return EditingStyleProfile.INVESTIGATIVE

        # Document and leaked records reveal
        if any(k in combined for k in ["leaked memo", "classified", "unsealed", "internal files", "secret cables", "dossier", "whistleblower documents"]):
            return EditingStyleProfile.DOCUMENT_REVEAL

        # Controversy and public dispute
        if any(k in combined for k in ["controversy", "backlash", "feud", "outrage", "boycott", "scandal", "sparks fury"]):
            return EditingStyleProfile.CONTROVERSY

        # Timeline and chronological sequence
        if any(k in combined for k in ["timeline", "chronology", "hour by hour", "day by day", "how it unfolded", "step by step"]):
            return EditingStyleProfile.TIMELINE

        # Fast news recap / rapid brief
        if any(k in combined for k in ["recap", "roundup", "in 60 seconds", "speedrun", "quick summary", "morning brief"]):
            return EditingStyleProfile.FAST_NEWS_RECAP

        # Breaking news alerts
        if any(k in combined for k in ["breaking news", "just in", "urgent alert", "bulletin"]):
            return EditingStyleProfile.BREAKING_NEWS
        elif any(k in combined for k in ["breaking", "urgent", "update", "developing", "flash", "latest"]):
            return EditingStyleProfile.FAST_BREAKING

        # Heavy statistics and numerical trends
        if any(k in combined for k in ["trillion", "billion", "inflation rate", "interest rate", "stock plunge", "quarterly earnings", "by the numbers"]):
            return EditingStyleProfile.STATISTIC_HEAVY

        # Quote / speech / testimony driven
        if any(k in combined for k in ["testimony", "press conference", "in their own words", "full remarks", "confession", "address to the nation"]):
            return EditingStyleProfile.QUOTE_DRIVEN

        # Political / legislative / governance analysis
        if any(k in combined for k in ["election", "senate", "congress", "parliament", "supreme court", "geopolitics", "foreign policy", "diplomacy", "legislation"]):
            return EditingStyleProfile.POLITICAL_ANALYSIS

        # Historical context / deep archival
        if any(k in combined for k in ["history", "archival", "decades ago", "cold war", "retrospective", "century", "historical context"]):
            return EditingStyleProfile.HISTORICAL_CONTEXT

        # Reaction / viral discourse
        if any(k in combined for k in ["viral reaction", "internet reacts", "public reaction", "streamer responds", "social media explodes"]):
            return EditingStyleProfile.REACTION_HEAVY

        # Analytical / technical
        if any(k in combined for k in ["data", "economy", "market", "statistic", "percent", "analysis", "study", "research", "chart"]):
            return EditingStyleProfile.ANALYTICAL

        # High dramatic conflict
        if any(k in combined for k in ["war", "battle", "siege", "cataclysm", "disaster", "crisis", "fall", "collapse", "clash"]):
            return EditingStyleProfile.DRAMATIC

        # Explainer / educational breakdown
        if any(k in combined for k in ["how", "why", "explained", "guide", "mechanism", "origin"]):
            return EditingStyleProfile.EXPLAINER

        # Human interest / emotional resilience
        elif any(k in combined for k in ["hero", "survivor", "life", "family", "tragedy", "courage", "heartbreak"]):
            return EditingStyleProfile.HUMAN_INTEREST

        # Standard news default
        return EditingStyleProfile.NEWS
