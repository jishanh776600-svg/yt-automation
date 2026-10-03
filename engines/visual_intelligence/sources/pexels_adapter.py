"""
Class A Source Adapter: Pexels API.
Licensed stock footage and photography with verified commercial zero-cost license.
Supports 1080p vertical and 1080p landscape video, rejects < 720p.
"""
import os
import re
import uuid
import logging
import requests
from typing import List, Dict, Any, Optional, Set

from .base import BaseSourceAdapter, VisualCandidate
from ..models import (
    VisualProvenance, RightsStatus, VisualContentType,
    SourceType, SourceTier, SourceContentClass
)
from config.settings import PEXELS_API_KEY

logger = logging.getLogger(__name__)


LITERAL_MACRO_NOUNS = {
    "clock", "clocks", "hourglass", "microscope", "centrifuge", "flask",
    "scale", "compass", "lens", "gear", "gears", "pendulum", "crystal",
    "pipette", "beaker", "telescope lens", "laboratory glassware"
}


class PexelsAdapter(BaseSourceAdapter):
    """Tier 5: Constrained Supporting Stock Adapter (Last Resort for Macro Nouns Only)."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(source_name="pexels", source_class="SOURCE_TIER_5_STOCK")
        self.source_tier = SourceTier.TIER_5_SUPPORTING_STOCK
        self.source_type = SourceType.STOCK
        self.api_key = api_key or PEXELS_API_KEY

    def search(
        self,
        queries: List[str],
        intent: Optional[Any] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """
        Queries Pexels API for video candidates.
        STRICT TIER 5 RULE: Strictly restricted to literal physical macro nouns.
        Forbidden as primary narrative evidence for historical/scientific storytelling.
        """
        candidates: List[VisualCandidate] = []
        exclude = exclude_urls or set()

        # Step 8G Hard Rule: Stock is ONLY permitted for literal physical macro nouns
        query_text = " ".join(queries).lower()
        intent_parts = []
        if intent:
            for attr in ("narration_text", "action", "target_object", "primary_entity"):
                val = getattr(intent, attr, None)
                if val:
                    intent_parts.append(str(val))
        intent_text = " ".join(intent_parts).lower()
        combined_check = query_text + " " + intent_text

        has_macro_noun = any(re.search(r"\b" + re.escape(noun) + r"\b", combined_check) for noun in LITERAL_MACRO_NOUNS)
        if not has_macro_noun:
            logger.info("[PEXELS_ADAPTER] Tier 5 constraint: query does not specify a literal physical macro noun. Rejecting stock filler.")
            return []

        api_key = self.api_key or PEXELS_API_KEY
        if not api_key:
            return candidates

        headers = {"Authorization": api_key}
        url = "https://api.pexels.com/videos/search"

        for query in queries[:2]:
            try:
                resp = requests.get(url, headers=headers, params={"query": query, "per_page": count}, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    for v in data.get("videos", []):
                        v_files = v.get("video_files", [])
                        best_file = None
                        best_res = 0
                        for vf in v_files:
                            w = vf.get("width") or 0
                            h = vf.get("height") or 0
                            if min(w, h) >= 720 and (w * h) > best_res:
                                best_res = w * h
                                best_file = vf

                        if best_file:
                            link = best_file.get("link")
                            if not link or link in exclude:
                                continue

                            w = best_file.get("width", 1080)
                            h = best_file.get("height", 1920)
                            cid = f"cand_px_{v.get('id')}_{uuid.uuid4().hex[:4]}"
                            
                            prov = VisualProvenance(
                                asset_id=cid,
                                source="pexels",
                                source_url=link,
                                creator=v.get("user", {}).get("name", "Pexels Contributor"),
                                publisher="Pexels",
                                rights_status=RightsStatus.LICENSED,
                                license_name="Pexels Commercial License",
                                content_type=VisualContentType.GENERIC_STOCK_VIDEO,
                                attribution_required=False,
                                confidence_score=1.0,
                                source_tier=SourceTier.TIER_5_SUPPORTING_STOCK,
                                source_content_class=SourceContentClass.STOCK_CONTEXT,
                                original_owner="Pexels Stock"
                            )

                            cand = VisualCandidate(
                                candidate_id=cid,
                                source_class=self.source_class,
                                source_name=self.source_name,
                                source_url=link,
                                media_url=link,
                                title=f"Pexels Stock: {query}",
                                description=f"Stock video relating to {query}",
                                content_type=VisualContentType.GENERIC_STOCK_VIDEO,
                                rights_status=RightsStatus.LICENSED,
                                license_name="Pexels License",
                                creator=v.get("user", {}).get("name"),
                                publisher="Pexels",
                                width=w,
                                height=h,
                                duration_sec=float(v.get("duration") or 4.0),
                                motion_score=0.75 if (w >= 1080 and h >= 1080) else 0.60,
                                is_video=True,
                                entity_tags=[query],
                                event_tags=[],
                                provenance=prov,
                                source_type=SourceType.STOCK,
                                source_tier=SourceTier.TIER_5_SUPPORTING_STOCK,
                                source_content_class=SourceContentClass.STOCK_CONTEXT
                            )
                            candidates.append(cand)
            except Exception as e:
                logger.debug(f"Pexels search exception for '{query}': {e}")

        return candidates
