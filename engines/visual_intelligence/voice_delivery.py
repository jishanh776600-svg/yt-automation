"""
AL-AMR Voice Delivery & Speaking Style Architecture.
Separates:
1. Voice Identity (timbre, persona, pitch)
2. Speaking Style / Delivery Profile (pacing, pause rhythm, cadence)
3. Delivery Intensity (Low, Medium, High, Climax)
4. Emotional & Tone Direction
5. Punctuation & Pause Direction
6. Informal Language & Profanity Policy
"""
import re
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple, Set

from config.constants import (
    VOICEOVER_PAUSE_MULTIPLIER,
    BASE_CLAUSE_PAUSE_SEC,
    BASE_SENTENCE_PAUSE_SEC,
    BASE_PARAGRAPH_PAUSE_SEC,
    BASE_EMPHASIS_PAUSE_SEC,
    EFFECTIVE_CLAUSE_PAUSE_SEC,
    EFFECTIVE_SENTENCE_PAUSE_SEC,
    EFFECTIVE_PARAGRAPH_PAUSE_SEC,
    EFFECTIVE_EMPHASIS_PAUSE_SEC,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. DELIVERY PROFILES / SPEAKING STYLES
# ==============================================================================

class DeliveryProfile(str, Enum):
    CONVERSATIONAL = "CONVERSATIONAL"
    INVESTIGATIVE = "INVESTIGATIVE"
    SARCASTIC_LIGHT = "SARCASTIC_LIGHT"
    URGENT = "URGENT"
    SHOCK_REVEAL = "SHOCK_REVEAL"
    CALM_EXPLANATION = "CALM_EXPLANATION"
    DRAMATIC_REVEAL = "DRAMATIC_REVEAL"
    DARK_HUMOR_CONTEXTUAL = "DARK_HUMOR_CONTEXTUAL"
    LIAM_MAX_CREATOR = "LIAM_MAX_CREATOR"
    SARAH_MAX_CREATOR = "SARAH_MAX_CREATOR"
    CREATOR_HIGH_PRESENCE_SLIGHT_FAST = "CREATOR_HIGH_PRESENCE_SLIGHT_FAST"


class ProfanityLevel(str, Enum):
    NONE = "NONE"              # Zero informal profanity; clean broadcast standard
    LIGHT = "LIGHT"            # Mild expressions: hell, damn, crap, insane, bizarre
    MODERATE = "MODERATE"      # Emphatic creator colloquialisms: fucking weird, badass, pissed off, bullshit
    STRONG = "STRONG"          # Full expressive commentary (restricted to non-sensitive pop culture/editorial)


# ==============================================================================
# 2. DATA SCHEMAS
# ==============================================================================

@dataclass
class DeliverySpec:
    """Complete directorial speech delivery specification for TTS synthesis."""
    profile: DeliveryProfile
    speed_multiplier: float = 1.0
    sentence_pause_sec: float = EFFECTIVE_SENTENCE_PAUSE_SEC
    clause_pause_sec: float = EFFECTIVE_CLAUSE_PAUSE_SEC
    paragraph_pause_sec: float = EFFECTIVE_PARAGRAPH_PAUSE_SEC
    emphasis_pause_sec: float = EFFECTIVE_EMPHASIS_PAUSE_SEC
    presence_boost_db: float = 2.2
    eq_freq_hz: int = 3000
    target_lufs: float = -15.5
    true_peak_ceiling: float = -1.2
    intensity: str = "MEDIUM"               # LOW, MEDIUM, HIGH, CLIMAX
    prepared_text: str = ""
    profanity_policy: ProfanityLevel = ProfanityLevel.NONE
    profanity_count: int = 0
    quoted_profanity_count: int = 0
    pitch_energy_direction: str = "BALANCED" # CALM, BALANCED, ELEVATED, INTENSE
    lead_in_applied: Optional[str] = None
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["profile"] = self.profile.value if isinstance(self.profile, DeliveryProfile) else self.profile
        d["profanity_policy"] = self.profanity_policy.value if isinstance(self.profanity_policy, ProfanityLevel) else self.profanity_policy
        return d


@dataclass
class VoiceDeliveryDecision:
    """Actionable decision record pairing a voice identity with a delivery profile."""
    voice_id: str
    delivery_profile: DeliveryProfile
    delivery_spec: DeliverySpec
    rationale: str
    repetition_check_passed: bool = True
    bgm_policy: str = "NONE"
    schema_version: str = "1.0.0"

    @property
    def speed_multiplier(self) -> float:
        return self.delivery_spec.speed_multiplier if self.delivery_spec else 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "delivery_profile": self.delivery_profile.value if isinstance(self.delivery_profile, DeliveryProfile) else self.delivery_profile,
            "delivery_spec": self.delivery_spec.to_dict(),
            "rationale": self.rationale,
            "repetition_check_passed": self.repetition_check_passed,
            "bgm_policy": self.bgm_policy,
            "schema_version": self.schema_version
        }


