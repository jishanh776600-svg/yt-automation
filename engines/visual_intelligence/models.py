"""
Visual Intelligence Unified Models and Data Structures.
Defines canonical data contracts for visual intent, provenance, candidates,
rights classification, diversity budgets, overlays, BGM, and visual QA.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Set


class RightsStatus(str, Enum):
    """Explicit legal / licensing status of visual material."""
    LICENSED = "LICENSED"                          # Verified API/stock license (e.g. Pexels, CC0, Commercial)
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"                # Pre-1929, CC0, or official government work
    PERMISSION_BASED = "PERMISSION_BASED"          # Explicit CC-BY / CC-BY-SA with commercial permission
    RIGHTS_UNCERTAIN = "RIGHTS_UNCERTAIN"          # Unverified web find; requires fallback
    TRANSFORMATIVE_EDITORIAL = "TRANSFORMATIVE"    # Commentary / news reporting with full provenance
    FAIR_USE_REVIEW = "FAIR_USE_REVIEW"            # Fair use review requirement


class VisualContentType(str, Enum):
    """Categorization of visual format and capture nature."""
    REAL_VIDEO = "REAL_VIDEO"                      # Live-action / real-world video capture
    LIVE_EVENT_FOOTAGE = "LIVE_EVENT_FOOTAGE"      # Press conference, speech, rally, hearing
    ARCHIVAL_VIDEO = "ARCHIVAL_VIDEO"              # Historical / news archive footage
    OFFICIAL_PUBLIC_RECORD = "OFFICIAL_RECORD"     # Government / institutional documentary record
    ANIMATED_DATA_MAP = "ANIMATED_DATA_MAP"        # Procedural / animated charts, graphs, maps
    SCREENSHOT_DOCUMENT = "SCREENSHOT_DOCUMENT"    # Headline, treaty, public filing, document
    STATIC_PHOTO = "STATIC_PHOTO"                  # Still photograph (high-resolution real world)
    GENERIC_STOCK_VIDEO = "GENERIC_STOCK_VIDEO"    # Generic B-roll video
    GENERIC_STOCK_IMAGE = "GENERIC_STOCK_IMAGE"    # Generic stock illustration or photo
    MEME_REACTION = "MEME_REACTION"                # Contextual reaction visual / expressive clip


@dataclass
class VisualProvenance:
    """Immutable provenance and rights record attached to every candidate."""
    asset_id: str
    source: str                                     # Adapter/Platform identifier (e.g. pexels, wikimedia, archive, official)
    source_url: str                                 # Canonical reference URL
    media_url: Optional[str] = None                 # Direct asset file URL or local path
    title: str = ""
    creator: Optional[str] = None                   # Photographer, author, agency
    publisher: Optional[str] = None                 # Publisher, archive, or institution
    publication_date: Optional[str] = None
    license_name: str = "Commercial Zero-Cost"
    rights_status: RightsStatus = RightsStatus.LICENSED
    content_type: Optional[VisualContentType] = None
    retrieval_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolution: Tuple[int, int] = (1080, 1920)
    duration: float = 4.0
    entity_matches: List[str] = field(default_factory=list)
    event_matches: List[str] = field(default_factory=list)
    attribution_required: bool = False
    attribution_text: Optional[str] = None
    confidence_score: float = 1.0                   # Confidence in rights and authenticity (0.0 - 1.0)
    topic_id: Optional[str] = None
    usage_count: int = 0
    last_used_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else self.rights_status
        return d


@dataclass
class VisualIntent:
    """Explicit visual requirements for a single narrative beat."""
    beat_id: str
    beat_index: int
    narration_text: str
    start_time: float
    end_time: float
    duration: float
    primary_entity: Optional[str] = None
    secondary_entities: List[str] = field(default_factory=list)
    event: Optional[str] = None
    location: Optional[str] = None
    date_context: Optional[str] = None
    action: Optional[str] = None
    claim_discussed: Optional[str] = None
    emotional_tone: str = "SERIOUS"              # SERIOUS, DRAMATIC, TENSE, REVEAL, URGENT, LIGHT
    visual_intent: str = "DOCUMENTARY"           # DOCUMENTARY, EVIDENCE, REVEAL, ATMOSPHERIC, REACTION
    preferred_visual_type: VisualContentType = VisualContentType.REAL_VIDEO
    preferred_source: str = "real_footage"        # real_footage, event_news, archival, official, document, reaction, generic_stock
    evidence_required: bool = False
    minimum_motion_requirement: float = 0.50     # 0.0 (static ok) to 0.85+ (strict video required)
    search_queries: List[str] = field(default_factory=list)

    # Backwards-compatibility aliases
    @property
    def required_visual_type(self) -> VisualContentType:
        return self.preferred_visual_type

    @property
    def preferred_source_tier(self) -> str:
        tier_map = {
            "real_footage": "SOURCE_A",
            "event_news": "SOURCE_B",
            "archival": "SOURCE_C",
            "official": "SOURCE_C",
            "document": "SOURCE_C",
            "reaction": "SOURCE_D",
            "generic_stock": "SOURCE_A"
        }
        return tier_map.get(self.preferred_source, "SOURCE_A")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["preferred_visual_type"] = self.preferred_visual_type.value if isinstance(self.preferred_visual_type, VisualContentType) else self.preferred_visual_type
        return d


@dataclass
class VisualCandidate:
    """Standardized visual candidate retrieved from any source tier."""
    candidate_id: str
    source_class: str                           # SOURCE_A, SOURCE_B, SOURCE_C, SOURCE_D
    source_name: str                            # pexels, wikimedia, editorial, archive, official, contextual, reaction
    source_url: str
    media_url: Optional[str] = None
    local_path: Optional[str] = None
    title: str = ""
    description: str = ""
    content_type: VisualContentType = VisualContentType.REAL_VIDEO
    rights_status: RightsStatus = RightsStatus.LICENSED
    license_name: str = "Unknown"
    creator: Optional[str] = None
    publisher: Optional[str] = None
    width: int = 1080
    height: int = 1920
    duration_sec: float = 4.0
    fps: int = 24
    motion_score: float = 1.0                   # 0.0 (static) to 1.0 (high-motion video)
    raw_score: float = 0.0
    final_score: float = 0.0
    is_video: bool = True
    entity_tags: List[str] = field(default_factory=list)
    event_tags: List[str] = field(default_factory=list)
    provenance: Optional[VisualProvenance] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["content_type"] = self.content_type.value if isinstance(self.content_type, VisualContentType) else self.content_type
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else self.rights_status
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d


@dataclass
class EvidenceOverlaySpec:
    """Specification for rendering authentic evidence/provenance lower-third overlays."""
    overlay_type: str                            # source, date, location, headline, quote, statistic, document, map, event
    label: str                                   # Short badge text (e.g. 'ARCHIVAL RECORD', 'LIVE BRIEFING')
    headline_text: Optional[str] = None
    quote_text: Optional[str] = None
    stat_text: Optional[str] = None
    attribution_text: Optional[str] = None
    date_text: Optional[str] = None
    require_provenance: bool = False
    source_name: Optional[str] = None
    date_str: Optional[str] = None
    location_str: Optional[str] = None
    citation_url: Optional[str] = None
    display_start: float = 0.2                   # Delay relative to beat start
    display_duration: float = 2.4                # Overlay duration in seconds
    confidence: float = 1.0


@dataclass
class BGMTrack:
    """BGM track record with full metadata and usage tracking."""
    track_id: str
    title: str
    license_name: str
    source: str
    mood: str                                    # TENSE, DRAMATIC, URGENT, INTRIGUING, INSPIRING, SOMBER
    energy: float                                # 0.0 - 1.0
    tempo: int                                   # BPM
    genre: str                                   # Orchestral, Cinematic Synth, Dark Ambient, Pulse
    intensity: str                               # LOW, MEDIUM, HIGH, CLIMACTIC
    loopability: bool = True
    editorial_suitability: List[str] = field(default_factory=list)
    usage_count: int = 0
    last_used_at: Optional[str] = None
    local_path: Optional[str] = None


@dataclass
class VoiceProfile:
    """Narrator voice definition for anti-monotony rotation."""
    voice_id: str
    name: str
    gender: str
    tone: str                                    # DOCUMENTARY, AUTHORITATIVE, DRAMATIC, CONVERSATIONAL
    default_speed: float = 1.0
    energy_range: Tuple[float, float] = (0.5, 0.9)
    description: str = ""
    suitability_tags: List[str] = field(default_factory=list)
    usage_count: int = 0
    last_used_at: Optional[str] = None


@dataclass
class VisualQAResult:
    """Measurable QA gate metrics for the assembled visual storyboard."""
    passed: bool
    score: float
    real_footage_pct: float
    generic_stock_pct: float
    static_asset_pct: float
    avg_motion_score: float
    duplicate_clip_count: int
    near_duplicate_count: int
    rights_risk_count: int
    evidence_attribution_failures: int
    frozen_frame_pct: float
    bgm_repetition: bool
    voice_repetition: bool
    provenance_completeness: float
    failure_reasons: List[str] = field(default_factory=list)
    telemetry: Dict[str, Any] = field(default_factory=dict)
