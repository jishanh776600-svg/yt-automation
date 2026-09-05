# AL-AMR — STEP 5: AUTONOMOUS RUNTIME & DEPLOYMENT BRIDGE REPORT

> **Status:** `[COMPLETED & VERIFIED]`  
> **Milestone:** Step 5 / Change Log Step 44  
> **Date:** September 4, 2026  
> **Targeted Test Status:** 10/10 Passed (`tests/test_autonomous_runtime.py`)  
> **Regression Test Status:** 17/17 Passed (`tests/test_mission_control.py`)  
> **Live API Tokens Spent:** 0 (Zero live AI spend, zero renders, zero real Drive/YouTube mutations)  

---

## Executive Summary

**AL-AMR Step 5** operationalizes the unified 15-stage production pipeline (`engines/orchestrator.py`) and the Mission Control web application (`dashboard/`) into a persistent, autonomous, fault-tolerant background service. 

Prior to Step 5, production batches, intelligence harvesting, and scheduled publishing required manual CLI commands or ephemeral cron triggers. Step 5 provides the dedicated, self-contained **Autonomous Runtime & Deployment Bridge** (`runtime/`) that runs as a persistent daemon or containerized service, continuously balancing the production buffer, discovering fresh topic intelligence, scheduling compliant video releases, and safely recovering interrupted or failed jobs with zero human intervention.

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph Host / Container Process
        CLI["CLI Entrypoint\n(python -m runtime.cli / main.py --runtime)"]
        CFG["RuntimeConfig\n(runtime/config.py)"]
        LOCK["ProcessLock\n('autonomous_worker')"]
        SIG["Graceful Signal Traps\n(SIGINT / SIGTERM / SIGBREAK)"]
    end

    subgraph Autonomous Runtime Service ["AutonomousRuntimeService (runtime/service.py)"]
        LOOP["Autonomous Production Loop\n(Configurable Interval, default 60s)"]
        HB["Persistent Heartbeat & State\n(data/runtime/worker_state.json)"]
        
        subgraph Autonomous Execution Subsystems
            S1["Subsystem 1: Crash Recovery\n(Resume in-flight jobs via STATE_RANK idempotency)"]
            S2["Subsystem 2: Intelligence Harvest\n(Active DiscoveryProfile, >=2 domain evidence gate)"]
            S3["Subsystem 3: Queue Replenishment\n(Maintain TARGET_BUFFER_STOCK ready shorts)"]
            S4["Subsystem 4: Scheduled Publishing\n(Strict DAILY_SHORTS_LIMIT = 3 & interval guard)"]
            S5["Subsystem 5: Failed Job Recovery\n(Exponential backoff & MAX_JOB_RETRIES ceiling)"]
        end
    end

    subgraph Integration Points
        ORCH["ProductionOrchestrator\n(ExecutionCapabilities: Production / Dry-Run)"]
        MC_SRV["MissionControlService\n(Queue Interlock & Event Stream)"]
        MC_UI["Mission Control WebApp\n(Live Telemetry & Status Badge at /mission-control)"]
        DB[(SQLite / Postgres DB)]
    end

    CLI --> CFG --> LOCK --> LOOP
    SIG -.->|Trigger stop| LOOP
    LOOP --> HB
    HB -->|Polls /api/mission-control/runtime| MC_UI
    LOOP --> S1 & S2 & S3 & S4 & S5
    S1 & S3 & S4 & S5 --> ORCH
    S2 --> DB
    LOOP -.->|Checks is_queue_paused()| MC_SRV
