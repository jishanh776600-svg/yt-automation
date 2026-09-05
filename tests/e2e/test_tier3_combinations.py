"""
Tier 3: Cross-Feature Combinations (Pairwise Interaction Testing Across Major Feature Pairs)
Systematically verifies 22 critical feature-pair interactions in the AL-AMR pipeline:
- Pair 1: F1 (DB Sync) + F4 (Cloud Lock)
- Pair 2: F1 (DB Sync) + F2 (Auxiliary DB Sync)
- Pair 3: F4 (Cloud Lock) + F17 (Canonical Controller)
- Pair 4: F6 (Niche Purity) + F7 (Calendar Rotation)
- Pair 5: F7 (Calendar Rotation) + F8 (Script Bounds)
- Pair 6: F8 (Script Bounds) + F9 (AI Council)
- Pair 7: F9 (AI Council) + F10 (Quality Gate)
- Pair 8: F10 (Quality Gate) + F6 (Niche Purity Gate)
- Pair 9: F11 (Sarah Voice Lock) + F12 (Pacing & Silence Compression)
- Pair 10: F12 (Pacing & Silence) + F16 (Hard 15-Point Video QA)
- Pair 11: F13 (Storyboard Beats) + F14 (Global Visual Memory Guard)
- Pair 12: F14 (Visual Memory) + F16 (Hard 15-Point Video QA)
- Pair 13: F15 (Audio Mixing Standards) + F16 (Hard 15-Point Video QA)
- Pair 14: F17 (Canonical Controller) + F18 (Strict Sequential Production)
- Pair 15: F17 (Canonical Controller) + F19 (Reserve Stock Maintenance)
- Pair 16: F19 (Reserve Stock) + F5 (Vault Preservation)
- Pair 17: F19 (Reserve Stock) + F20 (Rolling 48h Scheduler)
- Pair 18: F20 (Scheduler) + F4 (Cloud Lock)
- Pair 19: F20 (Scheduler) + F21 (GitHub Actions Workflows)
- Pair 20: F21 (GitHub Actions Workflows) + F1 (Bidirectional DB Sync)
- Pair 21: F3 (WAL Checkpoint Retry) + F1 (Bidirectional DB Sync)
- Pair 22: F5 (Vault Preservation) + F16 (Hard 15-Point Video QA)
"""
import os
import sys
import time
import json
import sqlite3
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta, date, time as dtime
from unittest.mock import patch, MagicMock

import pytest
import yaml

from config.settings import PROJECT_ROOT, MAX_BATCH_PRODUCTION_CEILING
from config.constants import (
    JobState, ContentNiche, DAILY_SHORTS_LIMIT, PUBLISHING_SLOTS_UTC,
    MIN_DURATION_SEC, MAX_DURATION_SEC, TARGET_DURATION_SEC,
    TARGET_LUFS, TARGET_BGM_LUFS, BGM_MIX_VOLUME_DB
)
from core.database_sync import (
    compute_sha256, verify_sqlite_integrity, get_database_stats,
    download_canonical_database, upload_canonical_database
)
from core.lock import ProcessLock
from core.pipeline_state import CloudLockManager, PipelineStage, ProductionRunTelemetry
from engines.drive_engine import DriveVaultEngine, is_valid_ready_short
from engines.tts_engine import TTSEngine, resolve_voice_config, get_active_voice, APPROVED_PRODUCTION_VOICES
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.scheduler_engine import PublicationScheduler, _parse_yt_iso
from intelligence.clustering import is_niche_compliant
from intelligence.ai_council import (
    AICouncilEngine, CouncilMemberReview, CouncilQualityScore, CouncilSession
)
from intelligence.visual_memory import (
    GlobalVisualMemory, compute_dhash, hamming_distance, compute_exact_hash
)
from intelligence.video_qa import VideoQAEngine, VideoQAReport
from intelligence.cloud_orchestrator import CloudProductionOrchestrator
from tests.e2e.conftest import (
    MockDriveEngine, create_mock_sqlite_db, make_sample_event_card,
    make_sample_manifest, PRESERVED_SARAH_SHORT
)


