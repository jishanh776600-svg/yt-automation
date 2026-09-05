"""
AL-AMR Voice Audition Engine — Round 4: Final Liam + Sarah Voice Tuning.
High-Presence / Slightly-Fast / Modern YouTube Creator Delivery.
Completely isolated under data/renders/voice_auditions_round4/.
Zero production configuration modifications.
"""
import os
import re
import json
import math
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import soundfile as sf
import numpy as np

from config.settings import RENDERS_DIR, FFMPEG_EXE
from engines.tts_engine import TTSEngine

logger = logging.getLogger(__name__)

ROUND4_DIR = RENDERS_DIR / "voice_auditions_round4"

# ==============================================================================
# 1. CANDIDATE VOICES (STRICT: ONLY LIAM & SARAH)
# ==============================================================================

AUDITION_CANDIDATES = {
    "am_liam": {
        "gender": "Male",
        "accent": "American",
        "display_name": "Liam (US Male)",
        "timbre": "Youthful, energetic, relatable, modern YouTube creator cadence"
    },
    "af_sarah": {
        "gender": "Female",
        "accent": "American",
        "display_name": "Sarah (US Female)",
        "timbre": "Warm, engaging, intelligent explainer, authentic conversational presence"
    }
}

# ==============================================================================
# 2. TUNING VARIANTS MATRIX (5 PER VOICE)
# ==============================================================================

TUNING_VARIANTS = {
    # Liam Variants
    "LIAM_CREATOR_BALANCED": {
        "voice_id": "am_liam",
        "gender": "Male",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.05,
        "sentence_pause": 0.20,
        "clause_pause": 0.08,
        "presence_boost_db": 1.5,
        "eq_freq_hz": 3000,
        "target_lufs": -16.0,
        "description": "Balanced baseline: natural conversational flow with subtle presence lift."
    },
    "LIAM_CREATOR_ENERGETIC": {
        "voice_id": "am_liam",
        "gender": "Male",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.07,
        "sentence_pause": 0.18,
        "clause_pause": 0.07,
        "presence_boost_db": 2.0,
        "eq_freq_hz": 3200,
        "target_lufs": -16.0,
        "description": "High-energy creator explainer: dynamic pacing with assertive upper-mid clarity."
    },
    "LIAM_HIGH_PRESENCE": {
        "voice_id": "am_liam",
        "gender": "Male",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.06,
        "sentence_pause": 0.19,
        "clause_pause": 0.08,
        "presence_boost_db": 2.5,
        "eq_freq_hz": 2800,
        "target_lufs": -15.5,
        "description": "Maximum vocal presence: forward, warm, cutting mobile speaker intelligibility."
    },
    "LIAM_SLIGHT_FAST_PUNCH": {
        "voice_id": "am_liam",
        "gender": "Male",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.09,
        "sentence_pause": 0.16,
        "clause_pause": 0.06,
        "presence_boost_db": 1.8,
        "eq_freq_hz": 3500,
        "target_lufs": -16.0,
        "description": "Slight-fast punch: tight clause spacing, high retention hook momentum."
    },
    "LIAM_MAX_CREATOR": {
        "voice_id": "am_liam",
        "gender": "Male",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.08,
        "sentence_pause": 0.17,
        "clause_pause": 0.07,
        "presence_boost_db": 2.2,
        "eq_freq_hz": 3000,
        "target_lufs": -15.5,
        "description": "The ultimate creator package: optimal speed, micro-pauses, warm broadcast mastering."
    },

    # Sarah Variants
    "SARAH_CREATOR_BALANCED": {
        "voice_id": "af_sarah",
        "gender": "Female",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.05,
        "sentence_pause": 0.20,
        "clause_pause": 0.08,
        "presence_boost_db": 1.5,
        "eq_freq_hz": 3000,
        "target_lufs": -16.0,
        "description": "Balanced baseline: warm storytelling inflection with natural conversational clarity."
    },
    "SARAH_CREATOR_ENERGETIC": {
        "voice_id": "af_sarah",
        "gender": "Female",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.07,
        "sentence_pause": 0.18,
        "clause_pause": 0.07,
        "presence_boost_db": 2.0,
        "eq_freq_hz": 3200,
        "target_lufs": -16.0,
        "description": "High-energy creator explainer: lively delivery, crisp diction, engaging curiosity."
    },
    "SARAH_HIGH_PRESENCE": {
        "voice_id": "af_sarah",
        "gender": "Female",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.06,
        "sentence_pause": 0.19,
        "clause_pause": 0.08,
        "presence_boost_db": 2.5,
        "eq_freq_hz": 2800,
        "target_lufs": -15.5,
        "description": "Maximum vocal presence: intimate, forward projection, rich warmth on phone speakers."
    },
    "SARAH_SLIGHT_FAST_PUNCH": {
        "voice_id": "af_sarah",
        "gender": "Female",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.09,
        "sentence_pause": 0.16,
        "clause_pause": 0.06,
        "presence_boost_db": 1.8,
        "eq_freq_hz": 3500,
        "target_lufs": -16.0,
        "description": "Slight-fast punch: brisk tempo, razor-sharp hook delivery, zero dragging."
    },
    "SARAH_MAX_CREATOR": {
        "voice_id": "af_sarah",
        "gender": "Female",
        "delivery_profile": "CREATOR_HIGH_PRESENCE_SLIGHT_FAST",
        "speed": 1.08,
        "sentence_pause": 0.17,
        "clause_pause": 0.07,
        "presence_boost_db": 2.2,
        "eq_freq_hz": 3000,
        "target_lufs": -15.5,
        "description": "The ultimate creator package: conversational warmth, fast hook cadence, broadcast mastering."
    }
}

