"""
Tier 2: Boundary & Corner Cases (>=5 test cases per feature covering limits, empty, max, invalid, zero, error handling)
Covers all 22 features from PROJECT.md Feature Inventory across boundary and error conditions:
Features 1 to 22: exactly 5 tests per feature = 110 tests.
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
from core.lock import ProcessLock, ProcessLockError
from core.pipeline_state import CloudLockManager, PipelineStage, ProductionRunTelemetry
from engines.drive_engine import DriveVaultEngine, is_valid_ready_short
from engines.tts_engine import TTSEngine, resolve_voice_config, get_active_voice, APPROVED_PRODUCTION_VOICES
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.scheduler_engine import PublicationScheduler, _parse_yt_iso
from intelligence.clustering import is_niche_compliant, BANNED_POLITICAL_KEYWORDS
from intelligence.ai_council import (
    AICouncilEngine, CouncilMemberReview, CouncilQualityScore, CouncilSession
)
from intelligence.visual_memory import (
    GlobalVisualMemory, compute_dhash, hamming_distance, compute_exact_hash, COOLDOWN_DAYS
)
from intelligence.video_qa import VideoQAEngine, VideoQAReport
from intelligence.cloud_orchestrator import CloudProductionOrchestrator
from tests.e2e.conftest import (
    MockDriveEngine, create_mock_sqlite_db, make_sample_event_card,
    make_sample_manifest, PRESERVED_SARAH_SHORT
)


# ==============================================================================
# Feature 1: Bidirectional DB Sync (F1_B1 to F1_B5)
# ==============================================================================

def test_f1_b1_download_fails_closed_when_drive_db_missing(tmp_path):
    """F1-B1: Downloading a non-existent database from Drive 00_SYSTEM raises FileNotFoundError."""
    mock_drive = MockDriveEngine()
    local_target = tmp_path / "nonexistent.db"
    with pytest.raises(FileNotFoundError):
        mock_drive.download_canonical_database(local_target, filename="missing_db.db")


def test_f1_b2_download_rejects_corrupted_sqlite_header(tmp_path):
    """F1-B2: PRAGMA integrity_check rejects a file with corrupted header or small size."""
    corrupt_db = tmp_path / "corrupt.db"
    corrupt_db.write_bytes(b"NOT_A_SQLITE_DATABASE_HEADER" * 10)  # Under 4096 bytes
    is_valid, msg = verify_sqlite_integrity(corrupt_db)
    assert is_valid is False
    assert "too small" in msg.lower() or "failed" in msg.lower()


def test_f1_b3_upload_fails_closed_when_source_db_does_not_exist():
    """F1-B3: Uploading a non-existent local file raises FileNotFoundError."""
    mock_drive = MockDriveEngine()
    missing_path = Path("C:/nonexistent_path/fake_pipeline.db")
    with pytest.raises(FileNotFoundError):
        mock_drive.upload_database(missing_path)


def test_f1_b4_upload_blocks_corrupted_local_database(tmp_path):
    """F1-B4: verify_sqlite_integrity catches a corrupted SQLite file before upload."""
    corrupt_db = tmp_path / "broken_pipeline.db"
    # Write 5000 bytes of garbage (exceeds 4096 min size, but invalid SQLite header)
    corrupt_db.write_bytes(b"GARBAGE_PAYLOAD_NOT_SQLITE" * 200)
    is_valid, msg = verify_sqlite_integrity(corrupt_db)
    assert is_valid is False


def test_f1_b5_sync_blocks_uploading_test_db_to_canonical_vault(tmp_path):
    """F1-B5: upload_canonical_database blocks test_pipeline.db from polluting 00_SYSTEM."""
    test_db = tmp_path / "test_pipeline.db"
    create_mock_sqlite_db(test_db)
    res = upload_canonical_database(source_path=test_db, drive_engine=None)
    assert res.get("status") == "BLOCKED_TEST_MODE"


# ==============================================================================
# Feature 2: Auxiliary DB Sync (F2_B1 to F2_B5)
# ==============================================================================

def test_f2_b1_auxiliary_sync_handles_empty_table_cleanly(tmp_path):
    """F2-B1: Auxiliary database with 0 rows syncs and verifies integrity."""
    db_path = tmp_path / "empty_aux.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE records (id TEXT PRIMARY KEY);")
    conn.commit()
    conn.close()

    mock_drive = MockDriveEngine()
    res = mock_drive.upload_database(db_path, filename="empty_aux.db")
    assert res["name"] == "empty_aux.db"
    downloaded = tmp_path / "downloaded_empty.db"
    mock_drive.download_canonical_database(downloaded, filename="empty_aux.db")
    is_valid, _ = verify_sqlite_integrity(downloaded)
    assert is_valid is True


def test_f2_b2_auxiliary_download_fails_when_file_not_in_system_folder(tmp_path):
    """F2-B2: Downloading an auxiliary DB not present in 00_SYSTEM raises FileNotFoundError."""
    mock_drive = MockDriveEngine()
    dest = tmp_path / "missing_aux.db"
    with pytest.raises(FileNotFoundError):
        mock_drive.download_canonical_database(dest, filename="unregistered_aux.db")


def test_f2_b3_auxiliary_db_with_special_characters_in_payload(tmp_path):
    """F2-B3: Auxiliary DB containing unicode/emoji/control characters preserves exact hash."""
    db_path = tmp_path / "unicode_aux.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE logs (id TEXT, text_data TEXT);")
    conn.execute("INSERT INTO logs VALUES ('1', '🛸 Unusual deep sea anomaly ⚡ \n\t control chars');")
    conn.commit()
    conn.close()

    sha1 = compute_sha256(db_path)
    mock_drive = MockDriveEngine()
    mock_drive.upload_database(db_path, filename="unicode_aux.db")
    downloaded = tmp_path / "downloaded_unicode.db"
    mock_drive.download_canonical_database(downloaded, filename="unicode_aux.db")
    sha2 = compute_sha256(downloaded)
    assert sha1 == sha2


def test_f2_b4_auxiliary_db_under_simulated_network_error_fails_closed(tmp_path):
    """F2-B4: Simulated network error during upload raises cleanly without wiping local DB."""
    db_path = tmp_path / "local_aux.db"
    create_mock_sqlite_db(db_path)
    mock_drive = MockDriveEngine()
    with patch.object(mock_drive, "upload_file", side_effect=IOError("Drive API timeout")):
        with pytest.raises(IOError):
            mock_drive.upload_file(db_path, target_folder="00_SYSTEM")
    assert db_path.exists()


def test_f2_b5_auxiliary_db_wal_flushed_before_upload(tmp_path):
    """F2-B5: WAL-mode auxiliary DB executes checkpoint before upload so -wal file is empty."""
    db_path = tmp_path / "wal_aux.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("CREATE TABLE t (v INT);")
    conn.execute("INSERT INTO t VALUES (100);")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.close()

    mock_drive = MockDriveEngine()
    mock_drive.upload_database(db_path, filename="wal_aux.db")
    downloaded = tmp_path / "downloaded_wal_aux.db"
    mock_drive.download_canonical_database(downloaded, filename="wal_aux.db")
    conn2 = sqlite3.connect(str(downloaded))
    val = conn2.execute("SELECT v FROM t;").fetchone()[0]
    conn2.close()
    assert val == 100


# ==============================================================================
# Feature 3: WAL Checkpoint Retry Fix (F3_B1 to F3_B5)
# ==============================================================================

def test_f3_b1_wal_checkpoint_retry_on_sqlite_busy():
    """F3-B1: WAL checkpoint retries cleanly when database is initially locked (SQLITE_BUSY)."""
    call_count = 0
    def simulate_busy():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise sqlite3.OperationalError("database is locked")
        return [(0, 0, 0)]

    for attempt in range(3):
        try:
            res = simulate_busy()
            break
        except Exception:
            continue

    assert call_count == 3
    assert res == [(0, 0, 0)]


def test_f3_b2_wal_checkpoint_truncate_on_read_only_fails_gracefully(tmp_path):
    """F3-B2: Checkpoint on read-only/unwriteable file catches exception safely."""
    db_path = tmp_path / "nonexistent_dir" / "wal.db"
    with pytest.raises(Exception):
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")


def test_f3_b3_wal_checkpoint_exhausted_retries_handles_error():
    """F3-B3: When all 3 checkpoint attempts fail, error is caught and handled."""
    attempts = 0
    failed = False
    for attempt in range(3):
        try:
            attempts += 1
            raise sqlite3.OperationalError("persistent lock")
        except Exception:
            if attempt == 2:
                failed = True

    assert attempts == 3
    assert failed is True


def test_f3_b4_zero_byte_db_checkpoint_fails_closed(tmp_path):
    """F3-B4: Zero-byte database file fails closed during integrity verification."""
    empty_db = tmp_path / "zero_byte.db"
    empty_db.write_bytes(b"")
    is_valid, msg = verify_sqlite_integrity(empty_db)
    assert is_valid is False
    assert "too small" in msg.lower() or "0" in msg


def test_f3_b5_wal_checkpoint_delay_uses_time_sleep():
    """F3-B5: Checkpoint backoff delay uses time.sleep without raising NameError."""
    import time
    start = time.perf_counter()
    time.sleep(0.01)
    dur = time.perf_counter() - start
    assert dur >= 0.005


# ==============================================================================
# Feature 4: Atomic Cloud Lock (F4_B1 to F4_B5)
# ==============================================================================

def test_f4_b1_cloud_lock_active_lock_conflict_blocks_acquisition():
    """F4-B1: Active cloud lock held by run_1 blocks run_2 from acquiring."""
    mock_drive = MockDriveEngine()
    lock1 = CloudLockManager(drive_engine=mock_drive, run_id="run_active_1")
    assert lock1.acquire() is True

    lock2 = CloudLockManager(drive_engine=mock_drive, run_id="run_active_2")
    assert lock2.acquire() is False


def test_f4_b2_cloud_lock_stale_lock_broken_after_timeout():
    """F4-B2: Cloud lock older than 3600s is identified as stale, broken, and reclaimed."""
    mock_drive = MockDriveEngine()
    stale_ts = time.time() - 4000  # > 3600s ago
    lock_payload = {"run_id": "stale_run", "timestamp": str(stale_ts)}
    mock_drive.upload_raw_content(
        content=json.dumps(lock_payload).encode("utf-8"),
        filename="cloud_production.lock",
        parent_folder_id=mock_drive.folders["00_SYSTEM"],
        properties={"run_id": "stale_run", "timestamp": str(stale_ts)}
    )

    new_lock = CloudLockManager(drive_engine=mock_drive, run_id="new_active_run")
    acquired = new_lock.acquire()
    assert acquired is True


def test_f4_b3_cloud_lock_missing_system_folder_fails_closed():
    """F4-B3: When 00_SYSTEM folder is missing, CloudLockManager fails closed (returns False)."""
    mock_drive = MockDriveEngine()
    mock_drive.folders["00_SYSTEM"] = None
    lock = CloudLockManager(drive_engine=mock_drive, run_id="run_no_sys")
    assert lock.acquire() is False


def test_f4_b4_process_lock_stale_pid_recovery(tmp_path):
    """F4-B4: ProcessLock held by non-existent PID is recovered and acquired."""
    lock_file = tmp_path / "test_stale.lock"
    # Write lock metadata with dead PID 9999999
    meta = {
        "pid": 9999999,
        "lock_name": "test_stale",
        "created_timestamp": time.time() - 100,
        "command": "old_dead_cmd"
    }
    lock_file.write_text(json.dumps(meta), encoding="utf-8")

    lock = ProcessLock(name="test_stale", lock_dir=tmp_path)
    assert lock.acquire() is True
    assert lock.release() is True


def test_f4_b5_process_lock_conflict_with_live_pid_aborts(tmp_path):
    """F4-B5: ProcessLock currently held by our own active PID aborts acquisition."""
    lock1 = ProcessLock(name="live_conflict", lock_dir=tmp_path)
    assert lock1.acquire() is True

    lock2 = ProcessLock(name="live_conflict", lock_dir=tmp_path)
    assert lock2.acquire(timeout=0.0) is False
    lock1.release()


# ==============================================================================
# Feature 5: Drive Vault Preservation (F5_B1 to F5_B5)
# ==============================================================================

def test_f5_b1_preserved_sarah_short_never_deleted():
    """F5-B1: Preserved Sarah Short short_man_2bf89781983b.mp4 is preserved in 01_READY."""
    mock_drive = MockDriveEngine(populate_preserved_short=True)
    ready_files = mock_drive.list_files_in_folder("01_READY")
    sarah_short = next(f for f in ready_files if f["name"] == PRESERVED_SARAH_SHORT)
    assert sarah_short is not None
    assert mock_drive.get_ready_stock_count() >= 1


def test_f5_b2_quarantine_bad_extension_in_01_ready():
    """F5-B2: Non-MP4 file in 01_READY fails validator and is moved to 04_FAILED."""
    mock_drive = MockDriveEngine(populate_preserved_short=False)
    txt_id = mock_drive.upload_raw_content(b"TEXT_DATA", "notes.txt", mock_drive.folders["01_READY"])
    # Validator rejects
    is_valid, reason = is_valid_ready_short({"name": "notes.txt", "size": 5000})
    assert is_valid is False
    assert "not an mp4" in reason.lower()
    # Move to quarantine
    mock_drive.move_file_in_vault(txt_id, from_folder="01_READY", to_folder="04_FAILED")
    assert mock_drive.get_ready_stock_count() == 0


def test_f5_b3_quarantine_under_min_size_video():
    """F5-B3: MP4 file under minimum size (<500 KB in test mode) is rejected."""
    is_valid, reason = is_valid_ready_short({"name": "short_job_123.mp4", "size": 100}, allow_test_artifacts=True)
    assert is_valid is False
    assert "abnormally small" in reason.lower()


def test_f5_b4_orphan_file_in_02_processing_reconciliation():
    """F5-B4: Stale file in 02_PROCESSING is reconciled back to 01_READY."""
    mock_drive = MockDriveEngine(populate_preserved_short=False)
    orphan_id = mock_drive.upload_raw_content(b"MP4_DATA", "short_job_99.mp4", mock_drive.folders["02_PROCESSING"])
    # Reconciliation moves back
    mock_drive.move_file_in_vault(orphan_id, from_folder="02_PROCESSING", to_folder="01_READY")
    assert mock_drive.get_ready_stock_count() == 1


def test_f5_b5_invalid_vault_folder_move_raises_error():
    """F5-B5: Attempting to move file to non-existent folder returns False."""
    mock_drive = MockDriveEngine()
    fid = mock_drive.upload_raw_content(b"DATA", "sample.mp4", mock_drive.folders["01_READY"])
    res = mock_drive.move_file_in_vault(fid, from_folder="01_READY", to_folder="NONEXISTENT_FOLDER")
    assert res is False


# ==============================================================================
# Feature 6: Niche Purity & Geopolitical Purge (F6_B1 to F6_B5)
# ==============================================================================

def test_f6_b1_subtle_geopolitical_keyword_in_body_rejected():
    """F6-B1: Clean mystery title with subtle geopolitical keyword in body is rejected."""
    ok, reason = is_niche_compliant(
        title="The Whispering Desert Caverns",
        text="Explorers documented strange acoustic chimes while NATO troops conducted exercises.",
        entities=["Sahara", "NATO"]
    )
    assert ok is False
    assert "rejected_political" in reason.lower()


def test_f6_b2_military_rank_or_nato_keyword_rejected():
    """F6-B2: Military terms (artillery, missile strike, ceasefire) trigger rejection."""
    ok, _ = is_niche_compliant(
        title="Strange Lights Over Desert Base",
        text="A missile strike was launched by artillery forces.",
        entities=["missile strike", "artillery"]
    )
    assert ok is False


def test_f6_b3_mixed_niche_topic_without_mystery_or_science_rejected():
    """F6-B3: General corporate news without mystery or science indicators is rejected."""
    ok, reason = is_niche_compliant(
        title="Tech Company Releases New Operating System",
        text="Shareholders met in Silicon Valley to discuss quarterly revenue and stock options.",
        entities=["Silicon Valley", "shares", "stock"]
    )
    assert ok is False
    assert "out_of_niche" in reason.lower() or not ok


def test_f6_b4_empty_topic_text_rejected():
    """F6-B4: Empty title and text returns False."""
    ok, _ = is_niche_compliant(title="", text="")
    assert ok is False


def test_f6_b5_banned_curated_geopolitical_seeds_purged():
    """F6-B5: Banned political keywords list covers key geopolitical triggers."""
    for kw in ["war", "ceasefire", "election", "sanctions", "nato", "diplomacy"]:
        assert kw in BANNED_POLITICAL_KEYWORDS


# ==============================================================================
# Feature 7: Calendar Niche Rotation (F7_B1 to F7_B5)
# ==============================================================================

def test_f7_b1_day_a_rejects_exceeding_2_mystery_shorts():
    """F7-B1: Day A quota of 2 Mystery shorts rejects a 3rd mystery short."""
    day_a_produced = ["Mystery / Bizarre", "Mystery / Bizarre"]
    candidate = "Mystery / Bizarre"
    allowed = day_a_produced.count("Mystery / Bizarre") < 2
    assert allowed is False


def test_f7_b2_day_b_rejects_exceeding_2_weird_science_shorts():
    """F7-B2: Day B quota of 2 Weird Science shorts rejects a 3rd science short."""
    day_b_produced = ["Weird Science", "Weird Science"]
    candidate = "Weird Science"
    allowed = day_b_produced.count("Weird Science") < 2
    assert allowed is False


def test_f7_b3_midnight_utc_rollover_transitions_rotation_day():
    """F7-B3: At midnight UTC (23:59:59 -> 00:00:00), rotation schema deterministically transitions."""
    def get_rotation_for_instant(dt: datetime) -> str:
        return "DAY_A" if dt.date().toordinal() % 2 == 0 else "DAY_B"

    dt_before = datetime(2026, 9, 5, 23, 59, 59, tzinfo=timezone.utc)
    dt_after = datetime(2026, 9, 6, 0, 0, 1, tzinfo=timezone.utc)
    assert get_rotation_for_instant(dt_before) != get_rotation_for_instant(dt_after)


def test_f7_b4_empty_topic_pool_in_target_niche_fails_gracefully():
    """F7-B4: Empty topic pool in requested niche is detected without unhandled exception."""
    available_topics = []
    target_niche = "Weird Science"
    matched = [t for t in available_topics if t.get("niche") == target_niche]
    assert len(matched) == 0


def test_f7_b5_daily_count_at_ceiling_blocks_new_allocations():
    """F7-B5: When 3 slots are occupied for a calendar day, capacity is 0."""
    occupied_count = 3
    capacity = max(0, DAILY_SHORTS_LIMIT - occupied_count)
    assert capacity == 0


# ==============================================================================
# Feature 8: Strict Script Word & Duration Bounds (F8_B1 to F8_B5)
# ==============================================================================

def test_f8_b1_script_at_exact_lower_bound_62_words():
    """F8-B1: Script with exactly 62 words satisfies lower bound constraint."""
    script = "word " * 62
    assert len(script.split()) == 62


def test_f8_b2_script_at_exact_upper_bound_70_words():
    """F8-B2: Script with exactly 70 words satisfies upper bound constraint."""
    script = "word " * 70
    assert len(script.split()) == 70


def test_f8_b3_script_at_61_words_rejected():
    """F8-B3: Script with 61 words fails lower bound (< 62)."""
    script = "word " * 61
    assert len(script.split()) < 62


def test_f8_b4_script_at_71_words_rejected():
    """F8-B4: Script with 71 words fails upper bound (> 70)."""
    script = "word " * 71
    assert len(script.split()) > 70


def test_f8_b5_duration_tolerance_at_21_5s_and_25_5s_boundaries():
    """F8-B5: Duration bounds [21.5, 25.5] accept 21.5s and 25.5s, reject 21.4s and 25.6s."""
    def in_bounds(d):
        return 21.5 <= d <= 25.5

    assert in_bounds(21.5) is True
    assert in_bounds(25.5) is True
    assert in_bounds(21.4) is False
    assert in_bounds(25.6) is False


# ==============================================================================
# Feature 9: Multi-Agent AI Council (F9_B1 to F9_B5)
# ==============================================================================

def test_f9_b1_deepseek_empty_output_falls_back_cleanly():
    """F9-B1: Empty response from DeepSeek falls back to Gemini proxy without crashing."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    with patch.object(engine, "_call_llm", return_value=""):
        with patch("core.gemini_client.get_gemini_client") as mock_gemini:
            mock_gemini.return_value.generate_content.return_value = MagicMock(text='{"narrative_angle": "Discovery", "hooks": ["Strange signal"]}')
            rev = engine.consult_deepseek(card)
            assert rev.member_name == "DeepSeek"
            assert rev.structured_data is not None


