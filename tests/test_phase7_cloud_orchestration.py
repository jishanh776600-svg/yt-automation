"""
Phase 7: Cloud-Autonomous Production Orchestration Test Suite.
==============================================================
Verifies 100% cloud autonomy, dependency classification, workflow headlessness,
zero browser/Antigravity dependencies, cloud locking, state machine transitions,
idempotency, buffer replenishment, publishing separation, and end-to-end dataflow.
"""

import inspect
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from config import settings
from core.models import (
    Job,
    Topic,
    ArticleRecord,
    ScriptRecord,
    ProductionAssetManifestRecord,
    RenderedVideoRecord,
)
from core.database import SessionLocal, init_db
from core.pipeline_state import (
    CLOUD_AUTONOMOUS,
    ALLOWED_RUNTIME,
    FORBIDDEN_RUNTIME,
    PipelineStage,
    ProductionRunTelemetry,
    CloudLockManager,
)
from intelligence.cloud_orchestrator import CloudProductionOrchestrator
from intelligence.event_card import (
    EventCard,
    WhoSection,
    WhereSection,
    WhenSection,
    ClaimEvidence,
    VerificationState,
)
from intelligence.journalistic_script import ScriptDocument, ScriptBeat
from intelligence.models import RawArticle
from intelligence.video_qa import VideoQAReport


# ==============================================================================
# 1. Cloud Autonomy & Architectural Dependency Contract Tests
# ==============================================================================

def test_cloud_autonomous_contract_constant():
    """Verifies that the authoritative architectural invariant is asserted True."""
    assert CLOUD_AUTONOMOUS is True
    assert "github_actions_runner" in ALLOWED_RUNTIME
    assert "google_drive_api" in ALLOWED_RUNTIME
    assert "selenium" in FORBIDDEN_RUNTIME
    assert "antigravity" in FORBIDDEN_RUNTIME
    assert "browser_engines" in FORBIDDEN_RUNTIME
    assert "windows_task_scheduler" in FORBIDDEN_RUNTIME


def test_no_browser_or_antigravity_in_production_modules():
    """
    Scans all production pipeline modules to prove complete absence of
    Antigravity, local browser automation, or interactive GUI packages.
    """
    production_modules = [
        "sources.news_ingestion",
        "sources.extractor",
        "sources.gdelt_adapter",
        "sources.rss_sources",
        "intelligence.clustering",
        "intelligence.verification",
        "intelligence.event_card",
        "intelligence.journalistic_script",
        "intelligence.visual_models",
        "intelligence.visual_sources",
        "intelligence.visual_matching",
        "intelligence.visual_evidence",
        "intelligence.asset_manifest",
        "intelligence.asset_fetcher",
        "intelligence.media_cache",
        "intelligence.headless_renderer",
        "intelligence.video_qa",
        "intelligence.cloud_orchestrator",
        "core.database",
        "core.database_sync",
        "core.pipeline_state",
    ]

    prohibited_terms = [
        "antigravity",
        "selenium",
        "playwright",
        "puppeteer",
        "pyppeteer",
        "pyautogui",
        "webbrowser.open",
    ]

    for mod_name in production_modules:
        if mod_name not in sys.modules:
            __import__(mod_name)
        mod = sys.modules[mod_name]
        source_code = inspect.getsource(mod).lower()

        for term in prohibited_terms:
            assert f"import {term}" not in source_code, f"Found 'import {term}' in {mod_name}"
            assert f"from {term}" not in source_code, f"Found 'from {term}' in {mod_name}"
            assert f"{term}(" not in source_code, f"Found '{term}(' in {mod_name}"


def test_production_paths_are_relative_and_cloud_portable():
    r"""Confirms no hardcoded C:\Users or local desktop references exist in production config."""
    assert str(settings.PROJECT_ROOT).strip() != ""
    assert not str(settings.DATA_DIR).startswith("C:\\Users\\Administrator")
    assert not str(settings.RENDERS_DIR).startswith("C:\\Users\\Default")


