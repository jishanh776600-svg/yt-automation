"""
Database Models for SQLite relational schema.
"""
from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, relationship
from config.constants import JobState, HistoricalCategory, LicenseType

Base = declarative_base()


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String(64), primary_key=True)
    topic_id = Column(String(64), ForeignKey("topics.id"), nullable=True)
    state = Column(String(32), default=JobState.QUEUED.value, nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    estimated_cost = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

    topic = relationship("Topic", back_populates="jobs")
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")
    renders = relationship("RenderOutput", back_populates="job", cascade="all, delete-orphan")
    qa_reports = relationship("QAReport", back_populates="job", cascade="all, delete-orphan")


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), ForeignKey("jobs.id"), nullable=False, index=True)
    stage = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False)
    message = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="logs")


class Topic(Base):
    __tablename__ = "topics"

    id = Column(String(64), primary_key=True)
    title = Column(String(255), nullable=False)
    summary = Column(Text, nullable=False)
    category = Column(String(64), default=HistoricalCategory.AMERICAN_HISTORY.value, nullable=False)
    score = Column(Float, default=0.0)
    status = Column(String(32), default="DISCOVERED")
    created_at = Column(DateTime, default=datetime.utcnow)

    jobs = relationship("Job", back_populates="topic")
    sources = relationship("SourceRecord", back_populates="topic", cascade="all, delete-orphan")
    claims = relationship("ClaimRecord", back_populates="topic", cascade="all, delete-orphan")
    scripts = relationship("ScriptRecord", back_populates="topic", cascade="all, delete-orphan")


