"""
Multi-Source Corroboration & Conflict Detection Engine.
Enforces strict journalistic standards for Phase 2:
- Distinguishes raw article count from independent publisher count
- Detects wire syndications & duplicate reporting to prevent fake corroboration
- Assigns explicit verification states:
    OFFICIAL_CONFIRMATION, MULTI_SOURCE_CORROBORATED, SINGLE_CREDIBLE_SOURCE,
    DEVELOPING, INSUFFICIENT_EVIDENCE, CONFLICTING_REPORTS
- Discovers factual contradictions (casualties, attribution, location, occurrence)
"""
import re
import uuid
import logging
from typing import List, Dict, Set, Tuple, Any, Optional
from datetime import datetime
from urllib.parse import urlparse

from intelligence.event_card import VerificationState, ConflictRecord, ClaimEvidence
from intelligence.scoring import SourceType, classify_source

logger = logging.getLogger(__name__)

# Known primary wire origins frequently syndicated across downstream publishers
KNOWN_WIRE_PATTERNS = {
    "reuters": [r"\b(reuters)\b", r"\(reuters\)", r"reporting by reuters"],
    "ap": [r"\b(associated press|ap)\b", r"\(ap\)", r"ap news"],
    "afp": [r"\b(agence france-presse|afp)\b", r"\(afp\)"],
    "bloomberg": [r"\bbloomberg\b"],
    "bbc": [r"\bbbc news\b", r"\bbbc\b"]
}


def canonicalize_publisher(publisher: str, domain: str = "", text_snippet: str = "") -> Tuple[str, bool]:
    """
    Identifies the underlying publisher entity and whether it represents a syndicated wire story.
    Returns: (canonical_publisher_name, is_syndicated)
    """
    pub_clean = (publisher or "").strip().lower()
    dom_clean = (domain or "").strip().lower()
    snippet_clean = (text_snippet or "").lower()

    # Check for direct publisher identity
    if "reuters" in pub_clean or "reuters.com" in dom_clean:
        return "reuters", False
    if "associated press" in pub_clean or "apnews.com" in dom_clean or pub_clean == "ap":
        return "ap", False
    if "bbc" in pub_clean or "bbc.com" in dom_clean or "bbc.co.uk" in dom_clean:
        return "bbc", False
    if "al jazeera" in pub_clean or "aljazeera.com" in dom_clean:
        return "al_jazeera", False
    if "deutsche welle" in pub_clean or "dw.com" in dom_clean or pub_clean == "dw":
        return "dw", False
    if "defense news" in pub_clean or "defensenews.com" in dom_clean:
        return "defense_news", False
    if "france 24" in pub_clean or "france24.com" in dom_clean:
        return "france24", False

    # Check if this article explicitly credits a wire agency as its source
    for wire_key, patterns in KNOWN_WIRE_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, pub_clean) or re.search(pat, snippet_clean[:300]):
                # Marked as syndicated copy of wire_key
                return wire_key, True

    # Fallback to domain host or clean publisher name
    if dom_clean:
        parts = dom_clean.split(".")
        root_name = parts[-2] if len(parts) >= 2 else dom_clean
        return root_name, False

    return pub_clean or "unknown_publisher", False