# ==============================================================================
# 3. ACTUAL AL-AMR CHANNEL SCRIPTS (6 CORE + 2 PROFANITY TEST)
# ==============================================================================

AUDITION_SCRIPTS = {
    "SCRIPT_A": {
        "archetype": "URGENT_GEOPOLITICAL",
        "title": "Urgent Geopolitical Development",
        "text": "Okay, this just got a lot more serious. A new move from the government could completely change what happens next — and here's the part almost everyone is missing."
    },
    "SCRIPT_B": {
        "archetype": "INFORMAL_EXPLANATION",
        "title": "Informal Explanation",
        "text": "So here's the weird part. Everyone is talking about the headline, but the actual story is buried underneath it."
    },
    "SCRIPT_C": {
        "archetype": "SHOCK_REVEAL",
        "title": "Shock / Reveal",
        "text": "Wait — because this is where the story gets really interesting. The document says one thing, but the timeline tells a completely different story."
    },
    "SCRIPT_D": {
        "archetype": "LIGHT_IRREVERENCE",
        "title": "Light Irreverence",
        "text": "And yeah, apparently somebody thought this was a brilliant idea. Spoiler: it really wasn't."
    },
    "SCRIPT_E": {
        "archetype": "HIGH_STAKES",
        "title": "High-Stakes Explanation",
        "text": "This isn't just another political argument. If this decision goes through, it could affect the entire region."
    },
    "SCRIPT_F": {
        "archetype": "FAST_HOOK_PAYOFF",
        "title": "Fast Hook + Payoff",
        "text": "Here's what happened, why it matters, and the one detail almost everybody completely missed."
    },
    "SCRIPT_P1": {
        "archetype": "LIGHT_PROFANITY_1",
        "title": "Light Profanity: Exasperated Reaction",
        "text": "This whole situation is honestly insane. They had one job, and what the hell were they actually thinking?"
    },
    "SCRIPT_P2": {
        "archetype": "LIGHT_PROFANITY_2",
        "title": "Light Profanity: Skeptical Creator",
        "text": "The official explanation is damn ridiculous, and frankly nobody is buying it anymore."
    }
}

