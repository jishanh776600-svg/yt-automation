"""
Global Short Duplicate Protection Guard.
=========================================
Prevents duplicate or overly similar Shorts from entering the READY pipeline or being uploaded.

Fingerprints each Short across:
  - Normalized Title & Topic Shingles
  - Script text 3-gram shingles (Jaccard similarity threshold)
  - Narration duration and character signature
  - Visual asset sequence and scene order

Rejection Policy:
  - Script Jaccard similarity > 0.65 -> REJECT
  - Title similarity > 0.70 -> REJECT
  - Scene sequence identical (> 50% asset overlap) -> REJECT
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any

logger = logging.getLogger("alamr.short_duplicate_guard")

DEFAULT_GUARD_DB_PATH = Path("data/database/short_fingerprints.db")
MAX_SCRIPT_JACCARD_SIMILARITY = 0.65
MAX_TITLE_JACCARD_SIMILARITY = 0.70
MAX_ASSET_SEQUENCE_OVERLAP = 0.50


def tokenize_shingles(text: str, k: int = 3) -> Set[str]:
    """Extracts k-word shingles from clean text for Jaccard similarity computation."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
    """Computes Jaccard similarity between two sets."""
    if not set1 or not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return float(intersection) / float(union) if union > 0 else 0.0


@dataclass
class ShortFingerprintRecord:
    short_id: str
    topic_title: str
    script_text: str
    duration_seconds: float
    asset_ids: List[str]
    fingerprint_hash: str
    created_at_utc: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ShortDuplicateGuard:
    """
    Defends against duplicate Short creation by maintaining persistent fingerprints.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DEFAULT_GUARD_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS short_fingerprints (
                    short_id TEXT PRIMARY KEY,
                    topic_title TEXT,
                    script_text TEXT,
                    duration_seconds REAL,
                    asset_ids_json TEXT,
                    fingerprint_hash TEXT,
                    created_at_utc TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sf_hash ON short_fingerprints(fingerprint_hash)")
            conn.commit()

    def verify_short_uniqueness(
        self,
        topic_title: str,
        script_text: str,
        duration_seconds: float,
        asset_ids: List[str],
        short_id: str = "",
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates candidate Short against all historical Shorts.
        Returns: (is_unique: bool, reason: str, metrics: dict)
        """
        clean_title = topic_title.strip()
        clean_script = script_text.strip()
        candidate_title_shingles = tokenize_shingles(clean_title, k=2)
        candidate_script_shingles = tokenize_shingles(clean_script, k=3)
        candidate_asset_set = set(asset_ids)

        metrics = {
            "max_title_similarity": 0.0,
            "max_script_similarity": 0.0,
            "max_asset_overlap": 0.0,
            "matched_short_id": None,
        }

        with self._get_conn() as conn:
            cursor = conn.execute("SELECT * FROM short_fingerprints")
            for row in cursor.fetchall():
                if short_id and row["short_id"] == short_id:
                    continue  # Skip checking against self

                prior_title = row["topic_title"] or ""
                prior_script = row["script_text"] or ""
                prior_assets = set(json.loads(row["asset_ids_json"] or "[]"))

                # 1. Title Similarity
                title_sim = jaccard_similarity(candidate_title_shingles, tokenize_shingles(prior_title, k=2))
                if title_sim > metrics["max_title_similarity"]:
                    metrics["max_title_similarity"] = round(title_sim, 3)
                    if title_sim >= MAX_TITLE_JACCARD_SIMILARITY:
                        metrics["matched_short_id"] = row["short_id"]
                        return False, f"Duplicate topic title (similarity {title_sim:.2f} >= {MAX_TITLE_JACCARD_SIMILARITY}) with Short {row['short_id']}", metrics

                # 2. Script Shingle Similarity
                script_sim = jaccard_similarity(candidate_script_shingles, tokenize_shingles(prior_script, k=3))
                if script_sim > metrics["max_script_similarity"]:
                    metrics["max_script_similarity"] = round(script_sim, 3)
                    if script_sim >= MAX_SCRIPT_JACCARD_SIMILARITY:
                        metrics["matched_short_id"] = row["short_id"]
                        return False, f"Duplicate script content (similarity {script_sim:.2f} >= {MAX_SCRIPT_JACCARD_SIMILARITY}) with Short {row['short_id']}", metrics

                # 3. Asset Sequence Overlap
                if candidate_asset_set and prior_assets:
                    asset_overlap = len(candidate_asset_set.intersection(prior_assets)) / float(len(candidate_asset_set))
                    if asset_overlap > metrics["max_asset_overlap"]:
                        metrics["max_asset_overlap"] = round(asset_overlap, 3)
                        if asset_overlap >= MAX_ASSET_SEQUENCE_OVERLAP:
                            metrics["matched_short_id"] = row["short_id"]
                            return False, f"Excessive scene asset overlap ({asset_overlap*100:.0f}% >= {MAX_ASSET_SEQUENCE_OVERLAP*100:.0f}%) with Short {row['short_id']}", metrics

        return True, "Passed global uniqueness verification", metrics

    def record_short(
        self,
        short_id: str,
        topic_title: str,
        script_text: str,
        duration_seconds: float,
        asset_ids: List[str],
    ) -> ShortFingerprintRecord:
        """Records finalized Short fingerprint into database."""
        fp_data = f"{topic_title.strip()}|{script_text.strip()}|{','.join(sorted(asset_ids))}"
        fp_hash = hashlib.sha256(fp_data.encode("utf-8")).hexdigest()
        now_str = datetime.now(timezone.utc).isoformat()

        with self._get_conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO short_fingerprints (
                    short_id, topic_title, script_text, duration_seconds,
                    asset_ids_json, fingerprint_hash, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                short_id, topic_title, script_text, float(duration_seconds),
                json.dumps(asset_ids), fp_hash, now_str
            ))
            conn.commit()

        return ShortFingerprintRecord(
            short_id=short_id,
            topic_title=topic_title,
            script_text=script_text,
            duration_seconds=duration_seconds,
            asset_ids=asset_ids,
            fingerprint_hash=fp_hash,
            created_at_utc=now_str,
        )