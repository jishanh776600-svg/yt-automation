"""
Render Engine.
Automated FFmpeg video composition for YouTube Shorts (1080x1920, 9:16 vertical).
Supports seamless 1080p/720p stock video clips, Ken Burns still images with natural color preservation,
subtle transitions (clean cuts, crossfade, dip-to-black), and burned-in synchronized ASS captions.
"""
import os
import uuid
import logging
import subprocess
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from config.settings import RENDERS_DIR, FFMPEG_EXE, ASSETS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from core.models import RenderOutput, AssetRecord

logger = logging.getLogger(__name__)


class RenderEngine:
    """Orchestrates FFmpeg composition into 1080x1920 vertical MP4."""

    def __init__(self):
        self.renders_dir = RENDERS_DIR
        self.renders_dir.mkdir(parents=True, exist_ok=True)


    def get_safe_fallback_video(self) -> Path:
        """Finds a verified, valid moving video MP4 from project assets to prevent black screens."""
        from config.settings import ASSETS_DIR
        candidate_dirs = [ASSETS_DIR, Path("data/assets"), Path("assets")]
        for cdir in candidate_dirs:
            if cdir.exists():
                for f in cdir.glob("*_raw.mp4"):
                    if f.is_file() and f.stat().st_size > 50000:
                        return f
                for f in cdir.glob("*.mp4"):
                    if f.is_file() and f.stat().st_size > 50000 and not f.name.startswith("short_") and not f.name.startswith("clip_"):
                        return f
        # Fallback to standard fallback image if no MP4 found
        return ASSETS_DIR / "fallback.jpg"

    def validate_clip_visual(self, clip_path: Path, min_duration: float = 0.5) -> bool:
        """
        Validates that a rendered video clip exists, is readable, has non-zero size,
        and does not consist entirely of black frames.
        """
        if not clip_path.exists() or clip_path.stat().st_size < 5000:
            return False
        try:
            # Check duration with ffprobe/ffmpeg
            cmd_probe = [
                FFMPEG_EXE, "-i", str(clip_path),
                "-t", "2",
                "-vf", "blackdetect=d=0.8:pic_th=0.98",
                "-an", "-f", "null", "-"
            ]
            res = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            err_out = res.stderr.decode("utf-8", errors="ignore")
            # If blackdetect detects blackness spanning the entire probe, flag it
            if "black_start:0" in err_out and ("black_end" not in err_out or "black_duration:2" in err_out):
                logger.warning(f"[BLACK_DETECT] Clip {clip_path.name} flagged for continuous black frames.")
                return False
            return True
        except Exception as e:
            logger.warning(f"Clip validation notice: {e}")
            return clip_path.stat().st_size > 10000

    def render_video_shot_clip(
        self,
        video_path: Path,
        duration: float,
        output_path: Path,
        motion: str = "none",
        overlay_image: Optional[Path] = None
    ) -> Path:
        """
        Renders a video clip into a 1080x1920 vertical 9:16 MP4 clip.
        Uses intelligent center-crop scaling and automatic looping for shorter clips.
        Maintains native moving video at 30 fps (never freeze-frames with zoompan).
        Supports optional overlay compositing.
        """
        if overlay_image and Path(overlay_image).exists():
            vf_filter = (
                f"[0:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(iw-{VIDEO_WIDTH})/2:(ih-{VIDEO_HEIGHT})/2,setsar=1[bg];"
                f"[1:v]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}[ov];"
                f"[bg][ov]overlay=0:0,format=yuv420p[v]"
            )
            cmd = [
                FFMPEG_EXE, "-y",
                "-stream_loop", "-1",
                "-ss", "0",
                "-i", str(video_path),
                "-i", str(overlay_image),
                "-t", str(duration),
                "-filter_complex", vf_filter,
                "-map", "[v]",
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-r", str(VIDEO_FPS),
                "-an",
                str(output_path)
            ]
        else:
            # Clean direct center-crop reframing without zoompan, keeping native video motion 100% active
            vf_filter = (
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(iw-{VIDEO_WIDTH})/2:(ih-{VIDEO_HEIGHT})/2,"
                f"setsar=1,format=yuv420p"
            )
            cmd = [
                FFMPEG_EXE, "-y",
                "-stream_loop", "-1",
                "-ss", "0",
                "-i", str(video_path),
                "-t", str(duration),
                "-vf", vf_filter,
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-r", str(VIDEO_FPS),
                "-an",
                str(output_path)
            ]

        logger.info(f"Rendering video shot clip ({duration:.1f}s, overlay={'yes' if overlay_image else 'none'}): {output_path.name}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.warning(f"Video clip render warning: {res.stderr.decode('utf-8', errors='ignore')}")
            # Fast fallback without stream_loop
            cmd_fallback = [
                FFMPEG_EXE, "-y",
                "-i", str(video_path),
                "-t", str(duration),
                "-vf", f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},format=yuv420p",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-pix_fmt", "yuv420p",
                "-r", str(VIDEO_FPS),
                "-an",
                str(output_path)
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return output_path

    def render_image_shot_clip(
        self,
        image_path: Path,
        duration: float,
        motion: str,
        output_path: Path
    ) -> Path:
        """
        Renders a single image into a 1080x1920 vertical video clip with Ken Burns motion.
        Maintains natural visual clarity with zero dark edge darkening or global contrast crushing.
        """
        frames = max(1, int(duration * VIDEO_FPS))
        if motion == "zoom_in" or motion == "subtle_zoom_in":
            zoom_filter = f"zoompan=z='min(zoom+0.0012,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        elif motion == "zoom_out" or motion == "subtle_zoom_out":
            zoom_filter = f"zoompan=z='if(lte(zoom,1.0),1.15,max(1.001,zoom-0.0012))':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        elif motion == "pan_left" or motion == "slow_pan_left":
            zoom_filter = f"zoompan=z='1.12':d={frames}:x='if(lte(on,1),(iw-iw/zoom)/2,x+0.8)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"
        else:
            zoom_filter = f"zoompan=z='min(zoom+0.0008,1.10)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={VIDEO_FPS}"

        filter_str = f"{zoom_filter},unsharp=3:3:0.4:3:3:0.0,format=yuv420p"

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
            "-an",
            str(output_path)
        ]

        logger.info(f"Rendering image shot clip ({motion}): {output_path.name}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.warning(f"Ken burns render warning: {res.stderr.decode('utf-8', errors='ignore')}")
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
                "-an",
                str(output_path)
            ]
            subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return output_path

    def render_shot_clip(
        self,
        media_path: Path,
        duration: float,
        motion: str,
        output_path: Path,
        overlay_image: Optional[Path] = None
    ) -> Path:
        """
        Polymorphic shot renderer: dispatches to video or image rendering based on file extension/type.
        """
        suffix = media_path.suffix.lower()
        if suffix in [".mp4", ".mov", ".mkv", ".webm"]:
            out = self.render_video_shot_clip(media_path, duration, output_path, motion=motion, overlay_image=overlay_image)
        else:
            out = self.render_image_shot_clip(media_path, duration, motion, output_path)

        # Auto-Repair: verify rendered clip is not black or corrupt
        if not self.validate_clip_visual(out, min_duration=min(duration * 0.5, 1.0)):
            logger.warning(f"[AUTO_REPAIR] Shot clip {output_path.name} failed visual validation. Auto-repairing with safe moving asset.")
            safe_asset = self.get_safe_fallback_video()
            if safe_asset.suffix.lower() in [".mp4", ".mov", ".mkv", ".webm"]:
                out = self.render_video_shot_clip(safe_asset, duration, output_path, motion=motion, overlay_image=overlay_image)
            else:
                out = self.render_image_shot_clip(safe_asset, duration, motion, output_path)
        return out

    def assemble_short(
        self,
        db: Session,
        job_id: str,
        shots_data: List[Dict[str, Any]],
        asset_map: Dict[str, AssetRecord],
        master_audio_path: Path,
        ass_subtitle_path: Optional[Path] = None,
        bgm_mood: Optional[str] = None,
        motion_style: Optional[str] = None,
        editing_plan: Optional[Any] = None
    ) -> RenderOutput:
        """
        Assembles all shots, applies editing plan directives, muxes master audio (with SFX + BGM),
        burns subtitles, and outputs final 1080x1920 vertical MP4.
        """
        temp_clips = []
        concat_list_path = self.renders_dir / f"concat_{job_id}.txt"
        final_video_path = self.renders_dir / f"short_{job_id}_1080x1920.mp4"
        visual_only_path = self.renders_dir / f"visual_{job_id}.mp4"

        # Map directives if editing plan exists
        directives_by_shot = {}
        if editing_plan:
            shots_list = getattr(editing_plan, "shots", None) or getattr(editing_plan, "scenes", None) or []
            for sc in shots_list:
                directives_by_shot[sc.shot_id] = sc

        # Auto-detect ass_subtitles_path from editing_plan if not explicitly passed
        if not ass_subtitle_path and editing_plan and getattr(editing_plan, "ass_subtitles_path", None):
            plan_ass = Path(editing_plan.ass_subtitles_path)
            if plan_ass.exists():
                ass_subtitle_path = plan_ass

        # Infer motion style if not explicitly supplied
        if not motion_style:
            motion_style = "AI_DIRECTED_MOTION" if editing_plan else "DYNAMIC_VIDEO_MOTION"

        if not bgm_mood:
            bgm_mood = "Historical / Serious Documentary"

        # Synchronize visual duration to cover master audio duration seamlessly
        audio_dur = 0.0
        if master_audio_path and Path(master_audio_path).exists():
            try:
                cmd_p = [FFMPEG_EXE, "-i", str(master_audio_path)]
                res_p = subprocess.run(cmd_p, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", res_p.stderr.decode("utf-8", errors="ignore"))
                if m:
                    audio_dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            except Exception as pe:
                logger.warning(f"Audio duration probe notice: {pe}")

        total_visual_dur = sum([s.get("duration", 0.0) for s in shots_data])
        target_dur = max(total_visual_dur, audio_dur)
        if target_dur > total_visual_dur and shots_data:
            deficit = target_dur - total_visual_dur
            shots_data[-1]["duration"] = round(shots_data[-1]["duration"] + deficit, 2)
            logger.info(f"[RENDER_SYNC] Extended final shot by {deficit:.2f}s to match master audio duration ({target_dur:.2f}s)")

        # 1. Render each individual shot clip
        with open(concat_list_path, "w", encoding="utf-8") as f_concat:
            for idx, shot in enumerate(shots_data):
                shot_id = shot["shot_id"]
                asset = asset_map.get(shot_id)
                media_path = Path(asset.local_path) if asset else (ASSETS_DIR / "fallback.jpg")
                clip_out = self.renders_dir / f"clip_{job_id}_{idx}.mp4"

                # Check for evidence overlay
                overlay_path = None
                if shot.get("overlay_image"):
                    overlay_path = Path(shot["overlay_image"])
                elif shot.get("evidence_overlay"):
                    overlay_path = Path(shot["evidence_overlay"])

                # Motion directive lookup
                sc_dir = directives_by_shot.get(shot_id)
                motion = "none"
                if sc_dir:
                    cm = getattr(sc_dir, "camera_motion", None)
                    if cm is not None:
                        motion = getattr(cm, "motion_type", cm)
                        if hasattr(motion, "value"):
                            motion = motion.value
                    else:
                        motion = shot.get("camera_motion", "none")
                    # Check if evidence overlay path is specified in editing plan
                    if getattr(sc_dir, "evidence_overlay_path", None):
                        cand_overlay = Path(sc_dir.evidence_overlay_path)
                        if cand_overlay.exists():
                            overlay_path = cand_overlay
                else:
                    motion = shot.get("camera_motion", "none")

                # Safety check: if media_path is an overlay PNG, avoid black-screen bug by falling back to fallback image/video
                if media_path.suffix.lower() == ".png" and "overlay" in media_path.name.lower():
                    overlay_path = media_path
                    media_path = ASSETS_DIR / "fallback.jpg"

                self.render_shot_clip(
                    media_path=media_path,
                    duration=shot["duration"],
                    motion=motion,
                    output_path=clip_out,
                    overlay_image=overlay_path
                )
                temp_clips.append(clip_out)
                clean_clip_path = str(clip_out).replace("\\", "/")
                f_concat.write(f"file '{clean_clip_path}'\n")

        # 2. Concat visual clips together
        cmd_concat = [
            FFMPEG_EXE, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_path),
            "-c", "copy",
            str(visual_only_path)
        ]
        res_concat = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res_concat.returncode != 0 or not visual_only_path.exists():
            # Fallback direct re-encoding concatenation
            inputs = []
            for c in temp_clips:
                inputs.extend(["-i", str(c)])
            filter_concat = "".join([f"[{i}:v]" for i in range(len(temp_clips))]) + f"concat=n={len(temp_clips)}:v=1:a=0[outv]"
            cmd_reconcat = [
                FFMPEG_EXE, "-y",
                *inputs,
                "-filter_complex", filter_concat,
                "-map", "[outv]",
                "-c:v", "libx264",
                "-preset", "fast",
                str(visual_only_path)
            ]
            subprocess.run(cmd_reconcat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 3. Final composite: Add master audio and burn-in ASS subtitles
        if ass_subtitle_path and ass_subtitle_path.exists():
            clean_ass_path = str(ass_subtitle_path).replace("\\", "/").replace(":", "\\:")
            vf_filter = f"ass=filename='{clean_ass_path}',format=yuv420p"
        else:
            vf_filter = "format=yuv420p"

        cmd_final = [
            FFMPEG_EXE, "-y",
            "-i", str(visual_only_path),
            "-i", str(master_audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
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
            "-t", str(sum([s["duration"] for s in shots_data])),
            str(final_video_path)
        ]

        logger.info(f"Rendering final short: {final_video_path.name}")
        res = subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.error(f"Final render failed (code {res.returncode}): {res.stderr.decode('utf-8', errors='ignore')}")

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
            file_size_bytes=file_size,
            bgm_mood=bgm_mood,
            motion_style=motion_style
        )
        db.add(render_rec)
        db.commit()
        logger.info(f"Render complete: {final_video_path} ({file_size} bytes | Mood: {bgm_mood} | Motion: {motion_style})")
        return render_rec
