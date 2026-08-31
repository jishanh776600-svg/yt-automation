# 01 — Architecture

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** Multi-tier architectural topology, storage segregation, process locking, and concurrency boundaries.  

---

## 1. Storage & State Segregation

AL AMR enforces strict separation of concerns across three distinct storage tiers:

```
+---------------------------------------------------------------------------------------------------+
| THREE-TIER SYSTEM ARCHITECTURE                                                                    |
+---------------------------------------------------------------------------------------------------+
| [TIER 1: RELATIONAL STATE]  SQLite Database (data/history_shorts.db)                               |
|   - Stores jobs, topics, script drafts, assets, render metadata, QA reports, strategy weights.     |
|   - Atomically updated through SQLAlchemy ORM with ACID transaction boundaries.                    |
|   - Backed up to Google Drive (00_DATABASE_BACKUP) upon every successful cloud execution.         |
|                                                                                                   |
| [TIER 2: DURABLE ASSET VAULT]  Google Drive Cloud Storage (YouTube_Shorts_Vault)                   |
|   - 00_DATABASE_BACKUP : Authoritative database snapshots with SHA-256 manifests.                 |
|   - 01_READY           : Staging vault for 6 QA-passed, production-ready MP4 Shorts.              |
|   - 02_SCHEDULED       : Archive of Shorts successfully uploaded and scheduled on YouTube.        |
|   - 03_PUBLISHED       : Permanent archive of live, published YouTube Shorts.                     |
|   - 04_NEEDS_REVIEW    : Isolated quarantine vault for jobs failing QA or policy checks.          |
|                                                                                                   |
| [TIER 3: KNOWLEDGE BRAIN]  Obsidian Knowledge Vault (data/knowledge)                             |
|   - Human-readable Markdown knowledge records with bi-directional wikilinks.                      |
|   - Maintains operational memory, forensic post-mortems, decision logs, and system invariants.    |
|   - Synchronized to Google Drive as plain-text archival documentation.                            |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Process Concurrency & Atomic Locking

To prevent race conditions between scheduled cron jobs, manual workflow dispatches, and dashboard actions:
1. **ProcessLock**: Operating-system level file locking (`core/lock.py`) using `msvcrt` (Windows) and `fcntl` (Linux/POSIX).
2. **Dedicated Lock Names**:
   - `production`: Protects buffer maintenance (`--maintain-buffer`) and batch rendering.
   - `publishing`: Protects schedule execution (`--schedule-ready`) and YouTube uploads.
   - `analytics`: Protects telemetry harvesting and learning engine updates.
3. **Encapsulation Contract**: All locked routines acquire the lock immediately and encapsulate all queries, processing, and file writes within a `try...finally: lock.release()` block to guarantee atomic release even under unhandled exceptions.

---

## 3. GitHub Actions Orchestration Topology

Autonomous operations execute in GitHub Actions runners (`ubuntu-latest` with Python 3.13 and FFmpeg):

| Workflow File | Trigger Schedule | Primary Command Executed | Responsibility |
|---|---|---|---|
| `.github/workflows/produce_buffer.yml` | `0 2 * * *` (Daily 02:00 UTC) | `python main.py --maintain-buffer 6` | Audits `01_READY`, computes deficit, produces replacement Shorts to restore stock to 6. |
| `.github/workflows/autopilot.yml` | `0 6,11,15 * * *` (Daily 3 slots) | `python main.py --schedule-ready` | Checks daily publishing limit ($\le 3$), claims 1 Short from `01_READY`, schedules it on YouTube. |
| `.github/workflows/harvest_analytics.yml` | `0 4 * * *` (Daily 04:00 UTC) | `python main.py --harvest-analytics` | Harvests video-level and channel-level YouTube Analytics, applies 24h maturation gate, updates UCB1 weights. |

---

## 4. Local Operations Console & Dashboard

- **Framework**: FastAPI + Starlette + Tailwind CSS + Chart.js
- **Entry Point**: `dashboard/app.py` (Port 8000)
- **Data Provider**: `dashboard/data_provider.py` (`SystemDataProvider` reading directly from SQLite with zero synthetic data).
- **Authentication**: PBKDF2-HMAC password hashing with 24-hour cryptographic session cookies (`dashboard/auth.py`).
- **Data Purity Guarantee**: Missing metrics are preserved as `None` / `"UNAVAILABLE"`. Zero is never substituted for missing views, AVD, or APV.