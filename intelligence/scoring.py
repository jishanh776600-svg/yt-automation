"""
Opportunity Scoring Engine.
Computes deterministic opportunity scores for EventClusters
by synthesizing Freshness, Geopolitical Relevance, Multi-Source Breadth,
Narrative Tension, and Coverage Velocity.
"""
import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from intelligence.models import EventCluster
from core.discovery_profile import (
    DEFAULT_NARRATIVE_TENSION_KEYWORDS,
    DiscoveryProfile,
    get_active_discovery_profile
)

logger = logging.getLogger(__name__)

# Narrative tension markers (conflict, surprise, high stakes, escalation) - backwards compatible default
NARRATIVE_TENSION_KEYWORDS = DEFAULT_NARRATIVE_TENSION_KEYWORDS


class SourceType(str, Enum):
    OFFICIAL_GOVERNMENT = "official_government"
    SPECIALIST_DEFENSE = "specialist_defense"
    ESTABLISHED_NEWS = "established_news"
    AGGREGATOR = "aggregator"
    UNKNOWN = "unknown"


# Domain & keyword mapping for source classification
OFFICIAL_TLDS = {".gov", ".mil", ".gov.uk", ".gov.au", ".gouv.fr"}
OFFICIAL_DOMAINS = {
    "state.gov", "defense.gov", "whitehouse.gov", "nato.int",
    "un.org", "gov.uk", "europa.eu", "mod.uk"
}

SPECIALIST_DEFENSE_DOMAINS = {
    "defensenews.com", "janes.com", "breakingdefense.com",
    "understandingwar.org", "iswresearch.org", "navalnews.com",
    "warontherocks.com", "armytimes.com", "airforcetimes.com"
}

ESTABLISHED_NEWS_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk",
    "aljazeera.com", "dw.com", "france24.com", "ft.com",
    "wsj.com", "nytimes.com", "washingtonpost.com", "theguardian.com",
    "bloomberg.com", "economist.com", "foreignpolicy.com",
    "sciencedaily.com", "livescience.com", "phys.org", "sciencealert.com",
    "nature.com", "scientificamerican.com", "smithsonianmag.com",
    "space.com", "nationalgeographic.com", "newscientist.com", "archaeology.org"
}

AGGREGATOR_DOMAINS = {
    "news.google.com", "news.yahoo.com", "yahoo.com", "msn.com",
    "gdeltproject.org", "bing.com"
}

BASE_CONFIDENCE = {
    SourceType.OFFICIAL_GOVERNMENT: 0.95,
    SourceType.SPECIALIST_DEFENSE: 0.90,
    SourceType.ESTABLISHED_NEWS: 0.85,
    SourceType.AGGREGATOR: 0.60,
    SourceType.UNKNOWN: 0.40,
}


def classify_source(url: str, publisher: Optional[str] = None) -> Tuple[SourceType, float, str]:
    """
    Analyzes an article URL and optional publisher string to classify source type and assign confidence.
    Returns: (SourceType, confidence_score, tier_label)
    """
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        domain = ""

    pub_clean = (publisher or "").lower().strip()

    # 1. Check official government
    if any(domain.endswith(tld) for tld in OFFICIAL_TLDS) or domain in OFFICIAL_DOMAINS:
        return SourceType.OFFICIAL_GOVERNMENT, BASE_CONFIDENCE[SourceType.OFFICIAL_GOVERNMENT], "TIER_1_OFFICIAL"

    # 2. Check specialist defense/security
    if domain in SPECIALIST_DEFENSE_DOMAINS or any(d in domain for d in ["defensenews", "janes", "breakingdefense", "understandingwar"]):
        return SourceType.SPECIALIST_DEFENSE, BASE_CONFIDENCE[SourceType.SPECIALIST_DEFENSE], "TIER_1_DEFENSE"

    # 3. Check established news and science research publisher
    if domain in ESTABLISHED_NEWS_DOMAINS or any(d in domain for d in [
        "reuters", "apnews", "bbc", "aljazeera", "dw.com", "france24", "theguardian",
        "sciencedaily", "livescience", "phys.org", "sciencealert", "smithsonian", "nature"
    ]):
        return SourceType.ESTABLISHED_NEWS, BASE_CONFIDENCE[SourceType.ESTABLISHED_NEWS], "TIER_2_ESTABLISHED"

    # Check publisher string for established names
    if any(p in pub_clean for p in [
        "reuters", "associated press", "ap news", "bbc", "al jazeera", "deutsche welle", "dw", "defense news",
        "sciencedaily", "science daily", "live science", "phys.org", "sciencealert", "smithsonian", "space.com"
    ]):
        return SourceType.ESTABLISHED_NEWS, BASE_CONFIDENCE[SourceType.ESTABLISHED_NEWS], "TIER_2_ESTABLISHED"

    # 4. Check aggregators
    if domain in AGGREGATOR_DOMAINS or "gdelt" in domain or "google" in domain:
        return SourceType.AGGREGATOR, BASE_CONFIDENCE[SourceType.AGGREGATOR], "TIER_3_AGGREGATOR"

    # 5. Default unknown
    return SourceType.UNKNOWN, BASE_CONFIDENCE[SourceType.UNKNOWN], "TIER_4_UNKNOWN"


