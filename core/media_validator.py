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
from dataclasses import dataclass
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
    error_message: Optional[str] = None

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
            "error_message": self.error_message,
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
    def validate_file(cls, file_path: Union[str, Path], min_duration: float = 0.5) -> VideoValidationResult:
        """
        Physically verifies a media file using FFprobe and binary signature checks.
        Enforces:
          1. File existence and non-trivial size.
          2. No static image magic bytes (e.g. JPEG disguised as MP4).
          3. Video stream existence (codec_type == 'video').
          4. Valid non-image video codec.
          5. Temporal duration > 0.
          6. Valid dimensions (width > 0, height > 0).
          7. Multi-frame stream (nb_frames > 1 or temporal duration > min_duration).
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

            return VideoValidationResult(
                is_valid=True,
                duration=duration,
                width=width,
                height=height,
                codec=codec_name,
                format_name=format_name,
                fps=fps,
                nb_frames=nb_frames
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
    def is_valid_video(cls, file_path: Union[str, Path], min_duration: float = 0.5) -> bool:
        """Convenience boolean checker."""
        res = cls.validate_file(file_path, min_duration=min_duration)
        return res.is_valid
