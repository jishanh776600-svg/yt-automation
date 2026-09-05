"""
Core Data Models for Advanced Editorial Engine.
Defines rich, serializable representations for:
- Keyframed camera motions & easing curves
- Transitions & temporal blending
- 20 Subtitle styles & dynamic screen positions
- SFX cues & audio priority hierarchy
- Vertical 9:16 reframing specifications
- Directorial style profiles & shot edits
- Deterministic EditingPlan and AI Council telemetry
"""
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple, Union


class MotionType(str, Enum):
    NONE = "none"
    SUBTLE_ZOOM_IN = "subtle_zoom_in"
    SUBTLE_ZOOM_OUT = "subtle_zoom_out"
    PUNCH_IN = "punch_in"
    PUNCH_OUT = "punch_out"
    SLOW_PAN_LEFT = "slow_pan_left"
    SLOW_PAN_RIGHT = "slow_pan_right"
    SLOW_PAN_UP = "slow_pan_up"
    SLOW_PAN_DOWN = "slow_pan_down"
    DYNAMIC_REFRAME = "dynamic_reframe"
    FREEZE_FRAME_EMPHASIS = "freeze_frame_emphasis"


class EasingType(str, Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    SPRING = "spring"


@dataclass
class Keyframe:
    """Represents a single visual keyframe along a shot timeline."""
    time_offset: float              # Relative to shot start (seconds)
    scale: float = 1.0              # 1.0 = native vertical crop
    x_offset: float = 0.0           # Horizontal shift (-1.0 to 1.0)
    y_offset: float = 0.0           # Vertical shift (-1.0 to 1.0)
    rotation_deg: float = 0.0       # Rotation in degrees
    opacity: float = 1.0            # 0.0 (transparent) to 1.0 (opaque)
    easing: EasingType = EasingType.EASE_IN_OUT

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["easing"] = self.easing.value if isinstance(self.easing, EasingType) else self.easing
        return d


@dataclass
class CameraMotionSpec:
    """Motion directive for a shot."""
    motion_type: MotionType = MotionType.NONE
    start_scale: float = 1.0
    end_scale: float = 1.05
    pan_direction: Optional[str] = None
    easing: EasingType = EasingType.EASE_IN_OUT
    intensity: float = 1.0          # Multiplier for motion speed
    keyframes: List[Keyframe] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["motion_type"] = self.motion_type.value if isinstance(self.motion_type, MotionType) else self.motion_type
        d["easing"] = self.easing.value if isinstance(self.easing, EasingType) else self.easing
        d["keyframes"] = [k.to_dict() if hasattr(k, "to_dict") else k for k in self.keyframes]
        return d


class TransitionType(str, Enum):
    CUT = "cut"
    CROSSFADE = "crossfade"
    DIP_TO_BLACK = "dip_to_black"
    DIP_TO_WHITE = "dip_to_white"
    WHIP_LEFT = "whip_left"
    WHIP_RIGHT = "whip_right"
    ZOOM_IN = "zoom_in"
    SLIDE_UP = "slide_up"
    BLUR_DISSOLVE = "blur_dissolve"
    FLASH = "flash"


@dataclass
class TransitionSpec:
    """Transition between consecutive shots."""
    transition_type: TransitionType = TransitionType.CUT
    duration: float = 0.0           # 0.0 for hard cuts, 0.20 - 0.40s for smooth transitions
    easing: EasingType = EasingType.EASE_IN_OUT

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["transition_type"] = self.transition_type.value if isinstance(self.transition_type, TransitionType) else self.transition_type
        d["easing"] = self.easing.value if isinstance(self.easing, EasingType) else self.easing
        return d


class SubtitleStyleType(str, Enum):
    CLEAN = "CLEAN"
    KINETIC = "KINETIC"
    WORD_HIGHLIGHT = "WORD_HIGHLIGHT"
    PUNCH = "PUNCH"
    IMPACT = "IMPACT"
    BOXED = "BOXED"
    OUTLINED = "OUTLINED"
    TOP_CAPTION = "TOP_CAPTION"
    BOTTOM_CAPTION = "BOTTOM_CAPTION"
    SIDE_CAPTION = "SIDE_CAPTION"
    SPLIT_CAPTION = "SPLIT_CAPTION"
    KEYWORD_CALLOUT = "KEYWORD_CALLOUT"
    QUOTE = "QUOTE"
    QUESTION = "QUESTION"
    STATISTIC = "STATISTIC"
    EVIDENCE = "EVIDENCE"
    LOCATION = "LOCATION"
    DATE = "DATE"
    REACTION = "REACTION"
    EMPHASIS = "EMPHASIS"


class SubtitlePositionType(str, Enum):
    BOTTOM_CENTER = "BOTTOM_CENTER"   # Standard default safe zone (Y: ~1440 in 1080x1920)
    LOWER_LEFT = "LOWER_LEFT"
    LOWER_RIGHT = "LOWER_RIGHT"
    CENTER = "CENTER"                 # Eye-level dramatic burst (Y: ~960)
    UPPER_CENTER = "UPPER_CENTER"     # Upper safe zone (Y: ~380, clears lower evidence cards)
    UPPER_LEFT = "UPPER_LEFT"
    UPPER_RIGHT = "UPPER_RIGHT"
    SIDE = "SIDE"                     # Aligned along margin (X: 120)
    SPLIT = "SPLIT"                   # Split two-tier layout


@dataclass
class SubtitleWord:
    """Individual word with precise millisecond timestamps."""
    word: str
    start: float
    end: float
    is_keyword: bool = False
    is_number: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubtitleTemplate:
    """Full typography and rendering definition for a subtitle style."""
    name: str
    style_type: SubtitleStyleType
    font_name: str = "Arial Black"
    font_size: int = 84
    font_weight: int = 900          # 400 normal, 700 bold, 900 heavy
    tracking: float = 0.0           # Letter spacing in pixels
    line_spacing: int = 12
    primary_color_hex: str = "&H00FFFFFF&"      # ASS hex format (BBGGRR)
    highlight_color_hex: str = "&H0000D7FF&"    # Vibrant yellow/gold for active word
    secondary_color_hex: str = "&H00FFFF00&"    # Cyan accent
    outline_color_hex: str = "&H00000000&"      # Black stroke
    back_color_hex: str = "&H80000000&"         # Semi-transparent shadow/box
    outline_width: int = 8
    shadow_depth: int = 4
    border_style: int = 1                       # 1 = outline + shadow, 3 = opaque box
    alignment: int = 2                          # ASS numpad alignment: 2 = bottom-center, 8 = top-center, 5 = center
    margin_l: int = 80
    margin_r: int = 80
    margin_v: int = 440                         # Vertical offset from bottom edge
    uppercase: bool = True
    entry_animation: str = "pop"                # pop, fade, slide_up, none
    karaoke_highlight: bool = True
    max_words_per_line: int = 3
    safe_zone_top_pct: float = 0.15
    safe_zone_bottom_pct: float = 0.20

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["style_type"] = self.style_type.value if isinstance(self.style_type, SubtitleStyleType) else self.style_type
        return d


@dataclass
class SubtitleCue:
    """A timed subtitle event on the timeline."""
    cue_id: str
    start_time: float
    end_time: float
    text: str
    words: List[SubtitleWord] = field(default_factory=list)
    style_type: SubtitleStyleType = SubtitleStyleType.CLEAN
    position_type: SubtitlePositionType = SubtitlePositionType.BOTTOM_CENTER
    screen_x: int = 540             # Center pixel
    screen_y: int = 1480            # Lower safe zone
    emphasis_keywords: List[str] = field(default_factory=list)
    ass_dialogue_line: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["style_type"] = self.style_type.value if isinstance(self.style_type, SubtitleStyleType) else self.style_type
        d["position_type"] = self.position_type.value if isinstance(self.position_type, SubtitlePositionType) else self.position_type
        d["words"] = [w.to_dict() if hasattr(w, "to_dict") else w for w in self.words]
        return d


class SFXArchetype(str, Enum):
    IMPACT_BOOM = "impact_boom"
    TENSION_RISER = "tension_riser"
    CINEMATIC_WHOOSH = "cinematic_whoosh"
    SUBTLE_PAPER_TURN = "subtle_paper_turn"
    DISTANT_THUNDER = "distant_thunder_rumble"
    CLOCK_TICK = "clock_tick_suspense"
    BELL_TOLL = "bell_toll_somber"
    NOTIFICATION_CHIME = "notification_chime"
    GLITCH_REVEAL = "glitch_reveal"
    CAMERA_SHUTTER = "camera_shutter"


@dataclass
class SFXCueSpec:
    """Sound effect cue placed at a specific timestamp."""
    sfx_id: str
    archetype: SFXArchetype
    start_time: float
    duration: float = 1.5
    volume_db: float = -20.0
    fade_in_sec: float = 0.05
    fade_out_sec: float = 0.30
    priority: int = 2               # 1 = high impact, 2 = medium, 3 = subtle foley
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["archetype"] = self.archetype.value if isinstance(self.archetype, SFXArchetype) else self.archetype
        return d


@dataclass
class AudioTrackSpec:
    """Audio stream specification (voice, sfx, bgm)."""
    track_id: str
    track_type: str                 # voice, bgm, sfx
    file_path: Optional[str] = None
    start_time: float = 0.0
    duration: float = 0.0
    volume_db: float = 0.0
    ducking_attenuation_db: float = -22.0
    fade_in_sec: float = 0.1
    fade_out_sec: float = 0.5
    priority: int = 1               # 1 = Voice (highest), 2 = SFX, 3 = BGM (ducked)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AudioMixPlan:
    """Master audio mixing blueprint."""
    master_duration: float
    voice_track: Optional[AudioTrackSpec] = None
    bgm_track: Optional[AudioTrackSpec] = None
    sfx_tracks: List[SFXCueSpec] = field(default_factory=list)
    master_lufs_target: float = -14.0
    bgm_lufs_target: float = -28.0
    ducking_points: List[Tuple[float, float, float]] = field(default_factory=list) # (start, end, volume_db)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "master_duration": self.master_duration,
            "voice_track": self.voice_track.to_dict() if self.voice_track else None,
            "bgm_track": self.bgm_track.to_dict() if self.bgm_track else None,
            "sfx_tracks": [s.to_dict() for s in self.sfx_tracks],
            "master_lufs_target": self.master_lufs_target,
            "bgm_lufs_target": self.bgm_lufs_target,
            "ducking_points": self.ducking_points
        }


