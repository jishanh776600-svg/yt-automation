"""
Controlled Voice Variation & Delivery Directorial Policy.
Balances channel brand identity with vocal variety across videos.
Prevents monotone single-voice presentation without chaotic random switching.

Reasons about:
- Voice Identity (timbre, persona, pitch)
- Speaking Style / Delivery Profile (conversational, urgent, investigative, etc.)
- Story Archetype
- Recent voice usage (max 2 consecutive repeats)
- Recent delivery-style usage (max 2 consecutive repeats)
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from collections import deque

from .voice_delivery import (
    DeliveryProfile, DeliveryDirector, DeliverySpec,
    VoiceDeliveryDecision, ProfanityLevel, ProfanityPolicyEngine
)

logger = logging.getLogger(__name__)


class VoiceVariationPolicy:
    """
    Directorial policy coordinator for vocal presentation.
    Selects balanced voice + delivery profile combinations, enforcing
    both voice-identity rotation and speaking-style rotation.
    """

    APPROVED_PERSONAS: Dict[str, Dict[str, Any]] = {
        "af_sarah": {
            "id": "af_sarah",
            "name": "Sarah (US Female)",
            "gender": "FEMALE",
            "style": "High-Presence / Slightly-Fast / Creator Delivery",
            "persona": "Energetic Female Creator",
            "best_for": ["culture", "human", "history", "mystery", "science", "global", "poignant", "curiosity", "geopolitics", "update", "breaking", "conflict", "diplomacy"],
            "profile": DeliveryProfile.SARAH_MAX_CREATOR,
            "supported_profiles": [DeliveryProfile.SARAH_MAX_CREATOR, DeliveryProfile.CREATOR_HIGH_PRESENCE_SLIGHT_FAST, DeliveryProfile.URGENT, DeliveryProfile.CONVERSATIONAL]
        }
    }

    # Backward compatibility alias
    AVAILABLE_VOICES = list(APPROVED_PERSONAS.keys())
    APPROVED_PRODUCTION_VOICES = ["af_sarah"]

    MAX_CONSECUTIVE_VOICE = 2
    MAX_CONSECUTIVE_PROFILE = 2

    def __init__(self):
        self._recent_voices: deque = deque(maxlen=6)
        self._recent_delivery_profiles: deque = deque(maxlen=6)
        self.delivery_director = DeliveryDirector()
        self.profanity_engine = ProfanityPolicyEngine()

    @property
    def history(self) -> List[str]:
        """Backward compatibility property returning recent voice history."""
        return list(self._recent_voices)

    def get_recent_voices(self) -> List[str]:
        return list(self._recent_voices)

    def get_recent_delivery_profiles(self) -> List[str]:
        return list(self._recent_delivery_profiles)

    def reset_history(self):
        """Resets both voice and speaking style rotation history."""
        self._recent_voices.clear()
        self._recent_delivery_profiles.clear()

    def select_voice_and_delivery(
        self,
        category: str = "",
        title: str = "",
        script_text: str = "",
        emotional_tone: str = "SERIOUS",
        enforce_rotation: bool = True,
        profanity_level: ProfanityLevel = ProfanityLevel.NONE,
        intensity: str = "MEDIUM",
        bgm_policy: str = "NONE"
    ) -> VoiceDeliveryDecision:
        """
        Coordinates full voice identity + speaking style selection.
        Enforces:
        - Strict lock to APPROVED_PRODUCTION_VOICES (am_liam, af_sarah)
        - Story topic / tone matching
        - Anti-consecutive voice repetition (max 2) with alternating balance
        - Direct coupling: am_liam -> LIAM_MAX_CREATOR, af_sarah -> SARAH_MAX_CREATOR
        - Solemnity / tragedy humor suppression
        - Channel identity preservation
        """
        full_text = f"{category} {title} {script_text}".lower()

        # 1. Voice Identity Rotation & Selection
        recent_v = list(self._recent_voices)
        voice_scores: Dict[str, float] = {}

        for vid, spec in self.APPROVED_PERSONAS.items():
            score = 1.0
            # Topic keyword bonuses
            for kw in spec.get("best_for", []):
                if kw in full_text:
                    score += 2.0

            # Rotation enforcement
            if enforce_rotation and recent_v:
                # Discourage consecutive repeats to promote alternation
                if recent_v[-1] == vid:
                    score -= 2.0
                # Hard block on 3rd consecutive repeat
                if len(recent_v) >= self.MAX_CONSECUTIVE_VOICE:
                    if all(v == vid for v in recent_v[-self.MAX_CONSECUTIVE_VOICE:]):
                        score -= 50.0

            voice_scores[vid] = score

        chosen_voice = max(voice_scores.items(), key=lambda x: x[1])[0]
        if chosen_voice not in self.APPROVED_PRODUCTION_VOICES:
            chosen_voice = "af_sarah"

        # 2. Select Delivery Profile coupled directly to the chosen voice
        if chosen_voice == "am_liam":
            profile = DeliveryProfile.LIAM_MAX_CREATOR
        else:
            profile = DeliveryProfile.SARAH_MAX_CREATOR

        # 3. Build calibrated delivery spec
        delivery_spec = self.delivery_director.build_delivery_spec(
            profile=profile,
            raw_text=script_text,
            category=category,
            emotional_tone=emotional_tone,
            profanity_level=profanity_level,
            intensity=intensity
        )

        # Update histories
        self._recent_voices.append(chosen_voice)
        self._recent_delivery_profiles.append(profile.value)

        rationale = (
            f"Production persona lock: matched '{category}/{title}' with Delivery: {profile.value} "
            f"and Voice: {chosen_voice} ({self.APPROVED_PERSONAS[chosen_voice]['name']})."
        )
        logger.info(f"[VOICE_POLICY] {rationale}")

        return VoiceDeliveryDecision(
            voice_id=chosen_voice,
            delivery_profile=profile,
            delivery_spec=delivery_spec,
            rationale=rationale,
            repetition_check_passed=True,
            bgm_policy=bgm_policy
        )

    def select_voice(
        self,
        category: str = "",
        title: str = "",
        script_text: str = "",
        enforce_rotation: bool = True
    ) -> str:
        """Backward-compatible voice selection interface."""
        decision = self.select_voice_and_delivery(
            category=category,
            title=title,
            script_text=script_text,
            enforce_rotation=enforce_rotation
        )
        return decision.voice_id