# Plan matrix: 20 samples per voice (40 total)
SAMPLE_PLAN = [
    # Script A tested across all 5 variants for direct head-to-head comparison
    ("SCRIPT_A", "CREATOR_BALANCED"),
    ("SCRIPT_A", "CREATOR_ENERGETIC"),
    ("SCRIPT_A", "HIGH_PRESENCE"),
    ("SCRIPT_A", "SLIGHT_FAST_PUNCH"),
    ("SCRIPT_A", "MAX_CREATOR"),

    # Script B tested across 3 representative variants
    ("SCRIPT_B", "CREATOR_BALANCED"),
    ("SCRIPT_B", "CREATOR_ENERGETIC"),
    ("SCRIPT_B", "MAX_CREATOR"),

    # Script C tested across 3 representative variants
    ("SCRIPT_C", "HIGH_PRESENCE"),
    ("SCRIPT_C", "SLIGHT_FAST_PUNCH"),
    ("SCRIPT_C", "MAX_CREATOR"),

    # Script D tested across 2 representative variants
    ("SCRIPT_D", "CREATOR_BALANCED"),
    ("SCRIPT_D", "MAX_CREATOR"),

    # Script E tested across 3 representative variants
    ("SCRIPT_E", "CREATOR_ENERGETIC"),
    ("SCRIPT_E", "HIGH_PRESENCE"),
    ("SCRIPT_E", "MAX_CREATOR"),

    # Script F tested across 2 representative variants
    ("SCRIPT_F", "SLIGHT_FAST_PUNCH"),
    ("SCRIPT_F", "MAX_CREATOR"),

    # Script P1 & P2 tested on MAX_CREATOR
    ("SCRIPT_P1", "MAX_CREATOR"),
    ("SCRIPT_P2", "MAX_CREATOR")
]


