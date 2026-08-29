# Autonomous Cloud Production Architecture Guide

**System Name**: Historia YouTube Shorts Autonomous Pipeline  
**Version**: Phase 10.12  
**Repository**: `jishanh776600-svg/yt-automation` (Public, Secret-Decoupled)  
**Execution Environment**: GitHub Actions Ubuntu Runners (`ubuntu-latest`)  
**Persistent Storage**: Google Drive Cloud Vault (`YouTube_Shorts_Vault/`)  
**Observability**: FastAPI Mission Control (Render Blueprint)  

---

## 1. High-Level Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                            GITHUB ACTIONS CLOUD ENGINE                            |
|                                                                                   |
|  +-----------------------+  +-----------------------+  +-----------------------+  |
|  |   produce_buffer.yml  |  |     autopilot.yml     |  | harvest_analytics.yml |  |
|  |       (02:00 UTC)     |  | (06,10,15,20 UTC)     |  |       (03:00 UTC)     |  |
|  +-----------+-----------+  +-----------+-----------+  +-----------+-----------+  |
|              |                          |                          |              |
|              +--------------------------+--------------------------+              |
|                                         |                                         |
|                 Unified Concurrency: pipeline-cloud-execution                     |
+-----------------------------------------+-----------------------------------------+
                                          |
                        Fail-Closed DB Download & Upload
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        GOOGLE DRIVE PRIVATE CLOUD VAULT                           |
|                                                                                   |
|  - 00_SYSTEM/pipeline.db   <- Canonical SQLite Database (SHA256 & Integrity Ver.) |
|  - 01_READY/               <- Rendered & QA-Approved Shorts (Buffer Target: 12)   |
|  - 02_PROCESSING/          <- Claimed Shorts Currently In-Flight / Scheduled      |
|  - 03_PUBLISHED/           <- Released YouTube Shorts with Metadata               |
|  - 04_FAILED/              <- Quarantined Media with Permanent Verification Errs  |
+-----------------------------------------------------------------------------------+
                                          |
                          YouTube Scheduled Publishing API
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                           YOUTUBE PRODUCTION CHANNEL                              |
|                                                                                   |
|  - 4 Daily Slots: 06:00, 10:00, 15:00, 20:00 UTC (Directly on YouTube)            |
|  - Non-Public Privacy: privacyStatus='private' + publishAt RFC3339 UTC            |
|  - YouTube Native Release: YouTube automatically transitions to PUBLIC at slot     |
+-----------------------------------------------------------------------------------+
```

---

## 2. Autonomy Classification Matrix

| Subsystem / Operation | Operational Classification | Recovery Behavior |
| :--- | :--- | :--- |
| **Topic Discovery & Deduplication** | **FULLY AUTOMATED** | Self-healing: Entity-aware deduplication against all 298 historical topics prevents topic recycling. |
| **Script Generation & Verification** | **FULLY AUTOMATED** | Self-healing: Adversarial fact-checker with deterministic fallback if Gemini rate-limited. |
| **Voice Synthesis (Kokoro TTS)** | **FULLY AUTOMATED** | Self-healing: Local CPU model download and synthesis with auto-retry. |
| **Video Assembly (FFmpeg)** | **FULLY AUTOMATED** | Self-healing: Strict 1080x1920 MP4 rendering with pre-upload media integrity probe. |
| **Buffer Maintenance (Target: 12)** | **FULLY AUTOMATED** | Self-healing: Dynamically calculates deficit (`12 - ready_count`) and generates exact delta. |
| **Database Sync (Google Drive)** | **FULLY AUTOMATED** | Automatically Recoverable: Atomic replacement, WAL truncation, SHA256 validation. Fail-closed. |
| **YouTube Slot Scheduling** | **FULLY AUTOMATED** | Automatically Recoverable: Idempotent channel search prevents duplicate uploads on dropped HTTP connections. |
| **Stale Processing Recovery** | **AUTOMATICALLY RECOVERABLE** | Self-healing: Abandoned files in `02_PROCESSING` auto-reconciled and restored to `01_READY`. |
| **Transient Network Errors** | **AUTOMATICALLY RECOVERABLE** | Self-healing: Exponential backoff with jitter. Files returned to `01_READY` for subsequent slot retry. |
| **Analytics Harvesting** | **AUTOMATICALLY RECOVERABLE** | Self-healing: Per-video exception isolation. A deleted video never aborts the remaining harvest. |
| **OAuth Credential Expiration** | **REQUIRES HUMAN INTERVENTION** | Fails closed safely. Operator must update `TOKEN_JSON` in GitHub Secrets if refresh token revoked. |
| **API Quota Exhaustion (Pexels/YouTube)** | **REQUIRES HUMAN INTERVENTION** | Fails closed safely without state corruption. Resumes automatically when quota resets. |

---

## 3. Core Safety & Resilience Invariants

1. **Zero Laptop Dependency**:
   - The host machine / laptop is never required for normal production, scheduling, rendering, or publishing.
   - All pipelines execute on GitHub-hosted Linux VMs (`ubuntu-latest`).

2. **Decoupled Database Persistence**:
   - `pipeline.db` is strictly untracked in Git (`.gitignore`).
   - Every runner downloads canonical state from `00_SYSTEM/pipeline.db`, validates SQLite integrity (`PRAGMA integrity_check;`), executes its workload, flushes WAL (`PRAGMA wal_checkpoint(TRUNCATE);`), and uploads back to Drive in-place.

3. **Concurrency Elimination**:
   - Unified concurrency group `pipeline-cloud-execution` ensures GitHub Actions queues overlapping workflows, preventing race conditions or split-brain database states.

4. **Upload Idempotency**:
   - `schedule_short()` searches the channel prior to uploading and immediately after any dropped connection.
   - Videos already scheduled or public on the channel are reconciled without duplicate uploading.

5. **Safe Vault State Transitions**:
   - `01_READY` -> `02_PROCESSING` (atomic move during slot claim)
   - `02_PROCESSING` -> `03_PUBLISHED` (upon YouTube release confirmation)
   - `02_PROCESSING` -> `01_READY` (upon transient upload network error)
   - `02_PROCESSING` -> `04_FAILED` (ONLY on permanent media corruption)