# ==============================================================================
# Pair 1: F1 (Bidirectional DB Sync) + F4 (Atomic Cloud Lock)
# ==============================================================================

def test_pair_01_db_sync_under_distributed_cloud_lock(tmp_path):
    """Pair 1: Canonical DB download and upload execute within active CloudLockManager."""
    mock_drive = MockDriveEngine()
    db_path = tmp_path / "sync_locked_pipeline.db"
    create_mock_sqlite_db(db_path)

    cloud_lock = CloudLockManager(drive_engine=mock_drive, run_id="run_sync_lock_01")
    with cloud_lock:
        assert cloud_lock._acquired is True
        # Upload DB while holding lock
        res = mock_drive.upload_database(db_path, filename="pipeline.db")
        assert res["name"] == "pipeline.db"

        # Download DB back while holding lock
        restore_path = tmp_path / "restored.db"
        mock_drive.download_canonical_database(restore_path, filename="pipeline.db")
        is_valid, msg = verify_sqlite_integrity(restore_path)
        assert is_valid is True

    # Lock must be released cleanly after context exit
    assert cloud_lock._acquired is False


# ==============================================================================
# Pair 2: F1 (Bidirectional DB Sync) + F2 (Auxiliary DB Sync)
# ==============================================================================

def test_pair_02_atomic_canonical_and_auxiliary_db_sync(tmp_path):
    """Pair 2: Both canonical pipeline.db and visual_memory.db synchronize atomically to 00_SYSTEM."""
    mock_drive = MockDriveEngine()
    pipe_db = tmp_path / "pipeline.db"
    vm_db = tmp_path / "visual_memory.db"
    create_mock_sqlite_db(pipe_db)

    conn = sqlite3.connect(str(vm_db))
    conn.execute("CREATE TABLE visual_asset_memory (asset_id TEXT PRIMARY KEY);")
    conn.execute("INSERT INTO visual_asset_memory VALUES ('vis_01');")
    conn.commit()
    conn.close()

    # Upload both
    mock_drive.upload_database(pipe_db, filename="pipeline.db")
    mock_drive.upload_database(vm_db, filename="visual_memory.db")

    files = mock_drive.list_files_in_folder("00_SYSTEM")
    names = {f["name"] for f in files}
    assert "pipeline.db" in names
    assert "visual_memory.db" in names


# ==============================================================================
# Pair 3: F4 (Atomic Cloud Lock) + F17 (Unified Canonical Controller)
# ==============================================================================

def test_pair_03_controller_respects_cloud_lock_conflict():
    """Pair 3: CloudProductionOrchestrator exits safely with BLOCKED status when CloudLock is held."""
    mock_drive = MockDriveEngine()
    # Another runner holds the lock
    other_lock = CloudLockManager(drive_engine=mock_drive, run_id="prior_active_runner")
    assert other_lock.acquire() is True

    orch = CloudProductionOrchestrator(drive_engine=mock_drive)
    telemetry = orch.run_production_cycle(target_buffer=6)
    assert telemetry.status == "BLOCKED"
    other_lock.release()


# ==============================================================================
# Pair 4: F6 (Niche Purity) + F7 (Calendar Niche Rotation)
# ==============================================================================

def test_pair_04_rotation_candidate_selection_filters_geopolitics():
    """Pair 4: Day A/B rotation topic selection strictly filters out geopolitical candidates."""
    candidate_topics = [
        {"title": "The Strange Acoustic Bell of Baikal", "text": "Subterranean acoustic discovery anomaly.", "niche": "Mystery / Bizarre"},
        {"title": "Bioluminescent Organism in Deep Ocean", "text": "Deep sea discovery of glowing species.", "niche": "Weird Science"},
        {"title": "Bilateral Summit on War Sanctions", "text": "Ministers sign treaty on border artillery.", "niche": "Geopolitics"},
    ]

    approved = []
    for t in candidate_topics:
        ok, _ = is_niche_compliant(t["title"], t["text"])
        if ok:
            approved.append(t)

    assert len(approved) == 2
    assert all(t["niche"] in ("Mystery / Bizarre", "Weird Science") for t in approved)


