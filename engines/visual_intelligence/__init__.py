"""
Visual Intelligence & Real-Footage Engine for AL-AMR.
Provides editorial story-beat deconstruction, multi-source acquisition (Classes A-D),
deterministic multi-factor scoring, video-first motion preference, anti-repetition control,
evidence overlays, BGM intelligence, voice variation, and visual QA gates.
"""
from .provenance import VisualProvenance, RightsStatus, VisualContentType
from .intent_extractor import VisualIntent, VisualIntentExtractor
from .scoring import VisualCandidateScorer, VisualCandidate
from .diversity import (
    VisualDiversityController,
    compute_dhash,
    hamming_distance,
    is_near_duplicate,
    detect_near_duplicates,
)
from .overlay_engine import EvidenceOverlayEngine
from .bgm_selector import BGMSelector
from .voice_policy import VoiceVariationPolicy
from .visual_qa import VisualQAGate

from .source_router import SourceRouter
from .models import EvidenceOverlaySpec, BGMTrack, VoiceProfile, VisualQAResult
from .editing import AdvancedEditorialEngine

__all__ = [
    "VisualProvenance",
    "RightsStatus",
    "VisualContentType",
    "VisualIntent",
    "VisualIntentExtractor",
    "VisualCandidate",
    "VisualCandidateScorer",
    "VisualDiversityController",
    "compute_dhash",
    "hamming_distance",
    "is_near_duplicate",
    "detect_near_duplicates",
    "EvidenceOverlayEngine",
    "EvidenceOverlaySpec",
    "BGMSelector",
    "BGMTrack",
    "VoiceVariationPolicy",
    "VoiceProfile",
    "VisualQAGate",
    "VisualQAResult",
    "SourceRouter",
    "AdvancedEditorialEngine",
]


