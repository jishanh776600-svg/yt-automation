"""
Autonomous Movie Recap Video Composer.
=======================================
Broadcast-grade 1080x1080 (1:1 Square) Episodic Movie Recap Pipeline.
Invariants:
  - 1:1 Square (1080x1080) canvas with black padding.
  - Top Banner: EPISODE {ep}/{total} • {MOVIE TITLE} (Arial Black, Gold/White)
  - Bottom Banner: 🔴 SUBSCRIBE FOR EPISODE {next_ep}! (Arial Black, Red/White)
  - Word-level / phrase-level dynamic karaoke subtitles (Impact, White/Cyan).
  - Method C Censorship: Noir desaturation (hue=s=0, contrast=1.35) on high-impact violence.
  - Narration: Kokoro TTS (af_bella, speed=1.14).
  - BGM: Blade Runner Dark Ambient ducked at volume=0.154 (Zero SFX).
"""

import os
import re
import json
import logging
import subprocess
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np

logger = logging.getLogger("alamr.movie_recap_composer")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BGM_PATH = PROJECT_ROOT / "assets" / "music" / "ambient_dark.wav"
# Fallback BGM options
FALLBACK_BGM_PATHS = [
    PROJECT_ROOT / "data" / "audio" / "bgm_blade_runner_dark.mp3",
    Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\audio\bgm_blade_runner_dark.mp3"),
    PROJECT_ROOT / "assets" / "music" / "dramatic_tension.wav"
]


def format_ass_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def build_square_ass_subtitles(
    beats: List[Dict[str, Any]],
    ass_path: Path,
    title_text: str,
    footer_text: str
) -> Path:
    """Builds broadcast ASS subtitles with top/bottom permanent banners and dynamic centered subtitles."""
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: HeaderBanner,Arial Black,50,&H0000FFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,2,0,1,5,2,8,20,20,80,1
Style: FooterBanner,Arial Black,46,&H000000FF,&H000000FF,&H00FFFFFF,&H80000000,-1,0,0,0,100,100,2,0,1,4,2,2,20,20,85,1
Style: SubtitleStyle,Impact,45,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,4,2,2,40,40,285,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    tot_end = beats[-1].get("audio_end", 60.0) + 0.5
    s_tot = format_ass_time(0.0)
    e_tot = format_ass_time(tot_end)
    events.append(f"Dialogue: 1,{s_tot},{e_tot},HeaderBanner,,0,0,0,,{title_text}")
    events.append(f"Dialogue: 1,{s_tot},{e_tot},FooterBanner,,0,0,0,,{{\\c&H0000FF&}}{footer_text}{{\\c&HFFFFFF&}}")

    for b in beats:
        text = b.get("text", "").upper().strip()
        if not text:
            continue
        words = text.split()
        chunk_size = 5
        chunks = [' '.join(words[i:i+chunk_size]) for i in range(0, len(words), chunk_size)]
        dur = b.get("audio_dur", len(words) * 0.38)
        chunk_dur = dur / max(1, len(chunks))
        start_t = b.get("audio_start", 0.0)

        for c_idx, chunk in enumerate(chunks):
            c_start = start_t + c_idx * chunk_dur
            c_end = c_start + chunk_dur
            events.append(
                f"Dialogue: 2,{format_ass_time(c_start)},{format_ass_time(c_end)},SubtitleStyle,,0,0,0,,{{\\c&H00FFFF&}}{chunk}{{\\c&HFFFFFF&}}"
            )

    ass_path.parent.mkdir(parents=True, exist_ok=True)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header + "\n".join(events))
    return ass_path


