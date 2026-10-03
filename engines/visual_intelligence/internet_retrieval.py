"""
Internet + Movie Video Retrieval Foundation (Step 1/8).
======================================================
Implements the multi-provider internet video retrieval foundation:
  1. Non-Stock Internet / Movie / Archival Video — PRIMARY
     - MOVIE: Cinematic film scenes, movie recreations, dramatic clips
     - INTERNET_REAL: Real event footage, news, press briefings, official public records
     - ARCHIVAL: Historical recordings, documentary archives, newsreels
  2. Stock Video — LAST RESORT FALLBACK
     - STOCK: Pexels Video, Pixabay Video (Video streams only, strictly fallback)

Hard Invariants:
  - VIDEO ONLY: No still images, photographs, AI stills, Ken Burns, or canvases.
  - Fail-Closed: Controlled failure when no authentic video passes physical validation.
  - Deterministic Priority: MOVIE / INTERNET_REAL / ARCHIVAL > STOCK.
"""
import os
import re
import time
import uuid
import logging
import requests
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Union, Tuple

from config.settings import ASSETS_CACHE_DIR, PEXELS_API_KEY, PIXABAY_API_KEY
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, LicenseType
from core.media_validator import PhysicalVideoValidator, VideoValidationResult, VIDEO_ONLY
from .models import (
    SourceType, NormalizedVideoCandidate, VisualCandidate, VisualIntent,
    VisualContentType, RightsStatus, VisualProvenance, SourceTier
)
from .sources.movie_adapter import MovieAdapter
from .sources.archive import ArchiveAdapter
from .sources.official import OfficialAdapter
from .sources.editorial_adapter import EditorialAdapter
from .sources.wikimedia_adapter import WikimediaAdapter
from .sources.youtube_adapter import YouTubeAdapter
from .sources.nasa_svs import NasaSvsAdapter
from .sources.procedural_3d_adapter import Procedural3DAdapter
from .sources.pexels_adapter import PexelsAdapter
from .sources.pixabay_adapter import PixabayAdapter
from .resolver import WebVideoResolver
from .adaptive_retrieval import (
    RetrievalBudget,
    AdaptiveQueryExpander,
    StagedStreamIngester,
    ParallelVideoRetriever,
    RetrievalTelemetryRecord,
    RetrievalTelemetryCollector,
)

logger = logging.getLogger(__name__)

# Max video download size: 100 MB
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
DEFAULT_DOWNLOAD_TIMEOUT = 25
MAX_DOWNLOAD_RETRIES = 2


def get_source_priority(source_type: Union[SourceType, str]) -> int:
    """
    Deterministic Source Priority:
      Priority 1: MOVIE, INTERNET_REAL, ARCHIVAL (Non-Stock Primary)
      Priority 2: STOCK (Safety net fallback only)
      Priority 99: Unknown / Prohibited
    """
    try:
        st = SourceType(source_type) if isinstance(source_type, str) else source_type
    except (ValueError, KeyError):
        return 99

    if st in (SourceType.MOVIE, SourceType.INTERNET_REAL, SourceType.ARCHIVAL, SourceType.YOUTUBE):
        return 1
    elif st == SourceType.STOCK:
        return 2
    return 99


# ==============================================================================
# Abstract Provider Interface
# ==============================================================================
class BaseVideoRetrievalProvider(ABC):
    """Abstract interface for video retrieval providers."""

    def __init__(self, name: str, source_type: SourceType):
        self.name = name
        self.source_type = source_type

    @property
    def priority(self) -> int:
        return get_source_priority(self.source_type)

    @abstractmethod
    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        """Discovers video candidates matching the query/intent."""
        pass


# ==============================================================================
# Concrete Providers
# ==============================================================================
class MovieRetrievalProvider(BaseVideoRetrievalProvider):
    """Retrieves film, cinematic, and movie scene footage (Priority 1)."""

    def __init__(self, adapter: Optional[MovieAdapter] = None):
        super().__init__(name="movie_footage", source_type=SourceType.MOVIE)
        self.adapter = adapter or MovieAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        try:
            queries = [query]
            if intent and intent.search_queries:
                queries = intent.search_queries
            v_cands = self.adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
            return [c.to_normalized_candidate(query_used=query) for c in v_cands]
        except Exception as e:
            logger.warning(f"[{self.name}] Search exception for '{query}': {e}")
            return []


class InternetRealRetrievalProvider(BaseVideoRetrievalProvider):
    """Retrieves real-world event, news, and official public records (Priority 1)."""

    def __init__(
        self,
        editorial_adapter: Optional[EditorialAdapter] = None,
        official_adapter: Optional[OfficialAdapter] = None
    ):
        super().__init__(name="internet_real", source_type=SourceType.INTERNET_REAL)
        self.editorial_adapter = editorial_adapter or EditorialAdapter()
        self.official_adapter = official_adapter or OfficialAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        results: List[NormalizedVideoCandidate] = []
        queries = [query]
        if intent and intent.search_queries:
            for sq in intent.search_queries:
                if sq and sq.lower() != query.lower() and sq not in queries:
                    queries.append(sq)

        for adapter in (self.editorial_adapter, self.official_adapter):
            try:
                cands = adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
                for c in cands:
                    c.source_type = SourceType.INTERNET_REAL
                    norm = c.to_normalized_candidate(query_used=query)
                    norm.source_type = SourceType.INTERNET_REAL
                    results.append(norm)
            except Exception as e:
                logger.warning(f"[{self.name}] Adapter {adapter.source_name} search notice: {e}")

        return results[:count]


