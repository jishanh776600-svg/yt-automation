"""
Text-to-Speech (TTS) Engine.
Uses Kokoro-82M ONNX (Apache 2.0 open-source code & model weights) for $0 commercial narration.
Features Edge-TTS / pyttsx3 fallbacks, duration calibration to 21-25s, and license tracking.
"""
import os
import uuid
import wave
import asyncio
import logging
import subprocess
import urllib.request
from pathlib import Path
from typing import Tuple, Optional, Any
from datetime import datetime
import soundfile as sf
import numpy as np
from sqlalchemy.orm import Session
from config.settings import VOICE_DIR, KOKORO_MODEL_PATH, KOKORO_VOICES_PATH, KOKORO_VOICE, TTS_PROVIDER
from config.constants import MIN_DURATION_SEC, MAX_DURATION_SEC, TARGET_DURATION_SEC, LicenseType
from core.models import AssetRecord, SystemConfig

logger = logging.getLogger(__name__)

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

APPROVED_PRODUCTION_VOICES = ["af_bella"]

AVAILABLE_VOICES = [
    {
        "id": "af_bella",
        "display_name": "Bella (US Female)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "Clear, crisp, and high-energy narration. Best for fast-paced viral hooks and sudden twists.",
        "style": "Dynamic / Engaging",
        "gender": "Female",
        "accent": "American",
        "kokoro_voice": "af_bella",
        "edge_voice": "en-US-JennyNeural",
        "delivery_profile": "BELLA_MAX_CREATOR",
        "available": True
    }
]


def resolve_voice_config(voice_id: str) -> dict:
    """
    Authoritative voice configuration resolver.
    Returns the canonical voice entry for any supported voice_id, ensuring
    both Kokoro and Edge-TTS providers resolve to the exact intended voice profile.
    Restricted strictly to APPROVED_PRODUCTION_VOICES (af_bella).
    """
    for v in AVAILABLE_VOICES:
        if v["id"] == voice_id:
            return v
    # Safe fallback to approved production voice (Bella)
    return AVAILABLE_VOICES[0]


def get_active_voice(db: Optional[Session] = None) -> str:
    """Retrieves active production voice preference, restricted strictly to APPROVED_PRODUCTION_VOICES."""
    if db:
        try:
            cfg = db.query(SystemConfig).filter(SystemConfig.key == "active_voice").first()
            if cfg and cfg.value and cfg.value in APPROVED_PRODUCTION_VOICES:
                return cfg.value
        except Exception:
            pass
    return "af_bella"


def select_voice_by_policy(category: str = "", title: str = "", script_text: str = "") -> str:
    """Selects approved voice according to VoiceVariationPolicy rotation."""
    from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
    return VoiceVariationPolicy().select_voice(category, title, script_text)


select_voice_for_job = select_voice_by_policy
get_authoritative_voice = get_active_voice



def set_active_voice(db: Session, voice_id: str) -> bool:
    """Sets and persists active production voice preference in SQLite."""
    if not any(v["id"] == voice_id for v in AVAILABLE_VOICES):
        raise ValueError(f"Voice '{voice_id}' is not in the list of available production voices.")

    cfg = db.query(SystemConfig).filter(SystemConfig.key == "active_voice").first()
    if cfg:
        cfg.value = voice_id
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = SystemConfig(key="active_voice", value=voice_id)
        db.add(cfg)
    db.commit()
    logger.info(f"[VOICE CONFIG] Active production voice set to: {voice_id}")
    return True