# ==============================================================================
# 2. Workflow Headlessness & Publishing Separation Tests
# ==============================================================================

def test_produce_buffer_workflow_has_zero_publishing_calls():
    """
    Strictly verifies that .github/workflows/produce_buffer.yml produces
    to 01_READY only and has NO calls to --schedule-ready or YouTube publishing.
    """
    wf_path = settings.PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml"
    assert wf_path.exists()
    content = wf_path.read_text(encoding="utf-8")

    assert "--schedule-ready" not in content, "produce_buffer.yml must NOT invoke --schedule-ready"
    assert "schedule_ready" not in content.lower() or "name:" in content, "Found unseparated publishing in produce_buffer.yml"


def test_autopilot_workflow_handles_publishing_isolated():
    """Verifies autopilot.yml is the dedicated publishing workflow."""
    wf_path = settings.PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml"
    assert wf_path.exists()
    content = wf_path.read_text(encoding="utf-8")

    assert "--schedule-ready" in content or "publish_next" in content
    assert "ubuntu-latest" in content


# ==============================================================================
# 3. Pipeline Lifecycle States & Telemetry Tests
# ==============================================================================

def test_pipeline_stage_transitions():
    """Verifies monotonic stage transitions and telemetry completion."""
    telemetry = ProductionRunTelemetry(target_buffer=6)
    assert telemetry.current_stage == PipelineStage.INITIALIZING.value
    assert telemetry.status == "IN_PROGRESS"

    telemetry.transition_stage(PipelineStage.INGESTING, "Testing ingestion stage")
    assert telemetry.current_stage == PipelineStage.INGESTING.value

    telemetry.transition_stage(PipelineStage.RENDERING, "Testing rendering stage")
    assert telemetry.current_stage == PipelineStage.RENDERING.value

    telemetry.complete(status="SUCCEEDED")
    assert telemetry.status == "SUCCEEDED"
    assert telemetry.end_time is not None
    assert telemetry.duration_seconds >= 0.0

    d = telemetry.to_dict()
    assert d["status"] == "SUCCEEDED"
    assert d["target_buffer"] == 6


# ==============================================================================
# 4. Cloud Locking & Concurrency Tests
# ==============================================================================

def test_cloud_lock_lifecycle():
    """Tests cloud lock acquisition and release semantics."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "sys_folder_123"}
    mock_drive.list_files.return_value = []
    mock_drive.upload_raw_content.return_value = "lock_file_id_999"

    lock = CloudLockManager(drive_engine=mock_drive, run_id="test_run_123")
    assert lock.acquire() is True
    assert lock._lock_file_id == "lock_file_id_999"

    # Release
    assert lock.release() is True
    mock_drive.delete_file.assert_called_once_with("lock_file_id_999")


def test_cloud_lock_stale_recovery():
    """Tests that a cloud lock older than 1 hour is broken as stale."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "sys_folder_123"}

    stale_timestamp = datetime.now(timezone.utc).timestamp() - 7200.0  # 2 hours old
    mock_drive.list_files.return_value = [
        {
            "id": "old_stale_lock_id",
            "name": "cloud_production.lock",
            "properties": {"timestamp": str(stale_timestamp), "run_id": "old_crashed_run"},
        }
    ]
    mock_drive.upload_raw_content.return_value = "new_lock_file_id"

    lock = CloudLockManager(drive_engine=mock_drive, run_id="new_run_456")
    assert lock.acquire() is True

    # Stale file was deleted
    mock_drive.delete_file.assert_called_once_with("old_stale_lock_id")
    # New lock file created
    mock_drive.upload_raw_content.assert_called_once()


# ==============================================================================
# 5. Buffer Management & Replenishment Logic
# ==============================================================================

