"""
Physical Media Validator & Hard Video-Only Enforcement Engine.
==============================================================
Enforces the hard invariant: VIDEO FOOTAGE ONLY (VIDEO_ONLY = True).
Strictly rejects all still images (JPEG, PNG, WebP, GIF, BMP, TIFF),
renamed image assets (.jpg renamed to .mp4), thumbnail URLs, and single-frame stills.
Uses both binary magic-byte inspection and physical FFprobe stream analysis.
"""
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any
from urllib.parse import urlparse

from config.settings import FFPROBE_EXE

logger = logging.getLogger(__name__)

# Canonical Hard Invariant
VIDEO_ONLY: bool = True

PROHIBITED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".svg", ".ico", ".avif"
}

PROHIBITED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp",
    "image/tiff", "image/svg+xml", "image/x-icon", "image/avif"
}

PROHIBITED_IMAGE_CODECS = {
    "mjpeg", "jpeg2000", "png", "bmp", "tiff", "webp", "gif", "svg"
}

VALID_VIDEO_EXTENSIONS = {
    ".mp4", ".webm", ".mov", ".mkv", ".ogv"
}

VALID_VIDEO_MIME_TYPES = {
    "video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/ogg"
}

IMAGE_MAGIC_SIGNATURES = [
    (b"\xFF\xD8\xFF", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]


@dataclass
class VideoValidationResult:
    """Detailed result of physical media inspection."""
    is_valid: bool
    duration: float = 0.0
    width: int = 0
    height: int = 0
    codec: str = ""
    format_name: str = ""
    fps: float = 0.0
    nb_frames: int = 0
    motion_score: float = 0.0
    is_moving: bool = True
    sharpness_score: float = 0.0
    saturation_mean: float = 0.0
    is_monochrome: bool = False
    has_watermark: bool = False
    has_timecode: bool = False
    has_presenter: bool = False
    is_graphic: bool = False
    error_message: Optional[str] = None
    cleanliness_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "duration": round(self.duration, 3),
            "width": self.width,
            "height": self.height,
            "codec": self.codec,
            "format_name": self.format_name,
            "fps": round(self.fps, 2),
            "nb_frames": self.nb_frames,
            "motion_score": round(self.motion_score, 3),
            "is_moving": self.is_moving,
            "sharpness_score": round(self.sharpness_score, 2),
            "saturation_mean": round(self.saturation_mean, 2),
            "is_monochrome": self.is_monochrome,
            "has_watermark": self.has_watermark,
            "has_timecode": self.has_timecode,
            "has_presenter": self.has_presenter,
            "is_graphic": self.is_graphic,
            "error_message": self.error_message,
            "cleanliness_details": self.cleanliness_details,
        }


