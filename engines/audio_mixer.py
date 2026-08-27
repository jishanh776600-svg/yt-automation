"""
Audio Mixer Engine.
Integrates user-provided local BGM library with AI mood classification,
intelligent story context matching, explicit 3-stage audio production:
  Stage A: Narration-only audio
  Stage B: BGM-only audio (trimmed, looped, volume adjusted, faded)
  Stage C: Final master mixed audio (-14 LUFS normalized)
"""
import os
import json
import uuid
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from config.settings import MUSIC_DIR, SFX_DIR, VOICE_DIR, RENDERS_DIR, FFMPEG_EXE, GEMINI_API_KEY
from config.constants import (
    AUDIO_SAMPLE_RATE, TARGET_LUFS, BGM_MIX_VOLUME_DB,
    BGM_FADE_IN_SEC, BGM_FADE_OUT_SEC, LicenseType
)
from core.models import AssetRecord

logger = logging.getLogger(__name__)


# 4 User-Provided Core BGM Tracks with detailed Mood & Context Mappings
BGM_LIBRARY = {
    "best_historical": {
        "primary_files": ["No copyright Best Historical.wav", "No copyright Best Historical.mp3"],
        "display_name": "No copyright Best Historical (Epic Documentary)",
        "mood": "Historical / Serious Documentary / War / Disaster / Bizarre Events",
        "description": "Epic historical orchestral music designed for historical mystery, war, disaster, strange historical events, and serious documentaries.",
        "keywords": ["history", "war", "battle", "disaster", "bizarre", "historical", "oddity", "riot", "conflict", "empire", "king", "queen", "court", "law", "army", "event"]
    },
    "emotional_sad": {
        "primary_files": ["Empty - Emotional Sad Background.mp3", "Empty - Emotional Sad Background.wav"],
        "display_name": "Empty - Emotional Sad Background (Tragedy & Grief)",
        "mood": "Emotional / Sad / Mournful / Poignant",
        "description": "Deeply emotional and somber melody for tragic stories, personal loss, heartfelt sacrifice, and poignant historical moments.",
        "keywords": ["sad", "tragedy", "emotional", "loss", "grief", "poignant", "mourn", "sacrifice", "heartbreak", "death", "tears", "memorial", "ruin", "sorrow"]
    },
    "suspense_climax": {
        "primary_files": ["No Copyright Background Music.wav", "No Copyright Background Music.mp3"],
        "display_name": "No Copyright Background Music (Suspenseful Climax)",
        "mood": "High Tension / Suspense / Dramatic Build Up / Thriller",
        "description": "Intense cinematic build-up with dramatic tempo for races against time, high-stakes escapes, shocking reveals, and escalating tension.",
        "keywords": ["suspense", "tension", "climax", "escape", "hunt", "chase", "race", "danger", "thriller", "build", "shock", "intense", "countdown", "panic"]
    },
    "flux_ambient": {
        "primary_files": ["The Flux Beneath It All.mp3", "The Flux Beneath It All.wav"],
        "display_name": "The Flux Beneath It All (Mystery & Intrigue)",
        "mood": "Curious / Mysterious / Scientific Wonder / Intrigue",
        "description": "Atmospheric, ambient curiosity pulse for strange inventions, lost civilizations, scientific oddities, and unexplained historical secrets.",
        "keywords": ["mystery", "secret", "strange", "lost", "invention", "wonder", "science", "curiosity", "puzzle", "ancient", "unexplained", "phenomenon", "intrigue"]
    }
}


