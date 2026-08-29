# Autonomous Cloud Disaster Recovery Guide

**System**: Historia YouTube Shorts Automation  
**Repository**: `jishanh776600-svg/yt-automation` (Public, Decoupled)  
**Primary Persistence**: Google Drive `YouTube_Shorts_Vault/00_SYSTEM/pipeline.db`  
**Revision**: Phase 10.13  

---

## 1. Zero-Local-State Philosophy

The production pipeline is designed to assume the local developer workstation / laptop has been permanently destroyed or disconnected.
All state, configuration, rendering, scheduling, and learning cycles operate autonomously within ephemeral cloud runners.

### Triad of Persistence
1. **Public Code Repository** (`origin/main`): Contains all code, deterministic templates, workflows, and test suites. Strictly zero secrets and zero database files.
2. **GitHub Repository Secrets**: Securely injects `TOKEN_JSON`, `CLIENT_SECRET_JSON`, `GEMINI_API_KEY`, `PEXELS_API_KEY`, and `DASHBOARD_ADMIN_PASSWORD_HASH`.
3. **Private Google Drive Vault** (`YouTube_Shorts_Vault/`):
   - `00_SYSTEM/pipeline.db`: Canonical, authoritative SQLite state containing all 298+ historical topics, 170+ scripts, 237+ jobs, 294+ uploads, and 639+ performance snapshots.
   - `01_READY/`: Rendered production Shorts awaiting release.
   - `02_PROCESSING/`: In-flight or scheduled uploads.
   - `03_PUBLISHED/`: Archival record of released videos.
   - `04_FAILED/`: Quarantined media.

---

## 2. Disaster Scenarios & Recovery Procedures

### Scenario A: Total Loss of Developer Workstation (Laptop Death)
- **Classification**: **FULLY AUTOMATED / ZERO HUMAN INTERVENTION**
- **Impact**: Zero impact on production.
- **Mechanism**: Cloud workflows (`autopilot.yml`, `produce_buffer.yml`, `harvest_analytics.yml`) continue executing on GitHub Actions schedules according to UTC crons.

### Scenario B: Ephemeral Runner Dies Mid-Execution
- **Classification**: **AUTOMATICALLY RECOVERABLE**
- **Impact**: In-flight job remains in `02_PROCESSING` or SQLite transaction aborts locally on the dead runner.
- **Recovery Path**:
  1. Because database upload occurs at the end of the workflow, the remote canonical database in Google Drive remains 100% clean and uncorrupted.
  2. The next scheduled runner automatically executes `RecoveryManager.recover_stale_processing_vault()`.
  3. Abandoned video in `02_PROCESSING` is safely returned to `01_READY`.

### Scenario C: Dropped Network Connection During YouTube Video Insert
- **Classification**: **AUTOMATICALLY RECOVERABLE**
- **Impact**: YouTube receives and schedules the Short, but the HTTP response drops before reaching the client runner.
- **Recovery Path**:
  1. `UploadEngine.schedule_short()` catches the exception and immediately queries the YouTube channel API.
  2. The search inspects both the video's normalized title and embedded `[JOB_ID: ...]` in the snippet description.
  3. Upon finding the match, it reconciles the `UploadRecord` as `SCHEDULED` without duplicating the upload.

### Scenario D: Google OAuth Refresh Token Revocation
- **Classification**: **HUMAN INTERVENTION REQUIRED**
- **Condition**: User manually revokes the OAuth client in Google Cloud Console or token expires after 6 months of complete inactivity.
- **Symptom**: Cloud workflows fail fast during `auth_youtube.py` check.
- **Remediation Procedure**:
  1. Run `python -m tools.auth_youtube` locally once to obtain new `token.json`.
  2. Update the `TOKEN_JSON` secret in GitHub Settings > Secrets and Variables > Actions.
  3. Re-run `verify_database_sync.yml` to confirm connectivity.

### Scenario E: Canonical Database Rollback
- **Classification**: **AUTOMATICALLY RECOVERABLE**
- **Mechanism**: Google Drive maintains native file revision history for `00_SYSTEM/pipeline.db`. Any prior version can be restored in 1 click from Google Drive web interface.
