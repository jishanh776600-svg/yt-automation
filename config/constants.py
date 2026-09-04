"""
Constants for History Shorts Pipeline.
Defines pipeline state machine, video specs, historical niches, scoring weights, and licensing rules.
"""
from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Tuple, Optional


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
    RENDERED_QA_PASSED = "RENDERED_QA_PASSED"
    READY_TO_UPLOAD = "READY_TO_UPLOAD"
    UPLOADING = "UPLOADING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


PUBLISHING_SLOTS_UTC = [
    (6, 0, "06:00 UTC (11:30 AM IST)"),
    (11, 0, "11:00 UTC (04:30 PM IST)"),
    (15, 0, "15:00 UTC (08:30 PM IST)"),
]

# Canonical Business Timezone (Asia/Kolkata / IST = UTC+5:30)
BUSINESS_TIMEZONE = "Asia/Kolkata"
BUSINESS_TZ = timezone(timedelta(hours=5, minutes=30), name=BUSINESS_TIMEZONE)


def get_business_day_bounds_utc(reference_dt: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    """
    Computes the UTC start and end bounds corresponding to 00:00:00 and 24:00:00
    of the business calendar day in Asia/Kolkata (UTC+5:30).

    If reference_dt is None, uses current instant.
    Returns naive UTC datetimes (start_utc, end_utc) suitable for database comparison against UTC columns.
    """
    if reference_dt is None:
        ref_utc = datetime.now(timezone.utc)
    elif reference_dt.tzinfo is None:
        ref_utc = reference_dt.replace(tzinfo=timezone.utc)
    else:
        ref_utc = reference_dt.astimezone(timezone.utc)

    ref_ist = ref_utc.astimezone(BUSINESS_TZ)
    today_ist = ref_ist.date()

    start_ist = datetime(today_ist.year, today_ist.month, today_ist.day, 0, 0, 0, tzinfo=BUSINESS_TZ)
    end_ist = start_ist + timedelta(days=1)

    start_utc = start_ist.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_ist.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


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


class CurrentAffairsCategory(str, Enum):
    GEOPOLITICS = "Geopolitics"
    GLOBAL_CONFLICT = "Global Conflict"
    WORLD_POLITICS = "World Politics"
    US_POLITICS = "US Politics"
    EUROPE_POLITICS = "Europe Politics"
    GLOBAL_ECONOMY = "Global Economy"
    DIPLOMACY = "Diplomacy"
    SECURITY = "Security"
    MAJOR_WORLD_EVENT = "Major World Event"


class LicenseType(str, Enum):
    PEXELS_LICENSE = "Pexels License (Commercial $0)"
    PUBLIC_DOMAIN_CC0 = "Public Domain / CC0"
    YOUTUBE_AUDIO_LIBRARY = "YouTube Audio Library (Monetizable $0)"
    APACHE_2_0 = "Apache 2.0"
    MIT = "MIT"
    AI_GENERATED_OPEN = "AI Generated (Commercially Permitted)"
    UNKNOWN = "UNKNOWN"


class VisualSourceType(str, Enum):
    ARCHIVAL_PHOTO = "ARCHIVAL_PHOTO"
    ARCHIVAL_VIDEO = "ARCHIVAL_VIDEO"
    HISTORICAL_DOCUMENT = "HISTORICAL_DOCUMENT"
    HISTORICAL_MAP = "HISTORICAL_MAP"
    HISTORICAL_ILLUSTRATION = "HISTORICAL_ILLUSTRATION"
    HISTORICAL_PAINTING = "HISTORICAL_PAINTING"
    HISTORICAL_ENGRAVING = "HISTORICAL_ENGRAVING"
    HISTORICAL_ARTIFACT = "HISTORICAL_ARTIFACT"
    GENERATED_RECONSTRUCTION = "GENERATED_RECONSTRUCTION"
    MODERN_CONTEXTUAL_STOCK = "MODERN_CONTEXTUAL_STOCK"
    ABSTRACT_ATMOSPHERIC = "ABSTRACT_ATMOSPHERIC"
    UNKNOWN = "UNKNOWN"


class HistoricalEventRelation(str, Enum):
    DIRECT_EVENT_EVIDENCE = "DIRECT_EVENT_EVIDENCE"
    EVENT_RELATED_HISTORICAL_CONTEXT = "EVENT_RELATED_HISTORICAL_CONTEXT"
    ERA_CONTEXT = "ERA_CONTEXT"
    GENERIC_MODERN_CONTEXT = "GENERIC_MODERN_CONTEXT"
    UNKNOWN = "UNKNOWN"


class FailureType(str, Enum):
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    RESEARCH_FAILURE = "RESEARCH_FAILURE"
    FACT_VERIFICATION_FAILURE = "FACT_VERIFICATION_FAILURE"
    SCRIPT_FAILURE = "SCRIPT_FAILURE"
    TTS_FAILURE = "TTS_FAILURE"
    VISUAL_FAILURE = "VISUAL_FAILURE"
    AUDIO_FAILURE = "AUDIO_FAILURE"
    CAPTION_FAILURE = "CAPTION_FAILURE"
    RENDER_FAILURE = "RENDER_FAILURE"
    QA_FAILURE = "QA_FAILURE"
    DRIVE_FAILURE = "DRIVE_FAILURE"
    UPLOAD_FAILURE = "UPLOAD_FAILURE"
    YOUTUBE_FAILURE = "YOUTUBE_FAILURE"
    OAUTH_FAILURE = "OAUTH_FAILURE"
    QUOTA_FAILURE = "QUOTA_FAILURE"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"


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
TARGET_BGM_LUFS = -30.0  # Standardized Stage B BGM bed target loudness (16 dB below narration master)
BGM_MIX_VOLUME_DB = -13.0  # Fallback relative BGM mixing level
MUSIC_DUCK_DB = -24.0
SFX_LEVEL_DB = -18.0
BGM_FADE_IN_SEC = 0.8
BGM_FADE_OUT_SEC = 1.5

# Audio QA Thresholds
MIN_AUDIO_LOUDNESS_LUFS = -22.0
MAX_AUDIO_LOUDNESS_LUFS = -10.0
MAX_TRUE_PEAK_DBTP = -0.5
MIN_BGM_RMS_ENERGY = 0.005  # Ensures BGM is physically audible in final render

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
DAILY_SHORTS_LIMIT = 3
TARGET_RESERVE_BUFFER = 6

# Recovery & Self-Healing Thresholds (Phase 6)
MAX_JOB_RETRIES = 3
MAX_UPLOAD_RETRIES = 2
STALE_JOB_TIMEOUT_SEC = 3600       # 1 hour
STALE_PROCESSING_TIMEOUT_SEC = 7200 # 2 hours
BACKOFF_BASE_SECONDS = 2.0
RETRY_BACKOFF_FACTOR = 2.0
MAX_BACKOFF_SECONDS = 60.0
