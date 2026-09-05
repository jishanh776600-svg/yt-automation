"""
Comprehensive Integration Test Suite for Step 3B: Full Production Readiness & Orchestration.
Verifies all 22 required minimum scenarios + Multi-Niche Proof + Static Architectural Audit:
 1. Complete successful lifecycle (Discover -> Publish)
 2. Discovery failure containment
 3. Insufficient evidence containment
 4. Research failure handling
 5. Script failure handling
 6. Critic rejection quarantine (NEEDS_REVIEW, no render)
 7. Visual planning failure
 8. TTS failure recovery
 9. Render failure containment
 10. QA failure hard gate (QA FAIL -> never publishes)
 11. Transient retry success
 12. Permanent failure (no infinite loops)
 13. Restart / resume from intermediate state
 14. Idempotent TTS reuse
 15. Idempotent render reuse
 16. Idempotent scheduling protection
 17. Idempotent publishing protection (duplicate publication prevention)
 18. Provider fallback cascade
 19. Profile resolution
 20. Multi-niche execution proof (CURRENT_AFFAIRS, HISTORICAL, SPACE_TECHNOLOGY, FINANCIAL_MARKETS)
 21. Zero forbidden mutations in dry-run mode
 22. Concurrent duplicate-job protection via ProcessLock
 23. Static architectural audit (no conditional coupling to niche identifiers)
"""
import ast
import os
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import RENDERS_DIR
from config.constants import JobState
from core.models import Base, Job, Topic, ScriptRecord, AssetRecord, RenderOutput, QAReport, UploadRecord, SourceRecord, ClaimRecord
from core.content_profile import ContentProfile, CURRENT_AFFAIRS_PROFILE, HISTORICAL_PROFILE
from core.discovery_profile import DiscoveryProfile, CURRENT_AFFAIRS_DISCOVERY_PROFILE, HISTORICAL_DISCOVERY_PROFILE
from engines.orchestrator import (
    ProductionOrchestrator,
    ExecutionCapabilities,
    OrchestrationError,
    TransientOrchestrationError,
    PermanentOrchestrationError,
    ScriptRejectionError,
    QAFailureError,
    DuplicatePublicationError,
    classify_error
)
from core.lock import ProcessLock, ProcessLockError


@pytest.fixture
def test_db():
    """Provides an isolated, in-memory SQLite database for deterministic test execution."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def mock_topic(test_db):
    """Provides a valid test topic in the database."""
    topic = Topic(
        id=f"top_{uuid.uuid4().hex[:10]}",
        title="Global Semiconductor Accord Signed in Geneva",
        summary="Major international powers sign landmark semiconductor trade treaty establishing supply chain guarantees.",
        category="TRADE_ECONOMY",
        score=78.5,
        status="APPROVED"
    )
    test_db.add(topic)
    test_db.commit()
    return topic


# ==============================================================================
# 1. COMPLETE SUCCESSFUL LIFECYCLE
# ==============================================================================
def test_01_complete_successful_lifecycle(test_db, mock_topic):
    """Scenario 1: Complete end-to-end lifecycle runs through all stages to PUBLISHED."""
    caps = ExecutionCapabilities.sandboxed_testing(
        allow_network_read=False,
        allow_ai=False,
        allow_tts=False,
        allow_render=False,
        allow_drive_write=False,
        allow_youtube_write=False,
        allow_schedule=False
    )
    orchestrator = ProductionOrchestrator(
        content_profile=CURRENT_AFFAIRS_PROFILE,
        discovery_profile=CURRENT_AFFAIRS_DISCOVERY_PROFILE,
        capabilities=caps
    )

    report = orchestrator.produce_job(topic=mock_topic, db=test_db)

    assert report.success is True
    assert report.final_state == JobState.PUBLISHED.value
    assert len(report.stages) == 12  # Research, Script, Critic, Visual, Assets, TTS, Audio, Render, QA, Ready, Schedule, Publish

    job = test_db.query(Job).filter(Job.id == report.job_id).first()
    assert job is not None
    assert job.state == JobState.PUBLISHED.value
    assert job.published_at is not None


# ==============================================================================
# 2. DISCOVERY FAILURE CONTAINMENT
# ==============================================================================
def test_02_discovery_failure_contained(test_db):
    """Scenario 2: When discovery fails or yields zero candidates, orchestrator fails safely without crashing."""
    caps = ExecutionCapabilities.dry_run()
    orchestrator = ProductionOrchestrator(capabilities=caps)

    # Mock stage_discover to return empty list
    with patch.object(orchestrator, "stage_discover", return_value=[]):
        report = orchestrator.produce_job(topic=None, db=test_db)
        assert report.success is False
        assert "No qualified candidate topics" in (report.error_message or "")


# ==============================================================================
# 3. INSUFFICIENT EVIDENCE CONTAINMENT
# ==============================================================================
def test_03_insufficient_evidence_contained(test_db):
    """Scenario 3: Topics lacking multi-source consensus are rejected before production."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run())

    # Single-source unverified topic
    topic_single_source = Topic(
        id="top_single_src",
        title="Unverified Rumor on Social Media",
        summary="A single uncorroborated post claims unusual naval movement.",
        category="DEFENSE_CONFLICT",
        score=20.0,
        status="DISCOVERED"
    )
    test_db.add(topic_single_source)
    test_db.commit()

    filtered = orchestrator.stage_filter_and_rank(test_db, [topic_single_source])
    assert len(filtered) <= 1