@dataclass
class ReframingSpec:
    """Vertical 9:16 subject-aware reframing directives."""
    crop_x: int = 0
    crop_y: int = 0
    crop_width: int = 1080
    crop_height: int = 1920
    subject_center_x: float = 0.5   # 0.0 left, 0.5 center, 1.0 right
    subject_center_y: float = 0.4   # Slightly above center for faces
    face_detected: bool = False
    face_bbox: Optional[Tuple[int, int, int, int]] = None # (x, y, w, h)
    safe_zone_preserved: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EditingStyleProfile(str, Enum):
    NEWS = "NEWS"
    BREAKING_NEWS = "BREAKING_NEWS"
    INVESTIGATIVE = "INVESTIGATIVE"
    POLITICAL_ANALYSIS = "POLITICAL_ANALYSIS"
    ANALYTICAL = "ANALYTICAL"
    DRAMATIC = "DRAMATIC"
    FAST_BREAKING = "FAST_BREAKING"
    FAST_NEWS_RECAP = "FAST_NEWS_RECAP"
    EXPLAINER = "EXPLAINER"
    TIMELINE = "TIMELINE"
    CONTROVERSY = "CONTROVERSY"
    STATISTIC_HEAVY = "STATISTIC_HEAVY"
    QUOTE_DRIVEN = "QUOTE_DRIVEN"
    DOCUMENT_REVEAL = "DOCUMENT_REVEAL"
    REACTION_HEAVY = "REACTION_HEAVY"
    HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"
    HUMAN_INTEREST = "HUMAN_INTEREST"