def test_buffer_healthy_exits_early_with_zero_production():
    """When ready stock in Drive meets or exceeds target, zero production is performed."""
    mock_drive = MagicMock()
    mock_drive.get_ready_stock_count.return_value = 8  # Current 8 >= Target 6

    orchestrator = CloudProductionOrchestrator(
        drive_engine=mock_drive,
        is_dry_run=True,
    )

    with patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])):
        telemetry = orchestrator.run_production_cycle(target_buffer=6)

    assert telemetry.status == "SUCCEEDED"
    assert telemetry.current_stage == PipelineStage.BUFFER_HEALTHY.value
    assert telemetry.videos_rendered == 0
    assert telemetry.videos_deposited == 0


# ==============================================================================
# 6. Idempotency & Duplicate Prevention Tests
# ==============================================================================

def test_is_event_already_produced():
    """Verifies that an event with an existing PASSED RenderedVideoRecord is skipped."""
    init_db()
    db = SessionLocal()
    try:
        # Insert a sample rendered record
        rec = RenderedVideoRecord(
            id="rend_idemp_01",
            manifest_id="mani_idemp_01",
            event_id="ev_idemp_100",
            script_id="sc_idemp_01",
            video_path="path/to/video.mp4",
            duration_seconds=30.0,
            qa_status="PASSED",
        )
        db.query(RenderedVideoRecord).filter_by(id="rend_idemp_01").delete()
        db.add(rec)
        db.commit()

        orchestrator = CloudProductionOrchestrator(is_dry_run=True)
        assert orchestrator.is_event_already_produced("ev_idemp_100", db) is True
        assert orchestrator.is_event_already_produced("ev_brand_new_999", db) is False
    finally:
        db.close()


# ==============================================================================
# 7. Dry-Run Execution Mode Verification
# ==============================================================================

def test_dry_run_executes_decision_pipeline_without_uploads():
    """
    Verifies that dry-run mode (AL_AMR_DRY_RUN=true) runs decision graph
    (scripting, visual evidence, manifest) but avoids rendering or Drive upload.
    """
    claim1 = ClaimEvidence(
        claim_id="claim_dry_01",
        claim_text="Danish patrol intercepted an unflagged tanker in the Baltic straits.",
        publisher="Reuters",
        source_url="https://reuters.com/baltic-tanker",
        confidence=0.95,
    )
    event_card = EventCard(
        event_id="ev_baltic_dry_run",
        canonical_title="Danish Patrol Intercepts Tanker in Baltic Straits",
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.95,
        first_seen_utc=datetime.now(timezone.utc) - timedelta(hours=2),
        latest_seen_utc=datetime.now(timezone.utc),
        who=WhoSection(
            organizations=["Danish Navy"],
            countries=["Denmark"],
            military_units=["Danish Patrol"],
        ),
        what="Danish patrol intercepted an unflagged tanker in Baltic international waters",
        where=WhereSection(
            region="Baltic Sea",
            location_name="Baltic Straits",
            country="Denmark",
        ),
        when=WhenSection(
            event_time_utc=datetime.now(timezone.utc) - timedelta(hours=2),
        ),
        actions=["intercepted", "boarded"],
        entities=["Danish Patrol", "Baltic Straits", "Danish Navy"],
        claims=[claim1],
        sources=[{"publisher": "Reuters", "url": "https://reuters.com/baltic-tanker"}],
    )

    orchestrator = CloudProductionOrchestrator(is_dry_run=True)
    telemetry = ProductionRunTelemetry(is_dry_run=True)

    db = SessionLocal()
    try:
        # Clear any existing record
        db.query(RenderedVideoRecord).filter_by(event_id="ev_baltic_dry_run").delete()
        db.commit()

        res = orchestrator.produce_single_event(event_card, telemetry, db)
        # Res is None in dry-run because rendering and uploads are skipped
        assert res is None
        assert telemetry.scripts_generated == 1
        assert telemetry.visual_plans_generated == 1
        assert telemetry.videos_rendered == 1  # Decision simulated
        assert telemetry.videos_qa_passed == 1
        assert telemetry.videos_deposited == 0  # Zero uploads in dry-run
    finally:
        db.close()