class ArchivalRetrievalProvider(BaseVideoRetrievalProvider):
    """Retrieves archival, documentary, and historical recordings (Priority 1)."""

    def __init__(
        self,
        archive_adapter: Optional[ArchiveAdapter] = None,
        wikimedia_adapter: Optional[WikimediaAdapter] = None
    ):
        super().__init__(name="archival_video", source_type=SourceType.ARCHIVAL)
        self.archive_adapter = archive_adapter or ArchiveAdapter()
        self.wikimedia_adapter = wikimedia_adapter or WikimediaAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        results: List[NormalizedVideoCandidate] = []
        queries = [query]
        if intent and intent.search_queries:
            for sq in intent.search_queries:
                if sq and sq.lower() != query.lower() and sq not in queries:
                    queries.append(sq)

        for adapter in (self.archive_adapter, self.wikimedia_adapter):
            try:
                cands = adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
                for c in cands:
                    c.source_type = SourceType.ARCHIVAL
                    norm = c.to_normalized_candidate(query_used=query)
                    norm.source_type = SourceType.ARCHIVAL
                    results.append(norm)
            except Exception as e:
                logger.warning(f"[{self.name}] Adapter {adapter.source_name} search notice: {e}")

        return results[:count]


class YouTubeRetrievalProvider(BaseVideoRetrievalProvider):
    """Retrieves authentic event/entity documentary, news, and archival footage via YouTube (Priority 1)."""

    def __init__(self, adapter: Optional[YouTubeAdapter] = None):
        super().__init__(name="youtube_video", source_type=SourceType.YOUTUBE)
        self.adapter = adapter or YouTubeAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        try:
            queries = [query]
            if intent and intent.search_queries:
                for sq in intent.search_queries:
                    if sq and sq.lower() != query.lower() and sq not in queries:
                        queries.append(sq)
            v_cands = self.adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
            norm_cands = []
            for c in v_cands:
                c.source_type = SourceType.YOUTUBE
                norm = c.to_normalized_candidate(query_used=query)
                norm.source_type = SourceType.YOUTUBE
                norm_cands.append(norm)
            return norm_cands
        except Exception as e:
            logger.warning(f"[{self.name}] Search exception for '{query}': {e}")
            return []


class NasaSvsRetrievalProvider(BaseVideoRetrievalProvider):
    """Tier 1: Retrieves authentic NASA SVS scientific visualizations and astrophysical animations (Priority 1)."""

    def __init__(self, adapter: Optional[NasaSvsAdapter] = None):
        super().__init__(name="nasa_svs", source_type=SourceType.INTERNET_REAL)
        self.adapter = adapter or NasaSvsAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        try:
            queries = [query]
            if intent and intent.search_queries:
                for sq in intent.search_queries:
                    if sq and sq.lower() != query.lower() and sq not in queries:
                        queries.append(sq)
            v_cands = self.adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
            return [c.to_normalized_candidate(query_used=query) for c in v_cands]
        except Exception as e:
            logger.warning(f"[{self.name}] Search notice for '{query}': {e}")
            return []


class Procedural3DRetrievalProvider(BaseVideoRetrievalProvider):
    """Tier 4: Generates authentic procedural 3D motion around primary source document/manuscript evidence (Priority 1)."""

    def __init__(self, adapter: Optional[Procedural3DAdapter] = None):
        super().__init__(name="procedural_3d", source_type=SourceType.INTERNET_REAL)
        self.adapter = adapter or Procedural3DAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        try:
            queries = [query]
            if intent and intent.search_queries:
                for sq in intent.search_queries:
                    if sq and sq.lower() != query.lower() and sq not in queries:
                        queries.append(sq)
            v_cands = self.adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
            return [c.to_normalized_candidate(query_used=query) for c in v_cands]
        except Exception as e:
            logger.warning(f"[{self.name}] Search notice for '{query}': {e}")
            return []


