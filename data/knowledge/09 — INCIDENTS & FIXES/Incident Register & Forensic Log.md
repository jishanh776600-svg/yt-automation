---
aliases:
  - Incident Register
  - Failure Forensics
  - Historical Post-Mortems
tags:
  - incidents
  - post-mortem
  - forensics
last_updated: 2026-09-07
---

# Incident Register & Forensic Log (Incidents 1–7)

> **Status:** `[HISTORICAL POST-MORTEM REGISTER]`  
> **Scope:** Forensic post-mortems of production failures and permanent code fixes implemented prior to Incident 8 `[CODE VERIFIED]`.

---

## Incident 1: "The Kettle War of 1784" Reselection Storm
- **Root Cause:** Script validation failure caused the engine to deterministically reselect the same topic on every iteration, exhausting retry limits.
- **Permanent Fix:** Introduced run-level `attempted_topic_ids: Set[str]` in `produce_batch()` and `maintain_buffer()`.

---

## Incident 2: YouTube Analytics HTTP 403 `accessNotConfigured`
- **Root Cause:** Google Cloud Project `1044637695745` had `youtubeanalytics.googleapis.com` disabled by default.
- **Permanent Fix:** Service enabled via Google Cloud Console; verified with live HTTP 200 responses.

---

## Incident 3: ProcessLock Dangling Exception Vulnerability
- **Root Cause:** Drive stock count query occurred prior to `try...finally: lock.release()` block, leaving disk lock held on network exception.
- **Permanent Fix:** Wrapped lock acquisition immediately inside `try: ... finally: lock.release()`.

---

## Incident 4: BGM Loudness Inconsistency
- **Root Cause:** Raw tracks spanned -19.2 to -12.1 LUFS; static -13.0 dB attenuation caused audible masking.
- **Permanent Fix:** Enforced EBU R128 Stage B bed normalization to `-30.0 LUFS` in `AudioMixer`.

---

## Incident 5: Production HTTP 500 — `python-dateutil` Missing
- **Root Cause:** `dateutil.parser.isoparse` invoked without package listed in `requirements.txt`.
- **Permanent Fix:** Replaced with stdlib-only `datetime.fromisoformat()` helper with explicit UTC normalization.

---

## Incident 6: Bella Voice Default Broken & Cross-Voice Duplicate Scheduling
- **Root Cause:** SQLite SystemConfig had stale `am_adam` active voice; topic discovery missed `SCHEDULED` status, allowing duplicates across voices.
- **Permanent Fix:** Coerced all defaults and DB lookups to `af_bella`; expanded topic exclusion to all in-flight states + semantic title variants.

---

## Incident 7: False-COMPLETED Topic Pollution & Self-Matching Dedup
- **Root Cause:** Unreviewed topics were marked `COMPLETED` prematurely; deduplication compared topics against themselves.
- **Permanent Fix:** Enforced strict status transitions; self-matching IDs excluded from similarity comparison.