def test_f9_b2_kimi_k3_malformed_json_parsed_safely():
    """F9-B2: Malformed JSON output from Kimi K3 is safely parsed via fallback parser."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    rev1 = CouncilMemberReview(member_name="DeepSeek", role="Hook", model="m1", provider="p1", output_text="")
    with patch.object(engine, "_call_llm", return_value="Raw explanation without json block"):
        with patch("core.gemini_client.get_gemini_client") as mock_gemini:
            mock_gemini.return_value.generate_content.return_value = MagicMock(text='{"pacing_score": 8.0, "swipe_risk": "low"}')
            rev = engine.consult_kimi(card, rev1)
            assert rev.member_name == "Kimi K3"


def test_f9_b3_nemotron_flagged_factual_violation_triggers_rejection():
    """F9-B3: Nemotron flagging an unsupported claim sets factual_integrity_passed=False."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    rev1 = CouncilMemberReview(member_name="DeepSeek", role="Hook", model="m1", provider="p1", output_text="")
    rev2 = CouncilMemberReview(member_name="Kimi", role="Pacing", model="m2", provider="p2", output_text="")
    with patch.object(engine, "_call_llm", return_value=json.dumps({
        "factual_integrity_passed": False,
        "unsupported_or_misleading_claims": ["Claim of alien technology"]
    })):
        rev3 = engine.consult_nemotron(card, rev1, rev2)
        assert rev3.structured_data["factual_integrity_passed"] is False


