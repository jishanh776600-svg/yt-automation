"""
Data models for the Isolated Current-Affairs Intelligence Layer.
These internal models represent raw articles and aggregated event clusters
prior to validation and promotion into the production SQLite Topic schema.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Set, Dict, Any, Optional
from config.constants import CurrentAffairsCategory


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

    # Normalized fields populated during processing
    normalized_title: str = ""
    normalized_summary: str = ""
    entities: Set[str] = field(default_factory=set)
    keywords: Set[str] = field(default_factory=set)
    countries: Set[str] = field(default_factory=set)
    action_tokens: Set[str] = field(default_factory=set)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventCluster:
    """
    A unified, multi-source event candidate formed by clustering related RawArticles.
    Represents a discrete real-world happening with corroborated evidence.
    """
    cluster_id: str
    canonical_title: str
    canonical_summary: str
    articles: List[RawArticle] = field(default_factory=list)
    source_domains: Set[str] = field(default_factory=set)

    first_published_at: Optional[datetime] = None
    last_published_at: Optional[datetime] = None

    primary_category: str = CurrentAffairsCategory.GEOPOLITICS.value
    entities: Set[str] = field(default_factory=set)
    countries: Set[str] = field(default_factory=set)
    actors: Set[str] = field(default_factory=set)
    action_tokens: Set[str] = field(default_factory=set)

    # Multi-factor algorithmic scores
    freshness_score: float = 0.0
    relevance_score: float = 0.0
    opportunity_score: float = 0.0

    # Gate evaluations
    has_multi_source_consensus: bool = False
    status: str = "DISCOVERED"  # DISCOVERED, INSUFFICIENT_EVIDENCE, APPROVED, REJECTED
    rejection_reason: Optional[str] = None

    def add_article(self, article: RawArticle) -> None:
        """Adds an article to the cluster and updates domain and timestamp boundaries."""
        self.articles.append(article)
        if article.source_domain:
            self.source_domains.add(article.source_domain.lower())

        if article.published_at:
            if not self.first_published_at or article.published_at < self.first_published_at:
                self.first_published_at = article.published_at
            if not self.last_published_at or article.published_at > self.last_published_at:
                self.last_published_at = article.published_at

        self.entities.update(article.entities)
        self.countries.update(article.countries)
        self.action_tokens.update(article.action_tokens)
