"""
Render Engine.
Automated FFmpeg video composition for YouTube Shorts (1080x1920, 9:16 vertical).
Applies Ken Burns zoom/pan motion to still images, sequences visual shots,
mixes audio, and burns in synchronized stylized ASS captions.
"""
import os
import uuid
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from config.settings import RENDERS_DIR, FFMPEG_EXE
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from core.models import RenderOutput, AssetRecord

logger = logging.getLogger(__name__)


class RenderEngine:
    """Orchestrates FFmpeg composition into 1080x1920 vertical MP4."""

    def __init__(self):
        self.renders_dir = RENDERS_DIR
        self.renders_dir.mkdir(parents=True, exist_ok=True)

    def render_shot_clip(self, image_path: Path, duration: float, motion: str, output_path: Path) -> Path:
        """
        Renders a single image into a 1080x1920 vertical video clip with Ken Burns motion.
        """
        frames = int(duration * VIDEO_FPS)
        # Ken Burns zoom expressions for 1080x1920 with high-precision subpixel motion
        if motion == "zoom_in":
            zoom_filter = f"zoompan=z='min(zoom+0.0018,1.28)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        elif motion == "zoom_out":
            zoom_filter = f"zoompan=z='if(lte(zoom,1.0),1.28,max(1.001,zoom-0.0018))':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        elif motion == "pan_left":
            zoom_filter = f"zoompan=z='1.18':d={frames}:x='if(lte(on,1),(iw-iw/zoom)/2,x+1.2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        else:
            zoom_filter = f"zoompan=z='min(zoom+0.0015,1.22)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"

        # Cinematic clarity filter: subtle sharpening (unsharp) + contrast enhancement + soft vignette
        filter_str = f"{zoom_filter},unsharp=5:5:0.8:5:5:0.0,eq=contrast=1.08:saturation=1.12:brightness=0.01,vignette=PI/4.5,format=yuv420p"

        cmd = [
            FFMPEG_EXE, "-y",
            "-loop", "1",
            "-i", str(image_path),
            "-vf", filter_str,
            "-t", str(duration),
            "-c:v", "libx264",
            "-preset", "slow",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", str(VIDEO_FPS),
            str(output_path)
        ]

        logger.info(f"Rendering shot clip ({motion}): {output_path.name}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.warning(f"Ken burns render warning: {res.stderr.decode('utf-8', errors='ignore')}")
            # Fallback simple image-to-video loop
            cmd_fallback = [
                FFMPEG_EXE, "-y",
                "-loop", "1",
                "-i", str(image_path),
                "-t", str(duration),
                "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT},format=yuv420p",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-r", str(VIDEO_FPS),
                str(output_path)
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return output_path

    def assemble_short(
        self,
        db: Session,
        job_id: str,
        shots_data: List[Dict[str, Any]],
        asset_map: Dict[str, AssetRecord],
        master_audio_path: Path,
        ass_subtitle_path: Optional[Path] = None
    ) -> RenderOutput:
        """
        Assembles all shots, applies transitions, muxes master audio, burns subtitles,
        and outputs final 1080x1920 vertical MP4.
        """
        temp_clips = []
        concat_list_path = self.renders_dir / f"concat_{job_id}.txt"
        final_video_path = self.renders_dir / f"short_{job_id}_1080x1920.mp4"
        visual_only_path = self.renders_dir / f"visual_{job_id}.mp4"

        # 1. Render each individual shot clip
        with open(concat_list_path, "w", encoding="utf-8") as f_concat:
            for idx, shot in enumerate(shots_data):
                shot_id = shot["shot_id"]
                asset = asset_map.get(shot_id)
                img_path = Path(asset.local_path) if asset else (ASSETS_CACHE_DIR / "fallback.jpg")
                clip_out = self.renders_dir / f"clip_{job_id}_{idx}.mp4"

                self.render_shot_clip(
                    image_path=img_path,
                    duration=shot["duration"],
                    motion=shot.get("camera_motion", "zoom_in"),
                    output_path=clip_out
                )
                temp_clips.append(clip_out)
                # Write to concat list (escaped forward slashes for FFmpeg)
                f_concat.write(f"file '{str(clip_out).replace('\\', '/')}'\n")

        # 2. Concat visual clips together
        cmd_concat = [
            FFMPEG_EXE, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(visual_only_path)
        ]
        subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 3. Final composite: Add master audio and burn-in ASS subtitles
        # Escape path for subtitle filter in Windows FFmpeg
        if ass_subtitle_path and ass_subtitle_path.exists():
            clean_ass_path = str(ass_subtitle_path).replace("\\", "/").replace(":", "\\:")
            vf_filter = f"ass='{clean_ass_path}',format=yuv420p"
        else:
            vf_filter = "format=yuv420p"

        cmd_final = [
            FFMPEG_EXE, "-y",
            "-i", str(visual_only_path),
            "-i", str(master_audio_path),
            "-vf", vf_filter,
            "-c:v", "libx264",
            "-profile:v", "high",
            "-level", "4.2",
            "-preset", "slow",
            "-b:v", "14000k",
            "-maxrate", "18000k",
            "-bufsize", "25000k",
            "-c:a", "aac",
            "-b:a", "256k",
            "-shortest",
            str(final_video_path)
        ]

        logger.info(f"Rendering final short: {final_video_path.name}")
        res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Cleanup temp clips
        try:
            concat_list_path.unlink(missing_ok=True)
            visual_only_path.unlink(missing_ok=True)
            for c in temp_clips:
                c.unlink(missing_ok=True)
        except Exception:
            pass

        file_size = final_video_path.stat().st_size if final_video_path.exists() else 0
        total_duration = sum([s["duration"] for s in shots_data])

        render_rec = RenderOutput(
            id=f"rnd_{uuid.uuid4().hex[:10]}",
            job_id=job_id,
            video_path=str(final_video_path),
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            fps=VIDEO_FPS,
            duration_sec=total_duration,
            video_codec="h264",
            audio_codec="aac",
            file_size_bytes=file_size
        )
        db.add(render_rec)
        db.commit()
        logger.info(f"Render complete: {final_video_path} ({file_size} bytes)")
        return render_rec
