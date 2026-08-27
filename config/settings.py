"""
System Settings and Path Configurations.
Loads environment variables and sets defaults for $0-cost operation.
"""
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
DATABASE_DIR = DATA_DIR / "database"
TOPICS_DIR = DATA_DIR / "topics"
RESEARCH_DIR = DATA_DIR / "research"
SCRIPTS_DIR = DATA_DIR / "scripts"
STORYBOARDS_DIR = DATA_DIR / "storyboards"
ASSETS_CACHE_DIR = DATA_DIR / "assets"
VOICE_DIR = DATA_DIR / "voice"
CAPTIONS_DIR = DATA_DIR / "captions"
RENDERS_DIR = DATA_DIR / "renders"
PUBLISHED_DIR = DATA_DIR / "published"
LOGS_DIR = DATA_DIR / "logs"

ASSETS_DIR = PROJECT_ROOT / "assets"
MUSIC_DIR = ASSETS_DIR / "music"
SFX_DIR = ASSETS_DIR / "sfx"
FONTS_DIR = ASSETS_DIR / "fonts"

DB_PATH = DATABASE_DIR / "pipeline.db"

# Ensure runtime directories exist
for d in [DATABASE_DIR, TOPICS_DIR, RESEARCH_DIR, SCRIPTS_DIR, STORYBOARDS_DIR,
          ASSETS_CACHE_DIR, VOICE_DIR, CAPTIONS_DIR, RENDERS_DIR, PUBLISHED_DIR,
          LOGS_DIR, MUSIC_DIR, SFX_DIR, FONTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Environment Variables & Keys
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE", str(PROJECT_ROOT / "client_secret.json"))

# TTS Settings
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "kokoro")  # kokoro, edge, piper
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "am_adam")
KOKORO_MODEL_PATH = DATA_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = DATA_DIR / "voices-v1.0.bin"

# Image Generation Fallback Provider
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")

# Publishing Frequency
SHORTS_PER_DAY = int(os.getenv("SHORTS_PER_DAY", "2"))
PUBLISH_TIME_SLOTS = ["14:00", "20:00"]


def get_ffmpeg_path() -> str:
    """Finds valid FFmpeg binary path."""
    ffmpeg_sys = shutil.which("ffmpeg")
    if ffmpeg_sys:
        return ffmpeg_sys
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FFMPEG_EXE = get_ffmpeg_path()
