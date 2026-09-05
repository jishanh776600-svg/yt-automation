"""
Semantic Event Clustering Engine.
Combines local CPU-friendly FastEmbed semantic sentence embeddings (BAAI/bge-small-en-v1.5)
with structured entity, action domain, and geographical gating to cluster news reports into EventClusters.
Handles heavy paraphrasing while strictly separating distinct events across locations and domains.
"""
import uuid
import logging
import re
from typing import List, Set, Dict, Optional, Tuple, Any
from datetime import datetime, timedelta

import numpy as np

from intelligence.models import RawArticle, EventCluster
from intelligence.event_card import VerificationState, ClaimEvidence, ConflictRecord
from intelligence.verification import EventVerificationEngine, canonicalize_publisher
from intelligence.normalization import extract_entities_and_tokens, clean_text_for_tokens
from core.discovery_profile import DEFAULT_ACTION_DOMAIN_MAP, DiscoveryProfile, get_active_discovery_profile

logger = logging.getLogger(__name__)

# Action domain mapping
ACTION_DOMAIN_MAP = DEFAULT_ACTION_DOMAIN_MAP


def compute_jaccard(set_a: Set[str], set_b: Set[str]) -> float:
    """Computes Jaccard similarity between two string sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a.intersection(set_b))
    union = len(set_a.union(set_b))
    return float(intersection) / float(union) if union > 0 else 0.0


def determine_action_domains(action_tokens: Set[str], action_domain_map: Optional[Dict[str, str]] = None) -> Set[str]:
    """Maps action tokens to high-level action domains (e.g. DEFENSE_CONFLICT vs TRADE_ECONOMY)."""
    mapping = action_domain_map if action_domain_map is not None else ACTION_DOMAIN_MAP
    domains = set()
    for act in action_tokens:
        domain = mapping.get(act)
        if domain:
            domains.add(domain)
    return domains


BANNED_POLITICAL_KEYWORDS = [
    "war", "warfare", "ceasefire", "military", "army", "troops", "infantry", "forces",
    "diplomacy", "diplomat", "diplomatic", "treaty", "election", "elections", "voters",
    "voting", "ballot", "parliament", "congress", "senate", "minister", "prime minister",
    "president", "presidential", "spokesperson", "spokesman", "sanctions", "tariff", "tariffs",
    "bilateral", "geopolitical", "geopolitics", "pentagon", "kremlin", "white house", "nato",
    "un security council", "missile strike", "air strike", "artillery", "offensive",
    "insurgency", "coup", "foreign policy", "envoy", "ambassador", "national security",
    "ground forces", "defense secretary", "state department", "foreign ministry", "legislation",
    "lawmakers", "referendum", "regime", "geopolitic"
]

APPROVED_NICHE_KEYWORDS = [
    "anomaly", "anomalies", "bizarre", "mysterious", "mystery", "unexplained", "strange",
    "ancient", "discovery", "discovered", "discoveries", "deep sea", "fossil", "fossils",
    "archaeolog", "quantum", "astronom", "telescope", "creature", "creatures", "species",
    "mutation", "dna", "skeleton", "tomb", "tombs", "pyramid", "pyramids", "space",
    "planet", "planets", "galaxy", "galaxies", "ocean", "oceans", "sound", "signal",
    "signals", "physics", "biology", "geology", "microscopic", "organism", "meteor",
    "meteorite", "asteroid", "laboratory", "experiment", "phenomenon", "phenomena",
    "radio burst", "submersible", "trench", "oddity", "peculiar", "unusual", "baffling",
    "puzzle", "enigma", "stone age", "cosmic", "deep ocean", "antarctica", "glacier",
    "ruins", "artifact", "artifacts", "monolith", "extraterrestrial", "supernova", "black hole",
    "cryptid", "megalith", "underwater city", "fossilized", "evolutionary", "bizarre fact",
    "weird science"
]


def is_niche_compliant(
    title: str,
    text: str = "",
    entities: Optional[List[str]] = None,
    allow_political: bool = False
) -> Tuple[bool, str]:
    """
    STRICT NICHE PURITY GATE.
    Authoritatively enforces the channel's sole target niches:
    1. Mystery / Bizarre real-world stories
    2. Weird Science / unbelievable-but-real facts
    Strictly rejects conventional politics, geopolitics, elections,
    military conflicts, diplomacy, and government commentary.
    """
    combined = f"{title} {text} {' '.join(entities or [])}".lower()

    # 1. Hard check for political/geopolitical/military terms
    if not allow_political:
        matched_political = []
        for kw in BANNED_POLITICAL_KEYWORDS:
            pattern = rf"\b{re.escape(kw)}\b"
            if re.search(pattern, combined):
                matched_political.append(kw)

        if matched_political:
            return False, f"REJECTED_POLITICAL_CONTENT: matched {matched_political[:3]}"

    # 2. Check for positive mystery / weird science alignment
    matched_niche = []
    for kw in APPROVED_NICHE_KEYWORDS:
        if kw in combined:
            matched_niche.append(kw)

    if matched_niche:
        return True, f"APPROVED_NICHE: matched {matched_niche[:3]}"

    return False, "REJECTED_OUT_OF_NICHE: Lacks mystery, archaeological, or weird science indicators"



class SemanticEmbeddingService:
    """
    Singleton service for local, CPU-friendly text embeddings via FastEmbed.
    Uses BAAI/bge-small-en-v1.5 (384-dimensional dense vectors).
    Gracefully degrades to pseudo-semantic lexical hash vectors if offline/uninitialized.
    """
    _instance: Optional["SemanticEmbeddingService"] = None

    def __init__(self):
        self._model = None
        self._model_load_attempted = False
        self._is_available = False

    @classmethod
    def get_instance(cls) -> "SemanticEmbeddingService":
        if cls._instance is None:
            cls._instance = SemanticEmbeddingService()
        return cls._instance

    def _init_model(self):
        if self._model_load_attempted:
            return
        self._model_load_attempted = True
        try:
            from fastembed import TextEmbedding
            # Initialize with small, fast, quantized ONNX model
            self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            self._is_available = True
            logger.info("FastEmbed BAAI/bge-small-en-v1.5 initialized successfully.")
        except Exception as e:
            logger.warning(f"FastEmbed initialization deferred/failed ({e}). Falling back to hybrid lexical-semantic vectors.")
            self._is_available = False

    def embed_text(self, text: str) -> np.ndarray:
        """Embeds single text into a unit-normalized vector."""
        if not text:
            return np.zeros(384, dtype=np.float32)

        self._init_model()
        if self._is_available and self._model is not None:
            try:
                embeddings = list(self._model.embed([text]))
                vec = np.array(embeddings[0], dtype=np.float32)
                norm = np.linalg.norm(vec)
                return vec / norm if norm > 1e-6 else vec
            except Exception as e:
                logger.debug(f"FastEmbed inference notice: {e}")

        # Fallback deterministic pseudo-vector (384 dim) based on token hashes
        # Ensures unit tests in strictly isolated/offline environments still run deterministically
        tokens = clean_text_for_tokens(text).split()
        vec = np.zeros(384, dtype=np.float32)
        for i, t in enumerate(tokens):
            h = hash(t) % 384
            vec[h] += 1.0 / (1.0 + 0.1 * i)
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 1e-6 else vec

    def compute_cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Computes cosine similarity between two normalized vectors."""
        if vec1 is None or vec2 is None or len(vec1) == 0 or len(vec2) == 0:
            return 0.0
        dot = float(np.dot(vec1, vec2))
        return max(0.0, min(1.0, dot))


