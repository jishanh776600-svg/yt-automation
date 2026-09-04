"""
Deterministic Event Clustering Engine.
Groups multi-source news articles covering the same real-world event into EventClusters.
Crucially distinguishes between different events occurring in the same city/country and year
by combining actor entities, action stems, and headline content tokens.
"""
import uuid
import logging
from typing import List, Set, Dict, Optional, Tuple
from intelligence.models import RawArticle, EventCluster

logger = logging.getLogger(__name__)

# Mutually exclusive action domains that prevent false clustering of distinct stories in the same location
ACTION_DOMAIN_MAP = {
    # Military / Armed Conflict
    "military": "DEFENSE_CONFLICT", "strike": "DEFENSE_CONFLICT", "attack": "DEFENSE_CONFLICT",
    "bombing": "DEFENSE_CONFLICT", "missile": "DEFENSE_CONFLICT", "drone": "DEFENSE_CONFLICT",
    "invasion": "DEFENSE_CONFLICT", "deploy": "DEFENSE_CONFLICT", "deployment": "DEFENSE_CONFLICT",
    "troops": "DEFENSE_CONFLICT", "ceasefire": "DEFENSE_CONFLICT", "combat": "DEFENSE_CONFLICT",
    "airspace": "DEFENSE_CONFLICT", "offensive": "DEFENSE_CONFLICT",
    # Economic / Trade
    "tariff": "TRADE_ECONOMY", "trade": "TRADE_ECONOMY", "embargo": "TRADE_ECONOMY",
    "inflation": "TRADE_ECONOMY", "debt": "TRADE_ECONOMY", "interest rate": "TRADE_ECONOMY",
    "currency": "TRADE_ECONOMY", "export": "TRADE_ECONOMY", "import": "TRADE_ECONOMY",
    "deficit": "TRADE_ECONOMY", "stimulus": "TRADE_ECONOMY",
    # Political / Elections / Domestic
    "election": "DOMESTIC_POLITICS", "vote": "DOMESTIC_POLITICS", "resign": "DOMESTIC_POLITICS",
    "impeach": "DOMESTIC_POLITICS", "cabinet": "DOMESTIC_POLITICS", "protest": "DOMESTIC_POLITICS",
    "parliament": "DOMESTIC_POLITICS", "dissolve": "DOMESTIC_POLITICS", "coup": "DOMESTIC_POLITICS",
    # Diplomatic / Treaties
    "summit": "DIPLOMACY", "treaty": "DIPLOMACY", "envoy": "DIPLOMACY", "bilateral": "DIPLOMACY",
    "pact": "DIPLOMACY", "accord": "DIPLOMACY", "ambassador": "DIPLOMACY"
}


def compute_jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    """Computes Jaccard similarity between two string sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return float(intersection) / float(union) if union > 0 else 0.0


def determine_action_domains(action_tokens: Set[str]) -> Set[str]:
    """Maps action tokens to high-level action domains (e.g. DEFENSE_CONFLICT vs TRADE_ECONOMY)."""
    domains = set()
    for act in action_tokens:
        domain = ACTION_DOMAIN_MAP.get(act)
        if domain:
            domains.add(domain)
    return domains


def are_articles_same_event(art1: RawArticle, art2: RawArticle) -> Tuple[bool, str]:
    """
    Evaluates whether two articles refer to the exact same real-world event.
    Returns (is_same_event, reason).
    """
    # 1. Exact URL or normalized title match
    if art1.url and art2.url and art1.url == art2.url:
        return True, "EXACT_URL_MATCH"

    if art1.normalized_title and art2.normalized_title and art1.normalized_title.lower() == art2.normalized_title.lower():
        return True, "EXACT_TITLE_MATCH"

    # 2. Check Action Domain Conflict
    domains1 = determine_action_domains(art1.action_tokens)
    domains2 = determine_action_domains(art2.action_tokens)
    # If both have explicit domains, but have ZERO domain overlap (e.g. DEFENSE_CONFLICT vs TRADE_ECONOMY),
    # they are separate events even if they occur in the same city/country!
    if domains1 and domains2 and not domains1.intersection(domains2):
        return False, "ACTION_DOMAIN_CONFLICT"

    # 3. Content Token Jaccard Similarity
    token_sim = compute_jaccard(art1.keywords, art2.keywords)

    # 4. Entity & Country Overlap
    shared_entities = art1.entities.intersection(art2.entities)
    shared_countries = art1.countries.intersection(art2.countries)
    shared_actions = art1.action_tokens.intersection(art2.action_tokens)

    # Strong match: high token similarity (>= 0.40)
    if token_sim >= 0.40:
        return True, f"HIGH_TOKEN_SIMILARITY_{token_sim:.2f}"

    # Moderate token similarity (>= 0.25) with shared action and shared entity
    if token_sim >= 0.25 and (len(shared_actions) >= 1 or len(domains1.intersection(domains2)) >= 1) and (len(shared_entities) >= 1 or len(shared_countries) >= 1):
        return True, f"MODERATE_TOKEN_SIM_{token_sim:.2f}_WITH_SHARED_ACTION_AND_ENTITY"

    # Specific shared multi-word entities and shared actions
    if len(shared_entities) >= 2 and len(shared_actions) >= 1 and token_sim >= 0.18:
        return True, "SHARED_MULTIPLE_ENTITIES_AND_ACTION"

    return False, f"INSUFFICIENT_SIMILARITY_{token_sim:.2f}"


class EventClusterEngine:
    """Aggregates raw news articles into discrete EventClusters."""

    def __init__(self, min_token_sim: float = 0.25):
        self.min_token_sim = min_token_sim

    def cluster_articles(self, articles: List[RawArticle]) -> List[EventCluster]:
        """
        Clusters a list of normalized RawArticles into EventClusters.
        O(N*C) greedy clustering bounded by active cluster count.
        """
        clusters: List[EventCluster] = []

        for art in articles:
            matched_cluster: Optional[EventCluster] = None

            for cluster in clusters:
                # Compare against canonical representative and members
                rep_article = cluster.articles[0]
                is_same, reason = are_articles_same_event(art, rep_article)

                if is_same:
                    matched_cluster = cluster
                    logger.debug(f"[CLUSTERING] Merged '{art.normalized_title[:45]}' into cluster '{cluster.canonical_title[:45]}' ({reason})")
                    break

            if matched_cluster:
                matched_cluster.add_article(art)
                # Keep canonical title as the longest clean title with good information density
                if len(art.normalized_title.split()) > len(matched_cluster.canonical_title.split()) and len(art.normalized_title.split()) <= 20:
                    matched_cluster.canonical_title = art.normalized_title
                    matched_cluster.canonical_summary = art.normalized_summary
            else:
                cluster_id = f"ev_{uuid.uuid4().hex[:12]}"
                new_cluster = EventCluster(
                    cluster_id=cluster_id,
                    canonical_title=art.normalized_title or art.title,
                    canonical_summary=art.normalized_summary or art.summary
                )
                new_cluster.add_article(art)
                clusters.append(new_cluster)

        logger.info(f"[CLUSTERING] Formed {len(clusters)} event clusters from {len(articles)} articles.")
        return clusters
