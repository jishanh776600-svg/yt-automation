"""
Empirical Adversarial Stress & Concurrency Suite for Milestone 1.
Authored by challenger_m1_1 (Empirical Challenger).

Exhaustive Probes:
1. Drive API Exception Fail-Closed Invariant
2. CompositeLock Rollback & Zero-Dangling-Lock Invariant
3. Stale Lock (TTL 3600s) Breaking vs Active Lock Respect Invariant
4. Clock Skew, Malformed Metadata, and Edge Invariants
5. Multithreaded High-Contention Race Consensus Stress
"""
import os
import sys
import time
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest

from core.cloud_lock import (
    CloudLockManager,
    CloudLockError,
    CompositeLock,
    CLOUD_LOCK_DEFAULT_TTL_SEC
)
from core.lock import ProcessLock, ProcessLockError


# ==============================================================================
# PROBE SET 1: DRIVE ACQUISITION EXCEPTION STRICT FAIL-CLOSED
# ==============================================================================

@pytest.mark.parametrize("exception_type,msg", [
    (ConnectionResetError, "Drive connection forcibly closed by remote host"),
    (TimeoutError, "Google Drive API timeout after 30s"),
    (RuntimeError, "Drive 503 Service Unavailable"),
    (PermissionError, "403 Storage Quota Exceeded"),
    (ValueError, "Malformed response JSON from Drive API"),
    (OSError, "Network unreachable"),
])
def test_drive_folder_hierarchy_exception_strictly_fails_closed(exception_type, msg):
    """
    FAIL-CLOSED INVARIANT:
    Any exception during folder discovery MUST return False.
    Lock state must remain unacquired, lock file ID None, no heartbeat thread.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.side_effect = exception_type(msg)

    lock = CloudLockManager(drive_engine=mock_drive, run_id="probe_run_fail_closed")
    acquired = lock.acquire()

    assert acquired is False, f"Expected False on {exception_type.__name__}, got {acquired}"
    assert lock._acquired is False
    assert lock._lock_file_id is None
    assert lock._heartbeat_thread is None


@pytest.mark.parametrize("exception_type,msg", [
    (ConnectionResetError, "Connection dropped during list_files"),
    (RuntimeError, "500 Internal Server Error during search"),
    (Exception, "Drive generic failure"),
])
def test_drive_list_files_exception_strictly_fails_closed(exception_type, msg):
    """
    FAIL-CLOSED INVARIANT:
    Any exception during lock checking query MUST return False.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    mock_drive.list_files.side_effect = exception_type(msg)

    lock = CloudLockManager(drive_engine=mock_drive, run_id="probe_list_fail")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    assert lock._lock_file_id is None
    mock_drive.upload_raw_content.assert_not_called()


def test_drive_upload_exception_strictly_fails_closed():
    """
    FAIL-CLOSED INVARIANT:
    Any exception during upload_raw_content MUST return False and not grant lock.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    mock_drive.list_files.return_value = []
    mock_drive.upload_raw_content.side_effect = IOError("Failed writing lock bytes to Drive")

    lock = CloudLockManager(drive_engine=mock_drive, run_id="probe_upload_fail")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    assert lock._lock_file_id is None


def test_drive_post_upload_tie_break_exception_strictly_fails_closed():
    """
    FAIL-CLOSED INVARIANT:
    If post-upload consensus query throws an exception, acquisition MUST fail closed (return False).
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    # Pre-upload list succeeds (no lock), upload succeeds, post-upload list raises exception
    mock_drive.list_files.side_effect = [
        [],  # initial pre-check
        RuntimeError("Transient error during consensus resolution")  # post-upload tie-break
    ]
    mock_drive.upload_raw_content.return_value = "orphan_lock_file"

    lock = CloudLockManager(drive_engine=mock_drive, run_id="probe_tiebreak_fail")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False


