"""
Phase 6: Cloud-Native Headless Asset Fetcher.
=============================================
Consumes ProductionAssetManifest, retrieves verified visual evidence and assets
via headless HTTP/HTTPS streaming directly to disk/cache, strictly enforcing SSRF security,
zero RAM buffering, zero arbitrary 50MB ceiling, and SHA-256 integrity caching.

Security & Cloud Autonomy Invariants:
  - 100% Headless & Cloud-Autonomous: Zero browser or GUI dependencies.
  - SSRF Protection: SafeURLValidator validates every hop of HTTP redirects.
  - Bounded Streaming: Direct disk/cache streaming prevents RAM exhaustion (no 50MB limit).
  - Exception Isolation: Per-asset failures are captured without crashing the manifest run.
  - Content-Addressable Caching: Leverages MediaCache to prevent redundant downloads.
"""

import hashlib
import io
import logging
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import requests

from intelligence.asset_manifest import ProductionAssetManifest, BeatVisualAssignment
from intelligence.media_cache import MediaCache, MediaIntegrityError, MediaCacheError
from intelligence.visual_sources import SafeURLValidator

logger = logging.getLogger("alamr.asset_fetcher")

# Operational defaults
DEFAULT_CONNECT_TIMEOUT = 5.0          # seconds
DEFAULT_READ_TIMEOUT = 15.0            # seconds
DEFAULT_MAX_REDIRECTS = 5


class AssetFetchStatus(str, Enum):
    SUCCESS = "SUCCESS"
    CACHE_HIT = "CACHE_HIT"
    FAILED_SSRF = "FAILED_SSRF"
    FAILED_SIZE = "FAILED_SIZE"
    FAILED_TIMEOUT = "FAILED_TIMEOUT"
    FAILED_HTTP = "FAILED_HTTP"
    FAILED_INTEGRITY = "FAILED_INTEGRITY"
    FAILED_NETWORK = "FAILED_NETWORK"
    SKIPPED_NO_URL = "SKIPPED_NO_URL"


@dataclass
class AssetFetchResult:
    """Outcome of fetching an individual visual asset."""
    url: str
    status: AssetFetchStatus
    local_path: Optional[Path] = None
    sha256: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: int = 0
    duration_ms: float = 0.0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status.value,
            "local_path": str(self.local_path) if self.local_path else None,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "duration_ms": round(self.duration_ms, 2),
            "error_message": self.error_message,
        }


@dataclass
class ManifestFetchSummary:
    """Summary of all asset fetch operations for a ProductionAssetManifest."""
    manifest_id: str
    total_requested: int = 0
    successful: int = 0
    cache_hits: int = 0
    downloads: int = 0
    failed: int = 0
    results: Dict[str, AssetFetchResult] = field(default_factory=dict)
    asset_path_by_beat: Dict[str, Optional[Path]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "total_requested": self.total_requested,
            "successful": self.successful,
            "cache_hits": self.cache_hits,
            "downloads": self.downloads,
            "failed": self.failed,
            "results": {k: v.to_dict() for k, v in self.results.items()},
            "asset_path_by_beat": {
                k: str(v) if v else None for k, v in self.asset_path_by_beat.items()
            },
        }