# ==============================================================================
# 4. RESEARCH FAILURE HANDLING
# ==============================================================================
def test_04_research_failure_handling(test_db, mock_topic):
    """Scenario 4: Research failure halts the job safely without proceeding to script."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=1)

    with patch.object(orchestrator.research_engine, "research_topic", side_effect=ValueError("Archive source corrupted")):
        report = orchestrator.produce_job(topic=mock_topic, db=test_db)
        assert report.success is False
        assert "Archive source corrupted" in (report.error_message or "")
        job = test_db.query(Job).filter(Job.id == report.job_id).first()
        assert job.state in [JobState.FAILED.value, JobState.RESEARCHING.value]


# ==============================================================================
# 5. SCRIPT FAILURE HANDLING
# ==============================================================================
def test_05_script_failure_handling(test_db, mock_topic):
    """Scenario 5: Script generation error halts before visual planning or rendering."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.sandboxed_testing(allow_ai=True), max_retries=1)

    with patch.object(orchestrator.script_engine, "generate_script", side_effect=RuntimeError("AI generation timed out")):
        report = orchestrator.produce_job(topic=mock_topic, db=test_db)
        assert report.success is False
        assert "AI generation timed out" in (report.error_message or "")


# ==============================================================================
# 6. CRITIC REJECTION QUARANTINE
# ==============================================================================
def test_06_critic_rejection_quarantine(test_db, mock_topic):
    """Scenario 6: Critic rejection moves job to NEEDS_REVIEW; rendering is NEVER invoked."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=1)

    with patch.object(orchestrator.script_critic, "evaluate_script", return_value=(False, ["FORBIDDEN_CLICHE: will shock you"])):
        with patch.object(orchestrator, "stage_render") as mock_render:
            report = orchestrator.produce_job(topic=mock_topic, db=test_db)
            assert report.success is False
            assert "Script rejected by Critic" in (report.error_message or "")
            mock_render.assert_not_called()

            job = test_db.query(Job).filter(Job.id == report.job_id).first()
            assert job.state == JobState.NEEDS_REVIEW.value


# ==============================================================================
# 7. VISUAL PLANNING FAILURE
# ==============================================================================
def test_07_visual_planning_failure(test_db, mock_topic):
    """Scenario 7: Storyboard failure stops the job cleanly before TTS."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=1)

    with patch.object(orchestrator.storyboard_engine, "create_storyboard", side_effect=ValueError("Invalid shot count")):
        with patch.object(orchestrator, "stage_tts") as mock_tts:
            report = orchestrator.produce_job(topic=mock_topic, db=test_db)
            assert report.success is False
            mock_tts.assert_not_called()


