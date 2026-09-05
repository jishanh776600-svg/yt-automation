# 01 — Architecture

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Multi-tier architectural topology, storage segregation, distributed cloud locking, and concurrency boundaries.  
> **Master Reference:** [[03 - Architecture|Cloud Architecture & Distributed Locking]]

---

## 1. Storage & State Segregation

AL-AMR enforces strict separation of concerns across three distinct storage tiers:

```
+---------------------------------------------------------------------------------------------------+
| THREE-TIER SYSTEM ARCHITECTURE                                                                    |
+---------------------------------------------------------------------------------------------------+
| [TIER 1: EPHEMERAL CLOUD RUNNERS]  GitHub Actions Runners (ubuntu-latest)                         |
|   - Zero persistent runner disk state; spins up on scheduled cron triggers.                      |
|   - Installs FFmpeg, fonts, Python 3.11/3.13, and pip dependencies.                              |
|   - Synchronizes database from Drive, executes work, and commits updated state back to Drive.     |
|                                                                                                   |
| [TIER 2: DURABLE ASSET VAULT]  Google Drive Cloud Storage (YouTube_Shorts_Vault)                   |
|   - 00_SYSTEM/         : Canonical SQLite DB, auxiliary DBs, and distributed lock files.         |
|   - 01_READY/          : Verified reserve of QA-passed 1080x1920 MP4 Shorts (Target >= 6).       |
|   - 02_PROCESSING/     : In-flight Shorts currently scheduled or uploading to YouTube.           |
|   - 03_PUBLISHED/      : Permanent archive of live, reconciled YouTube Shorts.                   |
|   - 04_FAILED/         : Quarantined assets failing QA or safety checks (never return to READY).   |
|                                                                                                   |
| [TIER 3: KNOWLEDGE BRAIN]  Obsidian Knowledge Vault (data/knowledge)                             |
|   - Human-readable Markdown knowledge records with bi-directional wikilinks.                      |
|   - Maintains operational memory, decision logs, and system invariants.                          |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Distributed Locking (`CompositeLock`)

To prevent race conditions between scheduled cron jobs, manual workflow dispatches, and daemon loops:
1. **`CompositeLock`**: Integrates local PID process locking with Google Drive distributed `CloudLockManager`.
2. **Dedicated Lock Names**:
   - `production`: Protects buffer maintenance (`--maintain-buffer`) and batch rendering.
   - `publisher`: Protects schedule execution (`--schedule-ready`) and YouTube uploads.
   - `analytics`: Protects telemetry harvesting and learning engine updates.
3. **Fail-Closed Rollback**: If the cloud lock cannot be acquired or Drive network errors occur, any acquired local lock is rolled back immediately and execution exits safely.

---

## 3. GitHub Actions Orchestration Topology

| Workflow File | Trigger Schedule | Primary Command Executed | Responsibility |
|---|---|---|---|
| `.github/workflows/produce_buffer.yml` | `0 2 * * *` (Daily 02:00 UTC) | `python main.py --maintain-buffer 6` | Audits `01_READY`, computes deficit, produces replacement Shorts sequentially to restore stock to 6. |
| `.github/workflows/autopilot.yml` | `0 6,11,15 * * *` (Daily 3 slots) | `python main.py --schedule-ready` | Audits 48h forward horizon, claims ready Shorts, schedules them to YouTube with `publishAt`. |
| `.github/workflows/verify_database_sync.yml` | `workflow_dispatch` | `python -m core.database_sync verify`| Verifies round-trip sync integrity between runner disk and Google Drive `00_SYSTEM`. |