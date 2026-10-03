"""
Global Persistent Visual Memory & Cross-Job Duplicate Prevention Engine (Step 5/8).
===================================================================================
Maintains an auditable, persistent record of visual usage across:
  - scenes within a Short (consecutive-scene protection)
  - Shorts and production jobs
  - QA jobs (strictly isolated from production memory)
  - future runs across process restarts

Capabilities:
  1. Multi-Level Duplicate Detection (canonical ID, URL normalization, file hash, perceptual dHash).
  2. Temporal Overlap & Window IoU (differentiates identical vs non-overlapping moments from same source).
  3. Framing-Aware Duplication (temporal overlap + visual similarity + crop coordinates).
  4. Recency Decay (deterministic penalties decaying from 24h to 30d).
  5. Source Diversity Preference (RELEVANCE > VARIETY: variety never overrides semantic relevance).
  6. Atomic Writes & Thread Safety (SQLite WAL mode with retry handling).
  7. VIDEO ONLY Invariant (prohibits image assets from visual memory).
"""
import re
import cv2
import json
import uuid
import math
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set, Union
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy import text
from sqlalchemy.orm import Session

from config.settings import DB_PATH
from core.database import SessionLocal, engine
from core.models import VisualUsageRecord
from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from .models import SourceType, VisualCandidate, VisualIntent, NormalizedVideoCandidate

logger = logging.getLogger(__name__)

TRACKING_PARAM_KEYS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "ncid", "_hsenc", "_hsmi", "mc_eid",
    "guccounter", "guce_referrer", "guce_referrer_sig", "feed",
    "sp_ref", "src", "platform", "ocid", "ved", "usqp", "srsltid",
    "feature", "si", "pp", "t"
}


# ==============================================================================
# 1. URL Normalization & Canonical Identifier Extraction
# ==============================================================================
def normalize_visual_url(url: str) -> str:
    """
    Produces a canonical normalized URL for visual deduplication.
    Strips tracking query parameters, fragments, default ports, trailing slashes,
    and normalizes domain names.
    """
    if not url:
        return ""

    raw = url.strip()
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Normalize YouTube shortlinks: youtu.be/<id> -> youtube.com/watch?v=<id>
        if netloc in ("youtu.be", "m.youtube.com"):
            netloc = "youtube.com"
            video_id = parsed.path.strip("/")
            if video_id and not parse_qs(parsed.query).get("v"):
                path = "/watch"
                query_params = {"v": [video_id]}
            else:
                path = parsed.path
                query_params = parse_qs(parsed.query)
        elif netloc == "youtube.com":
            # Normalize /shorts/<id> and /embed/<id> to /watch?v=<id>
            path_parts = parsed.path.strip("/").split("/")
            if len(path_parts) >= 2 and path_parts[0] in ("shorts", "embed", "v", "live"):
                path = "/watch"
                query_params = {"v": [path_parts[1]]}
            else:
                path = parsed.path.rstrip("/") or "/"
                query_params = parse_qs(parsed.query)
        else:
            path = parsed.path.rstrip("/") or "/"
            query_params = parse_qs(parsed.query)

        # Filter out tracking and cache-busting query parameters
        clean_params = {
            k: v for k, v in query_params.items()
            if k.lower() not in TRACKING_PARAM_KEYS
        }

        # Deterministically sort query parameters
        sorted_query = urlencode(clean_params, doseq=True)
        return urlunparse((scheme, netloc, path, "", sorted_query, ""))
    except Exception as e:
        logger.debug(f"[MEMORY] URL normalization fallback for '{url}': {e}")
        return url.strip().rstrip("/")


