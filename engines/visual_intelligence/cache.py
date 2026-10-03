"""
Canonical Asset Cache & Provider Circuit Breaker Engine.
=========================================================
Provides aggressive per-scene and per-job caching and fail-fast circuit breaking
for visual intelligence retrieval (Step 8 runtime optimization).

Guarantees:
  1. No duplicate downloads or analysis of the same canonical source within a job.
  2. Canonical source ID and normalized URL resolution mapped to local validated media.
  3. Cached timeline profiles (motion deltas, sharpness) to prevent redundant OpenCV passes.
  4. Instant reuse of already-downloaded and already-framed clips across shots/scenes.
  5. Bounded timeouts & fail-fast circuit breaker for slow, broken, or rate-limited providers.
  6. Thread-safe operations across concurrent workers.
"""
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Set

from core.media_validator import PhysicalVideoValidator, VideoValidationResult
from .memory import extract_canonical_source_id, normalize_visual_url

logger = logging.getLogger(__name__)


@dataclass
class CachedSource:
    canonical_id: str
    normalized_url: str
    local_path: Path
    duration: float
    width: int
    height: int
    codec: str
    sharpness_score: float = 0.0
    motion_score: float = 0.0
    is_monochrome: bool = False
    has_watermark: bool = False
    has_timecode: bool = False
    cleanliness_details: Dict[str, Any] = field(default_factory=dict)
    provenance_metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.perf_counter)


@dataclass
class CachedClip:
    canonical_id: str
    start_time: float
    end_time: float
    duration: float
    clip_path: Path
    framed_916_path: Optional[Path] = None


