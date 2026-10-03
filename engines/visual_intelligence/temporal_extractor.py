"""
Temporal Moment Retrieval & Exact Clip Extraction Engine (Step 3/8).
====================================================================
Analyzes candidate video timelines in temporal windows, scores windows based on
action-aware semantic intent, motion dynamics, visual change, and anti-repetition,
and uses FFmpeg to accurately extract and physically validate sub-clips (2-4s)
for storyboard scene beats.

Core Invariants:
  - VIDEO ONLY: No static image conversion, zero JPG/PNG fallback.
  - Physical video validation on every extracted clip via FFprobe & OpenCV.
  - Action-aware preference (cannon firing vs stationary; miners fleeing vs equipment).
  - High motion alone does NOT guarantee selection without action relevance.
  - Repeated moment protection across scenes using the same source (used_ranges).
  - Step 2 physical quality and cleanliness validation (timecode, watermark, blur).
  - Fail-closed: Rejects candidate if no temporal moment meets quality/relevance threshold.
"""
import re
import math
import uuid
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set

from config.settings import FFMPEG_EXE, FFPROBE_EXE, ASSETS_DIR
from core.media_validator import PhysicalVideoValidator, VideoValidationResult
from .models import (
    NormalizedVideoCandidate, VisualCandidate, VisualIntent, TemporalWindow
)

logger = logging.getLogger(__name__)

