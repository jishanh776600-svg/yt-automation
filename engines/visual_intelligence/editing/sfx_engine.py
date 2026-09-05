"""
SFX Intelligence & Semantic Sound Design Engine.
Implements restrained, narrative-synchronized sound effect placement:
- 10 Studio-grade SFX archetypes (Impacts, Risers, Whooshes, Foley, Clocks, Chimes)
- Strict frequency caps (maximum 2-3 SFX cues per Short)
- Anti-spam temporal cooldowns (minimum 4.0s separation)
- Calibrated volume levels (-18dB to -24dB) ensuring narrator voice priority
"""
import logging
from typing import Dict, Any, List, Optional
from .editing_models import SFXArchetype, SFXCueSpec

logger = logging.getLogger(__name__)


# Calibrated Archetype Specifications
SFX_ARCHETYPE_CONFIG: Dict[SFXArchetype, Dict[str, Any]] = {
    SFXArchetype.IMPACT_BOOM: {
        "filename": "impact_boom.wav",
        "description": "Sub-bass impact for dramatic reveals, explosions, and shocking facts",
        "default_volume_db": -18.0,
        "duration": 1.6,
        "fade_in": 0.05,
        "fade_out": 0.40,
        "priority": 1
    },
    SFXArchetype.TENSION_RISER: {
        "filename": "tension_riser.wav",
        "description": "Atmospheric bowed riser for suspense, escalations, and mystery builds",
        "default_volume_db": -22.0,
        "duration": 2.2,
        "fade_in": 0.20,
        "fade_out": 0.30,
        "priority": 2
    },
    SFXArchetype.CINEMATIC_WHOOSH: {
        "filename": "cinematic_whoosh.wav",
        "description": "Restrained airy whoosh for fast scene transitions and rapid shifts",
        "default_volume_db": -22.0,
        "duration": 1.2,
        "fade_in": 0.05,
        "fade_out": 0.15,
        "priority": 3
    },
    SFXArchetype.SUBTLE_PAPER_TURN: {
        "filename": "subtle_paper_turn.wav",
        "description": "Parchment / manuscript rustle for historical laws, decrees, and letters",
        "default_volume_db": -24.0,
        "duration": 0.8,
        "fade_in": 0.05,
        "fade_out": 0.15,
        "priority": 3
    },
    SFXArchetype.DISTANT_THUNDER: {
        "filename": "distant_thunder_rumble.wav",
        "description": "Low rumble for historical cataclysms, disasters, and stormy tension",
        "default_volume_db": -20.0,
        "duration": 2.5,
        "fade_in": 0.20,
        "fade_out": 0.50,
        "priority": 2
    },
    SFXArchetype.CLOCK_TICK: {
        "filename": "clock_tick_suspense.wav",
        "description": "High-stakes mechanical pulse for countdowns, chases, and time-sensitive heists",
        "default_volume_db": -22.0,
        "duration": 2.0,
        "fade_in": 0.02,
        "fade_out": 0.10,
        "priority": 2
    },
    SFXArchetype.BELL_TOLL: {
        "filename": "bell_toll_somber.wav",
        "description": "Somber chime for medieval history, plagues, funerals, and profound tragedy",
        "default_volume_db": -20.0,
        "duration": 2.5,
        "fade_in": 0.05,
        "fade_out": 0.60,
        "priority": 1
    },
    SFXArchetype.NOTIFICATION_CHIME: {
        "filename": "notification_chime.wav",
        "description": "Modern crisp alert chime for breaking news bulletins and phone notifications",
        "default_volume_db": -22.0,
        "duration": 1.0,
        "fade_in": 0.02,
        "fade_out": 0.20,
        "priority": 3
    },
    SFXArchetype.GLITCH_REVEAL: {
        "filename": "glitch_reveal.wav",
        "description": "Technological glitch / data burst for leaked files and secret intelligence",
        "default_volume_db": -22.0,
        "duration": 1.2,
        "fade_in": 0.02,
        "fade_out": 0.15,
        "priority": 2
    },
    SFXArchetype.CAMERA_SHUTTER: {
        "filename": "camera_shutter.wav",
        "description": "Press pool camera shutter click for official press briefings and photo evidence",
        "default_volume_db": -22.0,
        "duration": 0.9,
        "fade_in": 0.02,
        "fade_out": 0.10,
        "priority": 3
    }
}


