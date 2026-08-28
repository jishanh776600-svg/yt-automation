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
import urllib.request
from pathlib import Path
from typing import Tuple, Optional
from datetime import datetime
import soundfile as sf
from sqlalchemy.orm import Session
from config.settings import VOICE_DIR, KOKORO_MODEL_PATH, KOKORO_VOICES_PATH, KOKORO_VOICE, TTS_PROVIDER
from config.constants import MIN_DURATION_SEC, MAX_DURATION_SEC, TARGET_DURATION_SEC, LicenseType
from core.models import AssetRecord, SystemConfig

logger = logging.getLogger(__name__)

KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

AVAILABLE_VOICES = [
    {
        "id": "am_adam",
        "display_name": "Adam (US Male)",
        "engine": "Kokoro-82M ONNX",
        "description": "Deep documentary tone with confident, steady pacing. Best for serious historical events and unusual wars.",
        "style": "Deep Documentary",
        "gender": "Male",
        "accent": "American",
        "available": True
    },
    {
        "id": "am_michael",
        "display_name": "Michael (US Male)",
        "engine": "Kokoro-82M ONNX",
        "description": "Natural conversational storytelling with engaging inflection. Best for mysteries and historical oddities.",
        "style": "Storyteller / Natural",
        "gender": "Male",
        "accent": "American",
        "available": True
    },
    {
        "id": "af_bella",
        "display_name": "Bella (US Female)",
        "engine": "Kokoro-82M ONNX",
        "description": "Clear, crisp, and high-energy narration. Best for fast-paced viral hooks and sudden twists.",
        "style": "Dynamic / Engaging",
        "gender": "Female",
        "accent": "American",
        "available": True
    },
    {
        "id": "af_sarah",
        "display_name": "Sarah (US Female)",
        "engine": "Kokoro-82M ONNX",
        "description": "Warm, measured, and authoritative documentary delivery. Best for poignant human stories.",
        "style": "Warm / Professional",
        "gender": "Female",
        "accent": "American",
        "available": True
    },
    {
        "id": "bm_george",
        "display_name": "George (UK Male)",
        "engine": "Kokoro-82M ONNX",
        "description": "BBC-style classical British narrator with stately cadence. Best for medieval, monarchies, and ancient empires.",
        "style": "BBC Classical / Royal",
        "gender": "Male",
        "accent": "British",
        "available": True
    },
    {
        "id": "en-US-ChristopherNeural",
        "display_name": "Christopher (US Male)",
        "engine": "Edge-TTS Neural",
        "description": "Deep cinematic broadcast narration with neural clarity.",
        "style": "Deep Cinematic",
        "gender": "Male",
        "accent": "American",
        "available": True
    }
]