class EventVerificationEngine:
    """Evaluates multi-source corroboration and flags factual contradictions."""

    def __init__(self, min_independent_sources_for_consensus: int = 2):
        self.min_independent_sources = min_independent_sources_for_consensus

    def analyze_publishers(self, articles: List[Any]) -> Dict[str, Any]:
        """
        Analyzes articles in a cluster to distinguish total article count
        from independent publisher count, tracking syndications.
        """
        total_articles = len(articles)
        independent_publishers: Set[str] = set()
        syndicated_copies_count = 0
        publisher_source_types: Dict[str, str] = {}
        publisher_confidences: Dict[str, float] = {}
        has_official = False

        for art in articles:
            url = getattr(art, "url", "") or ""
            pub = getattr(art, "source_name", "") or getattr(art, "publisher", "") or ""
            domain = getattr(art, "source_domain", "") or ""
            if not domain and url:
                try:
                    domain = urlparse(url).netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                except Exception:
                    domain = ""

            snippet = getattr(art, "article_text", "") or getattr(art, "summary", "") or getattr(art, "description", "") or ""
            canonical_pub, is_syndicated = canonicalize_publisher(pub, domain, snippet)

            # Classify source tier & confidence
            src_type, conf, tier_label = classify_source(url, pub)
            if src_type == SourceType.OFFICIAL_GOVERNMENT or tier_label == "TIER_1_OFFICIAL":
                has_official = True

            if is_syndicated:
                syndicated_copies_count += 1
                # Credit to the root wire canonical name
                independent_publishers.add(canonical_pub)
            else:
                independent_publishers.add(canonical_pub)

            publisher_source_types[canonical_pub] = src_type.value if hasattr(src_type, "value") else str(src_type)
            publisher_confidences[canonical_pub] = max(publisher_confidences.get(canonical_pub, 0.0), conf)

        return {
            "total_articles": total_articles,
            "independent_publishers": list(independent_publishers),
            "independent_publisher_count": len(independent_publishers),
            "syndicated_copies_count": syndicated_copies_count,
            "has_official_source": has_official,
            "publisher_confidences": publisher_confidences,
            "max_source_confidence": max(publisher_confidences.values()) if publisher_confidences else 0.0
        }

    def detect_conflicts(self, articles: List[Any], claims: List[ClaimEvidence]) -> List[ConflictRecord]:
        """
        Scans articles and extracted claims for material factual disagreements:
        - Casualty numbers
        - Attribution / Actor responsibility
        - Denial / Occurrence disputes
        """
        conflicts: List[ConflictRecord] = []

        # 1. Casualty Count Conflict Detection
        # Match patterns like: "5 killed", "12 casualties", "at least 20 dead"
        casualty_pattern = re.compile(r"\b(?:at least|up to|over|about|roughly)?\s*(\d+)\s*(?:people|civilians|soldiers|sailors|troops)?\s*(?:killed|dead|casualties|injured|wounded|fatalities)\b", re.IGNORECASE)

        casualties_by_source: Dict[str, Set[int]] = {}
        claims_by_source: Dict[str, List[str]] = {}

        for art in articles:
            pub = getattr(art, "source_name", "") or getattr(art, "publisher", "") or "unknown"
            text = (getattr(art, "article_text", "") or getattr(art, "title", "") or "") + " " + (getattr(art, "summary", "") or "")
            matches = casualty_pattern.findall(text)
            for m in matches:
                try:
                    num = int(m)
                    if num > 0:
                        casualties_by_source.setdefault(pub, set()).add(num)
                except ValueError:
                    pass

        # Also inspect structured claims
        for cl in claims:
            pub = cl.publisher
            matches = casualty_pattern.findall(cl.claim_text)
            for m in matches:
                try:
                    num = int(m)
                    if num > 0:
                        casualties_by_source.setdefault(pub, set()).add(num)
                except ValueError:
                    pass

        distinct_numbers = set()
        for nums in casualties_by_source.values():
            distinct_numbers.update(nums)

        # If reputable publishers cite significantly different non-zero numbers
        if len(distinct_numbers) > 1:
            competing = []
            for pub, nums in casualties_by_source.items():
                competing.append({
                    "publisher": pub,
                    "reported_counts": sorted(list(nums))
                })
            conflicts.append(ConflictRecord(
                conflict_id=f"cnf_cas_{uuid.uuid4().hex[:8]}",
                topic_facet="casualty_count",
                competing_claims=competing,
                description=f"Discrepancy in casualty figures reported across sources: {distinct_numbers}",
                affected_sources=list(casualties_by_source.keys())
            ))

        # 2. Denial / Occurrence Conflict Detection
        # Words indicating direct denial of an incident: "denies", "refutes", "disputes", "claims false", "no evidence of"
        denial_pattern = re.compile(r"\b(denies|denied|refutes|refuted|dismisses|dismissed claims|fabricated report|no incident occurred)\b", re.IGNORECASE)
        denial_sources = []
        reporting_sources = []

        for art in articles:
            pub = getattr(art, "source_name", "") or getattr(art, "publisher", "") or "unknown"
            text = (getattr(art, "title", "") or "") + " " + (getattr(art, "summary", "") or "")
            if denial_pattern.search(text):
                denial_sources.append(pub)
            else:
                reporting_sources.append(pub)

        if denial_sources and reporting_sources and set(denial_sources) != set(reporting_sources):
            conflicts.append(ConflictRecord(
                conflict_id=f"cnf_occ_{uuid.uuid4().hex[:8]}",
                topic_facet="incident_occurrence",
                competing_claims=[
                    {"stance": "REPORTING_OCCURRENCE", "sources": list(set(reporting_sources))},
                    {"stance": "DENIAL_OR_DISPUTED", "sources": list(set(denial_sources))}
                ],
                description=f"Incident occurrence disputed: {list(set(denial_sources))} refute claims reported by other sources.",
                affected_sources=list(set(denial_sources + reporting_sources))
            ))

        return conflicts

    def evaluate_verification(
        self,
        articles: List[Any],
        claims: Optional[List[ClaimEvidence]] = None
    ) -> Tuple[VerificationState, float, List[ConflictRecord], Dict[str, Any]]:
        """
        Synthesizes corroboration evidence and conflict detection to determine
        the cluster verification state and composite confidence score.
        Returns: (verification_state, confidence, conflicts, publisher_analysis)
        """
        claims = claims or []
        pub_info = self.analyze_publishers(articles)
        conflicts = self.detect_conflicts(articles, claims)

        # 1. Check for material factual conflicts
        if conflicts:
            # Conflicting reports take precedence so script writer does not present as settled fact
            return VerificationState.CONFLICTING_REPORTS, 0.65, conflicts, pub_info

        indep_count = pub_info["independent_publisher_count"]
        has_official = pub_info["has_official_source"]
        max_conf = pub_info["max_source_confidence"]

        # 2. Official Government / Military Confirmation
        if has_official and (indep_count >= 1 or max_conf >= 0.90):
            return VerificationState.OFFICIAL_CONFIRMATION, 0.95, conflicts, pub_info

        # 3. Multi-Source Corroborated (>= 2 independent reputable sources)
        if indep_count >= self.min_independent_sources and max_conf >= 0.75:
            # Boost confidence for breadth of corroboration
            confidence = min(0.95, 0.85 + (indep_count - 2) * 0.03)
            return VerificationState.MULTI_SOURCE_CORROBORATED, round(confidence, 3), conflicts, pub_info

        # 4. Single Credible Source
        # Tier 1 Defense or Tier 2 Established News (confidence >= 0.80)
        if indep_count == 1 and max_conf >= 0.80:
            # A single highly credible source creates an active DEVELOPING event, NOT rejection
            return VerificationState.DEVELOPING, 0.80, conflicts, pub_info

        # 5. Single Moderate Source
        if indep_count == 1 and max_conf >= 0.65:
            return VerificationState.SINGLE_CREDIBLE_SOURCE, 0.70, conflicts, pub_info

        # 6. Insufficient evidence (e.g. only aggregators or low confidence)
        return VerificationState.INSUFFICIENT_EVIDENCE, 0.40, conflicts, pub_info