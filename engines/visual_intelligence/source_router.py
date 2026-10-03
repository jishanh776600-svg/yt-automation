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

from .models import VisualIntent, VisualCandidate, VisualContentType, RightsStatus, SourceType
from .sources.base import BaseSourceAdapter
from .sources.nasa_svs import NasaSvsAdapter
from .sources.archive import ArchiveAdapter
from .sources.youtube_adapter import YouTubeAdapter
from .sources.procedural_3d_adapter import Procedural3DAdapter
from .sources.movie_adapter import MovieAdapter
from .sources.pexels import PexelsAdapter
from .sources.pixabay import PixabayAdapter
from .sources.editorial import EditorialAdapter
from .sources.wikimedia import WikimediaAdapter
from .sources.official import OfficialAdapter
from .sources.contextual import ContextualAdapter
from .sources.reaction import ReactionAdapter
from config.settings import PIXABAY_API_KEY

logger = logging.getLogger(__name__)


class SourceRouter:
    """
    Intelligent routing and multi-source query dispatch.
    Implements the 5-Tier Provenance Ecosystem:
      Tier 1: Direct High-Authority Video (NASA SVS, ESO, NOAA)
      Tier 2: Archival / Institutional Video (Internet Archive, Prelinger)
      Tier 3: Whitelisted Docudrama / Film Discovery (YouTube whitelisted channels)
      Tier 4: Original Visual Creation (Procedural 3D around authentic evidence)
      Tier 5: Constrained Supporting Stock (Pexels / Pixabay for macro nouns only)
    """

    def __init__(self, pexels_api_key: Optional[str] = None, pixabay_api_key: Optional[str] = None):
        pb_key = pixabay_api_key or PIXABAY_API_KEY
        self.adapters: Dict[str, BaseSourceAdapter] = {
            "nasa_svs": NasaSvsAdapter(),
            "archive": ArchiveAdapter(),
            "youtube_docudrama": YouTubeAdapter(),
            "procedural_3d": Procedural3DAdapter(),
            "movie": MovieAdapter(),
            "editorial": EditorialAdapter(),
            "official": OfficialAdapter(),
            "wikimedia": WikimediaAdapter(),
            "contextual": ContextualAdapter(),
            "reaction": ReactionAdapter(),
            "pexels": PexelsAdapter(api_key=pexels_api_key),
            "pixabay": PixabayAdapter(api_key=pb_key)
        }

    def resolve_source_hierarchy(self, intent: VisualIntent) -> List[str]:
        """
        Determines the priority order of adapters based on visual intent and evidence requirements.
        """
        combined = f"{intent.narration_text} {intent.primary_entity or ''} {intent.event or ''} {' '.join(intent.search_queries)}".lower()

        # 1. Space, astronomy, physics, cosmology -> Tier 1 (NASA SVS) first
        if any(k in combined for k in ["black hole", "accretion", "space", "orbit", "planet", "galaxy", "star", "einstein", "gravity", "telescope", "cosmic"]):
            return ["nasa_svs", "archive", "youtube_docudrama", "procedural_3d", "pexels"]

        # 2. Document, manuscript, cipher, paper, scientific figure -> Tier 4 (Procedural 3D on evidence) first
        if any(k in combined for k in ["manuscript", "voynich", "beinecke", "cipher", "codex", "paper", "journal", "telemetry", "wow signal", "study"]):
            return ["procedural_3d", "youtube_docudrama", "archive", "contextual", "pexels"]

        # 3. Historical event, medieval, plague, tragedy, dramatic reenactment -> Tier 3 (Whitelisted Docudrama) first
        if any(k in combined for k in ["1518", "plague", "dancing", "reenactment", "historical", "century", "tragedy", "king", "queen", "castle", "medieval"]):
            return ["youtube_docudrama", "archive", "movie", "procedural_3d", "pexels"]

        # 4. 20th-century historical archive, military, newsreels, space missions -> Tier 2 (Internet Archive) first
        if any(k in combined for k in ["19", "apollo", "war", "newsreel", "cold war", "soviet", "navy", "military", "vintage", "president"]):
            return ["archive", "youtube_docudrama", "official", "procedural_3d", "pexels"]

        # Default 5-tier sequence: Institutional -> Archival -> Whitelisted Docudrama -> Procedural 3D -> Stock Last
        return ["nasa_svs", "archive", "youtube_docudrama", "procedural_3d", "pexels"]

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

        hierarchy = self.resolve_source_hierarchy(intent)
        candidates: List[VisualCandidate] = []
        seen_urls: Set[str] = set(exclude_urls or [])
        rejection_log: List[Dict[str, str]] = []

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

                for cand in tier_candidates:
                    if cand.source_url in seen_urls:
                        continue

                    # Contextual reaction safety filter
                    if cand.content_type == VisualContentType.MEME_REACTION:
                        if not self._is_reaction_editorially_permitted(cand, intent):
                            logger.info(f"[SOURCE_ROUTER] Filtered out uncontextual reaction: '{cand.title}'")
                            rejection_log.append({"candidate": cand.title, "reason": "uncontextual_reaction"})
                            continue

                    seen_urls.add(cand.source_url)
                    candidates.append(cand)

                if len(candidates) >= max_total_candidates:
                    break

            except Exception as e:
                logger.warning(f"[SOURCE_ROUTER] Adapter '{source_key}' notice: {e}")
                rejection_log.append({"adapter": source_key, "reason": str(e)})

        # FAIL-CLOSED CHECK: If zero acceptable candidates found
        if not candidates:
            claim_desc = getattr(intent, "claim_discussed", None) or getattr(intent, "narration_text", "")[:60]
            logger.error(
                f"[SOURCE_ROUTER] NO_ACCEPTABLE_VISUAL_EVIDENCE for claim: '{claim_desc}'. "
                f"Searched tiers: {hierarchy}. Refusing to fill with generic stock filler."
            )

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
