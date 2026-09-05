"""
Distributed Cloud Lock & Coordinated Process Locking Engine.
Provides fail-closed, atomic locking across ephemeral GitHub Actions cloud runners
and local invocations using Google Drive vault: YouTube_Shorts_Vault/00_SYSTEM/
and host-level ProcessLock.
"""
import os
import sys
import json
import time
import uuid
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.lock import ProcessLock, ProcessLockError

logger = logging.getLogger(__name__)

CLOUD_LOCK_FILENAME = "cloud_production.lock"
CLOUD_LOCK_DEFAULT_TTL_SEC = 3600.0  # 1 hour TTL
CLOUD_LOCK_HEARTBEAT_SEC = 300.0   # 5 minutes renewal interval


class CloudLockError(Exception):
    """Raised when the cloud lock cannot be acquired or held."""
    pass


class CloudLockManager:
    """
    Manages distributed atomic locking in Google Drive `00_SYSTEM/` folder to prevent
    concurrent cloud runners or out-of-order writes from clobbering state.
    
    Invariants:
    - Strict fail-closed: returns False on any network, quota, or Drive API error.
    - Stale lock detection & breaking: locks older than TTL (3600s) are safely broken.
    - Consensus race resolution: tie-breaker chooses earliest createdTime file ID.
    - Heartbeat renewal: background daemon thread updates lock timestamp every 5m.
    """

    def __init__(
        self,
        drive_engine: Optional[Any] = None,
        run_id: Optional[str] = None,
        lock_name: str = "cloud_production",
        ttl_seconds: float = CLOUD_LOCK_DEFAULT_TTL_SEC,
        heartbeat_interval: float = CLOUD_LOCK_HEARTBEAT_SEC
    ):
        self.drive_engine = drive_engine
        self.run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        self.lock_name = lock_name
        self.lock_filename = f"{lock_name}.lock" if not lock_name.endswith(".lock") else lock_name
        self.ttl_seconds = float(ttl_seconds)
        self.heartbeat_interval = float(heartbeat_interval)
        self._acquired = False
        self._lock_file_id: Optional[str] = None
        self._stop_heartbeat_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def acquire(self, timeout_seconds: float = 30.0) -> bool:
        """
        Attempts to acquire distributed cloud lock.
        Fails closed on any exception (returns False).
        Bypasses only if drive_engine is explicitly None (offline local test mode).
        """
        if self.drive_engine is None:
            self._acquired = True
            return True

        try:
            folders = self.drive_engine.ensure_folder_hierarchy()
            system_folder_id = folders.get("00_SYSTEM") if isinstance(folders, dict) else None
            if not system_folder_id:
                logger.warning("[FAIL_CLOSED] Drive 00_SYSTEM folder not found. Cannot acquire cloud lock.")
                self._acquired = False
                return False

            now_ts = datetime.now(timezone.utc).timestamp()

            # Search for existing lock files matching filename
            files = self.drive_engine.list_files(
                folder_id=system_folder_id,
                name_contains=self.lock_filename,
            )

            for f in files:
                if f.get("name") == self.lock_filename:
                    props = f.get("properties", {}) or {}
                    acquired_ts = float(props.get("timestamp", 0) or 0)
                    lock_owner = props.get("run_id", "unknown")

                    # Check if stale
                    if (now_ts - acquired_ts) < self.ttl_seconds and acquired_ts > 0:
                        logger.warning(
                            f"Cloud lock [{self.lock_filename}] held by active run [{lock_owner}] "
                            f"(acquired at {acquired_ts}, age {now_ts - acquired_ts:.1f}s < TTL {self.ttl_seconds}s). "
                            f"Acquisition blocked."
                        )
                        self._acquired = False
                        return False
                    else:
                        logger.warning(
                            f"Found stale cloud lock [{lock_owner}] (age: {now_ts - acquired_ts:.1f}s >= TTL {self.ttl_seconds}s). "
                            f"Breaking stale lock file {f.get('id')}."
                        )
                        try:
                            self.drive_engine.delete_file(f["id"])
                        except Exception as del_err:
                            logger.error(f"Failed to delete stale lock: {del_err}")

            # Upload our lock file
            lock_payload = {
                "run_id": self.run_id,
                "timestamp": str(now_ts),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "ttl_seconds": str(self.ttl_seconds)
            }
            file_id = self.drive_engine.upload_raw_content(
                content=json.dumps(lock_payload).encode("utf-8"),
                filename=self.lock_filename,
                parent_folder_id=system_folder_id,
                mime_type="application/json",
                properties=lock_payload,
            )
            self._lock_file_id = file_id

            # Distributed consensus tie-breaker
            active_files = self.drive_engine.list_files(
                folder_id=system_folder_id,
                name_contains=self.lock_filename
            )
            matching = [f for f in active_files if f.get("name") == self.lock_filename]
            if len(matching) > 1:
                # Winner has earliest createdTime, with lowest ID as secondary tie-breaker
                winner = min(matching, key=lambda x: (x.get("createdTime") or "", x.get("id") or ""))
                if winner.get("id") != file_id:
                    logger.warning(
                        f"Cloud lock race detected: runner {self.run_id} (file {file_id}) "
                        f"lost consensus to winner (file {winner.get('id')}). Relinquishing."
                    )
                    try:
                        self.drive_engine.delete_file(file_id)
                    except Exception:
                        pass
                    self._lock_file_id = None
                    self._acquired = False
                    return False

            self._acquired = True
            logger.info(f"[+] Acquired distributed cloud lock [{self.lock_filename}] (Run: {self.run_id}, File: {file_id})")
            self._start_heartbeat()
            return True

        except Exception as e:
            logger.error(f"[FAIL_CLOSED] Cloud lock acquisition failed with exception: {e}")
            self._acquired = False
            return False

    def renew_lock(self) -> bool:
        """Renews the active lock by updating its timestamp in Drive."""
        if not self._acquired or not self._lock_file_id or not self.drive_engine:
            return False

        now_ts = datetime.now(timezone.utc).timestamp()
        try:
            new_props = {
                "run_id": self.run_id,
                "timestamp": str(now_ts),
                "last_renewed_at": datetime.now(timezone.utc).isoformat()
            }
            if hasattr(self.drive_engine, "set_file_properties"):
                self.drive_engine.set_file_properties(self._lock_file_id, new_props)
                logger.debug(f"[LOCK_HEARTBEAT] Renewed cloud lock [{self.lock_filename}] at {now_ts}")
                return True
            return True
        except Exception as e:
            logger.warning(f"Failed to renew cloud lock heartbeat: {e}")
            return False

    def _start_heartbeat(self) -> None:
        """Starts background daemon heartbeat thread."""
        self._stop_heartbeat_event.clear()
        def _heartbeat_worker():
            while not self._stop_heartbeat_event.wait(self.heartbeat_interval):
                if not self.renew_lock():
                    logger.warning(f"Heartbeat renewal failed for [{self.lock_filename}]")

        self._heartbeat_thread = threading.Thread(
            target=_heartbeat_worker,
            name=f"CloudLockHeartbeat-{self.lock_name}",
            daemon=True
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        """Stops background heartbeat thread."""
        self._stop_heartbeat_event.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        self._heartbeat_thread = None

    def release(self) -> bool:
        """Releases the cloud lock file cleanly."""
        self._stop_heartbeat()

        if not self._acquired or not self.drive_engine:
            self._acquired = False
            return True

        try:
            if self._lock_file_id:
                self.drive_engine.delete_file(self._lock_file_id)
                logger.info(f"Released cloud lock [{self.lock_filename}] (Run: {self.run_id})")
            self._acquired = False
            self._lock_file_id = None
            return True
        except Exception as e:
            logger.warning(f"Failed to release cloud lock file: {e}")
            self._acquired = False
            return False

    def __enter__(self):
        if not self.acquire():
            raise CloudLockError(f"Could not acquire cloud lock [{self.lock_filename}] for run [{self.run_id}]")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class CompositeLock:
    """
    Coordinated two-tier locking:
    Phase 1: Host-local ProcessLock (instant, zero network cost)
    Phase 2: Distributed CloudLockManager (Google Drive)
    
    Guarantees rollback: If CloudLockManager fails to acquire, ProcessLock is
    immediately released before returning False, leaving zero dangling local locks.
    """

    def __init__(
        self,
        name: str,
        command_name: str,
        drive_engine: Optional[Any] = None,
        cloud_lock_name: Optional[str] = None,
        ttl_seconds: float = CLOUD_LOCK_DEFAULT_TTL_SEC
    ):
        self.name = name
        self.command_name = command_name
        self.process_lock = ProcessLock(name=name, command_name=command_name)
        self.cloud_lock = CloudLockManager(
            drive_engine=drive_engine,
            lock_name=cloud_lock_name or name,
            ttl_seconds=ttl_seconds
        )
        self._process_acquired = False
        self._cloud_acquired = False

    def acquire(self, timeout_seconds: float = 30.0) -> bool:
        """Acquires local process lock first, then cloud lock. Rolls back on failure."""
        # Tier 1: Local process lock
        if not self.process_lock.acquire():
            return False
        self._process_acquired = True

        # Tier 2: Cloud lock
        if not self.cloud_lock.acquire(timeout_seconds=timeout_seconds):
            # Rollback Phase 1
            self.process_lock.release()
            self._process_acquired = False
            return False

        self._cloud_acquired = True
        return True

    def release(self) -> bool:
        """Releases cloud lock first, then local process lock."""
        cloud_ok = True
        proc_ok = True

        if self._cloud_acquired:
            cloud_ok = self.cloud_lock.release()
            self._cloud_acquired = False

        if self._process_acquired:
            proc_ok = self.process_lock.release()
            self._process_acquired = False

        return cloud_ok and proc_ok

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """Returns local lock metadata if held."""
        return self.process_lock.get_lock_info()

    def __enter__(self):
        if not self.acquire():
            raise CloudLockError(f"Could not acquire CompositeLock '{self.name}'")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
