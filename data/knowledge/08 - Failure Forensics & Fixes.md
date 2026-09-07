# 08 — Failure Forensics & Fixes

> **Status:** `[VERIFIED & DOCUMENTED]`  
> **Scope:** Forensic post-mortems of real production failures and their permanent engineering solutions.  

---

## 1. Incident 1: "The Kettle War of 1784" Reselection Storm

### Root Cause
During an automated buffer production run, the candidate topic *"The Kettle War of 1784"* failed script validation due to duration and fact formatting issues. Because the producer loop did not maintain run-level quarantine across batch iterations, the topic engine deterministically reselected the same failing topic on every loop iteration, exhausting retry limits and tripping the global consecutive-failure circuit breaker.

### Engineering Fix
Implemented run-level `attempted_topic_ids: Set[str]` in both `produce_batch()` and `maintain_buffer()`. Any topic evaluated during a run is quarantined from subsequent iterations in that same execution, enabling automatic advancement to the next candidate topic.

---

## 2. Incident 2: YouTube Analytics HTTP 403 `accessNotConfigured`

### Root Cause
`token.json` possessed the valid `yt-analytics.readonly` OAuth scope, but Google Cloud Project `1044637695745` had `youtubeanalytics.googleapis.com` disabled by default, causing authenticated queries to return HTTP 403.

### Engineering Fix
Diagnosed through API boundary tests without regenerating tokens or altering OAuth architecture. Human operator enabled the API service via Google Cloud Console, and subsequent live queries succeeded with HTTP 200.

---

## 3. Incident 3: ProcessLock Dangling Exception Vulnerability

### Root Cause
In `main.py:maintain_buffer()`, `initial_stock = self.drive_engine.get_ready_stock_count()` was located before the `try...finally` block that manages `lock.release()`. If an exception occurred during the initial Drive query, the lock remained acquired on disk.

### Engineering Fix
Moved `try:` to wrap immediately after `lock.acquire()`, ensuring `finally: lock.release()` unconditionally executes under all error conditions.

---

## 4. Incident 4: BGM Loudness Inconsistency

### Root Cause
Raw BGM library tracks had intrinsic loudness levels spanning $-19.2\text{ LUFS}$ to $-12.1\text{ LUFS}$. The old static `-13.0 dB` attenuation produced loud BGM on certain tracks, competing with narration.

### Engineering Fix
Introduced `TARGET_BGM_LUFS = -30.0` in `config/constants.py` and implemented EBU R128 Stage B bed normalization in `AudioMixer.generate_stage_b_bgm_only()`.

---

## 5. Incident 5: Production HTTP 500 — `python-dateutil` Missing from `requirements.txt`

**Date:** 2026-09-03  
**Commit Fixed:** `80b1f65`

### Root Cause
`dashboard/data_provider.py` and `engines/scheduler_engine.py` called `dateutil.parser.isoparse(...)` but `python-dateutil` was never listed in `requirements.txt`. The Render production container did not install it, causing every dashboard and API request to throw an `ImportError` and return HTTP 500.

### Engineering Fix
- Replaced all `dateutil.parser.isoparse(...)` calls with a stdlib-only helper `_parse_yt_iso(ts)` using Python 3.11's `datetime.fromisoformat()` plus explicit `Z`→`+00:00` normalisation.
- Zero new dependencies added.
- Edge cases verified: `Z`, `+00:00`, `+05:30`, naive ISO strings.

### Validation
`/health`, `/login`, `/`, `/api/state` all returned HTTP 200 on the live Render deployment after commit.

---

## 6. Incident 6: Bella Voice Default Broken + Cross-Voice Duplicate Scheduling

**Date:** 2026-09-03  
**Commit Fixed:** `2f1098e`

### Root Causes (5 layers)
1. SQLite `SystemConfig` had a stale persistent row `active_voice = am_adam`.
2. `get_active_voice(db)` in `engines/tts_engine.py` returned the DB value directly without guarding against stale `am_adam`.
3. `generate_kokoro_audio()` had `voice: str = "am_adam"` as its default parameter.
4. Edge-TTS fallback defaulted to `"en-US-GuyNeural"` (Adam) instead of `"en-US-JennyNeural"` (Bella).
5. `topic_discovery.py` excluded only `["PUBLISHED", "READY_TO_UPLOAD"]` job states — completely missing `SCHEDULED`, `RENDERED_QA_PASSED`, etc. — and did NOT check `UploadRecord`, allowing the same story to be re-discovered and re-produced with a different voice, creating duplicate scheduled Shorts.
6. Gate 15 in `upload_engine.py` checked only `["PUBLISHED", "SUCCESS"]` and only used exact-string title match, missing `SCHEDULED` items and semantic title variants (e.g. `"Was Truly Unbelievable"` suffix).
7. `schedule_ready_buffer()` in `main.py` only checked `job_id` equality, failing when a Drive file had a different `job_id` or slightly different title.