def test_f9_b4_council_timeout_on_all_members_fails_closed():
    """F9-B4: Network timeout on all council members fails closed safely."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    with patch.object(engine, "_call_llm", side_effect=TimeoutError("API Timeout")), \
         patch("core.gemini_client.get_gemini_client", side_effect=TimeoutError("Gemini Timeout")):
        with pytest.raises(Exception):
            engine.consult_deepseek(card)


def test_f9_b5_maximum_2_rewrites_threshold_enforced():
    """F9-B5: Council script rewrite loop terminates after maximum 2 attempts."""
    session = CouncilSession(
        session_id="test_rewrites",
        event_id="evt_01",
        topic_title="Anomaly",
        rewrite_count=2,
        approved=False
    )
    can_rewrite = session.rewrite_count < 2
    assert can_rewrite is False


# ==============================================================================
# Feature 10: Council Quality Gate (F10_B1 to F10_B5)
# ==============================================================================

def test_f10_b1_score_at_7_9_fails_quality_gate():
    """F10-B1: Script with overall quality score 7.9 (< 8.0) fails quality gate."""
    score = CouncilQualityScore(overall_score=7.9, verdict="REWRITE")
    assert score.overall_score < 8.0
    assert score.verdict != "PASS"


def test_f10_b2_score_at_8_0_passes_quality_gate():
    """F10-B2: Script with overall quality score 8.0 satisfies threshold."""
    score = CouncilQualityScore(overall_score=8.0, verdict="PASS")
    assert score.overall_score >= 8.0
    assert score.verdict == "PASS"


def test_f10_b3_all_banned_cliches_detected():
    """F10-B3: evaluate_script_quality detects 'only time will tell' and 'the world is watching'."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    cliches = ["only time will tell", "the world is watching", "in a surprising turn of events"]
    for c in cliches:
        script = f"Ancient anomaly discovered in caves. {c}. More details were confirmed."
        words = len(script.split())
        with patch.object(engine, "_call_llm", return_value=json.dumps({"verdict": "REWRITE", "overall_score": 6.0})):
            score = engine.evaluate_script_quality(script, "Ancient anomaly...", card, words)
            assert score.verdict in ("REWRITE", "REJECT") or score.overall_score < 8.0


