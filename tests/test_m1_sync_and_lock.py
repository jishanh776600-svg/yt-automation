"""
Comprehensive Verification Suite for Milestone 1:
- Database Sync & Auxiliary DB persistence (visual_memory.db, short_fingerprints.db)
- WAL checkpoint truncate retry and connection safety
- Canonical alias mirroring (pipeline.db <-> youtube_automation.db)
- DatabaseSyncManager interface compliance
- CloudLockManager fail-closed semantics, 3600s TTL, race tie-breaker, and heartbeat
- CompositeLock coordination and rollback
- DriveVaultEngine extensions (ensure_folder_hierarchy, list_files, upload_raw_content, delete_file, verify_sarah_voice)
- Immutable preservation guard for short_man_2bf89781983b.mp4
- Quarantine invariant enforcement (04_FAILED)
"""
import os
import sys
import json
import time
import sqlite3
import pytest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

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
from core.cloud_lock import (
    CloudLockManager,
    CloudLockError,
    CompositeLock,
    CLOUD_LOCK_DEFAULT_TTL_SEC
)
from engines.drive_engine import DriveVaultEngine, is_valid_ready_short


def _create_sample_db(path: Path) -> Path:
    """Creates a valid SQLite database with a sample schema and rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test_items (id TEXT PRIMARY KEY, name TEXT);")
    conn.execute("INSERT INTO test_items VALUES ('1', 'Alpha'), ('2', 'Beta');")
    conn.commit()
    conn.close()
    return path


# ==============================================================================
# SECTION 1: DATABASE SYNC & WAL RETRY INTEGRITY
# ==============================================================================

def test_wal_checkpoint_retry_and_connection_safety(tmp_path):
    """Verifies that WAL checkpoint retries on lock contention without NameError and closes connections."""
    db_file = _create_sample_db(tmp_path / "test_wal.db")

    call_count = 0
    real_connect = sqlite3.connect

    def flaky_connect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_connect(*args, **kwargs)

    with patch("sqlite3.connect", side_effect=flaky_connect):
        with patch("time.sleep") as mock_sleep:
            success = flush_wal_checkpoint(db_file, max_attempts=3, base_delay=0.1)
            assert success is True
            assert call_count >= 2
            assert mock_sleep.called


def test_auxiliary_database_cold_start_initialization(tmp_path):
    """Verifies that download_auxiliary_databases initializes clean local tables when not in Drive."""
    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = None

    vm_path = tmp_path / "visual_memory.db"
    sf_path = tmp_path / "short_fingerprints.db"

    test_aux_config = {
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

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux_config):
        results = download_auxiliary_databases(drive_engine=mock_drive)

        assert "visual_memory" in results
        assert "short_fingerprints" in results
        assert vm_path.exists()
        assert sf_path.exists()

        is_vm_valid, _ = verify_sqlite_integrity(vm_path)
        is_sf_valid, _ = verify_sqlite_integrity(sf_path)
        assert is_vm_valid is True
        assert is_sf_valid is True

        conn_vm = sqlite3.connect(str(vm_path))
        cursor_vm = conn_vm.cursor()
        cursor_vm.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='visual_asset_memory';")
        assert cursor_vm.fetchone() is not None
        conn_vm.close()


def test_auxiliary_database_download_from_drive(tmp_path):
    """Verifies that existing auxiliary databases are downloaded and integrity verified."""
    remote_vm = _create_sample_db(tmp_path / "remote_vm.db")
    local_vm = tmp_path / "local_vm.db"

    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = {"id": "vm_file_123", "name": "visual_memory.db"}

    def mock_download(local_dest_path, filename):
        import shutil
        shutil.copy2(remote_vm, local_dest_path)
        return local_dest_path

    mock_drive.download_database.side_effect = mock_download

    test_aux = {
        "visual_memory": {
            "filename": "visual_memory.db",
            "local_path": local_vm,
            "table": "test_items",
            "init_sql": "CREATE TABLE test_items (id TEXT PRIMARY KEY);"
        }
    }

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux):
        results = download_auxiliary_databases(drive_engine=mock_drive, aux_keys=["visual_memory"])
        assert local_vm.exists()
        assert results["visual_memory"] == local_vm

        is_valid, _ = verify_sqlite_integrity(local_vm)
        assert is_valid is True


def test_auxiliary_database_corrupt_download_rejected(tmp_path):
    """Verifies that corrupt auxiliary database download fails closed without corrupting local file."""
    local_vm = _create_sample_db(tmp_path / "local_vm.db")

    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = {"id": "vm_file_123", "name": "visual_memory.db"}

    def mock_corrupt_dl(local_dest_path, filename):
        local_dest_path.write_bytes(b"CORRUPT_NOT_SQLITE_GARBAGE" * 200)
        return local_dest_path

    mock_drive.download_database.side_effect = mock_corrupt_dl

    test_aux = {
        "visual_memory": {
            "filename": "visual_memory.db",
            "local_path": local_vm,
            "table": "test_items",
            "init_sql": "CREATE TABLE test_items (id TEXT PRIMARY KEY);"
        }
    }

    with patch("core.database_sync.AUXILIARY_DATABASES", test_aux):
        with pytest.raises(ValueError, match="integrity check"):
            download_auxiliary_databases(drive_engine=mock_drive, aux_keys=["visual_memory"])

    # Local file must remain intact and valid
    is_valid, _ = verify_sqlite_integrity(local_vm)
    assert is_valid is True


def test_canonical_and_alias_database_sync(tmp_path):
    """Verifies that canonical pipeline.db synchronizes bidirectionally with youtube_automation.db."""
    canonical_db = _create_sample_db(tmp_path / "pipeline.db")
    alias_path = sync_canonical_alias(canonical_db)

    assert alias_path is not None
    assert alias_path.exists()
    assert alias_path.name == "youtube_automation.db"

    # Verify alias has exact table contents
    conn = sqlite3.connect(str(alias_path))
    count = conn.execute("SELECT COUNT(*) FROM test_items;").fetchone()[0]
    conn.close()
    assert count == 2


def test_database_sync_manager_interface_contracts(tmp_path):
    """Verifies that DatabaseSyncManager implements the PROJECT.md interface contract."""
    canonical_db = _create_sample_db(tmp_path / "pipeline.db")
    mock_drive = MagicMock(spec=DriveVaultEngine)
    mock_drive.find_file_in_folder.return_value = {"id": "drive_pipeline_id", "name": "pipeline.db"}

    def mock_dl(local_dest_path, filename="pipeline.db"):
        import shutil
        shutil.copy2(canonical_db, local_dest_path)
        return local_dest_path

    mock_drive.download_database.side_effect = mock_dl
    mock_drive.upload_database.return_value = {"id": "uploaded_id", "name": "pipeline.db"}

    manager = DatabaseSyncManager(drive_engine=mock_drive, canonical_path=canonical_db)

    # 1. download_database() -> Path
    downloaded_path = manager.download_database(canonical_only=True)
    assert isinstance(downloaded_path, Path)
    assert downloaded_path.exists()

    # 2. upload_database() -> bool
    upload_success = manager.upload_database(canonical_only=True)
    assert upload_success is True

    # 3. flush_wal() -> bool
    assert manager.flush_wal() is True

    # 4. verify_integrity() -> Tuple[bool, str]
    valid, msg = manager.verify_integrity()
    assert valid is True
    assert msg == "ok"


# ==============================================================================
# SECTION 2: ATOMIC CLOUD LOCKING & SECURITY
# ==============================================================================

def test_cloud_lock_fail_closed_on_drive_exception():
    """Security Invariant: CloudLockManager fails closed (returns False) on any Drive exception."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.side_effect = ConnectionError("Drive API Rate Limit 429")

    lock = CloudLockManager(drive_engine=mock_drive, run_id="test_run_fail_closed")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False