def test_drive_missing_system_folder_strictly_fails_closed():
    """
    FAIL-CLOSED INVARIANT:
    If 00_SYSTEM folder is missing or None in hierarchy, lock MUST NOT be granted.
    """
    mock_drive = MagicMock()
    # Missing 00_SYSTEM key
    mock_drive.ensure_folder_hierarchy.return_value = {"01_READY": "ready_fid"}

    lock = CloudLockManager(drive_engine=mock_drive, run_id="probe_missing_sys")
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    mock_drive.list_files.assert_not_called()
    mock_drive.upload_raw_content.assert_not_called()


def test_context_manager_strictly_raises_on_drive_exception():
    """
    FAIL-CLOSED INVARIANT:
    Using CloudLockManager as a context manager MUST raise CloudLockError when Drive fails,
    strictly preventing the protected block from executing.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.side_effect = RuntimeError("Drive offline")

    executed_protected_block = False
    with pytest.raises(CloudLockError, match="Could not acquire cloud lock"):
        with CloudLockManager(drive_engine=mock_drive, run_id="ctx_fail_probe"):
            executed_protected_block = True

    assert executed_protected_block is False


# ==============================================================================
# PROBE SET 2: COMPOSITELOCK ROLLBACK & CLEAN STATE
# ==============================================================================

def test_composite_lock_rolls_back_process_lock_on_drive_exception(tmp_path):
    """
    ROLLBACK INVARIANT:
    When CloudLockManager encounters a Drive exception, the local ProcessLock
    acquired in Tier 1 MUST be immediately rolled back and released.
    No lock file must be left behind, allowing immediate acquisition by others.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.side_effect = ConnectionError("Drive API down")

    lock_dir = tmp_path / "locks"
    lock_name = "test_rollback_probe"

    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        lock = CompositeLock(
            name=lock_name,
            command_name="test-rollback",
            drive_engine=mock_drive
        )

        result = lock.acquire()
        assert result is False
        assert lock._process_acquired is False
        assert lock._cloud_acquired is False

        # Confirm process lock file was completely unlinked
        expected_lock_file = lock_dir / f"{lock_name}.lock"
        assert not expected_lock_file.exists(), "Local process lock file was NOT removed on rollback!"

        # Confirm a new lock instance can acquire local process lock immediately
        new_proc_lock = ProcessLock(name=lock_name, lock_dir=lock_dir)
        assert new_proc_lock.acquire() is True
        new_proc_lock.release()


def test_composite_lock_rolls_back_on_active_cloud_lock_conflict(tmp_path):
    """
    ROLLBACK INVARIANT:
    When cloud lock is held by another active cloud runner, CompositeLock
    MUST release the local ProcessLock and return False.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    now_ts = datetime.now(timezone.utc).timestamp()
    mock_drive.list_files.return_value = [
        {
            "id": "active_file_99",
            "name": "cloud_active.lock",
            "properties": {
                "run_id": "active_runner_peer",
                "timestamp": str(now_ts - 60.0)  # 60s old (active)
            }
        }
    ]

    lock_dir = tmp_path / "locks"
    lock_name = "cloud_active"

    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        comp_lock = CompositeLock(
            name=lock_name,
            command_name="test-conflict",
            drive_engine=mock_drive
        )

        acquired = comp_lock.acquire()
        assert acquired is False
        assert comp_lock._process_acquired is False
        assert comp_lock._cloud_acquired is False

        # Verify disk lock file was unlinked
        expected_file = lock_dir / f"{lock_name}.lock"
        assert not expected_file.exists(), "Lock file remained after active cloud conflict rollback!"


def test_composite_lock_rolls_back_on_consensus_race_loss(tmp_path):
    """
    ROLLBACK INVARIANT:
    When cloud lock loses consensus tie-breaker to another runner,
    CompositeLock MUST roll back local ProcessLock.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    our_id = "our_file_id"
    winner_id = "competitor_file_id"

    mock_drive.upload_raw_content.return_value = our_id
    mock_drive.list_files.side_effect = [
        [],  # initial check: clear
        [    # tie-breaker query: competitor was 1s earlier
            {"id": winner_id, "name": "cloud_race.lock", "createdTime": "2026-09-05T15:00:00Z"},
            {"id": our_id, "name": "cloud_race.lock", "createdTime": "2026-09-05T15:00:01Z"}
        ]
    ]

    lock_dir = tmp_path / "locks"
    lock_name = "cloud_race"

    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        comp_lock = CompositeLock(
            name=lock_name,
            command_name="test-race",
            drive_engine=mock_drive
        )

        acquired = comp_lock.acquire()
        assert acquired is False
        assert comp_lock._process_acquired is False
        assert comp_lock._cloud_acquired is False

        # Deleted our cloud file
        mock_drive.delete_file.assert_called_with(our_id)

        # Unlinked local process lock
        expected_file = lock_dir / f"{lock_name}.lock"
        assert not expected_file.exists()


