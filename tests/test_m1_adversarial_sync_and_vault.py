"""
Adversarial Stress & State Invariant Verification Suite for Milestone 1.
Authored by challenger_m1_2 (Empirical Challenger).

Empirical Test Probes:
1. WAL Contention, Retry Loop, & Checkpoint Cleanup:
   - Simulated lock contention invokes retry loop without NameError
   - PRAGMA wal_checkpoint busy retry loop recovers cleanly
   - Unreleased lock exhausts retries -> connection closed safely, no crash
   - WAL log truncation and integrity check with live database
2. Auxiliary Databases Synchronization:
   - Registry and schema invariants for visual_memory.db and short_fingerprints.db
   - Cold-start bootstrap of clean schemas locally
   - Download from Drive 00_SYSTEM/ and atomic safe replacement
   - Corrupted remote aux DB rejection (preserves valid local)
   - Corrupted local aux DB upload blocked (prevents cloud contamination)
   - DatabaseSyncManager canonical_only flag compliance and stats
3. Preserved Sarah Short (short_man_2bf89781983b.mp4):
   - Deletion strictly blocked with PermissionError (local, ID, path variants)
   - Move to 04_FAILED strictly blocked with PermissionError
   - Unprotected files can still be deleted/quarantined (no false positive lock)
4. Publication Safety Gate Quarantine in main.py:
   - Failed safety gate quarantines video to 04_FAILED
   - Failed safety gate never returns video to 01_READY
   - Parametric verification across distinct failure modes
   - Contrast with transient upload error preservation in 01_READY
"""
import os
import sys
import time
import json
import uuid
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
import pytest

from config.settings import PROJECT_ROOT, DATABASE_DIR
from core.database_sync import (
    DatabaseSyncManager,
    download_canonical_database,
    upload_canonical_database,
    download_auxiliary_databases,
    upload_auxiliary_databases,
    verify_sqlite_integrity,
    compute_sha256,
    flush_wal_checkpoint,
    sync_canonical_alias,
    AUXILIARY_DATABASES,
    CANONICAL_DB_FILENAME,
    CANONICAL_VAULT_FOLDER
)
from engines.drive_engine import DriveVaultEngine


# ==============================================================================
# HELPERS
# ==============================================================================