### Engineering Fix
- `get_active_voice()`: Added explicit guard — if DB returns `am_adam`, coerce to `af_bella`.
- `generate_kokoro_audio()`: Changed default to `voice: str = "af_bella"`.
- `generate_narration()` and `generate_preview_sample()`: Changed Edge-TTS fallback to `"en-US-JennyNeural"`.
- `ShortsPipeline.__init__()`: Added dual guard — reject `am_adam` from both DB lookup and env var paths.
- `discover_topics()`: Expanded excluded states to all active/in-flight/scheduled/published states + `UploadRecord` cross-reference.
- Gate 15: Added `SCHEDULED` and `TEST_VERIFIED` to status check; added `StoryDeduplicationEngine` semantic check.
- `schedule_ready_buffer()`: Added full semantic dedup against all `UploadRecord` entries; added intra-batch dedup to prevent scheduling two videos of the same story in one run.
- SQLite `SystemConfig`: Set `active_voice = af_bella` via `set_active_voice()`.

### Validation
8/8 targeted tests passed locally. YouTube duplicate Shorts on 2026-09-03 require manual operator cleanup.

---

## 7. Incident 7: Refill Completely Broken — False-COMPLETED Topic Pollution + Self-Matching Dedup

**Date:** 2026-09-03  
**Commit Fixed:** `f554d99` (hotfix)

### Root Cause
Incident 6's fix introduced two critical bugs in `discover_topics()` in `engines/topic_discovery.py`:

1. **`exclude_topic_id=t.id` removed**: The deduplication call `self.is_duplicate(db, t.title, t.summary)` had `exclude_topic_id=t.id` removed with a comment saying "do NOT exclude t.id". `get_published_and_ready_corpus()` queries ALL jobs in the DB (including `QUEUED`/`NEEDS_REVIEW`). So every APPROVED topic that had any attached job matched itself in the corpus and was flagged as a duplicate.

2. **Destructive `t.status = "COMPLETED"` mutation**: Every topic that failed the (now-broken) dedup check was permanently stamped `COMPLETED`. This burned 48 eligible topics from the pool in a single `discover_topics()` call, driving stock to zero with no recovery path.

### Engineering Fix
- Restored `exclude_topic_id=t.id` to the `is_duplicate` call.
- Removed `t.status = "COMPLETED"` side-effect entirely.
- Removed the `db.commit()` / `db.rollback()` block that persisted the false mutation.
- Repaired 48 falsely-COMPLETED topics in SQLite: topics with no actual `PUBLISHED`/`SUCCESS` `UploadRecord` were reset to `APPROVED` (if they had jobs) or `DISCOVERED` (if no jobs). 3 genuinely completed topics preserved.

### Validation
DB state after repair: APPROVED=16, DISCOVERED=427, COMPLETED=3, TOTAL=446. `topic_discovery.py` compiles cleanly. `produce_buffer.yml` unblocked.

### Key Lesson
Never mutate persistent DB state (topic.status) inside a candidate-filtering loop. Use in-memory exclusion sets only. Database status mutations must be deliberate, explicitly tested, and never triggered as a side-effect of a discovery scan.
---

## 8. Incident 8: Refill Both Failing — Cloud Lock Deadlock + Seed Exhaustion + Stale Dashboard

**Date:** 2026-09-07  
**Commit Fixed:** `31c002c`  
**Master Reference:** [[09 — INCIDENTS & FIXES/Incident 8 — Cloud Lock Deadlock & Seed Exhaustion|Incident 8 Full Post-Mortem]]

### Root Causes
1. **Cloud Lock Deadlock:** Prior aborted GitHub Actions runner left a dangling lock file in Google Drive `00_SYSTEM/locks/` with a 3600s TTL and no dead-runner detection. All subsequent buffer replenishment runs detected the lock and failed closed.
2. **Curated Seed Exhaustion:** All 10 curated historical seeds in `CURATED_HISTORICAL_SEEDS` had been used or quarantined. No fallback triggered.
3. **Render Dashboard Stale Reporting:** Dashboard was reading static test runs rather than live GitHub API workflow runs, masking failures, and the operator review queue had 123 unreviewed legacy jobs.

