"""
AL-AMR Voice Audition Engine — Round 3: Urgent + Informal Voice Expansion.
Offline, deterministic, high-capacity audition battery for YouTube Shorts narration.
"""
import os
import re
import json
import math
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import soundfile as sf
import numpy as np

from config.settings import RENDERS_DIR
from engines.tts_engine import TTSEngine

logger = logging.getLogger(__name__)

ROUND3_DIR = RENDERS_DIR / "voice_auditions_round3"

# ==============================================================================
# 1. ACTUAL LOCALLY AVAILABLE VOICE INVENTORY
# ==============================================================================

KOKORO_VOICE_CATALOG = {
    # American Male (9)
    "am_adam": {"gender": "Male", "accent": "American", "persona": "Authoritative Investigator / Punchy Baritone"},
    "am_echo": {"gender": "Male", "accent": "American", "persona": "Resonant / Modern Forward Pace"},
    "am_eric": {"gender": "Male", "accent": "American", "persona": "Grounded / Conversational / Authentic"},
    "am_fenrir": {"gender": "Male", "accent": "American", "persona": "Cinematic Baritone / Dramatic Weight"},
    "am_liam": {"gender": "Male", "accent": "American", "persona": "Youthful / Dynamic / Upbeat Modern Creator"},
    "am_michael": {"gender": "Male", "accent": "American", "persona": "Engaged Storyteller / Agility / Curiosity"},
    "am_onyx": {"gender": "Male", "accent": "American", "persona": "Crisp / Razor-Sharp / Controlled Irony"},
    "am_puck": {"gender": "Male", "accent": "American", "persona": "Punchy Creator / Irreverent Energy / Fast Hooks"},
    "am_santa": {"gender": "Male", "accent": "American", "persona": "Jovial Character Voice"},
    # British Male (4)
    "bm_daniel": {"gender": "Male", "accent": "British", "persona": "Articulate / Clear UK Explainer"},
    "bm_fable": {"gender": "Male", "accent": "British", "persona": "Narrative Storyteller"},
    "bm_george": {"gender": "Male", "accent": "British", "persona": "BBC Classical / Stately Cadence"},
    "bm_lewis": {"gender": "Male", "accent": "British", "persona": "Modern British Creator / Dynamic Cadence"},
    # American Female (11)
    "af_alloy": {"gender": "Female", "accent": "American", "persona": "Crisp / Tech-Forward / Confident Pace"},
    "af_aoede": {"gender": "Female", "accent": "American", "persona": "Melodic Explainer"},
    "af_bella": {"gender": "Female", "accent": "American", "persona": "High-Energy / Fast-Paced / Viral Commentator"},
    "af_heart": {"gender": "Female", "accent": "American", "persona": "Natural Creator / Nuanced Inflection / Authentic"},
    "af_jessica": {"gender": "Female", "accent": "American", "persona": "Clear / Friendly Explainer"},
    "af_kore": {"gender": "Female", "accent": "American", "persona": "Direct / Assertive / Piercing Clarity"},
    "af_nicole": {"gender": "Female", "accent": "American", "persona": "Casual / Relaxed / Conversational Realism"},
    "af_nova": {"gender": "Female", "accent": "American", "persona": "Bright / Modern / Vibrant Direct Delivery"},
    "af_river": {"gender": "Female", "accent": "American", "persona": "Soft / Calm Explainer"},
    "af_sarah": {"gender": "Female", "accent": "American", "persona": "Warm / Conversational / Relatable Creator"},
    "af_sky": {"gender": "Female", "accent": "American", "persona": "Youthful / Vivid / Expressive Creator"},
    # British Female (4)
    "bf_alice": {"gender": "Female", "accent": "British", "persona": "Refined UK Explainer"},
    "bf_emma": {"gender": "Female", "accent": "British", "persona": "Crisp / Rapid / Articulate UK Delivery"},
    "bf_isabella": {"gender": "Female", "accent": "British", "persona": "Lively / Direct UK Explainer"},
    "bf_lily": {"gender": "Female", "accent": "British", "persona": "Gentle British Cadence"},
}