def test_cloud_lock_active_lock_blocks_acquisition():
    """Concurrency Invariant: Active cloud lock within TTL blocks another runner."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "folder_system_id"}

    now_ts = time.time()
    mock_drive.list_files.return_value = [
        {
            "id": "existing_lock_file_123",
            "name": "cloud_production.lock",
            "properties": {
                "run_id": "other_runner_active",
                "timestamp": str(now_ts - 120.0)  # 2 minutes old < 3600s TTL
            }
        }
    ]

    lock = CloudLockManager(drive_engine=mock_drive, run_id="current_runner")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    mock_drive.upload_raw_content.assert_not_called()


def test_cloud_lock_stale_lock_is_broken():
    """Self-Healing Invariant: Stale cloud lock (> TTL 3600s) is deleted and reacquired."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "folder_system_id"}

    now_ts = time.time()
    stale_file = {
        "id": "stale_lock_file_999",
        "name": "cloud_production.lock",
        "properties": {
            "run_id": "crashed_runner",
            "timestamp": str(now_ts - 4000.0)  # > 3600s TTL
        }
    }

    # Initial scan finds stale lock, post-upload scan finds only our new file
    mock_drive.list_files.side_effect = [
        [stale_file],
        [{"id": "new_lock_file_111", "name": "cloud_production.lock", "createdTime": "2026-09-05T15:00:00Z"}]
    ]
    mock_drive.upload_raw_content.return_value = "new_lock_file_111"

    lock = CloudLockManager(drive_engine=mock_drive, run_id="new_runner")
    acquired = lock.acquire()

    assert acquired is True
    assert lock._acquired is True
    mock_drive.delete_file.assert_any_call("stale_lock_file_999")
    lock.release()