# ==============================================================================
# 3. PROFANITY & INFORMAL LANGUAGE POLICY
# ==============================================================================

class ProfanityPolicyEngine:
    """
    Evaluates, enforces, and sanitizes informal creator language.
    Strictly prohibits profanity during solemn events, tragedies, casualties, or mourning.
    Distinguishes quoted historical language from narrator language.
    """

    SOLEMN_TRIGGER_WORDS: Set[str] = {
        "killed", "death", "deaths", "casualt", "casualty", "casualties", "fatal", "fatality", "died",
        "massacre", "funeral", "assassinated", "grief", "mourning", "genocide",
        "catastrophe", "catastrophic", "starved", "plague", "famine", "victim", "victims",
        "tragedy", "tragic", "suffering", "hostage", "burial", "earthquake", "disaster",
        "disasters", "lives", "perished", "tsunami"
    }

    # Quotation regex: matches text within double or curly quotes
    QUOTE_REGEX = re.compile(r'["“](.*?)["”]')

    # Vocabulary dictionaries
    MILD_WORDS = {"hell", "damn", "crap", "insane", "bizarre"}
    MODERATE_WORDS = {"fucking", "fuck", "shit", "badass", "pissed", "bullshit", "asshole", "clusterfuck"}

    def is_solemn_context(self, text: str, category: str = "", tone: str = "") -> bool:
        """Determines if the topic is too somber for informal or sarcastic language."""
        if tone.upper() in ("TRAGEDY", "MOURNING", "GRIEF", "WAR_CASUALTIES", "CRIME_VICTIM"):
            return True
        combined = f"{category} {text}".lower()
        return any(w in combined for w in self.SOLEMN_TRIGGER_WORDS)

    def sanitize_narration(
        self,
        text: str,
        policy_level: ProfanityLevel = ProfanityLevel.NONE,
        is_solemn: bool = False
    ) -> Tuple[str, int, int]:
        """Convenience alias for evaluate_profanity."""
        return self.evaluate_profanity(text, policy_level=policy_level, is_solemn=is_solemn)

    def evaluate_profanity(
        self,
        text: str,
        policy_level: ProfanityLevel,
        is_solemn: bool = False
    ) -> Tuple[str, int, int]:
        """
        Applies profanity policy to text.
        Returns: (sanitized_text, narrator_profanity_count, quoted_profanity_count)
        """
        # If solemn, unconditionally force level to NONE
        effective_level = ProfanityLevel.NONE if is_solemn else policy_level

        quoted_segments = self.QUOTE_REGEX.findall(text)
        quoted_profanity_count = 0
        for seg in quoted_segments:
            seg_words = seg.lower().split()
            quoted_profanity_count += sum(1 for w in seg_words if w in self.MODERATE_WORDS or w in self.MILD_WORDS)

        # Scan narrator words outside quotes
        unquoted_text = self.QUOTE_REGEX.sub("", text)
        narrator_words = re.findall(r'\b\w+\b', unquoted_text.lower())

        narrator_profanity_count = 0
        for w in narrator_words:
            if w in self.MODERATE_WORDS:
                narrator_profanity_count += 1
            elif w in self.MILD_WORDS and effective_level == ProfanityLevel.NONE:
                narrator_profanity_count += 1

        sanitized_text = text
        if effective_level == ProfanityLevel.NONE:
            # Cleanse moderate and mild words outside quotes
            def clean_word(match):
                word = match.group(0)
                lw = word.lower()
                if lw in {"fucking", "fuck", "shit", "bullshit"}:
                    return "completely" if lw == "fucking" else "nonsense"
                if lw in {"pissed", "asshole"}:
                    return "infuriated"
                if lw in {"hell", "damn"}:
                    return "earth"
                return word

            # Apply only outside quotes
            parts = re.split(r'(["“].*?["”])', text)
            new_parts = []
            for p in parts:
                if p.startswith(('"', '“')):
                    new_parts.append(p)  # Preserve exact quotation provenance
                else:
                    new_p = re.sub(r'\b(fucking|fuck|shit|bullshit|pissed|asshole|hell|damn)\b', clean_word, p, flags=re.IGNORECASE)
                    new_parts.append(new_p)
            sanitized_text = "".join(new_parts)

        elif effective_level == ProfanityLevel.LIGHT:
            # Cleanse harsh moderate profanities, permit mild expressions
            parts = re.split(r'(["“].*?["”])', text)
            new_parts = []
            for p in parts:
                if p.startswith(('"', '“')):
                    new_parts.append(p)
                else:
                    new_p = re.sub(r'\b(fucking|fuck|shit|bullshit)\b', "wildly", p, flags=re.IGNORECASE)
                    new_parts.append(new_p)
            sanitized_text = "".join(new_parts)

        return sanitized_text, narrator_profanity_count, quoted_profanity_count


