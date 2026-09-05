"""
Structured 5W1H EventCard & Claim Provenance Contract.
Defines machine-readable factual event intelligence schemas for Phase 2:
- EventCard: Comprehensive event representation for future script & visual engines
- ClaimEvidence: Granular claim-level provenance (who said what, where, and when)
- ConflictRecord: Explicit contradiction tracking between reputable sources
- TimelineEntry: Chronological development records grounded in article metadata
"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional, Set


class VerificationState(str, Enum):
    SINGLE_CREDIBLE_SOURCE = "SINGLE_CREDIBLE_SOURCE"
    MULTI_SOURCE_CORROBORATED = "MULTI_SOURCE_CORROBORATED"
    OFFICIAL_CONFIRMATION = "OFFICIAL_CONFIRMATION"
    DEVELOPING = "DEVELOPING"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_REPORTS = "CONFLICTING_REPORTS"


@dataclass
class ClaimEvidence:
    """Granular claim-level provenance tracking."""
    claim_id: str
    claim_text: str
    publisher: str
    source_article_id: Optional[str] = None
    source_url: Optional[str] = None
    published_utc: Optional[datetime] = None
    evidence_excerpt: Optional[str] = None
    confidence: float = 1.0
    verification_state: str = "VERIFIED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "publisher": self.publisher,
            "source_article_id": self.source_article_id,
            "source_url": self.source_url,
            "published_utc": self.published_utc.isoformat() if self.published_utc else None,
            "evidence_excerpt": self.evidence_excerpt,
            "confidence": round(self.confidence, 3),
            "verification_state": self.verification_state
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClaimEvidence":
        pub_utc = None
        if data.get("published_utc"):
            if isinstance(data["published_utc"], str):
                try:
                    pub_utc = datetime.fromisoformat(data["published_utc"])
                except ValueError:
                    pub_utc = None
            elif isinstance(data["published_utc"], datetime):
                pub_utc = data["published_utc"]

        return cls(
            claim_id=data.get("claim_id", f"cl_{uuid.uuid4().hex[:8]}"),
            claim_text=data.get("claim_text", ""),
            publisher=data.get("publisher", "Unknown"),
            source_article_id=data.get("source_article_id"),
            source_url=data.get("source_url"),
            published_utc=pub_utc,
            evidence_excerpt=data.get("evidence_excerpt"),
            confidence=float(data.get("confidence", 1.0)),
            verification_state=data.get("verification_state", "VERIFIED")
        )


@dataclass
class ConflictRecord:
    """Discrepancies or contradictory claims across sources."""
    conflict_id: str
    topic_facet: str  # e.g. casualty_count, actor_attribution, incident_location, weapon_type
    competing_claims: List[Dict[str, Any]] = field(default_factory=list)
    description: str = ""
    affected_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "topic_facet": self.topic_facet,
            "competing_claims": self.competing_claims,
            "description": self.description,
            "affected_sources": self.affected_sources
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictRecord":
        return cls(
            conflict_id=data.get("conflict_id", f"cnf_{uuid.uuid4().hex[:8]}"),
            topic_facet=data.get("topic_facet", "unspecified"),
            competing_claims=data.get("competing_claims", []),
            description=data.get("description", ""),
            affected_sources=data.get("affected_sources", [])
        )


@dataclass
class TimelineEntry:
    """Chronological event progression entry."""
    timestamp_utc: Optional[datetime]
    event_description: str
    publisher: str
    source_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc.isoformat() if self.timestamp_utc else None,
            "event_description": self.event_description,
            "publisher": self.publisher,
            "source_url": self.source_url
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineEntry":
        ts = None
        if data.get("timestamp_utc"):
            if isinstance(data["timestamp_utc"], str):
                try:
                    ts = datetime.fromisoformat(data["timestamp_utc"])
                except ValueError:
                    ts = None
            elif isinstance(data["timestamp_utc"], datetime):
                ts = data["timestamp_utc"]

        return cls(
            timestamp_utc=ts,
            event_description=data.get("event_description", ""),
            publisher=data.get("publisher", "Unknown"),
            source_url=data.get("source_url")
        )


@dataclass
class WhoSection:
    people: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)
    military_units: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WhereSection:
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    location_name: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WhenSection:
    event_time_utc: Optional[datetime] = None
    uncertainty: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_time_utc": self.event_time_utc.isoformat() if self.event_time_utc else None,
            "uncertainty": self.uncertainty
        }


@dataclass
class EventCard:
    """
    Standardized, machine-readable factual event intelligence contract.
    Consolidates verified information for consumption by Phase 3 (scripting)
    and future real-footage visual retrieval.
    """
    event_id: str
    canonical_title: str
    verification_state: str
    confidence: float

    first_seen_utc: Optional[datetime]
    latest_seen_utc: Optional[datetime]

    who: WhoSection
    what: str
    where: WhereSection
    when: WhenSection

    why: Optional[str] = None
    how: Optional[str] = None

    event_type: str = "geopolitical_incident"
    actions: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    important_objects: List[str] = field(default_factory=list)

    claims: List[ClaimEvidence] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    conflicting_claims: List[ConflictRecord] = field(default_factory=list)
    timeline: List[TimelineEntry] = field(default_factory=list)

    # Future visual engine handoff metadata
    visual_entities: List[str] = field(default_factory=list)
    visual_concepts: List[str] = field(default_factory=list)
    future_footage_queries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "canonical_title": self.canonical_title,
            "verification_state": self.verification_state,
            "confidence": round(self.confidence, 3),
            "first_seen_utc": self.first_seen_utc.isoformat() if self.first_seen_utc else None,
            "latest_seen_utc": self.latest_seen_utc.isoformat() if self.latest_seen_utc else None,
            "who": self.who.to_dict() if isinstance(self.who, WhoSection) else self.who,
            "what": self.what,
            "where": self.where.to_dict() if isinstance(self.where, WhereSection) else self.where,
            "when": self.when.to_dict() if isinstance(self.when, WhenSection) else self.when,
            "why": self.why,
            "how": self.how,
            "event_type": self.event_type,
            "actions": self.actions,
            "entities": self.entities,
            "important_objects": self.important_objects,
            "claims": [c.to_dict() if isinstance(c, ClaimEvidence) else c for c in self.claims],
            "sources": self.sources,
            "conflicting_claims": [cf.to_dict() if isinstance(cf, ConflictRecord) else cf for cf in self.conflicting_claims],
            "timeline": [t.to_dict() if isinstance(t, TimelineEntry) else t for t in self.timeline],
            "visual_entities": self.visual_entities,
            "visual_concepts": self.visual_concepts,
            "future_footage_queries": self.future_footage_queries
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventCard":
        def parse_dt(v):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(v)
            except Exception:
                return None

        who_data = data.get("who", {})
        who = WhoSection(
            people=who_data.get("people", []),
            organizations=who_data.get("organizations", []),
            countries=who_data.get("countries", []),
            military_units=who_data.get("military_units", [])
        )

        where_data = data.get("where", {})
        where = WhereSection(
            country=where_data.get("country"),
            region=where_data.get("region"),
            city=where_data.get("city"),
            location_name=where_data.get("location_name"),
            coordinates=where_data.get("coordinates")
        )

        when_data = data.get("when", {})
        when = WhenSection(
            event_time_utc=parse_dt(when_data.get("event_time_utc")),
            uncertainty=when_data.get("uncertainty")
        )

        claims = [
            ClaimEvidence.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("claims", [])
        ]
        conflicts = [
            ConflictRecord.from_dict(cf) if isinstance(cf, dict) else cf
            for cf in data.get("conflicting_claims", [])
        ]
        timeline = [
            TimelineEntry.from_dict(t) if isinstance(t, dict) else t
            for t in data.get("timeline", [])
        ]

        return cls(
            event_id=data.get("event_id", f"ev_{uuid.uuid4().hex[:12]}"),
            canonical_title=data.get("canonical_title", "Untitled Event"),
            verification_state=data.get("verification_state", VerificationState.DEVELOPING.value),
            confidence=float(data.get("confidence", 0.8)),
            first_seen_utc=parse_dt(data.get("first_seen_utc")),
            latest_seen_utc=parse_dt(data.get("latest_seen_utc")),
            who=who,
            what=data.get("what", ""),
            where=where,
            when=when,
            why=data.get("why"),
            how=data.get("how"),
            event_type=data.get("event_type", "geopolitical_incident"),
            actions=data.get("actions", []),
            entities=data.get("entities", []),
            important_objects=data.get("important_objects", []),
            claims=claims,
            sources=data.get("sources", []),
            conflicting_claims=conflicts,
            timeline=timeline,
            visual_entities=data.get("visual_entities", []),
            visual_concepts=data.get("visual_concepts", []),
            future_footage_queries=data.get("future_footage_queries", [])
        )

    @classmethod
    def from_json(cls, json_str: str) -> "EventCard":
        return cls.from_dict(json.loads(json_str))