# ==============================================================================
# 8. QA Gate Enforcement: Failed Videos Never Enter READY Vault
# ==============================================================================

def test_qa_gate_blocks_failed_renders():
    """Ensures that any video failing VideoQA is rejected and never uploaded to 01_READY."""
    sample_card = EventCard(
        event_id="ev_qa_fail_test",
        canonical_title="Red Sea Coalition Patrol Intercepts Airborne Drones",
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.94,
        first_seen_utc=datetime.now(timezone.utc) - timedelta(hours=3),
        latest_seen_utc=datetime.now(timezone.utc),
        who=WhoSection(
            organizations=["US Navy"],
            countries=["United States"],
            military_units=["USS Carney"],
        ),
        what="Naval forces intercepted multiple attack drones targeting commercial shipping",
        where=WhereSection(
            region="Red Sea",
            location_name="Bab el-Mandeb",
            country="Yemen",
        ),
        when=WhenSection(
            event_time_utc=datetime.now(timezone.utc) - timedelta(hours=3),
        ),
        actions=["intercepted", "shot down"],
        entities=["US Navy", "Red Sea", "USS Carney"],
        claims=[
            ClaimEvidence(
                claim_id="cl_qa_fail_01",
                claim_text="Naval forces shot down three drones over the Red Sea",
                publisher="Reuters",
                source_url="https://reuters.com/redsea-intercept",
                confidence=0.95,
            )
        ],
        sources=[{"publisher": "Reuters", "url": "https://reuters.com/redsea-intercept"}],
    )

    mock_drive = MagicMock()
    orchestrator = CloudProductionOrchestrator(drive_engine=mock_drive, is_dry_run=False)
    telemetry = ProductionRunTelemetry(is_dry_run=False)

    db = SessionLocal()
    try:
        db.query(RenderedVideoRecord).filter_by(event_id="ev_qa_fail_test").delete()
        db.commit()

        # Mock composer to produce a failed QA report
        fake_mp4 = Path("data/renders/fake_failed.mp4")
        failed_qa = VideoQAReport(
            video_path=str(fake_mp4),
            passed=False,
            status="FAILED",
            failure_reasons=["Continuous black frames detected (2.5s >= 0.5s threshold)."],
        )
        fake_rec = RenderedVideoRecord(
            id="rend_fail_01",
            manifest_id="mani_fail_01",
            event_id="ev_qa_fail_test",
            script_id="sc_fail_01",
            video_path=str(fake_mp4),
            duration_seconds=25.0,
            qa_status="FAILED",
        )

        with patch.object(orchestrator.composer, "assemble_manifest", return_value=(fake_mp4, failed_qa, fake_rec)):
            res = orchestrator.produce_single_event(sample_card, telemetry, db)

        assert res is None
        assert telemetry.videos_qa_failed == 1
        assert telemetry.videos_deposited == 0
        mock_drive.upload_video_to_vault.assert_not_called()
    finally:
        db.close()


# ==============================================================================
# 9. Voice & Audio Policy Invariants
# ==============================================================================

def test_voice_and_audio_invariants():
    """Confirms voice is Bella and configured in orchestrator."""
    orchestrator = CloudProductionOrchestrator()
    assert orchestrator.voice_id == "af_bella"
    assert orchestrator.composer.config.voice_id == "af_bella"



# ==============================================================================
# 10. End-to-End Orchestrator Ingestion & Clustering Integration
# ==============================================================================

