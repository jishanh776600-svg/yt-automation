"""
Constants for History Shorts Pipeline.
Defines pipeline state machine, video specs, historical niches, scoring weights, and licensing rules.
"""
from enum import Enum


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RESEARCHING = "RESEARCHING"
    RESEARCHED = "RESEARCHED"
    FACT_CHECKING = "FACT_CHECKING"
    FACT_CHECKED = "FACT_CHECKED"
    SCRIPTING = "SCRIPTING"
    SCRIPT_READY = "SCRIPT_READY"
    VISUAL_PLANNING = "VISUAL_PLANNING"
    VISUALS_SEARCHING = "VISUALS_SEARCHING"
    VISUALS_READY = "VISUALS_READY"
    VOICE_GENERATING = "VOICE_GENERATING"
    VOICE_READY = "VOICE_READY"
    AUDIO_READY = "AUDIO_READY"
    EDITING = "EDITING"
    QA = "QA"
    READY_TO_UPLOAD = "READY_TO_UPLOAD"
    UPLOADING = "UPLOADING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class HistoricalCategory(str, Enum):
    AMERICAN_HISTORY = "American History"
    EUROPEAN_HISTORY = "European History"
    STRANGE_LAWS = "Strange Historical Laws"
    UNUSUAL_WARS = "Unusual Wars"
    HISTORICAL_MYSTERIES = "Historical Mysteries"
    STRANGE_INVENTIONS = "Strange Inventions"
    LOST_PLACES = "Lost Places"
    UNUSUAL_BORDERS = "Unusual Borders"
    HISTORICAL_COINCIDENCES = "Unexpected Coincidences"
    DOCUMENTED_DISASTERS = "Documented Disasters"
    FORGOTTEN_FIGURES = "Forgotten Figures"


class LicenseType(str, Enum):
    PEXELS_LICENSE = "Pexels License (Commercial $0)"
    PUBLIC_DOMAIN_CC0 = "Public Domain / CC0"
    YOUTUBE_AUDIO_LIBRARY = "YouTube Audio Library (Monetizable $0)"
    APACHE_2_0 = "Apache 2.0"
    MIT = "MIT"
    AI_GENERATED_OPEN = "AI Generated (Commercially Permitted)"
    UNKNOWN = "UNKNOWN"


# Video Specifications (Strict YouTube Shorts vertical 9:16)
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
VIDEO_FPS = 30
VIDEO_ASPECT_RATIO = "9:16"

# Duration targets (Seconds)
MIN_DURATION_SEC = 21.0
MAX_DURATION_SEC = 25.0
TARGET_DURATION_SEC = 23.0

# Audio Standards
AUDIO_SAMPLE_RATE = 44100
TARGET_LUFS = -14.0
MUSIC_DUCK_DB = -24.0
SFX_LEVEL_DB = -18.0

# Script Constraints
MIN_WORD_COUNT = 45
MAX_WORD_COUNT = 65
OPTIMAL_WORD_COUNT = 55

# API Free Limits (Default Safety Buffers)
PEXELS_FREE_LIMIT_HOURLY = 200
PEXELS_FREE_LIMIT_MONTHLY = 20000
GEMINI_FREE_RPM = 15
YOUTUBE_DAILY_QUOTA_LIMIT = 10000
YOUTUBE_UPLOAD_COST = 1600
