"""
Deterministic Multi-Factor Visual Candidate Scoring Engine.
Ranks visual candidates by:
  - semantic_relevance
  - entity_match
  - event_match
  - location_match
  - date_match
  - motion_score (video-first)
  - visual_quality / resolution
  - freshness
  - source_quality
  - editorial_fit
  - rights_confidence
  - provenance_completeness

Penalties:
  - duplicate
  - near_duplicate
  - recent_use
  - generic_stock
  - rights_risk
  - misleading_context

Strictly prefers accurate/contextually relevant footage over beautiful but generic footage.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Set
from .models import VisualCandidate, VisualIntent, RightsStatus, VisualContentType

logger = logging.getLogger(__name__)


class VisualCandidateScorer:
    """
    Deterministic scoring and ranking model for visual assets.
    Prioritizes real entity footage, authentic events, and verified provenance.
    """

    # Multi-factor weights summing to 1.00
    WEIGHT_RELEVANCE = 0.18
    WEIGHT_ENTITY = 0.22
    WEIGHT_EVENT = 0.12
    WEIGHT_LOCATION = 0.08
    WEIGHT_DATE = 0.06
    WEIGHT_MOTION = 0.12
    WEIGHT_QUALITY = 0.08
    WEIGHT_SOURCE_QUALITY = 0.04
    WEIGHT_EDITORIAL_FIT = 0.04
    WEIGHT_RIGHTS_CONFIDENCE = 0.03
    WEIGHT_PROVENANCE = 0.03

    # Motion scores by content type (Video-First Rule)
    MOTION_TIERS = {
        VisualContentType.REAL_VIDEO: 1.0,
        VisualContentType.LIVE_EVENT_FOOTAGE: 0.95,
        VisualContentType.ARCHIVAL_VIDEO: 0.88,
        VisualContentType.OFFICIAL_PUBLIC_RECORD: 0.85,
        VisualContentType.ANIMATED_DATA_MAP: 0.70,
        VisualContentType.MEME_REACTION: 0.80,
        VisualContentType.SCREENSHOT_DOCUMENT: 0.50,
        VisualContentType.STATIC_PHOTO: 0.35,
        VisualContentType.GENERIC_STOCK_VIDEO: 0.60,
        VisualContentType.GENERIC_STOCK_IMAGE: 0.20
    }

    def compute_motion_score(self, candidate: VisualCandidate) -> float:
        """Calculates motion score adhering strictly to the Video-First Rule."""
        base_motion = self.MOTION_TIERS.get(candidate.content_type, 0.50)
        if candidate.is_video:
            if candidate.width >= 1080 and candidate.height >= 1080:
                base_motion = min(1.0, base_motion + 0.05)
        return round(base_motion, 3)

    def evaluate_entity_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates whether candidate specifically depicts the requested primary or secondary entities."""
        if not intent.primary_entity:
            return 0.70  # Neutral baseline when no specific entity is requested

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.entity_tags)}".lower()
        entity_lower = intent.primary_entity.lower()

        # Exact match
        if entity_lower in cand_text:
            return 1.0

        # Token match for multi-word entities (e.g. 'Donald Trump')
        entity_tokens = [t for t in re.split(r'\s+', entity_lower) if len(t) > 2]
        if entity_tokens:
            matches = sum(1 for t in entity_tokens if t in cand_text)
            match_ratio = matches / len(entity_tokens)
            if match_ratio >= 0.5:
                return round(0.50 + (0.50 * match_ratio), 2)

        # Check secondary entities
        for sec in intent.secondary_entities:
            if sec.lower() in cand_text:
                return 0.65

        # No entity match: heavy penalty when a specific person/entity was requested
        return 0.10

    def evaluate_event_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates match to the news or historical event being discussed."""
        if not intent.event and not intent.action:
            return 0.60

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.event_tags)}".lower()
        target_event = (intent.event or "").lower()
        target_action = (intent.action or "").lower()

        score = 0.30
        if target_action and target_action in cand_text:
            score += 0.35
        if target_event:
            tokens = [t for t in re.split(r'\s+', target_event) if len(t) > 3]
            if tokens:
                matches = sum(1 for t in tokens if t in cand_text)
                score += min(0.35, 0.35 * (matches / max(1, len(tokens))))

        return min(1.0, round(score, 2))

    def evaluate_location_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates geographic / location relevance."""
        if not intent.location:
            return 0.70  # Neutral if no location required

        cand_text = f"{candidate.title} {candidate.description}".lower()
        loc_lower = intent.location.lower()

        if loc_lower in cand_text:
            return 1.0
        return 0.30

    def evaluate_date_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates chronological era or date alignment."""
        if not intent.date_context:
            return 0.70

        target_date = str(intent.date_context).lower()
        cand_text = f"{candidate.title} {candidate.description} {getattr(candidate.provenance, 'publication_date', '')}".lower()

        if target_date in cand_text:
            return 1.0

        # Check year extraction match
        target_years = re.findall(r'\b(1[89]\d{2}|20\d{2})\b', target_date)
        if target_years:
            if any(y in cand_text for y in target_years):
                return 0.90

        return 0.40

    def evaluate_semantic_relevance(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates lexical and thematic overlap with the narration beat."""
        cand_words = set(re.findall(r'\b\w{3,}\b', f"{candidate.title} {candidate.description}".lower()))
        beat_words = set(re.findall(r'\b\w{3,}\b', intent.narration_text.lower()))

        if not beat_words:
            return 0.50

        overlap = cand_words.intersection(beat_words)
        ratio = len(overlap) / max(3, len(beat_words))
        return min(1.0, round(ratio * 1.5, 2))

    def evaluate_provenance_completeness(self, candidate: VisualCandidate) -> float:
        """Evaluates whether all required rights and origin fields are verified."""
        prov = candidate.provenance
        if not prov:
            return 0.20

        score = 0.20
        if prov.creator:
            score += 0.20
        if prov.publisher:
            score += 0.20
        if prov.source_url:
            score += 0.20
        if prov.license_name and prov.license_name != "Unknown":
            score += 0.20
        return round(score, 2)

    def score_candidate(
        self,
        candidate: VisualCandidate,
        intent: VisualIntent,
        recent_usage_counts: Optional[Dict[str, int]] = None,
        job_used_urls: Optional[Set[str]] = None,
        near_duplicate_urls: Optional[Set[str]] = None
    ) -> float:
        """
        Computes final deterministic score for candidate under given intent.
        Enforces:
          - Accurate/contextual relevance dominates over generic beauty
          - Video > Photo motion preference
          - Strict penalties for duplicate, rights risk, and generic stock overuse
        """
        job_used = job_used_urls or set()
        near_dups = near_duplicate_urls or set()
        recent_counts = recent_usage_counts or {}

        # 1. Base Multi-Factor Scores
        rel_score = self.evaluate_semantic_relevance(candidate, intent)
        entity_score = self.evaluate_entity_match(candidate, intent)
        event_score = self.evaluate_event_match(candidate, intent)
        loc_score = self.evaluate_location_match(candidate, intent)
        date_score = self.evaluate_date_match(candidate, intent)
        motion_score = self.compute_motion_score(candidate)

        # Resolution / Visual Quality
        quality_score = 0.50
        if candidate.width >= 1080 and candidate.height >= 1920:
            quality_score = 1.0
        elif candidate.width >= 720 and candidate.height >= 1280:
            quality_score = 0.85
        elif candidate.width >= 1920 and candidate.height >= 1080:
            quality_score = 0.90  # 1080p landscape (crops cleanly)
        elif candidate.width < 720 or candidate.height < 720:
            quality_score = 0.20

        source_quality = 1.0 if candidate.source_class in ("SOURCE_A", "SOURCE_C") else 0.80
        editorial_fit = 0.95 if (candidate.content_type == intent.required_visual_type) else 0.65
        rights_confidence = getattr(candidate.provenance, "confidence_score", 0.90) if candidate.provenance else 0.50
        prov_completeness = self.evaluate_provenance_completeness(candidate)

        # Weighted Sum
        composite = (
            rel_score * self.WEIGHT_RELEVANCE +
            entity_score * self.WEIGHT_ENTITY +
            event_score * self.WEIGHT_EVENT +
            loc_score * self.WEIGHT_LOCATION +
            date_score * self.WEIGHT_DATE +
            motion_score * self.WEIGHT_MOTION +
            quality_score * self.WEIGHT_QUALITY +
            source_quality * self.WEIGHT_SOURCE_QUALITY +
            editorial_fit * self.WEIGHT_EDITORIAL_FIT +
            rights_confidence * self.WEIGHT_RIGHTS_CONFIDENCE +
            prov_completeness * self.WEIGHT_PROVENANCE
        )

        # 2. Penalties
        # Single-short duplicate: absolute disqualify
        if candidate.source_url in job_used:
            composite -= 1.00

        # Perceptual / Near-duplicate penalty
        if candidate.source_url in near_dups:
            composite -= 0.40

        # Cross-job recent repetition penalty (recent-use decay)
        prior_uses = recent_counts.get(candidate.source_url, 0)
        if prior_uses > 0:
            composite -= min(0.50, prior_uses * 0.20)

        # Rights risk penalty
        if candidate.rights_status == RightsStatus.RIGHTS_UNCERTAIN:
            composite -= 0.40

        # Generic stock overuse penalty when specific entity/event is requested
        if (intent.primary_entity or intent.event) and candidate.content_type in (
            VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE
        ):
            composite -= 0.25

        # Misleading context penalty (e.g. meme used during serious factual claim)
        if intent.emotional_tone in ("SERIOUS", "TRAGIC") and candidate.content_type == VisualContentType.MEME_REACTION:
            composite -= 0.50

        candidate.raw_score = round(composite, 4)
        candidate.final_score = candidate.raw_score
        return candidate.final_score

    def rank_candidates(
        self,
        candidates: List[VisualCandidate],
        intent: VisualIntent,
        recent_usage_counts: Optional[Dict[str, int]] = None,
        job_used_urls: Optional[Set[str]] = None,
        near_duplicate_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """Ranks candidates in descending order of computed score."""
        for c in candidates:
            self.score_candidate(
                c,
                intent,
                recent_usage_counts=recent_usage_counts,
                job_used_urls=job_used_urls,
                near_duplicate_urls=near_duplicate_urls
            )

        ranked = sorted(candidates, key=lambda c: c.final_score, reverse=True)
        return ranked