# Audition Selection Groups
GROUP_A_URGENT = {
    "male": ["am_michael", "am_puck", "am_echo", "am_liam", "am_adam", "am_onyx"],
    "female": ["af_bella", "af_nova", "af_alloy", "af_kore", "af_sky", "bf_emma"],
}

GROUP_B_INFORMAL = {
    "male": ["am_michael", "am_eric", "am_puck", "am_liam", "am_onyx", "bm_lewis"],
    "female": ["af_heart", "af_sarah", "af_nova", "af_nicole", "af_sky", "af_bella"],
}

# ==============================================================================
# 2. STANDARDIZED AUDITION SCRIPTS
# ==============================================================================

SCRIPTS_URGENT = {
    "01": {
        "text": "Wait—because this just changed everything. Three hours ago, officials were denying the story. Now there's evidence showing the exact opposite.",
        "variant": "URGENT_CONTROLLED",
        "speed": 1.08,
        "sentence_pause": 0.20,
        "clause_pause": 0.08
    },
    "02": {
        "text": "And then, suddenly, the announcement dropped. Markets reacted, officials scrambled, and within minutes the entire situation had changed.",
        "variant": "URGENT_HIGH_ENERGY",
        "speed": 1.14,
        "sentence_pause": 0.16,
        "clause_pause": 0.07
    },
    "03": {
        "text": "This is moving fast. A new statement just came out, and if the details are accurate, this could completely change what happens next.",
        "variant": "URGENT_MAX_PUNCH",
        "speed": 1.18,
        "sentence_pause": 0.14,
        "clause_pause": 0.06
    }
}

SCRIPTS_INFORMAL = {
    "01": {
        "text": "Okay, so here's the weird part. Everyone was looking at the obvious explanation, but honestly, that's not even the interesting bit.",
        "variant": "INFORMAL_NATURAL",
        "speed": 1.03,
        "sentence_pause": 0.24,
        "clause_pause": 0.10
    },
    "02": {
        "text": "Yeah, this plan sounded great on paper. Then reality showed up, kicked the door in, and basically ruined the whole thing.",
        "variant": "INFORMAL_CREATOR",
        "speed": 1.08,
        "sentence_pause": 0.18,
        "clause_pause": 0.08
    },
    "03": {
        "text": "So you're telling me they had one job... and somehow managed to make the situation even worse? Yeah. Pretty much.",
        "variant": "INFORMAL_IRREVERENT",
        "speed": 1.06,
        "sentence_pause": 0.20,
        "clause_pause": 0.09
    },
    "04": {
        "text": "Here's what nobody seems to be talking about. The headline is interesting, sure, but the little detail buried underneath it is way crazier.",
        "variant": "INFORMAL_CREATOR",
        "speed": 1.09,
        "sentence_pause": 0.18,
        "clause_pause": 0.08
    }
}


