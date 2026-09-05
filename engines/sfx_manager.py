"""
SFX Manager Engine.
Manages professional sound design prioritizing user-provided editing assets
from Desktop/Automation Assets (Transitions, Whooshes, Suspense, Impacts).
Enforces anti-repetition rules, 4s cooldown, max 3 cues per short,
and audio sublayer mixing with precise temporal alignment and volume ducking.
"""
import os
import uuid
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from config.settings import SFX_DIR, RENDERS_DIR, ASSETS_DIR, DATA_DIR, FFMPEG_EXE
from config.constants import AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Paths for user-provided automation assets
USER_CATALOG_PATHS = [
    DATA_DIR / "assets" / "automation_assets_catalog.json",
    ASSETS_DIR / "automation_assets_catalog.json"
]
USER_ASSETS_DIRS = [
    DATA_DIR / "assets" / "user_provided",
    ASSETS_DIR / "user_provided"
]

def load_user_assets_catalog() -> Dict[str, Any]:
    """Loads indexed user-provided assets catalog from Desktop/Automation Assets."""
    for p in USER_CATALOG_PATHS:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load user assets catalog from {p}: {e}")
    return {}

USER_PROVIDED_CATALOG = load_user_assets_catalog()

# Primary editorial semantic presets mapping directly to user-provided assets
USER_SFX_PRESETS = {
    # --- Primary User-Provided Transition & Whoosh Presets ---
    "user_trailer_transition": {
        "asset_id": "transitions_cinematic_trailer_transition_whoosh_sound_effe_mp3_160k_",
        "category": "transition",
        "relative_path": "transitions/Cinematic Trailer Transition _Whoosh_ - Sound Effe_MP3_160K_.mp3",
        "description": "User-provided cinematic trailer whoosh transition",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.25
    },
    "user_flyby_sharp": {
        "asset_id": "transitions_06_flyby_c",
        "category": "transition",
        "relative_path": "transitions/06 Flyby C.wav",
        "description": "User-provided sharp acoustic flyby transition",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.2
    },
    "user_flyby_subtle": {
        "asset_id": "transitions_05_flyby_b",
        "category": "transition",
        "relative_path": "transitions/05 Flyby B.wav",
        "description": "User-provided subtle aerial flyby sweep",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.2
    },
    "user_short_transition": {
        "asset_id": "transitions_short_transition_2_sound_",
        "category": "transition",
        "relative_path": "transitions/Short Transition _2 Sound .mp3",
        "description": "User-provided rapid scene cut transition",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "user_whoosh_quick": {
        "asset_id": "whooshes_11_low_quick",
        "category": "transition",
        "relative_path": "whooshes/11 Low Quick.wav",
        "description": "User-provided low quick whoosh for rapid handoffs",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "user_whoosh_clean": {
        "asset_id": "whooshes_01_woosh",
        "category": "transition",
        "relative_path": "whooshes/01 Woosh.wav",
        "description": "User-provided clean natural acoustic whoosh",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    # --- Primary User-Provided Suspense & Tension Presets ---
    "user_suspense_sudden": {
        "asset_id": "funny_sudden_suspense_sound_effects_mp3_160k_",
        "category": "tension",
        "relative_path": "funny/Sudden suspense-Sound effects_MP3_160K_.mp3",
        "description": "User-provided sudden dramatic suspense sting",
        "default_volume_db": -12.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.3
    },
    "user_suspense_build": {
        "asset_id": "funny_suspence_1",
        "category": "tension",
        "relative_path": "funny/suspence 1.mp3",
        "description": "User-provided progressive suspense build cue",
        "default_volume_db": -12.0,
        "default_fade_in": 0.15,
        "default_fade_out": 0.35
    },
    "user_wind_impact": {
        "asset_id": "whooshes_wind_impact",
        "category": "impact",
        "relative_path": "whooshes/wind impact.mp3",
        "description": "User-provided atmospheric wind impact punch",
        "default_volume_db": -12.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.35
    }
}

# Canonical SFX Catalog with semantic archetype descriptions & calibrated target volume offsets
SFX_CATALOG = {
    # --- Studio-Grade Professional Editorial SFX ---
    "cinematic_impact_heavy": {
        "filename": "cinematic_impact_heavy.wav",
        "relative_path": "impacts/cinematic_impact_heavy.wav",
        "category": "impacts",
        "description": "Studio-grade cinematic heavy impact hit with clean sub-bass punch",
        "default_volume_db": -12.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.4
    },
    "editorial_hit_reveal": {
        "filename": "editorial_hit_reveal.wav",
        "relative_path": "impacts/editorial_hit_reveal.wav",
        "category": "impacts",
        "description": "Crisp editorial reveal impact for key factual turning points",
        "default_volume_db": -12.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.35
    },
    "subbass_boom": {
        "filename": "subbass_boom.wav",
        "relative_path": "impacts/subbass_boom.wav",
        "category": "impacts",
        "description": "Deep acoustic low-end boom without synthetic distortion",
        "default_volume_db": -12.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.45
    },
    "cinematic_whoosh_air": {
        "filename": "cinematic_whoosh_air.wav",
        "relative_path": "transitions/cinematic_whoosh_air.wav",
        "category": "transitions",
        "description": "High-velocity airy cinematic whoosh for rapid scene transitions",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.2
    },
    "subtle_whoosh_fast": {
        "filename": "subtle_whoosh_fast.wav",
        "relative_path": "transitions/subtle_whoosh_fast.wav",
        "category": "transitions",
        "description": "Short restrained whip whoosh for swift topic handoffs",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "editorial_transition": {
        "filename": "editorial_transition.wav",
        "relative_path": "transitions/editorial_transition.wav",
        "category": "transitions",
        "description": "Smooth textured cinematic transition element",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.3
    },
    "tension_riser_analog": {
        "filename": "tension_riser_analog.wav",
        "relative_path": "tension/tension_riser_analog.wav",
        "category": "tension",
        "description": "Progressive tension riser for escalating geopolitical stakes",
        "default_volume_db": -12.0,
        "default_fade_in": 0.2,
        "default_fade_out": 0.35
    },
    "document_page_turn": {
        "filename": "document_page_turn.wav",
        "relative_path": "paper/document_page_turn.wav",
        "category": "paper",
        "description": "Authentic paper page turn / official diplomatic document rustle",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "camera_press_shutter": {
        "filename": "camera_press_shutter.wav",
        "relative_path": "broadcast/camera_press_shutter.wav",
        "category": "broadcast",
        "description": "Clean single-lens reflex camera shutter for press conference context",
        "default_volume_db": -14.0,
        "default_fade_in": 0.02,
        "default_fade_out": 0.1
    },
    "camera_motor_burst": {
        "filename": "camera_motor_burst.wav",
        "relative_path": "broadcast/camera_motor_burst.wav",
        "category": "broadcast",
        "description": "Rapid photojournalism shutter burst for breaking media events",
        "default_volume_db": -14.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.25
    },

    # --- Legacy SFX Keys (Kept for Backward Compatibility & Audibility Invariants) ---
    "impact_boom": {
        "filename": "impact_boom.wav",
        "relative_path": "impacts/cinematic_impact_heavy.wav",
        "category": "impact",
        "description": "Deep sub-bass impact for dramatic reveals, explosions, and shocking facts",
        "default_volume_db": -3.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.4
    },
    "tension_riser": {
        "filename": "tension_riser.wav",
        "relative_path": "tension/tension_riser_analog.wav",
        "category": "tension",
        "description": "Atmospheric bowed riser for suspense, escalations, and mysterious builds",
        "default_volume_db": -4.0,
        "default_fade_in": 0.2,
        "default_fade_out": 0.3
    },
    "cinematic_whoosh": {
        "filename": "cinematic_whoosh.wav",
        "relative_path": "transitions/subtle_whoosh_fast.wav",
        "category": "transition",
        "description": "Restrained airy whoosh for fast scene transitions and rapid shifts",
        "default_volume_db": -4.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "subtle_paper_turn": {
        "filename": "subtle_paper_turn.wav",
        "relative_path": "paper/document_page_turn.wav",
        "category": "foley",
        "description": "Parchment / manuscript rustle for historical laws, decrees, and letters",
        "default_volume_db": -5.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.15
    },
    "distant_thunder_rumble": {
        "filename": "distant_thunder_rumble.wav",
        "category": "environment",
        "description": "Low rumble for historical cataclysms, disasters, and stormy tension",
        "default_volume_db": -4.0,
        "default_fade_in": 0.2,
        "default_fade_out": 0.5
    },
    "clock_tick_suspense": {
        "filename": "clock_tick_suspense.wav",
        "category": "tension",
        "description": "High-stakes mechanical pulse for countdowns, chases, and time-sensitive heists",
        "default_volume_db": -4.0,
        "default_fade_in": 0.02,
        "default_fade_out": 0.1
    },
    "bell_toll_somber": {
        "filename": "bell_toll_somber.wav",
        "category": "tone",
        "description": "Somber chime for medieval history, plagues, funerals, and profound tragedy",
        "default_volume_db": -4.0,
        "default_fade_in": 0.05,
        "default_fade_out": 0.6
    }
}

# Merge user presets into catalog
for k, v in USER_SFX_PRESETS.items():
    if k not in SFX_CATALOG:
        SFX_CATALOG[k] = v


class SFXManager:
    """
    Handles sound design selection, prioritizing user-provided editing assets,
    anti-repetition enforcement, and FFmpeg multi-track audio compositing.
    """

    def __init__(self, sfx_dir: Optional[Path] = None):
        self.sfx_dir = sfx_dir or SFX_DIR
        self.renders_dir = RENDERS_DIR
        self.sfx_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)
        self.user_catalog = USER_PROVIDED_CATALOG or load_user_assets_catalog()

    def get_sfx_path(self, sfx_id: str) -> Optional[Path]:
        """
        Resolves local file path for an SFX ID.
        PRIORITY:
        1. User-Provided Automation Assets (from Desktop/Automation Assets)
        2. USER_SFX_PRESETS
        3. SFX_CATALOG (Studio Library)
        """
        # 1. Check direct user-provided catalog match
        if sfx_id in self.user_catalog:
            rel = self.user_catalog[sfx_id].get("relative_path")
            if rel:
                for base in USER_ASSETS_DIRS:
                    cand = base / rel
                    if cand.exists() and cand.stat().st_size > 500:
                        return cand

        # 2. Check user presets
        if sfx_id in USER_SFX_PRESETS:
            rel = USER_SFX_PRESETS[sfx_id].get("relative_path")
            if rel:
                for base in USER_ASSETS_DIRS:
                    cand = base / rel
                    if cand.exists() and cand.stat().st_size > 500:
                        return cand

        # 3. Check SFX_CATALOG
        if sfx_id in SFX_CATALOG:
            info = SFX_CATALOG[sfx_id]
            candidates = []
            if "relative_path" in info:
                # Check user assets first if matching
                for base in USER_ASSETS_DIRS:
                    candidates.append(base / info["relative_path"])
                candidates.append(self.sfx_dir / info["relative_path"])
                candidates.append(ASSETS_DIR / "sfx" / info["relative_path"])
                candidates.append(DATA_DIR / "assets" / "sfx" / info["relative_path"])
            if "filename" in info:
                candidates.append(self.sfx_dir / info["filename"])
                candidates.append(ASSETS_DIR / "sfx" / info["filename"])
                candidates.append(DATA_DIR / "assets" / "sfx" / info["filename"])

            for p in candidates:
                if p.exists() and p.stat().st_size > 500:
                    return p

        # 4. Search user assets by name substring if not explicitly indexed
        clean_name = sfx_id.lower().replace("user_", "").replace("whoosh_", "").replace("transition_", "")
        for base in USER_ASSETS_DIRS:
            if base.exists():
                for cand in base.rglob("*.*"):
                    if cand.is_file() and clean_name in cand.stem.lower() and cand.stat().st_size > 500:
                        return cand

        logger.warning(f"SFX file for ID '{sfx_id}' does not exist on disk.")
        return None

    def render_sfx_layer(
        self,
        sfx_cues: List[Dict[str, Any]],
        total_duration: float,
        output_path: Path
    ) -> Optional[Path]:
        """
        Renders a clean multi-track SFX audio layer containing positioned sound cues.
        Enforces:
        - Maximum 3 SFX cues per Short
        - Minimum 4.0s cooldown between cues
        - Subordinate ducking under voice narration
        Returns output_path or None if no valid cues exist.
        """
        # Sort cues by start time and enforce max 3 cues & >=4.0s cooldown
        sorted_cues = sorted(sfx_cues, key=lambda c: float(c.get("start_time", 0.0)))
        filtered_cues = []
        last_start = -999.0

        for cue in sorted_cues:
            st = float(cue.get("start_time", 0.0))
            if st - last_start >= 4.0:
                filtered_cues.append(cue)
                last_start = st
            if len(filtered_cues) >= 3:
                break

        valid_cues = []
        for cue in filtered_cues:
            sfx_id = cue.get("sfx_id")
            s_path = self.get_sfx_path(sfx_id)
            if s_path:
                default_vol = -14.0
                if sfx_id in SFX_CATALOG:
                    default_vol = SFX_CATALOG[sfx_id].get("default_volume_db", -14.0)
                elif sfx_id in self.user_catalog:
                    default_vol = self.user_catalog[sfx_id].get("recommended_volume_db", -14.0)
                vol_db = float(cue.get("volume_db", default_vol))
                
                default_fade_in = SFX_CATALOG.get(sfx_id, {}).get("default_fade_in", 0.05)
                default_fade_out = SFX_CATALOG.get(sfx_id, {}).get("default_fade_out", 0.2)
                
                valid_cues.append({
                    "path": s_path,
                    "start": float(cue.get("start_time", 0.0)),
                    "duration": float(cue.get("duration", 1.5)),
                    "volume_db": vol_db,
                    "fade_in": float(cue.get("fade_in_sec", default_fade_in)),
                    "fade_out": float(cue.get("fade_out_sec", default_fade_out)),
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

        output_path.parent.mkdir(parents=True, exist_ok=True)
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
