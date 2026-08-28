"""
Process-Level Concurrency & Locking Control (Phase 5.3).
Provides:
  - Atomic, file/PID-based lock acquisition.
  - Stale lock detection via process liveliness checks and timeout thresholds.
  - Context manager and decorator interfaces.
  - Command-specific locks (e.g. 'production', 'publisher') to avoid unnecessary blocking.
"""
import os
import sys
import time
import json
import socket
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from config.settings import LOCKS_DIR, LOCK_STALE_TIMEOUT_SEC

logger = logging.getLogger(__name__)


def is_pid_alive(pid: int) -> bool:
    """
    Cross-platform check for whether a given process ID is actively running.
    """
    if pid <= 0:
        return False

    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # If OpenProcess failed, check error code
        err = ctypes.GetLastError()
        # ERROR_ACCESS_DENIED (5) means the process is alive but we don't have full query rights
        if err == 5:
            return True
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            # Process is running under another user
            return True
        except (ProcessLookupError, OSError):
            return False


class ProcessLockError(Exception):
    """Raised when a process lock cannot be acquired."""
    pass


class ProcessLock:
    """
    Atomic file-based process lock with PID diagnostics and stale recovery.
    """

    def __init__(
        self,
        name: str = "production",
        lock_dir: Optional[Path] = None,
        stale_timeout_sec: float = LOCK_STALE_TIMEOUT_SEC,
        command_name: Optional[str] = None
    ):
        self.name = name
        self.lock_dir = Path(lock_dir) if lock_dir else LOCKS_DIR
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.lock_dir / f"{self.name}.lock"
        self.stale_timeout_sec = stale_timeout_sec
        self.command_name = command_name or sys.argv[0] if sys.argv else "pipeline"
        self._acquired = False
        self._fd: Optional[int] = None

    def get_lock_info(self) -> Optional[Dict[str, Any]]:
        """Reads lock metadata from disk if file exists."""
        if not self.lock_file.exists():
            return None
        try:
            with open(self.lock_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def is_locked(self) -> bool:
        """Returns True if the lock file exists and is held by a live process."""
        info = self.get_lock_info()
        if not info:
            return False
        pid = info.get("pid")
        if pid and is_pid_alive(pid):
            return True
        return False

    def acquire(self, timeout: float = 0.0, retry_interval: float = 0.2) -> bool:
        """
        Attempts to acquire the lock atomically.
        If timeout > 0, retries until timeout expires.
        Returns True if acquired, False otherwise.
        """
        start_time = time.time()
        while True:
            try:
                # O_CREAT | O_EXCL provides atomic creation semantics
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                self._fd = os.open(str(self.lock_file), flags, 0o644)
                
                # Write diagnostic metadata
                metadata = {
                    "pid": os.getpid(),
                    "lock_name": self.name,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
                    "created_timestamp": time.time(),
                    "hostname": socket.gethostname(),
                    "command": self.command_name
                }
                meta_bytes = json.dumps(metadata, indent=2).encode("utf-8")
                os.write(self._fd, meta_bytes)
                os.close(self._fd)
                self._fd = None
                self._acquired = True
                logger.info(f"[LOCK ACQUIRED] Acquired '{self.name}' lock (PID {os.getpid()})")
                return True

            except FileExistsError:
                # Check for stale lock
                info = self.get_lock_info()
                if info:
                    owner_pid = info.get("pid", 0)
                    created_ts = info.get("created_timestamp", 0)
                    age = time.time() - created_ts if created_ts else 0

                    is_alive = is_pid_alive(owner_pid)
                    is_expired = age > self.stale_timeout_sec

                    if not is_alive or is_expired:
                        reason = "process is terminated" if not is_alive else f"exceeded stale timeout ({age:.1f}s > {self.stale_timeout_sec:.1f}s)"
                        logger.warning(f"[STALE LOCK DETECTED] Recovering lock '{self.name}' (PID {owner_pid}, {reason}). Removing stale lock file.")
                        try:
                            self.lock_file.unlink(missing_ok=True)
                            continue  # Retry acquisition immediately
                        except Exception as rm_err:
                            logger.error(f"Could not remove stale lock file: {rm_err}")

                    else:
                        logger.warning(
                            f"[LOCK CONFLICT] '{self.name}' lock is currently held by PID {owner_pid} "
                            f"(Command: '{info.get('command')}', Age: {age:.1f}s). Aborting acquisition."
                        )
                else:
                    # Empty or corrupt lock file; remove safely
                    try:
                        self.lock_file.unlink(missing_ok=True)
                        continue
                    except Exception:
                        pass

                if time.time() - start_time >= timeout:
                    return False

                time.sleep(retry_interval)

    def release(self) -> bool:
        """
        Releases the lock by removing the lock file if owned by the current process.
        """
        if not self._acquired:
            return False

        try:
            info = self.get_lock_info()
            # Safety check: only delete if owned by our PID
            if info and info.get("pid") == os.getpid():
                self.lock_file.unlink(missing_ok=True)
                self._acquired = False
                logger.info(f"[LOCK RELEASED] Released '{self.name}' lock (PID {os.getpid()})")
                return True
            elif not self.lock_file.exists():
                self._acquired = False
                return True
            else:
                logger.warning(f"Refusing to release lock '{self.name}' owned by different PID ({info.get('pid') if info else 'unknown'})")
                return False
        except Exception as e:
            logger.error(f"Error releasing lock '{self.name}': {e}")
            return False

    def __enter__(self):
        acquired = self.acquire()
        if not acquired:
            info = self.get_lock_info()
            owner_pid = info.get("pid") if info else "unknown"
            cmd = info.get("command") if info else "unknown"
            raise ProcessLockError(f"Could not acquire lock '{self.name}' (already held by PID {owner_pid}, command '{cmd}')")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