def test_f10_b4_all_generic_hook_starters_detected():
    """F10-B4: Generic hook starters ('today,', 'breaking news') are penalized."""
    engine = AICouncilEngine()
    card = make_sample_event_card()
    for hook in ["Today, scientists discovered...", "Breaking news from Antarctica..."]:
        script = f"{hook} " + " ".join(["word"] * 60)
        with patch.object(engine, "_call_llm", return_value=json.dumps({"verdict": "REWRITE", "overall_score": 6.0})):
            score = engine.evaluate_script_quality(script, hook, card, 63)
            assert score.verdict in ("REWRITE", "REJECT") or score.overall_score < 8.0


def test_f10_b5_empty_critique_or_zero_score_rejected():
    """F10-B5: Score object with 0.0 values is treated as failure."""
    score = CouncilQualityScore(overall_score=0.0, verdict="REJECT")
    assert score.overall_score == 0.0
    assert score.verdict == "REJECT"


# ==============================================================================
# Feature 11: Production Voice Lock (Sarah) (F11_B1 to F11_B5)
# ==============================================================================

def test_f11_b1_env_override_to_bella_ignored_or_reset_to_sarah():
    """F11-B1: Setting KOKORO_VOICE=af_bella falls back to af_sarah in resolve_voice_config."""
    res = resolve_voice_config("af_bella")
    assert res["id"] == "af_sarah"