@dataclass
class ShotEdit:
    """Complete directorial edit plan for a single shot."""
    shot_id: str
    shot_index: int
    timeline_start: float
    timeline_end: float
    duration: float
    source_asset_id: str
    source_url: str
    source_provenance_id: Optional[str] = None
    clip_in_point: float = 0.0
    clip_out_point: float = 4.0
    narrative_role: str = "SETUP"   # HOOK, SETUP, ESCALATION, REVEAL, IMPACT, CLIMAX, OUTRO
    intensity: str = "MEDIUM"       # LOW, MEDIUM, HIGH, CLIMAX
    reframing: ReframingSpec = field(default_factory=ReframingSpec)
    camera_motion: CameraMotionSpec = field(default_factory=CameraMotionSpec)
    transition_in: TransitionSpec = field(default_factory=TransitionSpec)
    subtitle_cues: List[SubtitleCue] = field(default_factory=list)
    sfx_cues: List[SFXCueSpec] = field(default_factory=list)
    evidence_overlay_path: Optional[str] = None
    editorial_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "shot_index": self.shot_index,
            "timeline_start": self.timeline_start,
            "timeline_end": self.timeline_end,
            "duration": self.duration,
            "source_asset_id": self.source_asset_id,
            "source_url": self.source_url,
            "source_provenance_id": self.source_provenance_id,
            "clip_in_point": self.clip_in_point,
            "clip_out_point": self.clip_out_point,
            "narrative_role": self.narrative_role,
            "intensity": self.intensity,
            "reframing": self.reframing.to_dict(),
            "camera_motion": self.camera_motion.to_dict(),
            "transition_in": self.transition_in.to_dict(),
            "subtitle_cues": [c.to_dict() for c in self.subtitle_cues],
            "sfx_cues": [s.to_dict() for s in self.sfx_cues],
            "evidence_overlay_path": self.evidence_overlay_path,
            "editorial_reason": self.editorial_reason
        }


