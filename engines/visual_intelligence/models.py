"""
Visual Intelligence Unified Models and Data Structures.
Defines canonical data contracts for visual intent, provenance, candidates,
rights classification, diversity budgets, overlays, BGM, and visual QA.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple, Set, Union
import uuid


class SourceType(str, Enum):
    """Normalized source categorization for visual retrieval hierarchy."""
    MOVIE = "MOVIE"                    # Movie, cinema, and dramatic film footage
    INTERNET_REAL = "INTERNET_REAL"    # Real event, news, official/public footage found on public internet
    ARCHIVAL = "ARCHIVAL"              # Archival footage, historical recordings, documentary
    YOUTUBE = "YOUTUBE"                # YouTube documentary, archival, and authentic event video
    STOCK = "STOCK"                    # Generic stock video (Pexels, Pixabay) - last fallback only


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


class SourceTier(str, Enum):
    """5-Tier Source Ecosystem derived from empirical reference channel forensics."""
    TIER_1_DIRECT_INSTITUTIONAL = "TIER_1_DIRECT_INSTITUTIONAL"         # NASA SVS, ESO, DVIDS, NOAA
    TIER_2_ARCHIVAL_VIDEO = "TIER_2_ARCHIVAL_VIDEO"                     # Internet Archive, Prelinger
    TIER_3_WHITELISTED_DOCUDRAMA = "TIER_3_WHITELISTED_DOCUDRAMA"       # Whitelisted YouTube docudramas & studio clips
    TIER_4_ORIGINAL_PROCEDURAL_3D = "TIER_4_ORIGINAL_PROCEDURAL_3D"     # Procedural 3D around authentic evidence
    TIER_5_SUPPORTING_STOCK = "TIER_5_SUPPORTING_STOCK"                 # Constrained stock last resort (macro nouns only)

    # Backward compatibility aliases
    TIER_1_CINEMATIC_DOCUDRAMA = "TIER_3_WHITELISTED_DOCUDRAMA"
    TIER_2_INSTITUTIONAL_ARCHIVE = "TIER_1_DIRECT_INSTITUTIONAL"
    TIER_3_MUSEUM_ACADEMIC = "TIER_4_ORIGINAL_PROCEDURAL_3D"
    TIER_4_ORIGINAL_VERIFIED = "TIER_1_DIRECT_INSTITUTIONAL"
    TIER_5_CLEAN_WEB_ARCHIVE = "TIER_2_ARCHIVAL_VIDEO"
    TIER_6_STOCK_FALLBACK = "TIER_5_SUPPORTING_STOCK"


class SourceContentClass(str, Enum):
    """Fine-grained classification of visual source content nature."""
    REAL_EVENT = "REAL_EVENT"
    REAL_SUBJECT = "REAL_SUBJECT"
    ARCHIVAL = "ARCHIVAL"
    DOCUMENTARY_REENACTMENT = "DOCUMENTARY_REENACTMENT"
    INSTITUTIONAL_VISUALIZATION = "INSTITUTIONAL_VISUALIZATION"
    ARTIFACT_DOCUMENTATION = "ARTIFACT_DOCUMENTATION"
    ORIGINAL_ON_LOCATION = "ORIGINAL_ON_LOCATION"
    CUSTOM_3D = "CUSTOM_3D"
    PROCEDURAL_3D = "PROCEDURAL_3D"
    ACADEMIC_EVIDENCE = "ACADEMIC_EVIDENCE"
    MANUSCRIPT_ARTIFACT = "MANUSCRIPT_ARTIFACT"
    STOCK_CONTEXT = "STOCK_CONTEXT"
    EXPLAINER = "EXPLAINER"
    TALKING_HEAD = "TALKING_HEAD"
    PODCAST = "PODCAST"
    LECTURE = "LECTURE"
    REACTION = "REACTION"
    FLAT_GRAPHIC = "FLAT_GRAPHIC"
    STATIC_IMAGE = "STATIC_IMAGE"
    TITLE_CARD = "TITLE_CARD"
    SOURCE_BRANDING = "SOURCE_BRANDING"
    UNKNOWN = "UNKNOWN"


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
    source_tier: Optional[SourceTier] = None
    source_content_class: Optional[SourceContentClass] = None
    archival_authenticity_exception: bool = False
    evidence_requirement: Optional[str] = None
    original_owner: Optional[str] = None
    channel_name: Optional[str] = None
    channel_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else self.rights_status
        if self.source_tier:
            d["source_tier"] = self.source_tier.value if isinstance(self.source_tier, SourceTier) else str(self.source_tier)
        if self.source_content_class:
            d["source_content_class"] = self.source_content_class.value if isinstance(self.source_content_class, SourceContentClass) else str(self.source_content_class)
        return d


@dataclass
class VisualIntent:
    """Explicit visual requirements for a single narrative beat."""
    beat_id: str
    beat_index: int
    narration_text: str
    start_time: float = 0.0
    end_time: float = 3.0
    duration: float = 3.0
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
    search_queries: List[str] = field(default_factory=list)
    era: Optional[str] = None
    environment: Optional[str] = None
    weather: Optional[str] = None
    time_of_day: Optional[str] = None
    mood: Optional[str] = None
    subject: Optional[str] = None
    historical_classification: str = "HISTORICAL"   # HISTORICAL, MODERN, TIMELESS
    architectural_requirements: Optional[str] = None
    clothing_requirements: Optional[str] = None
    forbidden_content: List[str] = field(default_factory=list)
    visual_action: Optional[str] = None
    target_object: Optional[str] = None
    people_actors: List[str] = field(default_factory=list)
    historical_context: Optional[str] = None
    important_nouns: List[str] = field(default_factory=list)
    important_verbs: List[str] = field(default_factory=list)
    disambiguating_terms: List[str] = field(default_factory=list)
    is_person_entity: bool = False

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
class TemporalWindow:
    """Analyzed temporal sub-window of a candidate video."""
    start_time: float
    end_time: float
    duration: float
    motion_score: float = 0.50
    action_score: float = 0.50
    stability_score: float = 0.80
    repetition_penalty: float = 0.0
    composite_score: float = 0.0
    matched_cues: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedVideoCandidate:
    """
    Normalized candidate representation for internet video retrieval.
    Guarantees structural priority: MOVIE / INTERNET_REAL / ARCHIVAL > STOCK.
    """
    source_name: str
    source_type: SourceType
    title: str
    description: Optional[str] = None
    page_url: str = ""
    media_url: str = ""
    thumbnail_url: Optional[str] = None
    duration: float = 0.0
    width: int = 1080
    height: int = 1920
    codec: Optional[str] = None
    discovered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    query_used: str = ""
    provenance_metadata: Dict[str, Any] = field(default_factory=dict)
    local_path: Optional[str] = None
    local_clip_path: Optional[str] = None
    selected_window_start: Optional[float] = None
    selected_window_end: Optional[float] = None
    is_video: bool = True
    source_tier: Optional[SourceTier] = None
    source_content_class: Optional[SourceContentClass] = None
    archival_authenticity_exception: bool = False
    evidence_requirement: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["source_type"] = self.source_type.value if isinstance(self.source_type, SourceType) else str(self.source_type)
        if self.source_tier:
            d["source_tier"] = self.source_tier.value if isinstance(self.source_tier, SourceTier) else str(self.source_tier)
        if self.source_content_class:
            d["source_content_class"] = self.source_content_class.value if isinstance(self.source_content_class, SourceContentClass) else str(self.source_content_class)
        return d

    def to_visual_candidate(self) -> "VisualCandidate":
        cid = f"cand_{uuid.uuid4().hex[:8]}"
        aid = f"ast_{uuid.uuid4().hex[:8]}"
        source_class = "SOURCE_A_CINEMATIC" if self.source_type == SourceType.MOVIE else (
            "SOURCE_B_YOUTUBE" if self.source_type == SourceType.YOUTUBE else (
                "SOURCE_A" if self.source_type == SourceType.STOCK else "SOURCE_B"
            )
        )
        content_type = VisualContentType.ARCHIVAL_VIDEO if self.source_type == SourceType.ARCHIVAL else (
            VisualContentType.GENERIC_STOCK_VIDEO if self.source_type == SourceType.STOCK else VisualContentType.REAL_VIDEO
        )
        prov = VisualProvenance(
            asset_id=aid,
            source=self.source_name,
            source_url=self.page_url or self.media_url,
            media_url=self.media_url,
            title=self.title,
            creator=self.provenance_metadata.get("creator"),
            publisher=self.provenance_metadata.get("publisher"),
            publication_date=self.provenance_metadata.get("publication_date"),
            license_name=self.provenance_metadata.get("license", "Verified Video"),
            rights_status=RightsStatus(self.provenance_metadata.get("rights_status", RightsStatus.LICENSED.value)) if self.provenance_metadata.get("rights_status") in [s.value for s in RightsStatus] else RightsStatus.LICENSED,
            content_type=content_type,
            duration=self.duration,
            source_tier=self.source_tier,
            source_content_class=self.source_content_class
        )
        return VisualCandidate(
            candidate_id=cid,
            source_class=source_class,
            source_name=self.source_name,
            source_url=self.page_url or self.media_url,
            media_url=self.media_url,
            local_path=self.local_path,
            title=self.title,
            description=self.description or "",
            content_type=content_type,
            rights_status=prov.rights_status,
            license_name=prov.license_name,
            creator=prov.creator,
            publisher=prov.publisher,
            width=self.width,
            height=self.height,
            duration_sec=self.duration,
            is_video=self.is_video,
            provenance=prov,
            source_type=self.source_type,
            source_tier=self.source_tier,
            source_content_class=self.source_content_class,
            metadata={"query_used": self.query_used, **self.provenance_metadata}
        )

    @classmethod
    def from_visual_candidate(cls, cand: "VisualCandidate", query_used: str = "") -> "NormalizedVideoCandidate":
        st = cand.source_type
        if not st:
            if "youtube" in cand.source_name.lower() or "youtube" in (cand.source_url or "").lower():
                st = SourceType.YOUTUBE
            elif "movie" in cand.source_name.lower():
                st = SourceType.MOVIE
            elif cand.source_name in ("pexels", "pixabay") or cand.content_type in (VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE):
                st = SourceType.STOCK
            elif cand.source_name in ("archive", "internet_archive", "wikimedia") or cand.content_type == VisualContentType.ARCHIVAL_VIDEO:
                st = SourceType.ARCHIVAL
            else:
                st = SourceType.INTERNET_REAL

        prov_meta = {}
        if cand.provenance:
            prov_meta = {
                "creator": cand.provenance.creator,
                "publisher": cand.provenance.publisher,
                "license": cand.provenance.license_name,
                "rights_status": cand.provenance.rights_status.value if isinstance(cand.provenance.rights_status, RightsStatus) else cand.provenance.rights_status,
                "publication_date": getattr(cand.provenance, "publication_date", None)
            }
        return cls(
            source_name=cand.source_name,
            source_type=st,
            title=cand.title,
            description=cand.description,
            page_url=cand.source_url,
            media_url=cand.media_url or "",
            duration=cand.duration_sec,
            width=cand.width,
            height=cand.height,
            query_used=query_used or cand.metadata.get("query_used", ""),
            provenance_metadata=prov_meta,
            local_path=cand.local_path,
            is_video=cand.is_video,
            source_tier=cand.source_tier or (cand.provenance.source_tier if cand.provenance else None),
            source_content_class=cand.source_content_class or (cand.provenance.source_content_class if cand.provenance else None)
        )


@dataclass
class VisualCandidate:
    """Standardized visual candidate retrieved from any source tier."""
    candidate_id: str
    source_class: str                           # SOURCE_A, SOURCE_B, SOURCE_C, SOURCE_D
    source_name: str                            # pexels, wikimedia, editorial, archive, official, contextual, reaction
    source_url: str
    media_url: Optional[str] = None
    local_path: Optional[str] = None
    local_clip_path: Optional[str] = None
    selected_window_start: Optional[float] = None
    selected_window_end: Optional[float] = None
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
    source_type: Optional[SourceType] = None
    source_tier: Optional[SourceTier] = None
    source_content_class: Optional[SourceContentClass] = None
    archival_authenticity_exception: bool = False
    evidence_requirement: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["content_type"] = self.content_type.value if isinstance(self.content_type, VisualContentType) else self.content_type
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else self.rights_status
        if self.source_type:
            d["source_type"] = self.source_type.value if isinstance(self.source_type, SourceType) else str(self.source_type)
        if self.source_tier:
            d["source_tier"] = self.source_tier.value if isinstance(self.source_tier, SourceTier) else str(self.source_tier)
        if self.source_content_class:
            d["source_content_class"] = self.source_content_class.value if isinstance(self.source_content_class, SourceContentClass) else str(self.source_content_class)
        if self.provenance:
            d["provenance"] = self.provenance.to_dict()
        return d

    def to_normalized_candidate(self, query_used: str = "") -> "NormalizedVideoCandidate":
        return NormalizedVideoCandidate.from_visual_candidate(self, query_used=query_used)


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