class StockVideoFallbackProvider(BaseVideoRetrievalProvider):
    """
    Last-Resort Stock Video Fallback Provider (Priority 2).
    Consulted ONLY after all non-stock retrieval sources fail.
    VIDEO ONLY — No stock photos or static images.
    """

    def __init__(
        self,
        pexels_adapter: Optional[PexelsAdapter] = None,
        pixabay_adapter: Optional[PixabayAdapter] = None
    ):
        super().__init__(name="stock_video_fallback", source_type=SourceType.STOCK)
        self.pexels_adapter = pexels_adapter or PexelsAdapter()
        self.pixabay_adapter = pixabay_adapter or PixabayAdapter()

    def search(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 5,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        results: List[NormalizedVideoCandidate] = []
        queries = [query]
        if intent and intent.search_queries:
            queries = intent.search_queries

        for adapter in (self.pexels_adapter, self.pixabay_adapter):
            try:
                cands = adapter.search(queries=queries, intent=intent, count=count, exclude_urls=exclude_urls)
                for c in cands:
                    # Enforce VIDEO ONLY: reject any candidate with image url
                    if PhysicalVideoValidator.is_image_url(c.media_url or c.source_url):
                        continue
                    c.source_type = SourceType.STOCK
                    norm = c.to_normalized_candidate(query_used=query)
                    norm.source_type = SourceType.STOCK
                    results.append(norm)
            except Exception as e:
                logger.warning(f"[{self.name}] Adapter {adapter.source_name} fallback notice: {e}")

        return results[:count]


# ==============================================================================
# Central Internet Video Retriever Orchestrator
# ==============================================================================
class InternetVideoRetriever:
    """
    Orchestrates the Internet + Movie Visual Retrieval Foundation.
    Enforces deterministic source hierarchy:
        MOVIE / INTERNET_REAL / ARCHIVAL (Primary)
                  ↓
             STOCK VIDEO (Last Resort Fallback)
    Ensures physical video validation and hard VIDEO_ONLY invariant.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        providers: Optional[List[BaseVideoRetrievalProvider]] = None,
        budget: Optional[RetrievalBudget] = None,
        allow_stock_fallback: bool = True
    ):
        self.cache_dir = cache_dir or ASSETS_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget or RetrievalBudget()
        self.allow_stock_fallback = allow_stock_fallback

        if providers is not None:
            self.providers = providers
        else:
            self.providers = [
                NasaSvsRetrievalProvider(),
                ArchivalRetrievalProvider(),
                YouTubeRetrievalProvider(),
                Procedural3DRetrievalProvider(),
                InternetRealRetrievalProvider(),
                MovieRetrievalProvider(),
                StockVideoFallbackProvider()
            ]

        self.expander = AdaptiveQueryExpander()
        self.ingester = StagedStreamIngester()
        self.resolver = WebVideoResolver(cache_dir=self.cache_dir)
        self.parallel_retriever = ParallelVideoRetriever()
        self.telemetry = RetrievalTelemetryCollector()

    def register_provider(self, provider: BaseVideoRetrievalProvider) -> None:
        """Dynamically registers or prepends a new video provider."""
        self.providers.append(provider)

    def get_providers_by_priority(self) -> Tuple[List[BaseVideoRetrievalProvider], List[BaseVideoRetrievalProvider]]:
        """Splits registered providers into primary non-stock vs stock fallback."""
        primary = [p for p in self.providers if p.priority == 1]
        fallback = [p for p in self.providers if p.priority == 2]
        return primary, fallback

    def search_candidates(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        count_per_provider: int = 3,
        exclude_urls: Optional[Set[str]] = None
    ) -> List[NormalizedVideoCandidate]:
        """
        Discovers video candidates honoring the structural priority:
        Queries non-stock providers first via safe parallel retrieval.
        If zero candidates found, attempts adaptive query expansion with VisualIntent.
        Only queries stock fallback if non-stock yields zero candidates.
        """
        primary_providers, fallback_providers = self.get_providers_by_priority()
        exclude = exclude_urls or set()

        # 1. Parallel Primary non-stock search
        candidates, _ = self.parallel_retriever.search_providers_parallel(
            providers=primary_providers,
            query=query,
            intent=intent,
            count=count_per_provider,
            exclude_urls=exclude,
            budget=self.budget
        )

        # If non-stock candidates discovered, return immediately — stock is not touched!
        if candidates:
            logger.info(f"[RETRIEVER] Discovered {len(candidates)} non-stock video candidates for '{query}'.")
            return candidates

        # 1b. Adaptive query expansion for primary non-stock if zero candidates found
        if intent:
            expanded_queries = self.expander.expand_queries(
                base_query=query,
                intent=intent,
                max_variants=self.budget.max_query_expansions
            )
            for alt_q in expanded_queries[1:]:
                logger.info(f"[RETRIEVER] Trying adaptive non-stock query: '{alt_q}'")
                alt_cands, _ = self.parallel_retriever.search_providers_parallel(
                    providers=primary_providers,
                    query=alt_q,
                    intent=intent,
                    count=count_per_provider,
                    exclude_urls=exclude,
                    budget=self.budget
                )
                if alt_cands:
                    logger.info(f"[RETRIEVER] Discovered {len(alt_cands)} non-stock candidates via adaptive query '{alt_q}'.")
                    return alt_cands

        if not self.allow_stock_fallback:
            logger.warning(f"[RETRIEVER] Primary non-stock providers yielded zero candidates for '{query}'. Stock fallback is strictly forbidden.")
            return []

        # 2. Last-resort stock fallback search (only if allow_stock_fallback is True)
        logger.info(f"[RETRIEVER] Zero non-stock candidates for '{query}'. Consulting stock fallback providers.")
        stock_cands, _ = self.parallel_retriever.search_providers_parallel(
            providers=fallback_providers,
            query=query,
            intent=intent,
            count=count_per_provider,
            exclude_urls=exclude,
            budget=self.budget
        )
        return stock_cands

    def download_and_validate(
        self,
        candidate: NormalizedVideoCandidate,
        target_path: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Downloads a candidate video stream via staged streaming and physically verifies its integrity.
        Rejects:
          - Image URLs or image extensions
          - HTML downloaded as MP4 (error pages)
          - Corrupted containers
          - Zero-duration media
          - Still images disguised as MP4 (magic bytes)
          - Missing video streams
        """
        if not candidate.media_url and not candidate.local_path:
            logger.warning(f"[RETRIEVER] Candidate '{candidate.title}' has neither media_url nor local_path.")
            return None

        # If already local, validate directly
        if candidate.local_path:
            p = Path(candidate.local_path)
            min_sharp = 120.0
            check_graphic = True
            check_tc = True
            s_tier = getattr(candidate, "source_tier", None)
            s_name = getattr(candidate, "source_name", "")
            if s_tier == SourceTier.TIER_5_SUPPORTING_STOCK or getattr(candidate, "source_type", None) == SourceType.STOCK:
                min_sharp = 2.0
            elif s_tier == SourceTier.TIER_4_ORIGINAL_PROCEDURAL_3D:
                check_graphic = False
                check_tc = False
            elif s_tier == SourceTier.TIER_1_DIRECT_INSTITUTIONAL or s_name == "nasa_svs":
                min_sharp = 40.0
                check_tc = False
            elif s_tier == SourceTier.TIER_2_ARCHIVAL_VIDEO:
                min_sharp = 40.0

            if p.exists() and PhysicalVideoValidator.is_valid_video(p, check_temporal_motion=True, min_motion_threshold=1.5):
                val_res = PhysicalVideoValidator.validate_file(
                    p,
                    check_temporal_motion=True,
                    check_cleanliness=True,
                    min_sharpness_threshold=min_sharp,
                    check_graphic=check_graphic,
                    check_timecode=check_tc
                )
                if val_res.is_valid:
                    candidate.duration = val_res.duration
                    candidate.width = val_res.width
                    candidate.height = val_res.height
                    candidate.codec = val_res.codec
                    candidate.provenance_metadata["sharpness_score"] = val_res.sharpness_score
                    candidate.provenance_metadata["saturation_mean"] = val_res.saturation_mean
                    candidate.provenance_metadata["is_monochrome"] = val_res.is_monochrome
                    candidate.provenance_metadata["has_watermark"] = val_res.has_watermark
                    candidate.provenance_metadata["has_timecode"] = val_res.has_timecode
                    candidate.provenance_metadata["cleanliness_details"] = val_res.cleanliness_details
                    candidate.provenance_metadata["motion_score"] = val_res.motion_score
                    return p
                else:
                    logger.warning(f"[RETRIEVER] Local path {p} failed physical cleanliness validation: {val_res.error_message}")
                    return None
            elif p.exists():
                logger.warning(f"[RETRIEVER] Local path {p} failed physical video validation.")
                return None

        # Rejection of image URLs
        if PhysicalVideoValidator.is_image_url(candidate.media_url):
            logger.warning(f"[RETRIEVER] Rejected candidate '{candidate.title}' due to static image URL: {candidate.media_url}")
            return None

        dest = target_path or (self.cache_dir / f"vid_{uuid.uuid4().hex[:10]}.mp4")

        # Check canonical asset cache first
        from .cache import get_canonical_cache
        cache = get_canonical_cache()
        media_url = candidate.media_url or candidate.page_url or ""
        if media_url:
            if cache.is_disqualified(media_url, candidate.title):
                logger.info(f"[RETRIEVER] Candidate '{candidate.title}' was previously disqualified. Skipping download.")
                return None
            cached_src = cache.get_source(media_url, candidate.title)
            if cached_src and cached_src.local_path.exists():
                if PhysicalVideoValidator.is_valid_video(cached_src.local_path, check_temporal_motion=True, min_motion_threshold=1.5):
                    logger.info(f"[RETRIEVER] Cache HIT: Reusing verified local source for '{candidate.title}': {cached_src.local_path.name}")
                    candidate.local_path = str(cached_src.local_path)
                    candidate.duration = cached_src.duration
                    candidate.width = cached_src.width
                    candidate.height = cached_src.height
                    candidate.codec = cached_src.codec
                    candidate.provenance_metadata["sharpness_score"] = cached_src.sharpness_score
                    candidate.provenance_metadata["motion_score"] = cached_src.motion_score
                    candidate.provenance_metadata["is_monochrome"] = cached_src.is_monochrome
                    candidate.provenance_metadata["has_watermark"] = cached_src.has_watermark
                    candidate.provenance_metadata["has_timecode"] = cached_src.has_timecode
                    candidate.provenance_metadata["cleanliness_details"] = cached_src.cleanliness_details
                    return cached_src.local_path

        # 1. Web Platforms & Stream Resolution (YouTube, Archive.org, Web Video)
        if self.resolver.is_youtube_url(media_url) or self.resolver.is_archive_org_url(media_url):
            start_time = time.perf_counter()
            resolved = self.resolver.resolve_and_download(
                candidate=candidate,
                target_path=dest,
                duration_sec=12.0
            )
            latency = time.perf_counter() - start_time
            if resolved and resolved.exists():
                cache.put_source(media_url, resolved, metadata=candidate.provenance_metadata, title=candidate.title)
                return resolved

            logger.warning(f"[RETRIEVER] Resolver failed for web media URL: {media_url}")
            cache.mark_disqualified(media_url, "WebVideoResolver could not resolve stream", candidate.title)
            dest.unlink(missing_ok=True)
            self.telemetry.record(RetrievalTelemetryRecord(
                scene_id=getattr(candidate, "scene_id", "scene_0"),
                query=getattr(candidate, "query_used", ""),
                provider=candidate.source_name,
                source_type=candidate.source_type.value,
                candidate_url=candidate.media_url or "",
                retrieval_latency=latency,
                bytes_downloaded=0,
                validation_result="RESOLVER_FAILED",
                semantic_score=candidate.provenance_metadata.get("semantic_score", 0.0),
                temporal_result="N/A",
                memory_result="N/A",
                rejection_reason="WebVideoResolver could not resolve stream",
                selected_status="REJECTED"
            ))
            return None

        # 2. Staged progressive streaming download with early magic byte inspection
        start_time = time.perf_counter()
        success, err_msg, bytes_dl = self.ingester.stream_and_validate(
            url=candidate.media_url,
            dest_path=dest,
            budget=self.budget
        )
        latency = time.perf_counter() - start_time

        if not success or not dest.exists():
            logger.warning(f"[RETRIEVER] Staged download failed for '{candidate.title}': {err_msg}")
            dest.unlink(missing_ok=True)
            self.telemetry.record(RetrievalTelemetryRecord(
                scene_id=getattr(candidate, "scene_id", "scene_0"),
                query=getattr(candidate, "query_used", ""),
                provider=candidate.source_name,
                source_type=candidate.source_type.value,
                candidate_url=candidate.media_url or "",
                retrieval_latency=latency,
                bytes_downloaded=bytes_dl,
                validation_result="DOWNLOAD_FAILED",
                semantic_score=candidate.provenance_metadata.get("semantic_score", 0.0),
                temporal_result="N/A",
                memory_result="N/A",
                rejection_reason=err_msg,
                selected_status="REJECTED"
            ))
            return None

        # Physical Media Validation with Cleanliness
        # Tier 5 literal macro nouns (e.g. clock gear closeups) frequently feature shallow depth of field (bokeh),
        # where the background is intentionally out of focus, yielding a lower whole-frame Laplacian variance.
        # Allow calibrated sharpness threshold for verified macro stock footage.
        min_sharp = 120.0
        check_graphic = True
        check_tc = True
        s_tier = getattr(candidate, "source_tier", None)
        s_name = getattr(candidate, "source_name", "")
        if s_tier == SourceTier.TIER_5_SUPPORTING_STOCK or getattr(candidate, "source_type", None) == SourceType.STOCK:
            min_sharp = 2.0  # Allow authentic macro photography closeups
        elif s_tier == SourceTier.TIER_4_ORIGINAL_PROCEDURAL_3D:
            check_graphic = False  # Procedural 3D camera animations around archival documents are valid Tier 4 video
            check_tc = False
        elif s_tier == SourceTier.TIER_1_DIRECT_INSTITUTIONAL or s_name == "nasa_svs":
            min_sharp = 40.0
            check_tc = False
        elif s_tier == SourceTier.TIER_2_ARCHIVAL_VIDEO:
            min_sharp = 40.0

        val_res = PhysicalVideoValidator.validate_file(
            dest,
            check_temporal_motion=True,
            check_cleanliness=True,
            min_sharpness_threshold=min_sharp,
            check_graphic=check_graphic,
            check_timecode=check_tc
        )
        if not val_res.is_valid:
            logger.warning(f"[RETRIEVER] Physical/cleanliness validation rejected candidate '{candidate.title}': {val_res.error_message}")
            if candidate.media_url:
                cache.mark_disqualified(candidate.media_url, f"Physical cleanliness rejected: {val_res.error_message}", candidate.title)
            dest.unlink(missing_ok=True)
            self.telemetry.record(RetrievalTelemetryRecord(
                scene_id=getattr(candidate, "scene_id", "scene_0"),
                query=getattr(candidate, "query_used", ""),
                provider=candidate.source_name,
                source_type=candidate.source_type.value,
                candidate_url=candidate.media_url or "",
                retrieval_latency=latency,
                bytes_downloaded=bytes_dl,
                validation_result="PHYSICAL_REJECTED",
                semantic_score=candidate.provenance_metadata.get("semantic_score", 0.0),
                temporal_result="N/A",
                memory_result="N/A",
                rejection_reason=val_res.error_message,
                selected_status="REJECTED"
            ))
            return None

        # Update candidate with authoritative physical media attributes and cleanliness metrics
        candidate.local_path = str(dest)
        candidate.duration = val_res.duration
        candidate.width = val_res.width
        candidate.height = val_res.height
        candidate.codec = val_res.codec
        candidate.provenance_metadata["sharpness_score"] = val_res.sharpness_score
        candidate.provenance_metadata["saturation_mean"] = val_res.saturation_mean
        candidate.provenance_metadata["is_monochrome"] = val_res.is_monochrome
        candidate.provenance_metadata["has_watermark"] = val_res.has_watermark
        candidate.provenance_metadata["has_timecode"] = val_res.has_timecode
        candidate.provenance_metadata["cleanliness_details"] = val_res.cleanliness_details
        candidate.provenance_metadata["motion_score"] = val_res.motion_score

        if candidate.media_url:
            cache.put_source(candidate.media_url, dest, val_res, candidate.provenance_metadata, candidate.title)

        logger.info(
            f"[RETRIEVER] Successfully validated {candidate.source_type.value} video: "
            f"'{candidate.title}' ({val_res.width}x{val_res.height}, {val_res.duration:.2f}s, codec={val_res.codec}, "
            f"sharpness={val_res.sharpness_score}, sat={val_res.saturation_mean:.1f})"
        )
        return dest

    def acquire_video_for_scene(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        exclude_urls: Optional[Set[str]] = None,
        target_dir: Optional[Path] = None,
        target_duration: float = 3.0,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        extract_moment: bool = False,
        memory_manager: Optional[Any] = None,
        job_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None
    ) -> NormalizedVideoCandidate:
        """
        Complete end-to-end acquisition pipeline for a scene beat (Steps 1 to 7):
          1. Parallel search non-stock providers (MOVIE, INTERNET_REAL, ARCHIVAL)
          2. Step 2 semantic qualification & Step 5 visual memory evaluation
          3. Adaptive query expansion if initial query yields zero or sub-threshold candidates
          4. Staged streaming download with early magic byte inspection
          5. Early success if qualified non-stock candidate satisfies threshold
          6. Fall back to STOCK VIDEO only if non-stock is exhausted/unqualified
          7. Fail closed under VIDEO_ONLY invariant.
        """
        primary_providers, fallback_providers = self.get_providers_by_priority()
        exclude = set(exclude_urls or [])
        save_dir = target_dir or self.cache_dir

        def _finalize_candidate(cand: NormalizedVideoCandidate) -> Optional[NormalizedVideoCandidate]:
            if extract_moment and cand.local_path and cand.duration > target_duration + 0.5:
                cand_used_ranges = list(used_ranges or [])
                if memory_manager and hasattr(memory_manager, "get_used_ranges_for_candidate"):
                    try:
                        mm_ranges = memory_manager.get_used_ranges_for_candidate(cand)
                        cand_used_ranges.extend(mm_ranges)
                    except Exception as e:
                        logger.debug(f"[RETRIEVER] Notice retrieving used_ranges from memory manager: {e}")

                from .cache import get_canonical_cache
                cache = get_canonical_cache()
                canon_url = cand.media_url or cand.page_url or ""
                reusable = cache.find_reusable_clip(
                    url=canon_url,
                    target_duration=target_duration,
                    used_ranges=cand_used_ranges,
                    require_916=False,
                    title=cand.title
                )
                if reusable:
                    re_path, re_start, re_end = reusable
                    cand.local_clip_path = str(re_path)
                    cand.local_path = str(re_path)
                    cand.duration = round(re_end - re_start, 2)
                    cand.selected_window_start = re_start
                    cand.selected_window_end = re_end
                    return cand

                from .temporal_extractor import TemporalMomentRetriever
                tmr = TemporalMomentRetriever(cache_dir=save_dir)
                clip_path, win = tmr.retrieve_and_extract_best_moment(
                    candidate=cand,
                    intent=intent,
                    target_duration=target_duration,
                    used_ranges=cand_used_ranges,
                    output_dir=save_dir
                )
                if clip_path and win:
                    # Final visual memory gate on extracted moment before mutating candidate
                    if memory_manager:
                        try:
                            final_mem = memory_manager.evaluate_candidate(
                                candidate=cand,
                                temporal_start=win.start_time,
                                temporal_end=win.end_time,
                                job_id=job_id,
                                recent_scene_urls=recent_scene_urls
                            )
                            if final_mem.is_hard_duplicate:
                                logger.warning(
                                    f"[RETRIEVER] Visual memory rejected extracted moment "
                                    f"[{win.start_time:.1f}-{win.end_time:.1f}s] for '{cand.title}': {final_mem.duplicate_reason}"
                                )
                                clip_path.unlink(missing_ok=True)
                                return None
                        except Exception as f_err:
                            logger.debug(f"[RETRIEVER] Final memory check notice: {f_err}")

                    cand.local_clip_path = str(clip_path)
                    cand.local_path = str(clip_path)
                    cand.duration = win.duration
                    cand.selected_window_start = win.start_time
                    cand.selected_window_end = win.end_time
                    cache.register_extracted_clip(
                        url=canon_url,
                        start_time=win.start_time,
                        end_time=win.end_time,
                        clip_path=clip_path,
                        title=cand.title
                    )
                    return cand
                else:
                    logger.warning(f"[RETRIEVER] Temporal extraction failed for '{cand.title}'. Candidate lacks valid moving footage.")
                    cache.mark_disqualified(canon_url, "Temporal extraction failed: no valid moving window", cand.title)
                    return None
            return cand

        # ----------------------------------------------------
        # 1. Non-Stock Retrieval (Primary) with Adaptive Query Loop & Shortlisted Top-Candidate Download
        # ----------------------------------------------------
        logger.info(f"[RETRIEVER] Initiating Primary Non-Stock Video Retrieval for: '{query}'")
        queries_to_try = [query]
        if intent:
            queries_to_try = self.expander.expand_queries(
                base_query=query,
                intent=intent,
                max_variants=self.budget.max_query_expansions
            )

        scene_start_time = time.perf_counter()
        attempted_queries: List[str] = []
        total_candidates_evaluated = 0

        from .cache import get_canonical_cache
        asset_cache = get_canonical_cache()

        for q_idx, active_query in enumerate(queries_to_try):
            elapsed_scene = time.perf_counter() - scene_start_time
            if elapsed_scene >= self.budget.total_scene_timeout:
                logger.warning(
                    f"[RETRIEVER] Scene retrieval total budget exhausted ({elapsed_scene:.1f}s >= "
                    f"{self.budget.total_scene_timeout}s) during query expansion #{q_idx} for '{query}'."
                )
                break

            if q_idx > 0:
                logger.info(f"[RETRIEVER] Executing adaptive non-stock query expansion #{q_idx}: '{active_query}'")
            attempted_queries.append(active_query)

            non_stock_candidates, _ = self.parallel_retriever.search_providers_parallel(
                providers=primary_providers,
                query=active_query,
                intent=intent,
                count=4,
                exclude_urls=exclude,
                budget=self.budget
            )

            if not non_stock_candidates:
                continue

            if intent:
                from .scoring import VisualCandidateScorer
                scorer = VisualCandidateScorer()
                scored_cands = []
                for cand in non_stock_candidates:
                    raw_url = cand.media_url or cand.page_url or ""
                    if raw_url in exclude or asset_cache.is_disqualified(raw_url, cand.title):
                        continue
                    v_cand = cand.to_visual_candidate()
                    score = scorer.score_candidate(v_cand, intent)
                    cand.provenance_metadata["semantic_score"] = score

                    # Check visual memory if manager provided
                    if memory_manager:
                        try:
                            from .memory import extract_canonical_source_id
                            recent_source_ids = [
                                extract_canonical_source_id(u)
                                for u in (recent_scene_urls or [])
                                if extract_canonical_source_id(u)
                            ]
                            eval_res = memory_manager.evaluate_candidate(
                                candidate=cand,
                                intent=intent,
                                job_id=job_id,
                                recent_scene_urls=recent_scene_urls,
                                recent_scene_source_ids=recent_source_ids
                            )
                            if eval_res.is_hard_duplicate:
                                logger.info(f"[RETRIEVER] Visual memory rejected duplicate candidate: {cand.title} ({eval_res.duplicate_reason})")
                                continue
                            score = max(0.0, score - eval_res.penalty)
                            if hasattr(memory_manager, "calculate_source_diversity_bonus"):
                                score += memory_manager.calculate_source_diversity_bonus(cand)
                        except Exception as mem_err:
                            logger.warning(f"[RETRIEVER] Visual memory check notice: {mem_err}")

                    # Pre-download authority & caching bonuses
                    tier_bonus = 0.0
                    s_tier = getattr(cand, "source_tier", None)
                    s_name = getattr(cand, "source_name", "")
                    if s_tier == SourceTier.TIER_1_DIRECT_INSTITUTIONAL or s_name == "nasa_svs":
                        tier_bonus = 0.15
                    elif s_tier == SourceTier.TIER_2_ARCHIVAL_VIDEO or cand.source_type == SourceType.ARCHIVAL:
                        tier_bonus = 0.10
                    elif s_tier == SourceTier.TIER_3_WHITELISTED_DOCUDRAMA or cand.source_type == SourceType.YOUTUBE:
                        tier_bonus = 0.08
                    elif s_tier == SourceTier.TIER_4_ORIGINAL_PROCEDURAL_3D:
                        tier_bonus = 0.05

                    cache_bonus = 0.12 if asset_cache.get_source(raw_url, cand.title) else 0.0
                    pre_rank_score = (0.70 * score) + tier_bonus + cache_bonus
                    cand.provenance_metadata["pre_rank_score"] = pre_rank_score

                    if score >= scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD:
                        scored_cands.append((cand, pre_rank_score, score))

                if not scored_cands:
                    logger.warning(
                        f"[RETRIEVER] Query '{active_query}' returned {len(non_stock_candidates)} candidate(s), "
                        f"but none met semantic threshold ({scorer.MIN_SEMANTIC_RELEVANCE_THRESHOLD})."
                    )
                    continue

                scored_cands.sort(key=lambda x: x[1], reverse=True)
                qualified = [cand for cand, _, _ in scored_cands]

                # Download ONLY the top qualified candidates one by one; stop on the FIRST validated winner!
                for cand in qualified:
                    if (time.perf_counter() - scene_start_time) >= self.budget.total_scene_timeout:
                        logger.warning(f"[RETRIEVER] Candidate download skipped: total scene timeout exceeded.")
                        break

                    valid_path = self.download_and_validate(cand, target_path=save_dir / f"shot_{uuid.uuid4().hex[:8]}.mp4")
                    if not valid_path:
                        bad_url = cand.media_url or cand.page_url
                        if bad_url:
                            exclude.add(bad_url)
                            asset_cache.mark_disqualified(bad_url, "Download or physical validation failed", cand.title)
                        continue

                    total_candidates_evaluated += 1

                    # Candidate physical validation succeeded! Run temporal extraction strictly on this shortlisted candidate.
                    finalized = _finalize_candidate(cand)
                    if finalized:
                        good_url = cand.media_url or cand.page_url
                        if good_url:
                            exclude.add(good_url)
                        logger.info(
                            f"[RETRIEVER] Shortlisted video selected & verified from '{cand.source_name}' "
                            f"(Type: {cand.source_type.value}, Pre-Rank: {cand.provenance_metadata.get('pre_rank_score', 0.0):.3f}): '{cand.title}'"
                        )
                        return finalized
                    else:
                        bad_url = cand.media_url or cand.page_url
                        if bad_url:
                            exclude.add(bad_url)
                            asset_cache.mark_disqualified(bad_url, "Temporal extraction or memory IoU failed", cand.title)

            else:
                for cand in non_stock_candidates:
                    raw_url = cand.media_url or cand.page_url or ""
                    if raw_url in exclude or asset_cache.is_disqualified(raw_url, cand.title):
                        continue
                    if (time.perf_counter() - scene_start_time) >= self.budget.total_scene_timeout:
                        break
                    valid_path = self.download_and_validate(cand, target_path=save_dir / f"shot_{uuid.uuid4().hex[:8]}.mp4")
                    if valid_path:
                        total_candidates_evaluated += 1
                        finalized = _finalize_candidate(cand)
                        if finalized:
                            exclude.add(raw_url)
                            logger.info(
                                f"[RETRIEVER] Primary non-stock video selected from '{cand.source_name}' "
                                f"(Type: {cand.source_type.value}): '{cand.title}'"
                            )
                            return finalized
                        else:
                            if cand.local_path:
                                try:
                                    Path(cand.local_path).unlink(missing_ok=True)
                                except Exception:
                                    pass
                            exclude.add(raw_url)
                            asset_cache.mark_disqualified(raw_url, "Temporal extraction failed", cand.title)

        # ----------------------------------------------------
        # 2. Stock Video Fallback (Only if allow_stock_fallback is True)
        # ----------------------------------------------------
        if self.allow_stock_fallback and fallback_providers:
            logger.warning(f"[RETRIEVER] Non-stock video retrieval exhausted for '{query}'. Consulting stock fallback.")
            stock_candidates, _ = self.parallel_retriever.search_providers_parallel(
                providers=fallback_providers,
                query=query,
                intent=intent,
                count=4,
                exclude_urls=exclude,
                budget=self.budget
            )
            if stock_candidates:
                if intent:
                    from .scoring import VisualCandidateScorer
                    scorer = VisualCandidateScorer()
                    scored_stock = []
                    for cand in stock_candidates:
                        if cand.media_url in exclude or cand.page_url in exclude:
                            continue
                        v_cand = cand.to_visual_candidate()
                        score = scorer.score_candidate(v_cand, intent)
                        cand.provenance_metadata["semantic_score"] = score
                        scored_stock.append((cand, score))
                    scored_stock.sort(key=lambda x: x[1], reverse=True)
                    for cand, score in scored_stock:
                        valid_path = self.download_and_validate(cand, target_path=save_dir / f"shot_{uuid.uuid4().hex[:8]}.mp4")
                        if valid_path:
                            exclude.add(cand.media_url or cand.page_url)
                            return _finalize_candidate(cand)
                else:
                    for cand in stock_candidates:
                        if cand.media_url in exclude or cand.page_url in exclude:
                            continue
                        valid_path = self.download_and_validate(cand, target_path=save_dir / f"shot_{uuid.uuid4().hex[:8]}.mp4")
                        if valid_path:
                            exclude.add(cand.media_url or cand.page_url)
                            return _finalize_candidate(cand)

        # Fail closed: zero stock permitted
        elapsed_total = time.perf_counter() - scene_start_time
        logger.error(
            f"[RETRIEVER] Non-stock video retrieval exhausted for query '{query}' "
            f"(Tried {len(attempted_queries)} queries in {elapsed_total:.1f}s, evaluated {total_candidates_evaluated} candidates). "
            f"Stock fallback is strictly forbidden."
        )
        raise RuntimeError(
            f"Unable to retrieve or physically verify authentic documentary/archival moving video for scene query '{query}'. "
            f"Attempted {len(attempted_queries)} queries: {attempted_queries}. "
            f"Evaluated {total_candidates_evaluated} downloaded candidates over {elapsed_total:.1f}s. "
            f"Under the real-footage production policy, stock fallback (Pexels/Pixabay) is strictly forbidden. Failing closed."
        )

    def acquire_moment_for_scene(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        exclude_urls: Optional[Set[str]] = None,
        target_dir: Optional[Path] = None,
        target_duration: float = 3.0,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        memory_manager: Optional[Any] = None,
        job_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None
    ) -> NormalizedVideoCandidate:
        """Convenience method that retrieves candidate footage and extracts the exact 2-4s temporal moment."""
        return self.acquire_video_for_scene(
            query=query,
            intent=intent,
            exclude_urls=exclude_urls,
            target_dir=target_dir,
            target_duration=target_duration,
            used_ranges=used_ranges,
            extract_moment=True,
            memory_manager=memory_manager,
            job_id=job_id,
            scene_id=scene_id,
            recent_scene_urls=recent_scene_urls
        )

    def acquire_framed_clip_for_scene(
        self,
        query: str,
        intent: Optional[VisualIntent] = None,
        exclude_urls: Optional[Set[str]] = None,
        target_dir: Optional[Path] = None,
        target_duration: float = 3.0,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        used_crops: Optional[List[Tuple[float, float]]] = None,
        memory_manager: Optional[Any] = None,
        job_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None
    ) -> NormalizedVideoCandidate:
        """
        Complete end-to-end acquisition, moment extraction, and vertical 9:16 framing pipeline (Steps 1 to 7):
          1. Retrieve primary non-stock / fallback stock footage with parallel search & adaptive expansion.
          2. Step 2 semantic qualification check & Step 5 visual memory evaluation.
          3. Step 3 temporal moment extraction (2-4s sub-clip).
          4. Step 4 intelligent 9:16 vertical editorial framing (1080x1920).
          5. Physical validation of final 9:16 video.
        """
        max_framing_retries = 3
        curr_exclude = set(exclude_urls or [])
        cand = None

        from .cache import get_canonical_cache
        cache = get_canonical_cache()

        for attempt in range(max_framing_retries):
            cand = self.acquire_moment_for_scene(
                query=query,
                intent=intent,
                exclude_urls=curr_exclude,
                target_dir=target_dir,
                target_duration=target_duration,
                used_ranges=used_ranges,
                memory_manager=memory_manager,
                job_id=job_id,
                scene_id=scene_id,
                recent_scene_urls=recent_scene_urls
            )

            if not cand or not cand.local_path or not Path(cand.local_path).exists():
                return cand

            if cand.width == 1080 and cand.height == 1920:
                return cand

            canon_url = cand.media_url or cand.page_url or ""
            reusable_framed = cache.find_reusable_clip(
                url=canon_url,
                target_duration=target_duration,
                used_ranges=used_ranges,
                require_916=True,
                title=cand.title
            )
            if reusable_framed:
                f_path, f_start, f_end = reusable_framed
                cand.local_clip_path = str(f_path)
                cand.local_path = str(f_path)
                cand.width = 1080
                cand.height = 1920
                return cand

            from .framing import IntelligentFramingEngine
            save_dir = target_dir or self.cache_dir
            framing_engine = IntelligentFramingEngine(cache_dir=save_dir)
            framed_path = framing_engine.frame_video_to_916(
                video_path=Path(cand.local_path),
                intent=intent,
                metadata=cand.provenance_metadata,
                used_crops=used_crops
            )
            if framed_path and framed_path.exists():
                cand.local_clip_path = str(framed_path)
                cand.local_path = str(framed_path)
                cand.width = framing_engine.TARGET_WIDTH
                cand.height = framing_engine.TARGET_HEIGHT
                cache.register_extracted_clip(
                    url=canon_url,
                    start_time=cand.selected_window_start or 0.0,
                    end_time=cand.selected_window_end or cand.duration,
                    clip_path=Path(cand.local_clip_path),
                    framed_916_path=framed_path,
                    title=cand.title
                )
                return cand
            else:
                logger.warning(
                    f"[RETRIEVER] Intelligent framing failed for candidate '{cand.title}'. "
                    f"Disqualifying candidate and retrying retrieval (attempt {attempt+1}/{max_framing_retries})."
                )
                bad_url = cand.media_url or cand.page_url
                if bad_url:
                    curr_exclude.add(bad_url)
                    cache.mark_disqualified(bad_url, "Intelligent framing failed", cand.title)
                if cand.local_path:
                    try:
                        Path(cand.local_path).unlink(missing_ok=True)
                    except Exception:
                        pass
                cand = None

        return cand
