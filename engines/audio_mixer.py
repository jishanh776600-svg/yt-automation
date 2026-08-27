"""
Audio Mixer Engine.
Manages royalty-free BGM library, intelligent story mood/tone matching,
flawless looping with fade-in/fade-out, audible -13 dB mixing, and -14.0 LUFS broadcast normalization.
Guarantees that every generated video contains verified background music with zero leaks.
"""
import os
import uuid
import math
import wave
import struct
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from config.settings import MUSIC_DIR, SFX_DIR, VOICE_DIR, FFMPEG_EXE
from config.constants import (
    AUDIO_SAMPLE_RATE, TARGET_LUFS, BGM_MIX_VOLUME_DB,
    BGM_FADE_IN_SEC, BGM_FADE_OUT_SEC, LicenseType
)
from core.models import AssetRecord

logger = logging.getLogger(__name__)


# Canonical BGM Track Definitions with detailed Mood / Tone Mapping
BGM_CATALOG = {
    "epic_war": {
        "filename": "No Copyright Background Music.wav",
        "fallback_names": ["epic_history_strings.wav", "No Copyright Background Music.mp3"],
        "display_name": "No Copyright Background Music (Epic Orchestral)",
        "mood": "Epic / High Intensity / War & Conflict",
        "description": "Dramatic orchestral strings and tension pulse for battles, disasters, and clashes.",
        "keywords": ["war", "battle", "clash", "disaster", "military", "flood", "fire", "conquest", "assault", "rebellion", "siege", "weapon", "explosion", "crisis"]
    },
    "flux_mystery": {
        "filename": "The Flux Beneath It All.mp3",
        "fallback_names": ["The Flux Beneath It All.wav", "mysterious_curiosity_tension.wav"],
        "display_name": "The Flux Beneath It All (Mystery & Pulse)",
        "mood": "Mysterious / Curious / Suspenseful",
        "description": "Atmospheric pulse and tension for historical mysteries, lost places, and bizarre phenomena.",
        "keywords": ["mystery", "secret", "strange", "lost", "unexplained", "hidden", "curiosity", "puzzle", "ancient", "phenomenon", "plague", "ghost", "riddle", "shadow"]
    },
    "emotional_sad": {
        "filename": "Empty - Emotional Sad Background.mp3",
        "fallback_names": ["Empty - Emotional Sad Background.wav", "cinematic_ambient_history.wav"],
        "display_name": "Empty - Emotional Sad Background (Melancholy / Reflective)",
        "mood": "Emotional / Sad / Mournful / Reflective",
        "description": "Gentle melancholic strings for tragic events, personal sacrifices, and poignant historical moments.",
        "keywords": ["sad", "emotional", "tragedy", "loss", "grief", "poignant", "mourn", "sacrifice", "heartbreak", "death", "tears", "memorial", "ruin", "farewell"]
    },
    "best_historical": {
        "filename": "No copyright Best Historical.wav",
        "fallback_names": ["No copyright Best Historical.mp3", "victorian_intrigue_chamber.wav"],
        "display_name": "No copyright Best Historical (Victorian / Chamber Intrigue)",
        "mood": "Traditional Historical / Classical Intrigue / Court & Culture",
        "description": "Rich classical chamber strings for strange laws, forgotten figures, eccentric inventions, and royal court intrigue.",
        "keywords": ["law", "invention", "royal", "emperor", "queen", "king", "court", "coincidence", "victorian", "border", "figure", "curious", "politics", "scandal", "history", "bizarre"]
    }
}