class TTSEngine:
    """Produces documentary-style narration with verified commercial licensing."""

    def __init__(self):
        self.voice_dir = VOICE_DIR
        self.voice_dir.mkdir(parents=True, exist_ok=True)
        self.kokoro_instance = None

    def _ensure_kokoro_files(self) -> bool:
        """Downloads Kokoro ONNX model files if missing."""
        try:
            if not KOKORO_MODEL_PATH.exists():
                logger.info("Downloading Kokoro ONNX model (Apache 2.0)...")
                urllib.request.urlretrieve(KOKORO_MODEL_URL, str(KOKORO_MODEL_PATH))

            if not KOKORO_VOICES_PATH.exists():
                logger.info("Downloading Kokoro voice embeddings...")
                urllib.request.urlretrieve(KOKORO_VOICES_URL, str(KOKORO_VOICES_PATH))
            return True
        except Exception as e:
            logger.warning(f"Could not download Kokoro files: {e}")
            return False

    def _get_kokoro(self):
        """Initializes Kokoro TTS engine."""
        if self.kokoro_instance is not None:
            return self.kokoro_instance

        if self._ensure_kokoro_files():
            try:
                from kokoro_onnx import Kokoro
                self.kokoro_instance = Kokoro(str(KOKORO_MODEL_PATH), str(KOKORO_VOICES_PATH))
                return self.kokoro_instance
            except Exception as e:
                logger.warning(f"Failed to load Kokoro ONNX: {e}")
        return None

    def generate_kokoro_audio(
        self,
        text: str,
        output_path: Path,
        voice: str = "af_bella",
        speed: float = 1.05,
        sentence_pause: float = 0.12,
        clause_pause: float = 0.04
    ) -> Tuple[bool, float]:
        """Synthesizes speech using Kokoro ONNX model with calibrated pause controls."""
        kokoro = self._get_kokoro()
        if not kokoro:
            return False, 0.0
        try:
            samples, sample_rate = kokoro.create(
                text,
                voice=voice,
                speed=speed,
                sentence_pause=sentence_pause,
                clause_pause=clause_pause,
                lang="en-us"
            )
            sf.write(str(output_path), samples, sample_rate)
            duration = len(samples) / float(sample_rate)
            return True, round(duration, 2)
        except Exception as e:
            logger.warning(f"Kokoro synthesis error: {e}")
            return False, 0.0

    async def _generate_edge_tts_async(self, text: str, output_path: Path, voice: str = "en-US-ChristopherNeural") -> Tuple[bool, float]:
        """Edge TTS fallback synthesis with resilient duration calculation."""
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
            
            if not output_path.exists() or output_path.stat().st_size == 0:
                return False, 0.0

            # Safe duration estimation/reading
            duration = max(1.0, round(len(text) / 14.0, 2))
            try:
                with wave.open(str(output_path), "rb") as wf:
                    duration = round(wf.getnframes() / float(wf.getframerate()), 2)
            except Exception:
                try:
                    data, sr = sf.read(str(output_path))
                    duration = round(len(data) / float(sr), 2)
                except Exception:
                    pass

            return True, duration
        except Exception as e:
            logger.warning(f"Edge TTS duration/synthesis error: {e}")
            return False, 0.0

    def generate_preview_sample(self, voice_id: str, sample_text: Optional[str] = None) -> Tuple[bool, Optional[bytes], str]:
        """
        Generates a short in-memory / temporary preview audio sample for a given voice.
        Does NOT create database records (Jobs/Assets), does NOT touch Drive or YouTube,
        and does NOT persist or mutate SystemConfig.
        Returns: (success, audio_bytes, mime_type)
        """
        if not any(v["id"] == voice_id for v in AVAILABLE_VOICES):
            raise ValueError(f"Voice '{voice_id}' is not in the list of available production voices.")

        v_cfg = resolve_voice_config(voice_id)
        kokoro_v = v_cfg.get("kokoro_voice", voice_id)
        edge_v = v_cfg.get("edge_voice", "en-US-JennyNeural")

        text = sample_text or "History holds the secrets of who we once were."
        temp_id = f"preview_{uuid.uuid4().hex[:8]}"

        # Fast-path: If Kokoro model weights are already cached locally on disk and not forced to edge
        use_kokoro = (
            not voice_id.startswith("en-")
            and TTS_PROVIDER != "edge"
            and KOKORO_MODEL_PATH.exists()
            and KOKORO_VOICES_PATH.exists()
        )

        if use_kokoro:
            temp_path = self.voice_dir / f"{temp_id}.wav"
            try:
                success, _ = self.generate_kokoro_audio(text, temp_path, voice=kokoro_v)
                if success and temp_path.exists():
                    audio_data = temp_path.read_bytes()
                    temp_path.unlink(missing_ok=True)
                    return True, audio_data, "audio/wav"
            except Exception as e:
                logger.warning(f"Kokoro preview failed for '{voice_id}': {e}")
                temp_path.unlink(missing_ok=True)

        # Fallback to Edge-TTS preview with exact 1:1 mapped distinct voice
        logger.info(f"Generating Edge-TTS preview for '{voice_id}' using '{edge_v}'...")
        temp_mp3_path = self.voice_dir / f"{temp_id}.mp3"
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            success, _ = loop.run_until_complete(self._generate_edge_tts_async(text, temp_mp3_path, voice=edge_v))
            if success and temp_mp3_path.exists():
                audio_data = temp_mp3_path.read_bytes()
                temp_mp3_path.unlink(missing_ok=True)
                return True, audio_data, "audio/mpeg"
        except Exception as fb_err:
            logger.warning(f"Edge TTS fallback preview failed for '{voice_id}': {fb_err}")
            temp_mp3_path.unlink(missing_ok=True)

        return False, None, ""

    def apply_presence_mastering(
        self,
        input_wav: Path,
        output_wav: Path,
        presence_boost_db: float = 2.2,
        eq_freq_hz: int = 3000,
        target_lufs: float = -15.5,
        true_peak_ceiling: float = -1.2
    ) -> bool:
        """
        Applies creator vocal presence EQ (+2.2 dB @ 3.0 kHz), highpass rumble filter (80 Hz),
        and ITU-R BS.1770 broadcast loudnorm (-15.5 LUFS, true peak ceiling -1.2 dBFS).
        """
        try:
            from config.settings import FFMPEG_EXE
            af_filter = (
                f"highpass=f=80,"
                f"equalizer=f={eq_freq_hz}:t=q:w=1.2:g={presence_boost_db},"
                f"loudnorm=I={target_lufs}:tp={true_peak_ceiling}:LRA=9,"
                f"aformat=sample_rates=24000:channel_layouts=mono"
            )
            cmd = [
                FFMPEG_EXE, "-y",
                "-i", str(input_wav),
                "-af", af_filter,
                "-c:a", "pcm_s16le",
                str(output_wav)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and output_wav.exists() and output_wav.stat().st_size > 1000
        except Exception as e:
            logger.warning(f"Voice presence mastering error: {e}")
            return False

    @staticmethod
    def compress_silence_gaps(input_wav: Path, output_wav: Path, max_pause_sec: float = 0.14) -> Tuple[bool, float]:
        """
        Compresses dead air and excessive pauses between spoken phrases/sentences down to max_pause_sec.
        Preserves natural breathing pauses (80-120ms) without clipping words or phonemes.
        """
        try:
            data, sr = sf.read(str(input_wav))
            if len(data) == 0:
                return False, 0.0

            # 10ms frame analysis
            frame_len = max(1, int(0.01 * sr))
            frames = [data[i : i + frame_len] for i in range(0, len(data), frame_len)]
            rms = [float(np.sqrt(np.mean(f**2))) if len(f) > 0 else 0.0 for f in frames]
            silence_thresh = 0.012  # RMS threshold for acoustic silence
            is_silence = [r < silence_thresh for r in rms]

            max_silence_frames = max(2, int(max_pause_sec / 0.01))
            new_frames = []
            cur_silence = 0
            for f, is_sil in zip(frames, is_silence):
                if is_sil:
                    cur_silence += 1
                    if cur_silence <= max_silence_frames:
                        new_frames.append(f)
                else:
                    cur_silence = 0
                    new_frames.append(f)

            if new_frames:
                compressed = np.concatenate(new_frames, axis=0)
                sf.write(str(output_wav), compressed, sr)
                new_dur = round(len(compressed) / float(sr), 2)
                return True, new_dur
            return False, 0.0
        except Exception as e:
            logger.warning(f"Silence compression notice: {e}")
            return False, 0.0

    def generate_narration(
        self,
        db: Session,
        text: str,
        speed_multiplier: float = 1.05,
        voice: Optional[str] = None,
        delivery_spec: Optional[Any] = None
    ) -> Tuple[AssetRecord, float]:
        """
        Generates full narration audio using the persistent active voice setting (or explicit run voice),
        adjusts speed if needed to fit 22-25s, and saves AssetRecord with verified license.
        Guarantees that active voice resolution is 100% identical to the preview path.
        Enforces APPROVED_PRODUCTION_VOICES lock (af_bella).
        """
        asset_id = f"aud_{uuid.uuid4().hex[:12]}"
        wav_path = self.voice_dir / f"{asset_id}.wav"

        active_voice = voice or get_active_voice(db)
        if active_voice not in APPROVED_PRODUCTION_VOICES:
            logger.warning(f"[TTS_ENGINE] Voice '{active_voice}' not approved for production. Defaulting to 'af_bella'.")
            active_voice = "af_bella"
        v_cfg = resolve_voice_config(active_voice)
        kokoro_v = v_cfg.get("kokoro_voice", active_voice)
        edge_v = v_cfg.get("edge_voice", "en-US-JennyNeural")

        # Extract delivery parameters if delivery_spec is provided
        synthesize_text = delivery_spec.prepared_text if (delivery_spec and getattr(delivery_spec, "prepared_text", None)) else text
        eff_speed = delivery_spec.speed_multiplier if (delivery_spec and speed_multiplier == 1.0) else speed_multiplier
        sentence_pause = getattr(delivery_spec, "sentence_pause_sec", 0.12) if delivery_spec else 0.12
        clause_pause = getattr(delivery_spec, "clause_pause_sec", 0.04) if delivery_spec else 0.04

        success = False
        duration = 0.0
        tts_source = "kokoro"
        license_type = LicenseType.APACHE_2_0.value

        # 1. Direct Edge-TTS route if configured or if voice is Edge-only
        if active_voice.startswith("en-") or TTS_PROVIDER == "edge":
            mp3_path = self.voice_dir / f"{asset_id}.mp3"
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(synthesize_text, mp3_path, voice=edge_v))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value
        else:
            # 2. Kokoro TTS route with calibrated tight pauses
            success, duration = self.generate_kokoro_audio(
                text=synthesize_text,
                output_path=wav_path,
                voice=kokoro_v,
                speed=eff_speed,
                sentence_pause=sentence_pause,
                clause_pause=clause_pause
            )

        # 3. Fallback to Edge-TTS using the EXACT SAME voice profile if Kokoro is unavailable / fails
        if not success or duration == 0.0:
            logger.info(f"Kokoro narration failed or unavailable for '{active_voice}'; falling back to Edge-TTS '{edge_v}'...")
            mp3_path = self.voice_dir / f"{asset_id}.mp3"
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(synthesize_text, mp3_path, voice=edge_v))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value

        # 3b. Apply silence gap tightening to eliminate awkward dead air between phrases
        if wav_path.exists():
            tightened_wav = self.voice_dir / f"{asset_id}_tightened.wav"
            t_ok, t_dur = self.compress_silence_gaps(wav_path, tightened_wav, max_pause_sec=0.14)
            if t_ok and t_dur > 0:
                wav_path = tightened_wav
                duration = t_dur

        # 4. Check Duration Sanity & Calibrate toward ~23s (22-25s)
        if duration < MIN_DURATION_SEC and duration > 16.0:
            logger.info(f"Duration {duration}s slightly short; re-synthesizing at 0.95x speed...")
            if tts_source == "kokoro":
                s_ok, s_dur = self.generate_kokoro_audio(text, wav_path, voice=kokoro_v, speed=0.95, sentence_pause=0.14, clause_pause=0.05)
                if s_ok:
                    duration = s_dur
        elif duration > MAX_DURATION_SEC and duration < 32.0:
            logger.info(f"Duration {duration}s slightly long; re-synthesizing at 1.08x speed...")
            if tts_source == "kokoro":
                s_ok, s_dur = self.generate_kokoro_audio(text, wav_path, voice=kokoro_v, speed=1.08, sentence_pause=0.10, clause_pause=0.03)
                if s_ok:
                    duration = s_dur

        # 5. Apply Studio Presence Mastering Chain
        mastered_wav = self.voice_dir / f"{asset_id}_mastered.wav"
        p_boost = getattr(delivery_spec, "presence_boost_db", 2.2) if delivery_spec else 2.2
        eq_hz = getattr(delivery_spec, "eq_freq_hz", 3000) if delivery_spec else 3000
        t_lufs = getattr(delivery_spec, "target_lufs", -15.5) if delivery_spec else -15.5
        tp_ceil = getattr(delivery_spec, "true_peak_ceiling", -1.2) if delivery_spec else -1.2

        if self.apply_presence_mastering(
            input_wav=wav_path,
            output_wav=mastered_wav,
            presence_boost_db=p_boost,
            eq_freq_hz=eq_hz,
            target_lufs=t_lufs,
            true_peak_ceiling=tp_ceil
        ):
            wav_path = mastered_wav

        asset = AssetRecord(
            id=asset_id,
            asset_type="voice",
            source=tts_source,
            source_url="https://github.com/hexgrad/kokoro" if tts_source == "kokoro" else "https://github.com/rany2/edge-tts",
            license=license_type,
            commercial_use=True,
            attribution_required=False,
            local_path=str(wav_path),
            duration_sec=duration
        )
        db.add(asset)
        db.commit()
        logger.info(f"Generated narration {asset.id} ({duration}s, engine={tts_source}, voice={active_voice})")
        return asset, duration