def test_cloud_lock_atomic_consensus_tie_breaker():
    """Consensus Invariant: If two runners upload simultaneously, loser relinquishes and fails closed."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "folder_system_id"}

    our_file_id = "file_runner_b"
    mock_drive.upload_raw_content.return_value = our_file_id

    # Post-upload scan reveals two lock files: runner A created earlier than runner B
    mock_drive.list_files.side_effect = [
        [],  # initial check: no lock
        [    # post-upload tie-break query:
            {"id": "file_runner_a", "name": "cloud_production.lock", "createdTime": "2026-09-05T15:00:01Z"},
            {"id": "file_runner_b", "name": "cloud_production.lock", "createdTime": "2026-09-05T15:00:02Z"}
        ]
    ]

    lock = CloudLockManager(drive_engine=mock_drive, run_id="runner_b")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    # Runner B must have deleted its own file upon losing consensus
    mock_drive.delete_file.assert_called_with(our_file_id)


def test_composite_lock_rollback_on_cloud_failure():
    """Atomicity Invariant: If distributed cloud lock fails, local process lock is rolled back immediately."""
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.side_effect = RuntimeError("Drive network outage")

    lock = CompositeLock(
        name="test_composite",
        command_name="test-op",
        drive_engine=mock_drive
    )

    acquired = lock.acquire()
    assert acquired is False
    assert lock._process_acquired is False
    assert lock._cloud_acquired is False

    # Check local process lock was released (can be acquired by another instance)
    second_lock = CompositeLock(
        name="test_composite",
        command_name="test-op-2",
        drive_engine=None  # Drive=None succeeds
    )
    assert second_lock.acquire() is True
    second_lock.release()


# ==============================================================================
# SECTION 3: VAULT PRESERVATION & QUARANTINE INVARIANTS
# ==============================================================================

def test_immutable_preservation_guard_on_preserved_sarah_short():
    """State Invariant: short_man_2bf89781983b.mp4 cannot be moved to 04_FAILED or deleted."""
    engine = DriveVaultEngine()

    # 1. Blocking move to 04_FAILED
    with pytest.raises(PermissionError, match="immutable vault policy"):
        engine.move_file_in_vault(
            file_id="local_short_man_2bf89781983b.mp4",
            from_folder="01_READY",
            to_folder="04_FAILED"
        )

    # 2. Blocking move via Drive ID
    with pytest.raises(PermissionError, match="immutable vault policy"):
        engine.move_file_in_vault(
            file_id="1AEupCriasKzBItqGdOfR3DtjFWMys0_-",
            from_folder="01_READY",
            to_folder="04_FAILED"
        )

    # 3. Blocking delete
    with pytest.raises(PermissionError, match="immutable vault policy"):
        engine.delete_file("local_short_man_2bf89781983b.mp4")


def test_drive_vault_engine_methods_implemented():
    """Interface Invariant: DriveVaultEngine implements all five required methods."""
    engine = DriveVaultEngine()

    assert hasattr(engine, "ensure_folder_hierarchy")
    assert hasattr(engine, "list_files")
    assert hasattr(engine, "upload_raw_content")
    assert hasattr(engine, "delete_file")
    assert hasattr(engine, "verify_sarah_voice")

    # Verify verify_sarah_voice accepts af_sarah and rejects other voices
    sarah_item = {"properties": {"voice": "af_sarah"}}
    bella_item = {"properties": {"voice": "af_bella"}}

    is_sarah, _ = engine.verify_sarah_voice(sarah_item)
    is_bella, reason_bella = engine.verify_sarah_voice(bella_item)

    assert is_sarah is True
    assert is_bella is False
    assert "af_sarah required" in reason_bella


def test_main_entry_points_configured_with_composite_locking():
    """Verification that main.py functions employ CompositeLock for cross-cloud safety."""
    import inspect
    from main import ShortsPipeline

    pipeline_src = inspect.getsource(ShortsPipeline.produce_batch)
    assert "CompositeLock" in pipeline_src

    sched_src = inspect.getsource(ShortsPipeline.schedule_ready_buffer)
    assert "CompositeLock" in sched_src

    job_src = inspect.getsource(ShortsPipeline.run_single_job)
    assert "CompositeLock" in job_src
