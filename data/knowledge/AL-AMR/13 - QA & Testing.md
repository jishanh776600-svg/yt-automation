---
aliases:
  - QA System
  - Quality Assurance
tags:
  - qa
  - testing
  - verification
last_updated: 2026-09-05
---

# 13 — Multi-Factor Video & Audio QA System

> **Status:** `[LIVE & ENFORCED]`  
> **Scope:** 15-point multi-factor video and audio quality gate, fail-closed thresholds, and targeted validation suites.

---

## 1. The 15-Point Production Safety Gate

Every rendered video must pass all 15 automated checkpoints before it is permitted into Google Drive `01_READY` or scheduled on YouTube:

| # | Inspection Check | Fail-Closed Threshold | Passing Specification |
|---|---|---|---|
| **1** | **Resolution** | Not `1080x1920` | Exactly `1080x1920` vertical |
| **2** | **Aspect Ratio** | Not `9:16` | Strictly `9:16` vertical Shorts |
| **3** | **Total Duration** | $< 22.0$s or $> 25.0$s | $22.0$s to $25.0$s (Target: ~23.2s) |
| **4** | **Max Narration Pause** | $\ge 0.35$s (350ms) | Strictly $< 0.35$s maximum silence |
| **5** | **Dead Air Ratio** | $> 18.0\%$ of runtime | Cumulative dead air $\le 18.0\%$ |
| **6** | **Voice Lock** | Non-`af_sarah` audio | Authoritative `af_sarah` verified |
| **7** | **Master Loudness** | Outside `[-22.0, -10.0]` LUFS | Target: `-14.0 LUFS` integrated |
| **8** | **True Peak Ceiling** | $> 0.0$ dBTP | True Peak $\le 0.0$ dBTP (Target: $-1.0$ dBTP) |
| **9** | **Black Frame Detection** | $\ge 1$ black frame | $0$ completely black or blank frames |
| **10**| **AV Desynchronization** | Speech cut off at tail | Speech completes $\ge 0.4$s before video end |
| **11**| **Scene Cut Density** | $< 9$ unique visual cuts | Minimum $9$ unique scenes (Target: 10–12) |
| **12**| **Intra-Short Visuals** | Duplicate asset inside Short | $100\%$ unique visual assets per video |
| **13**| **Global Visual Cooldown**| Asset reused within 45 days | Zero recently used visual assets |
| **14**| **BGM Presence** | No background music detected | BGM present and ducked 12–16dB below voice |
| **15**| **Duplicate Protection** | Topic/script similarity $\ge 0.60$ | Unique story shingles in `short_fingerprints.db` |

---

## 2. Hard Fail-Closed Enforcement

Implemented in [`intelligence/video_qa.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/video_qa.py):
- Any video failing even one check is rejected instantly.
- The rejected file is moved directly to `04_FAILED/` and logged in SQLite with a detailed `qa_report_json`.
- A failed file is never deposited into `01_READY` and can never be claimed by the scheduler.

---

## 3. Targeted Test Suite Verification

AL-AMR maintains focused test suites verifying core invariants without running full 200+ end-to-end regression suites:

| Test Module | Tests | Focus Area | Result |
|---|---|---|---|
| `test_m1_sync_and_lock.py` | 14 | Database sync, auxiliary DBs, composite locking | **14/14 PASSED** |
| `test_m1_adversarial_locking.py` | 26 | Stale lock recovery, consensus races, drive errors | **26/26 PASSED** |
| `test_m1_adversarial_sync_and_vault.py`| 26 | WAL checkpoints, Sarah preservation, quarantine | **26/26 PASSED** |
| `test_production_readiness_patch.py` | 6 | Niche purity, Council gate, 48h horizon | **6/6 PASSED** |
| `test_production_voice_lock.py` | 13 | Sarah exclusive lock, retired voices eliminated | **13/13 PASSED** |
| `test_cloud_autonomy.py` | 7 | Headless runners, zero desktop dependencies | **7/7 PASSED** |
| `test_cloud_production_validation.py` | 11 | Sequential refill, stop-at-6, recovery | **11/11 PASSED** |
| **Total Targeted Verification** | **103** | **Production-Readiness Suite** | **103/103 PASSED** |

---

## 4. Architectural Links
- Master Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Audio Standards: [[06 - Audio & Voice|Audio & Voice]]
- Visual Standards: [[07 - Visual System|Visual System]]
- Production Pipeline: [[09 - Production Pipeline|Production Pipeline]]