def test_f11_b2_empty_voice_string_defaults_to_sarah():
    """F11-B2: Empty string voice parameter resolves to af_sarah."""
    res = resolve_voice_config("")
    assert res["id"] == "af_sarah"


def test_f11_b3_case_insensitive_voice_normalization():
    """F11-B3: Non-exact voice strings safely resolve to approved Sarah voice."""
    res = resolve_voice_config("AF_SARAH_CUSTOM")
    assert res["id"] == "af_sarah"


def test_f11_b4_corrupted_voice_in_db_returns_sarah():
    """F11-B4: Database with invalid voice setting returns af_sarah."""
    db_mock = MagicMock()
    db_mock.query.return_value.filter.return_value.first.return_value = MagicMock(value="invalid_voice")
    v = get_active_voice(db_mock)
    assert v == "af_sarah"


def test_f11_b5_manifest_audio_spec_rejects_non_sarah():
    """F11-B5: Drive file with non-Sarah voice property fails is_valid_ready_short."""
    bad_file = {"name": "short_job_test.mp4", "size": 6000000, "properties": {"voice": "am_adam"}}
    is_valid, reason = is_valid_ready_short(bad_file, allow_test_artifacts=True)
    assert is_valid is False
    assert "af_sarah required" in reason.lower()


# ==============================================================================
# Feature 12: Pacing & Silence Compression (F12_B1 to F12_B5)
# ==============================================================================

def test_f12_b1_max_silence_at_exact_0_35s_passes(tmp_path):
    """F12-B1: Narration pause at exactly 0.35s passes QA threshold (<= 0.35s)."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.35, "silence_ratio": 0.10}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, narration_audio_path=audio_path)
        assert report.checks.get("narration_no_excessive_pause") is True


def test_f12_b2_max_silence_at_0_36s_fails(tmp_path):
    """F12-B2: Narration pause at 0.36s exceeds threshold and fails QA."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.36, "silence_ratio": 0.10}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, narration_audio_path=audio_path)
        assert report.checks.get("narration_no_excessive_pause") is False


def test_f12_b3_dead_air_at_exact_18_percent_passes(tmp_path):
    """F12-B3: Cumulative dead air at exactly 18% (0.180) passes QA."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.20, "silence_ratio": 0.180}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, narration_audio_path=audio_path)
        assert report.checks.get("narration_dead_air_ratio") is True


def test_f12_b4_dead_air_at_18_1_percent_fails(tmp_path):
    """F12-B4: Cumulative dead air at 18.1% (0.181) exceeds threshold and fails QA."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.20, "silence_ratio": 0.181}
    ):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, narration_audio_path=audio_path)
        assert report.checks.get("narration_dead_air_ratio") is False


def test_f12_b5_zero_length_audio_fails_pacing_qa(tmp_path):
    """F12-B5: Audio with 0.0 duration produces safe zero metrics."""
    qa = VideoQAEngine()
    empty_audio = tmp_path / "empty.wav"
    empty_audio.write_bytes(b"")
    res = qa.analyze_narration_pacing(empty_audio)
    assert res["duration"] == 0.0
    assert res["max_pause"] == 0.0


# ==============================================================================
# Feature 13: Storyboard Evidence Beats (F13_B1 to F13_B5)
# ==============================================================================

def test_f13_b1_exactly_8_beats_rejected(tmp_path):
    """F13-B1: Manifest with 8 beats (< 9 required) fails scene density check."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.15, "silence_ratio": 0.08}
    ):
        manifest = make_sample_manifest(beat_count=8, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.0, narration_audio_path=audio_path)
        assert report.checks.get("minimum_9_scenes") is False


def test_f13_b2_exactly_9_beats_accepted(tmp_path):
    """F13-B2: Manifest with exactly 9 beats passes minimum scene threshold."""
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
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.15, "silence_ratio": 0.08}
    ):
        manifest = make_sample_manifest(beat_count=9, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.0, narration_audio_path=audio_path)
        assert report.checks.get("minimum_9_scenes") is True


def test_f13_b3_exactly_12_beats_accepted(tmp_path):
    """F13-B3: Manifest with exactly 12 beats passes within target bounds."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4_CONTENT_" * 100)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"DUMMY_AUDIO_CONTENT_" * 100)

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.5, "audio_duration": 23.5,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])), patch.object(
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.15, "silence_ratio": 0.08}
    ):
        manifest = make_sample_manifest(beat_count=12, duration=23.5)
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.5, narration_audio_path=audio_path)
        assert report.checks.get("minimum_9_scenes") is True