class AssetFetcher:
    """
    Headless HTTP/HTTPS asset fetcher with SSRF validation, streaming byte limits,
    and automatic caching.
    """

    def __init__(
        self,
        media_cache: Optional[MediaCache] = None,
        max_bytes: Optional[int] = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        user_agent: str = "AL-AMR-NewsBot/1.0 (Cloud-Autonomous Production; +https://alamr.news)",
    ):
        self.media_cache = media_cache or MediaCache()
        self.max_bytes = max_bytes
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_redirects = max_redirects
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    @staticmethod
    def sniff_mime_type(data: bytes, header_mime: Optional[str] = None) -> str:
        """Determines MIME type from header and magic bytes."""
        if not data:
            return header_mime or "application/octet-stream"

        # Magic byte detection
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if data.startswith(b"RIFF") and len(data) > 12 and data[8:12] == b"WEBP":
            return "image/webp"
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return "video/webm"
        if len(data) > 8 and (data[4:8] == b"ftyp" or data[4:12].startswith(b"ftyp")):
            return "video/mp4"

        # Fallback to header MIME if present and specific
        if header_mime and header_mime != "application/octet-stream":
            clean_mime = header_mime.split(";")[0].strip().lower()
            return clean_mime

        return "application/octet-stream"

    def fetch_url(
        self,
        url: str,
        expected_hash: Optional[str] = None,
    ) -> AssetFetchResult:
        """
        Retrieves asset from URL or cache with complete validation.

        Args:
            url: Asset URL to fetch.
            expected_hash: Optional expected SHA-256 hash.

        Returns:
            AssetFetchResult with status and metadata.
        """
        start_t = time.perf_counter()

        if not url or not url.strip():
            return AssetFetchResult(
                url=url or "",
                status=AssetFetchStatus.SKIPPED_NO_URL,
                error_message="Empty URL",
            )

        clean_url = url.strip()

        # 1. Check MediaCache by URL or expected_hash first
        if expected_hash and self.media_cache.has_hash(expected_hash):
            cached_p = self.media_cache.get_by_hash(expected_hash)
            if cached_p:
                dur = (time.perf_counter() - start_t) * 1000
                return AssetFetchResult(
                    url=clean_url,
                    status=AssetFetchStatus.CACHE_HIT,
                    local_path=cached_p,
                    sha256=expected_hash,
                    mime_type=self.sniff_mime_type(b"", None),
                    size_bytes=cached_p.stat().st_size,
                    duration_ms=dur,
                )

        if self.media_cache.has_url(clean_url):
            cached_p = self.media_cache.get_by_url(clean_url)
            if cached_p:
                dur = (time.perf_counter() - start_t) * 1000
                sha = self.media_cache.compute_sha256(cached_p)
                return AssetFetchResult(
                    url=clean_url,
                    status=AssetFetchStatus.CACHE_HIT,
                    local_path=cached_p,
                    sha256=sha,
                    mime_type=None,
                    size_bytes=cached_p.stat().st_size,
                    duration_ms=dur,
                )

        # 2. Initial SSRF validation
        safe, reason = SafeURLValidator.is_safe_url(clean_url, resolve_dns=True)
        if not safe:
            dur = (time.perf_counter() - start_t) * 1000
            logger.warning(f"Blocked unsafe URL '{clean_url}': {reason}")
            return AssetFetchResult(
                url=clean_url,
                status=AssetFetchStatus.FAILED_SSRF,
                duration_ms=dur,
                error_message=f"SSRF violation: {reason}",
            )

        # 3. Stream download following redirects with hop-by-hop SSRF validation
        current_url = clean_url
        redirect_count = 0
        response = None

        try:
            while redirect_count <= self.max_redirects:
                resp = self.session.get(
                    current_url,
                    stream=True,
                    timeout=(self.connect_timeout, self.read_timeout),
                    allow_redirects=False,
                )

                # Check for redirect
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    location = resp.headers.get("Location")
                    if not location:
                        dur = (time.perf_counter() - start_t) * 1000
                        return AssetFetchResult(
                            url=clean_url,
                            status=AssetFetchStatus.FAILED_HTTP,
                            duration_ms=dur,
                            error_message="Redirect missing Location header",
                        )

                    next_url = urllib.parse.urljoin(current_url, location)
                    # Validate redirected URL against SSRF
                    is_safe_redir, redir_reason = SafeURLValidator.is_safe_url(
                        next_url, resolve_dns=True
                    )
                    if not is_safe_redir:
                        dur = (time.perf_counter() - start_t) * 1000
                        logger.warning(
                            f"SSRF blocked redirect from {current_url} to {next_url}: {redir_reason}"
                        )
                        return AssetFetchResult(
                            url=clean_url,
                            status=AssetFetchStatus.FAILED_SSRF,
                            duration_ms=dur,
                            error_message=f"Redirect SSRF violation: {redir_reason}",
                        )
                    current_url = next_url
                    continue

                response = resp
                break

            if not response or response.status_code != 200:
                code = response.status_code if response else "NO_RESPONSE"
                dur = (time.perf_counter() - start_t) * 1000
                return AssetFetchResult(
                    url=clean_url,
                    status=AssetFetchStatus.FAILED_HTTP,
                    duration_ms=dur,
                    error_message=f"HTTP {code}",
                )

            # If explicit max_bytes limit is configured, check Content-Length header
            header_len = response.headers.get("Content-Length")
            if header_len and self.max_bytes is not None:
                try:
                    decl_size = int(header_len)
                    if decl_size > self.max_bytes:
                        dur = (time.perf_counter() - start_t) * 1000
                        return AssetFetchResult(
                            url=clean_url,
                            status=AssetFetchStatus.FAILED_SIZE,
                            size_bytes=decl_size,
                            duration_ms=dur,
                            error_message=f"Content-Length ({decl_size}) exceeds configured limit ({self.max_bytes})",
                        )
                except ValueError:
                    pass

            # Stream chunks directly to disk/cache to ensure ZERO RAM exhaustion
            temp_stream_path = self.media_cache.blobs_dir / f"stream_{uuid.uuid4().hex}.tmp"
            hasher = hashlib.sha256()
            downloaded = 0
            header_sample = b""

            try:
                with open(temp_stream_path, "wb") as f_out:
                    for chunk in response.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if self.max_bytes is not None and downloaded > self.max_bytes:
                            dur = (time.perf_counter() - start_t) * 1000
                            return AssetFetchResult(
                                url=clean_url,
                                status=AssetFetchStatus.FAILED_SIZE,
                                size_bytes=downloaded,
                                duration_ms=dur,
                                error_message=f"Streamed bytes ({downloaded}) exceeded configured max limit ({self.max_bytes})",
                            )
                        if len(header_sample) < 65536:
                            header_sample += chunk[:65536 - len(header_sample)]
                        f_out.write(chunk)
                        hasher.update(chunk)

                if downloaded == 0:
                    dur = (time.perf_counter() - start_t) * 1000
                    return AssetFetchResult(
                        url=clean_url,
                        status=AssetFetchStatus.FAILED_HTTP,
                        duration_ms=dur,
                        error_message="Downloaded 0 bytes (empty body)",
                    )

                computed_hash = hasher.hexdigest()

                # Hash verification
                if expected_hash and computed_hash.lower() != expected_hash.strip().lower():
                    dur = (time.perf_counter() - start_t) * 1000
                    return AssetFetchResult(
                        url=clean_url,
                        status=AssetFetchStatus.FAILED_INTEGRITY,
                        sha256=computed_hash,
                        size_bytes=downloaded,
                        duration_ms=dur,
                        error_message=f"Checksum mismatch: expected {expected_hash}, got {computed_hash}",
                    )

                # MIME and extension detection from header sample and Content-Type
                header_mime = response.headers.get("Content-Type")
                mime_type = self.sniff_mime_type(header_sample, header_mime)

                # Atomically save to MediaCache using put_file (streaming directly on disk)
                cached_path, saved_hash = self.media_cache.put_file(
                    url=clean_url,
                    source_path=temp_stream_path,
                    mime_type=mime_type,
                    expected_hash=computed_hash,
                )

                dur = (time.perf_counter() - start_t) * 1000
                return AssetFetchResult(
                    url=clean_url,
                    status=AssetFetchStatus.SUCCESS,
                    local_path=cached_path,
                    sha256=saved_hash,
                    mime_type=mime_type,
                    size_bytes=downloaded,
                    duration_ms=dur,
                )

            finally:
                if temp_stream_path.exists():
                    try:
                        temp_stream_path.unlink()
                    except Exception:
                        pass

        except requests.exceptions.Timeout as te:
            dur = (time.perf_counter() - start_t) * 1000
            logger.warning(f"Timeout fetching {clean_url}: {te}")
            return AssetFetchResult(
                url=clean_url,
                status=AssetFetchStatus.FAILED_TIMEOUT,
                duration_ms=dur,
                error_message=f"Timeout: {te}",
            )
        except requests.exceptions.RequestException as re_err:
            dur = (time.perf_counter() - start_t) * 1000
            logger.warning(f"Network error fetching {clean_url}: {re_err}")
            return AssetFetchResult(
                url=clean_url,
                status=AssetFetchStatus.FAILED_NETWORK,
                duration_ms=dur,
                error_message=f"Request error: {re_err}",
            )
        except MediaIntegrityError as mie:
            dur = (time.perf_counter() - start_t) * 1000
            return AssetFetchResult(
                url=clean_url,
                status=AssetFetchStatus.FAILED_INTEGRITY,
                duration_ms=dur,
                error_message=str(mie),
            )
        except Exception as exc:
            dur = (time.perf_counter() - start_t) * 1000
            logger.error(f"Unexpected error fetching {clean_url}: {exc}")
            return AssetFetchResult(
                url=clean_url,
                status=AssetFetchStatus.FAILED_NETWORK,
                duration_ms=dur,
                error_message=f"Unexpected failure: {exc}",
            )

    def fetch_manifest_assets(
        self,
        manifest: ProductionAssetManifest,
    ) -> ManifestFetchSummary:
        """
        Retrieves all visual assets assigned in a ProductionAssetManifest.
        Maps local paths back to beats.
        """
        summary = ManifestFetchSummary(manifest_id=manifest.manifest_id)

        for beat in manifest.beats:
            media_url = beat.media_url
            if not media_url:
                summary.asset_path_by_beat[beat.beat_id] = None
                continue

            summary.total_requested += 1

            # Check if this URL was already fetched in this batch
            if media_url in summary.results:
                prev_res = summary.results[media_url]
                summary.asset_path_by_beat[beat.beat_id] = prev_res.local_path
                continue

            res = self.fetch_url(media_url)
            summary.results[media_url] = res

            if res.status in (AssetFetchStatus.SUCCESS, AssetFetchStatus.CACHE_HIT):
                summary.successful += 1
                if res.status == AssetFetchStatus.CACHE_HIT:
                    summary.cache_hits += 1
                else:
                    summary.downloads += 1
                summary.asset_path_by_beat[beat.beat_id] = res.local_path
            else:
                summary.failed += 1
                summary.asset_path_by_beat[beat.beat_id] = None

        logger.info(
            f"Manifest [{manifest.manifest_id}] asset fetch complete: "
            f"{summary.successful}/{summary.total_requested} fetched "
            f"({summary.cache_hits} cached, {summary.downloads} downloaded, {summary.failed} failed)"
        )
        return summary