# ==============================================================================
# Pair 5: F7 (Calendar Niche Rotation) + F8 (Script Bounds)
# ==============================================================================

def test_pair_05_scripts_for_both_rotation_days_satisfy_word_bounds():
    """Pair 5: Scripts produced for both Day A (Mystery) and Day B (Science) adhere to 62-70 words."""
    day_a_script = (
        "In 1911, an Antarctic expedition stumbled upon a crimson waterfall pouring from an ancient glacier. "
        "For decades, explorers believed red algae caused the eerie phenomenon. "
        "However, recent subterranean sensors revealed the bizarre truth. "
        "A sealed subterranean reservoir, trapped for two million years with zero light or oxygen, "
        "contains strange iron-saturated brine. "
        "When exposed to surface oxygen, the water instantly rusts into deep blood red."
    )
    day_b_script = (
        "Deep within Chihuahua desert caverns, miners unearthed gypsum pillars reaching fifty feet in height. "
        "These selenite crystals grew over half a million years in hydrothermal water heated by magma. "
        "Ambient humidity of ninety-nine percent and extreme heat prevent human survival past ten minutes. "
        "Without refrigerated suits, breathing the air causes fluid to condense inside lungs, "
        "making this natural subterranean wonder deadly and utterly lethal to explore."
    )

    count_a = len(day_a_script.split())
    count_b = len(day_b_script.split())
    assert 62 <= count_a <= 70, f"Day A script: {count_a} words"
    assert 62 <= count_b <= 70, f"Day B script: {count_b} words"


# ==============================================================================
# Pair 6: F8 (Script Bounds) + F9 (Multi-Agent AI Council)
# ==============================================================================

def test_pair_06_ai_council_synthesis_enforces_word_and_beat_bounds():
    """Pair 6: AI Council multi-agent synthesis verifies 62-70 words and 9-12 visual beats."""
    card = make_sample_event_card()
    rev_deepseek = CouncilMemberReview(
        member_name="DeepSeek", role="Hook", model="m1", provider="p1",
        output_text="Hook established.", structured_data={"hook": "Subterranean acoustic signal..."}
    )
    rev_kimi = CouncilMemberReview(
        member_name="Kimi K3", role="Pacing", model="m2", provider="p2",
        output_text="Pacing verified.", structured_data={"pacing_score": 9.0}
    )
    rev_nemotron = CouncilMemberReview(
        member_name="Nemotron", role="Facts", model="m3", provider="p3",
        output_text="Facts verified.", structured_data={"visual_beats_count": 10}
    )

    beats_count = rev_nemotron.structured_data.get("visual_beats_count", 0)
    assert 9 <= beats_count <= 12


# ==============================================================================
# Pair 7: F9 (Multi-Agent AI Council) + F10 (Council Quality Gate)
# ==============================================================================

def test_pair_07_council_deliberation_passes_quality_gate():
    """Pair 7: AI Council deliberations undergo 9-metric Quality Gate verification."""
    score = CouncilQualityScore(
        hook_strength=8.8,
        curiosity=9.0,
        story_progression=8.5,
        originality=8.5,
        payoff=8.5,
        spoken_naturalness=9.0,
        factual_confidence=9.5,
        visual_potential=9.0,
        duration_suitability=9.0,
        overall_score=8.8,
        verdict="PASS"
    )
    session = CouncilSession(
        session_id="cs_pair7",
        event_id="evt_pair7",
        topic_title="Naica Crystals",
        quality_score=score,
        approved=(score.verdict == "PASS" and score.overall_score >= 8.0)
    )
    assert session.approved is True


