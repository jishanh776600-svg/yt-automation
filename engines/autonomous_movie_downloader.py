"""
Autonomous Movie Downloader: 100% Headless 720p Movie Acquisition.
==================================================================
Acquires full 720p feature film media (~700MB - 1GB) completely autonomously
on cloud runners (GitHub Actions) without local PC intervention.

Multi-Strategy Acquisition:
  1. Direct cloud archive / CDN streaming mirrors from MovieCatalog.
  2. yt-dlp multi-fragment stream retrieval (Internet Archive, Dailymotion, public film archives).
  3. Master scene reel assembly (compiles major sequence clips if single full rip unavailable).
"""

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from config.settings import FFMPEG_EXE, FFPROBE_EXE, RENDERS_DIR
from core.movie_catalog import MovieEntry

logger = logging.getLogger("alamr.movie_downloader")


class AutonomousMovieDownloader:
    """Headless cloud downloader for 720p movie footage."""

    def __init__(
        self,
        target_dir: Optional[Path] = None,
        max_duration_seconds: int = 7200,
        min_duration_seconds: int = 300,
    ):
        self.target_dir = target_dir or Path("data/movies")
        self.target_dir.mkdir(parents=True, exist_ok=True)
        self.max_duration = max_duration_seconds
        self.min_duration = min_duration_seconds
        self.ffmpeg = FFMPEG_EXE or "ffmpeg"
        self.ffprobe = FFPROBE_EXE or "ffprobe"

    def get_video_metadata(self, file_path: Path) -> Dict[str, Any]:
        """Probes video duration, width, height, and codec using ffprobe."""
        if not file_path.exists():
            return {}

        cmd = [
            self.ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                duration = float(data.get("format", {}).get("duration", 0.0))
                width, height = 0, 0
                for stream in data.get("streams", []):
                    if stream.get("codec_type") == "video":
                        width = int(stream.get("width", 0))
                        height = int(stream.get("height", 0))
                        break
                return {
                    "duration_sec": duration,
                    "width": width,
                    "height": height,
                    "size_mb": round(file_path.stat().st_size / (1024 * 1024), 2),
                }
        except Exception as e:
            logger.warning(f"[MOVIE_PROBE] ffprobe error on {file_path.name}: {e}")

        return {}

    def is_valid_movie_file(self, file_path: Path) -> bool:
        """Verifies downloaded movie has valid duration and resolution."""
        meta = self.get_video_metadata(file_path)
        if not meta:
            return False

        dur = meta.get("duration_sec", 0.0)
        width = meta.get("width", 0)
        height = meta.get("height", 0)

        # Must have at least min_duration (5 mins) and at least 640x360
        has_dur = dur >= self.min_duration
        has_res = width >= 640 and height >= 360

        logger.info(
            f"[MOVIE_VERIFY] {file_path.name} -> Duration: {dur:.1f}s ({dur/60:.1f}m), "
            f"Resolution: {width}x{height}, Size: {meta.get('size_mb')}MB (Valid: {has_dur and has_res})"
        )
        return has_dur and has_res

    def download_movie_720p(self, movie: MovieEntry) -> Optional[Path]:
        """
        100% autonomously acquires the 720p movie file for this title.
        Returns local Path on success, None on failure.
        """
        clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", movie.title.lower())
        final_movie_path = self.target_dir / f"{clean_slug}_{movie.year}_720p.mp4"

        # Check local cache first
        if final_movie_path.exists() and self.is_valid_movie_file(final_movie_path):
            logger.info(f"[MOVIE_DOWNLOAD] Cache hit: {final_movie_path.name} already verified on disk.")
            return final_movie_path

        logger.info(f"[MOVIE_DOWNLOAD] Starting 100% autonomous 720p acquisition for: {movie.title} ({movie.year})")

        # Resolve egress proxy (WARP sidecar on 127.0.0.1:1080)
        proxy_url = os.environ.get("YOUTUBE_PROXY") or os.environ.get("ALL_PROXY") or ""
        if not proxy_url:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.3)
                    if sock.connect_ex(("127.0.0.1", 1080)) == 0:
                        proxy_url = "socks5h://127.0.0.1:1080"
            except Exception:
                pass

        # Strategy 1: Check direct cloud download URLs from catalog
        direct_urls = getattr(movie, "direct_download_urls", [])
        for url in direct_urls:
            if not url:
                continue
            logger.info(f"[MOVIE_DOWNLOAD] Trying direct cloud archive URL: {url}")
            try:
                # Use aria2c if available on runner for multi-connection speed, else curl/yt-dlp
                aria_cmd = [
                    "aria2c",
                    "-x", "8",
                    "-s", "8",
                    "--max-tries=3",
                    "--retry-wait=2",
                    "-o", final_movie_path.name,
                    "-d", str(self.target_dir),
                    url
                ]
                res = subprocess.run(aria_cmd, capture_output=True, timeout=180)
                if res.returncode == 0 and final_movie_path.exists() and self.is_valid_movie_file(final_movie_path):
                    logger.info(f"[MOVIE_DOWNLOAD] Successfully fetched {movie.title} via direct archive mirror!")
                    return final_movie_path
            except Exception as e:
                logger.warning(f"[MOVIE_DOWNLOAD] Direct URL failed: {e}")

        # Strategy 2: Autonomous yt-dlp 720p full stream locator
        import yt_dlp
        search_queries = [
            f"{movie.title} {movie.year} full movie 720p english",
            f"{movie.title} {movie.year} full movie stream",
            f"{movie.title} {movie.year} complete movie film 720p"
        ]

        out_template = str(self.target_dir / f"{clean_slug}_{movie.year}_720p.%(ext)s")

        for query in search_queries:
            logger.info(f"[MOVIE_DOWNLOAD] Searching cloud video streams for: '{query}'...")
            ydl_opts: Dict[str, Any] = {
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "outtmpl": out_template,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 30,
                # Match full-length streams (> 45 minutes)
                "match_filter": yt_dlp.utils.match_filter_func("duration >= 2700 & duration <= 8400"),
                "concurrent_fragments": 5,
            }
            if proxy_url:
                ydl_opts["proxy"] = proxy_url

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([f"ytsearch5:{query}"])

                # Check if file was produced
                candidates = list(self.target_dir.glob(f"{clean_slug}_{movie.year}_720p.*"))
                for c in candidates:
                    if self.is_valid_movie_file(c):
                        logger.info(f"[MOVIE_DOWNLOAD] Successfully acquired full 720p movie: {c.name}")
                        return c
            except Exception as ydl_err:
                logger.warning(f"[MOVIE_DOWNLOAD] Stream query '{query}' notice: {ydl_err}")

        # Strategy 3: Multi-Sequence Master Reel Synthesis
        # If full 90-minute film rip is blocked, download 4 major official 1080p/720p
        # sequence scene clips (20-30 mins total) and stitch them into a master reel
        logger.info(f"[MOVIE_DOWNLOAD] Deploying Strategy 3: Compiling master sequence reel for {movie.title}...")
        reel_path = self._compile_master_sequence_reel(movie, proxy_url)
        if reel_path and reel_path.exists() and self.is_valid_movie_file(reel_path):
            return reel_path

        logger.error(f"[MOVIE_DOWNLOAD] All acquisition strategies exhausted for {movie.title} ({movie.year})")
        return None

    def _compile_master_sequence_reel(self, movie: MovieEntry, proxy_url: str) -> Optional[Path]:
        """Downloads all official key scene setpieces and stitches into a 15-25m master reel."""
        import yt_dlp
        clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", movie.title.lower())
        reel_output = self.target_dir / f"{clean_slug}_{movie.year}_master_reel.mp4"

        reel_parts_dir = self.target_dir / f"parts_{clean_slug}"
        reel_parts_dir.mkdir(parents=True, exist_ok=True)

        downloaded_parts: List[Path] = []
        queries = movie.footage_search_queries + [
            f"{movie.title} {movie.year} opening scene 1080p",
            f"{movie.title} {movie.year} chase scene 1080p",
            f"{movie.title} {movie.year} climax scene 1080p",
        ]

        for idx, q in enumerate(queries[:5]):
            part_template = str(reel_parts_dir / f"part_{idx:02d}.%(ext)s")
            ydl_opts = {
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "outtmpl": part_template,
                "quiet": True,
                "no_warnings": True,
                "socket_timeout": 20,
            }
            if proxy_url:
                ydl_opts["proxy"] = proxy_url

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([f"ytsearch1:{q}"])
                matches = list(reel_parts_dir.glob(f"part_{idx:02d}.*"))
                if matches and matches[0].stat().st_size > 5_000_000:
                    downloaded_parts.append(matches[0])
            except Exception:
                pass

        if len(downloaded_parts) >= 2:
            concat_txt = reel_parts_dir / "concat.txt"
            with open(concat_txt, "w", encoding="utf-8") as f:
                for p in downloaded_parts:
                    f.write(f"file '{p.resolve().as_posix()}'\n")

            cmd = [
                self.ffmpeg, "-y", "-loglevel", "error",
                "-f", "concat", "-safe", "0",
                "-i", str(concat_txt),
                "-c:v", "libx264", "-c:a", "aac",
                str(reel_output)
            ]
            try:
                subprocess.run(cmd, check=True, timeout=120)
                if reel_output.exists():
                    logger.info(f"[MASTER_REEL] Compiled {len(downloaded_parts)} scene sequences into master reel.")
                    return reel_output
            except Exception as e:
                logger.error(f"[MASTER_REEL] Failed stitching master reel: {e}")

        return None
