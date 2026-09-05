"""
Current-Affairs Deduplication Engine.
Compares candidate EventClusters against existing database records and in-flight batches.
Explicitly avoids false-positive collisions for distinct events sharing the same year and city.
"""
import re
import hashlib
import logging
from typing import List, Set, Optional, Tuple, Any, Dict
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlalchemy.orm import Session

from intelligence.models import EventCluster
from intelligence.normalization import extract_entities_and_tokens, clean_text_for_tokens
from intelligence.clustering import compute_jaccard, determine_action_domains
from core.discovery_profile import DiscoveryProfile, get_active_discovery_profile
from core.models import Topic

logger = logging.getLogger(__name__)


def is_same_current_affairs_story(
    cand_title: str,
    cand_summary: str,
    cand_actions: Set[str],
    cand_entities: Set[str],
    cand_keywords: Set[str],
    exist_title: str,
    exist_summary: str,
    profile: Optional[DiscoveryProfile] = None
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

    # Extract tokens for existing story using profile
    active_profile = profile or get_active_discovery_profile()
    exist_entities, exist_countries, exist_actions, exist_keywords = extract_entities_and_tokens(
        f"{exist_title}. {exist_summary}",
        profile=active_profile
    )

    # 2. Check Action Domain Conflict
    domain_map = active_profile.action_domain_map if active_profile else None
    cand_domains = determine_action_domains(cand_actions, action_domain_map=domain_map)
    exist_domains = determine_action_domains(exist_actions, action_domain_map=domain_map)

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

    # 5. Semantic Vector Embedding Similarity (FastEmbed)
    try:
        from intelligence.clustering import SemanticEmbeddingService
        emb_service = SemanticEmbeddingService.get_instance()
        cand_vec = emb_service.embed_text(f"{cand_title}. {cand_summary}")
        exist_vec = emb_service.embed_text(f"{exist_title}. {exist_summary}")
        cos_sim = emb_service.compute_cosine_similarity(cand_vec, exist_vec)
        if cos_sim >= 0.82:
            return True, f"HIGH_SEMANTIC_SIMILARITY_{cos_sim:.2f}"
        if cos_sim >= 0.70 and (len(shared_entities) >= 1 or len(shared_actions) >= 1):
            return True, f"SEMANTIC_SIM_{cos_sim:.2f}_WITH_SHARED_EVIDENCE"
    except Exception:
        pass

    return False, "DISTINCT_EVENTS"


class CurrentAffairsDeduplicationEngine:
    """Evaluates candidate EventClusters against existing database topics to prevent duplicate reporting."""

    def __init__(self, profile: Optional[DiscoveryProfile] = None):
        self.profile = profile or get_active_discovery_profile()

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
        _, _, _, cand_keywords = extract_entities_and_tokens(
            f"{cand_title}. {cand_summary}",
            profile=self.profile
        )

        # Query existing topics (excluding rejected/test topics)
        query = db.query(Topic).filter(~Topic.status.in_(["REJECTED"]))
        if exclude_topic_id:
            query = query.filter(Topic.id != exclude_topic_id)
        existing_topics = query.all()

        for t in existing_topics:
            # 1. Exact event_id match
            if getattr(t, "event_id", None) and cluster.event_id and t.event_id == cluster.event_id:
                logger.info(f"[CURRENT_AFFAIRS_DEDUP] Rejected candidate '{cand_title[:45]}' — exact event_id match '{t.event_id}'")
                return True, t.title, "EXACT_EVENT_ID_MATCH"

            is_dup, reason = is_same_current_affairs_story(
                cand_title=cand_title,
                cand_summary=cand_summary,
                cand_actions=cand_actions,
                cand_entities=cand_entities,
                cand_keywords=cand_keywords,
                exist_title=t.title,
                exist_summary=t.summary or "",
                profile=self.profile
            )
            if is_dup:
                logger.info(
                    f"[CURRENT_AFFAIRS_DEDUP] Rejected candidate '{cand_title[:45]}' — duplicate of existing '{t.title[:45]}' ({reason})"
                )
                return True, t.title, reason

        return False, None, "UNIQUE_STORY"

    def evaluate_candidate(
        self,
        candidate_title: str,
        candidate_summary: str = "",
        candidate_script: str = "",
        db: Optional[Session] = None,
        vault_files: Optional[List[Dict[str, Any]]] = None,
        exclude_topic_id: Optional[str] = None
    ) -> Any:
        """
        Evaluates a candidate story against the SQLite Topic catalog and Upload records
        using current-affairs entity, domain, and keyword logic.
        Returns a DeduplicationResult compatible with StoryDeduplicationEngine.
        """
        from engines.deduplication_engine import DeduplicationResult

        if not db:
            return DeduplicationResult(
                is_duplicate=False,
                classification="COMPLETELY_NEW_STORY",
                similarity_score=0.0,
                is_allowed=True,
                reason="No database session provided for verification."
            )

        cand_text = f"{candidate_title}. {candidate_summary}"
        cand_entities, cand_countries, cand_actions, cand_keywords = extract_entities_and_tokens(
            cand_text,
            profile=self.profile
        )

        # 1. Check against DB Topics
        query = db.query(Topic).filter(~Topic.status.in_(["REJECTED"]))
        if exclude_topic_id:
            query = query.filter(Topic.id != exclude_topic_id)
        existing_topics = query.all()

        for t in existing_topics:
            is_dup, reason = is_same_current_affairs_story(
                cand_title=candidate_title,
                cand_summary=candidate_summary,
                cand_actions=cand_actions,
                cand_entities=cand_entities,
                cand_keywords=cand_keywords,
                exist_title=t.title,
                exist_summary=t.summary or "",
                profile=self.profile
            )
            if is_dup:
                return DeduplicationResult(
                    is_duplicate=True,
                    classification="SEMANTIC_DUPLICATE",
                    matched_event_title=t.title,
                    similarity_score=0.92,
                    shared_elements=[reason],
                    reason=f"Current-affairs duplicate of topic '{t.title}' ({reason})",
                    is_allowed=False
                )

        # 2. Check against UploadRecord
        try:
            from core.models import UploadRecord
            uploads = db.query(UploadRecord).filter(
                UploadRecord.status.in_(["PUBLISHED", "SCHEDULED", "SUCCESS", "TEST_VERIFIED"])
            ).all()
            for u in uploads:
                is_dup, reason = is_same_current_affairs_story(
                    cand_title=candidate_title,
                    cand_summary=candidate_summary,
                    cand_actions=cand_actions,
                    cand_entities=cand_entities,
                    cand_keywords=cand_keywords,
                    exist_title=u.title,
                    exist_summary=u.description or "",
                    profile=self.profile
                )
                if is_dup:
                    return DeduplicationResult(
                        is_duplicate=True,
                        classification="SEMANTIC_DUPLICATE",
                        matched_event_title=u.title,
                        similarity_score=0.92,
                        shared_elements=[reason],
                        reason=f"Current-affairs duplicate of upload '{u.title}' ({reason})",
                        is_allowed=False
                    )
        except Exception as e:
            logger.debug(f"[CURRENT_AFFAIRS_DEDUP] Upload check notice: {e}")

        return DeduplicationResult(
            is_duplicate=False,
            classification="COMPLETELY_NEW_STORY",
            similarity_score=0.0,
            shared_elements=[],
            reason="No colliding current-affairs events detected.",
            is_allowed=True
        )


# ==============================================================================
# URL NORMALIZATION AND DEDUPLICATION
# ==============================================================================

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "ncid", "_hsenc", "_hsmi", "mc_eid",
    "guccounter", "guce_referrer", "guce_referrer_sig", "feed",
    "sp_ref", "src", "platform", "ocid", "ved", "usqp", "srsltid"
}