def calculate_composite_score(freshness_score: float, source_confidence: float) -> float:
    """
    Combines freshness (0-100) and source confidence (0.0-1.0) into a balanced score.
    Freshness weighted 60%, Source credibility weighted 40%.
    """
    return round((freshness_score * 0.60) + (source_confidence * 100.0 * 0.40), 2)


class OpportunityScorer:
    """Calculates composite opportunity scores to prioritize high-impact stories."""

    def __init__(
        self,
        weight_freshness: Optional[float] = None,
        weight_relevance: Optional[float] = None,
        weight_breadth: Optional[float] = None,
        weight_tension: Optional[float] = None,
        weight_velocity: Optional[float] = None,
        profile: Optional[DiscoveryProfile] = None
    ):
        self.profile = profile or get_active_discovery_profile()
        p = self.profile
        self.w_fresh = weight_freshness if weight_freshness is not None else (p.weight_freshness if p else 0.30)
        self.w_rel = weight_relevance if weight_relevance is not None else (p.weight_relevance if p else 0.25)
        self.w_breadth = weight_breadth if weight_breadth is not None else (p.weight_breadth if p else 0.20)
        self.w_tension = weight_tension if weight_tension is not None else (p.weight_tension if p else 0.15)
        self.w_velocity = weight_velocity if weight_velocity is not None else (p.weight_velocity if p else 0.10)

    def compute_source_breadth_score(self, domain_count: int) -> float:
        """
        Calibrated score based on independent publisher domain breadth:
          1 domain:  30.0 (Uncorroborated single source)
          2 domains: 70.0 (Corroborated consensus baseline)
          3 domains: 85.0 (Strong consensus)
          4+ domains: 100.0 (Major global event consensus)
        """
        if domain_count <= 1:
            return 30.0
        elif domain_count == 2:
            return 70.0
        elif domain_count == 3:
            return 85.0
        else:
            return 100.0

    def compute_narrative_tension_score(self, cluster: EventCluster) -> float:
        """Evaluates high-stakes narrative tension and dramatic potential."""
        combined_text = f"{cluster.canonical_title} {cluster.canonical_summary}".lower()
        tension_kws = self.profile.tension_keywords if self.profile else NARRATIVE_TENSION_KEYWORDS
        tension_matches = sum(1 for kw in tension_kws if kw in combined_text)
        action_count = len(cluster.action_tokens)

        score = 40.0 + (tension_matches * 15.0) + (action_count * 5.0)
        return min(100.0, max(20.0, score))

    def compute_velocity_score(self, cluster: EventCluster) -> float:
        """Computes coverage velocity based on article volume relative to event age."""
        article_count = len(cluster.articles)
        domain_count = len(cluster.source_domains)

        if domain_count >= 3 and article_count >= 4:
            return 95.0
        elif domain_count >= 2 and article_count >= 2:
            return 75.0
        elif article_count >= 2:
            return 60.0
        return 40.0

    def calculate_opportunity_score(self, cluster: EventCluster) -> float:
        """
        Computes composite opportunity score:
          Score = (w_fresh * Freshness) + (w_rel * Relevance) +
                  (w_breadth * Breadth) + (w_tension * Tension) +
                  (w_velocity * Velocity)
        """
        fresh_score = cluster.freshness_score or 50.0
        rel_score = cluster.relevance_score or 50.0
        breadth_score = self.compute_source_breadth_score(len(cluster.source_domains))
        tension_score = self.compute_narrative_tension_score(cluster)
        velocity_score = self.compute_velocity_score(cluster)

        composite = (
            (self.w_fresh * fresh_score) +
            (self.w_rel * rel_score) +
            (self.w_breadth * breadth_score) +
            (self.w_tension * tension_score) +
            (self.w_velocity * velocity_score)
        )

        final_score = round(min(100.0, max(0.0, composite)), 2)
        cluster.opportunity_score = final_score
        return final_score
