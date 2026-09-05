"""
Visual Matching & Relevance Scoring Engine for AL-AMR Phase 4.
============================================================
Evaluates retrieved visual candidates against EventCard claims and ScriptBeat
visual query specifications.

Enforces:
  1. Multidimensional Relevance Scoring:
     - Entity overlap score
     - Action verb / event dynamic score
     - Geographic consistency score with HARD GEOGRAPHIC GATING (rejects mismatches)
     - Temporal proximity score
     - Source reliability weighting
  2. Authenticity Classification:
     - EVENT_SPECIFIC: Verified match for the exact reported incident
     - EVENT_RELATED: Direct match for involved vessel, unit, weapon system, or base
     - CONTEXTUAL: Real footage of relevant country or armed service (not this event)
     - GENERIC: Stock footage (strictly never promoted to EVENT_SPECIFIC)
  3. Safe Fallback & Non-Fabrication:
     - Explicit rejection when score is below threshold or geographic conflict detected.
     - Zero hallucination / zero visual synthesis.
"""

import logging
import math
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any

from intelligence.visual_models import (
    VisualAuthenticity,
    VisualEvidenceCandidate,
    VisualLicensingStatus,
)

logger = logging.getLogger("alamr.visual_matching")

# Country / Region conflict mapping for Geographic Gating
KNOWN_THEATERS = {
    "red_sea": {"red sea", "yemen", "houthi", "bab el-mandeb", "gulf of aden", "hodeidah", "sanaa"},
    "baltic": {"baltic", "denmark", "sweden", "finland", "estonia", "latvia", "lithuania", "bornholm", "kattegat", "great belt"},
    "taiwan_strait": {"taiwan", "taiwan strait", "kinmen", "penghu", "matsu", "fujian"},
    "black_sea": {"black sea", "crimea", "sevastopol", "odessa", "kerch", "novorossiysk", "bosporus"},
    "middle_east_levant": {"syria", "lebanon", "israel", "gaza", "damascus", "beirut", "golan"},
    "persian_gulf": {"persian gulf", "strait of hormuz", "iran", "uae", "oman", "fujairah", "bandar abbas"},
    "south_china_sea": {"south china sea", "second thomas shoal", "spratly", "paracel", "philippines", "scarborough shoal"},
    "korean_peninsula": {"north korea", "south korea", "pyongyang", "seoul", "dmz", "yellow sea"},
}


