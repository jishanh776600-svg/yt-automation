"""
Visual Evidence Retrieval Engine for AL-AMR Phase 4.
===================================================
Coordinates real-event visual retrieval across multi-tier sources (Tier 1-3),
evaluates candidates with VisualRelevanceScorer (including hard geographic gating),
and compiles a beat-level VisualEvidencePlan for an EventCard + ScriptDocument.

Core Invariants:
  - 100% Cloud-native & Headless: Zero browser / Selenium / Playwright dependencies.
  - Zero Fabrication: When no authentic or safe visual exists, records NO_VISUAL
    with selected_candidate=None. Never invents footage or falsifies authenticity.
  - Tier Authority: Official defense / primary media > News Wire > Stock API.
  - Beat-Level Evidence: Directly connects ScriptBeat.visual_query_candidates
    and structured claims to verified visual evidence.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

from intelligence.event_card import EventCard
from intelligence.journalistic_script import ScriptDocument, ScriptBeat
from intelligence.visual_models import (
    BeatVisualPlan,
    VisualAuthenticity,
    VisualCoverageType,
    VisualEvidenceCandidate,
    VisualEvidencePlan,
)
from intelligence.visual_matching import VisualRelevanceScorer
from intelligence.visual_sources import VisualSourceManager

logger = logging.getLogger("alamr.visual_evidence")


class VisualEvidenceRetrievalEngine:
    """
    Main Phase 4 engine: transforms an EventCard + ScriptDocument into an
    auditable, beat-by-beat VisualEvidencePlan.
    """

    def __init__(
        self,
        source_manager: Optional[VisualSourceManager] = None,
        scorer: Optional[VisualRelevanceScorer] = None,
    ):
        self.source_manager = source_manager or VisualSourceManager()
        self.scorer = scorer or VisualRelevanceScorer()

    def generate_evidence_plan(
        self,
        event_card: EventCard,
        script_doc: ScriptDocument,
        max_candidates_per_tier: int = 3,
    ) -> VisualEvidencePlan:
        """
        Execute visual retrieval and evidence matching across all beats of a ScriptDocument.

        Args:
            event_card: Verified Phase 2 EventCard
            script_doc: Claim-grounded Phase 3 ScriptDocument
            max_candidates_per_tier: Limit on candidate searches per source tier

        Returns:
            Fully populated VisualEvidencePlan
        """
        event_id = getattr(event_card, "event_id", getattr(event_card, "card_id", "unknown_event"))
        logger.info(
            f"Beginning visual evidence retrieval for EventCard {event_id} "
            f"and Script {script_doc.script_id}"
        )

        beat_plans: List[BeatVisualPlan] = []

        # Extract global event signals for matching
        event_entities: List[str] = []
        if hasattr(event_card, "entities") and event_card.entities:
            event_entities.extend(event_card.entities)
        if hasattr(event_card, "who") and event_card.who:
            who = event_card.who
            event_entities.extend(getattr(who, "organizations", []) + getattr(who, "military_units", []) + getattr(who, "countries", []))

        event_locations: List[str] = []
        if hasattr(event_card, "where") and event_card.where:
            where = event_card.where
            for attr in ["location_name", "region", "country", "city"]:
                v = getattr(where, attr, None)
                if v:
                    event_locations.append(v)
        elif hasattr(event_card, "location") and event_card.location:
            event_locations.append(event_card.location)

        event_actions: List[str] = []
        if hasattr(event_card, "actions") and event_card.actions:
            event_actions.extend(event_card.actions)
        if hasattr(event_card, "action") and event_card.action:
            event_actions.append(event_card.action)
        if hasattr(event_card, "what") and event_card.what:
            event_actions.append(event_card.what)

        event_time: Optional[datetime] = None
        if hasattr(event_card, "when") and event_card.when and getattr(event_card.when, "event_time_utc", None):
            event_time = event_card.when.event_time_utc
        elif hasattr(event_card, "first_seen_utc") and event_card.first_seen_utc:
            event_time = event_card.first_seen_utc
        elif hasattr(event_card, "occurred_at") and event_card.occurred_at:
            event_time = event_card.occurred_at

        for idx, beat in enumerate(script_doc.beats):
            plan_beat = self._process_beat(
                beat=beat,
                sequence=idx + 1,
                event_card=event_card,
                event_id=event_id,
                event_entities=event_entities,
                event_locations=event_locations,
                event_actions=event_actions,
                event_time=event_time,
                max_candidates_per_tier=max_candidates_per_tier,
            )
            beat_plans.append(plan_beat)

        evidence_plan = VisualEvidencePlan(
            event_id=event_id,
            script_id=script_doc.script_id,
            beat_plans=beat_plans,
        )
        evidence_plan.compute_metrics()

        logger.info(
            f"Completed VisualEvidencePlan for Script {script_doc.script_id}: "
            f"Evidence Ratio={evidence_plan.overall_evidence_ratio:.2f} "
            f"(Direct={evidence_plan.direct_evidence_count}, Related={evidence_plan.related_evidence_count}, "
            f"Contextual={evidence_plan.contextual_count}, NoVisual={evidence_plan.no_visual_count})"
        )

        return evidence_plan

    def _process_beat(
        self,
        beat: ScriptBeat,
        sequence: int,
        event_card: EventCard,
        event_id: str,
        event_entities: List[str],
        event_locations: List[str],
        event_actions: List[str],
        event_time: Optional[datetime],
        max_candidates_per_tier: int,
    ) -> BeatVisualPlan:
        """Processes candidate retrieval and evidence selection for a single beat."""
        # 1. Determine search queries
        query_candidates = list(beat.visual_query_candidates) if beat.visual_query_candidates else []
        if not query_candidates:
            primary_entity = event_entities[0] if event_entities else ""
            primary_location = event_locations[0] if event_locations else ""
            title = getattr(event_card, "canonical_title", getattr(event_card, "title", ""))
            query_candidates.append(f"{primary_entity} {primary_location} {title[:40]}".strip())

        primary_query = query_candidates[0]

        # Combine beat-specific entities with global event entities
        beat_entities = list(event_entities)
        if hasattr(beat, "structured_claim") and beat.structured_claim:
            claim_entities = beat.structured_claim.get("entities", [])
            if isinstance(claim_entities, list):
                beat_entities.extend(claim_entities)

        # 2. Retrieve candidates across tiers
        raw_candidates: List[VisualEvidenceCandidate] = []
        for q in query_candidates[:2]:
            results = self.source_manager.retrieve_candidates(
                query=q,
                event_id=event_id,
                beat_id=beat.beat_id,
                target_entities=beat_entities,
                target_locations=event_locations,
                event_date_hint=event_time.isoformat() if event_time else None,
                max_candidates_per_tier=max_candidates_per_tier,
            )
            raw_candidates.extend(results)

        # 3. Score all retrieved candidates
        scored_candidates: List[VisualEvidenceCandidate] = []
        seen_ids = set()

        for cand in raw_candidates:
            if cand.visual_id in seen_ids:
                continue
            seen_ids.add(cand.visual_id)

            scored = self.scorer.score_candidate(
                candidate=cand,
                target_query=primary_query,
                event_entities=beat_entities,
                event_locations=event_locations,
                event_actions=event_actions,
                event_time=event_time,
            )
            scored_candidates.append(scored)

        # 4. Rank candidates
        tier_weights = {
            "OFFICIAL_GOVERNMENT": 1.0,
            "WIRE_SERVICE": 0.9,
            "STOCK_API": 0.6,
            "ARCHIVE": 0.5,
        }

        def sort_key(c: VisualEvidenceCandidate) -> Tuple[int, float, float]:
            is_avail = 1 if c.retrieval_status == "AVAILABLE" else 0
            tier_w = tier_weights.get(c.source_type, 0.5)
            return (is_avail, tier_w, c.match_score)

        sorted_candidates = sorted(scored_candidates, key=sort_key, reverse=True)

        # 5. Select top candidate and assign coverage
        available = [c for c in sorted_candidates if c.retrieval_status == "AVAILABLE"]
        
        selected_candidate: Optional[VisualEvidenceCandidate] = None
        coverage_type = VisualCoverageType.NO_VISUAL.value

        if available:
            top_cand = available[0]
            selected_candidate = top_cand

            if top_cand.authenticity == VisualAuthenticity.EVENT_SPECIFIC.value:
                coverage_type = VisualCoverageType.DIRECT_EVIDENCE.value
            elif top_cand.authenticity == VisualAuthenticity.EVENT_RELATED.value:
                coverage_type = VisualCoverageType.RELATED_EVIDENCE.value
            else:
                coverage_type = VisualCoverageType.CONTEXTUAL.value
        else:
            coverage_type = VisualCoverageType.NO_VISUAL.value
            selected_candidate = None

        return BeatVisualPlan(
            beat_id=beat.beat_id,
            sequence=sequence,
            beat_text=beat.text,
            coverage_type=coverage_type,
            selected_candidate=selected_candidate,
            candidate_pool=sorted_candidates[:6],
            target_query=primary_query,
        )