class VoiceAuditionRound3Engine:
    """
    Renders Round 3 auditions for Urgent and Informal/Creator styles.
    Computes audio metadata, technical evaluations, and generates
    structured markdown reports and listening guides.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or ROUND3_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_engine = TTSEngine()

    def calculate_audio_metadata(self, audio_path: Path) -> Dict[str, Any]:
        """Calculates duration, peak dB, RMS dB, clipping status, and format metadata."""
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_db": -99.0,
                "rms_db": -99.0,
                "is_clipped": False,
                "file_size_bytes": 0
            }

        try:
            data, sr = sf.read(str(audio_path))
            duration = round(len(data) / float(sr), 2)
            channels = 1 if data.ndim == 1 else data.shape[1]

            peak = float(np.max(np.abs(data)))
            peak_db = round(20 * math.log10(max(peak, 1e-6)), 2)
            rms = float(np.sqrt(np.mean(data ** 2)))
            rms_db = round(20 * math.log10(max(rms, 1e-6)), 2)
            is_clipped = peak >= 0.999

            return {
                "duration_sec": duration,
                "sample_rate": sr,
                "channels": channels,
                "peak_db": peak_db,
                "rms_db": rms_db,
                "is_clipped": is_clipped,
                "file_size_bytes": audio_path.stat().st_size
            }
        except Exception as e:
            logger.warning(f"Error calculating metadata for {audio_path}: {e}")
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_db": -99.0,
                "rms_db": -99.0,
                "is_clipped": False,
                "file_size_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                "error": str(e)
            }

    def render_sample(
        self,
        voice_id: str,
        style: str,
        variant: str,
        script_num: str,
        script_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synthesizes a single audition sample offline with calibrated pause parameters."""
        filename = f"{voice_id}__{variant}__{script_num}.wav"
        out_path = self.output_dir / filename

        meta_voice = KOKORO_VOICE_CATALOG.get(voice_id, {"gender": "Unknown", "accent": "American", "persona": "Generic"})

        success, duration = self.tts_engine.generate_kokoro_audio(
            text=script_data["text"],
            output_path=out_path,
            voice=voice_id,
            speed=script_data["speed"],
            sentence_pause=script_data["sentence_pause"],
            clause_pause=script_data["clause_pause"]
        )

        audio_meta = self.calculate_audio_metadata(out_path)

        return {
            "voice_id": voice_id,
            "gender": meta_voice["gender"],
            "accent": meta_voice["accent"],
            "persona": meta_voice["persona"],
            "style": style,
            "variant": variant,
            "script_number": script_num,
            "script_text": script_data["text"],
            "speed_multiplier": script_data["speed"],
            "sentence_pause_sec": script_data["sentence_pause"],
            "clause_pause_sec": script_data["clause_pause"],
            "output_file": str(out_path),
            "filename": filename,
            "synthesis_success": success,
            "audio_metadata": audio_meta
        }

    def run_audition_battery(self) -> Dict[str, Any]:
        """Executes full Round 3 audition battery across Urgent and Informal groups."""
        samples: List[Dict[str, Any]] = []

        logger.info("[AUDITION_ROUND3] Beginning execution...")

        # 1. Urgent Battery (6 male + 6 female x 3 scripts = 36 samples)
        urgent_voices = GROUP_A_URGENT["male"] + GROUP_A_URGENT["female"]
        for vid in urgent_voices:
            for s_num, s_data in SCRIPTS_URGENT.items():
                res = self.render_sample(
                    voice_id=vid,
                    style="URGENT",
                    variant=s_data["variant"],
                    script_num=s_num,
                    script_data=s_data
                )
                samples.append(res)

        # 2. Informal Battery (6 male + 6 female x 4 scripts = 48 samples)
        informal_voices = GROUP_B_INFORMAL["male"] + GROUP_B_INFORMAL["female"]
        for vid in informal_voices:
            for s_num, s_data in SCRIPTS_INFORMAL.items():
                res = self.render_sample(
                    voice_id=vid,
                    style="INFORMAL",
                    variant=s_data["variant"],
                    script_num=s_num,
                    script_data=s_data
                )
                samples.append(res)

        urgent_count = sum(1 for s in samples if s["style"] == "URGENT")
        informal_count = sum(1 for s in samples if s["style"] == "INFORMAL")

        manifest = {
            "audition_round": "3.0.0",
            "total_samples_rendered": len(samples),
            "urgent_samples_count": urgent_count,
            "informal_samples_count": informal_count,
            "urgent_candidate_voices": urgent_voices,
            "informal_candidate_voices": informal_voices,
            "output_directory": str(self.output_dir),
            "production_voice_modified": False,
            "manifest_entries": samples
        }

        manifest_path = self.output_dir / "voice_audition_round3_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"[AUDITION_ROUND3] Completed {len(samples)} samples. Manifest saved to {manifest_path}.")
        return manifest