class VisualRelevanceScorer:
    """
    Evaluates visual evidence candidates for factual fidelity, geographic alignment,
    and editorial relevance.
    """

    MINIMUM_ACCEPTABLE_SCORE = 0.35
    EVENT_SPECIFIC_THRESHOLD = 0.72
    EVENT_RELATED_THRESHOLD = 0.50

    def __init__(self):
        pass

    def score_candidate(
        self,
        candidate: VisualEvidenceCandidate,
        target_query: str,
        event_entities: Optional[List[str]] = None,
        event_locations: Optional[List[str]] = None,
        event_actions: Optional[List[str]] = None,
        event_time: Optional[datetime] = None,
    ) -> VisualEvidenceCandidate:
        """
        Calculates all sub-scores, applies geographic gating, determines
        authenticity and final composite score, updating candidate in-place.
        """
        text_corpus = f"{candidate.title} {candidate.description} {' '.join(candidate.provenance.get('tags', []))}".lower()

        # 1. Geographic Gating & Location Score
        loc_score, geo_rejected, geo_reason = self._compute_location_score(
            text_corpus, event_locations
        )
        if geo_rejected:
            candidate.location_match_score = 0.0
            candidate.match_score = 0.0
            candidate.retrieval_status = "REJECTED"
            candidate.rejection_reason = f"Geographic Mismatch: {geo_reason}"
            candidate.authenticity = VisualAuthenticity.GENERIC.value
            return candidate

        candidate.location_match_score = loc_score

        # 2. Entity Overlap Score
        cand_entity_score = self._compute_entity_score(text_corpus, event_entities)
        candidate.entity_match_score = cand_entity_score

        # 3. Action Verb / Dynamic Score
        cand_action_score = self._compute_action_score(text_corpus, event_actions, target_query)
        candidate.action_match_score = cand_action_score

        # 4. Temporal Proximity Score
        cand_temp_score = self._compute_temporal_score(candidate.published_at, event_time)
        candidate.temporal_match_score = cand_temp_score

        # 5. Composite Match Score
        # Weights: Entity (30%), Location (25%), Action (25%), Temporal (10%), Source Reliability (10%)
        composite = (
            0.30 * candidate.entity_match_score
            + 0.25 * candidate.location_match_score
            + 0.25 * candidate.action_match_score
            + 0.10 * candidate.temporal_match_score
            + 0.10 * candidate.source_reliability_score
        )
        candidate.match_score = round(max(0.0, min(1.0, composite)), 3)

        # 6. Event Specificity Score
        cand_spec = (
            candidate.entity_match_score * 0.4
            + candidate.location_match_score * 0.3
            + candidate.action_match_score * 0.3
        )
        candidate.event_specificity_score = round(cand_spec, 3)

        # 7. Authenticity Classification
        self._classify_authenticity(candidate)

        # 8. Final Status
        if candidate.match_score < self.MINIMUM_ACCEPTABLE_SCORE:
            candidate.retrieval_status = "REJECTED"
            candidate.rejection_reason = f"Relevance score {candidate.match_score:.2f} below threshold {self.MINIMUM_ACCEPTABLE_SCORE:.2f}"
        else:
            candidate.retrieval_status = "AVAILABLE"

        return candidate

    def _compute_location_score(
        self, text_corpus: str, event_locations: Optional[List[str]]
    ) -> Tuple[float, bool, Optional[str]]:
        """
        Calculates location match score and enforces geographic gating against theater conflicts.
        """
        if not event_locations:
            return 0.5, False, None

        target_theaters: Set[str] = set()
        matched_locations: List[str] = []

        # Identify which theater(s) the target event belongs to
        clean_target_locs = [loc.lower().strip() for loc in event_locations if loc]
        for loc in clean_target_locs:
            for th_name, th_keywords in KNOWN_THEATERS.items():
                if any(kw in loc for kw in th_keywords):
                    target_theaters.add(th_name)

        # Check for direct location mentions
        for loc in clean_target_locs:
            pattern = r"\b" + re.escape(loc) + r"\b"
            if re.search(pattern, text_corpus):
                matched_locations.append(loc)

        # Detect conflicting theater mentions in candidate
        conflicting_theaters: Set[str] = set()
        if target_theaters:
            for th_name, th_keywords in KNOWN_THEATERS.items():
                if th_name not in target_theaters:
                    for kw in th_keywords:
                        pattern = r"\b" + re.escape(kw) + r"\b"
                        if re.search(pattern, text_corpus):
                            conflicting_theaters.add(th_name)
                            break

        # HARD GATING: If candidate mentions conflicting theater and no direct location match, reject!
        if conflicting_theaters and not matched_locations:
            conflict_names = ", ".join(conflicting_theaters)
            target_names = ", ".join(target_theaters)
            return (
                0.0,
                True,
                f"Candidate mentions conflicting theater [{conflict_names}] while event is in [{target_names}]",
            )

        # If direct target location matches
        if matched_locations:
            ratio = len(matched_locations) / max(1, len(clean_target_locs))
            return min(1.0, 0.7 + 0.3 * ratio), False, None

        # If theater keywords match
        if target_theaters:
            for th in target_theaters:
                th_kw = KNOWN_THEATERS[th]
                if any(re.search(r"\b" + re.escape(kw) + r"\b", text_corpus) for kw in th_kw):
                    return 0.70, False, None

        return 0.3, False, None

    def _compute_entity_score(
        self, text_corpus: str, event_entities: Optional[List[str]]
    ) -> float:
        """Calculates keyword/entity overlap score."""
        if not event_entities:
            return 0.5

        clean_entities = [e.lower().strip() for e in event_entities if e and len(e.strip()) > 2]
        if not clean_entities:
            return 0.5

        matched = 0.0
        for entity in clean_entities:
            pattern = r"\b" + re.escape(entity) + r"\b"
            if re.search(pattern, text_corpus):
                matched += 1.0
            else:
                tokens = [t for t in re.split(r"\s+", entity) if len(t) > 3]
                if tokens and all(re.search(r"\b" + re.escape(tok) + r"\b", text_corpus) for tok in tokens):
                    matched += 0.85
                elif tokens and any(re.search(r"\b" + re.escape(tok) + r"\b", text_corpus) for tok in tokens):
                    matched += 0.40

        ratio = matched / len(clean_entities)
        return min(1.0, round(ratio, 3))

    def _compute_action_score(
        self, text_corpus: str, event_actions: Optional[List[str]], target_query: str
    ) -> float:
        """Calculates action verb and military/event dynamic overlap."""
        candidates_actions: Set[str] = set()
        if event_actions:
            candidates_actions.update(a.lower().strip() for a in event_actions if a)

        query_words = [w.lower().strip() for w in re.split(r"\s+", target_query) if len(w) > 3]
        candidates_actions.update(query_words)

        if not candidates_actions:
            return 0.5

        matched = 0
        for act in candidates_actions:
            pattern = r"\b" + re.escape(act) + r"\b"
            if re.search(pattern, text_corpus):
                matched += 1

        score = min(1.0, matched / max(1, min(len(candidates_actions), 5)))
        return round(score, 3)

    def _compute_temporal_score(
        self, candidate_pub: Optional[datetime], event_time: Optional[datetime]
    ) -> float:
        """
        Evaluates temporal closeness between candidate publication and event occurrence.
        Events within 24h: 1.0; 48h: 0.85; 7d: 0.60; 30d: 0.35; older: 0.15.
        """
        if not candidate_pub or not event_time:
            return 0.5

        dt_cand = candidate_pub.astimezone(timezone.utc) if candidate_pub.tzinfo else candidate_pub.replace(tzinfo=timezone.utc)
        dt_event = event_time.astimezone(timezone.utc) if event_time.tzinfo else event_time.replace(tzinfo=timezone.utc)

        delta_hours = abs((dt_cand - dt_event).total_seconds()) / 3600.0

        if delta_hours <= 24:
            return 1.0
        elif delta_hours <= 48:
            return 0.85
        elif delta_hours <= 168:
            return 0.60
        elif delta_hours <= 720:
            return 0.35
        else:
            return 0.15

    def _classify_authenticity(self, candidate: VisualEvidenceCandidate) -> None:
        """
        Assigns strict authenticity classification.
        Hard Invariant: STOCK_API sources can NEVER be EVENT_SPECIFIC.
        """
        if candidate.source_type == "STOCK_API":
            candidate.authenticity = VisualAuthenticity.GENERIC.value
            return

        if candidate.match_score >= self.EVENT_SPECIFIC_THRESHOLD and candidate.location_match_score >= 0.7:
            candidate.authenticity = VisualAuthenticity.EVENT_SPECIFIC.value
        elif candidate.match_score >= self.EVENT_RELATED_THRESHOLD:
            candidate.authenticity = VisualAuthenticity.EVENT_RELATED.value
        else:
            candidate.authenticity = VisualAuthenticity.CONTEXTUAL.value
