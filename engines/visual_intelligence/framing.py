"""
Intelligent Video Framing & 9:16 Editorial Cropping Engine (Step 4/8).
======================================================================
Transforms retrieved real/movie/archival footage of any aspect ratio
(16:9, 4:3, 1:1, ultrawide, etc.) into high-quality vertical 9:16 video (1080x1920)
WITHOUT black bars, letterboxing/pillarboxing, distortion stretching, or image conversions.

Key Architecture:
  1. Center-of-Interest Detection: Computes motion concentration, multi-subject clusters,
     and frame difference centroids.
  2. Action Direction & Lead Room: Automatically shifts crop ahead of subjects moving left/right.
  3. Semantically Guided Framing: Fuses Step 2 VisualIntent (target object, actors, action region).
  4. Temporal Stability & Smooth Tracking: Bounded velocity (MAX_PAN_SPEED), micro-jitter suppression,
     and single-directional linear panning (no camera whipping or oscillation).
  5. Safe Crop Margins: Prevents subjects from touching extreme edges.
  6. Strict Physical Media Validation: Verifies 1080x1920, authentic ISO video stream, non-zero duration.
  7. Low-Resolution & Frozen-Frame Protection: Rejects frozen or sub-minimal resolution assets.
  8. Anti-Repetition: Avoids identical crop coordinates for multiple scenes from the same source.
"""
import math
import uuid
import logging
import subprocess
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple

import cv2
import numpy as np

from config.settings import FFMPEG_EXE, FFPROBE_EXE, ASSETS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT
from core.media_validator import PhysicalVideoValidator, VideoValidationResult
from .models import VisualIntent, NormalizedVideoCandidate

logger = logging.getLogger(__name__)

FRAMED_CLIPS_CACHE_DIR = Path(ASSETS_DIR) / "framed_clips"
FRAMED_CLIPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class EditorialCropStrategy(str, Enum):
    """Editorial cropping strategies for 9:16 framing."""
    CENTER_CROP = "center_crop"
    SUBJECT_GUIDED = "subject_guided"
    MOTION_GUIDED = "motion_guided"
    SAFE_FALLBACK = "safe_fallback"


@dataclass
class FramingSpec:
    """Complete mathematical and editorial specification for 9:16 framing."""
    strategy: EditorialCropStrategy
    source_width: int
    source_height: int
    target_width: int = VIDEO_WIDTH   # 1080
    target_height: int = VIDEO_HEIGHT # 1920
    start_cx: float = 0.5             # Normalized horizontal center [0.0, 1.0]
    end_cx: float = 0.5               # Normalized horizontal center [0.0, 1.0]
    start_cy: float = 0.5             # Normalized vertical center [0.0, 1.0]
    end_cy: float = 0.5               # Normalized vertical center [0.0, 1.0]
    confidence: float = 1.0           # Confidence score of detection [0.0, 1.0]
    is_moving: bool = False           # Whether the crop pans smoothly
    pan_speed: float = 0.0            # Normalized horizontal movement per second
    lead_room: float = 0.0            # Normalized lead-room offset
    ffmpeg_crop_filter: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["strategy"] = self.strategy.value
        return d


