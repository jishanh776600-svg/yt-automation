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
Raw BGM library tracks had intrinsic loudness levels spanning $-19.2	ext{ LUFS}$ to $-12.1	ext{ LUFS}$. The old static `-13.0 dB` attenuation produced loud BGM on certain tracks, competing with narration.

### Engineering Fix
Introduced `TARGET_BGM_LUFS = -30.0` in `config/constants.py` and implemented EBU R128 Stage B bed normalization in `AudioMixer.generate_stage_b_bgm_only()`.