"""
Visual Models and Data Contracts for Phase 4 Real-Event Visual Retrieval.
Defines machine-readable data structures for:
- VisualEvidenceCandidate: Structured visual candidate with granular scoring and provenance
- VisualAuthenticity: Strict classification (EVENT_SPECIFIC, EVENT_RELATED, CONTEXTUAL, GENERIC)
- VisualLicensingStatus: Explicit legal/licensing classification
- BeatVisualPlan: Beat-level visual evidence assignment and candidate pool
- VisualEvidencePlan: Full Short visual evidence compilation and coverage audit
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional, Set


class VisualAuthenticity(str, Enum):
    """Authenticity level relative to the specific reported real-world event."""
    EVENT_SPECIFIC = "EVENT_SPECIFIC"      # Depicts the exact reported real-world event
    EVENT_RELATED = "EVENT_RELATED"        # Directly related to the incident/vessel/entity/location
    CONTEXTUAL = "CONTEXTUAL"              # Authentic real-world footage of entity/country, not this event
    GENERIC = "GENERIC"                    # Generic stock footage; must NEVER be labeled event-specific


class VisualLicensingStatus(str, Enum):
    """Explicit legal licensing status of visual material."""
    LICENSE_CONFIRMED = "LICENSE_CONFIRMED"          # Confirmed commercial/editorial reuse license
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"                  # Government official work, pre-1929, CC0
    CREATIVE_COMMONS = "CREATIVE_COMMONS"            # CC-BY, CC-BY-SA with attribution
    STOCK_API_LICENSE = "STOCK_API_LICENSE"          # Verified stock provider license (e.g. Pexels)
    RESTRICTED = "RESTRICTED"                        # Copyrighted / all rights reserved; requires editorial review
    LICENSE_UNKNOWN = "LICENSE_UNKNOWN"              # Unverified; must NEVER be assumed safe


class VisualCoverageType(str, Enum):
    """Coverage status for an individual script beat."""
    DIRECT_EVIDENCE = "DIRECT_EVIDENCE"    # Backed by EVENT_SPECIFIC visual
    RELATED_EVIDENCE = "RELATED_EVIDENCE"  # Backed by EVENT_RELATED visual
    CONTEXTUAL = "CONTEXTUAL"              # Backed by CONTEXTUAL visual
    NO_VISUAL = "NO_VISUAL"                # No suitable footage found; explicitly recorded without padding


@dataclass
class VisualEvidenceCandidate:
    """Standardized visual evidence candidate retrieved from cloud sources."""
    visual_id: str
    event_id: str
    beat_id: str
    source_type: str                         # OFFICIAL_GOVERNMENT, WIRE_SERVICE, NEWS_BROADCAST, STOCK_API, ARCHIVE
    source_publisher: str                    # DVIDS, Reuters, AP, Danish Navy, Pexels, etc.
    source_url: str                          # Canonical web page URL
    media_url: str                           # Direct media/stream URL
    title: str
    description: str
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None
    event_occurred_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    visual_type: str = "VIDEO"               # VIDEO, PHOTO, DOCUMENT_SCREENSHOT, MAP
    match_score: float = 0.0                 # Composite visual match score (0.0 - 1.0)
    event_specificity_score: float = 0.0     # Specificity to this exact event (0.0 - 1.0)
    entity_match_score: float = 0.0          # Overlap with EventCard entities
    location_match_score: float = 0.0        # Geographic consistency score
    temporal_match_score: float = 0.0        # Temporal proximity score
    action_match_score: float = 0.0          # Action verb match score
    source_reliability_score: float = 1.0    # Source reliability weight
    authenticity: str = VisualAuthenticity.CONTEXTUAL.value
    licensing_status: str = VisualLicensingStatus.LICENSE_UNKNOWN.value
    provenance: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    retrieval_status: str = "AVAILABLE"      # AVAILABLE, FETCHED, REJECTED, NO_SUITABLE_VISUAL
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "visual_id": self.visual_id,
            "event_id": self.event_id,
            "beat_id": self.beat_id,
            "source_type": self.source_type,
            "source_publisher": self.source_publisher,
            "source_url": self.source_url,
            "media_url": self.media_url,
            "thumbnail_url": self.thumbnail_url,
            "title": self.title,
            "description": self.description,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "event_occurred_at": self.event_occurred_at.isoformat() if self.event_occurred_at else None,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None,
            "visual_type": self.visual_type,
            "match_score": round(self.match_score, 3),
            "event_specificity_score": round(self.event_specificity_score, 3),
            "entity_match_score": round(self.entity_match_score, 3),
            "location_match_score": round(self.location_match_score, 3),
            "temporal_match_score": round(self.temporal_match_score, 3),
            "action_match_score": round(self.action_match_score, 3),
            "source_reliability_score": round(self.source_reliability_score, 3),
            "authenticity": self.authenticity,
            "licensing_status": self.licensing_status,
            "provenance": self.provenance,
            "confidence": round(self.confidence, 3),
            "retrieval_status": self.retrieval_status,
            "rejection_reason": self.rejection_reason
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualEvidenceCandidate":
        def parse_dt(v):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(v)
            except Exception:
                return None

        return cls(
            visual_id=data.get("visual_id", f"vis_{uuid.uuid4().hex[:10]}"),
            event_id=data.get("event_id", "unknown_event"),
            beat_id=data.get("beat_id", "unknown_beat"),
            source_type=data.get("source_type", "STOCK_API"),
            source_publisher=data.get("source_publisher", "Unknown Publisher"),
            source_url=data.get("source_url", ""),
            media_url=data.get("media_url", ""),
            thumbnail_url=data.get("thumbnail_url"),
            title=data.get("title", ""),
            description=data.get("description", ""),
            discovered_at=parse_dt(data.get("discovered_at")) or datetime.now(timezone.utc),
            published_at=parse_dt(data.get("published_at")),
            event_occurred_at=parse_dt(data.get("event_occurred_at")),
            visual_type=data.get("visual_type", "VIDEO"),
            match_score=float(data.get("match_score", 0.0)),
            event_specificity_score=float(data.get("event_specificity_score", 0.0)),
            entity_match_score=float(data.get("entity_match_score", 0.0)),
            location_match_score=float(data.get("location_match_score", 0.0)),
            temporal_match_score=float(data.get("temporal_match_score", 0.0)),
            action_match_score=float(data.get("action_match_score", 0.0)),
            source_reliability_score=float(data.get("source_reliability_score", 1.0)),
            authenticity=data.get("authenticity", VisualAuthenticity.CONTEXTUAL.value),
            licensing_status=data.get("licensing_status", VisualLicensingStatus.LICENSE_UNKNOWN.value),
            provenance=data.get("provenance", {}),
            confidence=float(data.get("confidence", 1.0)),
            retrieval_status=data.get("retrieval_status", "AVAILABLE"),
            rejection_reason=data.get("rejection_reason")
        )


@dataclass
class BeatVisualPlan:
    """Visual evidence plan for a single script beat."""
    beat_id: str
    sequence: int
    beat_text: str
    coverage_type: str = VisualCoverageType.NO_VISUAL.value
    selected_candidate: Optional[VisualEvidenceCandidate] = None
    candidate_pool: List[VisualEvidenceCandidate] = field(default_factory=list)
    target_query: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "sequence": self.sequence,
            "beat_text": self.beat_text,
            "coverage_type": self.coverage_type,
            "selected_candidate": self.selected_candidate.to_dict() if self.selected_candidate else None,
            "candidate_pool": [c.to_dict() for c in self.candidate_pool],
            "target_query": self.target_query
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeatVisualPlan":
        sel = None
        if data.get("selected_candidate"):
            sel = VisualEvidenceCandidate.from_dict(data["selected_candidate"])
        pool = [VisualEvidenceCandidate.from_dict(c) for c in data.get("candidate_pool", [])]
        return cls(
            beat_id=data.get("beat_id", ""),
            sequence=int(data.get("sequence", 0)),
            beat_text=data.get("beat_text", ""),
            coverage_type=data.get("coverage_type", VisualCoverageType.NO_VISUAL.value),
            selected_candidate=sel,
            candidate_pool=pool,
            target_query=data.get("target_query", "")
        )


@dataclass
class VisualEvidencePlan:
    """Comprehensive visual evidence plan across all beats of a Short."""
    event_id: str
    script_id: str
    beat_plans: List[BeatVisualPlan] = field(default_factory=list)
    overall_evidence_ratio: float = 0.0
    direct_evidence_count: int = 0
    related_evidence_count: int = 0
    contextual_count: int = 0
    no_visual_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_metrics(self) -> None:
        """Recomputes coverage counts and ratios."""
        self.direct_evidence_count = sum(1 for b in self.beat_plans if b.coverage_type == VisualCoverageType.DIRECT_EVIDENCE.value)
        self.related_evidence_count = sum(1 for b in self.beat_plans if b.coverage_type == VisualCoverageType.RELATED_EVIDENCE.value)
        self.contextual_count = sum(1 for b in self.beat_plans if b.coverage_type == VisualCoverageType.CONTEXTUAL.value)
        self.no_visual_count = sum(1 for b in self.beat_plans if b.coverage_type == VisualCoverageType.NO_VISUAL.value)
        total = len(self.beat_plans)
        if total > 0:
            evidence_beats = self.direct_evidence_count + self.related_evidence_count
            self.overall_evidence_ratio = round(evidence_beats / total, 3)
        else:
            self.overall_evidence_ratio = 0.0

    def to_dict(self) -> Dict[str, Any]:
        self.compute_metrics()
        return {
            "event_id": self.event_id,
            "script_id": self.script_id,
            "beat_plans": [b.to_dict() for b in self.beat_plans],
            "overall_evidence_ratio": self.overall_evidence_ratio,
            "direct_evidence_count": self.direct_evidence_count,
            "related_evidence_count": self.related_evidence_count,
            "contextual_count": self.contextual_count,
            "no_visual_count": self.no_visual_count,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisualEvidencePlan":
        dt = None
        if data.get("created_at"):
            try:
                dt = datetime.fromisoformat(data["created_at"])
            except Exception:
                dt = datetime.now(timezone.utc)
        plans = [BeatVisualPlan.from_dict(b) for b in data.get("beat_plans", [])]
        plan = cls(
            event_id=data.get("event_id", ""),
            script_id=data.get("script_id", ""),
            beat_plans=plans,
            overall_evidence_ratio=float(data.get("overall_evidence_ratio", 0.0)),
            direct_evidence_count=int(data.get("direct_evidence_count", 0)),
            related_evidence_count=int(data.get("related_evidence_count", 0)),
            contextual_count=int(data.get("contextual_count", 0)),
            no_visual_count=int(data.get("no_visual_count", 0)),
            created_at=dt or datetime.now(timezone.utc)
        )
        plan.compute_metrics()
        return plan

    @classmethod
    def from_json(cls, json_str: str) -> "VisualEvidencePlan":
        return cls.from_dict(json.loads(json_str))
