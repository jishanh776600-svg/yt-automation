"""
Phase 7: Cloud Autonomy Contract, Pipeline Lifecycle Stages & Cloud State.
==========================================================================
Defines the authoritative architectural boundaries for 100% cloud-autonomous
execution, explicit stage states, run telemetry, and cloud locking.

Invariants:
  - CLOUD_AUTONOMOUS = True: Absolute runtime invariant.
  - Zero local device, browser, or GUI dependencies in production.
  - Fail-closed transitions with structured telemetry.
"""

import datetime
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger("alamr.pipeline_state")

# Authoritative Cloud Invariant & Target Reserve
CLOUD_AUTONOMOUS = True
TARGET_BUFFER: int = 6

# ---------------------------------------------------------------------------
# Machine-Verifiable Dependency Classification
# ---------------------------------------------------------------------------

ALLOWED_RUNTIME = {
    "github_actions_runner",
    "cloud_filesystem_ephemeral",
    "google_drive_api",
    "gemini_api",
    "gdelt_api",
    "rss_http_sources",
    "pexels_api",
    "approved_visual_rest_apis",
    "ffmpeg_headless",
    "python_standard_library",
    "sqlite_runner_ephemeral",
    "google_drive_canonical_persistence",
}

FORBIDDEN_RUNTIME = {
    "antigravity",
    "browser_interactive",
    "browser_engines",
    "selenium",
    "playwright",
    "puppeteer",
    "pyppeteer",
    "windows_task_scheduler",
    "localhost_oauth_callback",
    "user_desktop",
    "onedrive_local_sync_client",
    "c_users_hardcoded",
    "interactive_gui",
    "local_daemon",
    "local_home_network",
    "user_controlled_browser_session",
}


# ---------------------------------------------------------------------------
# Pipeline Lifecycle Stages
# ---------------------------------------------------------------------------

class PipelineStage(str, Enum):
    """Monotonic execution stages for autonomous production runs."""
    INITIALIZING = "INITIALIZING"
    LOCKING = "LOCKING"
    SYNCING_DB = "SYNCING_DB"
    INGESTING = "INGESTING"
    CLUSTERING = "CLUSTERING"
    VERIFYING = "VERIFYING"
    SCRIPTING = "SCRIPTING"
    VISUAL_RETRIEVAL = "VISUAL_RETRIEVAL"
    MANIFEST_BUILDING = "MANIFEST_BUILDING"
    ASSET_FETCHING = "ASSET_FETCHING"
    RENDERING = "RENDERING"
    QA = "QA"
    DEPOSITING_VAULT = "DEPOSITING_VAULT"
    SYNCING_DB_FINAL = "SYNCING_DB_FINAL"
    READY_FOR_PUBLISH = "READY_FOR_PUBLISH"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED_DUPLICATE = "SKIPPED_DUPLICATE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    BUFFER_HEALTHY = "BUFFER_HEALTHY"


# ---------------------------------------------------------------------------
# Production Run Telemetry & Checkpointing
# ---------------------------------------------------------------------------

@dataclass
class ProductionRunTelemetry:
    """Comprehensive, machine-readable telemetry emitted per production cycle."""
    run_id: str = field(default_factory=lambda: f"run_{uuid.uuid4().hex[:12]}")
    start_time: str = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat()
    )
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    current_stage: str = PipelineStage.INITIALIZING.value
    status: str = "IN_PROGRESS"         # IN_PROGRESS, SUCCEEDED, FAILED, PARTIAL, BLOCKED
    is_dry_run: bool = False
    events_discovered: int = 0
    events_verified: int = 0
    events_rejected: int = 0
    scripts_generated: int = 0
    visual_plans_generated: int = 0
    assets_fetched: int = 0
    videos_rendered: int = 0
    videos_qa_passed: int = 0
    videos_qa_failed: int = 0
    videos_deposited: int = 0
    duplicates_skipped: int = 0
    insufficient_evidence: int = 0
    initial_ready_stock: int = 0
    final_ready_stock: int = 0
    target_buffer: int = 6
    failure_reasons: List[str] = field(default_factory=list)
    stage_durations: Dict[str, float] = field(default_factory=dict)
    produced_records: List[Dict[str, Any]] = field(default_factory=list)

    def transition_stage(self, stage: PipelineStage, message: str = "") -> None:
        """Records transition to a new stage."""
        self.current_stage = stage.value
        logger.info(f"Pipeline [Run {self.run_id}] -> {stage.value}: {message}")

    def complete(self, status: str = "SUCCEEDED") -> None:
        """Finalizes run telemetry."""
        now = datetime.datetime.now(datetime.timezone.utc)
        self.end_time = now.isoformat()
        self.status = status
        try:
            start_dt = datetime.datetime.fromisoformat(self.start_time)
            self.duration_seconds = round((now - start_dt).total_seconds(), 2)
        except Exception:
            self.duration_seconds = 0.0
        logger.info(
            f"Pipeline [Run {self.run_id}] completed with status '{status}' "
            f"in {self.duration_seconds}s (Produced: {self.videos_deposited}, Stock: {self.final_ready_stock})"
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# Distributed Cloud Lock Re-Exports (Phase 7 & Milestone 1 Feature 4)
# ---------------------------------------------------------------------------
from core.cloud_lock import (
    CLOUD_LOCK_FILENAME,
    CLOUD_LOCK_DEFAULT_TTL_SEC,
    CLOUD_LOCK_DEFAULT_TTL_SEC as CLOUD_LOCK_STALE_SEC,
    CloudLockError,
    CloudLockManager,
    CompositeLock,
)

