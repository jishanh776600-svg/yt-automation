"""
Isolated Current-Affairs Intelligence Layer for AL-AMR.
Harvests, normalizes, clusters, scores, corroborates, and persists
geopolitics, world affairs, and breaking news opportunities into SQLite Topic records.
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from intelligence.models import RawArticle, EventCluster
from intelligence.normalization import normalize_article
from intelligence.sources.rss_source import RSSSourceAdapter
from intelligence.sources.gdelt_source import GDELTSourceAdapter
from intelligence.clustering import EventClusterEngine
from intelligence.freshness import FreshnessScorer
from intelligence.relevance import RelevanceScorer
from intelligence.scoring import OpportunityScorer
from intelligence.deduplication import CurrentAffairsDeduplicationEngine
from intelligence.candidate_writer import CandidateWriter
from core.models import Topic

logger = logging.getLogger(__name__)


def discover_current_affairs_candidates(
    db: Session,
    limit: int = 3,
    rss_adapter: Optional[RSSSourceAdapter] = None,
    gdelt_adapter: Optional[GDELTSourceAdapter] = None,
    include_gdelt: bool = False,
    min_independent_domains: int = 2,
    min_opportunity_score: float = 40.0
) -> List[Topic]:
    """
    High-level entry point for current-affairs opportunity discovery.
    Runs the complete pipeline:
      Harvest -> Normalize -> Cluster -> Freshness -> Relevance -> Opportunity Scoring -> Evidence Gate -> Topic Persistence
    Fails safely on any external exception without disrupting existing pipelines.
    """
    logger.info("[INTELLIGENCE] Starting current-affairs opportunity discovery cycle...")

    raw_articles: List[RawArticle] = []

    # 1. Harvest RSS
    try:
        rss = rss_adapter or RSSSourceAdapter()
        rss_articles = rss.ingest_all()
        raw_articles.extend(rss_articles)
        logger.info(f"[INTELLIGENCE] Harvested {len(rss_articles)} articles from RSS feeds.")
    except Exception as rss_err:
        logger.warning(f"[INTELLIGENCE] RSS harvest encountered an error (continuing): {rss_err}")

    # 2. Harvest GDELT (if enabled)
    if include_gdelt:
        try:
            gdelt = gdelt_adapter or GDELTSourceAdapter()
            gdelt_articles = gdelt.fetch_articles()
            raw_articles.extend(gdelt_articles)
            logger.info(f"[INTELLIGENCE] Harvested {len(gdelt_articles)} articles from GDELT.")
        except Exception as gdelt_err:
            logger.warning(f"[INTELLIGENCE] GDELT harvest encountered an error (continuing): {gdelt_err}")

    if not raw_articles:
        logger.info("[INTELLIGENCE] No articles harvested; exiting discovery cycle safely.")
        return []

    # 3. Cluster into discrete real-world events
    cluster_engine = EventClusterEngine()
    clusters = cluster_engine.cluster_articles(raw_articles)
    if not clusters:
        logger.info("[INTELLIGENCE] No event clusters formed.")
        return []

    # 4. Freshness, Relevance, and Opportunity Scoring
    freshness_scorer = FreshnessScorer()
    relevance_scorer = RelevanceScorer()
    opportunity_scorer = OpportunityScorer()

    for cl in clusters:
        freshness_scorer.evaluate_freshness(cl)
        relevance_scorer.evaluate_relevance(cl)
        opportunity_scorer.calculate_opportunity_score(cl)

    # 5. Multi-Source Evidence Gate, Deduplication & Topic Creation
    writer = CandidateWriter(
        min_independent_domains=min_independent_domains,
        min_opportunity_score=min_opportunity_score
    )

    approved_topics = writer.process_and_persist_candidates(clusters, db, limit=limit)
    logger.info(
        f"[INTELLIGENCE] Completed cycle: {len(raw_articles)} articles -> "
        f"{len(clusters)} clusters -> {len(approved_topics)} approved topics."
    )
    return approved_topics


__all__ = [
    "RawArticle",
    "EventCluster",
    "RSSSourceAdapter",
    "GDELTSourceAdapter",
    "EventClusterEngine",
    "FreshnessScorer",
    "RelevanceScorer",
    "OpportunityScorer",
    "CurrentAffairsDeduplicationEngine",
    "CandidateWriter",
    "discover_current_affairs_candidates",
]