class CenterOfInterestDetector:
    """
    Lightweight, deterministic center-of-interest detection engine.
    Derives spatial motion concentration, temporal centroids, multi-subject clusters,
    and semantic focus points.
    """

    MIN_MOTION_PIXELS = 150
    MAX_PAN_SPEED = 0.15  # Maximum normalized width movement per second (smooth pan constraint)

    def __init__(self):
        self.last_motion_details: Dict[str, Any] = {}

    def analyze_video_trajectory(
        self,
        video_path: Path,
        intent: Optional[VisualIntent] = None,
        sample_count: int = 10
    ) -> Tuple[List[Tuple[float, float, float]], float, bool]:
        """
        Samples video frames to compute temporal motion centroid trajectory.
        Evaluates multi-subject scenes, directional velocity, and lead room.
        Returns:
          - samples: List of (t, cx, cy)
          - confidence: Detection confidence [0.0, 1.0]
          - is_frozen: True if video has zero visual change (frozen frames)
        """
        self.last_motion_details = {
            "lead_room": 0.0,
            "direction": "STATIC",
            "v_x": 0.0,
            "multi_subject": False
        }

        if not video_path.exists():
            return [(0.0, 0.5, 0.5)], 0.0, False

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return [(0.0, 0.5, 0.5)], 0.0, False

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        duration = total_frames / max(1.0, fps)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        if total_frames <= 1 or width <= 0 or height <= 0:
            cap.release()
            return [(0.0, 0.5, 0.5)], 0.0, True

        frame_indices = np.linspace(0, total_frames - 1, min(sample_count + 1, total_frames), dtype=int)
        frames_gray = []
        timestamps = []

        for idx in frame_indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ret, frame = cap.read()
            if ret and frame is not None:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Downsample to 320-width for lightning-fast analysis (~1ms)
                if width > 320:
                    gray = cv2.resize(gray, (320, int(320 * height / width)), interpolation=cv2.INTER_AREA)
                frames_gray.append(gray)
                timestamps.append(idx / max(1.0, fps))

        cap.release()

        if len(frames_gray) < 2:
            return [(0.0, 0.5, 0.5)], 0.5, False

        # Measure motion between consecutive sampled frames
        centroids: List[Tuple[float, float, float]] = []
        max_diff_val = 0.0
        multi_subject_detected = False

        intent_text = ""
        if intent:
            intent_text = f"{intent.narration_text} {getattr(intent, 'visual_action', '')} {getattr(intent, 'target_object', '')}".lower()

        for i in range(len(frames_gray) - 1):
            diff = cv2.absdiff(frames_gray[i], frames_gray[i + 1])
            max_val = float(np.max(diff))
            max_diff_val = max(max_diff_val, max_val)

            _, thresh = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
            t_mid = (timestamps[i] + timestamps[i + 1]) / 2.0
            gw = frames_gray[i].shape[1]
            gh = frames_gray[i].shape[0]

            # Multi-Subject & Blob Analysis
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            valid_blobs = []
            for c in contours:
                area = cv2.contourArea(c)
                if area >= 50:  # Minimum significant motion blob
                    x, y, w, h = cv2.boundingRect(c)
                    valid_blobs.append((x, y, w, h, area))

            if valid_blobs:
                valid_blobs.sort(key=lambda b: b[4], reverse=True)
                if len(valid_blobs) > 1:
                    multi_subject_detected = True
                    # Check if all blobs fit within 9:16 vertical crop span (~32% of 16:9 width)
                    min_x = min(b[0] for b in valid_blobs)
                    max_x = max(b[0] + b[2] for b in valid_blobs)
                    span_norm = (max_x - min_x) / float(gw)

                    if span_norm <= 0.32:
                        # Group fits within vertical frame: center on midpoint of group
                        cx = ((min_x + max_x) / 2.0) / float(gw)
                        cy = 0.5
                    else:
                        # Cannot fit both: disambiguate using intent
                        chosen_blob = valid_blobs[0]
                        if any(k in intent_text for k in ["left", "port"]):
                            chosen_blob = min(valid_blobs, key=lambda b: b[0])
                        elif any(k in intent_text for k in ["right", "starboard"]):
                            chosen_blob = max(valid_blobs, key=lambda b: b[0] + b[2])
                        elif any(k in intent_text for k in ["flee", "blast", "fire", "sink", "strike"]):
                            # Pick blob with highest density / rapid action
                            chosen_blob = valid_blobs[0]

                        cx = (chosen_blob[0] + chosen_blob[2] / 2.0) / float(gw)
                        cy = (chosen_blob[1] + chosen_blob[3] / 2.0) / float(gh)
                else:
                    # Single dominant blob
                    b = valid_blobs[0]
                    cx = (b[0] + b[2] / 2.0) / float(gw)
                    cy = (b[1] + b[3] / 2.0) / float(gh)

                centroids.append((t_mid, float(cx), float(cy)))
            else:
                m = cv2.moments(thresh)
                if m["m00"] > self.MIN_MOTION_PIXELS:
                    cx = (m["m10"] / m["m00"]) / float(gw)
                    cy = (m["m01"] / m["m00"]) / float(gh)
                    centroids.append((t_mid, float(cx), float(cy)))
                else:
                    centroids.append((t_mid, 0.5, 0.5))

        # Frozen Video Detection: if maximum frame difference is near zero across entire clip
        if max_diff_val < 1.5:
            return [(0.0, 0.5, 0.5)], 0.0, True

        # Directional Velocity and Lead Room Calculation
        xs = [c[1] for c in centroids]
        v_x = 0.0
        lead_room = 0.0
        direction = "STATIC"

        if len(xs) >= 2:
            v_x = xs[-1] - xs[0]
            if v_x > 0.04:
                direction = "RIGHT"
                lead_room = min(0.08, v_x * 0.40)
            elif v_x < -0.04:
                direction = "LEFT"
                lead_room = -min(0.08, abs(v_x) * 0.40)

        self.last_motion_details = {
            "lead_room": round(lead_room, 3),
            "direction": direction,
            "v_x": round(v_x, 3),
            "multi_subject": multi_subject_detected
        }

        confidence = 0.85 if len(centroids) >= 3 else 0.50
        return centroids, confidence, False