```

---

## Key Subsystems Implemented

### 1. Configuration & Process Isolation (`runtime/config.py`)
- **`RuntimeConfig`**: Reads runtime knobs from environment variables with safe defaults:
  - `AUTONOMOUS_WORKER_ENABLED` (default: `True`)
  - `AUTONOMOUS_INTERVAL_SEC` (default: `60.0s`)
  - `HARVEST_INTERVAL_SEC` (default: `3600.0s`)
  - `RECOVERY_INTERVAL_SEC` (default: `300.0s`)
  - `TARGET_BUFFER_STOCK` (default: `6`)
  - `MAX_BATCH_SIZE` (default: `2`)
  - `AUTONOMOUS_DRY_RUN` (default: `False`)
  - `WORKER_HEARTBEAT_TIMEOUT_SEC` (default: `120.0s`)
  - `MAX_JOB_RETRIES` (default: `3`)
  - `STALE_JOB_THRESHOLD_SEC` (default: `1800.0s`)
- **Concurrency & Singleton Guard**: Uses `ProcessLock("autonomous_worker")` anchored in `locks/` to prevent dual worker executions across threads or processes.
- **Graceful Termination**: Handles `SIGINT`, `SIGTERM`, and Windows `SIGBREAK` cleanly, completing current cycle boundaries before writing an `OFFLINE` heartbeat and releasing OS lock handles.

### 2. Autonomous Runtime Service (`runtime/service.py`)
Implements `AutonomousRuntimeService` coordinating 5 core cycles per tick:
1. **Crash-Safe In-Flight Resumption**: Identifies jobs interrupted mid-stream (states between `RESEARCHING` and `QA`, excluding terminal and post-production states). Uses `STATE_RANK` idempotency in `ProductionOrchestrator` to resume from the exact last successful stage without repeating completed work.
2. **Periodic Intelligence Harvesting**: Invokes `discover_candidates()` parameterized dynamically by the active `DiscoveryProfile` (e.g. `CURRENT_AFFAIRS`, `HISTORICAL`, or custom). Enforces the multi-source evidence gate (>= 2 independent publisher domains) and persists approved topics without hardcoding.
3. **Target Buffer Replenishment**: Inspects the count of `READY_TO_UPLOAD` and `SCHEDULED` jobs against `TARGET_BUFFER_STOCK` (default: 6). If a deficit exists, batches production jobs through `ProductionOrchestrator.produce_batch()` up to `MAX_BATCH_SIZE`.
4. **Scheduled Publishing with Hard Limits**: Checks for available ready shorts and publishes eligible items strictly respecting `DAILY_SHORTS_LIMIT` (3 shorts/calendar day) and minimum publication interval spacing.
5. **Eligible Failed Job Auto-Recovery**: Detects failed jobs below `MAX_JOB_RETRIES` that have exceeded the recovery backoff window (`2^retries * 300s`), transitioning them back to `QUEUED` for safe re-processing.
6. **Queue Pause Interlock**: Respects Mission Control emergency interlocks (`mission_control_service.is_queue_paused()`), immediately halting new production and publishing when paused while maintaining telemetry.

### 3. Mission Control WebApp Integration
- **Heartbeat Telemetry File**: Persists atomic state JSON to `data/runtime/worker_state.json` recording:
  - `status` (`ONLINE` / `OFFLINE` / `PAUSED`)
  - `current_task` (e.g. `BUFFER_REPLENISHMENT`, `HARVESTING_INTELLIGENCE`, `RESUMING_JOB_...`)
  - `current_job_id`
  - `target_buffer_stock` & `current_buffer_stock`
  - `daily_limit` & `published_today`
  - `last_run`, `last_harvest`, `next_run`
  - `total_cycles`, `jobs_produced`, `jobs_published`, `jobs_recovered`
- **Telemetry Endpoint**: Exposed `GET /api/mission-control/runtime` providing real-time worker telemetry to Mission Control.
- **UI Dashboard**: View A (Command Center) dynamically reflects worker status (ONLINE/OFFLINE/PAUSED badge), active task description, and live buffer health.

### 4. CLI & Dispatcher (`runtime/cli.py` & `main.py`)
- Standardized execution entrypoint via `python -m runtime.cli` supporting:
  - `--once`: Execute a single evaluation tick and exit (ideal for cron/testing)
  - `--dry-run`: Force zero external side effects (`ExecutionCapabilities.dry_run()`)
  - `--interval`: Override loop sleep seconds
  - `--harvest-interval`: Override intelligence discovery period
  - `--target-buffer`: Override target stock level
  - `--niche`: Switch active content and discovery profile
- Integrated `--runtime` flag directly into `main.py` dispatcher (`python main.py --runtime`).

---

## Test & Verification Matrix

Targeted test suite `tests/test_autonomous_runtime.py` comprehensively verifies all requirements:

| Test ID | Test Name | Verification Focus | Result |
|---|---|---|---|
| `test_01` | `test_01_config_from_env` | Configuration parsing, type coercions, and ENV override handling | **PASSED** |
| `test_02` | `test_02_service_lifecycle_and_shutdown` | Heartbeat generation, PID capture, lock acquisition, graceful stop | **PASSED** |
| `test_03` | `test_03_crash_recovery_resumes_incomplete_job` | In-flight intermediate job resumption with state idempotency | **PASSED** |
| `test_04` | `test_04_periodic_intelligence_harvest` | DiscoveryProfile-driven topic discovery and evidence filtering | **PASSED** |
| `test_05` | `test_05_production_queue_replenishment` | Target buffer stock deficit detection and batch creation | **PASSED** |
| `test_06` | `test_06_scheduled_publishing_and_daily_limit_guard` | Publication scheduling and strict DAILY_SHORTS_LIMIT guard | **PASSED** |
| `test_07` | `test_07_eligible_failed_job_auto_recovery` | Exponential backoff recovery for eligible failed jobs | **PASSED** |
| `test_08` | `test_08_queue_pause_interlock` | Mission Control queue pause enforcement halting production | **PASSED** |
| `test_09` | `test_09_mission_control_runtime_telemetry` | API endpoint `/api/mission-control/runtime` telemetry integrity | **PASSED** |
| `test_10` | `test_10_ast_architectural_audit` | AST verification confirming 100% niche agnosticity | **PASSED** |

### Regression Test Suite
- `tests/test_mission_control.py`: **17/17 Passed** (0 regressions across all Step 4 views and controls).

---

## Exact Commands to Start the Autonomous Runtime

### Production Service (Persistent Autonomous Worker)
To run the autonomous runtime as a continuous daemon/service:
```bash
python -m runtime.cli
```
*Alternatively via the main dispatcher:*
```bash
python main.py --runtime
```

### Dry-Run & Staging Verification (Zero External API / Zero Side Effects)
To run in dry-run mode (safe mock rendering, zero YouTube uploads, zero AI spend):
```bash
python -m runtime.cli --dry-run
```

### Single-Cycle Execution (Cron / CI / Health-Check)
To execute a single loop tick (recovery, harvest, replenish, publish, report) and exit:
```bash
python -m runtime.cli --once --dry-run
```

### Parameter Overrides
```bash
python -m runtime.cli --interval 30 --target-buffer 8 --niche CURRENT_AFFAIRS
```