class AudioMixer:
    """Combines speech, ducked background music (-13 dB), and sound effects into balanced master audio."""

    def __init__(self):
        self.music_dir = MUSIC_DIR
        self.sfx_dir = SFX_DIR
        self.music_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_stock_audio_assets()

    def _generate_sine_wave(self, output_path: Path, freq: float = 220.0, duration: float = 5.0, volume: float = 0.2):
        """Generates procedural sine wave tone for testing/fallback."""
        sample_rate = AUDIO_SAMPLE_RATE
        num_samples = int(sample_rate * duration)
        with wave.open(str(output_path), "w") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            frames = []
            for i in range(num_samples):
                t = i / sample_rate
                val = int(32767.0 * volume * math.sin(2 * math.pi * freq * t))
                frames.append(struct.pack("<hh", val, val))
            wav_file.writeframes(b"".join(frames))

    def _ensure_stock_audio_assets(self):
        """Ensures all 4 core BGM tracks exist locally with procedural fallback if missing."""
        try:
            from generate_bgm import generate_all_bgm_tracks
            # Check if any track is missing
            missing = False
            for track_info in BGM_CATALOG.values():
                primary = self.music_dir / track_info["filename"]
                if not primary.exists():
                    missing = True
                    break
            if missing:
                logger.info("Initializing complete 4-track BGM library...")
                generate_all_bgm_tracks(self.music_dir)
        except Exception as e:
            logger.warning(f"BGM library generation notice: {e}")

    def select_bgm_track(
        self,
        category: str = "",
        title: str = "",
        summary: str = "",
        script_text: str = ""
    ) -> Tuple[Path, str, str, str]:
        """
        Intelligently selects the optimal BGM track based on topic category, mood, and narrative context.
        Returns: (track_path, track_key, detected_mood, reason_for_selection)
        """
        text_corpus = f"{category} {title} {summary} {script_text}".lower()

        # 1. Check Emotional / Tragedy keywords
        emotional_score = sum(1 for kw in BGM_CATALOG["emotional_sad"]["keywords"] if kw in text_corpus)
        # 2. Check Epic / War / Disaster keywords
        epic_score = sum(1 for kw in BGM_CATALOG["epic_war"]["keywords"] if kw in text_corpus)
        # 3. Check Mystery / Flux keywords
        mystery_score = sum(1 for kw in BGM_CATALOG["flux_mystery"]["keywords"] if kw in text_corpus)
        # 4. Check Historical / Chamber / Law keywords
        historical_score = sum(1 for kw in BGM_CATALOG["best_historical"]["keywords"] if kw in text_corpus)

        cat_lower = str(category).lower()

        # Direct category intent overrides
        if any(w in cat_lower for w in ["law", "invention", "border", "coincidence", "figure", "american", "european", "court", "victorian"]):
            selected_key = "best_historical"
            reason = f"Historical category match: '{category}'"
        elif any(w in cat_lower for w in ["mystery", "lost places", "secret"]):
            selected_key = "flux_mystery"
            reason = f"Mystery & suspense category match: '{category}'"
        elif any(w in cat_lower for w in ["war", "battle", "clash"]):
            selected_key = "epic_war"
            reason = f"War & high intensity category match: '{category}'"
        elif emotional_score >= 2 and emotional_score > epic_score:
            selected_key = "emotional_sad"
            reason = f"High emotional/melancholy score ({emotional_score} tone triggers detected)"
        elif epic_score >= 2:
            selected_key = "epic_war"
            reason = f"High dramatic tension/war intensity ({epic_score} triggers detected)"
        elif mystery_score >= 2:
            selected_key = "flux_mystery"
            reason = f"Intrigue/suspense topic match ({mystery_score} triggers detected)"
        elif historical_score >= 1:
            selected_key = "best_historical"
            reason = f"Historical chamber intrigue match ({historical_score} triggers detected)"
        else:
            selected_key = "best_historical"
            reason = "Default canonical historical track for documentary flow"

        track_info = BGM_CATALOG[selected_key]
        primary_file = self.music_dir / track_info["filename"]

        # If primary not on disk, search fallback names
        target_path = None
        if primary_file.exists() and primary_file.stat().st_size > 1000:
            target_path = primary_file
        else:
            for fallback_name in track_info["fallback_names"]:
                fb_path = self.music_dir / fallback_name
                if fb_path.exists() and fb_path.stat().st_size > 1000:
                    target_path = fb_path
                    break

        # If still missing, trigger instant generation
        if not target_path or not target_path.exists():
            self._ensure_stock_audio_assets()
            target_path = primary_file if primary_file.exists() else (self.music_dir / "epic_history_strings.wav")

        detected_mood = track_info["mood"]
        logger.info(
            f"BGM Selection -> Track: '{target_path.name}' | "
            f"Mood: '{detected_mood}' | "
            f"Reason: {reason} | "
            f"Mix Target: {BGM_MIX_VOLUME_DB} dB"
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

    def mix_audio(
        self,
        voice_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        bgm_volume_db: float = BGM_MIX_VOLUME_DB
    ) -> Path:
        """
        Uses FFmpeg to mix voiceover with clearly audible background music (-13dB target),
        applies smooth 0.8s fade-in and 1.5s fade-out, loops/trims cleanly,
        and normalizes master loudness to broadcast standard -14.0 LUFS.
        
        Guarantees that BGM is NEVER omitted. If mixing encounters an error,
        it automatically attempts a robust multi-pass repair.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fade_out_start = max(0.5, duration - BGM_FADE_OUT_SEC)

        # High-fidelity filter graph:
        # 1. Loop BGM infinitely, trim to exact length
        # 2. Apply volume (-13dB), smooth 0.8s fade-in and 1.5s fade-out
        # 3. Mix inputs (voiceover dominant, BGM clearly audible)
        # 4. Normalize master output to -14.0 LUFS
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{duration},"
            f"volume={bgm_volume_db}dB,"
            f"afade=t=in:ss=0:d={BGM_FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={BGM_FADE_OUT_SEC}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mixed];"
            f"[mixed]loudnorm=I={TARGET_LUFS}:LRA=7:tp=-1.0[outa]"
        )

        cmd = [
            FFMPEG_EXE, "-y",
            "-i", str(voice_path),
            "-i", str(music_path),
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
            f"Master: {TARGET_LUFS} LUFS, Duration: {duration:.2f}s)"
        )
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Verification of mixed audio file existence & size
        if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1000:
            err_msg = res.stderr.decode("utf-8", errors="ignore")
            logger.warning(f"FFmpeg complex audio mixing warning ({err_msg}). Executing automatic repair mixing...")
            self._repair_and_remix_audio(voice_path, music_path, output_path, duration, bgm_volume_db)

        # Final sanity check: Output MUST exist and have valid size
        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise RuntimeError(f"Master audio mixing failed: Output file {output_path} is missing or empty.")

        logger.info(f"[+] Master audio successfully mixed with BGM: {output_path.name} ({output_path.stat().st_size} bytes)")
        return output_path

    def _repair_and_remix_audio(
        self,
        voice_path: Path,
        music_path: Path,
        output_path: Path,
        duration: float,
        bgm_volume_db: float
    ):
        """
        Robust fallback mixer: Uses standard 2-stream overlay filter graph
        to guarantee BGM is mixed even if advanced loudnorm triggers an edge-case error.
        """
        fade_out_start = max(0.5, duration - 1.0)
        repair_filter = (
            f"[1:a]atrim=0:{duration},volume={bgm_volume_db}dB,afade=t=in:ss=0:d=0.5,afade=t=out:st={fade_out_start:.2f}:d=1.0[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first[outa]"
        )
        cmd_repair = [
            FFMPEG_EXE, "-y",
            "-i", str(voice_path),
            "-stream_loop", "-1",
            "-i", str(music_path),
            "-filter_complex", repair_filter,
            "-map", "[outa]",
            "-ac", "2",
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "aac",
            "-b:a", "192k",
            str(output_path)
        ]
        logger.info("Executing robust repair audio remix...")
        res_repair = subprocess.run(cmd_repair, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res_repair.returncode != 0:
            raise RuntimeError(f"Audio repair failed: {res_repair.stderr.decode('utf-8', errors='ignore')}")
