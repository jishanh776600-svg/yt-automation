"""
Global Visual Memory & Asset Reuse Control Engine.
=================================================
Maintains persistent visual asset memory across all produced Shorts to strictly
prevent exact duplicates, perceptual near-duplicates, and excessive visual repetition.

Capabilities:
  1. Exact Hash (SHA-256) tracking.
  2. Perceptual Difference Hash (dHash 64-bit) near-duplicate detection.
  3. Cooldown & Recency Penalties: Rejects assets used within COOLDOWN_DAYS (default 14 days).
  4. Per-Short Uniqueness: Enforces that every scene in a Short uses a distinct visual asset.
"""

import hashlib
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from PIL import Image

logger = logging.getLogger("alamr.visual_memory")

DEFAULT_DB_PATH = Path("data/database/visual_memory.db")
COOLDOWN_DAYS = 14
MAX_HAMMING_DISTANCE = 5  # Difference <= 5 bits out of 64 means perceptually identical


def compute_exact_hash(file_path: Path) -> str:
    """Computes SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def compute_dhash(image_path: Path) -> str:
    """
    Computes 64-bit difference hash (dHash) for an image.
    Resizes to 9x8 grayscale, compares horizontal adjacent pixels, and returns 16-hex string.
    """
    try:
        with Image.open(image_path) as img:
            gray = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())

            bits = []
            for row in range(8):
                row_start = row * 9
                for col in range(8):
                    left = pixels[row_start + col]
                    right = pixels[row_start + col + 1]
                    bits.append("1" if left > right else "0")
            bit_str = "".join(bits)
            return f"{int(bit_str, 2):016x}"
    except Exception as e:
        logger.debug(f"dHash computation notice for {image_path}: {e}")
        return hashlib.md5(str(image_path).encode("utf-8")).hexdigest()[:16]


def hamming_distance(hex1: str, hex2: str) -> int:
    """Computes Hamming distance (differing bit count) between two 16-char hex hashes."""
    try:
        val1 = int(hex1, 16)
        val2 = int(hex2, 16)
        return bin(val1 ^ val2).count("1")
    except Exception:
        return 64


@dataclass
class VisualAssetMemoryRecord:
    asset_id: str
    source: str
    exact_hash: str
    perceptual_hash: str
    subjects: List[str]
    category: str
    story_id: str
    first_used_at: str
    last_used_at: str
    usage_count: int
    recent_shorts: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GlobalVisualMemory:
    """
    Persistent registry enforcing visual diversity and blocking duplicate imagery.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS visual_asset_memory (
                    asset_id TEXT PRIMARY KEY,
                    source TEXT,
                    exact_hash TEXT,
                    perceptual_hash TEXT,
                    subjects_json TEXT,
                    category TEXT,
                    story_id TEXT,
                    first_used_at TEXT,
                    last_used_at TEXT,
                    usage_count INTEGER DEFAULT 1,
                    recent_shorts_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vam_exact ON visual_asset_memory(exact_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vam_phash ON visual_asset_memory(perceptual_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_vam_last_used ON visual_asset_memory(last_used_at)")
            conn.commit()

    def check_asset_reuse(
        self,
        asset_path: Path,
        current_short_id: str = "",
        cooldown_days: int = COOLDOWN_DAYS,
    ) -> Tuple[bool, str, float]:
        """
        Evaluates whether an asset is permitted for use in a new Short.
        Returns: (is_permitted, reason, penalty_score)
        where penalty_score ranges 0.0 (perfectly fresh) to 1.0 (blocked duplicate).
        """
        asset_path = Path(asset_path)
        if not asset_path.exists():
            return False, "Asset file does not exist on disk", 1.0

        exact_h = compute_exact_hash(asset_path)
        p_hash = compute_dhash(asset_path)
        now = datetime.now(timezone.utc)
        cooldown_cutoff = (now - timedelta(days=cooldown_days)).isoformat()

        with self._get_conn() as conn:
            # 1. Exact Hash Check
            row_exact = conn.execute(
                "SELECT * FROM visual_asset_memory WHERE exact_hash = ?", (exact_h,)
            ).fetchone()

            if row_exact:
                last_used = row_exact["last_used_at"]
                recent_shorts = json.loads(row_exact["recent_shorts_json"] or "[]")
                if current_short_id and current_short_id in recent_shorts:
                    return False, f"Exact duplicate already used in current Short {current_short_id}", 1.0
                if last_used > cooldown_cutoff:
                    return False, f"Exact duplicate used recently ({last_used}) in Short {recent_shorts[-1] if recent_shorts else 'prior'}", 1.0

            # 2. Perceptual Hash (dHash) Check
            cursor = conn.execute(
                "SELECT asset_id, perceptual_hash, last_used_at, recent_shorts_json FROM visual_asset_memory WHERE last_used_at > ?",
                (cooldown_cutoff,)
            )
            for row in cursor.fetchall():
                prior_phash = row["perceptual_hash"]
                dist = hamming_distance(p_hash, prior_phash)
                if dist <= MAX_HAMMING_DISTANCE:
                    prior_shorts = json.loads(row["recent_shorts_json"] or "[]")
                    return (
                        False,
                        f"Perceptual near-duplicate (dHash distance {dist} <= {MAX_HAMMING_DISTANCE}) "
                        f"matches {row['asset_id']} used in {prior_shorts[-1] if prior_shorts else 'prior Short'}",
                        1.0
                    )

        return True, "Fresh asset, passed memory verification", 0.0

    def record_asset_usage(
        self,
        asset_id: str,
        asset_path: Path,
        short_id: str,
        source: str = "Pexels",
        subjects: Optional[List[str]] = None,
        category: str = "Mystery",
        story_id: str = "",
    ) -> VisualAssetMemoryRecord:
        """
        Records or updates asset usage in the persistent memory registry.
        """
        asset_path = Path(asset_path)
        exact_h = compute_exact_hash(asset_path) if asset_path.exists() else ""
        p_hash = compute_dhash(asset_path) if asset_path.exists() else ""
        now_str = datetime.now(timezone.utc).isoformat()
        subs = subjects or []

        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM visual_asset_memory WHERE asset_id = ? OR exact_hash = ?",
                (asset_id, exact_h)
            ).fetchone()

            if existing:
                count = existing["usage_count"] + 1
                recent_shorts = json.loads(existing["recent_shorts_json"] or "[]")
                if short_id and short_id not in recent_shorts:
                    recent_shorts.append(short_id)
                conn.execute("""
                    UPDATE visual_asset_memory
                    SET last_used_at = ?, usage_count = ?, recent_shorts_json = ?, exact_hash = ?, perceptual_hash = ?
                    WHERE asset_id = ?
                """, (now_str, count, json.dumps(recent_shorts), exact_h, p_hash, existing["asset_id"]))
                conn.commit()
                return VisualAssetMemoryRecord(
                    asset_id=existing["asset_id"],
                    source=source,
                    exact_hash=exact_h,
                    perceptual_hash=p_hash,
                    subjects=subs,
                    category=category,
                    story_id=story_id,
                    first_used_at=existing["first_used_at"],
                    last_used_at=now_str,
                    usage_count=count,
                    recent_shorts=recent_shorts,
                )
            else:
                recent_shorts = [short_id] if short_id else []
                conn.execute("""
                    INSERT INTO visual_asset_memory (
                        asset_id, source, exact_hash, perceptual_hash, subjects_json,
                        category, story_id, first_used_at, last_used_at, usage_count, recent_shorts_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    asset_id, source, exact_h, p_hash, json.dumps(subs),
                    category, story_id, now_str, now_str, 1, json.dumps(recent_shorts)
                ))
                conn.commit()
                return VisualAssetMemoryRecord(
                    asset_id=asset_id,
                    source=source,
                    exact_hash=exact_h,
                    perceptual_hash=p_hash,
                    subjects=subs,
                    category=category,
                    story_id=story_id,
                    first_used_at=now_str,
                    last_used_at=now_str,
                    usage_count=1,
                    recent_shorts=recent_shorts,
                )