def are_articles_same_event(
    art1: Any,
    art2: Any,
    profile: Optional[DiscoveryProfile] = None,
    embedding_service: Optional[SemanticEmbeddingService] = None
) -> Tuple[bool, str]:
    """
    Evaluates whether two articles refer to the exact same underlying real-world event.
    Combines:
      1. Exact URL / title match
      2. Action Domain Conflict Guard (e.g. DEFENSE_CONFLICT vs TRADE_ECONOMY)
      3. Geographical / Country Conflict Guard (e.g. Yemen vs Syria)
      4. Temporal window consistency (<= 72h publication gap)
      5. FastEmbed semantic similarity (handles heavy paraphrasing)
      6. Entity & Action overlap
    Returns: (is_same_event, reason)
    """
    # 1. Exact URL or normalized title match
    url1 = getattr(art1, "url", "")
    url2 = getattr(art2, "url", "")
    if url1 and url2 and url1 == url2:
        return True, "EXACT_URL_MATCH"

    title1 = getattr(art1, "normalized_title", "") or getattr(art1, "title", "")
    title2 = getattr(art2, "normalized_title", "") or getattr(art2, "title", "")
    if title1 and title2 and clean_text_for_tokens(title1) == clean_text_for_tokens(title2):
        return True, "EXACT_TITLE_MATCH"

    # Extract tokens if not already present
    active_profile = profile or get_active_discovery_profile()
    actions1 = getattr(art1, "action_tokens", set())
    actions2 = getattr(art2, "action_tokens", set())
    entities1 = getattr(art1, "entities", set())
    entities2 = getattr(art2, "entities", set())
    countries1 = getattr(art1, "countries", set())
    countries2 = getattr(art2, "countries", set())
    keywords1 = getattr(art1, "keywords", set())
    keywords2 = getattr(art2, "keywords", set())

    if not entities1 and not actions1:
        text1 = f"{title1}. {getattr(art1, 'summary', '') or getattr(art1, 'description', '')}"
        ent1, cnt1, act1, kw1 = extract_entities_and_tokens(text1, profile=active_profile)
        entities1 = entities1.union(ent1)
        countries1 = countries1.union(cnt1)
        actions1 = actions1.union(act1)
        keywords1 = keywords1.union(kw1)
    if not entities2 and not actions2:
        text2 = f"{title2}. {getattr(art2, 'summary', '') or getattr(art2, 'description', '')}"
        ent2, cnt2, act2, kw2 = extract_entities_and_tokens(text2, profile=active_profile)
        entities2 = entities2.union(ent2)
        countries2 = countries2.union(cnt2)
        actions2 = actions2.union(act2)
        keywords2 = keywords2.union(kw2)

    # 2. Check Action Domain Conflict
    domain_map = active_profile.action_domain_map if active_profile else ACTION_DOMAIN_MAP
    domains1 = determine_action_domains(actions1, action_domain_map=domain_map)
    domains2 = determine_action_domains(actions2, action_domain_map=domain_map)
    if domains1 and domains2 and not domains1.intersection(domains2):
        return False, "ACTION_DOMAIN_CONFLICT"

    # 3. Country / Location Conflict Guard:
    # "missile strike in Syria" and "missile strike in Yemen" must NEVER cluster!
    if countries1 and countries2 and not countries1.intersection(countries2):
        return False, f"COUNTRY_MISMATCH_{list(countries1)}_VS_{list(countries2)}"

    # 4. Temporal Window Guard
    pub1 = getattr(art1, "published_utc", None) or getattr(art1, "published_at", None)
    pub2 = getattr(art2, "published_utc", None) or getattr(art2, "published_at", None)
    if pub1 and pub2:
        delta_hours = abs((pub1 - pub2).total_seconds()) / 3600.0
        if delta_hours > 72.0:
            return False, f"TEMPORAL_WINDOW_EXCEEDED_{delta_hours:.1f}h"

    # 5. Semantic Vector Embedding Similarity (FastEmbed)
    service = embedding_service or SemanticEmbeddingService.get_instance()
    emb1 = getattr(art1, "embedding", None)
    if emb1 is None:
        text_for_emb1 = f"{title1}. {getattr(art1, 'summary', '') or getattr(art1, 'description', '')}"
        emb1 = service.embed_text(text_for_emb1)
        try:
            art1.embedding = emb1
        except Exception:
            pass

    emb2 = getattr(art2, "embedding", None)
    if emb2 is None:
        text_for_emb2 = f"{title2}. {getattr(art2, 'summary', '') or getattr(art2, 'description', '')}"
        emb2 = service.embed_text(text_for_emb2)
        try:
            art2.embedding = emb2
        except Exception:
            pass

    cos_sim = service.compute_cosine_similarity(emb1, emb2)
    token_sim = compute_jaccard(keywords1, keywords2)

    shared_entities = entities1.intersection(entities2)
    shared_countries = countries1.intersection(countries2)
    shared_actions = actions1.intersection(actions2)

    # Strong Semantic Paraphrasing Match (cosine similarity >= 0.78)
    # E.g. "missile strike hits port" vs "rockets were launched against the harbor"
    if cos_sim >= 0.78:
        return True, f"HIGH_SEMANTIC_SIM_{cos_sim:.2f}"

    # Moderate Semantic Similarity (>= 0.65) with shared entity/country or shared action
    if cos_sim >= 0.65 and (len(shared_entities) >= 1 or len(shared_countries) >= 1 or len(shared_actions) >= 1):
        return True, f"SEMANTIC_SIM_{cos_sim:.2f}_WITH_SHARED_EVIDENCE"

    # Token overlap fallback rules for backwards compatibility
    if token_sim >= 0.40:
        return True, f"HIGH_TOKEN_SIM_{token_sim:.2f}"

    if token_sim >= 0.25 and (len(shared_actions) >= 1 or len(domains1.intersection(domains2)) >= 1) and (len(shared_entities) >= 1 or len(shared_countries) >= 1):
        return True, f"MODERATE_TOKEN_SIM_{token_sim:.2f}_WITH_SHARED_ACTION_AND_ENTITY"

    if len(shared_entities) >= 2 and len(shared_actions) >= 1 and token_sim >= 0.18:
        return True, "SHARED_MULTIPLE_ENTITIES_AND_ACTION"

    return False, f"INSUFFICIENT_SIMILARITY_cos_{cos_sim:.2f}_token_{token_sim:.2f}"


