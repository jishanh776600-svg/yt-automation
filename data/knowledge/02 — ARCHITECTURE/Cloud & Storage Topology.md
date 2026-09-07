---
aliases:
  - Architecture Topology
  - Storage Tiers
tags:
  - architecture
  - cloud
  - storage
last_updated: 2026-09-07
---

# 02 — Cloud & Storage Topology

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Multi-tier architectural topology, storage segregation, and data flow between cloud runners and Google Drive `[CODE VERIFIED]`.

---

## 1. Three-Tier Architectural Topology

AL-AMR enforces strict separation of concerns across three distinct storage tiers:

```
+---------------------------------------------------------------------------------------------------+
| THREE-TIER SYSTEM ARCHITECTURE                                                                    |
+---------------------------------------------------------------------------------------------------+
| [TIER 1: EPHEMERAL CLOUD COMPUTE]  GitHub Actions Runners (ubuntu-latest)                         |
|   - Zero persistent runner disk state; spins up on scheduled cron triggers or workflow_dispatch.  |
|   - Installs FFmpeg, DejaVu fonts, Python 3.11, and pip dependencies.                             |
|   - Synchronizes database from Drive, executes work, and commits updated state back to Drive.     |
|   - Live Verified: Run #47 successfully executed in 14m 26s without local machine interaction.     |
|                                                                                                   |
| [TIER 2: DURABLE ASSET VAULT]  Google Drive Cloud Storage (YouTube_Shorts_Vault)                   |
|   - 00_SYSTEM/         : Canonical SQLite DB, auxiliary DBs, and distributed lock manifests.      |
|   - 01_READY/          : Verified reserve of QA-passed 1080x1920 MP4 Shorts (Target >= 6).        |
|   - 02_PROCESSING/     : In-flight Shorts currently scheduled or uploading to YouTube.            |
|   - 03_PUBLISHED/      : Permanent archive of live, reconciled YouTube Shorts.                    |
|   - 04_FAILED/         : Quarantined assets failing QA or safety checks (never return to READY).    |
|                                                                                                   |
| [TIER 3: KNOWLEDGE BRAIN]  Obsidian Knowledge Vault (data/knowledge)                              |
|   - Human-readable Markdown knowledge records with bi-directional wikilinks.                       |
|   - Maintains operational memory, decision logs, failure forensics, and system invariants.        |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Ephemeral Runner Lifecycle

Every GitHub Actions execution follows a strict transactional lifecycle:
1. **Runner Provisioning:** Spins up `ubuntu-latest`, checks out repository, configures Python 3.11, installs system packages (`ffmpeg`, `fonts-dejavu-core`).
2. **Lock Acquisition:** Checks Google Drive `00_SYSTEM/locks/` via `CloudLockManager`. If uncontested or stale (>900s), writes lock manifest and spawns background heartbeat `[LIVE VERIFIED]`.
3. **State Hydration:** Downloads `youtube_automation.db` and auxiliary DBs from `00_SYSTEM` to runner disk.
4. **Production / Publishing Execution:** Runs sequential pipeline operations.
5. **State Persist & Reconciliation:** Computes SHA256 of updated databases, uploads to `00_SYSTEM`, and confirms remote integrity.
6. **Lock Teardown:** Releases cloud lock in `finally:` block, cleanly terminating runner.