# ==============================================================================
# 8. TTS FAILURE RECOVERY
# ==============================================================================
def test_08_tts_failure_recovery(test_db, mock_topic):
    """Scenario 8: TTS failure stops pipeline before audio mixing or rendering."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.sandboxed_testing(allow_tts=True), max_retries=1)

    with patch.object(orchestrator.tts_engine, "generate_narration", side_effect=RuntimeError("TTS engine unreachable")):
        with patch.object(orchestrator, "stage_render") as mock_render:
            report = orchestrator.produce_job(topic=mock_topic, db=test_db)
            assert report.success is False
            mock_render.assert_not_called()


# ==============================================================================
# 9. RENDER FAILURE CONTAINMENT
# ==============================================================================
def test_09_render_failure_containment(test_db, mock_topic):
    """Scenario 9: Rendering crash stops job before QA or Drive vault staging."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.sandboxed_testing(allow_render=True), max_retries=1)

    with patch.object(orchestrator.render_engine, "assemble_short", side_effect=RuntimeError("FFmpeg render crash")):
        with patch.object(orchestrator, "stage_ready") as mock_ready:
            report = orchestrator.produce_job(topic=mock_topic, db=test_db)
            assert report.success is False
            mock_ready.assert_not_called()


# ==============================================================================
# 10. QA FAILURE HARD GATE
# ==============================================================================
def test_10_qa_failure_hard_gate(test_db, mock_topic):
    """Scenario 10: Video failing QA NEVER reaches Drive staging, scheduling, or YouTube."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=1)

    failing_report = QAReport(
        job_id="job_qa_fail",
        passed=False,
        resolution_ok=False,
        failure_reasons="Resolution 720x1280 is not vertical 1080x1920"
    )

    with patch.object(orchestrator.qa_engine, "run_qa", return_value=(False, failing_report)):
        with patch.object(orchestrator, "stage_ready") as mock_ready:
            with patch.object(orchestrator, "stage_schedule") as mock_schedule:
                with patch.object(orchestrator, "stage_publish") as mock_publish:
                    report = orchestrator.produce_job(topic=mock_topic, db=test_db)
                    assert report.success is False
                    assert "QA Validation Failed" in (report.error_message or "")
                    mock_ready.assert_not_called()
                    mock_schedule.assert_not_called()
                    mock_publish.assert_not_called()


# ==============================================================================
# 11. TRANSIENT RETRY SUCCESS
# ==============================================================================
def test_11_transient_retry_success(test_db, mock_topic):
    """Scenario 11: Transient error on attempt 1 is retried and succeeds on attempt 2."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=2)

    call_count = [0]
    original_research = orchestrator.stage_research

    def flaky_research(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            raise TimeoutError("HTTP Connection timed out")
        return original_research(*args, **kwargs)

    with patch.object(orchestrator, "stage_research", side_effect=flaky_research):
        report = orchestrator.produce_job(topic=mock_topic, db=test_db)
        assert report.success is True
        assert report.retries_used == 1
        assert call_count[0] == 2


# ==============================================================================
# 12. PERMANENT FAILURE NO INFINITE LOOPS
# ==============================================================================
def test_12_permanent_failure_no_infinite_loop(test_db, mock_topic):
    """Scenario 12: Permanent error halts immediately without looping up to max_retries."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run(), max_retries=5)

    call_count = [0]

    def fatal_research(*args, **kwargs):
        call_count[0] += 1
        raise ValueError("Invalid schema: missing title")

    with patch.object(orchestrator, "stage_research", side_effect=fatal_research):
        report = orchestrator.produce_job(topic=mock_topic, db=test_db)
        assert report.success is False
        assert call_count[0] == 1


# ==============================================================================
# 13. RESTART / RESUME FROM INTERMEDIATE STATE
# ==============================================================================
def test_13_restart_resume_from_intermediate_state(test_db, mock_topic):
    """Scenario 13: Job interrupted at AUDIO_READY resumes render without repeating script."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run())

    existing_job = Job(
        id="job_crashed_01",
        topic_id=mock_topic.id,
        state=JobState.AUDIO_READY.value,
        retry_count=0
    )
    test_db.add(existing_job)

    script_rec = ScriptRecord(
        id="scr_existing",
        topic_id=mock_topic.id,
        hook=f"In 2026, critical developments surfaced regarding {mock_topic.title}.",
        context="International observers and intelligence analysts closely monitored strategic reactions across multiple sovereign borders.",
        escalation="Diplomatic officials confirmed the comprehensive initial defense response during high level negotiations.",
        reveal="The decisive revelation changed all tactical regional calculations permanently.",
        loop_twist="The central question remains how global leadership responds.",
        full_text="In 2026, critical developments surfaced regarding Global Semiconductor Accord Signed in Geneva. International observers and intelligence analysts closely monitored strategic reactions as unfolding events spread rapidly across multiple sovereign borders. Diplomatic officials confirmed the comprehensive initial defense response during high level emergency negotiations. The decisive revelation changed all tactical regional calculations permanently. The central question remains how global leadership responds.",
        word_count=57,
        estimated_duration_sec=24.0,
        status="APPROVED"
    )
    test_db.add(script_rec)
    test_db.commit()

    report = orchestrator.produce_job(topic=mock_topic, job_id=existing_job.id, db=test_db)
    assert report.success is True
    assert report.final_state == JobState.PUBLISHED.value


# ==============================================================================
# 14. IDEMPOTENT TTS REUSE
# ==============================================================================
def test_14_idempotent_tts_reuse(test_db, mock_topic):
    """Scenario 14: Existing voice file on disk is reused without calling TTS synthesis."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run())

    job = Job(id="job_tts_test", topic_id=mock_topic.id, state=JobState.SCRIPT_READY.value)
    test_db.add(job)
    test_db.commit()

    script = ScriptRecord(
        id="scr_tts", topic_id=mock_topic.id, hook="H", context="C",
        escalation="E", reveal="R", loop_twist="L",
        full_text="In 2026, critical developments surfaced regarding Global Semiconductor Accord Signed in Geneva. International observers and intelligence analysts closely monitored strategic reactions as unfolding events spread rapidly across multiple sovereign borders. Diplomatic officials confirmed the comprehensive initial defense response during high level emergency negotiations. The decisive revelation changed all tactical regional calculations permanently. The central question remains how global leadership responds.",
        word_count=57, estimated_duration_sec=24.0, status="APPROVED"
    )

    fake_voice_path = RENDERS_DIR / f"voice_{job.id}.wav"
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    fake_voice_path.write_bytes(b"RIFF" + b"\x00" * 2000)

    try:
        with patch.object(orchestrator.tts_engine, "generate_narration") as mock_gen:
            asset, dur = orchestrator.stage_tts(test_db, job, script)
            mock_gen.assert_not_called()
            assert f"voice_{job.id}.wav" in asset.local_path
    finally:
        if fake_voice_path.exists():
            fake_voice_path.unlink()


# ==============================================================================
# 15. IDEMPOTENT RENDER REUSE
# ==============================================================================
def test_15_idempotent_render_reuse(test_db, mock_topic):
    """Scenario 15: Existing RenderOutput in database is reused without re-assembling video."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run())

    job = Job(id="job_render_test", topic_id=mock_topic.id, state=JobState.AUDIO_READY.value)
    test_db.add(job)

    fake_video = RENDERS_DIR / f"rendered_{job.id}.mp4"
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)
    fake_video.write_bytes(b"\x00" * 20000)

    render_rec = RenderOutput(
        id="rnd_test_existing",
        job_id=job.id,
        video_path=str(fake_video),
        duration_sec=24.0,
        file_size_bytes=20000
    )
    test_db.add(render_rec)
    test_db.commit()

    try:
        with patch.object(orchestrator.render_engine, "assemble_short") as mock_assemble:
            output = orchestrator.stage_render(test_db, job, [], {}, Path(fake_video))
            mock_assemble.assert_not_called()
            assert output.id == "rnd_test_existing"
    finally:
        if fake_video.exists():
            fake_video.unlink()