def _init_wal_db(path: Path) -> Path:
    """Creates an SQLite database in WAL mode with test data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("CREATE TABLE test_data (id INTEGER PRIMARY KEY, payload TEXT);")
    conn.execute("INSERT INTO test_data (payload) VALUES ('initial');")
    conn.commit()
    conn.close()
    return path


# ==============================================================================
# PROBE SET 1: WAL CONTENTION, RETRY LOOP, AND CHECKPOINT HANDLING
# ==============================================================================

def test_wal_checkpoint_retry_loop_without_name_error(tmp_path):
    """
    WAL RETRY & NAMEERROR PROBE:
    Verify that when sqlite3.connect or PRAGMA wal_checkpoint encounters lock
    contention, the retry loop executes without raising NameError (confirming
    time.sleep is resolved).
    """
    db_file = _init_wal_db(tmp_path / "test_retry_no_nameerror.db")

    call_count = 0
    real_connect = sqlite3.connect

    def locked_then_success(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    with patch("sqlite3.connect", side_effect=locked_then_success):
        with patch("time.sleep") as mock_sleep:
            success = flush_wal_checkpoint(db_file, max_attempts=4, base_delay=0.05)
            assert success is True
            assert call_count == 3
            # Ensure time.sleep was invoked twice without NameError
            assert mock_sleep.call_count == 2
            mock_sleep.assert_has_calls([call(0.05), call(0.1)])


def test_wal_checkpoint_recovers_when_busy_clears(tmp_path):
    """
    PRAGMA WAL_CHECKPOINT BUSY RECOVERY PROBE:
    Simulates PRAGMA wal_checkpoint(TRUNCATE) returning busy=1 (pages blocked)
    on attempt 1 and 2, but clearing to busy=0 on attempt 3.
    Verifies retry loop executes, backoff occurs, and returns True.
    """
    db_file = _init_wal_db(tmp_path / "test_busy_recovery.db")

    checkpoint_attempts = 0

    class MockCursor:
        def execute(self, sql):
            pass
        def fetchone(self):
            nonlocal checkpoint_attempts
            checkpoint_attempts += 1
            if checkpoint_attempts < 3:
                # SQLite PRAGMA wal_checkpoint returns (busy, log, checkpointed)
                return (1, 20, 5)  # busy == 1
            return (0, 0, 25)      # busy == 0
        def close(self):
            pass

    class MockConn:
        def cursor(self):
            return MockCursor()
        def commit(self):
            pass
        def close(self):
            pass

    with patch("sqlite3.connect", return_value=MockConn()):
        with patch("time.sleep") as mock_sleep:
            success = flush_wal_checkpoint(db_file, max_attempts=4, base_delay=0.01)
            assert success is True
            assert checkpoint_attempts == 3
            assert mock_sleep.call_count == 2


def test_wal_checkpoint_unreleased_lock_exhausts_retries_safely(tmp_path):
    """
    PERSISTENT LOCK EXHAUSTION PROBE:
    When an exclusive lock is permanently held, flush_wal_checkpoint exhausts
    max_attempts, safely closes its own connection in finally, and returns False
    without hanging or throwing an uncaught exception.
    """
    db_file = _init_wal_db(tmp_path / "test_permanent_lock.db")

    # Mock cursor to report busy=(1, 10, 5)
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (1, 10, 5)  # busy == 1
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    # Simulate non-empty WAL file
    wal_file = tmp_path / "test_permanent_lock.db-wal"
    wal_file.write_bytes(b"non-empty-wal-bytes")

    with patch("sqlite3.connect", return_value=mock_conn):
        with patch("time.sleep") as mock_sleep:
            success = flush_wal_checkpoint(db_file, max_attempts=3, base_delay=0.01)
            assert success is False
            assert mock_conn.close.call_count == 3
            assert mock_sleep.call_count == 2


def test_wal_checkpoint_cleanly_truncates_live_wal(tmp_path):
    """
    WAL TRUNCATION & PAGE MERGE PROBE:
    Verifies that flush_wal_checkpoint merges uncommitted/dirty WAL pages
    and leaves the database fully consistent and queryable.
    """
    db_file = _init_wal_db(tmp_path / "test_wal_truncate.db")

    # Keep a reader connection open to prevent automatic passive checkpoint on close
    holder = sqlite3.connect(str(db_file))
    holder.execute("PRAGMA query_only = ON;")

    writer = sqlite3.connect(str(db_file))
    for i in range(50):
        writer.execute("INSERT INTO test_data (payload) VALUES (?)", (f"payload_{i}",))
    writer.commit()
    writer.close()

    wal_file = tmp_path / "test_wal_truncate.db-wal"
    # Even if WAL is on disk, checkpoint merges it cleanly
    success = flush_wal_checkpoint(db_file, max_attempts=3, base_delay=0.01)
    assert success is True

    holder.close()

    # Verify all 51 rows are queryable
    verify_conn = sqlite3.connect(str(db_file))
    count = verify_conn.execute("SELECT COUNT(*) FROM test_data;").fetchone()[0]
    verify_conn.close()
    assert count == 51


def test_database_sync_manager_flush_wal_interface(tmp_path):
    """Verifies DatabaseSyncManager.flush_wal delegates to flush_wal_checkpoint."""
    db_file = _init_wal_db(tmp_path / "test_dsm_wal.db")
    mgr = DatabaseSyncManager(canonical_path=db_file)
    assert mgr.flush_wal() is True


# ==============================================================================
# PROBE SET 2: AUXILIARY DATABASES SYNCHRONIZATION (visual_memory & short_fingerprints)
# ==============================================================================

def test_auxiliary_databases_registry_contract():
    """
    SCHEMA CONTRACT INVARIANT:
    AUXILIARY_DATABASES must contain visual_memory and short_fingerprints with
    valid filename, local_path, table name, and SQL DDL.
    """
    assert "visual_memory" in AUXILIARY_DATABASES
    assert "short_fingerprints" in AUXILIARY_DATABASES

    vm = AUXILIARY_DATABASES["visual_memory"]
    assert vm["filename"] == "visual_memory.db"
    assert vm["table"] == "visual_asset_memory"
    assert "CREATE TABLE IF NOT EXISTS visual_asset_memory" in vm["init_sql"]

    sf = AUXILIARY_DATABASES["short_fingerprints"]
    assert sf["filename"] == "short_fingerprints.db"
    assert sf["table"] == "short_fingerprints"
    assert "CREATE TABLE IF NOT EXISTS short_fingerprints" in sf["init_sql"]


def test_auxiliary_database_cold_start_bootstrapping(tmp_path):
    """
    COLD-START BOOTSTRAP PROBE:
    When neither Drive nor local disk has auxiliary databases, clean schemas
    are created locally with all expected tables and indexes.
    """
    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = None

    vm_path = tmp_path / "visual_memory.db"
    sf_path = tmp_path / "short_fingerprints.db"

    test_aux_cfg = {
        "visual_memory": {
            "filename": "visual_memory.db",
            "local_path": vm_path,
            "table": "visual_asset_memory",
            "init_sql": AUXILIARY_DATABASES["visual_memory"]["init_sql"]
        },
        "short_fingerprints": {
            "filename": "short_fingerprints.db",
            "local_path": sf_path,
            "table": "short_fingerprints",
            "init_sql": AUXILIARY_DATABASES["short_fingerprints"]["init_sql"]
        }
    }

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux_cfg):
        results = download_auxiliary_databases(drive_engine=mock_drive)

        assert "visual_memory" in results
        assert "short_fingerprints" in results
        assert vm_path.exists()
        assert sf_path.exists()

        # Check visual_memory schema
        vm_conn = sqlite3.connect(str(vm_path))
        vm_cols = [c[1] for c in vm_conn.execute("PRAGMA table_info(visual_asset_memory);").fetchall()]
        vm_conn.close()
        assert "asset_id" in vm_cols
        assert "perceptual_hash" in vm_cols

        # Check short_fingerprints schema
        sf_conn = sqlite3.connect(str(sf_path))
        sf_cols = [c[1] for c in sf_conn.execute("PRAGMA table_info(short_fingerprints);").fetchall()]
        sf_conn.close()
        assert "short_id" in sf_cols
        assert "fingerprint_hash" in sf_cols


def test_auxiliary_database_corrupted_download_preserves_valid_local(tmp_path):
    """
    ATOMIC SAFE REPLACEMENT PROBE:
    If a downloaded auxiliary DB from Drive fails SQLite integrity, download
    must raise ValueError and MUST NOT overwrite or delete the existing valid local DB.
    """
    vm_path = tmp_path / "visual_memory.db"
    conn = sqlite3.connect(str(vm_path))
    conn.execute("CREATE TABLE visual_asset_memory (asset_id TEXT PRIMARY KEY);")
    conn.execute("INSERT INTO visual_asset_memory VALUES ('asset_safe_1');")
    conn.commit()
    conn.close()

    # Mock Drive downloading garbage bytes to the temp path
    def download_corrupt_file(local_dest_path, filename):
        Path(local_dest_path).write_bytes(b"GARBAGE_NOT_A_SQLITE_DATABASE_DATA")

    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = {"id": "corrupt_drive_id"}
    mock_drive.download_database.side_effect = download_corrupt_file

    test_aux_cfg = {
        "visual_memory": {
            "filename": "visual_memory.db",
            "local_path": vm_path,
            "table": "visual_asset_memory",
            "init_sql": AUXILIARY_DATABASES["visual_memory"]["init_sql"]
        }
    }

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux_cfg):
        with pytest.raises(ValueError, match="failed integrity check"):
            download_auxiliary_databases(drive_engine=mock_drive, aux_keys=["visual_memory"])

        # Local database must still exist with intact data!
        assert vm_path.exists()
        vm_conn = sqlite3.connect(str(vm_path))
        row = vm_conn.execute("SELECT asset_id FROM visual_asset_memory").fetchone()
        vm_conn.close()
        assert row[0] == "asset_safe_1"


def test_auxiliary_database_corrupted_local_upload_blocked(tmp_path):
    """
    UPLOAD INTEGRITY GUARD PROBE:
    If a local auxiliary database is corrupt before upload, upload_auxiliary_databases
    must raise ValueError and never call DriveVaultEngine.upload_database.
    """
    corrupt_vm_path = tmp_path / "corrupt_visual_memory.db"
    corrupt_vm_path.write_bytes(b"CORRUPTED_DATABASE_BYTES_INVALID_SQLITE")

    mock_drive = MagicMock(spec=DriveVaultEngine)

    test_aux_cfg = {
        "visual_memory": {
            "filename": "visual_memory.db",
            "local_path": corrupt_vm_path,
            "table": "visual_asset_memory",
            "init_sql": AUXILIARY_DATABASES["visual_memory"]["init_sql"]
        }
    }

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux_cfg):
        with pytest.raises(ValueError, match="failed integrity check before upload"):
            upload_auxiliary_databases(drive_engine=mock_drive, aux_keys=["visual_memory"])

        mock_drive.upload_database.assert_not_called()


def test_database_sync_manager_auxiliary_coordination(tmp_path):
    """
    DATABASE SYNC MANAGER CONTRACT PROBE:
    Verify DatabaseSyncManager correctly coordinates both canonical and auxiliary
    databases with canonical_only flag respected.
    """
    canon_db = _init_wal_db(tmp_path / "pipeline.db")
    mock_drive = MagicMock(spec=DriveVaultEngine)

    mgr = DatabaseSyncManager(drive_engine=mock_drive, canonical_path=canon_db)

    # 1. Upload with canonical_only=False invokes upload_auxiliary_databases
    with patch("core.database_sync.upload_canonical_database") as mock_up_canon:
        with patch("core.database_sync.upload_auxiliary_databases") as mock_up_aux:
            res = mgr.upload_database(canonical_only=False)
            assert res is True
            mock_up_canon.assert_called_once()
            mock_up_aux.assert_called_once()

    # 2. Upload with canonical_only=True skips auxiliary
    with patch("core.database_sync.upload_canonical_database") as mock_up_canon:
        with patch("core.database_sync.upload_auxiliary_databases") as mock_up_aux:
            res = mgr.upload_database(canonical_only=True)
            assert res is True
            mock_up_canon.assert_called_once()
            mock_up_not = mock_up_aux
            mock_up_not.assert_not_called()

    # 3. Download with canonical_only=False invokes download_auxiliary_databases
    with patch("core.database_sync.download_canonical_database", return_value=canon_db) as mock_dl_canon:
        with patch("core.database_sync.download_auxiliary_databases") as mock_dl_aux:
            res_path = mgr.download_database(canonical_only=False)
            assert res_path == canon_db
            mock_dl_canon.assert_called_once()
            mock_dl_aux.assert_called_once()

    # 4. Download with canonical_only=True skips auxiliary
    with patch("core.database_sync.download_canonical_database", return_value=canon_db) as mock_dl_canon:
        with patch("core.database_sync.download_auxiliary_databases") as mock_dl_aux:
            res_path = mgr.download_database(canonical_only=True)
            assert res_path == canon_db
            mock_dl_canon.assert_called_once()
            mock_dl_aux.assert_not_called()


# ==============================================================================
# PROBE SET 3: PRESERVED SARAH SHORT (short_man_2bf89781983b.mp4) IMMUTABILITY
# ==============================================================================

@pytest.mark.parametrize("file_id_variant", [
    "short_man_2bf89781983b.mp4",
    "local_short_man_2bf89781983b.mp4",
    "1AEupCriasKzBItqGdOfR3DtjFWMys0_-",
    "local_2bf89781983b.mp4",
    "prefix_short_man_2bf89781983b.mp4",
])
def test_preserved_sarah_short_deletion_strictly_blocked(file_id_variant):
    """
    PRESERVATION INVARIANT:
    Attempts to delete short_man_2bf89781983b.mp4 (by filename, local ID, or Drive ID)
    MUST strictly raise PermissionError.
    """
    engine = DriveVaultEngine()
    with pytest.raises(PermissionError, match="immutable vault policy"):
        engine.delete_file(file_id_variant)


@pytest.mark.parametrize("file_id_variant", [
    "short_man_2bf89781983b.mp4",
    "local_short_man_2bf89781983b.mp4",
    "1AEupCriasKzBItqGdOfR3DtjFWMys0_-",
    "local_2bf89781983b.mp4",
])
def test_preserved_sarah_short_quarantine_to_04_failed_strictly_blocked(file_id_variant):
    """
    PRESERVATION INVARIANT:
    Attempts to move short_man_2bf89781983b.mp4 to 04_FAILED MUST strictly raise PermissionError.
    """
    engine = DriveVaultEngine()
    with pytest.raises(PermissionError, match="immutable vault policy"):
        engine.move_file_in_vault(file_id_variant, from_folder="01_READY", to_folder="04_FAILED")


def test_non_preserved_shorts_can_be_deleted_and_quarantined():
    """
    FALSE POSITIVE GUARD:
    Ordinary non-preserved shorts (e.g. temporary test files) CAN be deleted or
    moved to 04_FAILED without PermissionError.
    """
    engine = DriveVaultEngine()

    # Test file that does NOT match preserved patterns
    test_id = "local_unrelated_failed_short_12345.mp4"

    # Moving an unrelated short to 04_FAILED should not raise PermissionError
    res = engine.move_file_in_vault(test_id, from_folder="01_READY", to_folder="04_FAILED")
    assert res["id"] == test_id
    assert "04_FAILED" in res["parents"]

    # Deleting an unrelated short should succeed without PermissionError
    del_res = engine.delete_file(test_id)
    assert del_res is True


# ==============================================================================
# PROBE SET 4: PUBLICATION SAFETY GATE QUARANTINE IN MAIN.PY
# ==============================================================================

@pytest.mark.parametrize("gate_reason", [
    "Audio QA failure: max pause 0.42s > 0.35s",
    "Video QA failure: dead air ratio 0.22 > 0.18 max",
    "Black frames detected in rendered output",
    "Voice af_bella is not approved voice af_sarah",
    "Render duration 28.2s outside [22.0, 25.0]s range",
])
def test_failed_safety_gate_quarantines_to_04_failed_and_never_returns_to_ready(gate_reason, tmp_path):
    """
    SAFETY GATE QUARANTINE INVARIANT:
    When evaluate_publication_safety_gate fails, main.py MUST:
    1. Move the file to 04_FAILED
    2. NEVER move the file to 01_READY
    3. Return None to abort publication
    """
    from main import ShortsPipeline
    from core.models import Job, RenderOutput
    from core.state_machine import JobState

    pipeline = ShortsPipeline.__new__(ShortsPipeline)
    pipeline.upload_engine = MagicMock()
    pipeline.drive_engine = MagicMock()
    pipeline.experiment_manager = MagicMock()

    # Configure safety gate to reject with specified reason
    pipeline.upload_engine.evaluate_publication_safety_gate.return_value = (False, gate_reason)

    mock_db = MagicMock()
    mock_job = MagicMock(spec=Job)
    mock_job.id = "job_test_quarantine_probe"
    mock_render = MagicMock(spec=RenderOutput)

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 0
    mock_query.filter_by.return_value.first.side_effect = [mock_job, mock_render]

    test_file = {
        "id": "vault_failed_short_xyz",
        "name": "short_job_test_quarantine_probe.mp4",
        "properties": {"job_id": "job_test_quarantine_probe"}
    }

    # Execute _schedule_single_drive_file
    result = pipeline._schedule_single_drive_file(
        db=mock_db,
        target_file=test_file,
        current_folder="02_PROCESSING",
        scheduled_slot=datetime.now(timezone.utc)
    )

    # Invariant 1: Upload must be aborted (returns None)
    assert result is None

    # Invariant 2: File moved to 04_FAILED
    pipeline.drive_engine.move_file_in_vault.assert_any_call(
        "vault_failed_short_xyz",
        from_folder="02_PROCESSING",
        to_folder="04_FAILED"
    )

    # Invariant 3: File was NEVER returned to 01_READY
    for move_call in pipeline.drive_engine.move_file_in_vault.mock_calls:
        args, kwargs = move_call[1], move_call[2]
        to_folder = kwargs.get("to_folder") if "to_folder" in kwargs else (args[2] if len(args) > 2 else None)
        assert to_folder != "01_READY", f"Violation: file returned to 01_READY on safety gate rejection: {move_call}"


def test_transient_api_error_returns_file_to_01_ready_for_retry():
    """
    TRANSIENT ERROR CONTRAST:
    Contrast safety gate quarantine with transient API error:
    Transient YouTube network / quota error preserves the valid video in 01_READY.
    """
    from main import ShortsPipeline
    from core.models import Job, RenderOutput
    from core.state_machine import JobState

    pipeline = ShortsPipeline.__new__(ShortsPipeline)
    pipeline.upload_engine = MagicMock()
    pipeline.drive_engine = MagicMock()
    pipeline.experiment_manager = MagicMock()

    # Safety gate passes!
    pipeline.upload_engine.evaluate_publication_safety_gate.return_value = (True, "All checks passed")
    # But YouTube schedule fails transiently
    pipeline.upload_engine.schedule_short.side_effect = RuntimeError("YouTube API 503 Backend Error")

    mock_db = MagicMock()
    mock_job = MagicMock(spec=Job)
    mock_job.id = "job_transient_retry"
    mock_render = MagicMock(spec=RenderOutput)

    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value.count.return_value = 0
    mock_query.filter_by.return_value.first.side_effect = [mock_job, mock_render]

    test_file = {
        "id": "vault_transient_short_abc",
        "name": "short_job_transient_retry.mp4",
        "properties": {"job_id": "job_transient_retry"}
    }

    result = pipeline._schedule_single_drive_file(
        db=mock_db,
        target_file=test_file,
        current_folder="02_PROCESSING",
        scheduled_slot=datetime.now(timezone.utc)
    )

    assert result is None
    # On transient upload error, preserved in 01_READY
    pipeline.drive_engine.move_file_in_vault.assert_any_call(
        "vault_transient_short_abc",
        from_folder="02_PROCESSING",
        to_folder="01_READY"
    )
    # Never moved to 04_FAILED
    for move_call in pipeline.drive_engine.move_file_in_vault.mock_calls:
        args, kwargs = move_call[1], move_call[2]
        to_folder = kwargs.get("to_folder") if "to_folder" in kwargs else (args[2] if len(args) > 2 else None)
        assert to_folder != "04_FAILED", f"Violation: transient upload error wrongly moved to 04_FAILED: {move_call}"
