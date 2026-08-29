# Autonomous Cloud Production Operations Runbook

**Repository**: `jishanh776600-svg/yt-automation`  
**Operating Mode**: 100% Unattended Cloud Production  
**Phase**: 10.13  

---

## 1. Routine Autonomous Schedules (UTC)

| Schedule (UTC) | IST Time | Workflow | Purpose | Invariants Maintained |
| :--- | :--- | :--- | :--- | :--- |
| **02:00 UTC** | 07:30 AM | `produce_buffer.yml` | Buffer Refill | Refills `01_READY` to target 12 via Kokoro TTS & FFmpeg. |
| **03:00 UTC** | 08:30 AM | `harvest_analytics.yml` | Performance Harvester | Harvests Data API & Analytics API metrics; runs closed learning loop. |
| **06:00 UTC** | 11:30 AM | `autopilot.yml` | Morning Release Slot | Claims next `01_READY` Short; schedules directly on YouTube. |
| **10:00 UTC** | 03:30 PM | `autopilot.yml` | Midday Release Slot | Claims next `01_READY` Short; schedules directly on YouTube. |
| **15:00 UTC** | 08:30 PM | `autopilot.yml` | Evening Release Slot | Claims next `01_READY` Short; schedules directly on YouTube. |
| **20:00 UTC** | 01:30 AM | `autopilot.yml` | Night Release Slot | Claims next `01_READY` Short; schedules directly on YouTube. |

---

## 2. Operational Classifications

### A. FULLY AUTOMATED (Zero Stimulus)
- Script creation and adversarial fact checking
- High-fidelity FFmpeg rendering with Ken Burns zoom & audio ducking
- Automatic deposit to Google Drive `01_READY`
- YouTube release slot calculation (06:00, 10:00, 15:00, 20:00 UTC)
- YouTube private scheduling (`privacyStatus: private` + RFC3339 `publishAt`)
- Canonical SQLite database download and upload sync with Google Drive `00_SYSTEM`
- SQLite WAL checkpointing and integrity check before upload
- Concurrency serialization via GitHub Actions `pipeline-cloud-execution`

### B. AUTOMATICALLY RECOVERABLE (Self-Healing)
- **Drive API 503 Outages**: Retried with exponential backoff & jitter via `core.retry.retry_call`.
- **YouTube Upload Connection Timeout**: Reconciled via channel search with `[JOB_ID: ...]`.
- **Transient Upload Failures**: Rendered MP4 safely returned to `01_READY` instead of quarantined.
- **Stale Processing Vault**: Abandoned files in `02_PROCESSING` auto-restored to `01_READY`.
- **Single Bad Video Analytics Failure**: Logged and skipped; remaining 200+ videos harvested cleanly.

### C. HUMAN INTERVENTION REQUIRED (Exceptional Events Only)
1. **Google OAuth Client Revocation**: Re-authenticate via `python -m tools.auth_youtube` and update `TOKEN_JSON` secret in GitHub.
2. **Monthly Pexels Quota Exhaustion (20,000 requests)**: Automatic fallback to AI image generation (`Pollinations.ai`) activates; operator can optionally upgrade Pexels tier.
3. **Daily YouTube API Quota Exhaustion (10,000 units)**: Quota auto-resets at midnight Pacific Time (07:00 UTC). System halts non-urgent uploads and resumes autonomously.

---

## 3. Mission Control Telemetry

The Mission Control dashboard (`/` and `/mobile`) exposes:
- **Cloud Database Sync Telemetry**:
  - `canonical_vault_folder`: `00_SYSTEM`
  - `canonical_filename`: `pipeline.db`
  - `integrity_valid`: `True`
  - `sha256`: Checksum of canonical database
  - `table_counts`: Live counts of `topics`, `scripts`, `jobs`, `uploads`, `performance_snapshots`
- **Drive Vault Inventory**:
  - Breakdown across `01_READY`, `02_PROCESSING`, `03_PUBLISHED`, and `04_FAILED`.
- **Scheduler Queue**:
  - Next 4 occupied or scheduled slots.