TEMPORAL_CLIPS_CACHE_DIR = Path(ASSETS_DIR) / "temporal_clips"
TEMPORAL_CLIPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class TemporalMomentRetriever:
    """
    Deterministic Temporal Moment Retrieval and Sub-Clip Extraction Engine (Step 3/8).
    Discovers, scores, and extracts the most relevant moving moment from candidate footage.
    """

    DEFAULT_TARGET_CLIP_DURATION = 3.0
    MIN_CLIP_DURATION = 1.5
    MAX_CLIP_DURATION = 4.5
    DEFAULT_STRIDE = 1.5
    FAIL_CLOSED_SCORE_THRESHOLD = 0.35

    DYNAMIC_ACTION_KEYWORDS: Set[str] = {
        "fire", "firing", "blast", "explod", "explosion", "flee", "fled", "run", "running",
        "evacuat", "evacuation", "sink", "sinking", "rush", "rushing", "flood", "flooding",
        "whirlpool", "vortex", "struck", "strike", "collis", "collision", "crash", "erupt",
        "eruption", "protest", "clash", "storm", "waves", "charg", "charging", "launch",
        "launching", "burst", "shoot", "shooting", "attack", "march", "marching", "torpedo",
        "bomb", "bombing", "impact", "sail", "sailing", "swallow"
    }

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or TEMPORAL_CLIPS_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------------------
    # 1. Fast Single-Pass Video Timeline Profiling
    # --------------------------------------------------------------------------
    def profile_video_timeline(
        self,
        video_path: Path,
        max_samples: int = 120
    ) -> List[Dict[str, float]]:
        """
        Fast single-pass timeline profiling across source video.
        Samples frames at regular intervals downscaled to 320x180 to measure:
          - Inter-frame motion deltas Δ(t)
          - Laplacian sharpness σ²(t)
        Returns a time-indexed profile list: [{'time': t, 'motion': delta, 'sharpness': sharp}, ...]
        """
        p = Path(video_path)
        if not p.exists():
            return []

        try:
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(str(p))
            if not cap.isOpened():
                return []

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames <= 1:
                cap.release()
                return []

            duration = total_frames / fps
            step_sec = max(0.4, duration / max_samples)
            step_frames = max(1, int(step_sec * fps))

            profile: List[Dict[str, float]] = []
            prev_gray = None

            for frame_idx in range(0, total_frames, step_frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_AREA)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                motion_delta = 0.0
                if prev_gray is not None:
                    diff = cv2.absdiff(gray, prev_gray)
                    motion_delta = float(np.mean(diff))

                lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                curr_time = round(frame_idx / fps, 3)

                profile.append({
                    "time": curr_time,
                    "motion": round(motion_delta, 2),
                    "sharpness": round(lap_var, 1)
                })
                prev_gray = gray

            cap.release()

            if len(profile) > 1 and profile[0]["motion"] == 0.0:
                profile[0]["motion"] = profile[1]["motion"]

            return profile
        except Exception as e:
            logger.debug(f"[TEMPORAL] Timeline profiling notice for {p.name}: {e}")
            return []

    def detect_action_peaks(
        self,
        timeline_profile: List[Dict[str, float]],
        min_motion_threshold: float = 2.0
    ) -> List[float]:
        """
        Finds local motion maxima in the timeline profile that represent action peaks.
        Returns timestamps of prominent peaks sorted by motion intensity descending.
        """
        if not timeline_profile or len(timeline_profile) < 3:
            return []

        motions = [pt["motion"] for pt in timeline_profile]
        avg_motion = sum(motions) / len(motions)
        threshold = max(min_motion_threshold, avg_motion * 1.25)

        peaks = []
        for i in range(1, len(timeline_profile) - 1):
            m_curr = timeline_profile[i]["motion"]
            m_prev = timeline_profile[i - 1]["motion"]
            m_next = timeline_profile[i + 1]["motion"]

            if m_curr >= threshold and m_curr >= m_prev and m_curr >= m_next:
                peaks.append((timeline_profile[i]["time"], m_curr))

        peaks.sort(key=lambda x: x[1], reverse=True)
        return [p[0] for p in peaks[:8]]

    # --------------------------------------------------------------------------
    # 2. Cue and Action Annotation Detection
    # --------------------------------------------------------------------------
    def extract_temporal_cues(self, candidate: Any) -> List[Dict[str, Any]]:
        """
        Parses title, description, and metadata for timestamped events.
        E.g. 'collision at 0:25', 'explosion at 21.5s', chapter markers.
        """
        cues: List[Dict[str, Any]] = []

        # 1. Metadata annotations
        meta = getattr(candidate, "provenance_metadata", {}) or getattr(candidate, "metadata", {}) or {}
        if "action_moments" in meta and isinstance(meta["action_moments"], list):
            for m in meta["action_moments"]:
                if isinstance(m, dict) and "time" in m:
                    cues.append(m)

        # 2. Text timestamp patterns in title and description
        text = f"{getattr(candidate, 'title', '')} {getattr(candidate, 'description', '')}"

        # Pattern: 'at 21.5s' or 'at 21s' or 'at 21.5 sec'
        sec_matches = re.finditer(r'\bat\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\b', text, re.IGNORECASE)
        for sm in sec_matches:
            try:
                t = float(sm.group(1))
                cues.append({"time": t, "label": "text_timestamp"})
            except ValueError:
                pass

        # Pattern: '01:25' or '1:25'
        min_matches = re.finditer(r'\b(\d{1,2}):(\d{2})\b', text)
        for mm in min_matches:
            try:
                mins = int(mm.group(1))
                secs = int(mm.group(2))
                cues.append({"time": float(mins * 60 + secs), "label": "min_sec_timestamp"})
            except ValueError:
                pass

        return cues

    # --------------------------------------------------------------------------
    # 3. Before/After Context Window Construction
    # --------------------------------------------------------------------------
    def build_context_window(
        self,
        peak_timestamp: float,
        target_duration: float,
        source_duration: float,
        pre_roll_ratio: float = 0.35
    ) -> Tuple[float, float]:
        """
        Centers an action moment with pre-roll anticipation and post-roll aftermath.
        Guarantees bounds: 0.0 <= start < end <= source_duration.
        """
        dur = max(self.MIN_CLIP_DURATION, min(self.MAX_CLIP_DURATION, target_duration))
        if source_duration <= dur:
            return (0.0, round(source_duration, 3))

        pre_roll = dur * pre_roll_ratio
        start = max(0.0, peak_timestamp - pre_roll)
        end = min(source_duration, start + dur)

        if end == source_duration:
            start = max(0.0, source_duration - dur)

        return (round(start, 3), round(end, 3))

    # --------------------------------------------------------------------------
    # 4. Window Generation (Cues, Peaks, Intro-Bypass Sliding)
    # --------------------------------------------------------------------------
    def generate_candidate_windows(
        self,
        source_duration: float,
        target_duration: float = 3.0,
        stride: Optional[float] = None,
        timeline_profile: Optional[List[Dict[str, float]]] = None,
        cues: Optional[List[Dict[str, Any]]] = None
    ) -> List[Tuple[float, float]]:
        """
        Generates candidate temporal windows [start, end] across source video timeline:
          1. If source is short (<= target + 0.5s), returns full duration.
          2. Explicit cue-centered windows (metadata/title timestamps).
          3. Action peak-centered windows (optical/frame delta local maxima).
          4. Sliding windows with intro-bypass (t >= 2.0s on long videos, plus 0.0s baseline).
          5. Tail window to cover conclusion.
          6. Deduplicates overlapping windows within 0.5s start tolerance.
        """
        duration_target = max(self.MIN_CLIP_DURATION, min(self.MAX_CLIP_DURATION, float(target_duration)))
        step = stride if stride is not None else self.DEFAULT_STRIDE

        # Short source footage: use entire duration safely
        if source_duration <= duration_target + 0.5:
            return [(0.0, round(source_duration, 3))]

        windows: List[Tuple[float, float]] = []

        # A. Cue-centered windows
        if cues:
            for cue in cues:
                t_cue = cue.get("time", -1.0)
                if 0.0 <= t_cue <= source_duration:
                    w = self.build_context_window(
                        peak_timestamp=t_cue,
                        target_duration=duration_target,
                        source_duration=source_duration,
                        pre_roll_ratio=0.35
                    )
                    windows.append(w)

        # B. Action-peak centered windows
        if timeline_profile:
            peaks = self.detect_action_peaks(timeline_profile)
            for p_time in peaks:
                # Blackout intro action peaks (logos/title sequences) on long footage
                if source_duration >= 12.0 and p_time < 5.0 and not cues:
                    continue
                w = self.build_context_window(
                    peak_timestamp=p_time,
                    target_duration=duration_target,
                    source_duration=source_duration,
                    pre_roll_ratio=0.35
                )
                windows.append(w)

        # C. Sliding windows with Intro-Blackout (Skip 0-6s on third-party sources)
        if source_duration >= 12.0:
            curr = 6.0
        elif source_duration >= 8.0:
            curr = 3.0
        else:
            windows.append((0.0, round(duration_target, 3)))
            curr = step

        while curr + duration_target <= source_duration:
            windows.append((round(curr, 3), round(curr + duration_target, 3)))
            curr += step

        # D. Ensure tail window is represented
        tail_start = max(0.0, source_duration - duration_target)
        windows.append((round(tail_start, 3), round(source_duration, 3)))

        # Deduplicate windows starting within 0.5s of each other
        unique_windows: List[Tuple[float, float]] = []
        for w in windows:
            if not any(abs(w[0] - uw[0]) < 0.5 for uw in unique_windows):
                unique_windows.append(w)

        unique_windows.sort(key=lambda x: x[0])
        return unique_windows

    # --------------------------------------------------------------------------
    # 5. Motion, Context, and Stability Signal Analysis
    # --------------------------------------------------------------------------
    def analyze_window_profile(
        self,
        window: Tuple[float, float],
        timeline_profile: List[Dict[str, float]]
    ) -> Dict[str, float]:
        """
        Extracts temporal motion, sharpness, and context characteristics for a window
        directly from the fast timeline profile without spawning FFprobe.
        """
        w_start, w_end = window
        w_dur = max(0.1, w_end - w_start)

        samples = [
            pt for pt in timeline_profile
            if w_start <= pt["time"] <= w_end
        ]

        if not samples:
            return {
                "motion_score": 0.50,
                "visual_change": 0.50,
                "stability_score": 0.85,
                "context_score": 0.50,
                "is_frozen": False,
                "mean_sharpness": 150.0,
                "mean_motion": 5.0,
                "variance": 1.0,
                "peak_motion": 5.0,
                "peak_time": w_start + (w_dur * 0.5)
            }

        motions = [s["motion"] for s in samples]
        sharpnesses = [s["sharpness"] for s in samples]

        mean_motion = sum(motions) / len(motions)
        variance = math.sqrt(sum((m - mean_motion) ** 2 for m in motions) / len(motions)) if len(motions) > 1 else 0.0
        peak_sample = max(samples, key=lambda s: s["motion"])
        peak_motion = peak_sample["motion"]
        peak_time = peak_sample["time"]
        mean_sharpness = sum(sharpnesses) / len(sharpnesses)

        # Relative position of peak within window: [0.0, 1.0]
        rel_pos = (peak_time - w_start) / w_dur

        # Before / Action / After Context Score:
        # Ideal dynamic arc: peak occurs in interior (20% to 75% of window) and rises above baseline
        if len(samples) >= 3 and 0.20 <= rel_pos <= 0.75 and peak_motion >= 1.35 * max(0.1, samples[0]["motion"]):
            context_score = 1.00
        elif len(samples) >= 2 and 0.15 <= rel_pos <= 0.85 and peak_motion >= 1.20 * max(0.1, mean_motion):
            context_score = 0.80
        else:
            context_score = 0.50

        is_frozen = mean_motion < 1.0 and peak_motion < 1.8
        motion_score = round(min(1.0, max(0.10, 0.20 + (mean_motion / 15.0) * 0.80)), 3)
        visual_change = round(min(1.0, max(0.10, 0.20 + (variance / 8.0) * 0.80)), 3)
        stability_score = 0.90 if mean_sharpness >= 120.0 else 0.60

        return {
            "motion_score": motion_score,
            "visual_change": visual_change,
            "stability_score": stability_score,
            "context_score": round(context_score, 2),
            "is_frozen": is_frozen,
            "mean_sharpness": round(mean_sharpness, 1),
            "mean_motion": round(mean_motion, 2),
            "variance": round(variance, 2),
            "peak_motion": round(peak_motion, 2),
            "peak_time": round(peak_time, 2)
        }

    def analyze_window_motion(
        self,
        video_path: Path,
        start_time: float,
        end_time: float
    ) -> Dict[str, float]:
        """
        Analyzes motion density, visual activity, and stability for a temporal window via ffprobe.
        Used as a robust fallback when OpenCV timeline profiling is unavailable.
        """
        duration = max(0.1, end_time - start_time)
        result = {
            "motion_score": 0.50,
            "visual_change": 0.50,
            "stability_score": 0.85,
            "context_score": 0.50,
            "is_frozen": False,
            "mean_motion": 5.0
        }

        if not video_path.exists():
            return result

        try:
            cmd = [
                FFPROBE_EXE, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "packet=pts_time,size,flags",
                "-read_intervals", f"{start_time:.2f}%{end_time:.2f}",
                "-of", "csv=p=0",
                str(video_path)
            ]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4.0)
            lines = proc.stdout.strip().split("\n")
            sizes = []
            for line in lines:
                parts = line.strip().split(",")
                if len(parts) >= 2:
                    try:
                        sizes.append(int(parts[1]))
                    except (ValueError, IndexError):
                        pass

            if sizes:
                avg_size = sum(sizes) / len(sizes)
                if avg_size < 800 and max(sizes) < 1500:
                    result["motion_score"] = 0.15
                    result["visual_change"] = 0.10
                    result["is_frozen"] = True
                    result["mean_motion"] = 0.5
                else:
                    variance = math.sqrt(sum((s - avg_size) ** 2 for s in sizes) / len(sizes))
                    var_ratio = min(1.0, variance / max(1.0, avg_size))
                    result["motion_score"] = round(min(1.0, 0.35 + (var_ratio * 0.65)), 3)
                    result["visual_change"] = round(min(1.0, 0.30 + (var_ratio * 0.70)), 3)
                    result["mean_motion"] = 5.0 + (var_ratio * 10.0)

        except Exception as e:
            logger.debug(f"[TEMPORAL] Motion analysis probe notice for {video_path.name}: {e}")

        return result

    # --------------------------------------------------------------------------
    # 6. Action-Aware Temporal Window Scoring
    # --------------------------------------------------------------------------
    def score_temporal_window(
        self,
        window: Tuple[float, float],
        candidate: Any,
        intent: Optional[VisualIntent] = None,
        motion_signals: Optional[Dict[str, float]] = None,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        source_duration: float = 0.0
    ) -> TemporalWindow:
        """
        Computes composite temporal score combining:
          - Dynamic Action Relevance (cannon firing > museum cannon; fleeing > standing)
          - Motion density & activity
          - Before / Action / After Context Arc
          - Stability score
          - Anti-repetition penalty (used_ranges tracking)
          - Intro-bypass de-prioritization (never default to first seconds on long videos)
        """
        w_start, w_end = window
        w_dur = max(0.1, w_end - w_start)
        signals = motion_signals or {
            "motion_score": 0.50, "visual_change": 0.50, "stability_score": 0.85,
            "context_score": 0.50, "is_frozen": False, "mean_motion": 5.0
        }

        action_score = 0.50
        motion_score = signals.get("motion_score", 0.50)
        stability_score = signals.get("stability_score", 0.85)
        context_score = signals.get("context_score", 0.50)
        is_frozen = signals.get("is_frozen", False)
        mean_motion = signals.get("mean_motion", 5.0)
        matched_cues: List[str] = []

        # Check explicit timestamp cues from candidate
        cues = self.extract_temporal_cues(candidate)
        for cue in cues:
            cue_t = cue.get("time", -1.0)
            if w_start <= cue_t <= w_end:
                action_score = 1.00
                matched_cues.append(f"cue_at_{cue_t:.1f}s")

        # Dynamic Action-Aware Scoring from Scene Intent
        target_action = ""
        important_verbs = []
        if intent:
            target_action = getattr(intent, "visual_action", None) or intent.action or ""
            important_verbs = getattr(intent, "important_verbs", []) or []

        action_text = f"{target_action} {' '.join(important_verbs)}".lower()
        requires_dynamic_action = any(k in action_text for k in self.DYNAMIC_ACTION_KEYWORDS)

        if requires_dynamic_action:
            if is_frozen or motion_score < 0.22 or mean_motion < 1.5:
                # Contradictory static footage when dynamic action is requested
                # (Disqualifies stationary museum cannon, quiet lake, frozen scene)
                action_score = 0.08
                relevance_score = 0.15
                matched_cues.append("contradictory_static_penalty")
            elif action_score < 0.90:
                # Dynamic action score rewards real motion and context arc
                action_score = round(min(1.0, 0.35 + (motion_score * 0.40) + (context_score * 0.25)), 3)
                relevance_score = 0.85
            else:
                relevance_score = 0.90
        elif target_action:
            action_score = 0.75
            relevance_score = 0.75
        else:
            action_score = 0.50
            relevance_score = 0.50

        if matched_cues and not any("penalty" in c for c in matched_cues):
            relevance_score = 0.95

        # Intro Window De-prioritization / Blackout:
        # Never default to the first seconds on longer footage (bypasses title cards, logos, bumpers)
        intro_penalty = 0.0
        if w_start < 6.0 and source_duration >= 12.0 and not matched_cues:
            intro_penalty = 0.45
        elif w_start < 3.0 and source_duration >= 8.0 and not matched_cues:
            intro_penalty = 0.30
        elif w_start < 1.5 and not matched_cues:
            intro_penalty = 0.20

        # Repeated Moment Protection across scenes using the same source
        repetition_penalty = 0.0
        if used_ranges:
            for u_start, u_end in used_ranges:
                overlap = max(0.0, min(w_end, u_end) - max(w_start, u_start))
                if overlap > 0.3:
                    ov_ratio = overlap / w_dur
                    repetition_penalty = max(repetition_penalty, min(0.70, round(ov_ratio * 0.65, 3)))

        # Composite Score Calculation
        # Action relevance (0.35) and Motion (0.20) dominate over passive presence.
        composite = (
            0.35 * action_score +
            0.20 * motion_score +
            0.15 * context_score +
            0.15 * relevance_score +
            0.15 * stability_score -
            repetition_penalty -
            intro_penalty
        )
        composite_score = round(max(0.0, min(1.0, composite)), 4)

        return TemporalWindow(
            start_time=w_start,
            end_time=w_end,
            duration=w_dur,
            motion_score=motion_score,
            action_score=action_score,
            stability_score=stability_score,
            repetition_penalty=repetition_penalty,
            composite_score=composite_score,
            matched_cues=matched_cues,
            metadata={
                "is_frozen": is_frozen,
                "context_score": context_score,
                "intro_penalty": intro_penalty,
                "repetition_penalty": repetition_penalty
            }
        )

    # --------------------------------------------------------------------------
    # 7. Physical FFmpeg Sub-Clip Extraction with Step-2 Validation
    # --------------------------------------------------------------------------
    def extract_subclip(
        self,
        video_path: Path,
        start_time: float,
        duration: float,
        output_path: Optional[Path] = None,
        candidate: Optional[Any] = None
    ) -> Optional[Path]:
        """
        Extracts a high-precision sub-clip using FFmpeg.
        Enforces:
          - Video-only (no static image conversion)
          - Frame-accurate seek & extract
          - Step 2 physical quality and cleanliness validation:
            * Real pixel motion (not frozen)
            * No broadcast timecode (HH:MM:SS)
            * No persistent corner watermark/bugs
            * Sharpness threshold (calibrated for macro/archival)
            * Monochrome whiplash classification
        """
        if not video_path.exists():
            logger.warning(f"[TEMPORAL] Input video does not exist: {video_path}")
            return None

        # Reject image files disguised as input
        if not PhysicalVideoValidator.is_valid_video(video_path):
            logger.warning(f"[TEMPORAL] Rejected input {video_path} due to physical video validation failure.")
            return None

        out = output_path or (self.cache_dir / f"clip_{uuid.uuid4().hex[:10]}.mp4")

        # Fast and frame-accurate seek and extract
        cmd = [
            FFMPEG_EXE, "-y",
            "-ss", f"{start_time:.3f}",
            "-i", str(video_path),
            "-t", f"{duration:.3f}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-avoid_negative_ts", "make_zero",
            "-an",
            str(out)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12.0)
            if res.returncode != 0 or not out.exists():
                logger.warning(f"[TEMPORAL] FFmpeg extraction failed: {res.stderr.decode('utf-8', errors='ignore')[:300]}")
                out.unlink(missing_ok=True)
                return None
        except Exception as e:
            logger.warning(f"[TEMPORAL] FFmpeg extraction process error: {e}")
            out.unlink(missing_ok=True)
            return None

        # Step 2 Physical Media Quality and Cleanliness Validation on extracted output
        min_sharp = 120.0
        check_graphic = True
        max_wm_density = 0.010
        check_tc = True
        if candidate:
            s_tier = str(getattr(candidate, "source_tier", "") or "")
            s_type = str(getattr(candidate, "source_type", "") or "")
            s_name = str(getattr(candidate, "source_name", "") or "")
            if "TIER_5_SUPPORTING_STOCK" in s_tier or "STOCK" in s_type:
                min_sharp = 2.0
                max_wm_density = 0.025
            elif "TIER_4_ORIGINAL_PROCEDURAL_3D" in s_tier:
                check_graphic = False
                check_tc = False
            elif "TIER_1_DIRECT_INSTITUTIONAL" in s_tier or "nasa_svs" in s_name:
                min_sharp = 40.0
                check_tc = False
            elif "TIER_2_ARCHIVAL_VIDEO" in s_tier:
                min_sharp = 40.0

        val_res = PhysicalVideoValidator.validate_file(
            out,
            min_duration=0.5,
            check_temporal_motion=True,
            min_motion_threshold=1.5,
            check_cleanliness=True,
            min_sharpness_threshold=min_sharp,
            max_watermark_density=max_wm_density,
            check_presenter=True,
            check_graphic=check_graphic,
            check_timecode=check_tc
        )
        if not val_res.is_valid:
            logger.warning(f"[TEMPORAL] Physical validation rejected extracted subclip {out.name}: {val_res.error_message}")
            out.unlink(missing_ok=True)
            return None

        return out

    # --------------------------------------------------------------------------
    # 8. End-to-End Temporal Moment Retrieval Orchestration
    # --------------------------------------------------------------------------
    def retrieve_and_extract_best_moment(
        self,
        candidate: NormalizedVideoCandidate,
        intent: Optional[VisualIntent] = None,
        target_duration: float = 3.0,
        used_ranges: Optional[List[Tuple[float, float]]] = None,
        output_dir: Optional[Path] = None
    ) -> Tuple[Optional[Path], Optional[TemporalWindow]]:
        """
        Orchestrates full temporal analysis and sub-clip extraction:
          1. Validates local candidate file.
          2. Profiles video timeline in a single fast pass.
          3. Generates candidate temporal windows (cues, action peaks, intro-bypassed sliding).
          4. Scores windows combining dynamic action, motion, context, cues, anti-repetition.
          5. Filters out windows below FAIL_CLOSED_SCORE_THRESHOLD (0.35).
          6. Attempts FFmpeg extraction and physical Step-2 validation in rank order.
          7. Returns (extracted_clip_path, selected_window).
          8. Fail closed: If no window qualifies, returns (None, None). NO static fallback.
        """
        if not candidate.local_path or not Path(candidate.local_path).exists():
            logger.warning(f"[TEMPORAL] Candidate '{candidate.title}' has no valid local_path.")
            return None, None

        src_path = Path(candidate.local_path)
        val = PhysicalVideoValidator.validate_file(src_path)
        if not val.is_valid:
            logger.warning(f"[TEMPORAL] Candidate {src_path.name} failed physical validation: {val.error_message}")
            return None, None

        source_dur = val.duration
        target_dir = output_dir or self.cache_dir

        from .cache import get_canonical_cache
        cache = get_canonical_cache()
        canon_url = getattr(candidate, "media_url", "") or getattr(candidate, "page_url", "") or src_path.name

        # Fast clip reuse if a matching non-overlapping clip was already extracted
        reusable = cache.find_reusable_clip(
            url=canon_url,
            target_duration=target_duration,
            used_ranges=used_ranges,
            require_916=False,
            title=getattr(candidate, "title", "")
        )
        if reusable:
            re_path, re_start, re_end = reusable
            re_win = TemporalWindow(
                start_time=re_start,
                end_time=re_end,
                duration=round(re_end - re_start, 2),
                motion_score=0.90,
                action_score=0.90,
                stability_score=0.90,
                repetition_penalty=0.0,
                composite_score=0.90,
                matched_cues=["cached_clip_reuse"]
            )
            candidate.local_clip_path = str(re_path)
            candidate.selected_window_start = re_start
            candidate.selected_window_end = re_end
            candidate.duration = re_win.duration
            return re_path, re_win

        # Fast timeline profiling with canonical cache
        timeline_profile = cache.get_timeline_profile(canon_url, getattr(candidate, "title", ""))
        if not timeline_profile:
            timeline_profile = self.profile_video_timeline(src_path)
            if timeline_profile:
                cache.put_timeline_profile(canon_url, timeline_profile, getattr(candidate, "title", ""))

        cues = self.extract_temporal_cues(candidate)

        # Generate candidate windows (cues, action peaks, intro-bypassed sliding)
        raw_windows = self.generate_candidate_windows(
            source_duration=source_dur,
            target_duration=target_duration,
            stride=self.DEFAULT_STRIDE,
            timeline_profile=timeline_profile,
            cues=cues
        )

        # Score candidate windows
        scored_windows: List[TemporalWindow] = []
        for w in raw_windows:
            if timeline_profile:
                signals = self.analyze_window_profile(w, timeline_profile)
            else:
                signals = self.analyze_window_motion(src_path, w[0], w[1])

            tw = self.score_temporal_window(
                window=w,
                candidate=candidate,
                intent=intent,
                motion_signals=signals,
                used_ranges=used_ranges,
                source_duration=source_dur
            )
            scored_windows.append(tw)

        # Fail-closed gating: filter out windows below threshold
        qualifying_windows = [w for w in scored_windows if w.composite_score >= self.FAIL_CLOSED_SCORE_THRESHOLD]

        if not qualifying_windows:
            logger.warning(
                f"[TEMPORAL] Candidate '{candidate.title}' has no temporal windows meeting score threshold "
                f"({self.FAIL_CLOSED_SCORE_THRESHOLD}). Rejecting candidate fail-closed."
            )
            cache.mark_disqualified(canon_url, "No temporal window met motion/action threshold", getattr(candidate, "title", ""))
            return None, None

        # Sort qualifying windows descending by composite score
        qualifying_windows.sort(key=lambda x: x.composite_score, reverse=True)

        for win in qualifying_windows:
            clip_name = f"subclip_{uuid.uuid4().hex[:8]}.mp4"
            dest = target_dir / clip_name
            extracted = self.extract_subclip(
                video_path=src_path,
                start_time=win.start_time,
                duration=win.duration,
                output_path=dest,
                candidate=candidate
            )
            if extracted:
                candidate.local_clip_path = str(extracted)
                candidate.selected_window_start = win.start_time
                candidate.selected_window_end = win.end_time
                candidate.duration = win.duration
                cache.register_extracted_clip(
                    url=canon_url,
                    start_time=win.start_time,
                    end_time=win.end_time,
                    clip_path=extracted,
                    title=getattr(candidate, "title", "")
                )
                logger.info(
                    f"[TEMPORAL] Selected moment [{win.start_time:.1f}s - {win.end_time:.1f}s] "
                    f"(score={win.composite_score:.3f}, cues={win.matched_cues}) for candidate '{candidate.title}'"
                )
                return extracted, win

        logger.warning(f"[TEMPORAL] All qualifying temporal windows failed extraction/cleanliness for candidate '{candidate.title}'.")
        cache.mark_disqualified(canon_url, "All qualifying windows failed extraction/cleanliness", getattr(candidate, "title", ""))
        return None, None
