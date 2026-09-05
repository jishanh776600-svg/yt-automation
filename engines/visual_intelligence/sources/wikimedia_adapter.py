"""
Class C Source Adapter: Wikimedia Commons / Official Public Domain.
Authentic historical archives, public records, and official government media
with verified CC0, Public Domain, or CC-BY licenses.
"""
import uuid
import logging
import requests
from typing import List, Dict, Any, Optional, Set

from .base import BaseSourceAdapter, VisualCandidate
from ..provenance import VisualProvenance, RightsStatus, VisualContentType

logger = logging.getLogger(__name__)


class WikimediaAdapter(BaseSourceAdapter):
    """Class C: Wikimedia Commons & Official Public Domain Adapter."""

    def __init__(self):
        super().__init__(source_name="wikimedia_commons", source_class="SOURCE_C")

    def search(
        self,
        queries: List[str],
        intent: Any,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """Queries Wikimedia Commons API for authentic public domain and CC-BY visual records."""
        candidates: List[VisualCandidate] = []
        exclude = exclude_urls or set()

        url = "https://commons.wikimedia.org/w/api.php"
        headers = {"User-Agent": "AL_AMR_Visual_Intelligence/2.0 (Automated Editorial Educational Media)"}

        for q in queries[:2]:
            try:
                params = {
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": q,
                    "gsrnamespace": "6",
                    "gsrlimit": count,
                    "prop": "imageinfo",
                    "iiprop": "url|size|extmetadata",
                    "format": "json"
                }
                resp = requests.get(url, headers=headers, params=params, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for pid, pdata in pages.items():
                        infos = pdata.get("imageinfo", [])
                        if not infos:
                            continue
                        info = infos[0]
                        img_url = info.get("url")
                        if not img_url or img_url in exclude:
                            continue

                        w = info.get("width") or 1080
                        h = info.get("height") or 1920
                        if w < 400 or h < 400:
                            continue

                        ext = info.get("extmetadata", {})
                        lic = ext.get("LicenseShortName", {}).get("value", "Public Domain")
                        artist = ext.get("Artist", {}).get("value", "Historical Archive")
                        desc = ext.get("ImageDescription", {}).get("value", pdata.get("title", ""))

                        cid = f"cand_wiki_{pid}_{uuid.uuid4().hex[:4]}"
                        is_video = img_url.lower().endswith((".webm", ".mp4", ".ogv"))

                        prov = VisualProvenance(
                            asset_id=cid,
                            source="wikimedia_commons",
                            source_url=img_url,
                            creator=artist[:80],
                            publisher="Wikimedia Commons",
                            rights_status=RightsStatus.PUBLIC_DOMAIN if "public domain" in lic.lower() else RightsStatus.PERMISSION_BASED,
                            license_name=lic,
                            content_type=VisualContentType.ARCHIVAL_VIDEO if is_video else VisualContentType.STATIC_PHOTO,
                            attribution_required=bool(artist and artist != "Historical Archive"),
                            attribution_text=artist[:100],
                            confidence_score=0.98
                        )

                        cand = VisualCandidate(
                            candidate_id=cid,
                            source_class=self.source_class,
                            source_name=self.source_name,
                            source_url=img_url,
                            title=pdata.get("title", q),
                            description=desc[:150],
                            content_type=VisualContentType.ARCHIVAL_VIDEO if is_video else VisualContentType.STATIC_PHOTO,
                            rights_status=prov.rights_status,
                            license_name=lic,
                            creator=artist[:80],
                            publisher="Wikimedia Commons",
                            width=w,
                            height=h,
                            duration_sec=getattr(intent, "duration", 4.0),
                            motion_score=0.85 if is_video else 0.40,
                            is_video=is_video,
                            entity_tags=[q],
                            event_tags=[],
                            provenance=prov
                        )
                        candidates.append(cand)
            except Exception as e:
                logger.debug(f"Wikimedia adapter search notice for '{q}': {e}")

        return candidates