# ==============================================================================
# 4. DELIVERY DIRECTOR (SPEAKING STYLE & NATURAL PHRASING)
# ==============================================================================

class DeliveryDirector:
    """
    Directorial controller that transforms narrative beats into precise
    TTS delivery parameters (speed, sentence pauses, clause pauses, phrasing cadence).
    """

    # Baseline speed and pause parameters per delivery profile
    PROFILE_PRESETS: Dict[DeliveryProfile, Dict[str, Any]] = {
        DeliveryProfile.CONVERSATIONAL: {
            "speed_multiplier": 1.00,
            "sentence_pause_sec": 0.08,
            "clause_pause_sec": 0.03,
            "pitch_energy": "BALANCED",
            "lead_ins": ["Look,", "So,", "Here is the thing:", "Now,"]
        },
        DeliveryProfile.INVESTIGATIVE: {
            "speed_multiplier": 0.98,
            "sentence_pause_sec": 0.10,
            "clause_pause_sec": 0.04,
            "pitch_energy": "INTENSE",
            "lead_ins": ["Follow the trail.", "Notice what happened next.", "Declassified records show:"]
        },
        DeliveryProfile.SARCASTIC_LIGHT: {
            "speed_multiplier": 1.00,
            "sentence_pause_sec": 0.08,
            "clause_pause_sec": 0.03,
            "pitch_energy": "BALANCED",
            "lead_ins": ["Apparently,", "In an astonishing turn of events,", "Naturally,"]
        },
        DeliveryProfile.URGENT: {
            "speed_multiplier": 1.05,
            "sentence_pause_sec": 0.08,
            "clause_pause_sec": 0.02,
            "pitch_energy": "ELEVATED",
            "lead_ins": ["Breaking right now.", "Developing fast:"]
        },
        DeliveryProfile.SHOCK_REVEAL: {
            "speed_multiplier": 0.98,
            "sentence_pause_sec": 0.10,
            "clause_pause_sec": 0.04,
            "pitch_energy": "INTENSE",
            "lead_ins": ["And then came the twist.", "Here is what nobody expected:"]
        },
        DeliveryProfile.CALM_EXPLANATION: {
            "speed_multiplier": 0.98,
            "sentence_pause_sec": 0.10,
            "clause_pause_sec": 0.03,
            "pitch_energy": "CALM",
            "lead_ins": ["To understand this,", "Here is how it works:"]
        },
        DeliveryProfile.DRAMATIC_REVEAL: {
            "speed_multiplier": 0.96,
            "sentence_pause_sec": 0.10,
            "clause_pause_sec": 0.04,
            "pitch_energy": "INTENSE",
            "lead_ins": ["That changed everything.", "In that single moment:"]
        },
        DeliveryProfile.DARK_HUMOR_CONTEXTUAL: {
            "speed_multiplier": 1.00,
            "sentence_pause_sec": 0.08,
            "clause_pause_sec": 0.03,
            "pitch_energy": "BALANCED",
            "lead_ins": ["You cannot make this up.", "In peak bureaucratic fashion,"]
        },
        DeliveryProfile.LIAM_MAX_CREATOR: {
            "speed_multiplier": 1.08,
            "sentence_pause_sec": 0.17,
            "clause_pause_sec": 0.07,
            "presence_boost_db": 2.2,
            "eq_freq_hz": 3000,
            "target_lufs": -15.5,
            "true_peak_ceiling": -1.2,
            "pitch_energy": "HIGH_PRESENCE",
            "lead_ins": ["Okay, wait.", "So here's the thing.", "Look,", "And this is the part almost everyone missed."]
        },
        DeliveryProfile.SARAH_MAX_CREATOR: {
            "speed_multiplier": 1.08,
            "sentence_pause_sec": 0.17,
            "clause_pause_sec": 0.07,
            "presence_boost_db": 2.2,
            "eq_freq_hz": 3000,
            "target_lufs": -15.5,
            "true_peak_ceiling": -1.2,
            "pitch_energy": "HIGH_PRESENCE",
            "lead_ins": ["Okay, wait.", "So here's the thing.", "Look,", "And this is where things get interesting."]
        },
        DeliveryProfile.CREATOR_HIGH_PRESENCE_SLIGHT_FAST: {
            "speed_multiplier": 1.08,
            "sentence_pause_sec": 0.17,
            "clause_pause_sec": 0.07,
            "presence_boost_db": 2.2,
            "eq_freq_hz": 3000,
            "target_lufs": -15.5,
            "true_peak_ceiling": -1.2,
            "pitch_energy": "HIGH_PRESENCE",
            "lead_ins": ["Okay, wait.", "So here's the thing.", "Look,"]
        }
    }

    def __init__(self):
        self.profanity_engine = ProfanityPolicyEngine()

    def determine_profile(
        self,
        script_text: str = "",
        category: str = "",
        emotional_tone: str = "SERIOUS",
        text: Optional[str] = None,
        title: Optional[str] = None
    ) -> DeliveryProfile:
        """Alias supporting direct text and title parameters."""
        actual_text = text if text is not None else script_text
        actual_title = title or ""
        return self.select_profile_for_story(
            category=category,
            title=actual_title,
            script_text=actual_text,
            emotional_tone=emotional_tone
        )

    def select_profile_for_story(
        self,
        category: str,
        title: str,
        script_text: str = "",
        emotional_tone: str = "SERIOUS"
    ) -> DeliveryProfile:
        """
        Deterministically classifies the appropriate DeliveryProfile based on story characteristics.
        Strictly enforces tragedy / casualty gating to prevent inappropriate sarcasm.
        """
        combined = f"{category} {title} {script_text}".lower()

        # 1. Tragic / solemn check -> force CALM_EXPLANATION or INVESTIGATIVE
        if self.profanity_engine.is_solemn_context(script_text, category, emotional_tone):
            if any(k in combined for k in ["investigation", "probe", "documents", "evidence", "treaty"]):
                return DeliveryProfile.INVESTIGATIVE
            return DeliveryProfile.CALM_EXPLANATION

        # 2. Deep forensic investigation / paper trail
        if any(k in combined for k in ["investigation", "classified", "leaked", "paper trail", "memo", "scandal", "court", "probe"]):
            return DeliveryProfile.INVESTIGATIVE

        # 3. Breaking urgency
        if any(k in combined for k in ["breaking", "urgent", "update", "developing", "just in", "bulletin", "emergency"]):
            return DeliveryProfile.URGENT

        # 4. Shocking twist or sudden disclosure
        if any(k in combined for k in ["shocking", "twist", "unbelievable", "secretly", "stunning", "nobody saw this coming"]):
            return DeliveryProfile.SHOCK_REVEAL

        # 5. Bureaucratic absurdity / odd irony
        if any(k in combined for k in ["bizarre", "absurd", "irony", "ridiculous", "blunder", "farce", "oops"]):
            return DeliveryProfile.SARCASTIC_LIGHT

        # 6. Dramatic conflict / geopolitical confrontation
        if any(k in combined for k in ["war", "siege", "confrontation", "collapse", "crisis", "showdown", "threat"]):
            return DeliveryProfile.DRAMATIC_REVEAL

        # 7. Educational breakdown / mechanisms
        if any(k in combined for k in ["how", "why", "explained", "mechanism", "structure", "data"]):
            return DeliveryProfile.CALM_EXPLANATION

        # 8. Default: Creator conversational presentation
        return DeliveryProfile.CONVERSATIONAL

    def build_delivery_spec(
        self,
        profile: DeliveryProfile,
        raw_text: str,
        category: str = "",
        emotional_tone: str = "SERIOUS",
        profanity_level: ProfanityLevel = ProfanityLevel.NONE,
        intensity: str = "MEDIUM",
        inject_conversational_opening: bool = False
    ) -> DeliverySpec:
        """
        Builds a complete, calibrated DeliverySpec including:
        - Speed multiplier
        - Sentence and clause pause durations
        - Natural pause shaping (dashes, commas, question marks)
        - Profanity policy evaluation & sanitization
        """
        is_solemn = self.profanity_engine.is_solemn_context(raw_text, category, emotional_tone)
        
        # Guard against humor/sarcasm in somber topics
        if is_solemn and profile in (DeliveryProfile.SARCASTIC_LIGHT, DeliveryProfile.DARK_HUMOR_CONTEXTUAL):
            logger.info("[DELIVERY_DIRECTOR] Solemn context detected: Downgrading sarcastic delivery to CALM_EXPLANATION.")
            profile = DeliveryProfile.CALM_EXPLANATION

        preset = self.PROFILE_PRESETS.get(profile, self.PROFILE_PRESETS[DeliveryProfile.CONVERSATIONAL])

        # Evaluate and apply profanity policy
        sanitized_text, p_count, q_p_count = self.profanity_engine.evaluate_profanity(
            raw_text,
            policy_level=profanity_level,
            is_solemn=is_solemn
        )

        # Prepare natural punctuation for Kokoro TTS
        prepared = self._apply_prosody_punctuation(sanitized_text, profile, intensity)

        lead_in_used = None
        if inject_conversational_opening and not is_solemn and preset.get("lead_ins"):
            # If text doesn't already start with a conversational hook
            first_word = prepared.split()[0].lower() if prepared.split() else ""
            if first_word not in ["look,", "so,", "now,", "why", "how", "what", "here"]:
                lead_in_used = preset["lead_ins"][0]
                prepared = f"{lead_in_used} {prepared}"

        # Adjust speed slightly if intensity is CLIMAX
        speed = preset["speed_multiplier"]
        if intensity == "CLIMAX" and profile != DeliveryProfile.INVESTIGATIVE:
            speed = round(speed * 1.03, 2)
        elif intensity == "LOW":
            speed = round(speed * 0.97, 2)

        # Scale intentional pauses by canonical VOICEOVER_PAUSE_MULTIPLIER (1.40x)
        base_sent = preset["sentence_pause_sec"]
        base_clause = preset["clause_pause_sec"]
        base_para = preset.get("paragraph_pause_sec", BASE_PARAGRAPH_PAUSE_SEC)
        base_emphasis = preset.get("emphasis_pause_sec", BASE_EMPHASIS_PAUSE_SEC)

        effective_sentence_pause = round(base_sent * VOICEOVER_PAUSE_MULTIPLIER, 3)
        effective_clause_pause = round(base_clause * VOICEOVER_PAUSE_MULTIPLIER, 3)
        effective_paragraph_pause = round(base_para * VOICEOVER_PAUSE_MULTIPLIER, 3)
        effective_emphasis_pause = round(base_emphasis * VOICEOVER_PAUSE_MULTIPLIER, 3)

        # Apply emphasis pause for dramatic / climax moments
        if intensity == "CLIMAX" or profile in (DeliveryProfile.SHOCK_REVEAL, DeliveryProfile.DRAMATIC_REVEAL):
            effective_sentence_pause = max(effective_sentence_pause, effective_emphasis_pause)

        return DeliverySpec(
            profile=profile,
            speed_multiplier=speed,
            sentence_pause_sec=effective_sentence_pause,
            clause_pause_sec=effective_clause_pause,
            paragraph_pause_sec=effective_paragraph_pause,
            emphasis_pause_sec=effective_emphasis_pause,
            presence_boost_db=preset.get("presence_boost_db", 2.2),
            eq_freq_hz=preset.get("eq_freq_hz", 3000),
            target_lufs=preset.get("target_lufs", -15.5),
            true_peak_ceiling=preset.get("true_peak_ceiling", -1.2),
            intensity=intensity,
            prepared_text=prepared,
            profanity_policy=profanity_level if not is_solemn else ProfanityLevel.NONE,
            profanity_count=p_count,
            quoted_profanity_count=q_p_count,
            pitch_energy_direction=preset["pitch_energy"],
            lead_in_applied=lead_in_used
        )

    def _apply_prosody_punctuation(self, text: str, profile: DeliveryProfile, intensity: str) -> str:
        """
        Enhances text with natural phonetic pause markers:
        - Commas for breath pauses
        - Em-dashes '--' for dramatic parenthetical asides
        - Ellipsis '...' for reflective suspense
        Does not invent unsupported SSML; operates purely within text punctuation recognized by Kokoro.
        """
        cleaned = text.strip()
        
        # Replace multiple consecutive spaces
        cleaned = re.sub(r'\s+', ' ', cleaned)

        # In suspense / shock profiles, expand critical colons or semicolons to em-dashes for breath pause
        if profile in (DeliveryProfile.SHOCK_REVEAL, DeliveryProfile.DRAMATIC_REVEAL, DeliveryProfile.INVESTIGATIVE):
            cleaned = cleaned.replace(" - ", " -- ")

        # Ensure terminal punctuation exists
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."

        return cleaned
