"""
Audio Mixer Engine.
Manages royalty-free music library (YouTube Audio Library / CC0), cinematic sound effects,
clearly audible background music mixing (calibrated to -13 dB under narration),
and LUFS broadcast normalization.
"""
import os
import uuid
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from config.settings import MUSIC_DIR, SFX_DIR, VOICE_DIR, FFMPEG_EXE
from config.constants import AUDIO_SAMPLE_RATE, TARGET_LUFS, LicenseType
from core.models import AssetRecord

logger = logging.getLogger(__name__)


class AudioMixer:
    """Combines speech, audible background music, and sound effects into balanced master audio."""

    def __init__(self):
        self.music_dir = MUSIC_DIR
        self.sfx_dir = SFX_DIR

    def get_background_music(self, db: Session, category: str = "Unusual Wars") -> AssetRecord:
        """Selects suitable background music track based on historical topic mood."""
        cat_lower = str(category).lower()
        if any(w in cat_lower for w in ["war", "disaster", "flood", "battle", "clash"]):
            music_file = self.music_dir / "epic_history_strings.wav"
        elif any(w in cat_lower for w in ["mystery", "lost", "plague", "secret", "strange"]):
            music_file = self.music_dir / "mysterious_curiosity_tension.wav"
        else:
            music_file = self.music_dir / "victorian_intrigue_chamber.wav"

        if not music_file.exists():
            music_file = self.music_dir / "epic_history_strings.wav"

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
            duration_sec=32.0
        )
        db.add(asset)
        db.commit()
        logger.info(f"Selected BGM: {music_file.name} for category '{category}'")
        return asset

    def mix_audio(self, voice_path: Path, music_path: Path, output_path: Path, duration: float) -> Path:
        """
        Uses FFmpeg to mix voiceover with rich, clearly audible background music
        and normalize master loudness to broadcast standard -14 LUFS.
        """
        # FFmpeg filter: BGM looped and scaled to 0.22 (-13dB) with normalize=0 so volume isn't reduced
        filter_complex = (
            f"[1:a]aloop=loop=-1:size=2e+09,atrim=0:{duration},volume=0.22[bgm];"
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

        logger.info(f"Mixing master audio with clearly audible BGM: {' '.join(cmd)}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.warning(f"FFmpeg audio mixing fallback: {res.stderr.decode('utf-8', errors='ignore')}")
            # Direct copy fallback if amix filter encounters issues
            fallback_cmd = [
                FFMPEG_EXE, "-y",
                "-i", str(voice_path),
                "-c:a", "aac",
                "-b:a", "192k",
                str(output_path)
            ]
            subprocess.run(fallback_cmd)

        return output_path