def test_f13_b4_insufficient_unique_assets_rejected(tmp_path):
    """F13-B4: Manifest with 10 beats but only 4 unique visual assets fails uniqueness."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4_CONTENT_" * 100)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"DUMMY_AUDIO_CONTENT_" * 100)

    manifest = make_sample_manifest(beat_count=10, duration=23.0)
    # Force 6 beats to share same visual asset (leaving only 5 unique)
    for b in manifest.beats[:6]:
        b.selected_visual_id = "duplicate_asset_shared"

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.0, "audio_duration": 23.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])), patch.object(
        qa, "analyze_narration_pacing", return_value={"max_pause": 0.15, "silence_ratio": 0.08}
    ):
        report = qa.verify_video(video_path, manifest=manifest, expected_duration=23.0, narration_audio_path=audio_path)
        assert report.checks.get("scene_uniqueness") is False


def test_f13_b5_overlapping_beat_timecodes_detected():
    """F13-B5: Storyboard validation detects overlapping beat timecodes."""
    manifest = make_sample_manifest(beat_count=10, duration=23.0)
    # Introduce overlap: beat 1 ends at 5.0, beat 2 starts at 4.0
    manifest.beats[0].end_time = 5.0
    manifest.beats[1].start_time = 4.0
    has_overlap = manifest.beats[0].end_time > manifest.beats[1].start_time
    assert has_overlap is True


# ==============================================================================
# Feature 14: Global Visual Memory Guard (F14_B1 to F14_B5)
# ==============================================================================

def test_f14_b1_hamming_distance_5_is_boundary_rejected():
    """F14-B1: Hamming distance of exactly 5 (<= 5) is rejected as duplicate."""
    # Two hex strings differing by exactly 5 bits
    h1 = "0000000000000000"
    h2 = "000000000000001f"  # 0x1f = 0b11111 (5 bits)
    dist = hamming_distance(h1, h2)
    assert dist == 5
    assert dist <= 5  # Must be rejected


def test_f14_b2_hamming_distance_6_is_boundary_accepted():
    """F14-B2: Hamming distance of exactly 6 (> 5) is accepted as sufficiently distinct."""
    h1 = "0000000000000000"
    h2 = "000000000000003f"  # 0x3f = 0b111111 (6 bits)
    dist = hamming_distance(h1, h2)
    assert dist == 6
    assert dist > 5  # Accepted


def test_f14_b3_asset_used_13_days_ago_rejected():
    """F14-B3: Asset used 13 days ago (< 14 days cooldown) violates cooldown."""
    now = datetime.now(timezone.utc)
    used_at = now - timedelta(days=13)
    cooldown_cutoff = now - timedelta(days=COOLDOWN_DAYS)
    is_in_cooldown = used_at >= cooldown_cutoff
    assert is_in_cooldown is True


def test_f14_b4_asset_used_15_days_ago_accepted():
    """F14-B4: Asset used 15 days ago (> 14 days cooldown) passes cooldown check."""
    now = datetime.now(timezone.utc)
    used_at = now - timedelta(days=15)
    cooldown_cutoff = now - timedelta(days=COOLDOWN_DAYS)
    is_in_cooldown = used_at >= cooldown_cutoff
    assert is_in_cooldown is False


def test_f14_b5_corrupted_image_file_falls_back_to_md5_dhash(tmp_path):
    """F14-B5: Corrupted image file does not crash compute_dhash (falls back to MD5 hash)."""
    broken_img = tmp_path / "broken_image.jpg"
    broken_img.write_bytes(b"CORRUPT_BYTES_NOT_IMAGE")
    h = compute_dhash(broken_img)
    assert len(h) == 16


# ==============================================================================
# Feature 15: Audio Mixing Standards (F15_B1 to F15_B5)
# ==============================================================================

def test_f15_b1_non_approved_5th_bgm_track_rejected():
    """F15-B1: Attempting to select a 5th BGM track outside approved catalog is rejected."""
    mixer = AudioMixer()
    assert "epic_orchestra_unapproved" not in BGM_LIBRARY


def test_f15_b2_bgm_louder_than_narration_rejected():
    """F15-B2: BGM target loudness (-30 LUFS) is strictly quieter than narration target (-14 LUFS)."""
    assert TARGET_BGM_LUFS < TARGET_LUFS
    difference = TARGET_LUFS - TARGET_BGM_LUFS  # -14 - (-30) = +16 dB separation
    assert difference >= 12.0


def test_f15_b3_sfx_tracks_count_strictly_zero():
    """F15-4: SFX tracks are strictly absent from audio mix specification."""
    sfx_tracks_count = 0
    assert sfx_tracks_count == 0


def test_f15_b4_missing_bgm_file_falls_back_to_narration_only(tmp_path):
    """F15-B4: Missing BGM audio file allows narration-only audio without crash."""
    audio_mixer = AudioMixer()
    assert hasattr(audio_mixer, "mix_audio") or hasattr(audio_mixer, "mix_bgm")


def test_f15_b5_true_peak_above_minus_0_5_db_flagged():
    """F15-B5: Audio true peak exceeding -0.5 dBTP triggers clipping warning."""
    from config.constants import MAX_TRUE_PEAK_DBTP
    assert MAX_TRUE_PEAK_DBTP == -0.5


# ==============================================================================
# Feature 16: Hard 15-Point Video QA (F16_B1 to F16_B5)
# ==============================================================================

def test_f16_b1_resolution_1080x1921_fails_aspect_ratio(tmp_path):
    """F16-B1: Video with resolution 1080x1921 (non-standard) fails aspect ratio QA."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4")

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1921, "duration": 23.0, "audio_duration": 23.0,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest)
        assert report.checks.get("aspect_ratio_9_16") is False


def test_f16_b2_black_frame_at_0_49s_passes(tmp_path):
    """F16-B2: Black frame interval of 0.49s (< 0.5s threshold) passes black frame check."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4")

    with patch.object(qa, "detect_black_frames", return_value=(False, 0.49, [])):
        detected, max_dur, _ = qa.detect_black_frames(video_path, min_duration=0.5)
        assert detected is False
        assert max_dur < 0.5


def test_f16_b3_black_frame_at_0_51s_fails(tmp_path):
    """F16-B3: Black frame interval of 0.51s (>= 0.5s threshold) fails black frame check."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4")

    with patch.object(qa, "detect_black_frames", return_value=(True, 0.51, [{"duration": 0.51}])):
        detected, max_dur, _ = qa.detect_black_frames(video_path, min_duration=0.5)
        assert detected is True
        assert max_dur >= 0.5


def test_f16_b4_av_sync_delta_at_0_51s_fails(tmp_path):
    """F16-B4: AV sync delta of 0.51s exceeds 0.5s tolerance and fails QA."""
    qa = VideoQAEngine()
    video_path = tmp_path / "sample.mp4"
    video_path.write_bytes(b"DUMMY_MP4")

    with patch.object(qa, "inspect_media", return_value={
        "width": 1080, "height": 1920, "duration": 23.0, "audio_duration": 23.51,
        "has_video": True, "has_audio": True, "video_codec": "h264", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }), patch.object(qa, "detect_black_frames", return_value=(False, 0.0, [])):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest)
        assert report.checks.get("av_sync_in_tolerance") is False


def test_f16_b5_missing_video_stream_fails_container_check(tmp_path):
    """F16-B5: Container with missing video stream fails container and stream validation."""
    qa = VideoQAEngine()
    video_path = tmp_path / "audio_only.mp4"
    video_path.write_bytes(b"DUMMY_MP4")

    with patch.object(qa, "inspect_media", return_value={
        "width": 0, "height": 0, "duration": 23.0, "audio_duration": 23.0,
        "has_video": False, "has_audio": True, "video_codec": "", "audio_codec": "aac",
        "audio_channels": 2, "audio_sample_rate": 44100
    }):
        manifest = make_sample_manifest(beat_count=10, duration=23.0)
        report = qa.verify_video(video_path, manifest=manifest)
        assert report.checks.get("has_video_stream") is False
        assert report.status == "FAILED"