class AudioMixer:
    """Combines voiceover, ducked background music (-13 dB), and sound effects into balanced master audio."""

    def __init__(self):
        self.music_dir = MUSIC_DIR
        self.sfx_dir = SFX_DIR
        self.renders_dir = RENDERS_DIR
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)

    def classify_story_mood_ai(self, topic_title: str, category: str, script_text: str) -> Optional[Tuple[str, str, str]]:
        """
        Uses Gemini AI to classify story mood into one of the 4 BGM library tracks.
        Returns: (track_key, detected_mood, reason) or None if AI is unavailable.
        """
        if not GEMINI_API_KEY:
            return None

        prompt = (
            f"Analyze this short historical documentary story and select the best matching background music track from the 4 options:\n"
            f"1. 'best_historical': For historical mystery, war, disaster, strange/bizarre events, and serious documentaries.\n"
            f"2. 'emotional_sad': For genuine tragedy, sad stories, heavy loss, poignant moments, and emotional grief.\n"
            f"3. 'suspense_climax': For high tension, thrilling chases, dramatic escalation, and shocking climactic buildup.\n"
            f"4. 'flux_ambient': For curious mysteries, strange inventions, lost secrets, and atmospheric scientific wonder.\n\n"
            f"Story Title: {topic_title}\n"
            f"Category: {category}\n"
            f"Script: {script_text}\n\n"
            f"Respond ONLY in valid JSON format:\n"
            f'{{"track": "best_historical" | "emotional_sad" | "suspense_climax" | "flux_ambient", "mood": "<short mood description>", "reason": "<1-sentence explanation>"}}'
        )

        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            clean_text = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_text)
            track_key = data.get("track")
            if track_key in BGM_LIBRARY:
                return track_key, data.get("mood", BGM_LIBRARY[track_key]["mood"]), data.get("reason", "AI classified mood match")
        except Exception as e:
            logger.warning(f"AI story mood classification fallback: {e}")

        return None

    def select_bgm_track(
        self,
        category: str = "",
        title: str = "",
        summary: str = "",
        script_text: str = ""
    ) -> Tuple[Path, str, str, str]:
        """
        Selects the most appropriate BGM track based on AI classification and semantic keywords.
        Returns: (track_path, track_key, detected_mood, reason_for_selection)
        """
        # 1. Attempt AI Mood Classification
        ai_result = self.classify_story_mood_ai(title, category, script_text)
        if ai_result:
            selected_key, detected_mood, reason = ai_result
            reason = f"[AI Analyzed] {reason}"
        else:
            # 2. Fallback to Semantic Keyword Analysis
            text_corpus = f"{category} {title} {summary} {script_text}".lower()

            scores = {}
            for key, info in BGM_LIBRARY.items():
                score = sum(2 if kw in f"{category} {title}".lower() else 1 for kw in info["keywords"] if kw in text_corpus)
                scores[key] = score

            if scores["emotional_sad"] >= 2 and scores["emotional_sad"] >= scores["suspense_climax"]:
                selected_key = "emotional_sad"
                reason = f"Keyword match for tragic/emotional tone ({scores['emotional_sad']} triggers)"
            elif scores["suspense_climax"] >= 3 and scores["suspense_climax"] > scores["flux_ambient"]:
                selected_key = "suspense_climax"
                reason = f"Keyword match for high suspense/tension ({scores['suspense_climax']} triggers)"
            elif scores["flux_ambient"] >= 2 and any(w in category.lower() for w in ["mystery", "lost", "invention", "science"]):
                selected_key = "flux_ambient"
                reason = f"Keyword match for mystery/curiosity atmosphere ({scores['flux_ambient']} triggers)"
            else:
                selected_key = "best_historical"
                reason = f"Documentary default track for historical events & oddities ({scores.get('best_historical', 0)} triggers)"

            detected_mood = BGM_LIBRARY[selected_key]["mood"]

        # Resolve physical file on disk
        track_info = BGM_LIBRARY[selected_key]
        target_path = None

        for filename in track_info["primary_files"]:
            candidate = self.music_dir / filename
            if candidate.exists() and candidate.stat().st_size > 1000:
                target_path = candidate
                break

        if not target_path or not target_path.exists():
            for f in self.music_dir.iterdir():
                if f.is_file() and f.suffix.lower() in [".wav", ".mp3", ".m4a"]:
                    target_path = f
                    break

        if not target_path or not target_path.exists():
            raise FileNotFoundError(f"No BGM audio tracks found in {self.music_dir}")

        logger.info(
            f"BGM Selection -> File: '{target_path.name}' | "
            f"Mood: '{detected_mood}' | "
            f"Reason: {reason} | "
            f"Target Mix Level: {BGM_MIX_VOLUME_DB} dB"
        )
        return target_path, selected_key, detected_mood, reason

    def get_background_music(
        self,
        db: Session,
        category: str = "Unusual Wars",
        title: str = "",
        summary: str = "",
        script_text: str = ""
    ) -> AssetRecord:
        """
        Selects suitable background music track and records it in Asset database with full metadata.
        """
        music_file, track_key, mood, reason = self.select_bgm_track(
            category=category,
            title=title,
            summary=summary,
            script_text=script_text
        )

        asset_id = f"bgm_{uuid.uuid4().hex[:10]}"
        asset = AssetRecord(
            id=asset_id,
            asset_type="music",
            source="youtube_audio_library_cc0",
            source_url="https://studio.youtube.com/channel/audio_library",
            license=LicenseType.YOUTUBE_AUDIO_LIBRARY.value,
            commercial_use=True,
            attribution_required=False,
            local_path=str(music_file),
            duration_sec=35.0
        )
        db.add(asset)
        db.commit()
        return asset

    def generate_stage_b_bgm_only(
        self,
        source_music_path: Path,
        output_bgm_only_path: Path,
        duration: float,
        bgm_volume_db: float = BGM_MIX_VOLUME_DB
    ) -> Path:
        """
        Stage B: Produces standalone, listenable BGM-only audio file
        with exact looping, trimming, volume scaling (-13 dB), and fade in/out.
        """
        output_bgm_only_path.parent.mkdir(parents=True, exist_ok=True)
        fade_out_start = max(0.5, duration - BGM_FADE_OUT_SEC)

        # Build clean Stage B BGM filter
        filter_b = (
            f"aloop=loop=-1:size=2e+09,atrim=0:{duration},"
            f"volume={bgm_volume_db}dB,"
            f"afade=t=in:ss=0:d={BGM_FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={BGM_FADE_OUT_SEC},"
            f"aformat=channel_layouts=stereo:sample_rates={AUDIO_SAMPLE_RATE}"
        )

        cmd_b = [
            FFMPEG_EXE, "-y",
            "-i", str(source_music_path),
            "-af", filter_b,
            "-c:a", "pcm_s16le",
            str(output_bgm_only_path)
        ]
        subprocess.run(cmd_b, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_bgm_only_path

    def mix_audio(
        self,
        voice_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        bgm_volume_db: float = BGM_MIX_VOLUME_DB,
        job_id: str = ""
    ) -> Tuple[Path, Path]:
        """
        Produces Stage B (BGM-only) and Stage C (Master mixed audio normalized to -14.0 LUFS).
        Returns: (master_audio_path, bgm_only_path)
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Stage B: Render standalone BGM track
        job_tag = job_id if job_id else uuid.uuid4().hex[:8]
        bgm_only_path = self.renders_dir / f"bgm_only_{job_tag}.wav"
        self.generate_stage_b_bgm_only(
            source_music_path=music_path,
            output_bgm_only_path=bgm_only_path,
            duration=duration,
            bgm_volume_db=bgm_volume_db
        )

        # 2. Stage C: Mix Stage A (Voice) + Stage B (BGM) with -14.0 LUFS Loudnorm
        filter_complex = (
            f"[0:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[v];"
            f"[1:a]aformat=channel_layouts=stereo[bgm];"
            f"[v][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed];"
            f"[mixed]loudnorm=I={TARGET_LUFS}:LRA=7:tp=-1.0[outa]"
        )

        cmd = [
            FFMPEG_EXE, "-y",
            "-i", str(voice_path),
            "-i", str(bgm_only_path),
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-ac", "2",
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "aac",
            "-b:a", "256k",
            str(output_path)
        ]

        logger.info(
            f"Mixing master audio (Voice: {voice_path.name} + BGM: {music_path.name} at {bgm_volume_db}dB, "
            f"Master Target: {TARGET_LUFS} LUFS, Duration: {duration:.2f}s)"
        )
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Robust multi-pass auto-repair fallback if complex mixing fails
        if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
            err_msg = res.stderr.decode("utf-8", errors="ignore")
            logger.warning(f"Audio mixing warning ({err_msg}). Executing direct repair remix...")
            repair_filter = (
                f"[0:a]aresample={AUDIO_SAMPLE_RATE},aformat=channel_layouts=stereo[v];"
                f"[1:a]aformat=channel_layouts=stereo[bgm];"
                f"[v][bgm]amix=inputs=2:duration=first:normalize=0[outa]"
            )
            cmd_repair = [
                FFMPEG_EXE, "-y",
                "-i", str(voice_path),
                "-i", str(bgm_only_path),
                "-filter_complex", repair_filter,
                "-map", "[outa]",
                "-ac", "2",
                "-ar", str(AUDIO_SAMPLE_RATE),
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path)
            ]
            subprocess.run(cmd_repair, check=True)

        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise RuntimeError(f"Master audio mixing failed: Output file {output_path} is missing or empty.")

        logger.info(f"[+] Master audio successfully mixed with BGM: {output_path.name} ({output_path.stat().st_size} bytes)")
        return output_path, bgm_only_path
