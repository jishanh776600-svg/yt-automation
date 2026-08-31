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

LOCKS_DIR = DATA_DIR / "locks"

TEST_DB_PATH = os.getenv("TEST_DB_PATH")
if TEST_DB_PATH:
    DB_PATH = Path(TEST_DB_PATH)
elif os.getenv("IS_TEST_ENV", "").lower() == "true":
    DB_PATH = DATABASE_DIR / "test_pipeline.db"
else:
    DB_PATH = DATABASE_DIR / "pipeline.db"

# Ensure runtime directories exist
for d in [DATABASE_DIR, TOPICS_DIR, RESEARCH_DIR, SCRIPTS_DIR, STORYBOARDS_DIR,
          ASSETS_CACHE_DIR, VOICE_DIR, CAPTIONS_DIR, RENDERS_DIR, PUBLISHED_DIR,
          LOGS_DIR, LOCKS_DIR, MUSIC_DIR, SFX_DIR, FONTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Environment Variables & Keys
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_API_KEY_SECONDARY = os.getenv("GEMINI_API_KEY_SECONDARY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_MODEL_SECONDARY = os.getenv("GEMINI_MODEL_SECONDARY", "")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-ai/deepseek-v4-flash-0731")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://integrate.api.nvidia.com/v1/chat/completions")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "groq/compound-mini")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")

AI_PROVIDER_AVAILABLE = bool(
    GEMINI_API_KEY
    or GROQ_API_KEY
    or DEEPSEEK_API_KEY
)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
YOUTUBE_REFRESH_TOKEN = os.getenv("YOUTUBE_REFRESH_TOKEN", "")
CLIENT_SECRETS_FILE = os.getenv("CLIENT_SECRETS_FILE", str(PROJECT_ROOT / "client_secret.json"))

# TTS Settings
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "kokoro")  # kokoro, edge, piper
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_bella")
KOKORO_MODEL_PATH = DATA_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = DATA_DIR / "voices-v1.0.bin"

# Image Generation Fallback Provider
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "pollinations")

# Publishing Frequency
SHORTS_PER_DAY = int(os.getenv("SHORTS_PER_DAY", "2"))
PUBLISH_TIME_SLOTS = ["14:00", "20:00"]

# Self-Improvement & Strategy Execution (Phase 4)
SELF_IMPROVEMENT_ENABLED = os.getenv("SELF_IMPROVEMENT_ENABLED", "false").lower() == "true"
STRATEGY_MODE = os.getenv("STRATEGY_MODE", "LEARNED").upper()  # LEARNED, EXPLORE, DEFAULT
EXPLORATION_RATE = float(os.getenv("EXPLORATION_RATE", "0.20"))

# Resilient Bounded Retries (Phase 5.2)
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", "3"))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", "1.0"))
RETRY_MAX_DELAY = float(os.getenv("RETRY_MAX_DELAY", "30.0"))

# Concurrency & Buffer Guardrails (Phase 5.3)
MAX_BATCH_PRODUCTION_CEILING = int(os.getenv("MAX_BATCH_PRODUCTION_CEILING", "8"))
MAX_PRODUCTION_ATTEMPTS_CEILING = int(os.getenv("MAX_PRODUCTION_ATTEMPTS_CEILING", "12"))
MAX_BUFFER_RESERVE_CEILING = int(os.getenv("MAX_BUFFER_RESERVE_CEILING", "24"))
LOCK_STALE_TIMEOUT_SEC = float(os.getenv("LOCK_STALE_TIMEOUT_SEC", "1800.0"))  # 30 minutes

# Cloud Mode & Remote GitHub Actions Dispatcher (Phase 7.2)
CLOUD_MODE = os.getenv("CLOUD_MODE", "true").lower() == "true"
GITHUB_PAT = os.getenv("GITHUB_PAT") or os.getenv("GITHUB_TOKEN") or ""
GITHUB_REPOSITORY_OWNER = os.getenv("GITHUB_REPOSITORY_OWNER") or "jishanh776600-svg"
GITHUB_REPOSITORY_NAME = os.getenv("GITHUB_REPOSITORY_NAME") or "yt-automation"
GITHUB_REF = os.getenv("GITHUB_REF", "main")

# Google Drive Cloud Storage Entitlement (Phase 11.2 - Confirmed 5 TB Storage Plan)
GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES = int(os.getenv("GOOGLE_DRIVE_TOTAL_CAPACITY_BYTES", str(5 * (1024 ** 4))))  # 5 TB = 5,497,558,138,880 bytes


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
