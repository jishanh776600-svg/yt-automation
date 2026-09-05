"""
Visual Source Router: Orchestrates Multi-Tier Visual Acquisition.
Implements the Real-Footage-First Hierarchy:
  1. Real entity-specific footage (Editorial Press Pool)
  2. Relevant event/news footage (Editorial Archive)
  3. Archival footage (Internet Archive, Prelinger)
  4. Official/public-domain material (NASA, National Archives, Gov Records)
  5. Documents/headlines/maps/charts (Contextual Adapter)
  6. Contextual reaction/meme visuals (Reaction Adapter - with strict filter)
  7. Licensed stock footage as fallback (Pexels)
"""
import logging
from typing import List, Dict, Any, Optional, Set

from .models import VisualIntent, VisualCandidate, VisualContentType, RightsStatus
from .sources.base import BaseSourceAdapter
from .sources.pexels import PexelsAdapter
from .sources.editorial import EditorialAdapter
from .sources.wikimedia import WikimediaAdapter
from .sources.archive import ArchiveAdapter
from .sources.official import OfficialAdapter
from .sources.contextual import ContextualAdapter
from .sources.reaction import ReactionAdapter

logger = logging.getLogger(__name__)


class SourceRouter:
    """
    Intelligent routing and multi-source query dispatch.
    Prioritizes authentic real-world footage while using generic stock as a bounded fallback.
    """

    def __init__(self, pexels_api_key: Optional[str] = None):
        self.adapters: Dict[str, BaseSourceAdapter] = {
            "editorial": EditorialAdapter(),
            "official": OfficialAdapter(),
            "wikimedia": WikimediaAdapter(),
            "archive": ArchiveAdapter(),
            "contextual": ContextualAdapter(),
            "reaction": ReactionAdapter(),
            "pexels": PexelsAdapter(api_key=pexels_api_key)
        }

    def resolve_source_hierarchy(self, intent: VisualIntent) -> List[str]:
        """
        Determines the priority order of adapters based on visual intent.
        Niche-agnostic: relies entirely on structured intent fields (entity, event, claim, tone).
        """
        v_intent = getattr(intent, "visual_intent", "")
        req_type = getattr(intent, "required_visual_type", getattr(intent, "preferred_visual_type", None))
        ev_req = getattr(intent, "evidence_required", False)
        date_ctx = getattr(intent, "date_context", None)
        p_entity = getattr(intent, "primary_entity", None)
        evt = getattr(intent, "event", None)

        # If reaction visual is explicitly desired and editorially sound
        if v_intent == "REACTION" or req_type == VisualContentType.MEME_REACTION:
            return ["reaction", "contextual", "editorial", "pexels"]

        # If evidence/document is required (e.g. treaty, headline, court filing, stat)
        if ev_req or req_type == VisualContentType.SCREENSHOT_DOCUMENT:
            return ["contextual", "official", "wikimedia", "editorial", "pexels"]

        # If archival / historical date context is specified
        if date_ctx and any(c.isdigit() for c in str(date_ctx)):
            return ["archive", "wikimedia", "official", "editorial", "pexels"]

        # Default real-world entity/event order
        if p_entity or evt:
            return ["editorial", "official", "wikimedia", "archive", "contextual", "pexels"]

        # Fallback general hierarchy
        return ["editorial", "wikimedia", "official", "archive", "contextual", "pexels"]

    def acquire_candidates(
        self,
        intent: VisualIntent,
        count_per_tier: int = 4,
        max_total_candidates: int = 15,
        exclude_urls: Optional[Set[str]] = None,
        count_per_beat: Optional[int] = None
    ) -> List[VisualCandidate]:
        if count_per_beat is not None:
            count_per_tier = count_per_beat
        """
        Dispatches multi-source queries following the Real-Footage-First hierarchy.
        Returns aggregated candidates enriched with provenance and rights classification.
        """
        hierarchy = self.resolve_source_hierarchy(intent)
        candidates: List[VisualCandidate] = []
        seen_urls: Set[str] = set(exclude_urls or [])

        queries = list(intent.search_queries)
        if not queries:
            base_q = intent.primary_entity or intent.event or intent.action or "documentary scene"
            queries = [base_q]

        for source_key in hierarchy:
            adapter = self.adapters.get(source_key)
            if not adapter:
                continue

            try:
                tier_candidates = adapter.search(
                    queries=queries,
                    intent=intent,
                    count=count_per_tier,
                    exclude_urls=seen_urls
                )

                # Filter out any unverified rights risk or misleading reactions
                for cand in tier_candidates:
                    if cand.source_url in seen_urls:
                        continue

                    # Contextual reaction safety filter
                    if cand.content_type == VisualContentType.MEME_REACTION:
                        if not self._is_reaction_editorially_permitted(cand, intent):
                            logger.info(f"[SOURCE_ROUTER] Filtered out uncontextual reaction: '{cand.title}'")
                            continue

                    seen_urls.add(cand.source_url)
                    candidates.append(cand)

                if len(candidates) >= max_total_candidates:
                    break

            except Exception as e:
                logger.warning(f"[SOURCE_ROUTER] Adapter '{source_key}' encountered notice: {e}")

        # Ensure we always have at least some candidates via fallback
        if not candidates and "pexels" not in [c.source_name for c in candidates]:
            try:
                fb = self.adapters["pexels"].search(queries=queries, intent=intent, count=count_per_tier, exclude_urls=seen_urls)
                candidates.extend(fb)
            except Exception as e:
                logger.warning(f"[SOURCE_ROUTER] Pexels fallback notice: {e}")

        return candidates[:max_total_candidates]

    def _is_reaction_editorially_permitted(self, candidate: VisualCandidate, intent: VisualIntent) -> bool:
        """
        Strict safety gate for reaction/meme visuals:
          - Must match emotional tone
          - Prohibits fabricated quotes or manipulated footage
          - Requires serious commentary tone to reject frivolous memes
        """
        # Reject if tone is serious / somber / tragic and meme is frivolous
        if intent.emotional_tone in ("SERIOUS", "TRAGIC", "CRITICAL") and intent.visual_intent != "REACTION":
            return False

        # Reject if misleading or unverified rights
        if candidate.rights_status == RightsStatus.RIGHTS_UNCERTAIN:
            return False

        return True