def get_active_voice(db: Optional[Session] = None) -> str:
    """Retrieves active production voice preference from SQLite, falling back to settings."""
    if db is not None:
        try:
            cfg = db.query(SystemConfig).filter(SystemConfig.key == "active_voice").first()
            if cfg and cfg.value:
                # Verify voice exists in library
                if any(v["id"] == cfg.value for v in AVAILABLE_VOICES):
                    return cfg.value
        except Exception as e:
            logger.debug(f"Could not read active_voice from DB: {e}")

    return KOKORO_VOICE or "am_adam"


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

    def generate_kokoro_audio(self, text: str, output_path: Path, voice: str = "am_adam", speed: float = 1.0) -> Tuple[bool, float]:
        """Synthesizes speech using Kokoro ONNX model."""
        kokoro = self._get_kokoro()
        if not kokoro:
            return False, 0.0
        try:
            samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang="en-us")
            sf.write(str(output_path), samples, sample_rate)
            duration = len(samples) / float(sample_rate)
            return True, round(duration, 2)
        except Exception as e:
            logger.warning(f"Kokoro synthesis error: {e}")
            return False, 0.0

    async def _generate_edge_tts_async(self, text: str, output_path: Path, voice: str = "en-US-ChristopherNeural") -> Tuple[bool, float]:
        """Edge TTS fallback synthesis."""
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(str(output_path))
            # Read duration
            with wave.open(str(output_path), "rb") as wf:
                duration = wf.getnframes() / float(wf.getframerate())
            return True, round(duration, 2)
        except Exception:
            # If mp3, compute duration via mutagen or soundfile
            try:
                data, sr = sf.read(str(output_path))
                duration = len(data) / float(sr)
                return True, round(duration, 2)
            except Exception as e:
                logger.warning(f"Edge TTS duration read error: {e}")
    def generate_preview_sample(self, voice_id: str, sample_text: Optional[str] = None) -> Tuple[bool, Optional[bytes], str]:
        """
        Generates a short in-memory / temporary preview audio sample for a given voice.
        Does NOT create database records (Jobs/Assets), does NOT touch Drive or YouTube,
        and does NOT persist or mutate SystemConfig.
        Returns: (success, audio_bytes, mime_type)
        """
        if not any(v["id"] == voice_id for v in AVAILABLE_VOICES):
            raise ValueError(f"Voice '{voice_id}' is not in the list of available production voices.")

        text = sample_text or "History holds the secrets of who we once were."
        temp_id = f"preview_{uuid.uuid4().hex[:8]}"

        if voice_id.startswith("en-") or TTS_PROVIDER == "edge":
            temp_path = self.voice_dir / f"{temp_id}.mp3"
            try:
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                success, _ = loop.run_until_complete(self._generate_edge_tts_async(text, temp_path, voice=voice_id))
                if success and temp_path.exists():
                    audio_data = temp_path.read_bytes()
                    temp_path.unlink(missing_ok=True)
                    return True, audio_data, "audio/mp3"
            except Exception as e:
                logger.warning(f"Edge TTS preview failed: {e}")
                temp_path.unlink(missing_ok=True)
        else:
            temp_path = self.voice_dir / f"{temp_id}.wav"
            try:
                success, _ = self.generate_kokoro_audio(text, temp_path, voice=voice_id)
                if success and temp_path.exists():
                    audio_data = temp_path.read_bytes()
                    temp_path.unlink(missing_ok=True)
                    return True, audio_data, "audio/wav"
            except Exception as e:
                logger.warning(f"Kokoro preview failed: {e}")
                temp_path.unlink(missing_ok=True)

        return False, None, ""

    def generate_narration(self, db: Session, text: str, speed_multiplier: float = 1.0) -> Tuple[AssetRecord, float]:
        """
        Generates full narration audio using the persistent active voice setting,
        adjusts speed if needed to fit 21-25s, and saves AssetRecord with verified license.
        """
        asset_id = f"aud_{uuid.uuid4().hex[:12]}"
        wav_path = self.voice_dir / f"{asset_id}.wav"

        active_voice = get_active_voice(db)
        success = False
        duration = 0.0
        tts_source = "kokoro"
        license_type = LicenseType.APACHE_2_0.value

        # 1. Check if chosen voice is Edge-TTS or Kokoro
        if active_voice.startswith("en-") or TTS_PROVIDER == "edge":
            # Direct Edge-TTS route
            mp3_path = self.voice_dir / f"{asset_id}.mp3"
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(text, mp3_path, voice=active_voice))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value
        else:
            # Kokoro TTS route
            success, duration = self.generate_kokoro_audio(text, wav_path, voice=active_voice, speed=speed_multiplier)

        # 2. Fallback to Edge-TTS if Kokoro failed
        if not success or duration == 0.0:
            logger.info("Falling back to Edge-TTS engine...")
            mp3_path = self.voice_dir / f"{asset_id}.mp3"
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(text, mp3_path, voice="en-US-ChristopherNeural"))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value

        # 3. Check Duration Sanity & Calibrate
        if duration < MIN_DURATION_SEC and duration > 16.0:
            logger.info(f"Duration {duration}s slightly short; re-synthesizing at 0.92x speed...")
            if tts_source == "kokoro":
                success, duration = self.generate_kokoro_audio(text, wav_path, voice=active_voice, speed=0.92)
        elif duration > MAX_DURATION_SEC and duration < 30.0:
            logger.info(f"Duration {duration}s slightly long; re-synthesizing at 1.08x speed...")
            if tts_source == "kokoro":
                success, duration = self.generate_kokoro_audio(text, wav_path, voice=active_voice, speed=1.08)

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
        logger.info(f"Generated narration {asset.id} ({duration}s, engine={tts_source})")
        return asset, duration