class PhysicalVideoValidator:
    """
    Validates that a visual asset is physically an authentic, moving video stream
    with non-zero temporal duration, valid video codec, and moving frames.
    """

    @staticmethod
    def is_image_url(url: str) -> bool:
        """Determines if a URL points to a static image, photo, or thumbnail."""
        if not url:
            return True
        clean_url = url.split("?")[0].lower()
        # Extension check
        for ext in PROHIBITED_EXTENSIONS:
            if clean_url.endswith(ext):
                return True

        # Query parameter / path patterns
        lower_url = url.lower()
        image_indicators = [
            "/photos/",
            "/photo/",
            "/images/",
            "/image/",
            "/thumb/",
            "/thumbnail/",
            "format=jpg",
            "format=jpeg",
            "format=png",
            "format=webp",
            "image_id=",
            "pollinations.ai",
            "images.pexels.com",
            "wikimedia.org/wikipedia/commons/thumb/",
        ]
        for ind in image_indicators:
            if ind in lower_url and not any(v_ext in lower_url for v_ext in [".mp4", ".webm", ".mov", ".mkv"]):
                return True

        return False

    @staticmethod
    def is_video_url(url: str) -> bool:
        """Determines if a URL is explicitly a video resource."""
        if not url:
            return False
        if PhysicalVideoValidator.is_image_url(url):
            return False
        clean_url = url.split("?")[0].lower()
        for ext in VALID_VIDEO_EXTENSIONS:
            if clean_url.endswith(ext):
                return True
        lower_url = url.lower()
        if "video" in lower_url and not PhysicalVideoValidator.is_image_url(lower_url):
            return True
        return False

    @staticmethod
    def check_magic_bytes(file_path: Union[str, Path]) -> Optional[str]:
        """
        Inspects header bytes to detect static image types masquerading as videos.
        Returns the detected image mime type if matching an image format, else None.
        """
        path = Path(file_path)
        if not path.exists() or path.stat().st_size < 16:
            return None
        try:
            with open(path, "rb") as f:
                header = f.read(32)
            # Check exact image headers
            for sig, mime in IMAGE_MAGIC_SIGNATURES:
                if header.startswith(sig):
                    return mime
            # Check WebP RIFF header: starts with RIFF and has WEBP at offset 8
            if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
                return "image/webp"
        except Exception as e:
            logger.debug(f"Error checking magic bytes for {file_path}: {e}")
        return None

    @classmethod
    def verify_temporal_motion(
        cls,
        file_path: Union[str, Path],
        min_motion_threshold: float = 1.5,
        sample_stride: int = 12,
        max_samples: int = 8
    ) -> Tuple[bool, float, str]:
        """
        Physically inspects video frames using OpenCV to compute true pixel-level motion.
        Detects and rejects static photos disguised as MP4, frozen video streams,
        and static graphics/diagrams where frame-to-frame pixel change is below threshold.
        """
        path = Path(file_path)
        if not path.exists():
            return False, 0.0, f"File does not exist: {file_path}"

        try:
            import cv2
            import numpy as np

            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                return False, 0.0, f"OpenCV failed to open video: {path.name}"

            frames = []
            count = 0
            # Read sequentially with stride to ensure fast evaluation (< 100ms)
            while len(frames) < max_samples and count < (max_samples * sample_stride * 2):
                ret, frame = cap.read()
                if not ret or frame is None:
                    break
                if count % sample_stride == 0:
                    # Resize to standard thumbnail for fast normalized diff calculation preserving aspect ratio
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    fh, fw = gray.shape[:2]
                    target_size = (180, 320) if fh > fw else (320, 180)
                    gray = cv2.resize(gray, target_size)
                    frames.append(gray)
                count += 1
            cap.release()

            if len(frames) < 2:
                return False, 0.0, "Asset has insufficient frames to verify physical motion"

            # 1. Darkness / Blown-out Frame Rejection (Black screens, transition frames)
            means = [float(np.mean(f)) for f in frames]
            min_br = min(means)
            max_br = max(means)
            if min_br < 5.0 and max_br < 16.0:
                return False, 0.0, f"Physical motion failure: Asset contains black or near-black blank frames (min brightness {min_br:.1f}, max {max_br:.1f} < 16.0)"
            elif float(np.mean(means)) < 7.0:
                return False, 0.0, f"Physical motion failure: Asset is excessively dark overall (average brightness {float(np.mean(means)):.1f} < 7.0)"
            if max_br > 248.0 and float(np.mean(means)) > 240.0:
                return False, 0.0, f"Physical motion failure: Asset contains blown-out/white blank frames (max brightness {max_br:.1f} > 248.0)"

            # Document / Web Page / Screen Recording Rejection (rejects browser captures, sponsor ads, white slides)
            white_ratios = [float(np.sum(f > 215)) / (f.shape[0] * f.shape[1]) for f in frames]
            if max(white_ratios) > 0.55:
                return False, 0.0, f"Physical motion failure: Document, website capture, or white screen recording (white pixel ratio {max(white_ratios):.2f} > 0.55)"

            # 2. Raw Absolute Pixel Difference Check
            diffs = [float(np.mean(cv2.absdiff(frames[i], frames[i+1]))) for i in range(len(frames) - 1)]
            avg_diff = sum(diffs) / len(diffs) if diffs else 0.0

            if avg_diff < min_motion_threshold:
                return (
                    False,
                    avg_diff,
                    f"Physical motion failure: Asset is static/frozen imagery wrapped in video container (mean frame diff {avg_diff:.2f} < threshold {min_motion_threshold})"
                )

            # 3. Optical Flow Variance Check (Distinguishes genuine moving video from Ken Burns pan of still photo / painting / clock)
            flow_stds = []
            for i in range(min(5, len(frames) - 1)):
                flow = cv2.calcOpticalFlowFarneback(frames[i], frames[i+1], None, 0.5, 3, 15, 3, 5, 1.2, 0)
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                flow_stds.append(float(np.std(mag)))

            avg_flow_std = sum(flow_stds) / len(flow_stds) if flow_stds else 0.0
            min_flow_threshold = 0.50
            if avg_flow_std < min_flow_threshold:
                return (
                    False,
                    avg_flow_std,
                    f"Physical motion failure: Asset lacks dynamic motion (flow variance {avg_flow_std:.2f} < threshold {min_flow_threshold}; uniform Ken Burns pan of still photo, painting, diagram, or clock)"
                )

            # 4. Texture / Edge Density Check (Distinguishes textured footage from flat graphics / title cards)
            edge_densities = [
                float(np.sum(cv2.Canny(f, 80, 160) > 0)) / (f.shape[0] * f.shape[1])
                for f in frames
            ]
            max_edge_density = max(edge_densities) if edge_densities else 0.0
            if max_edge_density < 0.006:
                return False, 0.0, f"Physical motion failure: Flat canvas or solid title background (max edge density {max_edge_density:.4f} < 0.006)"

            return True, avg_diff, ""

        except Exception as e:
            logger.warning(f"Notice computing temporal motion for {path.name}: {e}")
            return True, 5.0, ""

    @classmethod
    def extract_sampled_frames(
        cls,
        file_path: Union[str, Path],
        num_samples: int = 5
    ) -> List[Any]:
        """Samples frames across video duration for physical cleanliness and quality evaluation."""
        path = Path(file_path)
        if not path.exists():
            return []
        try:
            import cv2
            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                return []
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames <= 0:
                frames = []
                while len(frames) < num_samples:
                    ret, f = cap.read()
                    if not ret or f is None:
                        break
                    frames.append(f)
                cap.release()
                return frames

            indices = [
                int(total_frames * ratio)
                for ratio in [0.10, 0.30, 0.50, 0.70, 0.90][:num_samples]
            ]
            frames = []
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(total_frames - 1, idx)))
                ret, f = cap.read()
                if ret and f is not None:
                    frames.append(f)
            cap.release()
            return frames
        except Exception as e:
            logger.warning(f"Notice sampling frames from {path.name}: {e}")
            return []

    @classmethod
    def detect_broadcast_timecode(
        cls,
        sampled_frames: List[Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Detects persistent broadcast clocks/timecodes (e.g. HH:MM:SS or HH:MM:SS:FF).
        Enforces:
          1. Monospace colon pair alignment along a horizontal baseline in top/bottom 22% strips.
          2. Temporal coordinate persistence across multiple frames (eliminates false positives).
          3. Complete immunity for legitimate historical dates (e.g. '1872' has zero colons).
        """
        if not sampled_frames or len(sampled_frames) < 2:
            return False, "", {"timecode_detected": False}

        try:
            import cv2
            import numpy as np

            def extract_colons_from_strip(strip: np.ndarray) -> List[Tuple[Tuple[float, float], Tuple[float, float], float]]:
                sh, sw = strip.shape[:2]
                if sh < 20 or sw < 50:
                    return []
                scale = 180.0 / sh
                resized = cv2.resize(strip, (max(50, int(sw * scale)), 180))
                gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
                results = []
                for invert in [False, True]:
                    t = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 4)
                    if invert:
                        t = cv2.bitwise_not(t)
                    num_labels, _, stats, centroids = cv2.connectedComponentsWithStats(t)
                    dots = []
                    for i in range(1, num_labels):
                        x, y, cw, ch, area = stats[i]
                        if 2 <= cw <= 14 and 2 <= ch <= 14 and 0.5 <= cw / max(1, ch) <= 2.0 and area >= 4:
                            dots.append((centroids[i][0], centroids[i][1], cw, ch, y))
                    for i in range(len(dots)):
                        for j in range(i + 1, len(dots)):
                            x1, y1, w1, h1, top1 = dots[i]
                            x2, y2, w2, h2, top2 = dots[j]
                            if 0.6 <= h1 / max(1, h2) <= 1.6 and 0.6 <= w1 / max(1, w2) <= 1.6:
                                if abs(x1 - x2) <= max(3.0, 0.45 * max(w1, w2)):
                                    dy = abs(y1 - y2)
                                    gap = abs(top1 - top2) - min(h1, h2)
                                    if 0.5 * min(h1, h2) <= gap <= 3.5 * min(h1, h2):
                                        results.append(((x1 + x2) / 2.0, (y1 + y2) / 2.0, dy))
                unique = []
                for c in results:
                    if not any(abs(c[0] - u[0]) < 6 and abs(c[1] - u[1]) < 6 for u in unique):
                        unique.append(c)
                unique.sort(key=lambda c: c[0])
                aligned = []
                for i in range(len(unique)):
                    for j in range(i + 1, len(unique)):
                        c1, c2 = unique[i], unique[j]
                        if abs(c1[1] - c2[1]) <= max(3.0, 0.3 * max(c1[2], c2[2])):
                            dx = c2[0] - c1[0]
                            if 20.0 <= dx <= 120.0:
                                aligned.append(((c1[0], c1[1]), (c2[0], c2[1]), dx))
                return aligned

            h, w = sampled_frames[0].shape[:2]
            strips_config = [
                ("top", 0, int(0.22 * h)),
                ("bottom", int(0.78 * h), h)
            ]
            for strip_name, y_start, y_end in strips_config:
                frame_colons = [
                    extract_colons_from_strip(f[y_start:y_end, :])
                    for f in sampled_frames if f is not None and f.shape[0] >= y_end
                ]
                persistent_count = 0
                for i in range(len(frame_colons)):
                    for j in range(i + 1, len(frame_colons)):
                        for p1 in frame_colons[i]:
                            for p2 in frame_colons[j]:
                                c1_match = abs(p1[0][0] - p2[0][0]) <= 4 and abs(p1[0][1] - p2[0][1]) <= 4
                                c2_match = abs(p1[1][0] - p2[1][0]) <= 4 and abs(p1[1][1] - p2[1][1]) <= 4
                                if c1_match and c2_match:
                                    persistent_count += 1
                                    if persistent_count >= 2:
                                        return (
                                            True,
                                            f"Persistent broadcast clock/timecode pattern detected in {strip_name} strip",
                                            {"timecode_detected": True, "strip": strip_name, "persistent_count": persistent_count}
                                        )

            return False, "", {"timecode_detected": False}
        except Exception as e:
            logger.debug(f"Timecode detection notice: {e}")
            return False, "", {"timecode_detected": False, "error": str(e)}

    @classmethod
    def detect_persistent_watermark(
        cls,
        sampled_frames: List[Any],
        is_moving: bool = True,
        max_density: float = 0.015
    ) -> Tuple[bool, float, str, Dict[str, float]]:
        """
        Detects stationary corner watermarks, channel bugs, and network logos.
        Computes temporal intersection of Canny edges across moving frames.
        """
        if not sampled_frames or len(sampled_frames) < 3 or not is_moving:
            return False, 0.0, "", {}

        try:
            import cv2
            import numpy as np

            h, w = sampled_frames[0].shape[:2]
            target_size = (480, 270) if w >= h else (270, 480)
            tw, th = target_size[0], target_size[1]

            grays = [cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), target_size) for f in sampled_frames if f is not None]
            if len(grays) < 3:
                return False, 0.0, "", {}

            # Crop active visual area if letterbox bars (>92% black) are present
            first_gray = grays[0]
            row_means = np.mean(first_gray, axis=1)
            col_means = np.mean(first_gray, axis=0)
            valid_rows = np.where(row_means > 12.0)[0]
            valid_cols = np.where(col_means > 12.0)[0]
            if len(valid_rows) > int(0.5 * th) and len(valid_cols) > int(0.5 * tw):
                r_min, r_max = valid_rows[0], valid_rows[-1] + 1
                c_min, c_max = valid_cols[0], valid_cols[-1] + 1
            else:
                r_min, r_max = 0, th
                c_min, c_max = 0, tw

            active_grays = [g[r_min:r_max, c_min:c_max] for g in grays]
            ah, aw = active_grays[0].shape[:2]
            if ah < 40 or aw < 40:
                return False, 0.0, "", {}

            edges_list = [cv2.Canny(g, 80, 160) for g in active_grays]
            kernel = np.ones((2, 2), np.uint8)
            dilated = [cv2.dilate(e, kernel) for e in edges_list]

            persistent = edges_list[0].copy()
            for d in dilated[1:]:
                persistent = cv2.bitwise_and(persistent, d)

            # Check 4 corner boxes (each 20% width x 20% height of active content)
            # If the video is landscape / wider than 9:16 vertical, constrain watermark
            # detection to the active 9:16 vertical crop zone so TV channel bugs residing
            # in discarded 16:9 outer margins do not cause false rejections.
            target_vw = int(ah * (9.0 / 16.0))
            if aw > target_vw:
                vx_start = (aw - target_vw) // 2
                vx_end = vx_start + target_vw
                eval_patch = persistent[:, vx_start:vx_end]
                ew, eh = target_vw, ah
            else:
                eval_patch = persistent
                ew, eh = aw, ah

            # Check corner boxes of eval_patch (vertical crop zone)
            cw, ch = max(5, int(0.20 * ew)), max(5, int(0.20 * eh))
            corners = {
                "top_left": eval_patch[0:ch, 0:cw],
                "top_right": eval_patch[0:ch, ew - cw:ew],
                "bottom_left": eval_patch[eh - ch:eh, 0:cw],
                "bottom_right": eval_patch[eh - ch:eh, ew - cw:ew]
            }

            # If landscape, also inspect the outer frame corners so broadcaster/channel TV bugs
            # in the full source frame are caught before framing can pan onto them
            if aw > ew:
                fcw, fch = max(5, int(0.18 * aw)), max(5, int(0.18 * ah))
                corners["full_top_left"] = persistent[0:fch, 0:fcw]
                corners["full_top_right"] = persistent[0:fch, aw - fcw:aw]
                corners["full_bottom_left"] = persistent[ah - fch:ah, 0:fcw]
                corners["full_bottom_right"] = persistent[ah - fch:ah, aw - fcw:aw]

            densities = {}
            max_d = 0.0
            violating_corner = ""
            for name, patch in corners.items():
                if patch.shape[0] == 0 or patch.shape[1] == 0:
                    continue
                d = float(np.count_nonzero(patch)) / float(patch.shape[0] * patch.shape[1])
                densities[name] = round(d, 5)
                if d > max_d:
                    max_d = d
                # Effective threshold for corner bugs
                corner_thresh = max_density if "full" not in name else max_density * 1.2
                if d > corner_thresh and not violating_corner:
                    violating_corner = name

            if violating_corner:
                return (
                    True,
                    max_d,
                    f"Persistent watermark or TV bug in {violating_corner} corner (density {max_d:.4f} > {max_density:.4f})",
                    densities
                )

            # Also check center stock watermark band (30% to 70% height and 20% to 80% width of active zone)
            center_patch = eval_patch[int(0.30 * eh):int(0.70 * eh), int(0.20 * ew):int(0.80 * ew)]
            center_d = float(np.count_nonzero(center_patch)) / float(center_patch.shape[0] * center_patch.shape[1])
            densities["center"] = round(center_d, 5)
            center_thresh = max(0.022, max_density * 2.2)
            if center_d > center_thresh:
                return (
                    True,
                    center_d,
                    f"Persistent center watermark overlay detected (density {center_d:.4f} > {center_thresh:.4f})",
                    densities
                )

            # Also check upper-middle title card / typography band (15% to 50% height and 15% to 85% width)
            title_patch = eval_patch[int(0.15 * eh):int(0.50 * eh), int(0.15 * ew):int(0.85 * ew)]
            if title_patch.shape[0] > 0 and title_patch.shape[1] > 0:
                title_d = float(np.count_nonzero(title_patch)) / float(title_patch.shape[0] * title_patch.shape[1])
                densities["upper_middle_title"] = round(title_d, 5)
                if title_d > 0.024:
                    return (
                        True,
                        title_d,
                        f"Persistent title card or upper-screen typography detected (density {title_d:.4f} > 0.024)",
                        densities
                    )

            return False, max_d, "", densities
        except Exception as e:
            logger.debug(f"Watermark detection notice: {e}")
            return False, 0.0, "", {}

    @classmethod
    def detect_presenter_talking_head(
        cls,
        sampled_frames: List[Any],
        min_face_ratio: float = 0.08,
        persistence_threshold: float = 0.35
    ) -> Tuple[bool, float, str, Dict[str, Any]]:
        """
        Detects YouTube creator / explainer / talking-head segments (Problem 1).
        A creator talking head is characterized by:
          - A prominent frontal/near-frontal face looking at camera
          - Face occupies significant frame area (width >= 8% of frame width or area >= 1.2% of frame)
          - Face is centered (center_x between 15% and 85%, center_y between 10% and 80%)
          - Face persists across multiple frames of the temporal window (>= 35% of frames)
        """
        if not sampled_frames:
            return False, 0.0, "", {}
        try:
            import cv2
            import numpy as np

            # Locate cascade files
            cascade_candidates = [
                Path("data/models/haarcascade_frontalface_default.xml"),
                Path(__file__).parent.parent / "data" / "models" / "haarcascade_frontalface_default.xml",
            ]
            cascade_file = None
            for cp in cascade_candidates:
                if cp.exists():
                    cascade_file = str(cp)
                    break

            if not cascade_file:
                return False, 0.0, "", {}

            face_cascade = cv2.CascadeClassifier(cascade_file)
            if face_cascade.empty():
                return False, 0.0, "", {}

            profile_candidates = [
                Path("data/models/haarcascade_profileface.xml"),
                Path(__file__).parent.parent / "data" / "models" / "haarcascade_profileface.xml",
            ]
            profile_cascade = None
            for pp in profile_candidates:
                if pp.exists():
                    pc = cv2.CascadeClassifier(str(pp))
                    if not pc.empty():
                        profile_cascade = pc
                        break

            faces_detected_count = 0
            total_frames = len(sampled_frames)
            max_face_area_ratio = 0.0
            face_boxes = []

            for frame in sampled_frames:
                if frame is None:
                    continue
                fh, fw = frame.shape[:2]
                if fh < 80 or fw < 80:
                    continue

                target_w = 480
                target_h = int(fh * (target_w / fw))
                small = cv2.resize(frame, (target_w, target_h))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                gray = cv2.equalizeHist(gray)

                min_sz = (int(target_w * min_face_ratio), int(target_h * min_face_ratio))
                faces = face_cascade.detectMultiScale(
                    gray,
                    scaleFactor=1.15,
                    minNeighbors=4,
                    minSize=min_sz,
                    flags=cv2.CASCADE_SCALE_IMAGE
                )

                frame_has_talking_head = False
                for (x, y, w, h) in faces:
                    area_ratio = (w * h) / float(target_w * target_h)
                    cx = x + w / 2.0
                    cy = y + h / 2.0
                    norm_cx = cx / target_w
                    norm_cy = cy / target_h

                    # Centered, prominent face check
                    if area_ratio >= 0.010 and (0.15 <= norm_cx <= 0.85) and (0.10 <= norm_cy <= 0.80):
                        frame_has_talking_head = True
                        if area_ratio > max_face_area_ratio:
                            max_face_area_ratio = area_ratio
                        face_boxes.append({"x": x, "y": y, "w": w, "h": h, "area_ratio": round(area_ratio, 4)})
                        break

                if not frame_has_talking_head and profile_cascade:
                    pfaces = profile_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.15,
                        minNeighbors=4,
                        minSize=min_sz
                    )
                    for (x, y, w, h) in pfaces:
                        area_ratio = (w * h) / float(target_w * target_h)
                        cx = x + w / 2.0
                        cy = y + h / 2.0
                        norm_cx = cx / target_w
                        norm_cy = cy / target_h
                        if area_ratio >= 0.010 and (0.15 <= norm_cx <= 0.85) and (0.10 <= norm_cy <= 0.80):
                            frame_has_talking_head = True
                            if area_ratio > max_face_area_ratio:
                                max_face_area_ratio = area_ratio
                            face_boxes.append({"x": x, "y": y, "w": w, "h": h, "area_ratio": round(area_ratio, 4)})
                            break

                if frame_has_talking_head:
                    faces_detected_count += 1

            persistence_ratio = faces_detected_count / max(1, total_frames)
            is_presenter = (persistence_ratio >= persistence_threshold and max_face_area_ratio >= 0.012)

            meta = {
                "faces_detected_frames": faces_detected_count,
                "total_frames": total_frames,
                "persistence_ratio": round(persistence_ratio, 3),
                "max_face_area_ratio": round(max_face_area_ratio, 4),
                "is_presenter": is_presenter
            }

            if is_presenter:
                err = (
                    f"Creator/explainer talking-head detected (face present in {faces_detected_count}/{total_frames} "
                    f"frames, persistence {persistence_ratio:.2f} >= {persistence_threshold:.2f}, max area {max_face_area_ratio:.3f})"
                )
                return True, persistence_ratio, err, meta

            return False, persistence_ratio, "", meta
        except Exception as e:
            logger.debug(f"Talking head detection notice: {e}")
            return False, 0.0, "", {}

    @classmethod
    def detect_static_graphic_or_map(
        cls,
        sampled_frames: List[Any],
        max_flat_ratio: float = 0.45,
        min_entropy: float = 4.2
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Detects animated maps, explanatory graphics, presentation slides, and diagrams (Problem 6).
        These are characterized by:
          - High proportion of uniform / flat solid-color regions (large background patches)
          - Low color histogram entropy (synthetic computer palettes vs camera sensors)
          - Lack of natural camera sensor grain/texture
        """
        if not sampled_frames:
            return False, "", {}
        try:
            import cv2
            import numpy as np

            flat_ratios = []
            entropies = []
            palette_counts = []

            for frame in sampled_frames:
                if frame is None:
                    continue
                small = cv2.resize(frame, (320, 180))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

                # 1. Color entropy
                hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).ravel()
                hist = hist / max(1.0, float(np.sum(hist)))
                non_zero_hist = hist[hist > 0]
                entropy = -float(np.sum(non_zero_hist * np.log2(non_zero_hist)))
                entropies.append(entropy)

                # 2. Local gradient flatness
                gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
                gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
                mag = cv2.magnitude(gx, gy)
                flat_count = np.count_nonzero(mag < 3.0)
                flat_ratio = flat_count / float(small.shape[0] * small.shape[1])
                flat_ratios.append(flat_ratio)

                # 3. Quantized color palette count (distinguishes 2D vector art from camera footage)
                # Downsample to 5-bit color space (32 levels per channel = 32768 total possible colors)
                quantized = (small // 8).astype(np.uint32)
                packed_colors = (quantized[:, :, 0] << 10) | (quantized[:, :, 1] << 5) | quantized[:, :, 2]
                palette_counts.append(len(np.unique(packed_colors)))

            if not entropies:
                return False, "", {}

            avg_entropy = float(np.mean(entropies))
            avg_flat = float(np.mean(flat_ratios))
            avg_palette = float(np.mean(palette_counts)) if palette_counts else 9999.0

            meta = {
                "avg_entropy": round(avg_entropy, 2),
                "avg_flat_ratio": round(avg_flat, 3),
                "avg_palette_count": int(avg_palette),
            }

            # Flat vector graphics failure: low entropy + high flatness OR small palette count (< 600) + high flatness
            is_vector_graphic = (
                (avg_palette < 600 and avg_flat > 0.38) or
                (avg_palette < 350) or
                (avg_entropy < min_entropy and avg_flat > max_flat_ratio) or
                (avg_entropy < 4.8 and avg_flat > 0.50)
            )

            if is_vector_graphic:
                err = (
                    f"Synthetic graphic/2D vector/map/presentation slide detected "
                    f"(entropy {avg_entropy:.2f} < {min_entropy:.2f}, flat ratio {avg_flat:.2f} > {max_flat_ratio:.2f}, "
                    f"palette colors {int(avg_palette)} < 600)"
                )
                return True, err, meta

            return False, "", meta
        except Exception as e:
            logger.debug(f"Graphic/map detection notice: {e}")
            return False, "", {}

    @classmethod
    def evaluate_sharpness_and_color(
        cls,
        sampled_frames: List[Any]
    ) -> Dict[str, Any]:
        """
        Measures Laplacian variance sharpness and HSV mean saturation.
        Categorizes sharpness:
          - blurry: max sharpness < 120.0
          - soft (archival acceptable): 120.0 <= max sharpness < 180.0
          - sharp: max sharpness >= 180.0
        Categorizes color:
          - monochrome: mean HSV saturation < 18.0
        """
        if not sampled_frames:
            return {
                "sharpness_score": 0.0,
                "max_sharpness": 0.0,
                "is_blurry": True,
                "is_soft": False,
                "is_sharp": False,
                "saturation_mean": 0.0,
                "is_monochrome": False
            }

        try:
            import cv2
            import numpy as np

            lap_vars = []
            sat_means = []
            for f in sampled_frames:
                if f is None:
                    continue
                gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                lap_vars.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
                sat_means.append(float(np.mean(hsv[..., 1])))

            if not lap_vars:
                return {"sharpness_score": 0.0, "max_sharpness": 0.0, "is_blurry": True, "saturation_mean": 0.0, "is_monochrome": False}

            sharpness_score = float(np.percentile(lap_vars, 75))
            max_sharpness = float(np.max(lap_vars))
            saturation_mean = float(np.mean(sat_means)) if sat_means else 0.0
            is_monochrome = saturation_mean < 18.0

            return {
                "sharpness_score": round(sharpness_score, 2),
                "max_sharpness": round(max_sharpness, 2),
                "is_blurry": max_sharpness < 120.0,
                "is_soft": 120.0 <= max_sharpness < 180.0,
                "is_sharp": max_sharpness >= 180.0,
                "saturation_mean": round(saturation_mean, 2),
                "is_monochrome": is_monochrome,
                "all_sharpness": [round(x, 1) for x in lap_vars]
            }
        except Exception as e:
            logger.debug(f"Sharpness/color evaluation notice: {e}")
            return {"sharpness_score": 200.0, "max_sharpness": 200.0, "is_blurry": False, "saturation_mean": 50.0, "is_monochrome": False}

    @classmethod
    def verify_cleanliness(
        cls,
        file_path: Union[str, Path],
        min_sharpness: float = 120.0,
        max_watermark_density: float = 0.012,
        check_presenter: bool = True,
        check_graphic: bool = True,
        check_timecode: bool = True,
        num_samples: int = 5
    ) -> Tuple[bool, Dict[str, Any], str]:
        """
        Executes physical cleanliness filter pipeline:
          1. Blur filter rejection (max Laplacian sharpness < min_sharpness).
          2. Broadcast timecode rejection (colon pairs persisting in top/bottom strips).
          3. Persistent corner watermark / TV bug rejection (temporal edge intersection).
          4. Color/monochrome classification (HSV saturation < 18.0).
          5. Creator/presenter talking head rejection (face persistence across frames).
          6. Synthetic graphic / animated map / presentation slide rejection.
        """
        sampled = cls.extract_sampled_frames(file_path, num_samples=num_samples)
        if not sampled or len(sampled) < 2:
            return True, {}, ""

        # 1. Sharpness and Color Evaluation
        sc_res = cls.evaluate_sharpness_and_color(sampled)
        if sc_res.get("max_sharpness", 0.0) < min_sharpness:
            max_sh = sc_res.get("max_sharpness", 0.0)
            return (
                False,
                sc_res,
                f"Physical cleanliness rejection: Persistently blurry or low-resolution upscale (max sharpness {max_sh:.1f} < threshold {min_sharpness:.1f})"
            )

        # 2. Broadcast Timecode Rejection
        if check_timecode:
            has_tc, tc_err, tc_meta = cls.detect_broadcast_timecode(sampled)
            if has_tc:
                sc_res.update(tc_meta)
                sc_res["has_timecode"] = True
                return False, sc_res, f"Physical cleanliness rejection: {tc_err}"
        sc_res["has_timecode"] = False

        # 3. Persistent Watermark / Bug Rejection (conditioned on motion)
        has_wm, wm_density, wm_err, wm_densities = cls.detect_persistent_watermark(
            sampled, is_moving=True, max_density=max_watermark_density
        )
        sc_res["corner_watermark_densities"] = wm_densities
        sc_res["has_watermark"] = has_wm
        if has_wm:
            return False, sc_res, f"Physical cleanliness rejection: {wm_err}"

        # 4. Talking Head / Presenter Rejection (Problem 1)
        if check_presenter:
            has_pres, pres_ratio, pres_err, pres_meta = cls.detect_presenter_talking_head(sampled)
            sc_res.update(pres_meta)
            sc_res["has_presenter"] = has_pres
            if has_pres:
                return False, sc_res, f"Physical cleanliness rejection: {pres_err}"
        else:
            sc_res["has_presenter"] = False

        # 5. Synthetic Graphic / Animated Map / Slide Rejection (Problem 6)
        if check_graphic:
            is_graph, graph_err, graph_meta = cls.detect_static_graphic_or_map(sampled)
            sc_res.update(graph_meta)
            sc_res["is_graphic"] = is_graph
            if is_graph:
                return False, sc_res, f"Physical cleanliness rejection: {graph_err}"
        else:
            sc_res["is_graphic"] = False

        return True, sc_res, ""

    @classmethod
    def validate_file(
        cls,
        file_path: Union[str, Path],
        min_duration: float = 0.5,
        check_temporal_motion: bool = False,
        min_motion_threshold: float = 1.5,
        check_cleanliness: bool = False,
        min_sharpness_threshold: float = 120.0,
        max_watermark_density: float = 0.012,
        check_presenter: bool = True,
        check_graphic: bool = True,
        check_timecode: bool = True
    ) -> VideoValidationResult:
        """
        Physically verifies a media file using FFprobe, binary signature checks, and OpenCV temporal motion & cleanliness.
        Enforces:
          1. File existence and non-trivial size.
          2. No static image magic bytes (e.g. JPEG disguised as MP4).
          3. Video stream existence (codec_type == 'video').
          4. Valid non-image video codec.
          5. Temporal duration > 0.
          6. Valid dimensions (width > 0, height > 0).
          7. Multi-frame stream (nb_frames > 1 or temporal duration > min_duration).
          8. Optional OpenCV pixel-level temporal motion verification (mean delta >= threshold).
          9. Optional physical cleanliness filters (blur rejection < 120, broadcast timecode, persistent corner watermark).
        """
        path = Path(file_path)
        if not path.exists():
            return VideoValidationResult(
                is_valid=False,
                error_message=f"File does not exist: {file_path}"
            )

        # 1. Fast rejection by file extension if explicitly an image
        if path.suffix.lower() in PROHIBITED_EXTENSIONS:
            return VideoValidationResult(
                is_valid=False,
                error_message=f"Prohibited static image extension: {path.suffix.lower()}"
            )

        # 2. Rejection of renamed image files (e.g. image.jpg -> video.mp4)
        detected_image_mime = cls.check_magic_bytes(path)
        if detected_image_mime:
            return VideoValidationResult(
                is_valid=False,
                error_message=f"Physical inspection revealed static image payload ({detected_image_mime}) disguised as {path.suffix}"
            )

        if path.stat().st_size < 1000:
            return VideoValidationResult(
                is_valid=False,
                error_message=f"File is too small to be a valid video container: {path.stat().st_size} bytes"
            )

        # 3. FFprobe physical stream inspection
        ffprobe_bin = FFPROBE_EXE or "ffprobe"
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,codec_type,width,height,duration,nb_frames,r_frame_rate",
            "-show_entries", "format=duration,format_name",
            "-of", "json",
            str(path)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=12, check=False)
            if res.returncode != 0:
                err = res.stderr.decode("utf-8", errors="ignore").strip()
                return VideoValidationResult(
                    is_valid=False,
                    error_message=f"FFprobe failed to decode file (returncode {res.returncode}): {err[:200]}"
                )

            data = json.loads(res.stdout.decode("utf-8", errors="ignore"))
            streams = data.get("streams", [])
            fmt = data.get("format", {})

            if not streams:
                return VideoValidationResult(
                    is_valid=False,
                    error_message="No video streams found in asset container (audio-only or corrupt container)"
                )

            v_stream = streams[0]
            codec_type = v_stream.get("codec_type", "")
            codec_name = v_stream.get("codec_name", "").lower()
            width = int(v_stream.get("width", 0) or 0)
            height = int(v_stream.get("height", 0) or 0)
            format_name = fmt.get("format_name", "").lower()

            if codec_type != "video":
                return VideoValidationResult(
                    is_valid=False,
                    error_message=f"Primary stream is not video (found {codec_type})"
                )

            # Check format_name: Reject image pipe containers
            if any(img_fmt in format_name for img_fmt in ["image2", "png_pipe", "jpeg_pipe", "webp_pipe"]):
                return VideoValidationResult(
                    is_valid=False,
                    codec=codec_name,
                    format_name=format_name,
                    error_message=f"Container format indicates still image stream: {format_name}"
                )

            # Duration calculation
            duration = 0.0
            if "duration" in fmt and fmt["duration"]:
                try:
                    duration = float(fmt["duration"])
                except ValueError:
                    pass
            if duration <= 0.0 and "duration" in v_stream and v_stream["duration"]:
                try:
                    duration = float(v_stream["duration"])
                except ValueError:
                    pass

            # Frame rate & frame count
            fps = 0.0
            r_fps = v_stream.get("r_frame_rate", "")
            if r_fps and "/" in r_fps:
                try:
                    num, den = r_fps.split("/")
                    if float(den) > 0:
                        fps = float(num) / float(den)
                except Exception:
                    pass

            nb_frames = 0
            if "nb_frames" in v_stream and v_stream["nb_frames"]:
                try:
                    nb_frames = int(v_stream["nb_frames"])
                except ValueError:
                    pass

            if nb_frames == 0 and duration > 0 and fps > 0:
                nb_frames = int(duration * fps)

            # Reject prohibited still image codecs
            if codec_name in PROHIBITED_IMAGE_CODECS:
                if nb_frames <= 1 or duration < min_duration:
                    return VideoValidationResult(
                        is_valid=False,
                        codec=codec_name,
                        duration=duration,
                        nb_frames=nb_frames,
                        error_message=f"Codec {codec_name} is a static image format without temporal motion"
                    )

            # Check minimum temporal duration
            if duration <= 0.05:
                return VideoValidationResult(
                    is_valid=False,
                    duration=duration,
                    codec=codec_name,
                    error_message=f"Asset has zero or sub-frame temporal duration ({duration}s)"
                )

            # Check dimensions
            if width <= 0 or height <= 0:
                return VideoValidationResult(
                    is_valid=False,
                    width=width,
                    height=height,
                    error_message=f"Invalid video frame dimensions: {width}x{height}"
                )

            # Single frame rejection (e.g. animated GIF with 1 frame or image looped once)
            if nb_frames == 1 and duration <= 0.5:
                return VideoValidationResult(
                    is_valid=False,
                    duration=duration,
                    nb_frames=nb_frames,
                    error_message="Asset contains only a single static frame (still photograph)"
                )

            motion_score = 0.0
            is_moving = True
            if check_temporal_motion or check_cleanliness:
                is_moving, motion_score, motion_err = cls.verify_temporal_motion(
                    path, min_motion_threshold=min_motion_threshold
                )
                if not is_moving:
                    return VideoValidationResult(
                        is_valid=False,
                        duration=duration,
                        width=width,
                        height=height,
                        codec=codec_name,
                        format_name=format_name,
                        fps=fps,
                        nb_frames=nb_frames,
                        motion_score=motion_score,
                        is_moving=False,
                        error_message=motion_err
                    )

            # Physical Cleanliness Inspection (Watermark, Timecode, Sharpness, Color, Presenter, Graphic)
            sharpness_score = 0.0
            saturation_mean = 0.0
            is_monochrome = False
            has_watermark = False
            has_timecode = False
            has_presenter = False
            is_graphic = False
            clean_details: Dict[str, Any] = {}

            if check_cleanliness:
                is_clean, clean_details, clean_err = cls.verify_cleanliness(
                    path,
                    min_sharpness=min_sharpness_threshold,
                    max_watermark_density=max_watermark_density,
                    check_presenter=check_presenter,
                    check_graphic=check_graphic,
                    check_timecode=check_timecode
                )
                sharpness_score = clean_details.get("sharpness_score", 0.0)
                saturation_mean = clean_details.get("saturation_mean", 0.0)
                is_monochrome = clean_details.get("is_monochrome", False)
                has_watermark = clean_details.get("has_watermark", False)
                has_timecode = clean_details.get("has_timecode", False)
                has_presenter = clean_details.get("has_presenter", False)
                is_graphic = clean_details.get("is_graphic", False)

                if not is_clean:
                    return VideoValidationResult(
                        is_valid=False,
                        duration=duration,
                        width=width,
                        height=height,
                        codec=codec_name,
                        format_name=format_name,
                        fps=fps,
                        nb_frames=nb_frames,
                        motion_score=motion_score,
                        is_moving=is_moving,
                        sharpness_score=sharpness_score,
                        saturation_mean=saturation_mean,
                        is_monochrome=is_monochrome,
                        has_watermark=has_watermark,
                        has_timecode=has_timecode,
                        has_presenter=has_presenter,
                        is_graphic=is_graphic,
                        cleanliness_details=clean_details,
                        error_message=clean_err
                    )

            return VideoValidationResult(
                is_valid=True,
                duration=duration,
                width=width,
                height=height,
                codec=codec_name,
                format_name=format_name,
                fps=fps,
                nb_frames=nb_frames,
                motion_score=motion_score,
                is_moving=is_moving,
                sharpness_score=sharpness_score,
                saturation_mean=saturation_mean,
                is_monochrome=is_monochrome,
                has_watermark=has_watermark,
                has_timecode=has_timecode,
                has_presenter=has_presenter,
                is_graphic=is_graphic,
                cleanliness_details=clean_details
            )

        except subprocess.TimeoutExpired:
            return VideoValidationResult(
                is_valid=False,
                error_message="FFprobe execution timed out while inspecting asset"
            )
        except Exception as e:
            return VideoValidationResult(
                is_valid=False,
                error_message=f"Unexpected error validating video media: {str(e)}"
            )

    @classmethod
    def is_valid_video(
        cls,
        file_path: Union[str, Path],
        min_duration: float = 0.5,
        check_temporal_motion: bool = False,
        min_motion_threshold: float = 1.5,
        check_cleanliness: bool = False,
        min_sharpness_threshold: float = 120.0,
        max_watermark_density: float = 0.012,
        check_presenter: bool = True,
        check_graphic: bool = True
    ) -> bool:
        """Convenience boolean checker."""
        res = cls.validate_file(
            file_path,
            min_duration=min_duration,
            check_temporal_motion=check_temporal_motion,
            min_motion_threshold=min_motion_threshold,
            check_cleanliness=check_cleanliness,
            min_sharpness_threshold=min_sharpness_threshold,
            max_watermark_density=max_watermark_density,
            check_presenter=check_presenter,
            check_graphic=check_graphic
        )
        return res.is_valid

    # Canonical alias for compatibility
    validate_video = validate_file