class CanonicalAssetCache:
    """
    Per-job and per-scene canonical asset cache.
    Eliminates redundant downloads, redundant temporal profiling, and redundant framing.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._sources: Dict[str, CachedSource] = {}
        self._disqualified: Dict[str, str] = {}
        self._timeline_profiles: Dict[str, List[Dict[str, float]]] = {}
        self._extracted_clips: Dict[str, List[CachedClip]] = {}

    def get_canonical_key(self, url: str, title: str = "") -> str:
        """Derives a primary canonical key for the media asset."""
        if not url:
            return ""
        cid = extract_canonical_source_id(url, title)
        if cid:
            return cid
        norm = normalize_visual_url(url)
        return norm or url.strip()

    def is_disqualified(self, url: str, title: str = "") -> bool:
        """Checks if a canonical source has already failed or been disqualified in this job."""
        key = self.get_canonical_key(url, title)
        with self._lock:
            if key in self._disqualified:
                return True
            norm = normalize_visual_url(url)
            return norm in self._disqualified

    def get_disqualification_reason(self, url: str, title: str = "") -> Optional[str]:
        key = self.get_canonical_key(url, title)
        with self._lock:
            return self._disqualified.get(key) or self._disqualified.get(normalize_visual_url(url))

    def mark_disqualified(self, url: str, reason: str, title: str = "") -> None:
        """Marks a canonical source as disqualified so it is never re-downloaded or re-analyzed."""
        key = self.get_canonical_key(url, title)
        norm = normalize_visual_url(url)
        with self._lock:
            if key:
                self._disqualified[key] = reason
            if norm:
                self._disqualified[norm] = reason
            logger.debug(f"[ASSET_CACHE] Disqualified source '{key or norm}': {reason}")

    def get_source(self, url: str, title: str = "") -> Optional[CachedSource]:
        """Retrieves a cached source if already validated and existing on disk."""
        key = self.get_canonical_key(url, title)
        norm = normalize_visual_url(url)
        with self._lock:
            source = self._sources.get(key) or self._sources.get(norm)
            if source:
                if source.local_path and source.local_path.exists():
                    return source
                else:
                    self._sources.pop(key, None)
                    if norm:
                        self._sources.pop(norm, None)
            return None

    def put_source(
        self,
        url: str,
        local_path: Path,
        val_res: Optional[VideoValidationResult] = None,
        metadata: Optional[Dict[str, Any]] = None,
        title: str = ""
    ) -> CachedSource:
        """Stores a validated downloaded/sliced video source in the cache."""
        key = self.get_canonical_key(url, title)
        norm = normalize_visual_url(url)
        meta = metadata or {}

        if val_res and val_res.is_valid:
            duration = val_res.duration
            width = val_res.width
            height = val_res.height
            codec = val_res.codec
            sharpness = val_res.sharpness_score
            motion = val_res.motion_score
            is_mono = val_res.is_monochrome
            has_wm = val_res.has_watermark
            has_tc = val_res.has_timecode
            clean_det = val_res.cleanliness_details
        else:
            duration = float(meta.get("duration", 0.0))
            width = int(meta.get("width", 1920))
            height = int(meta.get("height", 1080))
            codec = str(meta.get("codec", "h264"))
            sharpness = float(meta.get("sharpness_score", 0.0))
            motion = float(meta.get("motion_score", 0.0))
            is_mono = bool(meta.get("is_monochrome", False))
            has_wm = bool(meta.get("has_watermark", False))
            has_tc = bool(meta.get("has_timecode", False))
            clean_det = meta.get("cleanliness_details", {})

        cached = CachedSource(
            canonical_id=key,
            normalized_url=norm,
            local_path=local_path,
            duration=duration,
            width=width,
            height=height,
            codec=codec,
            sharpness_score=sharpness,
            motion_score=motion,
            is_monochrome=is_mono,
            has_watermark=has_wm,
            has_timecode=has_tc,
            cleanliness_details=clean_det,
            provenance_metadata=meta
        )

        with self._lock:
            if key:
                self._sources[key] = cached
            if norm:
                self._sources[norm] = cached
            logger.info(f"[ASSET_CACHE] Registered validated source '{key or norm}' -> {local_path.name}")
        return cached

    def get_timeline_profile(self, url: str, title: str = "") -> Optional[List[Dict[str, float]]]:
        """Retrieves cached timeline profile to bypass OpenCV frame extraction."""
        key = self.get_canonical_key(url, title)
        with self._lock:
            return self._timeline_profiles.get(key)

    def put_timeline_profile(self, url: str, profile: List[Dict[str, float]], title: str = "") -> None:
        """Stores computed timeline profile for a canonical source."""
        key = self.get_canonical_key(url, title)
        with self._lock:
            if key:
                self._timeline_profiles[key] = profile

    def register_extracted_clip(
        self,
        url: str,
        start_time: float,
        end_time: float,
        clip_path: Path,
        framed_916_path: Optional[Path] = None,
        title: str = ""
    ) -> None:
        """Records an extracted sub-clip and framed video for possible reuse."""
        key = self.get_canonical_key(url, title)
        clip = CachedClip(
            canonical_id=key,
            start_time=start_time,
            end_time=end_time,
            duration=round(end_time - start_time, 2),
            clip_path=clip_path,
            framed_916_path=framed_916_path
        )
        with self._lock:
            if key not in self._extracted_clips:
                self._extracted_clips[key] = []
            self._extracted_clips[key].append(clip)
            logger.debug(f"[ASSET_CACHE] Registered extracted clip [{start_time:.1f}s-{end_time:.1f}s] for '{key}'")

    def find_reusable_clip(
        self,
        url: str,
        target_duration: float,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        require_916: bool = False,
        title: str = ""
    ) -> Optional[Tuple[Path, float, float]]:
        """
        Finds an already extracted clip from this canonical source that satisfies
        target_duration (+/- 1.2s) and does NOT overlap with used_ranges.
        """
        key = self.get_canonical_key(url, title)
        used = used_ranges or []
        with self._lock:
            clips = self._extracted_clips.get(key, [])
            for c in clips:
                cand_path = c.framed_916_path if require_916 else (c.framed_916_path or c.clip_path)
                if not cand_path or not cand_path.exists():
                    continue

                if abs(c.duration - target_duration) > 1.2:
                    continue

                has_overlap = False
                for u_start, u_end in used:
                    ov = max(0.0, min(c.end_time, u_end) - max(c.start_time, u_start))
                    if ov > 0.5:
                        has_overlap = True
                        break
                if not has_overlap:
                    logger.info(f"[ASSET_CACHE] Reusing extracted clip for '{key}' [{c.start_time:.1f}s-{c.end_time:.1f}s]: {cand_path.name}")
                    return cand_path, c.start_time, c.end_time

        return None

    def reset(self) -> None:
        """Resets the in-memory cache (e.g. between jobs)."""
        with self._lock:
            self._sources.clear()
            self._disqualified.clear()
            self._timeline_profiles.clear()
            self._extracted_clips.clear()


class ProviderCircuitBreaker:
    """
    Fail-fast circuit breaker for retrieval providers.
    Prevents repeated stalls when a provider times out, encounters rate limits,
    or has network connectivity issues.
    """

    MAX_CONSECUTIVE_FAILURES = 2

    def __init__(self):
        self._lock = threading.RLock()
        self._failures: Dict[str, int] = {}
        self._is_open: Dict[str, bool] = {}
        self._trip_reasons: Dict[str, str] = {}

    def is_available(self, provider_name: str) -> bool:
        """Checks if a provider is operational (circuit CLOSED)."""
        with self._lock:
            return not self._is_open.get(provider_name, False)

    def record_success(self, provider_name: str) -> None:
        """Records a successful search, resetting failure counts."""
        with self._lock:
            self._failures[provider_name] = 0
            self._is_open[provider_name] = False

    def record_failure(self, provider_name: str, error: str) -> None:
        """Records a provider failure and trips circuit if threshold exceeded."""
        with self._lock:
            curr = self._failures.get(provider_name, 0) + 1
            self._failures[provider_name] = curr
            if curr >= self.MAX_CONSECUTIVE_FAILURES:
                self._is_open[provider_name] = True
                self._trip_reasons[provider_name] = error
                logger.warning(
                    f"[CIRCUIT_BREAKER] Provider '{provider_name}' TRIPPED after {curr} consecutive failures. "
                    f"Last error: {error}. Bypassing for this job."
                )
            else:
                logger.info(f"[CIRCUIT_BREAKER] Provider '{provider_name}' recorded failure ({curr}/{self.MAX_CONSECUTIVE_FAILURES}): {error}")

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()
            self._is_open.clear()
            self._trip_reasons.clear()


# Global Singleton Access
_GLOBAL_ASSET_CACHE = CanonicalAssetCache()
_GLOBAL_CIRCUIT_BREAKER = ProviderCircuitBreaker()


def get_canonical_cache() -> CanonicalAssetCache:
    return _GLOBAL_ASSET_CACHE


def get_circuit_breaker() -> ProviderCircuitBreaker:
    return _GLOBAL_CIRCUIT_BREAKER
