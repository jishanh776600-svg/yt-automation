# 09 — Operational State

> **Status:** `[SINGLE SOURCE OF TRUTH]`  
> **Last Audited:** `2026-09-03 22:18 IST (16:48 UTC)`  
> **Overall Verdict:** **`DEGRADED → RECOVERING`**

---

## 1. Google Drive Vault Inventory (`YouTube_Shorts_Vault`)

| Vault Tier | Folder Path | Item Count | Status | Notes |
|---|---|---|---|---|
| **00_DATABASE_BACKUP** | `YouTube_Shorts_Vault/00_DATABASE_BACKUP` | 1 File | Synchronized | Authoritative SQLite snapshot (`File ID: 1glg-Slh75f6FEVfCO17qyTTtbP0kO1DQ`). |
| **01_READY** | `YouTube_Shorts_Vault/01_READY` | **`0 Shorts`** | **`EMPTY — REFILL REQUIRED`** | Buffer exhausted due to Incident 7. `produce_buffer.yml` now unblocked. |
| **02_PROCESSING** | `YouTube_Shorts_Vault/02_PROCESSING` | Unknown | In-flight | Duplicate Bella+Adam Shorts for same stories may be here pending operator cleanup. |
| **03_PUBLISHED** | `YouTube_Shorts_Vault/03_PUBLISHED` | Growing | Live | Live mature videos generating public analytics. |

---

## 2. YouTube Channel Inventory

- **Live Public Shorts**: `23` (as of 2026-09-03 ground truth)
- **Scheduled Pending Shorts**: `4` (includes confirmed duplicates — see Pending Actions)
- **Daily Publishing Quota**: `DAILY_SHORTS_LIMIT = 3` (unchanged)
- **Publishing Slots**: `06:00`, `11:00`, `15:00 UTC` (unchanged)
- **Known Duplicate Scheduled Shorts (2026-09-03)** — Require manual YouTube Studio cleanup:
  - `YA8yJ0rza3M` + `7ewqSD_NFSE` — "The Kentucky Meat Shower of 1876" (both 06:00 UTC, same story × 2 voices)
  - `ozdVFX9Hn1A` + `ae9MxslrT4A` — "The Liechtensteiner Army of 1866" (11:00 + 15:00 UTC, same story × 2 voices)

---

## 3. SQLite Database State (`data/pipeline.db`)

| Table | Key Stat | Notes |
|---|---|---|
| `Topic` | APPROVED: 16 / DISCOVERED: 427 / COMPLETED: 3 / TOTAL: 446 | 48 falsely-COMPLETED topics repaired on 2026-09-03 |
| `Job` | PUBLISHED: 182 / SCHEDULED: 1 / RENDERED_QA_PASSED: 4 / QUEUED: 55 / NEEDS_REVIEW: 110 | QUEUED/NEEDS_REVIEW are test/seed artefacts |
| `UploadRecord` | PUBLISHED: 43 / SUCCESS: 154 / SCHEDULED: 4 / PENDING: 25 | |
| `SystemConfig` | `active_voice = af_bella` | Repaired from stale `am_adam` on 2026-09-03 |

---

## 4. Git Repository State

- **Branch**: `main`
- **Remote**: Synchronized with `origin/main`
- **Working Tree**: Clean
- **Latest Commits** (most recent first):

| Commit | Description |
|---|---|
| `f554d99` | `hotfix(refill)`: restore exclude_topic_id, remove destructive status mutation |
| `2f1098e` | `fix(pipeline)`: enforce Bella voice + multi-layer dedup |
| `80b1f65` | `fix(dashboard)`: stdlib ISO parsing, resolve production HTTP 500 |
| `80de94b` | `fix(audio)`: standardize Stage B BGM bed loudness (-30.0 LUFS) |

---

## 5. Pending Manual Actions (Human Operator Required)

- [ ] **YouTube Studio**: Delete/cancel one of the two duplicate "Kentucky Meat Shower" scheduled videos (recommend deleting `7ewqSD_NFSE` — the one with doubled title suffix).
- [ ] **YouTube Studio**: Delete/cancel one of the two duplicate "Liechtensteiner Army" scheduled videos (recommend deleting `ae9MxslrT4A` — the one with doubled title suffix).
- [ ] **GitHub Actions**: Trigger `produce_buffer.yml` (workflow_dispatch) with `batch_count=3`, `active_voice=af_bella` to refill `01_READY` to at least 3 Shorts.