@dataclass
class EditingTelemetry:
    """Directorial telemetry recorded for the AI Council and analytics."""
    job_id: str
    editing_profile: str
    shot_count: int
    total_duration: float
    avg_shot_duration: float
    shot_duration_variance: float
    subtitle_styles_used: List[str]
    subtitle_style_transitions: int
    subtitle_positions_used: List[str]
    caption_occlusion_avoidances: int
    transitions_used: Dict[str, int]
    sfx_count: int
    sfx_types_used: List[str]
    camera_motions_used: Dict[str, int]
    bgm_track: str
    voice_id: str
    real_footage_pct: float
    generic_stock_pct: float
    static_asset_pct: float
    evidence_overlays_count: int
    provenance_completeness: float
    delivery_profile: str = "CONVERSATIONAL"
    delivery_intensity: str = "MEDIUM"
    speech_rate_profile: float = 1.0
    pause_profile: str = "STANDARD"
    profanity_policy: str = "NONE"
    profanity_usage_count: int = 0
    voice_rotation_status: str = "OK"
    delivery_rotation_status: str = "OK"
    bgm_policy: str = "NONE"
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditingPlan:
    """Complete, deterministic multitrack editing blueprint for a Short."""
    job_id: str
    topic_title: str
    profile: EditingStyleProfile
    total_duration: float
    shots: List[ShotEdit] = field(default_factory=list)
    audio_mix_plan: Optional[AudioMixPlan] = None
    ass_subtitles_path: Optional[str] = None
    telemetry: Optional[EditingTelemetry] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "topic_title": self.topic_title,
            "profile": self.profile.value if isinstance(self.profile, EditingStyleProfile) else self.profile,
            "total_duration": self.total_duration,
            "shots": [s.to_dict() for s in self.shots],
            "audio_mix_plan": self.audio_mix_plan.to_dict() if self.audio_mix_plan else None,
            "ass_subtitles_path": self.ass_subtitles_path,
            "telemetry": self.telemetry.to_dict() if self.telemetry else None
        }