class EventClusterEngine:
    """Aggregates multi-source articles into verified EventClusters and EventCards."""

    def __init__(
        self,
        min_semantic_sim: float = 0.65,
        profile: Optional[DiscoveryProfile] = None
    ):
        self.min_semantic_sim = min_semantic_sim
        self.profile = profile or get_active_discovery_profile()
        self.embedding_service = SemanticEmbeddingService.get_instance()
        self.verification_engine = EventVerificationEngine()

    def _select_canonical_title(self, cluster: EventCluster) -> str:
        """
        Selects or synthesizes the most concrete, specific title describing the actual event.
        Rejects generic editorial clichés ('Rising tensions', 'Major developments', 'What you need to know').
        """
        generic_markers = [
            "what to know", "what you need to know", "rising tensions", "crisis deepens",
            "major developments", "explained", "everything we know", "at a glance"
        ]

        candidate_titles = []
        for a in cluster.articles:
            t = getattr(a, "normalized_title", None) or getattr(a, "title", "")
            if not t:
                continue
            is_generic = any(g in t.lower() for g in generic_markers)
            word_count = len(t.split())
            score = 50.0

            # Prefer specific title lengths (7 to 18 words)
            if 7 <= word_count <= 18:
                score += 20.0
            elif word_count > 18:
                score -= 10.0

            # Penalize generic clickbait phrasing
            if is_generic:
                score -= 35.0

            # Boost established wire publishers
            pub = getattr(a, "source_name", "") or getattr(a, "publisher", "")
            if any(wire in pub.lower() for wire in ["reuters", "associated press", "ap news", "defense news", "bbc"]):
                score += 15.0

            candidate_titles.append((score, t))

        if candidate_titles:
            candidate_titles.sort(key=lambda x: x[0], reverse=True)
            return candidate_titles[0][1]

        return cluster.canonical_title or "Verified Geopolitical Event"

    def _extract_claims(self, cluster: EventCluster) -> List[ClaimEvidence]:
        """Extracts claim-level provenance from cluster articles."""
        claims: List[ClaimEvidence] = []
        seen_claims = set()

        for art in cluster.articles:
            art_id = getattr(art, "article_id", None) or getattr(art, "id", None) or getattr(art, "url", "")
            pub = getattr(art, "source_name", None) or getattr(art, "publisher", "Unknown")
            url = getattr(art, "url", None)
            pub_utc = getattr(art, "published_utc", None) or getattr(art, "published_at", None)

            text_sources = []
            title = getattr(art, "title", "")
            if title:
                text_sources.append(title)
            body = getattr(art, "article_text", "") or getattr(art, "summary", "") or getattr(art, "description", "")
            if body:
                text_sources.append(body)

            combined = " ".join(text_sources)
            # Break into candidate claim sentences
            sentences = [s.strip() for s in re.split(r"[.!?]", combined) if len(s.strip().split()) >= 6][:5]

            for s in sentences:
                clean_s = s.strip()
                if not clean_s.endswith("."):
                    clean_s += "."
                s_key = clean_text_for_tokens(clean_s)
                if s_key in seen_claims:
                    continue
                seen_claims.add(s_key)

                claims.append(ClaimEvidence(
                    claim_id=f"cl_{uuid.uuid4().hex[:8]}",
                    claim_text=clean_s,
                    publisher=pub,
                    source_article_id=art_id,
                    source_url=url,
                    published_utc=pub_utc,
                    evidence_excerpt=clean_s,
                    confidence=0.90,
                    verification_state="VERIFIED"
                ))

        return claims

    def cluster_articles(self, articles: List[Any]) -> List[EventCluster]:
        """
        Clusters articles into discrete EventClusters with semantic verification.
        """
        clusters: List[EventCluster] = []

        for art in articles:
            # Enrich article with entities and embeddings if missing
            title = getattr(art, "normalized_title", None) or getattr(art, "title", "")
            summary = getattr(art, "normalized_summary", None) or getattr(art, "summary", None) or getattr(art, "description", "")
            if not getattr(art, "entities", None) and not getattr(art, "action_tokens", None):
                ent, cnt, act, kw = extract_entities_and_tokens(f"{title}. {summary}", profile=self.profile)
                if hasattr(art, "entities"):
                    art.entities = (getattr(art, "entities", None) or set()).union(ent)
                    art.countries = (getattr(art, "countries", None) or set()).union(cnt)
                    art.action_tokens = (getattr(art, "action_tokens", None) or set()).union(act)
                    art.keywords = (getattr(art, "keywords", None) or set()).union(kw)

            matched_cluster: Optional[EventCluster] = None
            for cluster in clusters:
                rep_article = cluster.articles[0]
                is_same, reason = are_articles_same_event(
                    art,
                    rep_article,
                    profile=self.profile,
                    embedding_service=self.embedding_service
                )
                if is_same:
                    matched_cluster = cluster
                    logger.debug(f"[CLUSTERING] Merged '{title[:45]}' into cluster '{cluster.canonical_title[:45]}' ({reason})")
                    break

            if matched_cluster:
                matched_cluster.add_article(art)
            else:
                cluster_id = f"ev_{uuid.uuid4().hex[:12]}"
                new_cluster = EventCluster(
                    cluster_id=cluster_id,
                    canonical_title=title,
                    canonical_summary=summary
                )
                new_cluster.add_article(art)
                clusters.append(new_cluster)

        # Post-process each cluster: select canonical title, extract claims, and evaluate verification
        for cluster in clusters:
            cluster.canonical_title = self._select_canonical_title(cluster)
            cluster.claims = self._extract_claims(cluster)

            v_state, conf, conflicts, pub_info = self.verification_engine.evaluate_verification(
                cluster.articles,
                cluster.claims
            )
            cluster.verification_state = v_state.value if hasattr(v_state, "value") else str(v_state)
            cluster.confidence = conf
            cluster.conflicts = conflicts
            cluster.independent_publisher_count = pub_info["independent_publisher_count"]
            cluster.independent_publishers = pub_info["independent_publishers"]
            cluster.has_multi_source_consensus = (pub_info["independent_publisher_count"] >= 2)

        logger.info(f"[CLUSTERING] Formed {len(clusters)} event clusters from {len(articles)} articles.")
        return clusters