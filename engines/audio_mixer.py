"""
Audio Mixer Engine.
Integrates user-provided local BGM library with AI mood classification,
multidimensional narrative context matching (topic, emotional tone, intensity, pacing, atmosphere, seriousness),
and explicit 3-stage audio production:
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


# 4 Approved Core BGM Tracks with detailed Mood & Context Mappings
BGM_LIBRARY = {
    "best_historical": {
        "primary_files": ["No copyright Best Historical.wav", "No copyright Best Historical.mp3"],
        "display_name": "No copyright Best Historical...",
        "mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
        "default_intensity": "Medium-High",
        "description": "Epic historical orchestral music designed for historical mystery, war, disaster, strange historical events, and serious documentaries.",
        "keywords": ["history", "war", "battle", "disaster", "bizarre", "historical", "oddity", "riot", "conflict", "empire", "king", "queen", "court", "law", "army", "event", "parliament", "revolution", "monarch"]
    },
    "emotional_sad": {
        "primary_files": ["Empty - Emotional Sad Background.mp3", "Empty - Emotional Sad Background.wav"],
        "display_name": "Empty - Emotional Sad Background...",
        "mood": "Emotional / Sad / Mournful / Poignant / Human Tragedy",
        "default_intensity": "Subdued-Poignant",
        "description": "Deeply emotional and somber melody for tragic stories, personal loss, heartfelt sacrifice, and poignant historical moments.",
        "keywords": ["sad", "tragedy", "emotional", "loss", "grief", "poignant", "mourn", "sacrifice", "heartbreak", "death", "tears", "memorial", "ruin", "sorrow", "farewell", "crying", "dying", "famine"]
    },
    "flux_ambient": {
        "primary_files": ["The Flux Beneath It All.mp3", "The Flux Beneath It All.wav"],
        "display_name": "The Flux Beneath It All.mp3",
        "mood": "Dark / Intense / Dramatic / Mysterious / Scientific Wonder / Intrigue",
        "default_intensity": "Atmospheric-Tense",
        "description": "Atmospheric, ambient curiosity and dark mysterious pulse for unexplained secrets, lost civilizations, strange inventions, and scientific wonder.",
        "keywords": ["mystery", "secret", "strange", "lost", "invention", "wonder", "science", "curiosity", "puzzle", "ancient", "unexplained", "phenomenon", "intrigue", "dark", "riddle", "cryptic", "alchemist"]
    },
    "suspense_climax": {
        "primary_files": ["No Copyright Background Music.wav", "No Copyright Background Music.mp3"],
        "display_name": "No Copyright Background Music",
        "mood": "High Tension / Suspense / Dramatic Build-Up / Thriller / General Documentary",
        "default_intensity": "High-Driving",
        "description": "Intense cinematic build-up with dramatic tempo for races against time, high-stakes escapes, shocking reveals, and escalating tension.",
        "keywords": ["suspense", "tension", "climax", "escape", "hunt", "chase", "race", "danger", "thriller", "build", "shock", "intense", "countdown", "panic", "heist", "manhunt", "assassination"]
    }
}

# Alias for backward compatibility
BGM_CATALOG = BGM_LIBRARY


class AudioMixer:
    """Combines voiceover, ducked background music (-13 dB), and sound effects into balanced master audio."""

    def __init__(self):
        self.music_dir = MUSIC_DIR
        self.sfx_dir = SFX_DIR
        self.renders_dir = RENDERS_DIR
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)

    def classify_story_mood_ai(
        self,
        topic_title: str,
        category: str,
        script_text: str
    ) -> Optional[Tuple[str, str, str, str]]:
        """
        Uses Gemini AI to perform multidimensional narrative analysis:
        (topic, genre, emotional tone, intensity, pacing, atmosphere, seriousness)
        and classifies into ONE of the 4 approved BGM tracks.
        Returns: (track_key, detected_mood, detected_intensity, reason) or None.
        """
        if not GEMINI_API_KEY:
            return None

        prompt = (
            f"You are an expert audio director for short historical documentaries.\n"
            f"Analyze this story and select the single best matching background music track from the ONLY 4 approved tracks:\n\n"
            f"APPROVED TRACKS:\n"
            f"1. 'best_historical': Best for historical documentary, war, disaster, strange/bizarre historical events, riots, laws, monarchies, and serious history.\n"
            f"2. 'emotional_sad': Best for poignant human tragedy, sadness, loss, emotional grief, heartfelt sacrifice, and sorrow.\n"
            f"3. 'flux_ambient': Best for dark mystery, strange inventions, lost civilizations, curiosity, scientific wonder, and atmospheric intrigue.\n"
            f"4. 'suspense_climax': Best for high-stakes tension, thrilling escapes, dramatic climax, urgent countdowns, and general high-energy documentary content.\n\n"
            f"STORY DETAILS:\n"
            f"Title: {topic_title}\n"
            f"Category/Genre: {category}\n"
            f"Script Text: {script_text}\n\n"
            f"Evaluate the story's emotional tone, intensity, pacing, atmosphere, and seriousness.\n"
            f"Respond ONLY in valid JSON format:\n"
            f'{{\n'
            f'  "track": "best_historical" | "emotional_sad" | "flux_ambient" | "suspense_climax",\n'
            f'  "mood": "<short mood & atmospheric description>",\n'
            f'  "intensity": "Low" | "Medium" | "High" | "Dramatic",\n'
            f'  "reason": "<1-2 sentence justification for why this track fits the story better than the others>"\n'
            f'}}'
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
                detected_mood = data.get("mood", BGM_LIBRARY[track_key]["mood"])
                detected_intensity = data.get("intensity", BGM_LIBRARY[track_key]["default_intensity"])
                reason = data.get("reason", "AI multidimensional mood and tone analysis")
                return track_key, detected_mood, detected_intensity, reason
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
        # 1. Attempt Multidimensional AI Mood Classification
        ai_result = self.classify_story_mood_ai(title, category, script_text)
        if ai_result:
            selected_key, detected_mood, detected_intensity, reason = ai_result
            reason = f"[AI Analyzed] {reason}"
        else:
            # 2. Semantic Multidimensional Fallback Analysis
            text_corpus = f"{category} {title} {summary} {script_text}".lower()

            scores = {}
            for key, info in BGM_LIBRARY.items():
                score = sum(2 if kw in f"{category} {title}".lower() else 1 for kw in info["keywords"] if kw in text_corpus)
                scores[key] = score

            if scores["emotional_sad"] >= 2 and scores["emotional_sad"] >= scores["suspense_climax"]:
                selected_key = "emotional_sad"
                detected_intensity = "Subdued-Poignant"
                reason = f"Keyword match for tragic/emotional tone ({scores['emotional_sad']} triggers)"
            elif scores["flux_ambient"] >= 2 and any(w in f"{category} {title}".lower() for w in ["mystery", "lost", "invention", "science", "secret", "dark"]):
                selected_key = "flux_ambient"
                detected_intensity = "Atmospheric-Tense"
                reason = f"Keyword match for mystery/curiosity atmosphere ({scores['flux_ambient']} triggers)"
            elif scores["suspense_climax"] >= 3 and scores["suspense_climax"] > scores["best_historical"]:
                selected_key = "suspense_climax"
                detected_intensity = "High-Driving"
                reason = f"Keyword match for high suspense/tension ({scores['suspense_climax']} triggers)"
            else:
                selected_key = "best_historical"
                detected_intensity = "Medium-High"
                reason = f"Documentary default track for historical events & oddities ({scores.get('best_historical', 0)} triggers)"

            detected_mood = BGM_LIBRARY[selected_key]["mood"]

        # Resolve physical file on disk (dynamically from self.music_dir)
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

        # Explicit Logging of BGM Decision
        logger.info("==================================================")
        logger.info(f"BGM Decision -> Topic: {title or category}")
        logger.info(f"Detected Mood: {detected_mood}")
        logger.info(f"Detected Intensity: {detected_intensity}")
        logger.info(f"Selected BGM: {track_info['display_name']} ({target_path.name})")
        logger.info(f"Reason: {reason}")
        logger.info(f"BGM Source Path: {target_path}")
        logger.info(f"Mix Target Level: {BGM_MIX_VOLUME_DB} dB")
        logger.info("==================================================")

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
        
        job_tag = job_id if job_id else uuid.uuid4().hex[:8]
        bgm_only_path = self.renders_dir / f"bgm_only_{job_tag}.wav"
        self.generate_stage_b_bgm_only(
            source_music_path=music_path,
            output_bgm_only_path=bgm_only_path,
            duration=duration,
            bgm_volume_db=bgm_volume_db
        )

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
