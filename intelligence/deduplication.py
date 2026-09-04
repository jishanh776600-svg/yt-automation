"""
Current-Affairs Deduplication Engine.
Compares candidate EventClusters against existing database records and in-flight batches.
Explicitly avoids false-positive collisions for distinct events sharing the same year and city.
"""
import re
import logging
from typing import List, Set, Optional, Tuple
from sqlalchemy.orm import Session

from intelligence.models import EventCluster
from intelligence.normalization import extract_entities_and_tokens, clean_text_for_tokens
from intelligence.clustering import compute_jaccard, determine_action_domains
from core.models import Topic

logger = logging.getLogger(__name__)


def is_same_current_affairs_story(
    cand_title: str,
    cand_summary: str,
    cand_actions: Set[str],
    cand_entities: Set[str],
    cand_keywords: Set[str],
    exist_title: str,
    exist_summary: str
) -> Tuple[bool, str]:
    """
    Evaluates whether a candidate current-affairs story is a duplicate of an existing story.
    Returns (is_duplicate, reason).
    """
    # 1. Exact title match
    clean_cand_t = clean_text_for_tokens(cand_title)
    clean_exist_t = clean_text_for_tokens(exist_title)
    if clean_cand_t == clean_exist_t:
        return True, "EXACT_TITLE_MATCH"

    # Extract tokens for existing story
    exist_entities, exist_countries, exist_actions, exist_keywords = extract_entities_and_tokens(
        f"{exist_title}. {exist_summary}"
    )

    # 2. Check Action Domain Conflict
    cand_domains = determine_action_domains(cand_actions)
    exist_domains = determine_action_domains(exist_actions)

    # If action domains are completely distinct (e.g. DEFENSE_CONFLICT vs TRADE_ECONOMY),
    # they are DEFINITIVELY DISTINCT EVENTS, even if they share city/country and year!
    if cand_domains and exist_domains and not cand_domains.intersection(exist_domains):
        return False, "DIFFERENT_ACTION_DOMAINS"

    # 3. Content Token Jaccard Similarity on Titles
    title_cand_words = set(clean_cand_t.split())
    title_exist_words = set(clean_exist_t.split())
    title_sim = compute_jaccard(title_cand_words, title_exist_words)

    if title_sim >= 0.60:
        return True, f"HIGH_TITLE_SIMILARITY_{title_sim:.2f}"

    # 4. Keyword and Entity Overlap
    keyword_sim = compute_jaccard(cand_keywords, exist_keywords)
    shared_entities = cand_entities.intersection(exist_entities)
    shared_actions = cand_actions.intersection(exist_actions)

    # Same story requires: moderate/high keyword similarity AND shared actors AND shared action
    if keyword_sim >= 0.45 and len(shared_entities) >= 1 and len(shared_actions) >= 1:
        return True, f"SHARED_ENTITIES_AND_ACTION_SIM_{keyword_sim:.2f}"

    if keyword_sim >= 0.55:
        return True, f"HIGH_KEYWORD_SIMILARITY_{keyword_sim:.2f}"

    return False, "DISTINCT_EVENTS"


class CurrentAffairsDeduplicationEngine:
    """Evaluates candidate EventClusters against existing database topics to prevent duplicate reporting."""

    def is_cluster_duplicate(
        self,
        cluster: EventCluster,
        db: Session,
        exclude_topic_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str], str]:
        """
        Checks if an EventCluster collides with any existing Topic in SQLite.
        Returns (is_duplicate, matched_topic_title, reason).
        """
        cand_title = cluster.canonical_title
        cand_summary = cluster.canonical_summary
        cand_actions = cluster.action_tokens
        cand_entities = cluster.entities
        _, _, _, cand_keywords = extract_entities_and_tokens(f"{cand_title}. {cand_summary}")

        # Query existing topics (excluding rejected/test topics)
        query = db.query(Topic).filter(~Topic.status.in_(["REJECTED"]))
        if exclude_topic_id:
            query = query.filter(Topic.id != exclude_topic_id)
        existing_topics = query.all()

        for t in existing_topics:
            is_dup, reason = is_same_current_affairs_story(
                cand_title=cand_title,
                cand_summary=cand_summary,
                cand_actions=cand_actions,
                cand_entities=cand_entities,
                cand_keywords=cand_keywords,
                exist_title=t.title,
                exist_summary=t.summary or ""
            )
            if is_dup:
                logger.info(
                    f"[CURRENT_AFFAIRS_DEDUP] Rejected candidate '{cand_title[:45]}' — duplicate of existing '{t.title[:45]}' ({reason})"
                )
                return True, t.title, reason

        return False, None, "UNIQUE_STORY"