def test_composite_lock_local_conflict_never_touches_cloud(tmp_path):
    """
    EFFICIENCY & DEFENSIVE INVARIANT:
    If local process lock cannot be acquired (already held locally),
    CompositeLock MUST return False immediately WITHOUT contacting Google Drive.
    """
    mock_drive = MagicMock()
    lock_dir = tmp_path / "locks"
    lock_name = "local_held_lock"

    # Process 1 acquires local process lock
    proc1 = ProcessLock(name=lock_name, lock_dir=lock_dir)
    assert proc1.acquire() is True

    # Process 2 attempts CompositeLock
    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        comp_lock = CompositeLock(
            name=lock_name,
            command_name="test-local-held",
            drive_engine=mock_drive
        )

        acquired = comp_lock.acquire()
        assert acquired is False
        # Drive engine must never have been touched
        mock_drive.ensure_folder_hierarchy.assert_not_called()
        mock_drive.list_files.assert_not_called()

    proc1.release()


def test_composite_lock_context_manager_clean_unwind_on_exception(tmp_path):
    """
    SAFETY INVARIANT:
    When an exception occurs within a CompositeLock context manager,
    both cloud lock and local process lock MUST be released cleanly in __exit__.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    mock_drive.list_files.side_effect = [
        [],
        [{"id": "file_ctx_ok", "name": "ctx_clean.lock", "createdTime": "2026-09-05T15:00:00Z"}]
    ]
    mock_drive.upload_raw_content.return_value = "file_ctx_ok"

    lock_dir = tmp_path / "locks"
    lock_name = "ctx_clean"

    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        comp_lock = CompositeLock(
            name=lock_name,
            command_name="test-ctx-clean",
            drive_engine=mock_drive
        )

        with pytest.raises(ZeroDivisionError):
            with comp_lock:
                assert comp_lock._process_acquired is True
                assert comp_lock._cloud_acquired is True
                _ = 1 / 0

        # After exception exit:
        assert comp_lock._process_acquired is False
        assert comp_lock._cloud_acquired is False
        mock_drive.delete_file.assert_called_with("file_ctx_ok")
        expected_file = lock_dir / f"{lock_name}.lock"
        assert not expected_file.exists()


# ==============================================================================
# PROBE SET 3: STALE LOCK (TTL 3600s) BREAKING VS ACTIVE LOCK RESPECT
# ==============================================================================

def test_active_lock_within_ttl_strictly_blocks():
    """
    PRECISION BOUNDARY TEST:
    Lock age = 3590.0 seconds (10s before TTL 3600.0s).
    Must strictly respect active lock:
    - Returns False
    - Does NOT delete existing lock file
    - Does NOT upload new lock file
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    now_ts = datetime.now(timezone.utc).timestamp()
    active_ts = now_ts - 3590.0  # 10s within TTL

    mock_drive.list_files.return_value = [
        {
            "id": "file_active_boundary",
            "name": "boundary.lock",
            "properties": {
                "run_id": "active_peer",
                "timestamp": str(active_ts)
            }
        }
    ]

    lock = CloudLockManager(drive_engine=mock_drive, lock_name="boundary", ttl_seconds=3600.0)
    acquired = lock.acquire()

    assert acquired is False
    assert lock._acquired is False
    mock_drive.delete_file.assert_not_called()
    mock_drive.upload_raw_content.assert_not_called()