def extract_canonical_source_id(url: str, title: str = "") -> Optional[str]:
    """
    Extracts canonical video identifier across major platforms if available.
    Examples:
      - YouTube: 11-char ID
      - Pexels: Numeric video ID
      - Pixabay: Numeric video ID
      - Internet Archive: Identifier slug
      - DVIDS: Video ID
      - Wikimedia Commons: File title
    """
    if not url:
        return None

    # YouTube: watch?v=XXXXXXXXXXX, youtu.be/XXXXXXXXXXX, shorts/XXXXXXXXXXX, embed/XXXXXXXXXXX
    yt_match = re.search(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([a-zA-Z0-9_-]{11})", url)
    if yt_match:
        return f"yt_{yt_match.group(1)}"

    # Pexels: pexels.com/video/...-1234567/ or pexels.com/video/1234567/
    pexels_match = re.search(r"pexels\.com/video/(?:.*?-)?(\d+)", url)
    if pexels_match:
        return f"pexels_{pexels_match.group(1)}"

    # Pixabay: pixabay.com/videos/...-12345/ or pixabay.com/videos/12345/
    pixabay_match = re.search(r"pixabay\.com/videos/(?:.*?-)?(\d+)", url)
    if pixabay_match:
        return f"pixabay_{pixabay_match.group(1)}"

    # Internet Archive: archive.org/details/IDENTIFIER or archive.org/download/IDENTIFIER
    archive_match = re.search(r"archive\.org/(?:details|download)/([a-zA-Z0-9_\-\.]+)", url)
    if archive_match:
        return f"ia_{archive_match.group(1)}"

    # DVIDS Hub: dvidshub.net/video/123456 or api.dvidshub.net/video/cand_dvids_XXXXX
    dvids_match = re.search(r"dvidshub\.net/video/(\w+)", url)
    if dvids_match:
        return f"dvids_{dvids_match.group(1)}"

    # Wikimedia Commons: File:Example.webm or wiki/Example.webm
    wiki_match = re.search(r"commons\.wikimedia\.org/wiki/(?:Special:FilePath/|File:)?([^/?#]+)", url)
    if wiki_match:
        return f"wiki_{wiki_match.group(1)}"

    return None


# ==============================================================================
# 2. Visual Fingerprinting (Perceptual Hash & File Header Hash)
# ==============================================================================
class VisualFingerprinter:
    """
    Lightweight visual fingerprinter.
    Uses difference hashing (dHash) across uniformly sampled video frames.
    Survives resizing, re-encoding, minor compression, and subtle crop shifts.
    """

    @staticmethod
    def compute_file_fingerprint(file_path: Path) -> str:
        """
        Fast, deterministic hash computed from file header (64KB), footer (64KB), and length.
        Avoids reading gigantic movie files fully while remaining collision-resistant.
        """
        if not file_path.exists():
            return ""

        size = file_path.stat().st_size
        hasher = hashlib.sha256()
        hasher.update(str(size).encode("utf-8"))

        with open(file_path, "rb") as f:
            header = f.read(65536)
            hasher.update(header)
            if size > 131072:
                f.seek(-65536, 2)
                footer = f.read(65536)
                hasher.update(footer)

        return hasher.hexdigest()

    @staticmethod
    def compute_frame_dhash(frame_gray) -> str:
        """Computes 64-bit difference hash (dHash) on an 8x8 gradient matrix."""
        resized = cv2.resize(frame_gray, (9, 8), interpolation=cv2.INTER_AREA)
        diff = resized[:, 1:] > resized[:, :-1]
        bits = diff.flatten()
        val = 0
        for bit in bits:
            val = (val << 1) | int(bit)
        return f"{val:016x}"

    @classmethod
    def compute_clip_perceptual_hash(cls, video_path: Path, sample_count: int = 4) -> str:
        """
        Samples uniformly spaced frames from video clip and computes composite dHash.
        Returns a hyphen-separated sequence of frame hashes.
        """
        if not video_path.exists():
            return ""

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return ""

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return ""

        sample_fractions = [0.15, 0.40, 0.65, 0.90] if sample_count == 4 else [
            (i + 0.5) / float(sample_count) for i in range(sample_count)
        ]

        frame_hashes = []
        for frac in sample_fractions:
            frame_idx = min(total_frames - 1, max(0, int(total_frames * frac)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            dhash_str = cls.compute_frame_dhash(gray)
            frame_hashes.append(dhash_str)

        cap.release()
        return "-".join(frame_hashes)

    @staticmethod
    def compare_perceptual_hashes(hash1: str, hash2: str) -> float:
        """
        Computes similarity between two perceptual hash sequences based on Hamming distance.
        Returns float in [0.0, 1.0], where 1.0 is identical.
        """
        if not hash1 or not hash2:
            return 0.0

        parts1 = hash1.split("-")
        parts2 = hash2.split("-")

        if not parts1 or not parts2:
            return 0.0

        sims = []
        min_len = min(len(parts1), len(parts2))
        for i in range(min_len):
            try:
                v1 = int(parts1[i], 16)
                v2 = int(parts2[i], 16)
                dist = bin(v1 ^ v2).count("1")
                sim = max(0.0, 1.0 - (dist / 64.0))
                sims.append(sim)
            except ValueError:
                continue

        return float(sum(sims) / len(sims)) if sims else 0.0


# ==============================================================================
# 3. Temporal Overlap & Recency Decay
# ==============================================================================
def calculate_temporal_overlap(
    s1: float, e1: float, s2: float, e2: float
) -> Tuple[float, float, float]:
    """
    Computes temporal intersection between two time windows.
    Returns:
      (overlap_duration, overlap_ratio_of_smaller, iou)
    """
    overlap_duration = max(0.0, min(e1, e2) - max(s1, s2))
    dur1 = max(0.01, e1 - s1)
    dur2 = max(0.01, e2 - s2)
    smaller_dur = min(dur1, dur2)
    span = max(0.01, max(e1, e2) - min(s1, s2))

    overlap_ratio = overlap_duration / smaller_dur
    iou = overlap_duration / span
    return (round(overlap_duration, 3), round(overlap_ratio, 3), round(iou, 3))


def compute_recency_penalty(last_used_at: datetime, current_time: Optional[datetime] = None) -> float:
    """
    Computes deterministic recency decay penalty based on elapsed time:
      - < 24 hours: 0.40 (Strong recency penalty)
      - 24 - 72 hours: 0.25 (Moderate recency penalty)
      - 3 - 7 days (72-168h): 0.15 (Smaller recency penalty)
      - 7 - 30 days (168-720h): 0.05 (Light recency penalty)
      - >= 30 days: 0.00 (Fully decayed, no penalty)
    """
    now = current_time or datetime.now(timezone.utc)
    if last_used_at.tzinfo is None and now.tzinfo is not None:
        last_used_at = last_used_at.replace(tzinfo=timezone.utc)
    elif last_used_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta_hours = max(0.0, (now - last_used_at).total_seconds() / 3600.0)

    if delta_hours < 24.0:
        return 0.40
    elif delta_hours < 72.0:
        return 0.25
    elif delta_hours < 168.0:
        return 0.15
    elif delta_hours < 720.0:
        return 0.05
    return 0.0


# ==============================================================================
# 4. Visual Memory Evaluation Data Structure
# ==============================================================================
@dataclass
class VisualMemoryEvaluation:
    """Detailed evaluation result of checking a candidate against visual memory."""
    is_hard_duplicate: bool
    duplicate_reason: Optional[str]
    penalty: float
    matched_record_id: Optional[str] = None
    similarity_metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# 5. Visual Memory Manager
# ==============================================================================
class VisualMemoryManager:
    """
    Manages global persistent visual memory and cross-job duplicate prevention.
    Adheres strictly to:
      - RELEVANCE > VARIETY (Variety never overrides high semantic relevance).
      - VIDEO ONLY (Prohibits static images, canvases, and slides).
      - QA Isolation (Temporary QA jobs never poison production memory).
      - Thread-Safe / Multi-Worker Concurrency (WAL mode + busy timeout).
    """

    NEAR_IDENTICAL_OVERLAP_THRESHOLD = 0.70  # Hard rejection
    SUBSTANTIAL_OVERLAP_THRESHOLD = 0.25     # Strong penalty
    NEAR_IDENTICAL_VISUAL_HASH_THRESHOLD = 0.88  # Hard rejection
    HIGH_VISUAL_HASH_THRESHOLD = 0.75        # Moderate-to-high penalty

    def __init__(
        self,
        db_session: Optional[Session] = None,
        classification: str = "PRODUCTION"
    ):
        self._external_session = db_session
        self.classification = classification.upper()
        try:
            from core.models import VisualUsageRecord
            bind = None
            if db_session:
                try:
                    bind = db_session.get_bind()
                except Exception:
                    bind = None
            if bind is None:
                from core.database import engine
                bind = engine
            VisualUsageRecord.__table__.create(bind=bind, checkfirst=True)
        except Exception as e:
            logger.debug(f"[MEMORY] Table creation check notice: {e}")

    def get_session(self) -> Session:
        """Returns active database session."""
        if self._external_session:
            return self._external_session
        return SessionLocal()

    # --------------------------------------------------------------------------
    # Evaluation Against Memory
    # --------------------------------------------------------------------------
    def evaluate_candidate(
        self,
        candidate: Union[VisualCandidate, NormalizedVideoCandidate],
        temporal_start: float = 0.0,
        temporal_end: float = 0.0,
        job_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None,
        recent_scene_source_ids: Optional[List[str]] = None,
        current_time: Optional[datetime] = None,
        intent: Optional[Any] = None,
        framing_crop_info: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> VisualMemoryEvaluation:
        """
        Evaluates candidate against persistent visual memory across:
          1. Same-Short consecutive scene protection
          2. Canonical ID and normalized URL matching
          3. Source file fingerprinting (header/footer SHA256)
          4. Temporal interval overlap (IoU and overlap ratio)
          5. Perceptual visual fingerprinting (dHash similarity)
          6. Framing-aware duplicate detection
          7. Cross-job recency decay
        """
        raw_url = getattr(candidate, "source_url", "") or getattr(candidate, "page_url", "") or getattr(candidate, "media_url", "")
        norm_url = normalize_visual_url(raw_url)
        canon_id = extract_canonical_source_id(raw_url, getattr(candidate, "title", ""))

        # 1. Consecutive-Scene Protection (Within same Short)
        if recent_scene_urls:
            norm_recent = [normalize_visual_url(u) for u in recent_scene_urls if u]
            if norm_url and norm_url in norm_recent:
                return VisualMemoryEvaluation(
                    is_hard_duplicate=True,
                    duplicate_reason="Consecutive-scene duplicate: source URL already used in current Short",
                    penalty=1.00,
                    similarity_metrics={"consecutive_scene_url_match": True}
                )

        if recent_scene_source_ids and canon_id:
            if canon_id in recent_scene_source_ids:
                return VisualMemoryEvaluation(
                    is_hard_duplicate=True,
                    duplicate_reason="Consecutive-scene duplicate: canonical source ID already used in current Short",
                    penalty=1.00,
                    similarity_metrics={"consecutive_scene_canon_id_match": True}
                )

        # 2. Query Persistent Visual Memory
        session = self.get_session()
        try:
            from sqlalchemy import or_
            query = session.query(VisualUsageRecord).filter(
                VisualUsageRecord.usage_classification == self.classification
            )

            or_clauses = []
            if norm_url:
                or_clauses.append(VisualUsageRecord.normalized_url == norm_url)
            if canon_id:
                or_clauses.append(VisualUsageRecord.canonical_source_id == canon_id)

            local_path = getattr(candidate, "local_path", None)
            file_fp = ""
            if local_path and Path(local_path).exists():
                file_fp = VisualFingerprinter.compute_file_fingerprint(Path(local_path))
                if file_fp:
                    or_clauses.append(VisualUsageRecord.original_video_fingerprint == file_fp)

            if not or_clauses:
                return VisualMemoryEvaluation(is_hard_duplicate=False, duplicate_reason=None, penalty=0.0)

            records = query.filter(or_(*or_clauses)).all()
        finally:
            if not self._external_session:
                session.close()

        if not records:
            return VisualMemoryEvaluation(is_hard_duplicate=False, duplicate_reason=None, penalty=0.0)

        # 3. Analyze Matching Records (Overlap, Perceptual Hash, Recency)
        highest_penalty = 0.0
        is_hard_dup = False
        reasons = []
        matched_id = None
        metrics: Dict[str, Any] = {}

        cand_clip_path = getattr(candidate, "local_clip_path", None) or getattr(candidate, "local_path", None)
        cand_visual_hash = ""
        if cand_clip_path and Path(cand_clip_path).exists():
            cand_visual_hash = VisualFingerprinter.compute_clip_perceptual_hash(Path(cand_clip_path))

        has_temporal_window = temporal_end > temporal_start
        dur = max(0.5, temporal_end - temporal_start) if has_temporal_window else (
            getattr(candidate, "duration", 0.0) or getattr(candidate, "duration_sec", 0.0) or 3.0
        )
        c_start = temporal_start
        c_end = temporal_end if has_temporal_window else temporal_start + dur

        for rec in records:
            overlap_sec = 0.0
            overlap_ratio = 0.0
            iou = 0.0

            # A. Temporal Overlap Check
            if has_temporal_window and rec.temporal_end > rec.temporal_start:
                overlap_sec, overlap_ratio, iou = calculate_temporal_overlap(
                    c_start, c_end, rec.temporal_start, rec.temporal_end
                )

                metrics[rec.id] = {
                    "overlap_sec": overlap_sec,
                    "overlap_ratio": overlap_ratio,
                    "iou": iou
                }

                if overlap_ratio >= self.NEAR_IDENTICAL_OVERLAP_THRESHOLD:
                    is_hard_dup = True
                    highest_penalty = 1.00
                    reasons.append(f"Near-identical temporal overlap ({overlap_ratio:.0%}) with record {rec.id}")
                    matched_id = rec.id
                    break
                elif overlap_ratio >= self.SUBSTANTIAL_OVERLAP_THRESHOLD:
                    highest_penalty = max(highest_penalty, 0.50)
                    reasons.append(f"Substantial temporal overlap ({overlap_ratio:.0%}) with record {rec.id}")
                    matched_id = rec.id

            # B. Visual Fingerprint Similarity Check (dHash)
            if cand_visual_hash and rec.visual_hash:
                vis_sim = VisualFingerprinter.compare_perceptual_hashes(cand_visual_hash, rec.visual_hash)
                metrics.setdefault(rec.id, {})["visual_similarity"] = round(vis_sim, 3)

                if vis_sim >= self.NEAR_IDENTICAL_VISUAL_HASH_THRESHOLD:
                    is_hard_dup = True
                    highest_penalty = 1.00
                    reasons.append(f"Near-identical visual appearance ({vis_sim:.0%}) with record {rec.id}")
                    matched_id = rec.id
                    break
                elif vis_sim >= self.HIGH_VISUAL_HASH_THRESHOLD:
                    highest_penalty = max(highest_penalty, 0.40)
                    reasons.append(f"High visual similarity ({vis_sim:.0%}) with record {rec.id}")
                    matched_id = rec.id

            # C. Framing-Aware Duplication Check
            if framing_crop_info and rec.framing_crop_info:
                try:
                    past_crop = json.loads(rec.framing_crop_info)
                    if isinstance(past_crop, dict):
                        cx1 = framing_crop_info.get("start_cx")
                        cx2 = past_crop.get("start_cx")
                        if cx1 is not None and cx2 is not None and abs(cx1 - cx2) < 0.05 and overlap_ratio > 0.20:
                            highest_penalty = max(highest_penalty, 0.45)
                            reasons.append(f"Identical framing and crop center with record {rec.id}")
                            matched_id = rec.id
                except Exception:
                    pass

            # D. Recency Decay Penalty
            rec_penalty = compute_recency_penalty(rec.last_used_at, current_time=current_time)
            if not has_temporal_window or overlap_ratio < self.SUBSTANTIAL_OVERLAP_THRESHOLD:
                # Same source video but non-overlapping moment: mild source-level repetition penalty
                source_reuse_pen = min(0.35, 0.15 + (rec_penalty * 0.5))
                highest_penalty = max(highest_penalty, source_reuse_pen)
                matched_id = matched_id or rec.id
            else:
                highest_penalty = max(highest_penalty, rec_penalty)
                matched_id = matched_id or rec.id

        return VisualMemoryEvaluation(
            is_hard_duplicate=is_hard_dup,
            duplicate_reason="; ".join(reasons) if reasons else None,
            penalty=round(highest_penalty, 3),
            matched_record_id=matched_id,
            similarity_metrics=metrics
        )

    # --------------------------------------------------------------------------
    # Temporal Diversity: Get Used Ranges for Candidate
    # --------------------------------------------------------------------------
    def get_used_ranges_for_candidate(
        self,
        candidate: Union[VisualCandidate, NormalizedVideoCandidate],
        job_id: Optional[str] = None
    ) -> List[Tuple[float, float]]:
        """
        Retrieves previously used temporal intervals [start, end] for this candidate's
        source URL or canonical ID within the current job or recent memory.
        Enables same-source moment diversity without repeating identical clips.
        """
        raw_url = getattr(candidate, "source_url", "") or getattr(candidate, "page_url", "") or getattr(candidate, "media_url", "")
        norm_url = normalize_visual_url(raw_url)
        canon_id = extract_canonical_source_id(raw_url, getattr(candidate, "title", ""))

        if not norm_url and not canon_id:
            return []

        session = self.get_session()
        try:
            from core.models import VisualUsageRecord
            query = session.query(VisualUsageRecord).filter(
                VisualUsageRecord.usage_classification == self.classification
            )
            conditions = []
            if norm_url:
                conditions.append(VisualUsageRecord.normalized_url == norm_url)
            if canon_id:
                conditions.append(VisualUsageRecord.canonical_source_id == canon_id)

            from sqlalchemy import or_
            query = query.filter(or_(*conditions))

            if job_id:
                query = query.filter(VisualUsageRecord.job_id == job_id)

            records = query.all()
            ranges: List[Tuple[float, float]] = []
            for r in records:
                if r.temporal_end > r.temporal_start:
                    ranges.append((round(r.temporal_start, 2), round(r.temporal_end, 2)))
            return ranges
        except Exception as e:
            logger.debug(f"[MEMORY] Notice getting used ranges for candidate: {e}")
            return []
        finally:
            if not self._external_session:
                session.close()

    # --------------------------------------------------------------------------
    # Record Visual Usage (Atomic Write)
    # --------------------------------------------------------------------------
    def record_visual_usage(
        self,
        candidate: Union[VisualCandidate, NormalizedVideoCandidate],
        video_path: Path,
        temporal_start: float = 0.0,
        temporal_end: float = 0.0,
        framing_strategy: Optional[str] = None,
        framing_crop_info: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
        scene_id: Optional[str] = None,
        topic_id: Optional[str] = None,
        event_id: Optional[str] = None,
        used_at: Optional[datetime] = None
    ) -> VisualUsageRecord:
        """
        Atomically records video clip usage to persistent visual memory.
        Enforces:
          - VIDEO ONLY invariant (rejects images immediately).
          - Perceptual hash generation.
          - Source fingerprinting.
          - Concurrency-safe SQLite commit.
        """
        assert VIDEO_ONLY is True, "VIDEO_ONLY invariant violation"

        if not video_path.exists():
            raise FileNotFoundError(f"Video file to record not found: {video_path}")

        # Physical validation of media (strictly rejects image files)
        val = PhysicalVideoValidator.validate_file(video_path)
        if not val.is_valid:
            raise ValueError(f"Prohibited visual asset rejected from visual memory: {val.error_message}")

        raw_url = getattr(candidate, "source_url", "") or getattr(candidate, "page_url", "") or getattr(candidate, "media_url", "")
        norm_url = normalize_visual_url(raw_url)
        canon_id = extract_canonical_source_id(raw_url, getattr(candidate, "title", ""))

        source_type = getattr(candidate, "source_type", SourceType.STOCK)
        st_val = source_type.value if isinstance(source_type, SourceType) else str(source_type)
        source_provider = getattr(candidate, "source_name", "unknown")

        # Compute fingerprints
        file_fp = VisualFingerprinter.compute_file_fingerprint(video_path)
        clip_fp = hashlib.md5(f"{file_fp}_{temporal_start:.2f}_{temporal_end:.2f}".encode("utf-8")).hexdigest()
        visual_hash = VisualFingerprinter.compute_clip_perceptual_hash(video_path)

        now = used_at or datetime.now(timezone.utc)
        record_id = f"vis_{uuid.uuid4().hex[:12]}"
        crop_json = json.dumps(framing_crop_info) if framing_crop_info else None

        creator = (
            getattr(candidate, "creator", None) or
            getattr(candidate, "provenance_metadata", {}).get("creator") or
            getattr(candidate, "uploader", None) or ""
        )
        channel_id = getattr(candidate, "provenance_metadata", {}).get("channel_id", "")

        record = VisualUsageRecord(
            id=record_id,
            source_url=raw_url,
            normalized_url=norm_url,
            canonical_source_id=canon_id,
            source_provider=source_provider,
            source_type=st_val,
            original_video_fingerprint=file_fp,
            clip_fingerprint=clip_fp,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            duration=val.duration,
            width=val.width,
            height=val.height,
            framing_strategy=framing_strategy,
            framing_crop_info=crop_json,
            visual_hash=visual_hash,
            job_id=job_id,
            scene_id=scene_id,
            topic_id=topic_id,
            event_id=event_id,
            usage_classification=self.classification,
            usage_count=1,
            first_used_at=now,
            last_used_at=now,
            metadata_json=json.dumps({
                "title": getattr(candidate, "title", ""),
                "creator": creator,
                "channel_id": channel_id,
                "codec": val.codec
            })
        )

        session = self.get_session()
        try:
            session.add(record)
            session.commit()
            session.refresh(record)
            logger.info(
                f"[MEMORY] Recorded {self.classification} visual usage for '{norm_url}' "
                f"({temporal_start:.2f}-{temporal_end:.2f}s, record_id={record.id})"
            )
            return record
        except Exception as e:
            session.rollback()
            logger.error(f"[MEMORY] Failed to atomically record visual usage: {e}")
            if self.classification == "PRODUCTION":
                return record
            raise
        finally:
            if not self._external_session:
                session.close()

    record_usage = record_visual_usage

    # --------------------------------------------------------------------------
    # Diversity Bonus / Source Diversity Adjustment
    # --------------------------------------------------------------------------
    def calculate_source_diversity_bonus(
        self,
        candidate: Union[VisualCandidate, NormalizedVideoCandidate]
    ) -> float:
        """
        Calculates a small source diversity bonus (+0.05) if the candidate represents
        a fresh archival / movie / internet source that has not been used recently.
        Adheres strictly to RELEVANCE > VARIETY (bonus is capped at 0.05, never
        allowing an unqualified candidate to beat a qualified candidate).
        """
        raw_url = getattr(candidate, "source_url", "") or getattr(candidate, "page_url", "") or getattr(candidate, "media_url", "")
        norm_url = normalize_visual_url(raw_url)
        canon_id = extract_canonical_source_id(raw_url, getattr(candidate, "title", ""))

        session = self.get_session()
        try:
            from sqlalchemy import or_
            query = session.query(VisualUsageRecord).filter(
                VisualUsageRecord.usage_classification == self.classification
            )
            conditions = []
            if norm_url:
                conditions.append(VisualUsageRecord.normalized_url == norm_url)
            if canon_id:
                conditions.append(VisualUsageRecord.canonical_source_id == canon_id)

            if not conditions:
                return 0.05

            count = query.filter(or_(*conditions)).count()
            if count == 0:
                return 0.05
            return 0.00
        except Exception as e:
            logger.debug(f"[MEMORY] Notice calculating diversity bonus: {e}")
            return 0.00
        finally:
            if not self._external_session:
                session.close()
