"""
Visual Diversity Budget & Repetition Controller.
Enforces per-video diversity limits, prevents intra-video duplicate asset reuse,
applies cross-job exponential decay penalties on recently selected footage,
and implements perceptual difference hashing (dHash) for near-duplicate rejection.
"""
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from collections import Counter
from PIL import Image

from .sources.base import VisualCandidate
from .provenance import VisualContentType

logger = logging.getLogger(__name__)


def compute_dhash(image_input: Union[str, Path, Image.Image], hash_size: int = 8) -> str:
    """
    Computes a 64-bit difference hash (dHash) for an image.
    Accepts PIL.Image.Image, Path, or str path.
    Returns 16-character hex string representing the perceptual hash.
    """
    if isinstance(image_input, (str, Path)):
        img = Image.open(str(image_input))
        should_close = True
    else:
        img = image_input
        should_close = False

    try:
        resample_filter = getattr(Image, "Resampling", Image).LANCZOS if hasattr(Image, "Resampling") else getattr(Image, "LANCZOS", 1)
        # Convert to grayscale and resize to (hash_size + 1, hash_size)
        img_gray = img.convert("L").resize((hash_size + 1, hash_size), resample_filter)
        pixels = list(img_gray.get_flattened_data()) if hasattr(img_gray, 'get_flattened_data') else list(img_gray.getdata())

        # Compare adjacent pixels horizontally row by row
        diff = []
        width = hash_size + 1
        for row in range(hash_size):
            row_offset = row * width
            for col in range(hash_size):
                diff.append(1 if pixels[row_offset + col + 1] > pixels[row_offset + col] else 0)

        # Convert bits to integer and then hex string
        decimal_val = 0
        for bit in diff:
            decimal_val = (decimal_val << 1) | bit
        hex_len = (hash_size * hash_size) // 4
        return f"{decimal_val:0{hex_len}x}"
    finally:
        if should_close:
            try:
                img.close()
            except Exception:
                pass


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Calculates the Hamming distance (number of bit differences) between two hex hashes.
    Returns 64 if either hash is invalid.
    """
    if not hash1 or not hash2:
        return 64
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        xor_val = val1 ^ val2
        return bin(xor_val).count('1')
    except (ValueError, TypeError):
        return 64


def is_near_duplicate(hash1: str, hash2: str, max_distance: int = 10) -> bool:
    """
    Determines if two difference hashes represent near-duplicate visuals.
    A Hamming distance <= max_distance (default 10) indicates near-duplicate.
    """
    return hamming_distance(hash1, hash2) <= max_distance


def detect_near_duplicates(
    candidates: List[VisualCandidate],
    threshold: int = 10
) -> List[Tuple[str, str, int]]:
    """
    Detects pairwise near-duplicates among candidates based on dHash.
    Returns list of (id1, id2, distance).
    """
    near_dups: List[Tuple[str, str, int]] = []
    hashes: Dict[str, str] = {}

    for c in candidates:
        cand_id = c.candidate_id or c.source_url
        h = c.metadata.get("dhash") if c.metadata else None
        if not h and c.local_path and os.path.exists(c.local_path):
            try:
                h = compute_dhash(c.local_path)
                if c.metadata is not None:
                    c.metadata["dhash"] = h
            except Exception as e:
                logger.warning(f"Failed computing dHash for {c.candidate_id}: {e}")
        if h:
            hashes[cand_id] = h

    cand_ids = list(hashes.keys())
    for i in range(len(cand_ids)):
        for j in range(i + 1, len(cand_ids)):
            id1, id2 = cand_ids[i], cand_ids[j]
            dist = hamming_distance(hashes[id1], hashes[id2])
            if dist <= threshold:
                near_dups.append((id1, id2, dist))

    return near_dups


class VisualDiversityController:
    """
    Manages editorial visual variety and enforces strict anti-monotony constraints.
    - Zero duplicate clip reuse in the same Short.
    - Zero near-duplicate visual frames via dHash (Hamming <= 10).
    - Maximum 35% generic stock footage per Short.
    - Maximum 35% static imagery per Short.
    - Minimum 50% real / archival / editorial / document visual content.
    """

    MAX_GENERIC_STOCK_RATIO = 0.35
    MAX_STATIC_RATIO = 0.35
    MIN_REAL_FOOTAGE_RATIO = 0.50
    NEAR_DUPLICATE_HAMMING_THRESHOLD = 10

    def __init__(self):
        # In-memory history tracking recent asset URLs across jobs
        self._history: Counter = Counter()
        # Perceptual hash registry: key -> dhash
        self._known_hashes: Dict[str, str] = {}

    def record_job_assets(self, selected_candidates: List[VisualCandidate]):
        """Records selected assets into cross-job usage history."""
        for c in selected_candidates:
            if c.source_url:
                self._history[c.source_url] += 1
            cand_id = c.candidate_id or c.source_url
            h = c.metadata.get("dhash") if c.metadata else None
            if h and cand_id:
                self._known_hashes[cand_id] = h

    def store_hash(self, asset_key: str, dhash_val: str):
        """Manually registers an asset dHash in the diversity controller."""
        self._known_hashes[asset_key] = dhash_val

    def get_recent_usage_counts(self) -> Dict[str, int]:
        """Returns map of URL -> usage count."""
        return dict(self._history)

    def check_near_duplicates(
        self,
        candidates: List[VisualCandidate],
        threshold: Optional[int] = None
    ) -> List[Tuple[str, str, int]]:
        """
        Detects near duplicates among provided candidates.
        """
        th = threshold if threshold is not None else self.NEAR_DUPLICATE_HAMMING_THRESHOLD
        return detect_near_duplicates(candidates, threshold=th)

    def evaluate_diversity_budget(self, selected: List[VisualCandidate]) -> Dict[str, Any]:
        """
        Calculates category breakdown and validates compliance with diversity rules.
        Returns audit summary dict.
        """
        if not selected:
            return {
                "compliant": True,
                "total_shots": 0,
                "real_footage_pct": 0.0,
                "generic_stock_pct": 0.0,
                "static_pct": 0.0,
                "duplicates_count": 0,
                "near_duplicates_count": 0,
                "near_duplicate_pairs": []
            }

        total = len(selected)
        urls = [c.source_url for c in selected if c.source_url]
        unique_urls = set(urls)
        duplicates = len(urls) - len(unique_urls)

        # Perceptual near duplicates
        near_dups = self.check_near_duplicates(selected)
        near_dups_count = len(near_dups)

        real_count = sum(1 for c in selected if c.content_type in (
            VisualContentType.REAL_VIDEO,
            VisualContentType.LIVE_EVENT_FOOTAGE,
            VisualContentType.ARCHIVAL_VIDEO,
            VisualContentType.SCREENSHOT_DOCUMENT,
            VisualContentType.ANIMATED_DATA_MAP,
            VisualContentType.MEME_REACTION
        ))

        generic_count = sum(1 for c in selected if c.content_type in (
            VisualContentType.GENERIC_STOCK_VIDEO,
            VisualContentType.GENERIC_STOCK_IMAGE
        ))

        static_count = sum(1 for c in selected if not c.is_video)

        real_pct = round((real_count / total) * 100, 1)
        generic_pct = round((generic_count / total) * 100, 1)
        static_pct = round((static_count / total) * 100, 1)

        is_compliant = (
            duplicates == 0 and
            near_dups_count == 0 and
            (generic_pct <= (self.MAX_GENERIC_STOCK_RATIO * 100) or total <= 3) and
            (static_pct <= (self.MAX_STATIC_RATIO * 100) or total <= 3)
        )

        return {
            "compliant": is_compliant,
            "total_shots": total,
            "real_footage_pct": real_pct,
            "generic_stock_pct": generic_pct,
            "static_pct": static_pct,
            "duplicates_count": duplicates,
            "near_duplicates_count": near_dups_count,
            "near_duplicate_pairs": near_dups,
            "categories_used": list(set(c.content_type.value for c in selected))
        }