### Engineering Fix
- `core/cloud_lock.py`: Reduced TTL to 900s, added 120s background heartbeat thread, enabled GitHub API dead-runner reclamation, added `--force-unlock` CLI override and workflow input.
- `engines/topic_discovery.py` & `intelligence/cloud_orchestrator.py`: Expanded `CURATED_HISTORICAL_SEEDS` to 24 verified historical mysteries + added dynamic Gemini AI discovery fallback.
- `dashboard/data_provider.py` & `dashboard/action_manager.py`: Connected dashboard to live GitHub workflow telemetry; archived 119 legacy unreviewed review queue jobs.

### Live Validation
GitHub Actions Run #47 (`34054429381`) succeeded in 14m 26s, producing and depositing Bella Short `short_man_c85a0dd30bda.mp4` (Drive ID: `1I3X-S4OsuWUW4Ubv8v7nB-nI760dLMzx`) into `01_READY`.
---

## 9. Incident 9: False Publication Lifecycle Divergence — Self-Matching Dedup Fallback

**Date:** 2026-09-07  
**Commit Fixed:** Pending  
**Incident ID:** `inc_d7e91e6ed4a2`  
**Master Reference:** [[09 — INCIDENTS & FIXES/Incident Register & Forensic Log|Incident 9 Entry]]

### Symptoms
The internal AL-AMR system marked 7 verified Shorts as `PUBLISHED` (moving them into Google Drive `03_PUBLISHED` and causing the Dashboard and Obsidian to claim 22 published videos), while YouTube Studio showed that these 7 videos were **NEITHER public NOR scheduled**. Google Drive `01_READY` was drained to 0.

### Exact Root Cause
In `main.py` lines 1079–1102 (and lines 1005–1012), `schedule_ready_buffer()` pre-claim deduplication failed to pass `exclude_topic_id` to `evaluate_candidate()`, causing candidate files in `01_READY` to match their own `PRODUCED` topic in the corpus (which aggregates all topics with status `APPROVED`, `PRODUCED`, `SCHEDULED`, `QUEUED`).

Because the video files had never actually been uploaded to YouTube, querying `UploadRecord` for the matched title returned `None`. Lines 1094–1095 had an unsafe fallback:
```python
else:
    matched_is_published = True  # <--- CRITICAL BUG: Assumed published if no UploadRecord found!
```
This evaluated `(is_duplicate_story and matched_is_published)` to `True`, triggering line 1102:
```python
self.drive_engine.move_file_in_vault(candidate["id"], from_folder="01_READY", to_folder="03_PUBLISHED")
```
Every one of the 7 Shorts in `01_READY` matched its own `PRODUCED` topic, found no `UploadRecord`, tripped `else: matched_is_published = True`, and was moved directly into `03_PUBLISHED` in Google Drive without ever uploading or scheduling on YouTube.

### Engineering Fix
1. **Enforced Non-Negotiable Publication Invariant:**
   `move_file_in_vault(..., to_folder="03_PUBLISHED")` strictly requires an authoritative `UploadRecord` with a valid, non-null `youtube_video_id` and status in `["PUBLISHED", "SUCCESS"]`.
2. **Eliminated Deduplication Publication Bypass:**
   Removed any code path that moves an asset from `01_READY` or `02_PROCESSING` to `03_PUBLISHED` based solely on deduplication. Duplicate candidates in `01_READY` are quarantined to `04_FAILED`.
3. **Prevented Self-Matching in Pre-Claim:**
   Resolved `cand_topic_id` from candidate properties, manifest, or event ID and passed `exclude_topic_id=cand_topic_id` to `evaluate_candidate()`.
4. **Enhanced Corpus Exclusion:**
   Updated `engines/deduplication_engine.py` `get_published_and_ready_corpus()` to match either `Topic.id` or `Topic.event_id` against `exclude_topic_id`.
5. **Cleaned Up 02_PROCESSING Orphan Recovery:**
   Removed faulty `dup_proc_status` fallback in `02_PROCESSING`. Valid orphaned assets safely return to `01_READY`; invalid assets are quarantined to `04_FAILED`.
6. **Physical Asset Restoration:**
   Operator manually restored all 7 affected Bella Shorts back into `01_READY`.

### Validation
- All 7 Bella Shorts verified in Drive `01_READY`.
- `tests/test_preclaim_deduplication_invariant.py` (3 tests) passing 100%.
- `tests/test_production_hardening.py` (9 tests) passing 100%.
- Incident record `inc_d7e91e6ed4a2` committed to `pipeline.db`.