class IntelligentFramingEngine:
    """
    Core engine that reframes landscape, archival, and standard footage
    into vertical 9:16 1080x1920 video with smooth camera movement and zero black bars.
    """

    TARGET_WIDTH = VIDEO_WIDTH    # 1080
    TARGET_HEIGHT = VIDEO_HEIGHT  # 1920
    TARGET_ASPECT = 9.0 / 16.0    # 0.5625
    MIN_SOURCE_WIDTH = 320
    MIN_SOURCE_HEIGHT = 240

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or FRAMED_CLIPS_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.detector = CenterOfInterestDetector()

    # --------------------------------------------------------------------------
    # 1. Framing Specification Calculation
    # --------------------------------------------------------------------------
    def calculate_framing_spec(
        self,
        video_path: Path,
        intent: Optional[VisualIntent] = None,
        metadata: Optional[Dict[str, Any]] = None,
        used_crops: Optional[List[Tuple[float, float]]] = None
    ) -> FramingSpec:
        """
        Determines the optimal 9:16 crop window and temporal camera pan trajectory.
        Guarantees:
          - zero black bars / letterbox / pillarbox
          - no unnatural stretching
          - smooth temporal pan (no jerky jumps or oscillation)
          - lead room ahead of moving subjects
          - semantic guidance from VisualIntent
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Physical validation of input
        val = PhysicalVideoValidator.validate_file(video_path)
        if not val.is_valid:
            raise ValueError(f"Input {video_path.name} failed physical video validation: {val.error_message}")

        src_w = val.width
        src_h = val.height
        duration = max(0.5, val.duration)

        # Low-Resolution Protection: reject unusable tiny resolution
        if src_w < self.MIN_SOURCE_WIDTH or src_h < self.MIN_SOURCE_HEIGHT:
            raise ValueError(
                f"Source resolution {src_w}x{src_h} is below minimum {self.MIN_SOURCE_WIDTH}x{self.MIN_SOURCE_HEIGHT} "
                f"for quality 9:16 vertical editorial framing."
            )

        src_aspect = src_w / float(src_h)

        # ----------------------------------------------------------------------
        # Case A: Already Vertical 9:16 (0.5625 +- 0.02)
        # ----------------------------------------------------------------------
        if abs(src_aspect - self.TARGET_ASPECT) < 0.02:
            return FramingSpec(
                strategy=EditorialCropStrategy.CENTER_CROP,
                source_width=src_w,
                source_height=src_h,
                target_width=self.TARGET_WIDTH,
                target_height=self.TARGET_HEIGHT,
                start_cx=0.5,
                end_cx=0.5,
                confidence=1.0,
                is_moving=False,
                lead_room=0.0,
                ffmpeg_crop_filter=f"scale={self.TARGET_WIDTH}:{self.TARGET_HEIGHT},setsar=1"
            )

        # ----------------------------------------------------------------------
        # Trajectory Analysis & Center of Interest
        # ----------------------------------------------------------------------
        traj_res = self.detector.analyze_video_trajectory(
            video_path=video_path,
            intent=intent
        )
        if len(traj_res) == 4:
            trajectory, det_conf, is_frozen, motion_details = traj_res
        else:
            trajectory, det_conf, is_frozen = traj_res
            motion_details = getattr(self.detector, "last_motion_details", {})

        if is_frozen:
            raise ValueError(f"Video {video_path.name} consists of frozen/static frames; rejected under video-first policy.")

        # Compute raw start and end centers
        xs = [c[1] for c in trajectory]
        if not xs:
            raw_start_cx = 0.5
            raw_end_cx = 0.5
        elif len(xs) == 1:
            raw_start_cx = float(xs[0])
            raw_end_cx = float(xs[0])
        else:
            mid = max(1, len(xs) // 2)
            raw_start_cx = float(np.mean(xs[:mid]))
            raw_end_cx = float(np.mean(xs[mid:]))

        strategy = EditorialCropStrategy.MOTION_GUIDED
        confidence = det_conf

        # ----------------------------------------------------------------------
        # Action Direction & Lead Room Application
        # ----------------------------------------------------------------------
        lead_room = motion_details.get("lead_room", 0.0)
        if lead_room != 0.0:
            raw_start_cx = max(0.10, min(0.90, raw_start_cx + lead_room))
            raw_end_cx = max(0.10, min(0.90, raw_end_cx + lead_room))

        # ----------------------------------------------------------------------
        # Semantic Guidance Integration (VisualIntent & Candidate Metadata)
        # ----------------------------------------------------------------------
        meta = metadata or {}
        semantic_cx = None

        if "subject_x" in meta:
            try:
                semantic_cx = float(meta["subject_x"])
            except (ValueError, TypeError):
                pass

        intent_text = ""
        if intent:
            intent_text = f"{intent.narration_text} {getattr(intent, 'visual_action', '')} {getattr(intent, 'target_object', '')}".lower()

        if semantic_cx is None and intent_text:
            if any(k in intent_text for k in ["left", "port side", "entering from left", "fleeing left"]):
                semantic_cx = 0.28
            elif any(k in intent_text for k in ["right", "starboard", "entering from right", "fleeing right"]):
                semantic_cx = 0.72

        if semantic_cx is not None:
            strategy = EditorialCropStrategy.SUBJECT_GUIDED
            raw_start_cx = round(0.65 * semantic_cx + 0.35 * raw_start_cx, 3)
            raw_end_cx = round(0.65 * semantic_cx + 0.35 * raw_end_cx, 3)
            confidence = min(1.0, confidence + 0.15)

        # ----------------------------------------------------------------------
        # Anti-Repetition Across Scenes
        # ----------------------------------------------------------------------
        if used_crops:
            for past_start, past_end in used_crops:
                if abs(raw_start_cx - past_start) < 0.10:
                    if 0.40 <= raw_start_cx <= 0.60:
                        raw_start_cx = max(0.25, raw_start_cx - 0.15)
                        raw_end_cx = max(0.25, raw_end_cx - 0.15)
                    break

        # ----------------------------------------------------------------------
        # Low Confidence & Small Motion Fallback
        # ----------------------------------------------------------------------
        if confidence < 0.40:
            strategy = EditorialCropStrategy.SAFE_FALLBACK
            raw_start_cx = 0.5
            raw_end_cx = 0.5
        else:
            # Micro-jitter elimination: if movement is tiny, lock to static
            if abs(raw_end_cx - raw_start_cx) < 0.05:
                mid_cx = round((raw_start_cx + raw_end_cx) / 2.0, 3)
                raw_start_cx = mid_cx
                raw_end_cx = mid_cx
                if abs(mid_cx - 0.5) < 0.08:
                    strategy = EditorialCropStrategy.CENTER_CROP
                    raw_start_cx = 0.5
                    raw_end_cx = 0.5

        # ----------------------------------------------------------------------
        # Temporal Smoothing: Bounded Pan Velocity (No violent jumping or oscillation)
        # ----------------------------------------------------------------------
        max_allowed_delta = self.detector.MAX_PAN_SPEED * duration
        actual_delta = raw_end_cx - raw_start_cx
        if abs(actual_delta) > max_allowed_delta:
            raw_end_cx = raw_start_cx + math.copysign(max_allowed_delta, actual_delta)

        # Safe Crop Margins: prevent content from touching extreme edges
        start_cx = max(0.05, min(0.95, round(raw_start_cx, 3)))
        end_cx = max(0.05, min(0.95, round(raw_end_cx, 3)))
        is_moving = abs(end_cx - start_cx) >= 0.04
        pan_speed = round(abs(end_cx - start_cx) / duration, 4)

        # ----------------------------------------------------------------------
        # FFmpeg Filter Formulation (Zero Black Bars, Zero Distortion)
        # ----------------------------------------------------------------------
        scaled_w = round(src_w * (float(self.TARGET_HEIGHT) / float(src_h)))
        scaled_h = self.TARGET_HEIGHT

        if scaled_w < self.TARGET_WIDTH:
            # Ultra-tall video (e.g. 1:2): scale width to 1080, crop vertically
            scaled_w = self.TARGET_WIDTH
            scaled_h = round(src_h * (float(self.TARGET_WIDTH) / float(src_w)))
            max_y = max(0, scaled_h - self.TARGET_HEIGHT)
            y_pos = int(max_y * 0.5)
            crop_expr = f"scale={scaled_w}:{scaled_h},crop={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:0:{y_pos},setsar=1"
        else:
            # Standard landscape / archival (16:9, 4:3, 1:1, etc.)
            max_x = max(0, scaled_w - self.TARGET_WIDTH)

            # Compute pixel coordinates from normalized cx clamped to valid crop bounds
            x_start_px = int(max(0, min(max_x, round(start_cx * scaled_w - (self.TARGET_WIDTH / 2.0)))))
            x_end_px = int(max(0, min(max_x, round(end_cx * scaled_w - (self.TARGET_WIDTH / 2.0)))))

            if not is_moving or x_start_px == x_end_px:
                crop_expr = f"scale={scaled_w}:{scaled_h},crop={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:{x_start_px}:0,setsar=1"
            else:
                # Smooth continuous camera pan expression across duration D
                crop_expr = (
                    f"scale={scaled_w}:{scaled_h},"
                    f"crop={self.TARGET_WIDTH}:{self.TARGET_HEIGHT}:"
                    f"'min({max_x},max(0,{x_start_px}+({x_end_px}-{x_start_px})*t/{duration:.3f}))':0,setsar=1"
                )

        return FramingSpec(
            strategy=strategy,
            source_width=src_w,
            source_height=src_h,
            target_width=self.TARGET_WIDTH,
            target_height=self.TARGET_HEIGHT,
            start_cx=start_cx,
            end_cx=end_cx,
            confidence=round(confidence, 3),
            is_moving=is_moving,
            pan_speed=pan_speed,
            lead_room=round(lead_room, 3),
            ffmpeg_crop_filter=crop_expr,
            metadata={"scaled_w": scaled_w, "scaled_h": scaled_h, "duration": duration}
        )

    # --------------------------------------------------------------------------
    # 2. Sub-Clip Framing & Rendering Execution
    # --------------------------------------------------------------------------
    def frame_video_to_916(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        intent: Optional[VisualIntent] = None,
        metadata: Optional[Dict[str, Any]] = None,
        used_crops: Optional[List[Tuple[float, float]]] = None
    ) -> Optional[Path]:
        """
        Executes FFmpeg framing and validates resulting 1080x1920 video clip.
        Strictly enforces:
          - Real moving video input ONLY (no static image fallback)
          - Non-zero temporal duration
          - Exact 1080x1920 physical geometry
          - Zero black bars or stretching
        """
        if not video_path.exists():
            logger.warning(f"[FRAMING] Input video file does not exist: {video_path}")
            return None

        # Absolute Rule: operates ONLY on real moving video clips
        if not PhysicalVideoValidator.is_valid_video(video_path, check_temporal_motion=True, min_motion_threshold=1.0):
            logger.warning(f"[FRAMING] Rejected non-video or frozen input: {video_path}")
            return None

        try:
            spec = self.calculate_framing_spec(
                video_path=video_path,
                intent=intent,
                metadata=metadata,
                used_crops=used_crops
            )
        except Exception as e:
            logger.warning(f"[FRAMING] Calculation failed for {video_path.name}: {e}")
            return None

        out = output_path or (self.cache_dir / f"framed_{uuid.uuid4().hex[:10]}.mp4")

        cmd = [
            FFMPEG_EXE, "-y",
            "-i", str(video_path),
            "-vf", spec.ffmpeg_crop_filter,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
            str(out)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=35.0)
            if res.returncode != 0 or not out.exists():
                logger.warning(f"[FRAMING] FFmpeg execution error: {res.stderr.decode('utf-8', errors='ignore')[:300]}")
                out.unlink(missing_ok=True)
                return None
        except Exception as e:
            logger.warning(f"[FRAMING] Process error: {e}")
            out.unlink(missing_ok=True)
            return None

        # Physical Media Validation on framed output
        val_res = PhysicalVideoValidator.validate_file(out, check_temporal_motion=True, min_motion_threshold=1.0)
        if not val_res.is_valid:
            logger.warning(f"[FRAMING] Framed output failed physical validation: {val_res.error_message}")
            out.unlink(missing_ok=True)
            return None

        # Verify exact 1080x1920 geometry and 9:16 aspect ratio
        if val_res.width != self.TARGET_WIDTH or val_res.height != self.TARGET_HEIGHT:
            logger.warning(f"[FRAMING] Output dimension mismatch: {val_res.width}x{val_res.height} != 1080x1920")
            out.unlink(missing_ok=True)
            return None

        logger.info(
            f"[FRAMING] Successfully framed '{video_path.name}' -> 1080x1920 9:16 "
            f"(Strategy: {spec.strategy.value}, cx={spec.start_cx:.2f}->{spec.end_cx:.2f}, Moving={spec.is_moving}, LeadRoom={spec.lead_room:+.2f})"
        )
        return out