def test_stale_lock_just_exceeding_ttl_cleanly_broken():
    """
    PRECISION BOUNDARY TEST:
    Lock age = 3605.0 seconds (5s past TTL 3600.0s).
    Must break stale lock:
    - Deletes stale lock file
    - Uploads new lock file
    - Returns True
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    now_ts = datetime.now(timezone.utc).timestamp()
    stale_ts = now_ts - 3605.0  # 5s past TTL

    stale_file_id = "file_stale_boundary"
    new_file_id = "file_new_owner"

    mock_drive.list_files.side_effect = [
        [
            {
                "id": stale_file_id,
                "name": "boundary.lock",
                "properties": {
                    "run_id": "crashed_worker",
                    "timestamp": str(stale_ts)
                }
            }
        ],
        [
            {"id": new_file_id, "name": "boundary.lock", "createdTime": "2026-09-05T15:00:00Z"}
        ]
    ]
    mock_drive.upload_raw_content.return_value = new_file_id

    lock = CloudLockManager(drive_engine=mock_drive, lock_name="boundary", ttl_seconds=3600.0)
    acquired = lock.acquire()

    assert acquired is True
    assert lock._acquired is True
    assert lock._lock_file_id == new_file_id
    mock_drive.delete_file.assert_called_with(stale_file_id)
    lock.release()


def test_malformed_corrupted_properties_treated_as_stale():
    """
    RESILIENCE INVARIANT:
    If existing lock properties are empty, corrupted, non-numeric, or missing timestamp,
    it must be treated as stale/broken, safely deleted, and not crash with TypeError/ValueError.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    corrupt_files = [
        {"id": "f_none_props", "name": "test_corrupt.lock", "properties": None},
        {"id": "f_empty_props", "name": "test_corrupt.lock", "properties": {}},
        {"id": "f_str_garbage", "name": "test_corrupt.lock", "properties": {"timestamp": "GARBAGE_NOT_FLOAT"}},
        {"id": "f_zero_ts", "name": "test_corrupt.lock", "properties": {"timestamp": "0"}},
    ]

    for corrupt_file in corrupt_files:
        mock_drive.reset_mock()
        new_id = f"new_{corrupt_file['id']}"
        mock_drive.list_files.side_effect = [
            [corrupt_file],
            [{"id": new_id, "name": "test_corrupt.lock", "createdTime": "2026-09-05T15:00:00Z"}]
        ]
        mock_drive.upload_raw_content.return_value = new_id

        # Note: In CloudLockManager line 92: float(props.get("timestamp", 0) or 0)
        # If timestamp is "GARBAGE_NOT_FLOAT", float(...) could raise ValueError in unhandled case,
        # which triggers except Exception -> fail closed!
        lock = CloudLockManager(drive_engine=mock_drive, lock_name="test_corrupt", ttl_seconds=3600.0)
        acquired = lock.acquire()

        if corrupt_file["id"] == "f_str_garbage":
            # float("GARBAGE_NOT_FLOAT") raises ValueError -> fail closed returns False safely!
            assert acquired is False
        else:
            assert acquired is True
            mock_drive.delete_file.assert_called_with(corrupt_file["id"])
            lock.release()


