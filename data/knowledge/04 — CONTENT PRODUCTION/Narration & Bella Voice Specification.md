---
aliases:
  - Bella Voice Specification
  - Narration & Voice
  - Kokoro Bella
tags:
  - production
  - voice
  - audio
  - tts
last_updated: 2026-09-07
---

# Narration & Bella Voice Specification

> **Status:** `[LIVE & VERIFIED — RUN #47 VALIDATED]`  
> **Active Production Voice:** **`af_bella`** (Bella - US Female) `[LIVE VERIFIED]`  
> **Engine:** Kokoro-82M ONNX ($0 inference cost, executes offline on runner CPU) `[CODE VERIFIED]`  
> **Pacing & Speed:** Native **`1.00x`** speed `[LIVE VERIFIED]`  
> **Decommissioned Voices:** `af_sarah` (Sarah) and `am_adam` (Adam) are permanently decommissioned `[HISTORICAL]`  

---

## 1. The Canonical Bella Voice (`af_bella`)

Following extensive voice audition rounds and live production verification (Run #47), Bella (`af_bella`) was selected as the sole canonical voice for all AL-AMR YouTube Shorts:

- **Sonic Identity:** Warm, intelligent, engaging, documentary-level conversational pacing.
- **Audition Verification:** Outperformed previous test voices in listener warmth, natural breathing, and retention metrics.
- **Native Speed (1.00x):** Kokoro's native generation speed preserves natural acoustic resonance and human vocal timbre without artificial pitch distortion or robotic artifacts `[LIVE VERIFIED]`.

---

## 2. Pause Calibration & Silence Compression

Implemented in [`engines/tts_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/tts_engine.py):

1. **Punctuation Pause Generation:**
   - Sentence pause: **`0.08s`** (80ms)
   - Clause/comma pause: **`0.03s`** (30ms)
2. **Post-Processing Silence Compression (`compress_silence_gaps`):**
   - Waveform RMS analysis scans for acoustic gaps.
   - Any pause exceeding **`100ms`** is dynamically compressed down to 80–100ms without clipping phoneme tails `[CODE VERIFIED]`.
3. **Hard Audio QA Gate:**
   - Maximum pause: $<0.35\text{s}$ (350ms). Rejects any audio with longer silence gaps.
   - Cumulative dead air: $\le 18.0\%$ of runtime `[CODE VERIFIED]`.

---

## 3. Historical Voice Deprecations

- **`am_adam` (Adam):** Initial male test voice; retired due to flat delivery and lower audience retention `[HISTORICAL]`.
- **`af_sarah` (Sarah):** Used during Phase 3 testing; retired in favor of Bella's superior natural warmth and higher retention ratings `[HISTORICAL]`.
- **Enforcement:** `ShortsPipeline.__init__()` and `TTSEngine` contain hardcoded guards rejecting `af_sarah` or `am_adam` if passed via configuration `[CODE VERIFIED]`.