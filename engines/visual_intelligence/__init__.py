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

from .models import (
    EvidenceOverlaySpec,
    BGMTrack,
    VoiceProfile,
    VisualQAResult,
    TemporalWindow,
    NormalizedVideoCandidate,
    SourceType,
)
from .temporal_extractor import TemporalMomentRetriever
from .framing import IntelligentFramingEngine, FramingSpec, EditorialCropStrategy
from .editing import AdvancedEditorialEngine
from .memory import (
    VisualMemoryManager,
    VisualFingerprinter,
    VisualMemoryEvaluation,
    normalize_visual_url,
    calculate_temporal_overlap,
    compute_recency_penalty,
)
from .composition import (
    EditorialCompositionEngine,
    NarrationTimelineBuilder,
    NarrationTimeline,
    SynchronizedShot,
    EditorialComposition,
    ActionAnchorAligner,
)
from .adaptive_retrieval import (
    RetrievalBudget,
    AdaptiveQueryExpander,
    StagedStreamIngester,
    ParallelVideoRetriever,
    RetrievalTelemetryRecord,
    RetrievalTelemetryCollector,
)
from .internet_retrieval import (
    InternetVideoRetriever,
    BaseVideoRetrievalProvider,
    MovieRetrievalProvider,
    InternetRealRetrievalProvider,
    ArchivalRetrievalProvider,
    StockVideoFallbackProvider,
)
from .cache import (
    CanonicalAssetCache,
    ProviderCircuitBreaker,
    get_canonical_cache,
    get_circuit_breaker,
)

__all__ = [
    "VisualProvenance",
    "RightsStatus",
    "VisualContentType",
    "VisualIntent",
    "VisualIntentExtractor",
    "VisualCandidate",
    "VisualCandidateScorer",
    "TemporalWindow",
    "TemporalMomentRetriever",
    "IntelligentFramingEngine",
    "FramingSpec",
    "EditorialCropStrategy",
    "VisualMemoryManager",
    "VisualFingerprinter",
    "VisualMemoryEvaluation",
    "normalize_visual_url",
    "calculate_temporal_overlap",
    "compute_recency_penalty",
    "EditorialCompositionEngine",
    "NarrationTimelineBuilder",
    "NarrationTimeline",
    "SynchronizedShot",
    "EditorialComposition",
    "ActionAnchorAligner",
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
    "RetrievalBudget",
    "AdaptiveQueryExpander",
    "StagedStreamIngester",
    "ParallelVideoRetriever",
    "RetrievalTelemetryRecord",
    "RetrievalTelemetryCollector",
    "InternetVideoRetriever",
    "BaseVideoRetrievalProvider",
    "MovieRetrievalProvider",
    "InternetRealRetrievalProvider",
    "ArchivalRetrievalProvider",
    "StockVideoFallbackProvider",
]


