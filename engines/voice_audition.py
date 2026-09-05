"""
AL-AMR Voice Audition & Comparative Evaluation Engine.
Provides deterministic, offline audition rendering across candidate voices
and directorial speaking styles without modifying production defaults.

Audition Script Battery:
A. Normal Conversational Explanation
B. Breaking-News Energy
C. Suspense / Reveal
D. Sarcastic / Light Reaction
E. Serious Investigative Narration
F. Informal Creator-Style Narration
"""
import os
import json
import wave
import math
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import soundfile as sf
import numpy as np

from config.settings import VOICE_DIR, RENDERS_DIR
from engines.tts_engine import TTSEngine, resolve_voice_config
from engines.visual_intelligence.voice_delivery import DeliveryDirector, DeliveryProfile, ProfanityLevel, DeliverySpec

logger = logging.getLogger(__name__)

AUDITIONS_DIR = RENDERS_DIR / "voice_auditions"

AUDITION_SCRIPTS: Dict[str, Dict[str, Any]] = {
    "SCRIPT_A_CONVERSATIONAL": {
        "title": "Normal Conversational Explanation",
        "profile": DeliveryProfile.CONVERSATIONAL,
        "intensity": "MEDIUM",
        "text": "So here is what everyone is missing about this treaty. It was not signed in secret, but buried in paragraph forty-two was a single clause that shifted fifty billion dollars overnight."
    },
    "SCRIPT_B_URGENT": {
        "title": "Breaking-News Energy",
        "profile": DeliveryProfile.URGENT,
        "intensity": "HIGH",
        "text": "Breaking right now. Multiple diplomatic sources confirm the emergency vote just collapsed in Berlin, triggering an immediate midnight cabinet resignation."
    },
    "SCRIPT_C_SUSPENSE": {
        "title": "Suspense / Reveal",
        "profile": DeliveryProfile.SHOCK_REVEAL,
        "intensity": "CLIMAX",
        "text": "For forty years, naval intelligence assumed the missing submarine had sunk in deep water. They were wrong -- satellite scans just found it hidden in plain sight."
    },
    "SCRIPT_D_SARCASTIC": {
        "title": "Sarcastic / Light Reaction",
        "profile": DeliveryProfile.SARCASTIC_LIGHT,
        "intensity": "MEDIUM",
        "text": "Apparently, the defense ministry spent forty-two million dollars studying if goats can detect radar. The official conclusion? No. They just eat the cables."
    },
    "SCRIPT_E_INVESTIGATIVE": {
        "title": "Serious Investigative Narration",
        "profile": DeliveryProfile.INVESTIGATIVE,
        "intensity": "HIGH",
        "text": "Follow the paper trail. Three offshore shell corporations, all registered on the exact same morning, controlled ninety percent of the emergency grain shipment."
    },
    "SCRIPT_F_INFORMAL": {
        "title": "Informal Creator-Style Narration",
        "profile": DeliveryProfile.CONVERSATIONAL,
        "intensity": "HIGH",
        "text": "Look, this entire situation is completely wild. The minister literally forgot his own security briefing on a public train, and people only noticed when it leaked on Reddit."
    }
}

AUDITION_CANDIDATE_VOICES = [
    {
        "voice_id": "af_bella",
        "display_name": "Bella (US Female - Current Default)",
        "timbre": "High-energy, crisp, viral pacing",
        "persona": "Energetic Commentator"
    },
    {
        "voice_id": "af_heart",
        "display_name": "Heart (US Female)",
        "timbre": "Natural, expressive, nuanced inflection, authentic creator tone",
        "persona": "Natural Creator / Explainer"
    },
    {
        "voice_id": "am_michael",
        "display_name": "Michael (US Male)",
        "timbre": "Conversational, articulate, engaging storyteller",
        "persona": "Engaged Storyteller"
    },
    {
        "voice_id": "am_adam",
        "display_name": "Adam (US Male)",
        "timbre": "Deep, resonant, authoritative documentary weight",
        "persona": "Authoritative Investigator"
    },
    {
        "voice_id": "af_nova",
        "display_name": "Nova (US Female)",
        "timbre": "Bright, modern, clear, engaging pacing",
        "persona": "Dynamic Explainer"
    },
    {
        "voice_id": "am_fenrir",
        "display_name": "Fenrir (US Male)",
        "timbre": "Low cinematic baritone, dramatic weight",
        "persona": "Cinematic Narrator"
    }
]