# AI Council & Self-Learning Strategy Interfaces
@dataclass
class EditingStrategy:
    """Directorial policy tested by the AI Council."""
    schema_version: str = "1.0.0"
    strategy_id: str = "strat_default"
    name: str = "Default Editorial Strategy"
    description: str = "Balanced editorial guidelines"
    target_profile: EditingStyleProfile = EditingStyleProfile.NEWS
    caption_density: str = "BALANCED"           # LOW, MEDIUM, HIGH, ULTRA
    pacing_speed: str = "BALANCED"              # DELIBERATE, BALANCED, AGGRESSIVE
    sfx_frequency: str = "MINIMAL"              # MINIMAL, BALANCED, DYNAMIC
    motion_intensity: float = 1.0
    target_shot_duration: float = 2.8
    min_real_footage_pct: float = 50.0
    max_generic_stock_pct: float = 35.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["target_profile"] = self.target_profile.value if isinstance(self.target_profile, EditingStyleProfile) else self.target_profile
        return d


@dataclass
class EditingDecision:
    """Individual directorial micro-decision logged for AI evaluation."""
    schema_version: str = "1.0.0"
    timestamp: float = 0.0
    decision_type: str = ""              # SUBTITLE_STYLE, POSITION, TRANSITION, MOTION, SFX, BGM, VOICE
    chosen_value: str = ""
    alternative_options: List[str] = field(default_factory=list)
    context_reason: str = ""
    narrative_role: str = "SETUP"
    emotional_intensity: str = "MEDIUM"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditingOutcome:
    """Downstream retention and performance outcome linked to an EditingPlan."""
    schema_version: str = "1.0.0"
    job_id: str = ""
    strategy_id: Optional[str] = None
    views: int = 0
    average_percentage_viewed: float = 0.0
    avg_watch_time_sec: float = 0.0
    retention_at_3s_pct: float = 0.0
    retention_at_15s_pct: float = 0.0
    completion_rate_pct: float = 0.0
    swipe_away_rate_pct: float = 0.0
    likes: int = 0
    shares: int = 0
    comments: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyEvaluation:
    """AI Council evaluation of an EditingStrategy performance."""
    schema_version: str = "1.0.0"
    evaluation_id: str = ""
    strategy_id: str = ""
    profile: EditingStyleProfile = EditingStyleProfile.NEWS
    sample_size: int = 0
    avg_retention_3s: float = 0.0
    avg_completion_rate: float = 0.0
    avg_swipe_away_rate: float = 0.0
    performance_score: float = 0.0          # 0.0 to 1.0 composite
    win_rate_vs_baseline: float = 0.0
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    status: str = "ACTIVE"                  # ACTIVE, TESTING, PROMOTED, DEPRECATED

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["profile"] = self.profile.value if isinstance(self.profile, EditingStyleProfile) else self.profile
        return d


@dataclass
class CouncilRecommendation:
    """Actionable directorial policy adjustment emitted by the AI Council."""
    schema_version: str = "1.0.0"
    recommendation_id: str = ""
    generated_at_utc: str = ""
    recommended_strategy_id: str = ""
    target_dimension: str = ""             # HOOK_PACING, SUBTITLE_DENSITY, SFX_FREQUENCY, REAL_FOOTAGE_RATIO
    adjustment_type: str = ""              # INCREASE, DECREASE, SHIFT_STYLE, TIGHTEN_COOLDOWN
    rationale: str = ""
    confidence_score: float = 0.0          # 0.0 to 1.0
    expected_retention_delta_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