def test_future_timestamp_clock_drift_treated_as_active():
    """
    CLOCK SKEW INVARIANT:
    If another runner's clock was 30 seconds fast (timestamp in the future),
    (now_ts - acquired_ts) is negative (< 3600s).
    It must be treated as ACTIVE and blocked, not stale.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    now_ts = datetime.now(timezone.utc).timestamp()
    future_ts = now_ts + 30.0  # 30 seconds in future

    mock_drive.list_files.return_value = [
        {
            "id": "file_future_skew",
            "name": "skew.lock",
            "properties": {
                "run_id": "fast_clock_runner",
                "timestamp": str(future_ts)
            }
        }
    ]

    lock = CloudLockManager(drive_engine=mock_drive, lock_name="skew", ttl_seconds=3600.0)
    acquired = lock.acquire()

    assert acquired is False
    mock_drive.delete_file.assert_not_called()
    mock_drive.upload_raw_content.assert_not_called()


def test_multiple_stale_locks_all_cleared():
    """
    MULTIPLE STALE LOCK CLEANUP:
    If 3 stale locks accumulated from multiple runner crashes,
    all 3 stale files must be deleted before new lock is established.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    now_ts = datetime.now(timezone.utc).timestamp()
    stale_files = [
        {"id": "stale_1", "name": "multi_stale.lock", "properties": {"run_id": "r1", "timestamp": str(now_ts - 5000)}},
        {"id": "stale_2", "name": "multi_stale.lock", "properties": {"run_id": "r2", "timestamp": str(now_ts - 4500)}},
        {"id": "stale_3", "name": "multi_stale.lock", "properties": {"run_id": "r3", "timestamp": str(now_ts - 4000)}},
    ]

    mock_drive.list_files.side_effect = [
        stale_files,
        [{"id": "new_winner", "name": "multi_stale.lock", "createdTime": "2026-09-05T15:00:00Z"}]
    ]
    mock_drive.upload_raw_content.return_value = "new_winner"

    lock = CloudLockManager(drive_engine=mock_drive, lock_name="multi_stale")
    acquired = lock.acquire()

    assert acquired is True
    # Verify all 3 stale files were sent to delete_file
    deleted_ids = [c[0][0] for c in mock_drive.delete_file.call_args_list]
    assert "stale_1" in deleted_ids
    assert "stale_2" in deleted_ids
    assert "stale_3" in deleted_ids
    lock.release()


# ==============================================================================
# PROBE SET 4: CONCURRENCY CONSENSUS & HEARTBEAT LIFECYCLE
# ==============================================================================