class VoiceAuditionEngine:
    """
    Renders standardized comparative audition batteries across candidate voices
    and speaking styles. Produces a structured JSON manifest with technical audio analysis.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or AUDITIONS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.tts_engine = TTSEngine()
        self.delivery_director = DeliveryDirector()

    def calculate_audio_metadata(self, audio_path: Path) -> Dict[str, Any]:
        """Extracts technical audio parameters: duration, RMS dB, Peak dB, sample rate, channels."""
        if not audio_path.exists() or audio_path.stat().st_size == 0:
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_db": -99.0,
                "rms_db": -99.0,
                "file_size_bytes": 0
            }

        try:
            data, sr = sf.read(str(audio_path))
            duration = round(len(data) / float(sr), 2)
            channels = 1 if data.ndim == 1 else data.shape[1]

            # Peak and RMS calculation
            peak = float(np.max(np.abs(data)))
            peak_db = round(20 * math.log10(max(peak, 1e-6)), 2)
            rms = float(np.sqrt(np.mean(data ** 2)))
            rms_db = round(20 * math.log10(max(rms, 1e-6)), 2)

            return {
                "duration_sec": duration,
                "sample_rate": sr,
                "channels": channels,
                "peak_db": peak_db,
                "rms_db": rms_db,
                "file_size_bytes": audio_path.stat().st_size
            }
        except Exception as e:
            logger.warning(f"Failed to read audio metadata for {audio_path}: {e}")
            return {
                "duration_sec": 0.0,
                "sample_rate": 0,
                "channels": 0,
                "peak_db": -99.0,
                "rms_db": -99.0,
                "file_size_bytes": audio_path.stat().st_size if audio_path.exists() else 0,
                "error": str(e)
            }

    def run_audition_battery(
        self,
        candidate_voices: Optional[List[Dict[str, Any]]] = None,
        script_keys: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Executes comparative audition rendering offline.
        Does NOT change system configuration or active production voice.
        """
        candidates = candidate_voices or AUDITION_CANDIDATE_VOICES
        target_scripts = script_keys or list(AUDITION_SCRIPTS.keys())

        results: List[Dict[str, Any]] = []

        logger.info(f"[VOICE_AUDITION] Beginning audition battery: {len(candidates)} voices x {len(target_scripts)} scripts")

        for voice_info in candidates:
            voice_id = voice_info["voice_id"]
            for s_key in target_scripts:
                s_info = AUDITION_SCRIPTS[s_key]
                profile = s_info["profile"]
                intensity = s_info.get("intensity", "MEDIUM")

                # Build delivery directives
                spec = self.delivery_director.build_delivery_spec(
                    profile=profile,
                    raw_text=s_info["text"],
                    intensity=intensity
                )

                out_filename = f"audition_{voice_id}_{s_key}.wav"
                out_path = self.output_dir / out_filename

                # Synthesize locally with Kokoro
                success, duration = self.tts_engine.generate_kokoro_audio(
                    text=spec.prepared_text,
                    output_path=out_path,
                    voice=voice_id,
                    speed=spec.speed_multiplier,
                    sentence_pause=spec.sentence_pause_sec,
                    clause_pause=spec.clause_pause_sec
                )

                meta = self.calculate_audio_metadata(out_path)

                entry = {
                    "voice_id": voice_id,
                    "voice_display_name": voice_info["display_name"],
                    "voice_persona": voice_info["persona"],
                    "script_key": s_key,
                    "script_title": s_info["title"],
                    "delivery_profile": profile.value,
                    "speed_multiplier": spec.speed_multiplier,
                    "sentence_pause_sec": spec.sentence_pause_sec,
                    "clause_pause_sec": spec.clause_pause_sec,
                    "intensity": spec.intensity,
                    "text_synthesized": spec.prepared_text,
                    "output_file": str(out_path),
                    "generation_status": "SUCCESS" if success else "FAILED",
                    "audio_metadata": meta
                }
                results.append(entry)

        manifest = {
            "audition_version": "1.0.0",
            "total_candidates": len(candidates),
            "total_scripts": len(target_scripts),
            "total_samples_rendered": len(results),
            "output_directory": str(self.output_dir),
            "production_voice_modified": False,
            "manifest_entries": results
        }

        manifest_path = self.output_dir / "voice_audition_manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        logger.info(f"[VOICE_AUDITION] Manifest saved to {manifest_path} ({len(results)} samples)")
        return manifest