class SourceRecord(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(String(64), ForeignKey("topics.id"), nullable=False)
    source_name = Column(String(255), nullable=False)
    source_url = Column(Text, nullable=True)
    source_type = Column(String(64), default="primary")
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("Topic", back_populates="sources")


class ClaimRecord(Base):
    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    topic_id = Column(String(64), ForeignKey("topics.id"), nullable=False)
    claim_text = Column(Text, nullable=False)
    verification_status = Column(String(32), default="VERIFIED")
    supporting_sources = Column(Text, nullable=True)
    confidence = Column(Float, default=1.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("Topic", back_populates="claims")


class ScriptRecord(Base):
    __tablename__ = "scripts"

    id = Column(String(64), primary_key=True)
    topic_id = Column(String(64), ForeignKey("topics.id"), nullable=False)
    hook = Column(Text, nullable=False)
    context = Column(Text, nullable=False)
    escalation = Column(Text, nullable=False)
    reveal = Column(Text, nullable=False)
    loop_twist = Column(Text, nullable=False)
    full_text = Column(Text, nullable=False)
    word_count = Column(Integer, nullable=False)
    estimated_duration_sec = Column(Float, nullable=False)
    hook_archetype = Column(String(64), nullable=True)  # DATE_TIME_ANCHOR, CONTRADICTION_SHOCK, HYPOTHETICAL_CURIOSITY, IN_MEDIAS_RES, UNSOLVED_MYSTERY, OTHER
    duration_target = Column(String(64), nullable=True)  # ULTRA_TIGHT, SWEET_SPOT, NARRATIVE_RICH
    status = Column(String(32), default="APPROVED")
    created_at = Column(DateTime, default=datetime.utcnow)

    topic = relationship("Topic", back_populates="scripts")


class AssetRecord(Base):
    __tablename__ = "assets"

    id = Column(String(64), primary_key=True)
    asset_type = Column(String(32), nullable=False)  # video, image, music, sfx, font
    source = Column(String(64), nullable=False)      # pexels, pollinations, yt_library, cc0, local
    source_url = Column(Text, nullable=True)
    license = Column(String(128), default=LicenseType.UNKNOWN.value, nullable=False)
    license_url = Column(Text, nullable=True)
    commercial_use = Column(Boolean, default=False, nullable=False)
    attribution_required = Column(Boolean, default=False)
    attribution_text = Column(Text, nullable=True)
    local_path = Column(Text, nullable=False)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    duration_sec = Column(Float, nullable=True)
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class RenderOutput(Base):
    __tablename__ = "renders"

    id = Column(String(64), primary_key=True)
    job_id = Column(String(64), ForeignKey("jobs.id"), nullable=False)
    video_path = Column(Text, nullable=False)
    width = Column(Integer, default=1080)
    height = Column(Integer, default=1920)
    fps = Column(Float, default=30.0)
    duration_sec = Column(Float, nullable=False)
    video_codec = Column(String(32), default="h264")
    audio_codec = Column(String(32), default="aac")
    file_size_bytes = Column(Integer, nullable=False)
    bgm_mood = Column(String(128), nullable=True)
    motion_style = Column(String(64), nullable=True)  # DYNAMIC_ZOOM_PAN, KEN_BURNS_STANDARD, STATIC
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="renders")


class QAReport(Base):
    __tablename__ = "qa_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), ForeignKey("jobs.id"), nullable=False)
    passed = Column(Boolean, default=False)
    resolution_ok = Column(Boolean, default=False)
    duration_ok = Column(Boolean, default=False)
    audio_ok = Column(Boolean, default=False)
    captions_ok = Column(Boolean, default=False)
    license_ok = Column(Boolean, default=False)
    policy_ok = Column(Boolean, default=False)
    failure_reasons = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job", back_populates="qa_reports")


class UploadRecord(Base):
    __tablename__ = "uploads"

    id = Column(String(64), primary_key=True)
    job_id = Column(String(64), nullable=False, index=True)
    youtube_video_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    description = Column(Text, nullable=False)
    tags = Column(Text, nullable=True)
    privacy_status = Column(String(32), default="private")
    scheduled_publish_at = Column(DateTime, nullable=True)
    published_at = Column(DateTime, nullable=True)
    status = Column(String(32), default="SUCCESS")  # SCHEDULED, PUBLISHED, FAILED, TEST_VERIFIED
    reconciliation_metadata = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    snapshots = relationship("PerformanceSnapshot", back_populates="upload", cascade="all, delete-orphan")


class PerformanceSnapshot(Base):
    """Immutable time-series performance metrics for a published video."""
    __tablename__ = "performance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    upload_id = Column(String(64), ForeignKey("uploads.id"), nullable=False, index=True)
    youtube_video_id = Column(String(64), nullable=True, index=True)
    snapshot_time = Column(DateTime, default=datetime.utcnow, nullable=False)
    hours_since_upload = Column(Float, default=0.0)

    # Core metrics
    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    subscribers_gained = Column(Integer, default=0)
    subscribers_lost = Column(Integer, default=0)

    # Retention & watch depth
    average_view_duration_sec = Column(Float, default=0.0)
    average_view_percentage = Column(Float, default=0.0)
    estimated_minutes_watched = Column(Float, default=0.0)
    engagement_rate = Column(Float, default=0.0)

    # Traffic sources & extra metrics (JSON)
    traffic_sources_json = Column(Text, nullable=True)
    raw_analytics_json = Column(Text, nullable=True)
    validation_status = Column(String(32), default="VALID_REAL", nullable=True)  # VALID_REAL, UNVERIFIED, STALE, DUPLICATE, MOCK, TEST, ORPHANED, UNAVAILABLE

    upload = relationship("UploadRecord", back_populates="snapshots")


class VideoAnalysisRecord(Base):
    """Statistical classification and structured Fact vs Hypothesis breakdown."""
    __tablename__ = "video_analyses"

    id = Column(String(64), primary_key=True)
    upload_id = Column(String(64), nullable=False, index=True)
    youtube_video_id = Column(String(64), nullable=True)
    analyzed_at = Column(DateTime, default=datetime.utcnow)

    # Classification: OUTPERFORMER, AVERAGE, UNDERPERFORMER, INSUFFICIENT_DATA
    classification = Column(String(32), nullable=False, index=True)
    
    # Baselines compared against
    channel_median_views = Column(Float, default=0.0)
    channel_median_apv = Column(Float, default=0.0)
    category_median_apv = Column(Float, default=0.0)

    # Structured Reason Engine (Facts vs Hypotheses)
    facts_observed = Column(Text, nullable=False)        # JSON list
    hypotheses = Column(Text, nullable=False)            # JSON list
    evidence = Column(Text, nullable=False)              # JSON list
    uncertainties = Column(Text, nullable=False)         # JSON list
    recommended_test = Column(Text, nullable=True)

    # Multi-dimensional score
    performance_score = Column(Float, default=50.0)


class ContentPattern(Base):
    """Persistent learning database tracking what works across formats, hooks, topics."""
    __tablename__ = "content_patterns"

    id = Column(String(64), primary_key=True)
    pattern_type = Column(String(64), nullable=False, index=True)  # hook_archetype, category, duration_bracket, visual_style, cta_style, posting_window
    pattern_key = Column(String(128), nullable=False, index=True)  # e.g., 'Contradiction', '21-23s', 'Documented Disasters'
    description = Column(Text, nullable=True)

    # Evidence & sample tracking
    sample_size = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    underperform_count = Column(Integer, default=0)

    # Performance metrics
    avg_percentage_viewed = Column(Float, default=0.0)
    avg_engagement_rate = Column(Float, default=0.0)
    avg_subscriber_conversion = Column(Float, default=0.0)
    composite_effectiveness_score = Column(Float, default=50.0)

    # Confidence: LOW_CONFIDENCE (N=1), MEDIUM_CONFIDENCE (N=2-4), HIGH_CONFIDENCE (N>=5)
    confidence = Column(String(32), default="LOW_CONFIDENCE")
    status = Column(String(32), default="ACTIVE")  # ACTIVE, RETIRED, PROVEN, FAILED
    last_updated = Column(DateTime, default=datetime.utcnow)


class ExperimentRecord(Base):
    """Tracks controlled strategy assignments, experiments, and resulting learnings."""
    __tablename__ = "experiments"

    id = Column(String(64), primary_key=True)
    experiment_type = Column(String(64), nullable=True)  # STRATEGY_ASSIGNMENT, EXPERIMENT_A, etc.
    experiment_group_id = Column(String(64), nullable=True, index=True)
    title = Column(String(255), nullable=True)
    hypothesis = Column(Text, nullable=True)
    
    # Controlled & test variables
    control_variable = Column(String(128), nullable=True)
    test_variable = Column(String(128), nullable=True)
    control_job_id = Column(String(64), nullable=True)
    test_job_id = Column(String(64), nullable=True)

    # Phase 4 Strategy Assignment Fields
    job_id = Column(String(64), nullable=True, index=True)
    topic_id = Column(String(64), nullable=True, index=True)
    hook_archetype = Column(String(64), nullable=True)
    duration_target = Column(String(64), nullable=True)
    bgm_mood = Column(String(128), nullable=True)
    motion_style = Column(String(64), nullable=True)
    category = Column(String(64), nullable=True)
    selection_mode = Column(String(32), default="EXPLOITATION")  # EXPLOITATION, EXPLORATION, MANUAL_OVERRIDE, DEFAULT
    strategy_reason = Column(Text, nullable=True)
    combination_type = Column(String(32), default="KNOWN")  # KNOWN, PARTIALLY_KNOWN, UNSEEN

    # Lifecycle State
    status = Column(String(32), default="PLANNED")  # PLANNED, SELECTED, PRODUCED, READY, UPLOADED, MEASURED, FAILED, CANCELLED
    failure_reason = Column(Text, nullable=True)
    
    # Upload & Metric Linking
    upload_id = Column(String(64), nullable=True, index=True)
    youtube_video_id = Column(String(64), nullable=True, index=True)
    outcome_snapshot_id = Column(Integer, nullable=True)
    outcome_summary = Column(Text, nullable=True)
    measured_delta_apv = Column(Float, nullable=True)
    confidence = Column(String(32), default="LOW_CONFIDENCE")
    created_at = Column(DateTime, default=datetime.utcnow)
    concluded_at = Column(DateTime, nullable=True)


class ProviderUsage(Base):
    __tablename__ = "provider_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_name = Column(String(64), nullable=False, index=True)
    units_used = Column(Integer, default=1)
    model_name = Column(String(64), nullable=True)
    endpoint = Column(String(128), nullable=True)
    status_code = Column(Integer, nullable=True)
    rate_limit = Column(Integer, nullable=True)
    rate_remaining = Column(Integer, nullable=True)
    rate_reset = Column(Integer, nullable=True)
    is_observed = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class StrategyWeight(Base):
    """Stores persistent, deterministic strategy weights for content generation."""
    __tablename__ = "strategy_weights"

    id = Column(String(64), primary_key=True)
    feature_type = Column(String(64), nullable=False, index=True)  # hook_archetype, duration_target, bgm_mood, motion_style, category
    feature_value = Column(String(128), nullable=False, index=True)
    weight = Column(Float, default=1.0, nullable=False)  # Bounded [0.20, 2.00]
    sample_count = Column(Integer, default=0, nullable=False)
    performance_mean = Column(Float, default=50.0, nullable=False)
    baseline_performance = Column(Float, default=50.0, nullable=False)
    relative_lift = Column(Float, default=0.0, nullable=False)  # Percentage lift vs baseline (e.g. +15.2%)
    confidence_level = Column(String(32), default="INSUFFICIENT_EVIDENCE", nullable=False)  # INSUFFICIENT_EVIDENCE (<3), WEAK_EVIDENCE (3-4), USABLE_EVIDENCE (>=5)
    last_updated = Column(DateTime, default=datetime.utcnow)
    update_reason = Column(Text, nullable=True)


class SystemConfig(Base):
    """Stores persistent key-value configuration for pipeline operations (e.g. active voice)."""
    __tablename__ = "system_config"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LearningEvent(Base):
    """
    Immutable audit trail for closed-loop self-improvement decisions and strategy weight updates.
    Records exact mathematical deltas, evidence sample sizes, baseline comparisons,
    and tracks whether future generation has consumed the updated production profile.
    """
    __tablename__ = "learning_events"

    id = Column(String(64), primary_key=True)
    cycle_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Outcome: LEARNING_APPLIED, NO_CHANGE_INSUFFICIENT_EVIDENCE, NO_CHANGE_NO_SIGNIFICANT_SIGNAL, NO_CHANGE_MISSING_TELEMETRY
    outcome = Column(String(64), nullable=False, index=True)

    # Feature attribution
    feature_type = Column(String(64), nullable=True, index=True)  # hook_archetype, duration_target, category, etc.
    feature_value = Column(String(128), nullable=True)

    # Evidence & Maturation
    sample_size = Column(Integer, default=0, nullable=False)
    matured_count = Column(Integer, default=0, nullable=False)
    immature_count = Column(Integer, default=0, nullable=False)

    # Metrics & Signals
    signal_metric = Column(String(64), default="COMPOSITE_RETENTION_APV", nullable=False)
    baseline_metric = Column(Float, nullable=True)
    observed_metric = Column(Float, nullable=True)
    delta = Column(Float, nullable=True)

    # Confidence & Bounded Weights
    confidence = Column(String(32), default="INSUFFICIENT_EVIDENCE", nullable=False)  # INSUFFICIENT_EVIDENCE, WEAK_EVIDENCE, USABLE_EVIDENCE
    old_weight = Column(Float, default=1.00, nullable=False)
    new_weight = Column(Float, default=1.00, nullable=False)

    # Explainability & Traceability
    reason = Column(Text, nullable=False)
    profile_version = Column(String(64), nullable=True)

    # Future generation consumption confirmation
    consumed_by_generation = Column(Boolean, default=False, nullable=False)
    consumed_by_job_id = Column(String(64), nullable=True, index=True)
    details_json = Column(Text, nullable=True)

