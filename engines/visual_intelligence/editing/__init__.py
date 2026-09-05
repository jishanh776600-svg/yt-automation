"""
Advanced Editorial Engine for AL-AMR Visual Intelligence.
Provides deterministic, intelligence-driven video editing:
- Multitrack timeline composition
- Multi-style ASS subtitles (multiple styles per Short)
- Dynamic collision-free subtitle positioning
- Camera motions, keyframing, and spring physics easing
- Restrained, anti-repetition transitions
- Semantic sound design (SFX) with frequency caps
- Audio hierarchy & dynamic BGM ducking
- Subject-aware 9:16 vertical reframing
- AI Council telemetry & strategy evaluation
"""
from .editing_models import (
    MotionType, EasingType, Keyframe, CameraMotionSpec,
    TransitionType, TransitionSpec,
    SubtitleStyleType, SubtitlePositionType, SubtitleWord, SubtitleCue, SubtitleTemplate,
    SFXArchetype, SFXCueSpec,
    AudioTrackSpec, AudioMixPlan,
    ReframingSpec,
    EditingStyleProfile, ShotEdit, EditingPlan,
    EditingStrategy, EditingDecision, EditingTelemetry, EditingOutcome
)
from .subtitle_templates import (
    SUBTITLE_TEMPLATES, get_subtitle_template, generate_ass_style_header
)
from .style_selector import SubtitleStyleSelector, EditingStyleSelector
from .position_engine import SubtitlePositionEngine
from .subtitle_engine import MultiStyleSubtitleEngine
from .motion_engine import MotionEngine, spring_physics, ease_in_out_cubic
from .transition_engine import TransitionEngine
from .sfx_engine import SFXEngine
from .audio_mixer import AudioDirector
from .reframing_engine import ReframingEngine
from .editing_rhythm import EditingRhythmEngine
from .timeline import MultitrackTimeline, TimelineValidationError
from .template_registry import TemplateRegistry
from .telemetry import EditingTelemetryCollector
from .editor import AdvancedEditorialEngine

__all__ = [
    # Models
    "MotionType",
    "EasingType",
    "Keyframe",
    "CameraMotionSpec",
    "TransitionType",
    "TransitionSpec",
    "SubtitleStyleType",
    "SubtitlePositionType",
    "SubtitleWord",
    "SubtitleCue",
    "SubtitleTemplate",
    "SFXArchetype",
    "SFXCueSpec",
    "AudioTrackSpec",
    "AudioMixPlan",
    "ReframingSpec",
    "EditingStyleProfile",
    "ShotEdit",
    "EditingPlan",
    "EditingStrategy",
    "EditingDecision",
    "EditingTelemetry",
    "EditingOutcome",
    # Engines & Registries
    "SUBTITLE_TEMPLATES",
    "get_subtitle_template",
    "generate_ass_style_header",
    "SubtitleStyleSelector",
    "EditingStyleSelector",
    "SubtitlePositionEngine",
    "MultiStyleSubtitleEngine",
    "MotionEngine",
    "spring_physics",
    "ease_in_out_cubic",
    "TransitionEngine",
    "SFXEngine",
    "AudioDirector",
    "ReframingEngine",
    "EditingRhythmEngine",
    "MultitrackTimeline",
    "TimelineValidationError",
    "TemplateRegistry",
    "EditingTelemetryCollector",
    "AdvancedEditorialEngine",
]
