"""
Tier 1 Source Adapter: NASA Scientific Visualization Studio (SVS).
Retrieves authentic supercomputer simulations, astronomical visualizations,
and planetary physics animations directly from the official NASA SVS REST API.
License: Public Domain (17 U.S.C. § 105 / NASA Open Data Policy).
"""
import os
import re
import uuid
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional, Set

from .base import BaseSourceAdapter, VisualCandidate
from ..models import (
    VisualIntent, VisualProvenance, RightsStatus, VisualContentType,
    SourceType, SourceTier, SourceContentClass
)

logger = logging.getLogger(__name__)


class NasaSvsAdapter(BaseSourceAdapter):
    """
    Tier 1 Direct High-Authority Video Adapter for NASA SVS.
    Direct REST API acquisition for space, astrophysics, Earth science, and planetary phenomena.
    """

    def __init__(self, timeout_sec: int = 8):
        super().__init__(source_name="nasa_svs", source_class="SOURCE_TIER_1_INSTITUTIONAL")
        self.source_type = SourceType.INTERNET_REAL
        self.source_tier = SourceTier.TIER_1_DIRECT_INSTITUTIONAL
        self.timeout_sec = timeout_sec
        self.headers = {"User-Agent": "AL_AMR_Visual_Intelligence/2.0 (Open Science Educational Access)"}

    def search(
        self,
        queries: List[str],
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[VisualCandidate]:
        """
        Queries NASA SVS Search API, resolves direct master MP4s from asset detail endpoints.
        """
        from ..cache import get_circuit_breaker, get_canonical_cache
        circuit_breaker = get_circuit_breaker()
        if not circuit_breaker.is_available(self.source_name):
            logger.info(f"[{self.source_name}] Circuit breaker is OPEN. Skipping NASA SVS search.")
            return []

        asset_cache = get_canonical_cache()
        candidates: List[VisualCandidate] = []
        exclude = set(exclude_urls or [])

        # Check if intent is suitable for NASA SVS
        if intent:
            combined_text = f"{intent.narration_text} {intent.primary_entity or ''} {intent.event or ''} {' '.join(intent.search_queries)}".lower()
            space_keywords = [
                "black hole", "accretion", "space", "orbit", "planet", "solar", "sun", "galaxy",
                "star", "supernova", "gravity", "gravitational", "einstein", "relativity",
                "telescope", "webb", "hubble", "mars", "moon", "earth", "climate", "atmosphere",
                "magnetosphere", "satellite", "nebula", "neutron", "cosmic", "universe", "physics"
            ]
            if not any(k in combined_text for k in space_keywords):
                return []

        search_terms = []
        for q in queries:
            clean_q = re.sub(r"[^\w\s]", " ", q).strip()
            clean_words = [w for w in clean_q.split() if w.lower() not in ("footage", "video", "scene", "the", "a", "an", "of", "and")]
            if clean_words:
                search_terms.append("+".join(clean_words[:4]))

        if not search_terms:
            search_terms = ["black+hole"]

        seen_asset_ids = set()

        def _fetch_asset_detail(asset_id: str, is_curated: bool = False, query_term: str = "") -> Optional[VisualCandidate]:
            try:
                detail_url = f"https://svs.gsfc.nasa.gov/api/{asset_id}/"
                d_resp = requests.get(detail_url, headers=self.headers, timeout=min(5.0, self.timeout_sec))
                if d_resp.status_code != 200:
                    return None
                d_data = d_resp.json()
                media_groups = d_data.get("media_groups", [])
                mp4_candidates = []
                for mg in (media_groups or []):
                    if not isinstance(mg, dict):
                        continue
                    for it in (mg.get("items") or []):
                        if not isinstance(it, dict):
                            continue
                        inst = it.get("instance") or {}
                        if not isinstance(inst, dict):
                            continue
                        url = inst.get("url") or ""
                        if url and url.lower().endswith(".mp4"):
                            fn = inst.get("filename", "")
                            if any(k in fn.lower() for k in ["dump", "prores", "uncompressed"]):
                                continue
                            w = inst.get("width") or 0
                            h = inst.get("height") or 0
                            mp4_candidates.append((url, w, h, fn))

                if not mp4_candidates:
                    return None

                def _rank_mp4(c):
                    url, w, h, fn = c
                    if "-hd" in fn.lower() or "1080" in fn or w == 1920 or h == 1080:
                        return 4
                    if "720" in fn or w >= 1280:
                        return 3
                    if "-4k" in fn.lower() or "4k" in fn.lower():
                        return 2
                    return 1

                mp4_candidates.sort(key=_rank_mp4, reverse=True)
                available_mp4s = [c for c in mp4_candidates if c[0] not in exclude and not asset_cache.is_disqualified(c[0])]
                if not available_mp4s:
                    return None

                best_url, best_w, best_h, best_fn = available_mp4s[0]
                title = d_data.get("title") or f"NASA SVS Visualization {asset_id}"
                if any(k in title.lower() for k in ["behind the scenes", "concert", "interview", "press briefing", "talk:", "making of"]):
                    return None

                desc = d_data.get("description") or ""
                release_date = d_data.get("release_date", "Official NASA Record")
                cid = f"cand_svs_{asset_id}_{abs(hash(best_url)) % 10000}"
                page_url = d_data.get("url") or f"https://svs.gsfc.nasa.gov/{asset_id}/"

                prov = VisualProvenance(
                    asset_id=cid,
                    source="nasa_svs",
                    source_url=page_url,
                    media_url=best_url,
                    title=title,
                    creator="NASA Goddard Space Flight Center / Scientific Visualization Studio",
                    publisher="NASA",
                    publication_date=str(release_date),
                    license_name="Public Domain (NASA Open Data Policy / 17 U.S.C. § 105)",
                    rights_status=RightsStatus.PUBLIC_DOMAIN,
                    content_type=VisualContentType.OFFICIAL_PUBLIC_RECORD,
                    attribution_required=True,
                    attribution_text=f"NASA SVS: {title} (Asset #{asset_id})",
                    confidence_score=0.99,
                    entity_matches=[intent.primary_entity] if (intent and intent.primary_entity) else [],
                    event_matches=[intent.event] if (intent and intent.event) else [],
                    source_tier=SourceTier.TIER_1_DIRECT_INSTITUTIONAL,
                    source_content_class=SourceContentClass.INSTITUTIONAL_VISUALIZATION,
                    evidence_requirement=getattr(intent, "claim_discussed", None),
                    original_owner="NASA"
                )

                return VisualCandidate(
                    candidate_id=cid,
                    source_class=self.source_class,
                    source_name="nasa_svs",
                    source_url=page_url,
                    media_url=best_url,
                    title=title,
                    description=desc[:200],
                    content_type=VisualContentType.OFFICIAL_PUBLIC_RECORD,
                    rights_status=RightsStatus.PUBLIC_DOMAIN,
                    license_name="Public Domain (NASA SVS)",
                    creator="NASA SVS",
                    publisher="NASA",
                    width=best_w or 1920,
                    height=best_h or 1080,
                    duration_sec=getattr(intent, "duration", 4.0) if intent else 4.0,
                    fps=60,
                    motion_score=0.92,
                    is_video=True,
                    provenance=prov,
                    source_type=SourceType.INTERNET_REAL,
                    source_tier=SourceTier.TIER_1_DIRECT_INSTITUTIONAL,
                    source_content_class=SourceContentClass.INSTITUTIONAL_VISUALIZATION,
                    evidence_requirement=getattr(intent, "claim_discussed", None),
                    metadata={
                        "nasa_asset_id": asset_id,
                        "filename": best_fn,
                        "curated": is_curated,
                        "query_used": query_term
                    }
                )
            except Exception as e:
                logger.debug(f"[NASA_SVS] Detail lookup notice for asset #{asset_id}: {e}")
                return None

        # 1. Curated astrophysics assets in parallel if relevant
        query_text = " ".join(queries).lower()
        curated_ids_to_check = []
        if any(k in query_text for k in ["black hole", "accretion", "lensing", "relativity", "event horizon", "photon sphere"]):
            curated_ids_to_check = ["13326", "14620", "13831", "14619"]

        if curated_ids_to_check:
            with ThreadPoolExecutor(max_workers=min(4, len(curated_ids_to_check))) as executor:
                futures = {executor.submit(_fetch_asset_detail, cid, True, "curated"): cid for cid in curated_ids_to_check}
                for fut in as_completed(futures):
                    cid = futures[fut]
                    cand = fut.result()
                    if cand:
                        seen_asset_ids.add(cid)
                        candidates.append(cand)
                        exclude.add(cand.media_url)
                        if len(candidates) >= count:
                            break

        # 2. Search API terms if more needed
        if len(candidates) < count:
            for term in search_terms[:2]:
                if len(candidates) >= count:
                    break
                try:
                    search_url = f"https://svs.gsfc.nasa.gov/api/search/?search={term}&limit=4"
                    resp = requests.get(search_url, headers=self.headers, timeout=min(5.0, self.timeout_sec))
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    results = data.get("results", [])
                    new_asset_ids = []
                    for item in results:
                        aid = str(item.get("id"))
                        if aid and aid not in seen_asset_ids:
                            seen_asset_ids.add(aid)
                            new_asset_ids.append(aid)

                    if new_asset_ids:
                        with ThreadPoolExecutor(max_workers=min(4, len(new_asset_ids))) as executor:
                            futures = {executor.submit(_fetch_asset_detail, aid, False, term): aid for aid in new_asset_ids}
                            for fut in as_completed(futures):
                                cand = fut.result()
                                if cand:
                                    candidates.append(cand)
                                    exclude.add(cand.media_url)
                                    if len(candidates) >= count:
                                        break
                except Exception as e:
                    logger.warning(f"[NASA_SVS] Error querying term '{term}': {e}")

        if candidates:
            circuit_breaker.record_success(self.source_name)
        logger.info(f"[NASA_SVS] Discovered {len(candidates)} high-authority NASA SVS master videos.")
        return candidates