class VoiceAuditionRound4Engine:
    """
    Renders Round 4 high-presence auditions for Liam and Sarah.
    Applies dedicated presence & broadcast mastering filters.
    Measures duration, peak dBFS, RMS dBFS, crest factor, and Whisper word alignment.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or ROUND4_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_engine = TTSEngine()

    def apply_presence_processing(
        self,
        raw_wav: Path,
        proc_wav: Path,
        presence_boost_db: float = 2.0,
        eq_freq_hz: int = 3000,
        target_lufs: float = -16.0
    ) -> bool:
        """
        Applies vocal presence EQ, highpass sub-rumble filter (80Hz),
        and transparent broadcast loudness leveling with true-peak limiter (-1.2 dBFS).
        """
        try:
            af_filter = (
                f"highpass=f=80,"
                f"equalizer=f={eq_freq_hz}:t=q:w=1.2:g={presence_boost_db},"
                f"loudnorm=I={target_lufs}:tp=-1.2:LRA=9,"
                f"aformat=sample_rates=24000:channel_layouts=mono"
            )
            cmd = [
                FFMPEG_EXE, "-y",
                "-i", str(raw_wav),
                "-af", af_filter,
                "-c:a", "pcm_s16le",
                str(proc_wav)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and proc_wav.exists() and proc_wav.stat().st_size > 1000
        except Exception as e:
            logger.warning(f"Audio processing error: {e}")
            return False

    def calculate_audio_metrics(self, audio_path: Path) -> Dict[str, Any]:
        """Calculates precise audio engineering measurements."""
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_dbfs": -99.0,
                "rms_dbfs": -99.0,
                "crest_factor": 0.0,
                "is_clipped": False,
                "file_size_bytes": 0
            }

        try:
            data, sr = sf.read(str(audio_path))
            duration = round(len(data) / float(sr), 2)
            channels = 1 if data.ndim == 1 else data.shape[1]

            peak = float(np.max(np.abs(data)))
            peak_dbfs = round(20 * math.log10(max(peak, 1e-6)), 2)
            rms = float(np.sqrt(np.mean(data ** 2)))
            rms_dbfs = round(20 * math.log10(max(rms, 1e-6)), 2)
            crest_factor = round(peak_dbfs - rms_dbfs, 2)
            is_clipped = peak >= 0.999

            return {
                "duration_sec": duration,
                "sample_rate": sr,
                "channels": channels,
                "peak_dbfs": peak_dbfs,
                "rms_dbfs": rms_dbfs,
                "crest_factor": crest_factor,
                "is_clipped": is_clipped,
                "file_size_bytes": audio_path.stat().st_size
            }
        except Exception as e:
            logger.warning(f"Error measuring audio: {e}")
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_dbfs": -99.0,
                "rms_dbfs": -99.0,
                "crest_factor": 0.0,
                "is_clipped": False,
                "file_size_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                "error": str(e)
            }

    def render_audition_sample(
        self,
        voice_id: str,
        variant_suffix: str,
        script_key: str
    ) -> Dict[str, Any]:
        """Synthesizes and processes a single tuned audition sample."""
        voice_prefix = "LIAM" if voice_id == "am_liam" else "SARAH"
        full_variant_key = f"{voice_prefix}_{variant_suffix}"
        variant_cfg = TUNING_VARIANTS[full_variant_key]
        script_info = AUDITION_SCRIPTS[script_key]

        filename = f"{voice_id}__{full_variant_key}__{script_key}.wav"
        raw_filename = f"raw_{filename}"
        raw_path = self.output_dir / raw_filename
        out_path = self.output_dir / filename

        # 1. Synthesize raw audio locally via Kokoro ONNX
        success, duration = self.tts_engine.generate_kokoro_audio(
            text=script_info["text"],
            output_path=raw_path,
            voice=voice_id,
            speed=variant_cfg["speed"],
            sentence_pause=variant_cfg["sentence_pause"],
            clause_pause=variant_cfg["clause_pause"]
        )

        # 2. Apply presence & broadcast leveling chain
        proc_success = self.apply_presence_processing(
            raw_wav=raw_path,
            proc_wav=out_path,
            presence_boost_db=variant_cfg["presence_boost_db"],
            eq_freq_hz=variant_cfg["eq_freq_hz"],
            target_lufs=variant_cfg["target_lufs"]
        )

        # Clean up temporary raw WAV
        raw_path.unlink(missing_ok=True)

        # 3. Calculate technical measurements
        metrics = self.calculate_audio_metrics(out_path)

        return {
            "voice_id": voice_id,
            "gender": variant_cfg["gender"],
            "variant": full_variant_key,
            "script_id": script_key,
            "script_archetype": script_info["archetype"],
            "script_title": script_info["title"],
            "script_text": script_info["text"],
            "delivery_profile": variant_cfg["delivery_profile"],
            "speech_rate": variant_cfg["speed"],
            "sentence_pause": variant_cfg["sentence_pause"],
            "clause_pause": variant_cfg["clause_pause"],
            "presence_boost_db": variant_cfg["presence_boost_db"],
            "eq_freq_hz": variant_cfg["eq_freq_hz"],
            "target_lufs": variant_cfg["target_lufs"],
            "processing_parameters": {
                "highpass_hz": 80,
                "eq_gain_db": variant_cfg["presence_boost_db"],
                "eq_center_hz": variant_cfg["eq_freq_hz"],
                "true_peak_ceiling_dbfs": -1.2,
                "target_lufs": variant_cfg["target_lufs"]
            },
            "output_path": str(out_path),
            "filename": filename,
            "synthesis_success": success and proc_success,
            "audio_metadata": metrics
        }

    def run_audition_battery(self) -> Dict[str, Any]:
        """Runs the entire Round 4 audition battery (40 samples)."""
        logger.info("[AUDITION_ROUND4] Beginning execution for am_liam and af_sarah...")
        samples: List[Dict[str, Any]] = []

        for voice_id in ["am_liam", "af_sarah"]:
            for script_key, variant_suffix in SAMPLE_PLAN:
                sample_data = self.render_audition_sample(
                    voice_id=voice_id,
                    variant_suffix=variant_suffix,
                    script_key=script_key
                )
                samples.append(sample_data)

        manifest = {
            "audition_round": "4.0.0",
            "audition_purpose": "Final Liam + Sarah Voice Tuning (Creator Delivery / High Presence)",
            "voices_tested": ["am_liam", "af_sarah"],
            "total_samples_rendered": len(samples),
            "output_directory": str(self.output_dir),
            "production_voice_modified": False,
            "manifest_entries": samples
        }

        manifest_path = self.output_dir / "voice_audition_round4_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"[AUDITION_ROUND4] Finished. {len(samples)} samples saved to {manifest_path}.")
        return manifest
