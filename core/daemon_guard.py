"""
Daemon Integrity & Stale Code Guard.
Guarantees that a running autonomous daemon cannot execute production mutations
if the code on disk has diverged from the version loaded into process RAM at startup.
"""
import os
import sys
import hashlib
import logging
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class StaleDaemonError(Exception):
    """Raised when daemon code in memory is stale compared to disk."""
    pass


class DaemonIntegrityGuard:
    """
    Tracks git commit and source file fingerprint at daemon startup.
    Evaluates integrity before every convergence pass.
    If stale code is detected, halts daemon gracefully to prevent rogue mutations.
    """

    def __init__(self, project_root: Optional[Path] = None):
        self.root = project_root or PROJECT_ROOT
        self.startup_commit = self.get_current_git_commit()
        self.startup_fingerprint = self.compute_source_fingerprint()
        logger.info(
            f"[DAEMON_INTEGRITY] Initialized guard. "
            f"Commit: {self.startup_commit[:8] if self.startup_commit else 'unknown'} | "
            f"Fingerprint: {self.startup_fingerprint[:8]}"
        )

    def get_current_git_commit(self) -> str:
        """Reads current git commit hash."""
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass

        head_file = self.root / ".git" / "HEAD"
        if head_file.exists():
            try:
                ref = head_file.read_text(encoding="utf-8").strip()
                if ref.startswith("ref:"):
                    ref_path = self.root / ".git" / ref.split()[1]
                    if ref_path.exists():
                        return ref_path.read_text(encoding="utf-8").strip()
                return ref
            except Exception:
                pass
        return "UNKNOWN_COMMIT"

    def compute_source_fingerprint(self) -> str:
        """Computes combined SHA-256 fingerprint across all core Python source files."""
        hasher = hashlib.sha256()
        key_subdirs = ["core", "engines", "intelligence", "dashboard", "runtime", "config"]
        
        # Include main.py
        main_file = self.root / "main.py"
        if main_file.exists():
            try:
                hasher.update(main_file.read_bytes())
            except Exception:
                pass

        for subdir in key_subdirs:
            target_dir = self.root / subdir
            if not target_dir.exists():
                continue
            for p in sorted(target_dir.rglob("*.py")):
                if "__pycache__" in str(p):
                    continue
                try:
                    hasher.update(str(p.relative_to(self.root)).encode("utf-8"))
                    hasher.update(p.read_bytes())
                except Exception:
                    pass

        return hasher.hexdigest()

    def verify_integrity(self) -> Tuple[bool, str]:
        """
        Verifies that current disk state matches process startup state.
        Returns (is_valid, reason).
        """
        current_commit = self.get_current_git_commit()
        if self.startup_commit != "UNKNOWN_COMMIT" and current_commit != "UNKNOWN_COMMIT":
            if current_commit != self.startup_commit:
                return False, (
                    f"Git commit changed on disk since startup: "
                    f"started at {self.startup_commit[:8]}, disk is at {current_commit[:8]}"
                )

        current_fingerprint = self.compute_source_fingerprint()
        if current_fingerprint != self.startup_fingerprint:
            return False, (
                f"Source code modified on disk since startup: "
                f"startup fingerprint {self.startup_fingerprint[:8]}, disk fingerprint {current_fingerprint[:8]}"
            )

        return True, "Codebase integrity verified (in-memory code matches deployed disk version)."

    def enforce_integrity(self) -> None:
        """Enforces integrity check, raising StaleDaemonError if mismatch detected."""
        is_valid, reason = self.verify_integrity()
        if not is_valid:
            logger.critical(f"[STALE_DAEMON_HALT] {reason}")
            raise StaleDaemonError(f"Stale daemon execution prohibited: {reason}")
