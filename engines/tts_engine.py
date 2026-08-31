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
        "id": "af_bella",
        "display_name": "Bella (US Female)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "Clear, crisp, and high-energy narration. Best for fast-paced viral hooks and sudden twists.",
        "style": "Dynamic / Engaging",
        "gender": "Female",
        "accent": "American",
        "kokoro_voice": "af_bella",
        "edge_voice": "en-US-JennyNeural",
        "available": True
    },
    {
        "id": "am_adam",
        "display_name": "Adam (US Male)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "Deep documentary tone with confident, steady pacing. Best for serious historical events and unusual wars.",
        "style": "Deep Documentary",
        "gender": "Male",
        "accent": "American",
        "kokoro_voice": "am_adam",
        "edge_voice": "en-US-GuyNeural",
        "available": True
    },
    {
        "id": "am_michael",
        "display_name": "Michael (US Male)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "Natural conversational storytelling with engaging inflection. Best for mysteries and historical oddities.",
        "style": "Storyteller / Natural",
        "gender": "Male",
        "accent": "American",
        "kokoro_voice": "am_michael",
        "edge_voice": "en-US-EricNeural",
        "available": True
    },
    {
        "id": "af_sarah",
        "display_name": "Sarah (US Female)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "Warm, measured, and authoritative documentary delivery. Best for poignant human stories.",
        "style": "Warm / Professional",
        "gender": "Female",
        "accent": "American",
        "kokoro_voice": "af_sarah",
        "edge_voice": "en-US-AriaNeural",
        "available": True
    },
    {
        "id": "bm_george",
        "display_name": "George (UK Male)",
        "engine": "Kokoro-82M ONNX / Edge-TTS",
        "description": "BBC-style classical British narrator with stately cadence. Best for medieval, monarchies, and ancient empires.",
        "style": "BBC Classical / Royal",
        "gender": "Male",
        "accent": "British",
        "kokoro_voice": "bm_george",
        "edge_voice": "en-GB-RyanNeural",
        "available": True
    },
    {
        "id": "en-US-ChristopherNeural",
        "display_name": "Christopher (US Male)",
        "engine": "Edge-TTS Neural / Kokoro",
        "description": "Deep cinematic broadcast narration with neural clarity.",
        "style": "Deep Cinematic",
        "gender": "Male",
        "accent": "American",
        "kokoro_voice": "am_fenrir",
        "edge_voice": "en-US-ChristopherNeural",
        "available": True
    }
]


def resolve_voice_config(voice_id: str) -> dict:
    """
    Authoritative voice configuration resolver.
    Returns the canonical voice entry for any supported voice_id, ensuring
    both Kokoro and Edge-TTS providers resolve to the exact intended voice profile.
    """
    for v in AVAILABLE_VOICES:
        if v["id"] == voice_id:
            return v
    # Fallback to default canonical voice (Bella)
    return AVAILABLE_VOICES[0]


def get_active_voice(db: Optional[Session] = None) -> str:
    """Retrieves active production voice preference from SQLite, falling back to settings."""
    session = db
    close_session = False
    if session is None:
        try:
            from core.database import SessionLocal
            session = SessionLocal()
            close_session = True
        except Exception:
            session = None

    if session is not None:
        try:
            cfg = session.query(SystemConfig).filter(SystemConfig.key == "active_voice").first()
            if cfg and cfg.value:
                # Verify voice exists in library
                if any(v["id"] == cfg.value for v in AVAILABLE_VOICES):
                    return cfg.value
        except Exception as e:
            logger.debug(f"Could not read active_voice from DB: {e}")
        finally:
            if close_session:
                session.close()

    return KOKORO_VOICE or "af_bella"


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
        edge_v = v_cfg.get("edge_voice", "en-US-GuyNeural")

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

    def generate_narration(
        self,
        db: Session,
        text: str,
        speed_multiplier: float = 1.0,
        voice: Optional[str] = None
    ) -> Tuple[AssetRecord, float]:
        """
        Generates full narration audio using the persistent active voice setting (or explicit run voice),
        adjusts speed if needed to fit 21-25s, and saves AssetRecord with verified license.
        Guarantees that active voice resolution is 100% identical to the preview path.
        """
        asset_id = f"aud_{uuid.uuid4().hex[:12]}"
        wav_path = self.voice_dir / f"{asset_id}.wav"

        active_voice = voice or get_active_voice(db)
        v_cfg = resolve_voice_config(active_voice)
        kokoro_v = v_cfg.get("kokoro_voice", active_voice)
        edge_v = v_cfg.get("edge_voice", "en-US-GuyNeural")

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
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(text, mp3_path, voice=edge_v))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value
        else:
            # 2. Kokoro TTS route
            success, duration = self.generate_kokoro_audio(text, wav_path, voice=kokoro_v, speed=speed_multiplier)

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
            success, duration = loop.run_until_complete(self._generate_edge_tts_async(text, mp3_path, voice=edge_v))
            if success:
                wav_path = mp3_path
                tts_source = "edge_tts"
                license_type = LicenseType.AI_GENERATED_OPEN.value

        # 4. Check Duration Sanity & Calibrate
        if duration < MIN_DURATION_SEC and duration > 16.0:
            logger.info(f"Duration {duration}s slightly short; re-synthesizing at 0.92x speed...")
            if tts_source == "kokoro":
                success, duration = self.generate_kokoro_audio(text, wav_path, voice=kokoro_v, speed=0.92)
        elif duration > MAX_DURATION_SEC and duration < 30.0:
            logger.info(f"Duration {duration}s slightly long; re-synthesizing at 1.08x speed...")
            if tts_source == "kokoro":
                success, duration = self.generate_kokoro_audio(text, wav_path, voice=kokoro_v, speed=1.08)

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