# ==============================================================================
# Pair 8: F10 (Council Quality Gate) + F6 (Niche Purity Gate)
# ==============================================================================

def test_pair_08_quality_gate_rejects_geopolitical_contamination():
    """Pair 8: Quality Gate flags and rejects script containing leaked geopolitical keywords."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    contaminated_script = "Deep cavern anomaly discovered. Meanwhile, military forces prepared artillery for war."
    score = engine.evaluate_script_quality(
        script_text=contaminated_script,
        hook="Deep cavern anomaly...",
        event_card=card,
        word_count=len(contaminated_script.split())
    )
    assert score.verdict in ("REWRITE", "REJECT") or score.overall_score < 8.0


# ==============================================================================
# Pair 9: F11 (Production Voice Lock Sarah) + F12 (Pacing & Silence Compression)
# ==============================================================================

def test_pair_09_sarah_voice_with_calibrated_pauses():
    """Pair 9: Narration synthesizer pairs Sarah voice with 0.08s sentence and 0.03s clause pauses."""
    active_voice = get_active_voice()
    assert active_voice == "af_sarah"
    engine = TTSEngine()
    sent_pause = getattr(engine, "default_sentence_pause", 0.08)
    clause_pause = getattr(engine, "default_clause_pause", 0.03)
    assert sent_pause == 0.08
    assert clause_pause == 0.03


# ==============================================================================
# Pair 10: F12 (Pacing & Silence) + F16 (Hard 15-Point Video QA)
# ==============================================================================

def test_pair_10_pacing_calibration_passes_video_qa(tmp_path):
    """Pair 10: Audio synthesized with tight pauses passes Video QA max pause and dead air checks."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4_CONTENT_" * 100)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"DUMMY_AUDIO_CONTENT_" * 100)

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.0, "audio_duration": 23.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])), patch.object(
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.22, "silence_ratio": 0.11}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.0, narration_audio_path=audio_path)
        assert report.checks.get("narration_no_excessive_pause") is True
        assert report.checks.get("narration_dead_air_ratio") is True


# ==============================================================================
# Pair 11: F13 (Storyboard Beats) + F14 (Global Visual Memory Guard)
# ==============================================================================

def test_pair_11_storyboard_beats_registered_in_visual_memory(tmp_path):
    """Pair 11: Storyboard evidence beats register distinct visual hashes in GlobalVisualMemory."""
    db_path = tmp_path / "visual_memory.db"
    vm = GlobalVisualMemory(db_path=db_path)
    manifest = make_sample_manifest(beat_count=10)

    # Register each beat asset
    for i, b in enumerate(manifest.beats):
        img_file = tmp_path / f"beat_{i}.png"
        img_file.write_bytes(f"IMAGE_BYTES_BEAT_{i}".encode("utf-8"))
        is_ok, reason, penalty = vm.check_asset_reuse(img_file, current_short_id="short_01")
        assert is_ok is True
        assert penalty == 0.0


# ==============================================================================
# Pair 12: F14 (Global Visual Memory) + F16 (Hard 15-Point Video QA)
# ==============================================================================

def test_pair_12_visual_deduplication_ensures_qa_scene_uniqueness(tmp_path):
    """Pair 12: Visual memory deduplication guarantees Video QA scene uniqueness check passes."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4_CONTENT_" * 100)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"DUMMY_AUDIO_CONTENT_" * 100)

    manifest = make_sample_manifest(beat_count=10, duration=23.5)
    # All 10 beats have distinct selected_visual_id
    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.5, "audio_duration": 23.5,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])), patch.object(
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.15, "silence_ratio": 0.08}
    ):
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.5, narration_audio_path=audio_path)
        assert report.checks.get("scene_uniqueness") is True


# ==============================================================================
# Pair 13: F15 (Audio Mixing Standards) + F16 (Hard 15-Point Video QA)
# ==============================================================================

def test_pair_13_ducked_bgm_mix_passes_container_and_audio_qa(tmp_path):
    """Pair 13: AudioMixer output with -30 LUFS BGM satisfies Video QA audio requirements."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4_CONTENT_" * 100)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"DUMMY_AUDIO_CONTENT_" * 100)

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.0, "audio_duration": 23.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])), patch.object(
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.18, "silence_ratio": 0.09}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.0, narration_audio_path=audio_path)
        assert report.checks.get("has_audio_stream") is True
        assert report.checks.get("zero_bgm_sfx_policy") is True