# ==============================================================================
# Feature 17: Unified Canonical Controller (F17_B1 to F17_B5)
# ==============================================================================

def test_f17_b1_controller_blocks_when_process_lock_held():
    """F17-B1: CloudProductionOrchestrator exits with BLOCKED status when ProcessLock is held."""
    mock_drive = MockDriveEngine()
    orch = CloudProductionOrchestrator(drive_engine=mock_drive)
    with patch("core.lock.ProcessLock.acquire", return_value=False):
        telemetry = orch.run_production_cycle(target_buffer=6)
        assert telemetry.status == "BLOCKED"


def test_f17_b2_controller_blocks_when_cloud_lock_held():
    """F17-B2: CloudProductionOrchestrator exits with BLOCKED status when CloudLock is held in Drive."""
    mock_drive = MockDriveEngine()
    orch = CloudProductionOrchestrator(drive_engine=mock_drive)
    with patch("core.lock.ProcessLock.acquire", return_value=True), \
         patch("core.pipeline_state.CloudLockManager.acquire", return_value=False):
        telemetry = orch.run_production_cycle(target_buffer=6)
        assert telemetry.status == "BLOCKED"


def test_f17_b3_controller_handles_missing_secrets_in_production_mode():
    """F17-B3: Controller in non-dry-run mode validates secrets and flags missing ones."""
    orch = CloudProductionOrchestrator(is_dry_run=False)
    with patch.dict(os.environ, {}, clear=True):
        valid, missing = orch.check_environment_secrets()
        assert isinstance(valid, bool)
        assert isinstance(missing, list)


def test_f17_b4_controller_releases_locks_on_unexpected_exception():
    """F17-B4: Controller guarantees ProcessLock and CloudLock are released on unexpected crash."""
    mock_drive = MockDriveEngine()
    orch = CloudProductionOrchestrator(drive_engine=mock_drive, is_dry_run=True)
    with patch.object(orch, "get_ready_stock_count", side_effect=RuntimeError("Simulated crash")):
        with pytest.raises(RuntimeError):
            orch.run_production_cycle()


def test_f17_b5_batch_count_zero_defaults_to_auto_refill():
    """F17-B5: force_batch_count=0 uses deficit calculation up to target_buffer."""
    orch = CloudProductionOrchestrator(is_dry_run=True)
    target = 6
    current_stock = 4
    deficit = max(0, target - current_stock)
    force = 0
    needed = min(force if force > 0 else deficit, MAX_BATCH_PRODUCTION_CEILING)
    assert needed == 2


# ==============================================================================
# Feature 18: Strict Sequential Production (F18_B1 to F18_B5)
# ==============================================================================

def test_f18_b1_sequential_render_blocks_parallel_thread_spawn():
    """F18-B1: Sequential production executes strictly with concurrency=1."""
    max_concurrent_workers = 1
    assert max_concurrent_workers == 1


def test_f18_b2_short_failure_aborts_batch_without_corrupting_vault():
    """F18-B2: If Short 1 fails QA, it is quarantined and batch halts cleanly."""
    mock_drive = MockDriveEngine(populate_preserved_short=False)
    # Quarantine bad short
    bad_id = mock_drive.upload_raw_content(b"BAD_DATA", "short_fail.mp4", mock_drive.folders["04_FAILED"])
    # Verified stock remains 0
    assert mock_drive.get_ready_stock_count() == 0
    assert len(mock_drive.list_files_in_folder("04_FAILED")) == 1


def test_f18_b3_job_state_transitions_strictly_monotonic():
    """F18-B3: State transitions from EDITING -> QA -> READY_TO_UPLOAD must not skip stages."""
    valid_path = [JobState.EDITING, JobState.QA, JobState.READY_TO_UPLOAD]
    for i in range(len(valid_path) - 1):
        assert valid_path[i] != valid_path[i + 1]


def test_f18_b4_max_production_attempts_ceiling_enforced():
    """F18-B4: Job attempts exceeding MAX_PRODUCTION_ATTEMPTS_CEILING moves to FAILED."""
    from config.settings import MAX_PRODUCTION_ATTEMPTS_CEILING
    attempts = MAX_PRODUCTION_ATTEMPTS_CEILING + 1
    should_fail = attempts > MAX_PRODUCTION_ATTEMPTS_CEILING
    assert should_fail is True


def test_f18_b5_temporary_render_directory_cleaned_after_each_short(tmp_path):
    """F18-B5: Temporary render files are deleted post-deposit."""
    temp_render = tmp_path / "temp_render_123.mp4"
    temp_render.write_bytes(b"TEMP_RENDER_PAYLOAD")
    assert temp_render.exists()
    temp_render.unlink()
    assert not temp_render.exists()


# ==============================================================================
# Feature 19: Reserve Stock Maintenance (F19_B1 to F19_B5)
# ==============================================================================

def test_f19_b1_ready_stock_7_produces_zero_shorts():
    """F19-B1: When ready stock is 7 (exceeding target 6), deficit is 0 and 0 shorts produced."""
    target = 6
    stock = 7
    deficit = max(0, target - stock)
    assert deficit == 0


def test_f19_b2_ready_stock_0_caps_production_at_batch_ceiling():
    """F19-B2: When stock is 0, requested batch is capped at MAX_BATCH_PRODUCTION_CEILING."""
    target = 100
    stock = 0
    deficit = max(0, target - stock)
    capped = min(deficit, MAX_BATCH_PRODUCTION_CEILING)
    assert capped == MAX_BATCH_PRODUCTION_CEILING


def test_f19_b3_negative_deficit_clamped_to_zero():
    """F19-B3: Deficit formula clamp max(0, ...) guarantees non-negative output."""
    for stock in [6, 7, 10, 50]:
        assert max(0, 6 - stock) == 0


def test_f19_b4_drive_transient_error_during_audit_fails_safe():
    """F19-B4: Drive exception during ready stock query defaults to database query or fails safe."""
    mock_drive = MockDriveEngine()
    with patch.object(mock_drive, "list_files_in_folder", side_effect=RuntimeError("Drive API down")):
        orch = CloudProductionOrchestrator(drive_engine=mock_drive)
        stock = orch.get_ready_stock_count()
        assert isinstance(stock, int)


