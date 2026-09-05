"""
Runtime Configuration for AL-AMR Autonomous Production Service.
Loads configuration from environment variables with safe defaults.
"""
import os
from dataclasses import dataclass
from pathlib import Path
from config.settings import PROJECT_ROOT, TEST_MODE, DATA_DIR, LOCKS_DIR


@dataclass
class RuntimeConfig:
    """Authoritative configuration for the autonomous worker runtime."""
    enabled: bool = True
    interval_sec: float = 60.0
    harvest_interval_sec: float = 300.0
    recovery_interval_sec: float = 180.0
    target_buffer_stock: int = 6
    max_batch_size: int = 1
    dry_run: bool = False
    heartbeat_timeout_sec: float = 120.0
    max_retries: int = 3
    stale_job_timeout_sec: float = 1800.0
    canary_mode: bool = False
    state_file_path: Path = LOCKS_DIR / "worker_state.json"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        """Constructs runtime configuration from environment variables."""
        return cls(
            enabled=os.getenv("AUTONOMOUS_WORKER_ENABLED", "true").lower() == "true",
            interval_sec=float(os.getenv("AUTONOMOUS_INTERVAL_SEC", "60.0")),
            harvest_interval_sec=float(os.getenv("HARVEST_INTERVAL_SEC", "300.0")),
            recovery_interval_sec=float(os.getenv("RECOVERY_INTERVAL_SEC", "180.0")),
            target_buffer_stock=int(os.getenv("TARGET_BUFFER_STOCK", "6")),
            max_batch_size=int(os.getenv("MAX_BATCH_SIZE", "1")),
            dry_run=os.getenv("AUTONOMOUS_DRY_RUN", str(TEST_MODE)).lower() == "true",
            heartbeat_timeout_sec=float(os.getenv("WORKER_HEARTBEAT_TIMEOUT_SEC", "120.0")),
            max_retries=int(os.getenv("MAX_JOB_RETRIES", "3")),
            stale_job_timeout_sec=float(os.getenv("STALE_JOB_THRESHOLD_SEC", "1800.0")),
            canary_mode=os.getenv("AUTONOMOUS_CANARY_MODE", "false").lower() == "true",
            state_file_path=LOCKS_DIR / "worker_state.json"
        )