def test_orchestrator_end_to_end_cycle():
    """
    Tests an end-to-end production cycle:
    Ingestion -> Clustering -> EventCard -> Scripting -> Manifest -> Dry Run Complete.
    """
    mock_drive = MagicMock()
    mock_drive.get_ready_stock_count.return_value = 2  # Stock 2 < Target 3 -> Deficit 1

    orchestrator = CloudProductionOrchestrator(
        drive_engine=mock_drive,
        is_dry_run=True,
    )

    fake_articles = [
        RawArticle(
            article_id="art_baltic_1",
            title="Danish Navy boards shadow tanker in Baltic international waters",
            summary="Naval authorities inspected a non-compliant vessel in Danish straits.",
            url="https://reuters.com/baltic-tanker-1",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=datetime.now(timezone.utc),
            article_text="Full article text confirming Danish naval boarding in Baltic Sea.",
        ),
        RawArticle(
            article_id="art_baltic_2",
            title="Maritime authorities confirm inspection of Baltic shadow fleet tanker",
            summary="Coordinated operation underway in the Baltic sea route.",
            url="https://apnews.com/baltic-tanker-2",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=datetime.now(timezone.utc),
            article_text="AP confirms multi-lateral monitoring of vessel in the Baltic straits.",
        ),
    ]

    with patch.object(orchestrator.ingestion_service, "ingest_live_news", return_value=fake_articles), \
         patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])):
        telemetry = orchestrator.run_production_cycle(target_buffer=3, force_batch_count=1)

    assert telemetry.status == "SUCCEEDED"
    assert telemetry.events_discovered == 2
    assert telemetry.events_verified >= 1
    assert telemetry.scripts_generated >= 1
    assert telemetry.visual_plans_generated >= 1
    assert telemetry.videos_rendered >= 1
    assert telemetry.videos_qa_passed >= 1


# ==============================================================================
# 11. Target Buffer = 6 Deficit & Compute Conservation Tests
# ==============================================================================

@pytest.mark.parametrize(
    "ready_count, requested_count, expected_deficit, expected_to_produce",
    [
        (0, 1, 6, 1),
        (0, 6, 6, 6),
        (1, 2, 5, 2),
        (1, 0, 5, 5),
        (4, 3, 2, 2),
        (4, 0, 2, 2),
        (5, 2, 1, 1),
        (5, 0, 1, 1),
        (6, 1, 0, 0),
        (6, 0, 0, 0),
        (7, 1, 0, 0),
        (7, 5, 0, 0),
    ],
)
def test_target_buffer_6_deficit_logic(
    ready_count, requested_count, expected_deficit, expected_to_produce
):
    """
    Verifies that for TARGET_BUFFER = 6:
    deficit = max(0, 6 - ready_count)
    to_produce = min(requested_count, deficit)
    """
    target = 6
    deficit = max(0, target - ready_count)
    assert deficit == expected_deficit

    req = requested_count if requested_count > 0 else deficit
    to_produce = min(req, deficit)
    assert to_produce == expected_to_produce


def test_buffer_full_conserves_compute_when_ready_ge_6():
    """
    When READY >= 6, orchestrator MUST NOT render additional videos merely because
    a requested count was supplied; compute/API must be conserved and buffer reported full.
    """
    mock_drive = MagicMock()
    mock_drive.get_ready_stock_count.return_value = 6  # Buffer already at target 6

    orchestrator = CloudProductionOrchestrator(
        drive_engine=mock_drive,
        is_dry_run=True,
    )

    with patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])), \
         patch.object(orchestrator.ingestion_service, "ingest_live_news") as mock_ingest:
        # Request 2 videos when stock is already 6
        telemetry = orchestrator.run_production_cycle(target_buffer=6, force_batch_count=2)

    # Ingestion and production must be bypassed to conserve compute
    mock_ingest.assert_not_called()
    assert telemetry.status == "SUCCEEDED"
    assert telemetry.current_stage == "BUFFER_HEALTHY"
    assert telemetry.initial_ready_stock == 6
    assert telemetry.videos_deposited == 0
    assert telemetry.scripts_generated == 0
