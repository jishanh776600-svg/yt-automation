"""
Versioned Editorial Template Registry for AL-AMR.
Provides centralized, data-driven registry access for:
- 20 Subtitle styles
- Evidence graphic card profiles
- Transition presets
- Sound design archetypes
- Directorial EditingStyleProfiles
"""
import logging
from typing import Dict, Any, List, Optional
from .editing_models import (
    SubtitleStyleType, SubtitleTemplate, TransitionType,
    SFXArchetype, EditingStyleProfile
)
from .subtitle_templates import SUBTITLE_TEMPLATES

logger = logging.getLogger(__name__)


# Directorial Editing Profiles Configuration
STYLE_PROFILE_CONFIGS: Dict[EditingStyleProfile, Dict[str, Any]] = {
    EditingStyleProfile.NEWS: {
        "name": "Broadcast News",
        "description": "Balanced documentary pacing, clean subtitles, authoritative delivery",
        "target_shot_duration": 2.8,
        "default_motion": "subtle_zoom_in",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.CLEAN
    },
    EditingStyleProfile.BREAKING_NEWS: {
        "name": "Breaking News",
        "description": "Immediate urgent pacing, high-contrast hook, rapid narrative progression",
        "target_shot_duration": 2.1,
        "default_motion": "punch_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.QUESTION
    },
    EditingStyleProfile.INVESTIGATIVE: {
        "name": "Investigative Exposé",
        "description": "Tense pacing, evidence focus, document callouts, dramatic reveals",
        "target_shot_duration": 2.5,
        "default_motion": "dynamic_reframe",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.EVIDENCE
    },
    EditingStyleProfile.POLITICAL_ANALYSIS: {
        "name": "Political Analysis",
        "description": "Analytical breakdown of statecraft, treaties, and political maneuvers",
        "target_shot_duration": 2.9,
        "default_motion": "slow_pan_right",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.KEYWORD_CALLOUT
    },
    EditingStyleProfile.ANALYTICAL: {
        "name": "Analytical / Data-Driven",
        "description": "Deliberate pacing for charts, statistics, and historical clarity",
        "target_shot_duration": 3.0,
        "default_motion": "slow_pan_right",
        "sfx_frequency": "MINIMAL",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.STATISTIC
    },
    EditingStyleProfile.DRAMATIC: {
        "name": "Cinematic Drama",
        "description": "High contrast, impact bursts, tension risers, and bold zooms",
        "target_shot_duration": 2.4,
        "default_motion": "punch_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.IMPACT
    },
    EditingStyleProfile.FAST_BREAKING: {
        "name": "Fast-Breaking Alert",
        "description": "Rapid cuts, energetic kinetic captions, urgent audio pacing",
        "target_shot_duration": 2.0,
        "default_motion": "punch_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "ULTRA",
        "primary_subtitle_style": SubtitleStyleType.PUNCH
    },
    EditingStyleProfile.FAST_NEWS_RECAP: {
        "name": "Fast News Recap",
        "description": "Brisk recap across multiple rapid developments",
        "target_shot_duration": 2.2,
        "default_motion": "subtle_zoom_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.PUNCH
    },
    EditingStyleProfile.EXPLAINER: {
        "name": "Educational Explainer",
        "description": "Smooth step-by-step progression, keyword callouts, and clean dissolves",
        "target_shot_duration": 2.7,
        "default_motion": "subtle_zoom_in",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.WORD_HIGHLIGHT
    },
    EditingStyleProfile.TIMELINE: {
        "name": "Chronological Timeline",
        "description": "Sequential year-by-year progression with date stamps and archival pacing",
        "target_shot_duration": 2.8,
        "default_motion": "slow_pan_left",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.DATE
    },
    EditingStyleProfile.CONTROVERSY: {
        "name": "Controversy & Debate",
        "description": "Polarized viewpoints with question hooks and dramatic reveal beats",
        "target_shot_duration": 2.5,
        "default_motion": "punch_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.QUESTION
    },
    EditingStyleProfile.STATISTIC_HEAVY: {
        "name": "Statistic Heavy",
        "description": "Data-first presentation highlighting numbers, percentages, and metrics",
        "target_shot_duration": 3.0,
        "default_motion": "subtle_zoom_in",
        "sfx_frequency": "MINIMAL",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.STATISTIC
    },
    EditingStyleProfile.QUOTE_DRIVEN: {
        "name": "Quote Driven",
        "description": "Testimony-centered editorial with verbatim quoted excerpts",
        "target_shot_duration": 3.2,
        "default_motion": "slow_pan_right",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.QUOTE
    },
    EditingStyleProfile.DOCUMENT_REVEAL: {
        "name": "Document Reveal",
        "description": "Focus on declassified archives, treaty clauses, and investigative evidence",
        "target_shot_duration": 2.7,
        "default_motion": "dynamic_reframe",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.EVIDENCE
    },
    EditingStyleProfile.REACTION_HEAVY: {
        "name": "Reaction Heavy",
        "description": "Public sentiment and cultural response driven presentation",
        "target_shot_duration": 2.3,
        "default_motion": "punch_in",
        "sfx_frequency": "DYNAMIC",
        "caption_density": "HIGH",
        "primary_subtitle_style": SubtitleStyleType.REACTION
    },
    EditingStyleProfile.HISTORICAL_CONTEXT: {
        "name": "Historical Context",
        "description": "Deep archival narrative exploring forgotten events and historical parallels",
        "target_shot_duration": 3.2,
        "default_motion": "slow_pan_left",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.CLEAN
    },
    EditingStyleProfile.HUMAN_INTEREST: {
        "name": "Human Interest & Courage",
        "description": "Poignant, emotional pacing with quote emphasis and somber tone",
        "target_shot_duration": 3.1,
        "default_motion": "slow_pan_left",
        "sfx_frequency": "MINIMAL",
        "caption_density": "BALANCED",
        "primary_subtitle_style": SubtitleStyleType.QUOTE
    }
}


class TemplateRegistry:
    """Versioned registry for all directorial templates."""

    REGISTRY_VERSION = "2.0.0"

    @classmethod
    def get_subtitle_template(cls, style: SubtitleStyleType) -> SubtitleTemplate:
        """Retrieves subtitle template definition."""
        return SUBTITLE_TEMPLATES.get(style, SUBTITLE_TEMPLATES[SubtitleStyleType.CLEAN])

    @classmethod
    def list_subtitle_styles(cls) -> List[str]:
        """Lists all registered subtitle style names."""
        return [s.value for s in SUBTITLE_TEMPLATES.keys()]

    @classmethod
    def get_profile_config(cls, profile: EditingStyleProfile) -> Dict[str, Any]:
        """Retrieves configuration parameters for an EditingStyleProfile."""
        return STYLE_PROFILE_CONFIGS.get(profile, STYLE_PROFILE_CONFIGS[EditingStyleProfile.NEWS])

    @classmethod
    def list_profiles(cls) -> List[str]:
        """Lists all available editorial profile names."""
        return [p.value for p in STYLE_PROFILE_CONFIGS.keys()]
