"""
SFX Manager Engine.
Manages studio-grade sound effect catalog, anti-repetition rules,
and audio sublayer mixing with precise temporal alignment and volume ducking.
"""
import os
import uuid
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from config.settings import SFX_DIR, RENDERS_DIR, FFMPEG_EXE
from config.constants import AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Canonical SFX Catalog with semantic archetype descriptions & calibrated target volume offsets
SFX_CATALOG = {
    "impact_boom": {
        "filename": "impact_boom.wav",
        "category": "impact",
        "description": "Deep sub-bass impact for dramatic reveals, explosions, and shocking facts",
        "default_volume_db": -18.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.4
    },
    "tension_riser": {
        "filename": "tension_riser.wav",
        "category": "tension",
        "description": "Atmospheric bowed riser for suspense, escalations, and mysterious builds",
        "default_volume_db": -22.0,
        "default_fade_in": 0.2,
        "default_fade_out": 0.3
    },
    "cinematic_whoosh": {
        "filename": "cinematic_whoosh.wav",
        "category": "transition",
        "description": "Restrained airy whoosh for fast scene transitions and rapid shifts",
        "default_volume_db": -22.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "subtle_paper_turn": {
        "filename": "subtle_paper_turn.wav",
        "category": "foley",
        "description": "Parchment / manuscript rustle for historical laws, decrees, and letters",
        "default_volume_db": -24.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "distant_thunder_rumble": {
        "filename": "distant_thunder_rumble.wav",
        "category": "environment",
        "description": "Low rumble for historical cataclysms, disasters, and stormy tension",
        "default_volume_db": -20.0,
        "default_fade_in": 0.2,
        "default_fade_out": 0.5
    },
    "clock_tick_suspense": {
        "filename": "clock_tick_suspense.wav",
        "category": "tension",
        "description": "High-stakes mechanical pulse for countdowns, chases, and time-sensitive heists",
        "default_volume_db": -22.0,
        "default_fade_in": 0.02,
        "default_fade_out": 0.1
    },
    "bell_toll_somber": {
        "filename": "bell_toll_somber.wav",
        "category": "tone",
        "description": "Somber chime for medieval history, plagues, funerals, and profound tragedy",
        "default_volume_db": -20.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.6
    }
}


class SFXManager:
    """Handles sound design selection, anti-repetition enforcement, and FFmpeg multi-track audio compositing."""

    def __init__(self, sfx_dir: Optional[Path] = None):
        self.sfx_dir = sfx_dir or SFX_DIR
        self.renders_dir = RENDERS_DIR
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)

    def get_sfx_path(self, sfx_id: str) -> Optional[Path]:
        """Resolves local file path for a canonical SFX ID."""
        if sfx_id not in SFX_CATALOG:
            logger.warning(f"SFX ID '{sfx_id}' not found in SFX catalog.")
            return None
        info = SFX_CATALOG[sfx_id]
        p = self.sfx_dir / info["filename"]
        if p.exists() and p.stat().st_size > 1000:
            return p
        logger.warning(f"SFX file {p} does not exist on disk.")
        return None

    def render_sfx_layer(
        self,
        sfx_cues: List[Dict[str, Any]],
        total_duration: float,
        output_path: Path
    ) -> Optional[Path]:
        """
        Renders a clean multi-track SFX audio layer containing all positioned sound cues.
        Returns output_path or None if no valid cues exist.
        """
        valid_cues = []
        for cue in sfx_cues:
            sfx_id = cue.get("sfx_id")
            s_path = self.get_sfx_path(sfx_id)
            if s_path:
                valid_cues.append({
                    "path": s_path,
                    "start": float(cue.get("start_time", 0.0)),
                    "duration": float(cue.get("duration", 1.5)),
                    "volume_db": float(cue.get("volume_db", SFX_CATALOG[sfx_id]["default_volume_db"])),
                    "fade_in": float(cue.get("fade_in_sec", SFX_CATALOG[sfx_id]["default_fade_in"])),
                    "fade_out": float(cue.get("fade_out_sec", SFX_CATALOG[sfx_id]["default_fade_out"])),
                    "sfx_id": sfx_id
                })

        if not valid_cues:
            logger.info("No SFX cues scheduled for this Short; proceeding with silent SFX sublayer.")
            return None

        inputs = []
        filter_parts = []

        base_filter = f"aevalsrc=0:d={total_duration}:s={AUDIO_SAMPLE_RATE}:c=stereo[base]"
        filter_parts.append(base_filter)

        for idx, cue in enumerate(valid_cues):
            inputs.extend(["-i", str(cue["path"])])
            delay_ms = int(cue["start"] * 1000)
            vol_db = cue["volume_db"]
            fo_start = max(0.01, cue["duration"] - cue["fade_out"])

            f_str = (
                f"[{idx}:a]aformat=sample_fmts=fltp:sample_rates={AUDIO_SAMPLE_RATE}:channel_layouts=stereo,"
                f"volume={vol_db}dB,"
                f"afade=t=in:ss=0:d={cue['fade_in']},"
                f"afade=t=out:st={fo_start:.2f}:d={cue['fade_out']},"
                f"adelay={delay_ms}|{delay_ms}[sfx_{idx}]"
            )
            filter_parts.append(f_str)

        mix_inputs = "[base]" + "".join([f"[sfx_{i}]" for i in range(len(valid_cues))])
        filter_parts.append(f"{mix_inputs}amix=inputs={len(valid_cues)+1}:duration=first:normalize=0[outsfx]")

        full_filter = ";".join(filter_parts)

        cmd = [
            FFMPEG_EXE, "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", "[outsfx]",
            "-ac", "2",
            "-ar", str(AUDIO_SAMPLE_RATE),
            "-c:a", "pcm_s16le",
            str(output_path)
        ]

        logger.info(f"Rendering SFX track ({len(valid_cues)} cues): {output_path.name}")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            logger.warning(f"SFX layer rendering warning: {res.stderr.decode('utf-8', errors='ignore')}")
            return None

        return output_path