class SFXEngine:
    """
    Directorial sound design engine. Enforces frequency caps, volume calibration,
    and anti-repetition cooldowns.
    """

    MAX_SFX_PER_SHORT = 3           # Strictly maximum 3 SFX per entire 25s video
    MIN_SFX_INTERVAL_SEC = 4.0      # Minimum seconds between two SFX triggers

    def __init__(self):
        self._placed_cues: List[SFXCueSpec] = []

    def reset(self):
        """Resets placed cues for a new video job."""
        self._placed_cues.clear()

    @property
    def placed_cues(self) -> List[SFXCueSpec]:
        return list(self._placed_cues)

    def evaluate_sfx_opportunity(
        self,
        start_time: float,
        duration: float,
        narrative_role: str,
        narration_text: str,
        intensity: str = "MEDIUM",
        evidence_overlay_present: bool = False
    ) -> Optional[SFXCueSpec]:
        """
        Evaluates whether an SFX is warranted for the given shot.
        Returns a calibrated SFXCueSpec or None if capped/inappropriate.
        """
        # 1. Check global frequency cap
        if len(self._placed_cues) >= self.MAX_SFX_PER_SHORT:
            return None

        # 2. Check temporal cooldown
        cue_time = round(start_time + 0.15, 2) # Slight 150ms onset delay
        if self._placed_cues:
            last_time = self._placed_cues[-1].start_time
            if (cue_time - last_time) < self.MIN_SFX_INTERVAL_SEC:
                return None

        text = narration_text.lower()
        role = narrative_role.upper()
        inten = intensity.upper()

        chosen_archetype: Optional[SFXArchetype] = None
        reason: str = ""

        # A. Climax or Shocking Impact Reveal
        if role in ("CLIMAX", "IMPACT") or inten == "CLIMAX":
            chosen_archetype = SFXArchetype.IMPACT_BOOM
            reason = "Dramatic climax impact punch"

        # B. Evidence document or press leak
        elif evidence_overlay_present or any(k in text for k in ["document", "treaty", "court", "file", "record"]):
            if any(k in text for k in ["secret", "leaked", "classified"]):
                chosen_archetype = SFXArchetype.GLITCH_REVEAL
                reason = "Classified record glitch reveal"
            else:
                chosen_archetype = SFXArchetype.SUBTLE_PAPER_TURN
                reason = "Documentary archive paper foley"

        # C. Escalation / High Tension
        elif role == "ESCALATION" and inten in ("HIGH", "MEDIUM"):
            chosen_archetype = SFXArchetype.TENSION_RISER
            reason = "Building narrative tension"

        # D. Official briefing / Speech
        elif any(k in text for k in ["press conference", "announced", "briefing", "speech", "spoke"]):
            chosen_archetype = SFXArchetype.CAMERA_SHUTTER
            reason = "Press briefing camera shutter"

        # E. Cataclysm / Disaster
        elif any(k in text for k in ["disaster", "explosion", "storm", "cataclysm", "earthquake", "collapse"]):
            chosen_archetype = SFXArchetype.DISTANT_THUNDER
            reason = "Cataclysmic disaster rumble"

        # F. Solemn Tragedy
        elif any(k in text for k in ["died", "killed", "tragedy", "loss", "plague", "funeral"]):
            chosen_archetype = SFXArchetype.BELL_TOLL
            reason = "Somber tragedy bell toll"

        if not chosen_archetype:
            return None

        cfg = SFX_ARCHETYPE_CONFIG[chosen_archetype]
        spec = SFXCueSpec(
            sfx_id=f"sfx_{len(self._placed_cues)+1}_{chosen_archetype.value}",
            archetype=chosen_archetype,
            start_time=cue_time,
            duration=cfg["duration"],
            volume_db=cfg["default_volume_db"],
            fade_in_sec=cfg["fade_in"],
            fade_out_sec=cfg["fade_out"],
            priority=cfg["priority"],
            reason=reason
        )
        self._placed_cues.append(spec)
        logger.debug(f"Placed sound design cue: {spec.archetype.value} at {cue_time:.2f}s ({reason})")
        return spec
