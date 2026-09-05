"""
Visual Intelligence Provenance & Rights Classification.
Defines canonical data structures for tracking asset origin, licensing,
re-use permissions, and editorial evidence attribution.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any


class RightsStatus(str, Enum):
    """Explicit legal / licensing status of visual material."""
    LICENSED = "LICENSED"                          # Verified API/stock license (e.g. Pexels, Shutterstock)
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"                # CC0, pre-1929, US Government work
    PERMISSION_BASED = "PERMISSION_BASED"          # Explicit CC-BY, CC-BY-SA with commercial permission
    RIGHTS_UNCERTAIN = "RIGHTS_UNCERTAIN"          # Unverified web find; requires review / fallback
    TRANSFORMATIVE_EDITORIAL = "TRANSFORMATIVE"    # Used strictly for commentary/news reporting with full provenance


class VisualContentType(str, Enum):
    """Categorization of visual format and capture nature."""
    REAL_VIDEO = "REAL_VIDEO"                      # Live-action / real-world video capture
    LIVE_EVENT_FOOTAGE = "LIVE_EVENT_FOOTAGE"      # Press conference, speech, rally, hearing
    ARCHIVAL_VIDEO = "ARCHIVAL_VIDEO"              # Historical / news archive footage
    ANIMATED_DATA_MAP = "ANIMATED_DATA_MAP"        # Procedural / animated charts, graphs, maps
    SCREENSHOT_DOCUMENT = "SCREENSHOT_DOCUMENT"    # Article headline, public record, treaty, filing
    STATIC_PHOTO = "STATIC_PHOTO"                  # Still photograph (high-resolution real world)
    GENERIC_STOCK_VIDEO = "GENERIC_STOCK_VIDEO"    # Generic B-roll video
    GENERIC_STOCK_IMAGE = "GENERIC_STOCK_IMAGE"    # Generic stock illustration or photo
    MEME_REACTION = "MEME_REACTION"                # Contextual humorous reaction / expressive clip


@dataclass
class VisualProvenance:
    """Immutable provenance record attached to every candidate and acquired asset."""
    asset_id: str
    source: str                                     # Adapter/Platform identifier (e.g. pexels, wikimedia, news_archive)
    source_url: str                                 # Canonical URL or URI
    creator: Optional[str] = None                   # Artist / Photographer / Videographer
    publisher: Optional[str] = None                 # Publication / Agency / Host
    rights_status: RightsStatus = RightsStatus.LICENSED
    license_name: str = "Commercial Zero-Cost"
    acquired_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    content_type: VisualContentType = VisualContentType.REAL_VIDEO
    attribution_required: bool = False
    attribution_text: Optional[str] = None
    confidence_score: float = 1.0                   # Confidence in rights / authenticity (0.0 - 1.0)
    topic_id: Optional[str] = None
    entity_ids: List[str] = field(default_factory=list)
    event_ids: List[str] = field(default_factory=list)
    usage_count: int = 0
    last_used_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["rights_status"] = self.rights_status.value if isinstance(self.rights_status, RightsStatus) else self.rights_status
        d["content_type"] = self.content_type.value if isinstance(self.content_type, VisualContentType) else self.content_type
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualProvenance":
        d = dict(data)
        if "rights_status" in d and isinstance(d["rights_status"], str):
            try:
                d["rights_status"] = RightsStatus(d["rights_status"])
            except ValueError:
                d["rights_status"] = RightsStatus.RIGHTS_UNCERTAIN
        if "content_type" in d and isinstance(d["content_type"], str):
            try:
                d["content_type"] = VisualContentType(d["content_type"])
            except ValueError:
                d["content_type"] = VisualContentType.GENERIC_STOCK_VIDEO
        return cls(**d)