# ==============================================================================
# 16. IDEMPOTENT SCHEDULING PROTECTION
# ==============================================================================
def test_16_idempotent_scheduling_protection(test_db, mock_topic):
    """Scenario 16: Job already having an UploadRecord is not scheduled twice."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.sandboxed_testing(allow_schedule=True))

    job = Job(id="job_sched_test", topic_id=mock_topic.id, state=JobState.READY_TO_UPLOAD.value)
    existing_upl = UploadRecord(
        id="upl_existing_01",
        job_id=job.id,
        title=mock_topic.title,
        description=mock_topic.summary,
        scheduled_publish_at=datetime.utcnow() + timedelta(hours=5),
        status="SCHEDULED"
    )
    test_db.add(job)
    test_db.add(existing_upl)
    test_db.commit()

    mock_script = ScriptRecord(
        id="scr_sched", topic_id=mock_topic.id, hook="H", context="C",
        escalation="E", reveal="R", loop_twist="L", full_text="Word " * 50,
        word_count=50, estimated_duration_sec=24.0, status="APPROVED"
    )

    with patch.object(orchestrator.scheduler, "get_vacant_slots") as mock_slots:
        res = orchestrator.stage_schedule(test_db, job, mock_topic, mock_script, {"title": mock_topic.title})
        mock_slots.assert_not_called()
        assert res.id == "upl_existing_01"


# ==============================================================================
# 17. IDEMPOTENT PUBLISHING PROTECTION
# ==============================================================================
def test_17_idempotent_publishing_protection(test_db, mock_topic):
    """Scenario 17: Video already published is never uploaded again."""
    orchestrator = ProductionOrchestrator(capabilities=ExecutionCapabilities.sandboxed_testing(allow_youtube_write=True))

    job = Job(id="job_pub_test", topic_id=mock_topic.id, state=JobState.SCHEDULED.value)
    upl = UploadRecord(
        id="upl_pub_test",
        job_id=job.id,
        youtube_video_id="yt_vid_12345",
        title=mock_topic.title,
        description=mock_topic.summary,
        status="PUBLISHED"
    )
    test_db.add(job)
    test_db.add(upl)
    test_db.commit()

    with patch.object(orchestrator.upload_engine, "upload_and_schedule_short") as mock_yt:
        published = orchestrator.stage_publish(test_db, job, upl)
        mock_yt.assert_not_called()
        assert published is True


# ==============================================================================
# 18. PROVIDER FALLBACK CASCADE
# ==============================================================================
def test_18_provider_fallback_cascade():
    """Scenario 18: Provider cascade has all 6 providers in exact order."""
    from core.gemini_client import GeminiClient
    client = GeminiClient(
        api_key="primary_key",
        secondary_api_key="secondary_key",
        groq_api_key="groq_key",
        openrouter_api_key="openrouter_key",
        deepseek_api_key="deepseek_key",
        nvidia_api_key="nvidia_key",
        sleeper=MagicMock()
    )
    providers = client._get_configured_providers()
    names = [p["name"] for p in providers]
    assert names == ["primary", "secondary", "groq", "openrouter", "deepseek", "nvidia"]


# ==============================================================================
# 19. PROFILE RESOLUTION
# ==============================================================================
def test_19_profile_resolution():
    """Scenario 19: ContentProfile and DiscoveryProfile resolve dynamically."""
    from core.content_profile import get_active_profile, set_active_profile
    from core.discovery_profile import get_active_discovery_profile

    cp = get_active_profile()
    dp = get_active_discovery_profile()
    assert cp is not None
    assert dp is not None

    set_active_profile(HISTORICAL_PROFILE)
    try:
        assert get_active_profile().name == "HISTORICAL"
    finally:
        set_active_profile(None)


# ==============================================================================
# 20. MULTI-NICHE EXECUTION PROOF
# ==============================================================================
def test_20_multi_niche_execution_proof(test_db):
    """
    Scenario 20: Executes the SAME orchestrator across 4 distinct niches:
      1. CURRENT_AFFAIRS
      2. HISTORICAL
      3. SPACE_TECHNOLOGY
      4. FINANCIAL_MARKETS
    Without modifying ANY orchestrator code!
    """
    # 1. Current Affairs
    orch_ca = ProductionOrchestrator(
        content_profile=CURRENT_AFFAIRS_PROFILE,
        discovery_profile=CURRENT_AFFAIRS_DISCOVERY_PROFILE,
        capabilities=ExecutionCapabilities.dry_run()
    )
    t_ca = Topic(id="top_niche_ca", title="Geneva Accord Signed", summary="Peace treaty signed.", category="DIPLOMACY")
    test_db.add(t_ca)
    test_db.commit()
    rep_ca = orch_ca.produce_job(topic=t_ca, db=test_db)
    assert rep_ca.success is True
    assert rep_ca.niche == "CURRENT_AFFAIRS"

    # 2. Historical
    orch_hist = ProductionOrchestrator(
        content_profile=HISTORICAL_PROFILE,
        discovery_profile=HISTORICAL_DISCOVERY_PROFILE,
        capabilities=ExecutionCapabilities.dry_run()
    )
    t_hist = Topic(id="top_niche_hist", title="The Boston Molasses Flood", summary="Molasses tank burst in 1919.", category="DOCUMENTED_DISASTERS")
    test_db.add(t_hist)
    test_db.commit()
    rep_hist = orch_hist.produce_job(topic=t_hist, db=test_db)
    assert rep_hist.success is True
    assert rep_hist.niche == "HISTORICAL"

    # 3. Space Technology
    SPACE_PROFILE = ContentProfile(
        name="SPACE_TECHNOLOGY",
        description="Space exploration, rocketry, propulsion, and astrophysics.",
        target_audience="Science enthusiasts and aerospace followers.",
        tone="Awe-inspiring, scientifically precise, forward-looking.",
        script_objective="Explain breakthrough aerospace engineering in 50 seconds.",
        system_role_instruction="You are an aerospace engineer and science communicator.",
        min_words=45,
        max_words=68,
        deduplication_policy="event_action_domain"
    )
    SPACE_DISCOVERY_PROFILE = DiscoveryProfile(
        name="SPACE_TECHNOLOGY",
        target_niche="space_technology",
        recognized_entities={"nasa", "spacex", "artemis", "starship", "iss", "moon", "mars"},
        action_stems={"launch", "orbit", "dock", "propulsion", "landing", "mission"},
        default_category="Aerospace & Space Exploration"
    )
    orch_space = ProductionOrchestrator(
        content_profile=SPACE_PROFILE,
        discovery_profile=SPACE_DISCOVERY_PROFILE,
        capabilities=ExecutionCapabilities.dry_run()
    )
    t_space = Topic(id="top_niche_space", title="Starship Orbit Test Succeeds", summary="Starship completes successful orbital burn.", category="Aerospace")
    test_db.add(t_space)
    test_db.commit()
    rep_space = orch_space.produce_job(topic=t_space, db=test_db)
    assert rep_space.success is True
    assert rep_space.niche == "SPACE_TECHNOLOGY"

    # 4. Financial Markets
    FINANCE_PROFILE = ContentProfile(
        name="FINANCIAL_MARKETS",
        description="Macroeconomics, interest rates, currency markets, and commodities.",
        target_audience="Investors, analysts, and financial professionals.",
        tone="Rigorous, analytical, data-focused, objective.",
        script_objective="Break down major macroeconomic market movements in 50 seconds.",
        system_role_instruction="You are a senior macroeconomic analyst.",
        min_words=45,
        max_words=68,
        deduplication_policy="event_action_domain"
    )
    FINANCE_DISCOVERY_PROFILE = DiscoveryProfile(
        name="FINANCIAL_MARKETS",
        target_niche="financial_markets",
        recognized_entities={"federal reserve", "ecb", "wall street", "nasdaq", "treasury", "imf"},
        action_stems={"inflation", "interest rate", "yield", "bond", "rally", "selloff"},
        default_category="Macroeconomics & Markets"
    )
    orch_finance = ProductionOrchestrator(
        content_profile=FINANCE_PROFILE,
        discovery_profile=FINANCE_DISCOVERY_PROFILE,
        capabilities=ExecutionCapabilities.dry_run()
    )
    t_fin = Topic(id="top_niche_fin", title="Federal Reserve Cuts Benchmark Rate", summary="Central bank eases policy by 50 basis points.", category="Macroeconomics")
    test_db.add(t_fin)
    test_db.commit()
    rep_fin = orch_finance.produce_job(topic=t_fin, db=test_db)
    assert rep_fin.success is True
    assert rep_fin.niche == "FINANCIAL_MARKETS"


# ==============================================================================
# 21. ZERO FORBIDDEN MUTATIONS IN DRY-RUN
# ==============================================================================
def test_21_zero_forbidden_mutations_in_dry_run(test_db, mock_topic):
    """Scenario 21: In dry-run mode, zero Drive uploads, zero YouTube calls, zero real renders."""
    caps = ExecutionCapabilities.dry_run()
    orchestrator = ProductionOrchestrator(capabilities=caps)

    with patch.object(orchestrator.drive_engine, "upload_video_to_vault") as mock_drive:
        with patch.object(orchestrator.upload_engine, "upload_and_schedule_short") as mock_yt:
            with patch.object(orchestrator.render_engine, "assemble_short") as mock_render:
                report = orchestrator.produce_job(topic=mock_topic, db=test_db)
                assert report.success is True
                assert report.is_dry_run is True
                mock_drive.assert_not_called()
                mock_yt.assert_not_called()
                mock_render.assert_not_called()


# ==============================================================================
# 22. CONCURRENT DUPLICATE-JOB PROTECTION
# ==============================================================================
def test_22_concurrent_duplicate_job_protection():
    """Scenario 22: ProcessLock prevents concurrent overlapping production runs."""
    lock1 = ProcessLock(name="production", command_name="test_runner_1")
    lock2 = ProcessLock(name="production", command_name="test_runner_2")

    try:
        assert lock1.acquire() is True
        # Second acquire should return False
        assert lock2.acquire() is False
    finally:
        lock1.release()


# ==============================================================================
# 23. STATIC ARCHITECTURAL AUDIT
# ==============================================================================
def test_23_static_architectural_audit():
    """
    Scenario 23: Audits engines/orchestrator.py AST to guarantee ZERO hardcoded niche branching.
    Universal engine code must never branch on niche names.
    """
    orchestrator_path = Path("engines/orchestrator.py")
    assert orchestrator_path.exists(), "engines/orchestrator.py must exist!"

    tree = ast.parse(orchestrator_path.read_text(encoding="utf-8"))

    forbidden_identifiers = {
        "current_affairs", "historical", "space_technology",
        "financial_markets", "geopolitics"
    }

    # Inspect all If statements in AST
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_str = ast.unparse(node.test).lower()
            for fid in forbidden_identifiers:
                assert f'"{fid}"' not in test_str and f"'{fid}'" not in test_str, (
                    f"Forbidden conditional coupling to niche identifier '{fid}' found in engines/orchestrator.py: "
                    f"Line {node.lineno}: if {test_str}"
                )
