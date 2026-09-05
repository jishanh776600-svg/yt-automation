"""
Class A Source Adapter: Pexels API.
Licensed stock footage and photography with verified commercial zero-cost license.
Supports 1080p vertical and 1080p landscape video, rejects < 720p.
"""
import os
import uuid
import logging
import requests
from typing import List, Dict, Any, Optional, Set

from .base import BaseSourceAdapter, VisualCandidate
from ..provenance import VisualProvenance, RightsStatus, VisualContentType
from config.settings import PEXELS_API_KEY

logger = logging.getLogger(__name__)


class PexelsAdapter(BaseSourceAdapter):
    """Class A: Licensed Stock Video and Photography Adapter."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__(source_name="pexels", source_class="SOURCE_A")
        self.api_key = api_key or PEXELS_API_KEY

    def search(
        self,
        queries: List[str],
        intent: Any,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """Queries Pexels API for video and photo candidates."""
        candidates: List[VisualCandidate] = []
        exclude = exclude_urls or set()

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
                                confidence_score=1.0
                            )

                            cand = VisualCandidate(
                                candidate_id=cid,
                                source_class=self.source_class,
                                source_name=self.source_name,
                                source_url=link,
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
                                provenance=prov
                            )
                            candidates.append(cand)
            except Exception as e:
                logger.debug(f"Pexels search exception for '{query}': {e}")

        return candidates
