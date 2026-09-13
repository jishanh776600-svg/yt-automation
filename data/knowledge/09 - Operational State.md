# 09 — Operational State

> **Status:** `[SINGLE SOURCE OF TRUTH]` `[LIVE VERIFIED]`  
> **Last Audited:** `2026-09-13 22:30 UTC`  
> **Overall Verdict:** **`🟢 LIVE / CLOUD-AUTONOMOUS`** `[LIVE VERIFIED]`  
> **Authoritative Commit:** **`b4dd8f6306368859f07352adf42deb0b1de6199a`** on `origin/main` `[CODE VERIFIED]`  
> **Production Voice:** **`af_bella`** (`APPROVED_PRODUCTION_VOICES = ["af_bella"]`) `[LIVE VERIFIED]`  
> **Autorefill Mechanism:** **`WORKING / VERIFIED`** (GitHub Actions cron `0 */3 * * *`, bot commits verified) `[LIVE VERIFIED]`  
> **Master Reference:** [[07 — MISSION CONTROL/Operational State & Inventory|Operational State & Inventory]]

---

## 1. Google Drive Vault Inventory & State Verification

| Vault Tier | Folder Path | Operational Status | Safeguards & Notes |
|---|---|---|---|
| **00_SYSTEM** | `YouTube_Shorts_Vault/00_SYSTEM` | Synchronized | Contains `youtube_automation.db`, `visual_memory.db`, `short_fingerprints.db`, and `locks/`. |
| **01_READY** | `YouTube_Shorts_Vault/01_READY` | Verified Reserve | Holds QA-verified Shorts awaiting scheduling. Target = 6. 7 falsely-published Bella Shorts recovered here `[CODE VERIFIED]`. |
| **02_PROCESSING** | `YouTube_Shorts_Vault/02_PROCESSING` | Claimed / In-Flight | In-flight scheduled uploads. Videos remain here until confirmed public on YouTube. |
| **03_PUBLISHED** | `YouTube_Shorts_Vault/03_PUBLISHED` | Public Releases Only | **Hard physical barrier** enforced via `core/lifecycle_gateway.py`. Only verified public YouTube videos admitted. |
| **04_FAILED** | `YouTube_Shorts_Vault/04_FAILED` | Quarantined Assets | Irrecoverable container failures safely isolated. Never returned to `01_READY`. |

---

## 2. Lifecycle Hardening & Safeguards Verified

- **Authoritative Publication Gateway:** Direct folder moves to `03_PUBLISHED` raise `InvariantViolationError` unless passing through `core.lifecycle_gateway`.
- **YouTube Read-Back Verification:** Only videos confirmed public on YouTube (`privacyStatus == 'public'`) can enter `03_PUBLISHED`.
- **7 Bella Assets Restored:** Recovered from premature `03_PUBLISHED` state back to `01_READY` with full DB transaction reconciliation.
- **Pre-READY Content Quality Gate:** Verifies semantic era/visual alignment, phonetic TTS normalization, dynamic storyboard pacing, loop endings, and [22.0, 27.0]s duration.
- **Authoritative Voice Whitelist:** `APPROVED_PRODUCTION_VOICES = ["af_bella"]`. Any unapproved voice request fails closed to `af_bella`.
- **Stale Daemon Guard:** Heartbeat and PID validation blocks orphaned local processes from mutating production state.

---

## 3. Git Repository & Deployment State

- **Branch:** `main` (Synchronized with `origin/main`)
- **Authoritative Commit:** **`b4dd8f6306368859f07352adf42deb0b1de6199a`** (`fix(voice): restore af_bella as single authoritative production voice and finalize content quality upgrade`)
- **Refill Cadence:** Every 3 hours (`0 */3 * * *`) via `produce_buffer.yml` (Status: `WORKING / VERIFIED`).
- **Publishing Cadence:** Daily at `06:00, 11:00, 15:00 UTC` via `autopilot.yml`.