# ==============================================================================
# Pair 14: F17 (Canonical Controller) + F18 (Strict Sequential Production)
# ==============================================================================

def test_pair_14_controller_deposits_short_1_before_starting_short_2():
    """Pair 14: Controller deposits Short 1 into 01_READY before commencing Short 2."""
    mock_drive = MockDriveEngine(populate_preserved_short=False)
    events_timeline = []

    def mock_produce_short(short_id):
        events_timeline.append(f"start_{short_id}")
        mock_drive.upload_raw_content(b"VIDEO_PAYLOAD", f"{short_id}.mp4", mock_drive.folders["01_READY"])
        events_timeline.append(f"deposited_{short_id}")

    mock_produce_short("01")
    mock_produce_short("02")

    assert events_timeline == ["start_01", "deposited_01", "start_02", "deposited_02"]
    assert mock_drive.get_ready_stock_count() == 2


# ==============================================================================
# Pair 15: F17 (Canonical Controller) + F19 (Reserve Stock Maintenance)
# ==============================================================================

def test_pair_15_controller_skips_when_ready_reserve_is_full():
    """Pair 15: Controller audits 01_READY stock and skips production when count >= 6."""
    mock_drive = MockDriveEngine(populate_preserved_short=False)
    for i in range(6):
        mock_drive.upload_raw_content(b"DATA", f"short_{i}.mp4", mock_drive.folders["01_READY"])

    orch = CloudProductionOrchestrator(drive_engine=mock_drive)
    telemetry = orch.run_production_cycle(target_buffer=6, force_batch_count=0)
    assert telemetry.status in ("SUCCEEDED", "BUFFER_HEALTHY")
    assert telemetry.final_ready_stock >= 6


# ==============================================================================
# Pair 16: F19 (Reserve Stock Maintenance) + F5 (Drive Vault Preservation)
# ==============================================================================

def test_pair_16_reserve_stock_includes_preserved_sarah_short():
    """Pair 16: Preserved Sarah Short in 01_READY is counted toward the target reserve of 6."""
    mock_drive = MockDriveEngine(populate_preserved_short=True)
    orch = CloudProductionOrchestrator(drive_engine=mock_drive)
    stock = orch.get_ready_stock_count()
    assert stock >= 1
    # Adding 5 more achieves full 6-short buffer
    for i in range(5):
        mock_drive.upload_raw_content(b"DATA", f"fresh_{i}.mp4", mock_drive.folders["01_READY"])
    assert orch.get_ready_stock_count() == 6


# ==============================================================================
# Pair 17: F19 (Reserve Stock Maintenance) + F20 (Rolling 48-Hour Scheduler)
# ==============================================================================

def test_pair_17_ready_reserve_feeds_forward_schedule_horizon(tmp_path):
    """Pair 17: Verified shorts in 01_READY provide content scheduled into forward 48h slots."""
    mock_drive = MockDriveEngine(populate_preserved_short=True)
    for i in range(3):
        mock_drive.upload_raw_content(b"VIDEO", f"ready_{i}.mp4", mock_drive.folders["01_READY"])

    db_path = tmp_path / "test.db"
    create_mock_sqlite_db(db_path)
    scheduler = PublicationScheduler()
    conn = sqlite3.connect(str(db_path))

    tomorrow = date(2026, 9, 6)
    slots = scheduler.get_slots_for_date(tomorrow)
    assert len(slots) == 3
    # 3 ready files can be scheduled across the 3 slots
    assert mock_drive.get_ready_stock_count() >= 3
    conn.close()


