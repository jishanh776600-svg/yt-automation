"""
Phase 6: Content-Addressable Media Cache & Integrity Verification.
==================================================================
Provides atomic, deterministic, content-addressable storage for fetched visual
assets (images, video clips) indexed by SHA-256 hash and source URL.

Invariants:
  - Content-Addressable: Storage layout keyed by sha256 hash.
  - Atomic Writes: Writes to temporary files before atomic rename, preventing partial/corrupt files.
  - Verification on Read/Write: Detects bitrot, truncated downloads, and hash mismatches.
  - 100% Headless & Cloud-Autonomous: Pure Python standard library file operations, works in any OS.
"""

import hashlib
import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple, Any

logger = logging.getLogger("alamr.media_cache")

DEFAULT_CACHE_DIR = Path("data/cache/media")


class MediaCacheError(Exception):
    """Base exception for media cache failures."""
    pass


class MediaIntegrityError(MediaCacheError):
    """Raised when an asset's computed hash does not match its expected hash."""
    pass


class MediaCache:
    """
    Content-Addressable Media Cache storing assets by SHA-256 hash.
    Maintains a URL-to-hash mapping index for fast lookups.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.blobs_dir = self.cache_dir / "sha256"
        self.index_file = self.cache_dir / "media_index.json"
        self._ensure_dirs()
        self._index: Dict[str, Dict[str, Any]] = self._load_index()

    def _ensure_dirs(self) -> None:
        """Create necessary directories if they do not exist."""
        self.blobs_dir.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        """Loads index mapping from disk."""
        if not self.index_file.exists():
            return {}
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read media cache index: {e}, resetting index")
            return {}

    def _save_index(self) -> None:
        """Persists index mapping to disk atomically."""
        tmp_file = self.cache_dir / f"media_index.json.tmp.{uuid.uuid4().hex}"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self._index, f, indent=2)
            tmp_file.replace(self.index_file)
        except Exception as e:
            logger.error(f"Failed to save media cache index: {e}")
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

    @staticmethod
    def compute_sha256(data_or_path: Any) -> str:
        """Computes SHA-256 hex digest for either bytes or a Path."""
        hasher = hashlib.sha256()
        if isinstance(data_or_path, (bytes, bytearray)):
            hasher.update(data_or_path)
            return hasher.hexdigest()
        elif isinstance(data_or_path, (str, Path)):
            path = Path(data_or_path)
            if not path.exists():
                raise FileNotFoundError(f"Cannot compute hash: file does not exist {path}")
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
            return hasher.hexdigest()
        else:
            raise TypeError(f"Expected bytes or Path, got {type(data_or_path)}")

    def _normalize_ext(self, ext: Optional[str], mime_type: Optional[str] = None) -> str:
        """Determines normalized extension from explicit ext or mime_type."""
        if ext and ext.strip().lower() not in (".tmp", ".temp", ".part", ".bin"):
            clean = ext.strip().lower()
            if not clean.startswith("."):
                clean = f".{clean}"
            return clean

        mime_map = {
            "video/mp4": ".mp4",
            "video/webm": ".webm",
            "video/quicktime": ".mov",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/aac": ".aac",
        }
        if mime_type and mime_type.lower() in mime_map:
            return mime_map[mime_type.lower()]

        return ".jpg"

    def has_hash(self, sha256_hash: str) -> bool:
        """Returns True if a blob with the given hash exists and is non-empty."""
        if not sha256_hash:
            return False
        h = sha256_hash.strip().lower()
        candidates = list(self.blobs_dir.glob(f"{h}.*")) + list(self.blobs_dir.glob(f"{h}"))
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                return True
        return False

    def has_url(self, url: str) -> bool:
        """Returns True if the URL is indexed and the cached file exists."""
        if not url or url not in self._index:
            return False
        entry = self._index[url]
        sha256_hash = entry.get("sha256")
        cached_path = entry.get("path")
        if cached_path and Path(cached_path).is_file() and Path(cached_path).stat().st_size > 0:
            return True
        if sha256_hash and self.has_hash(sha256_hash):
            return True
        return False

    def get_by_hash(self, sha256_hash: str) -> Optional[Path]:
        """Retrieves path for cached blob by hash, or None if not found."""
        if not sha256_hash:
            return None
        h = sha256_hash.strip().lower()
        candidates = list(self.blobs_dir.glob(f"{h}.*")) + [self.blobs_dir / h]
        for c in candidates:
            if c.is_file() and c.stat().st_size > 0:
                return c
        return None

    def get_by_url(self, url: str) -> Optional[Path]:
        """Retrieves cached file path by URL if indexed and valid."""
        if not url or url not in self._index:
            return None
        entry = self._index[url]
        p = entry.get("path")
        if p and Path(p).is_file() and Path(p).stat().st_size > 0:
            return Path(p)
        sha = entry.get("sha256")
        if sha:
            return self.get_by_hash(sha)
        return None

    def verify_integrity(self, file_path: Path, expected_hash: str) -> bool:
        """Verifies that the file at file_path has the exact expected_hash."""
        if not file_path.exists() or not expected_hash:
            return False
        computed = self.compute_sha256(file_path)
        return computed.lower() == expected_hash.strip().lower()

    def put(
        self,
        url: str,
        data: bytes,
        ext: Optional[str] = None,
        mime_type: Optional[str] = None,
        expected_hash: Optional[str] = None,
    ) -> Tuple[Path, str]:
        """
        Atomically saves binary data into content-addressable cache.

        Args:
            url: Origin URL of the asset.
            data: Raw binary contents.
            ext: Optional file extension.
            mime_type: Optional MIME type for extension determination.
            expected_hash: Optional expected SHA-256 hash.

        Returns:
            Tuple of (Path to cached file, SHA-256 hex digest)

        Raises:
            MediaIntegrityError: If computed hash does not match expected_hash.
        """
        if not data:
            raise MediaCacheError("Cannot cache empty data.")

        computed_hash = self.compute_sha256(data)
        if expected_hash and computed_hash.lower() != expected_hash.strip().lower():
            raise MediaIntegrityError(
                f"Integrity check failed: expected {expected_hash}, computed {computed_hash}"
            )

        extension = self._normalize_ext(ext, mime_type)
        target_filename = f"{computed_hash}{extension}"
        target_path = self.blobs_dir / target_filename

        # If file already exists and is non-empty, update index and return
        if target_path.exists() and target_path.stat().st_size == len(data):
            self._index[url] = {
                "sha256": computed_hash,
                "path": str(target_path),
                "size_bytes": len(data),
                "mime_type": mime_type or "",
                "original_url": url,
            }
            self._save_index()
            return target_path, computed_hash

        # Atomic write
        tmp_path = self.blobs_dir / f"{target_filename}.tmp.{uuid.uuid4().hex}"
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            # Verify temporary file integrity before replacing
            if self.compute_sha256(tmp_path) != computed_hash:
                raise MediaIntegrityError("Temporary file write failed hash verification.")
            tmp_path.replace(target_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

        self._index[url] = {
            "sha256": computed_hash,
            "path": str(target_path),
            "size_bytes": len(data),
            "mime_type": mime_type or "",
            "original_url": url,
        }
        self._save_index()
        logger.info(f"Cached asset [{computed_hash[:8]}] from {url} ({len(data)} bytes)")
        return target_path, computed_hash

    def put_file(
        self,
        url: str,
        source_path: Path,
        ext: Optional[str] = None,
        mime_type: Optional[str] = None,
        expected_hash: Optional[str] = None,
    ) -> Tuple[Path, str]:
        """
        Stores a file from a local source path into the content-addressable cache.
        """
        source_path = Path(source_path)
        if not source_path.exists() or source_path.stat().st_size == 0:
            raise MediaCacheError(f"Source file does not exist or is empty: {source_path}")

        computed_hash = self.compute_sha256(source_path)
        if expected_hash and computed_hash.lower() != expected_hash.strip().lower():
            raise MediaIntegrityError(
                f"Integrity check failed for {source_path}: expected {expected_hash}, got {computed_hash}"
            )

        if not ext and source_path.suffix and source_path.suffix.lower() not in (".tmp", ".temp", ".part", ".bin"):
            ext = source_path.suffix
        extension = self._normalize_ext(ext, mime_type)
        target_filename = f"{computed_hash}{extension}"
        target_path = self.blobs_dir / target_filename

        if target_path.exists() and target_path.stat().st_size == source_path.stat().st_size:
            self._index[url] = {
                "sha256": computed_hash,
                "path": str(target_path),
                "size_bytes": source_path.stat().st_size,
                "mime_type": mime_type or "",
                "original_url": url,
            }
            self._save_index()
            return target_path, computed_hash

        tmp_path = self.blobs_dir / f"{target_filename}.tmp.{uuid.uuid4().hex}"
        try:
            shutil.copyfile(source_path, tmp_path)
            tmp_path.replace(target_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass

        self._index[url] = {
            "sha256": computed_hash,
            "path": str(target_path),
            "size_bytes": target_path.stat().st_size,
            "mime_type": mime_type or "",
            "original_url": url,
        }
        self._save_index()
        return target_path, computed_hash

    def purge_corrupted(self) -> int:
        """Scans blobs directory and deletes any corrupted or zero-byte files."""
        purged = 0
        for blob in self.blobs_dir.glob("*"):
            if not blob.is_file():
                continue
            if blob.name.startswith("media_index") or ".tmp." in blob.name:
                continue
            expected_hash = blob.stem
            if blob.stat().st_size == 0:
                blob.unlink()
                purged += 1
                continue
            try:
                if len(expected_hash) == 64 and self.compute_sha256(blob) != expected_hash:
                    blob.unlink()
                    purged += 1
            except Exception:
                blob.unlink()
                purged += 1
        return purged

    def clear(self) -> None:
        """Purges all cached files and index (for tests/maintenance)."""
        self._index = {}
        self._save_index()
        if self.blobs_dir.exists():
            for f in self.blobs_dir.glob("*"):
                try:
                    if f.is_file():
                        f.unlink()
                except Exception:
                    pass