def normalize_url(url: str) -> str:
    """
    Produces a canonical, clean version of a URL for deduplication.
    - Strips whitespace
    - Lowercases scheme and hostname
    - Strips default ports (80/443)
    - Strips tracking parameters
    - Strips fragments (#...)
    - Normalizes paths (strips redundant root or trailing slashes)
    - Re-orders remaining query parameters
    """
    if not url:
        return ""

    raw = url.strip()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Strip standard default ports
        if (scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443):
            netloc = parsed.hostname or netloc

        path = parsed.path
        if path == "/" or not path:
            path = ""
        elif path.endswith("/"):
            path = path.rstrip("/")

        # Filter query params
        query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
        clean_pairs = sorted([(k, v) for k, v in query_pairs if k.lower() not in TRACKING_PARAMS])
        query_str = urlencode(clean_pairs)

        clean_url = urlunparse((scheme, netloc, path, "", query_str, ""))
        return clean_url
    except Exception:
        return url.strip()


def compute_url_hash(normalized_url: str) -> str:
    """Returns SHA-256 hex digest of normalized URL."""
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


class URLDeduplicator:
    """Tracks seen URLs in-memory and against database."""

    def __init__(self):
        self.seen_normalized_urls: Set[str] = set()

    def is_duplicate(self, url: str, db: Optional[Session] = None) -> bool:
        """Checks if URL was already seen in this session or exists in Article database."""
        norm = normalize_url(url)
        if not norm:
            return True

        if norm in self.seen_normalized_urls:
            return True

        if db is not None:
            from core.models import ArticleRecord
            existing = db.query(ArticleRecord).filter(ArticleRecord.normalized_url == norm).first()
            if existing is not None:
                self.seen_normalized_urls.add(norm)
                return True

        return False

    def mark_seen(self, url: str):
        """Registers normalized URL in memory."""
        norm = normalize_url(url)
        if norm:
            self.seen_normalized_urls.add(norm)

