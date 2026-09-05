"""
Data models for the Isolated Current-Affairs Intelligence Layer.
These internal models represent raw articles and aggregated event clusters
prior to validation and promotion into the production SQLite Topic schema.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Set, Dict, Any, Optional
from config.constants import CurrentAffairsCategory
from intelligence.event_card import VerificationState, EventCard, WhoSection, WhereSection, WhenSection, ClaimEvidence, ConflictRecord, TimelineEntry


@dataclass
class RawArticle:
    """
    Lightweight, normalized representation of an incoming news item
    from RSS, GDELT, or wire services.
    """
    title: str
    summary: str
    url: str
    source_domain: str
    source_name: str
    published_at: Optional[datetime]
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    author: Optional[str] = None
    image_url: Optional[str] = None
    article_id: Optional[str] = None
    article_text: Optional[str] = None

    # Normalized fields populated during processing
    normalized_title: str = ""
    normalized_summary: str = ""
    entities: Set[str] = field(default_factory=set)
    keywords: Set[str] = field(default_factory=set)
    countries: Set[str] = field(default_factory=set)
    action_tokens: Set[str] = field(default_factory=set)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    # Embedding vector cached on demand
    embedding: Optional[List[float]] = None

    @property
    def publisher(self) -> str:
        return self.source_name

    @property
    def description(self) -> str:
        return self.summary


@dataclass
class EventCluster:
    """
    A unified, multi-source event candidate formed by clustering related news articles.
    Represents a discrete real-world happening with corroborated evidence.
    """
    cluster_id: str
    canonical_title: str
    canonical_summary: str
    articles: List[Any] = field(default_factory=list)
    source_domains: Set[str] = field(default_factory=set)
    source_publishers: Set[str] = field(default_factory=set)

    first_published_at: Optional[datetime] = None
    last_published_at: Optional[datetime] = None
    event_occurred_at: Optional[datetime] = None  # Distinct from publication timestamp

    primary_category: str = CurrentAffairsCategory.GEOPOLITICS.value
    event_type: str = "geopolitical_incident"
    entities: Set[str] = field(default_factory=set)
    countries: Set[str] = field(default_factory=set)
    actors: Set[str] = field(default_factory=set)
    people: Set[str] = field(default_factory=set)
    organizations: Set[str] = field(default_factory=set)
    locations: Set[str] = field(default_factory=set)
    action_tokens: Set[str] = field(default_factory=set)
    important_objects: Set[str] = field(default_factory=set)

    # Corroboration & Verification fields
    independent_publisher_count: int = 1
    independent_publishers: List[str] = field(default_factory=list)
    verification_state: str = VerificationState.DEVELOPING.value
    confidence: float = 0.80
    conflicts: List[ConflictRecord] = field(default_factory=list)
    claims: List[ClaimEvidence] = field(default_factory=list)

    # Multi-factor algorithmic scores
    freshness_score: float = 0.0
    relevance_score: float = 0.0
    opportunity_score: float = 0.0

    # Gate evaluations
    has_multi_source_consensus: bool = False
    status: str = "DISCOVERED"  # DISCOVERED, INSUFFICIENT_EVIDENCE, APPROVED, REJECTED
    rejection_reason: Optional[str] = None

    # Cached embedding for cluster centroid
    embedding: Optional[List[float]] = None

    @property
    def event_id(self) -> str:
        return self.cluster_id

    @property
    def source_count(self) -> int:
        return len(self.articles)

    @property
    def article_ids(self) -> List[str]:
        ids = []
        for a in self.articles:
            aid = getattr(a, "article_id", None) or getattr(a, "id", None) or getattr(a, "url", None)
            if aid:
                ids.append(str(aid))
        return ids

    @property
    def first_seen_utc(self) -> Optional[datetime]:
        return self.first_published_at

    @property
    def latest_seen_utc(self) -> Optional[datetime]:
        return self.last_published_at

    def add_article(self, article: Any) -> None:
        """Adds an article to the cluster and updates domain, publisher, and timestamp boundaries."""
        self.articles.append(article)

        dom = getattr(article, "source_domain", None)
        if dom:
            self.source_domains.add(dom.lower())

        pub = getattr(article, "source_name", None) or getattr(article, "publisher", None)
        if pub:
            self.source_publishers.add(pub)

        pub_at = getattr(article, "published_at", None) or getattr(article, "published_utc", None)
        if pub_at:
            if not self.first_published_at or pub_at < self.first_published_at:
                self.first_published_at = pub_at
            if not self.last_published_at or pub_at > self.last_published_at:
                self.last_published_at = pub_at

        # Update entity sets
        for attr in ["entities", "countries", "actors", "people", "organizations", "locations", "action_tokens", "important_objects"]:
            val = getattr(article, attr, None)
            if val and isinstance(val, (set, list)):
                target_set = getattr(self, attr)
                target_set.update(val)

    def to_event_card(self) -> EventCard:
        """Constructs a fully populated, machine-readable EventCard contract."""
        who = WhoSection(
            people=sorted(list(self.people)),
            organizations=sorted(list(self.organizations or self.actors)),
            countries=sorted(list(self.countries)),
            military_units=[e for e in self.entities if any(w in e.lower() for w in ["fleet", "navy", "guard", "brigade", "division", "corps", "command"])]
        )

        loc_name = next(iter(self.locations), None)
        country_name = next(iter(self.countries), None)
        where = WhereSection(
            country=country_name,
            region=loc_name if loc_name and loc_name != country_name else None,
            city=loc_name if loc_name and loc_name != country_name else None,
            location_name=f"{loc_name}, {country_name}" if (loc_name and country_name and loc_name != country_name) else (loc_name or country_name)
        )

        when = WhenSection(
            event_time_utc=self.event_occurred_at or self.first_published_at,
            uncertainty="earliest reported wire timestamp" if not self.event_occurred_at else None
        )

        sources_summary = []
        for art in self.articles:
            sources_summary.append({
                "publisher": getattr(art, "source_name", "") or getattr(art, "publisher", "Unknown"),
                "url": getattr(art, "url", ""),
                "published_utc": (getattr(art, "published_utc", None) or getattr(art, "published_at", None)).isoformat() if (getattr(art, "published_utc", None) or getattr(art, "published_at", None)) else None,
                "title": getattr(art, "title", "")
            })

        # Future visual engine queries & concepts
        visual_entities = list(self.important_objects.union(self.entities).union(self.countries))
        future_queries = [
            f"{self.canonical_title} footage",
            f"{' '.join(list(self.action_tokens)[:2])} {' '.join(list(self.entities)[:2])} incident"
        ]

        timeline_entries = []
        for art in sorted(self.articles, key=lambda a: (getattr(a, "published_utc", None) or getattr(a, "published_at", None) or datetime.min)):
            art_time = getattr(art, "published_utc", None) or getattr(art, "published_at", None)
            pub = getattr(art, "source_name", "") or getattr(art, "publisher", "Unknown")
            title = getattr(art, "title", "")
            if art_time:
                timeline_entries.append(TimelineEntry(
                    timestamp_utc=art_time,
                    event_description=title,
                    publisher=pub,
                    source_url=getattr(art, "url", None)
                ))

        return EventCard(
            event_id=self.cluster_id,
            canonical_title=self.canonical_title,
            verification_state=self.verification_state,
            confidence=self.confidence,
            first_seen_utc=self.first_seen_utc,
            latest_seen_utc=self.latest_seen_utc,
            who=who,
            what=self.canonical_summary or self.canonical_title,
            where=where,
            when=when,
            why=None,  # Not manufactured without explicit evidence
            how=None,  # Not manufactured without explicit evidence
            event_type=self.event_type,
            actions=sorted(list(self.action_tokens)),
            entities=sorted(list(self.entities)),
            important_objects=sorted(list(self.important_objects)),
            claims=self.claims,
            sources=sources_summary,
            conflicting_claims=self.conflicts,
            timeline=timeline_entries,
            visual_entities=visual_entities[:10],
            visual_concepts=sorted(list(self.action_tokens))[:6],
            future_footage_queries=future_queries
        )