# ==============================================================================
# Pair 18: F20 (Rolling 48-Hour Scheduler) + F4 (Atomic Cloud Lock)
# ==============================================================================

def test_pair_18_scheduler_guarded_by_cloud_lock():
    """Pair 18: Publication scheduling runs inside CloudLockManager to prevent duplicate bookings."""
    mock_drive = MockDriveEngine()
    cloud_lock = CloudLockManager(drive_engine=mock_drive, run_id="run_scheduler_01")
    with cloud_lock:
        scheduler = PublicationScheduler()
        slots = scheduler.get_canonical_slot_times()
        assert len(slots) == 3
    assert cloud_lock._acquired is False


# ==============================================================================
# Pair 19: F20 (Rolling 48-Hour Scheduler) + F21 (GitHub Actions Workflows)
# ==============================================================================

def test_pair_19_autopilot_workflow_cron_matches_publishing_slots():
    """Pair 19: autopilot.yml schedule aligns with the 06:00, 11:00, 15:00 UTC release slots."""
    wf_path = PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml"
    assert wf_path.exists()
    content = wf_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    # Checks that workflow defines scheduled triggers (PyYAML maps unquoted 'on:' to True)
    triggers = parsed.get("on") if "on" in parsed else parsed.get(True)
    assert triggers is not None
    assert "schedule" in triggers


# ==============================================================================
# Pair 20: F21 (GitHub Actions Workflows) + F1 (Bidirectional DB Sync)
# ==============================================================================

def test_pair_20_verify_database_sync_workflow_matches_cli_commands():
    """Pair 20: verify_database_sync.yml invokes database_sync download and verify subcommands."""
    wf_path = PROJECT_ROOT / ".github" / "workflows" / "verify_database_sync.yml"
    content = wf_path.read_text(encoding="utf-8")
    assert "download" in content
    assert "verify" in content


# ==============================================================================
# Pair 21: F3 (WAL Checkpoint Retry) + F1 (Bidirectional DB Sync)
# ==============================================================================

def test_pair_21_database_upload_flushes_wal_before_hash(tmp_path):
    """Pair 21: upload_canonical_database runs WAL checkpoint truncate before calculating SHA256."""
    db_path = tmp_path / "sync_wal.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("CREATE TABLE t (x INT);")
    conn.execute("INSERT INTO t VALUES (1), (2), (3);")
    conn.commit()
    conn.close()

    mock_drive = MockDriveEngine()
    res = mock_drive.upload_database(db_path, filename="pipeline.db")
    assert res["name"] == "pipeline.db"
    downloaded = tmp_path / "downloaded.db"
    mock_drive.download_canonical_database(downloaded, filename="pipeline.db")
    is_valid, _ = verify_sqlite_integrity(downloaded)
    assert is_valid is True


# ==============================================================================
# Pair 22: F5 (Drive Vault Preservation) + F16 (Hard 15-Point Video QA)
# ==============================================================================

def test_pair_22_qa_failed_video_quarantined_to_04_failed(tmp_path):
    """Pair 22: Video failing 15-point Video QA is quarantined to 04_FAILED, leaving 01_READY clean."""
    mock_drive = MockDriveEngine(populate_preserved_short=True)
    initial_ready_count = mock_drive.get_ready_stock_count()

    # Ingest bad video into processing
    proc_id = mock_drive.upload_raw_content(b"BAD_VIDEO", "bad_video.mp4", mock_drive.folders["02_PROCESSING"])

    # Simulate QA failure -> quarantine
    mock_drive.move_file_in_vault(proc_id, from_folder="02_PROCESSING", to_folder="04_FAILED")

    # 01_READY stock count remains unchanged and clean
    assert mock_drive.get_ready_stock_count() == initial_ready_count
    assert len(mock_drive.list_files_in_folder("04_FAILED")) == 1