class MovieRecapComposer:
    """Renders 1080x1080 square cinematic movie recaps with Method C editorial safeguards."""

    def __init__(self, ffmpeg_exe: str = "ffmpeg"):
        self.ffmpeg_exe = ffmpeg_exe

    def resolve_bgm_path(self) -> Optional[Path]:
        for p in [DEFAULT_BGM_PATH] + FALLBACK_BGM_PATHS:
            if p.exists() and p.stat().st_size > 10000:
                return p
        return None

    def render_movie_short(
        self,
        clip_paths: List[Path],
        beat_metadata: List[Dict[str, Any]],
        voice_audio_path: Path,
        output_mp4: Path,
        movie_title: str,
        part_number: int,
        total_parts: int,
        work_dir: Optional[Path] = None,
    ) -> Path:
        """
        Renders complete 1:1 Square Short from sliced clips and synchronized narration.
        """
        if not work_dir:
            work_dir = output_mp4.parent / f"tmp_{output_mp4.stem}"
        work_dir.mkdir(parents=True, exist_ok=True)
        clips_work = work_dir / "clips"
        clips_work.mkdir(parents=True, exist_ok=True)

        title_header = f"EPISODE {part_number:02d}/{total_parts:02d} • {movie_title.upper()}"
        next_part = part_number + 1 if part_number < total_parts else 1
        footer_sub = f"🔴 SUBSCRIBE FOR EPISODE {next_part:02d}!"

        # 1. Prepare and trim individual clips to match beat audio durations
        clip_list_file = work_dir / "clips_concat.txt"
        processed_clip_paths = []

        with open(clip_list_file, "w", encoding="utf-8") as f_list:
            for idx, beat in enumerate(beat_metadata):
                src_clip = clip_paths[idx % len(clip_paths)]
                dur = beat.get("audio_dur", 3.5)
                is_impact = beat.get("is_impact", False)

                out_clip = clips_work / f"beat_{idx:02d}.mp4"
                base_filter = "scale=1080:-2,setsar=1,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black"
                if is_impact:
                    filter_str = f"{base_filter},hue=s=0,eq=contrast=1.35:brightness=-0.04,fps=24"
                else:
                    filter_str = f"{base_filter},fps=24"

                cmd = [
                    self.ffmpeg_exe, "-y",
                    "-i", str(src_clip),
                    "-t", f"{dur:.3f}",
                    "-vf", filter_str,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                    "-an",
                    str(out_clip)
                ]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                f_list.write(f"file '{out_clip.resolve().as_posix()}'\n")
                processed_clip_paths.append(out_clip)

        # 2. Concatenate video stream
        video_concat_mp4 = work_dir / "video_concat.mp4"
        cmd_concat = [
            self.ffmpeg_exe, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(clip_list_file),
            "-c", "copy",
            str(video_concat_mp4)
        ]
        subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        # 3. Audio Ducking with Dark Ambient BGM
        # Get duration of voice
        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(voice_audio_path)]
        res = subprocess.run(probe_cmd, capture_output=True, text=True)
        tot_dur = float(res.stdout.strip()) if res.stdout.strip() else 55.0

        bgm_path = self.resolve_bgm_path()
        mixed_audio = work_dir / "mixed_audio.wav"

        if bgm_path and bgm_path.exists():
            fade_start = max(1.0, tot_dur - 3.5)
            mix_cmd = [
                self.ffmpeg_exe, "-y",
                "-i", str(voice_audio_path),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-filter_complex",
                f"[1:a]volume=0.154,afade=t=out:st={fade_start:.1f}:d=3[bgm];"
                "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]",
                "-map", "[aout]",
                "-c:a", "pcm_s16le",
                str(mixed_audio)
            ]
            subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        else:
            shutil.copy2(voice_audio_path, mixed_audio)

        # 4. Generate Broadcast ASS Subtitles
        ass_path = work_dir / "subtitles.ass"
        build_square_ass_subtitles(
            beats=beat_metadata,
            ass_path=ass_path,
            title_text=title_header,
            footer_text=footer_sub
        )

        # 5. Final Master Composition
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        clean_ass = str(ass_path.resolve()).replace("\\", "/")

        final_cmd = [
            self.ffmpeg_exe, "-y",
            "-i", str(video_concat_mp4),
            "-i", str(mixed_audio),
            "-vf", f"subtitles='{clean_ass}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(output_mp4)
        ]
        subprocess.run(final_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        logger.info(f"[MOVIE_RECAP_COMPOSER] Finished 1:1 Square render: {output_mp4} ({output_mp4.stat().st_size / (1024*1024):.2f} MB)")
        return output_mp4