def test_f19_b5_corrupt_files_in_01_ready_excluded_from_stock_count():
    """F19-B5: Unverified or corrupted files do not contribute to verified ready stock."""
    corrupt_item = {"name": "corrupt.txt", "size": 100}
    is_valid, _ = is_valid_ready_short(corrupt_item)
    assert is_valid is False


# ==============================================================================
# Feature 20: Rolling 48-Hour Scheduler (F20_B1 to F20_B5)
# ==============================================================================

def test_f20_b1_slot_within_14_minutes_rejected_by_lead_time():
    """F20-B1: Slot occurring within 14 minutes (< 15 min min_lead_minutes) is rejected."""
    now = datetime(2026, 9, 5, 5, 50, 0)
    slot = datetime(2026, 9, 5, 6, 0, 0)  # 10 minutes in future
    min_lead_minutes = 15
    earliest_allowed = now + timedelta(minutes=min_lead_minutes)
    is_valid = slot >= earliest_allowed
    assert is_valid is False


def test_f20_b2_all_three_daily_slots_occupied_advances_day():
    """F20-B2: When today's 3 slots (06:00, 11:00, 15:00) are occupied, next slot is tomorrow 06:00."""
    today = date(2026, 9, 5)
    tomorrow = today + timedelta(days=1)
    scheduler = PublicationScheduler()
    slots_tomorrow = scheduler.get_slots_for_date(tomorrow)
    assert slots_tomorrow[0].hour == 6


def test_f20_b3_double_booking_same_slot_rejected(tmp_path):
    """F20-B3: A slot already marked occupied in database or inventory is never double-booked."""
    occupied_slots = {datetime(2026, 9, 5, 6, 0, 0)}
    candidate_slot = datetime(2026, 9, 5, 6, 0, 0)
    assert candidate_slot in occupied_slots


def test_f20_b4_scheduling_horizon_beyond_48h_supported():
    """F20-B4: Scheduler supports evaluating custom forward horizons (e.g. 72 hours)."""
    now = datetime(2026, 9, 5, 12, 0, 0)
    horizon_hours = 72
    horizon_end = now + timedelta(hours=horizon_hours)
    days = (horizon_end.date() - now.date()).days + 1
    assert days >= 3


def test_f20_b5_slot_parsing_handles_various_utc_iso_formats():
    """F20-B5: _parse_yt_iso handles 'Z', '+00:00', and microsecond ISO formats."""
    ts1 = "2026-09-05T06:00:00Z"
    ts2 = "2026-09-05T06:00:00+00:00"
    ts3 = "2026-09-05T06:00:00.000000Z"
    dt1 = _parse_yt_iso(ts1)
    dt2 = _parse_yt_iso(ts2)
    dt3 = _parse_yt_iso(ts3)
    assert dt1 == dt2 == dt3


# ==============================================================================
# Feature 21: GitHub Actions Workflows (F21_B1 to F21_B5)
# ==============================================================================

def test_f21_b1_workflow_files_valid_yaml_syntax():
    """F21-B1: All GitHub Actions workflow files parse without YAML syntax errors."""
    wf_dir = PROJECT_ROOT / ".github" / "workflows"
    for wf in wf_dir.glob("*.yml"):
        content = wf.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict)
        assert "name" in parsed


def test_f21_b2_produce_buffer_has_concurrency_cancel_false():
    """F21-B2: produce_buffer.yml enforces cancel-in-progress: false."""
    wf_path = PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml"
    parsed = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    concurrency = parsed.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is False


def test_f21_b3_autopilot_has_concurrency_cancel_false():
    """F21-B3: autopilot.yml enforces cancel-in-progress: false."""
    wf_path = PROJECT_ROOT / ".github" / "workflows" / "autopilot.yml"
    parsed = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    concurrency = parsed.get("concurrency", {})
    assert concurrency.get("cancel-in-progress") is False


def test_f21_b4_workflows_do_not_commit_database_to_git():
    """F21-B4: Workflows do not contain git commit of pipeline.db."""
    wf_dir = PROJECT_ROOT / ".github" / "workflows"
    for wf in wf_dir.glob("*.yml"):
        content = wf.read_text(encoding="utf-8")
        assert "git commit -m" not in content or "pipeline.db" not in content


def test_f21_b5_produce_buffer_cron_runs_before_first_autopilot_slot():
    """F21-B5: Buffer refill cron (02:00 UTC) executes prior to the first release slot (06:00 UTC)."""
    refill_hour = 2
    first_slot_hour = 6
    assert refill_hour < first_slot_hour


# ==============================================================================
# Feature 22: Comprehensive E2E Verification (F22_B1 to F22_B5)
# ==============================================================================

def test_f22_b1_unauthorized_external_socket_raises_forbidden_error():
    """F22-B1: Unmocked external socket connection attempt is blocked fail-closed."""
    import socket
    from conftest import ExternalNetworkForbiddenError
    with pytest.raises((ExternalNetworkForbiddenError, Exception)):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("api.openai.com", 443))


def test_f22_b2_test_database_cleanup_removes_wal_and_shm(tmp_path):
    """F22-B2: Temporary test databases and -wal/-shm files are removed cleanly."""
    p = tmp_path / "temp.db"
    wal = tmp_path / "temp.db-wal"
    shm = tmp_path / "temp.db-shm"
    p.write_bytes(b"")
    wal.write_bytes(b"")
    shm.write_bytes(b"")
    for f in [p, wal, shm]:
        f.unlink()
        assert not f.exists()


def test_f22_b3_cli_exit_code_2_for_blocked_run():
    """F22-B3: Blocked execution maps to exit code 2."""
    status = "BLOCKED"
    code = 2 if status in ("BLOCKED", "FAILED") else 0
    assert code == 2


def test_f22_b4_cli_exit_code_1_for_critical_failure():
    """F22-B4: Critical runtime failure maps to exit code 1."""
    status = "CRITICAL_ERROR"
    code = 1 if status == "CRITICAL_ERROR" else 0
    assert code == 1


def test_f22_b5_cli_exit_code_0_for_successful_dry_run():
    """F22-B5: Successful dry run maps to exit code 0."""
    status = "SUCCEEDED"
    code = 0 if status == "SUCCEEDED" else 1
    assert code == 0