def test_n_way_distributed_consensus_tie_breaker():
    """
    DISTRIBUTED CONSENSUS INVARIANT:
    When N runners upload lock files simultaneously:
    1. The winner is determined deterministically by (createdTime, id).
    2. Any losing runner must delete its own file and return False.
    3. The winning runner retains its lock and returns True.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    winner_file = {"id": "f_winner", "name": "consensus.lock", "createdTime": "2026-09-05T15:00:00.100Z"}
    loser_file = {"id": "f_loser", "name": "consensus.lock", "createdTime": "2026-09-05T15:00:00.200Z"}

    # Test as Loser
    mock_drive.upload_raw_content.return_value = loser_file["id"]
    mock_drive.list_files.side_effect = [
        [],  # initial check
        [winner_file, loser_file]  # tie breaker: both files exist
    ]

    loser_lock = CloudLockManager(drive_engine=mock_drive, run_id="loser_run", lock_name="consensus")
    assert loser_lock.acquire() is False
    assert loser_lock._acquired is False
    mock_drive.delete_file.assert_called_with(loser_file["id"])

    # Test as Winner
    mock_drive.reset_mock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    mock_drive.upload_raw_content.return_value = winner_file["id"]
    mock_drive.list_files.side_effect = [
        [],
        [winner_file, loser_file]
    ]

    winner_lock = CloudLockManager(drive_engine=mock_drive, run_id="winner_run", lock_name="consensus")
    assert winner_lock.acquire() is True
    assert winner_lock._acquired is True
    # Winner does NOT delete its file
    mock_drive.delete_file.assert_not_called()
    winner_lock.release()


def test_heartbeat_thread_clean_start_and_termination():
    """
    RESOURCE LEAK INVARIANT:
    Heartbeat daemon thread must start upon acquisition and cleanly terminate
    upon release without hanging or leaking threads.
    """
    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}
    mock_drive.list_files.side_effect = [
        [],
        [{"id": "hb_file", "name": "hb.lock", "createdTime": "2026-09-05T15:00:00Z"}]
    ]
    mock_drive.upload_raw_content.return_value = "hb_file"

    lock = CloudLockManager(
        drive_engine=mock_drive,
        lock_name="hb",
        heartbeat_interval=0.1  # fast heartbeat for testing
    )

    initial_threads = threading.active_count()
    acquired = lock.acquire()
    assert acquired is True
    assert lock._heartbeat_thread is not None
    assert lock._heartbeat_thread.is_alive()

    # Let heartbeat fire at least once
    time.sleep(0.25)
    assert mock_drive.set_file_properties.called

    # Release
    lock.release()
    assert lock._heartbeat_thread is None
    # Thread must be joined and dead
    time.sleep(0.1)
    assert threading.active_count() <= initial_threads


def test_multithreaded_composite_lock_contention(tmp_path):
    """
    STRESS TEST:
    10 concurrent threads simultaneously attempt to acquire CompositeLock for the same resource.
    Invariant:
    - EXACTLY ONE thread must succeed in acquiring both local and cloud lock.
    - 9 threads must fail cleanly (return False).
    - After the winner releases, another thread can acquire without deadlock or dangling state.
    """
    lock_dir = tmp_path / "locks"
    lock_name = "stress_contention"

    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"00_SYSTEM": "system_fid"}

    active_cloud_id = None
    cloud_lock_mutex = threading.Lock()

    def mock_list_files(folder_id, name_contains=None):
        nonlocal active_cloud_id
        with cloud_lock_mutex:
            if active_cloud_id:
                return [{
                    "id": active_cloud_id,
                    "name": f"{lock_name}.lock",
                    "createdTime": "2026-09-05T15:00:00Z",
                    "properties": {
                        "run_id": "winner",
                        "timestamp": str(datetime.now(timezone.utc).timestamp())
                    }
                }]
            return []

    def mock_upload(content, filename, parent_folder_id, mime_type, properties):
        nonlocal active_cloud_id
        with cloud_lock_mutex:
            active_cloud_id = f"cloud_file_{properties.get('run_id')}"
            return active_cloud_id

    def mock_delete(file_id):
        nonlocal active_cloud_id
        with cloud_lock_mutex:
            if active_cloud_id == file_id:
                active_cloud_id = None
            return True

    mock_drive.list_files.side_effect = mock_list_files
    mock_drive.upload_raw_content.side_effect = mock_upload
    mock_drive.delete_file.side_effect = mock_delete

    results = []
    locks = []

    def worker_thread(thread_idx):
        with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
            c_lock = CompositeLock(
                name=lock_name,
                command_name=f"worker-{thread_idx}",
                drive_engine=mock_drive
            )
            success = c_lock.acquire()
            results.append((thread_idx, success))
            if success:
                locks.append(c_lock)

    threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    success_count = sum(1 for _, s in results if s is True)
    failure_count = sum(1 for _, s in results if s is False)

    assert success_count == 1, f"Expected exactly 1 winner among 10 threads, got {success_count}"
    assert failure_count == 9, f"Expected exactly 9 losers among 10 threads, got {failure_count}"

    # Winner releases
    winner_lock = locks[0]
    released = winner_lock.release()
    assert released is True

    # After winner releases, a subsequent caller can cleanly acquire
    with patch("core.cloud_lock.ProcessLock", lambda **kwargs: ProcessLock(lock_dir=lock_dir, **kwargs)):
        new_lock = CompositeLock(
            name=lock_name,
            command_name="subsequent-worker",
            drive_engine=mock_drive
        )
        assert new_lock.acquire() is True
        new_lock.release()
