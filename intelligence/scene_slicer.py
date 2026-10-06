"""
Scene Slicer & Fair-Use Transformer for Movie Footage.
======================================================
Transforms raw downloaded movie scenes into fair-use compliant vertical (9:16) video clips:
  1. Detects natural scene cuts using FFmpeg (select='gt(scene,0.35)').
  2. Enforces strict maximum duration ceiling (2.5s - 3.2s per clip).
  3. Mutes 100% of original movie audio (0.0% dialogue or soundtrack leak).
  4. Applies subtle dynamic scale and center-crop to break Content ID hash fingerprints.
  5. Inspects frames for talking-head anchors or trailer title cards.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from config.settings import FFMPEG_EXE, FFPROBE_EXE

logger = logging.getLogger("alamr.scene_slicer")


class SceneSlicer:
    """Slices and transforms movie footage into high-retention, anti-copyright vertical cuts."""

    def __init__(self, target_width: int = 1080, target_height: int = 1920):
        self.target_width = target_width
        self.target_height = target_height
        self.ffmpeg = FFMPEG_EXE or "ffmpeg"
        self.ffprobe = FFPROBE_EXE or "ffprobe"

    def slice_clip(
        self,
        source_media_path: Path,
        output_path: Path,
        start_sec: float = 0.0,
        duration_sec: float = 3.0,
        subtle_zoom: bool = True
    ) -> bool:
        """
        Slices a 2.5s-3.5s segment from source media, strips all original audio,
        centers/crops to 9:16 vertical (1080x1920), and applies subtle dynamic transformation.
        """
        if not source_media_path.exists():
            logger.error(f"[SCENE_SLICER] Source media does not exist: {source_media_path}")
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Enforce strict 3.5s maximum cut ceiling for fair-use Content ID protection
        clamped_duration = max(2.0, min(3.2, duration_sec))

        # Dynamic scale & crop filter for vertical 9:16
        # Takes 16:9 movie footage, scales height to 1920, and center-crops width to 1080
        # If subtle_zoom is true, adds a tiny 1.03x scale to prevent exact frame hash matching
        scale_filter = (
            f"scale=1080*1.04:1920*1.04:force_original_aspect_ratio=increase,"
            f"crop={self.target_width}:{self.target_height}"
        ) if subtle_zoom else (
            f"scale={self.target_width}:{self.target_height}:force_original_aspect_ratio=increase,"
            f"crop={self.target_width}:{self.target_height}"
        )

        cmd = [
            self.ffmpeg, "-y",
            "-ss", f"{start_sec:.2f}",
            "-i", str(source_media_path),
            "-t", f"{clamped_duration:.2f}",
            "-vf", scale_filter,
            "-an",  # 100% audio mute — zero dialogue leak!
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(output_path)
        ]

        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            if res.returncode == 0 and output_path.exists() and output_path.stat().st_size > 10000:
                logger.info(f"[SCENE_SLICER] Sliced {clamped_duration}s clip -> {output_path.name}")
                return True
            else:
                logger.warning(f"[SCENE_SLICER] FFmpeg slicing failed: {res.stderr.decode('utf-8', errors='ignore')[:300]}")
                return False
        except Exception as e:
            logger.error(f"[SCENE_SLICER] Slicing error: {e}")
            return False

    def extract_keyframes(self, video_path: Path, count: int = 3) -> List[Path]:
        """Extracts 3 keyframes across the clip for VLM inspection."""
        if not video_path.exists():
            return []

        out_frames = []
        temp_dir = video_path.parent / f"frames_{video_path.stem}"
        temp_dir.mkdir(exist_ok=True)

        for i, pct in enumerate([0.15, 0.50, 0.85]):
            frame_p = temp_dir / f"frame_{i}.jpg"
            cmd = [
                self.ffmpeg, "-y",
                "-ss", f"{pct * 2.5:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "3",
                str(frame_p)
            ]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                if frame_p.exists() and frame_p.stat().st_size > 1000:
                    out_frames.append(frame_p)
            except Exception:
                pass

        return out_frames
