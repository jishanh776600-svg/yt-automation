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
> **Production Whitelist:** `APPROVED_PRODUCTION_VOICES = ["af_bella"]` `[CODE VERIFIED]`  
> **Latest Corrective Commit:** `b4dd8f6306368859f07352adf42deb0b1de6199a` `[CODE VERIFIED]`  
> **Engine:** Kokoro-82M ONNX ($0 inference cost, executes offline on runner CPU) `[CODE VERIFIED]`  
> **Pacing & Speed:** Native **`1.00x`** speed `[LIVE VERIFIED]`  
> **Decommissioned Voices:** `af_sarah` (Sarah) and `am_adam` (Adam) are permanently decommissioned `[HISTORICAL]`  

---

## 1. The Canonical Bella Voice (`af_bella`)

Following extensive voice audition rounds and live production verification (Run #47), Bella (`af_bella`) was selected as the sole canonical voice for all AL-AMR YouTube Shorts:

- **Sonic Identity:** Warm, intelligent, engaging, documentary-level conversational pacing.
- **Audition Verification:** Outperformed previous test voices in listener warmth, natural breathing, and retention metrics.
- **Native Speed (1.00x):** Kokoro's native generation speed preserves natural acoustic resonance and human vocal timbre without artificial pitch distortion or robotic artifacts `[LIVE VERIFIED]`.
- **Authoritative Whitelist:** Enforced strictly via `APPROVED_PRODUCTION_VOICES = ["af_bella"]` across all modules.

---

## 2. Pause Calibration, Silence Compression & Pronunciation Normalization

Implemented in [`engines/tts_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/tts_engine.py) and [`engines/tts_normalizer.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/tts_normalizer.py):

1. **Phonetic Pronunciation Normalization (`TTSNormalizer`):**
   - Context-aware year/number normalization converts historical years (e.g. "1837" -> "eighteen thirty-seven", "1066" -> "ten sixty-six") so the TTS engine pronounces dates naturally rather than reading them as robotic quantities `[CODE VERIFIED]`.
   - Preserves proper nouns, Roman numerals, and specialized historical terms.
2. **Punctuation Pause Generation:**
   - Sentence pause: **`0.08s`** (80ms)
   - Clause/comma pause: **`0.03s`** (30ms)
3. **Post-Processing Silence Compression (`compress_silence_gaps`):**
   - Waveform RMS analysis scans for acoustic gaps.
   - Any pause exceeding **`100ms`** is dynamically compressed down to 80–100ms without clipping phoneme tails `[CODE VERIFIED]`.
4. **Hard Audio QA Gate:**
   - Maximum pause: $<0.35\text{s}$ (350ms). Rejects any audio with longer silence gaps.
   - Cumulative dead air: $\le 18.0\%$ of runtime `[CODE VERIFIED]`.

---

## 3. Surgical Rollback of Erroneous Sarah Lock

An earlier content-quality hardening update inadvertently locked `APPROVED_PRODUCTION_VOICES` and defaults to `af_sarah`. This was an erroneous change that was immediately identified and surgically rolled back in commit `b4dd8f6306368859f07352adf42deb0b1de6199a`:

- **Configuration Locations Enforced:**
  1. `config/settings.py`: `KOKORO_VOICE = "af_bella"`, `APPROVED_PRODUCTION_VOICES = ["af_bella"]`.
  2. `engines/tts_engine.py`: `APPROVED_PRODUCTION_VOICES = ["af_bella"]`, `AVAILABLE_VOICES` maps solely to Bella, default/fallback resolves strictly to `af_bella`.
  3. `engines/visual_intelligence/voice_policy.py`: `APPROVED_PERSONAS` restores `af_bella` with `DeliveryProfile.CONVERSATIONAL`, `APPROVED_PRODUCTION_VOICES = ["af_bella"]`.
  4. `engines/orchestrator.py`: Voice override check locked strictly to `af_bella`.
  5. `main.py`: Runtime DB init and CLI default fallbacks coerced to `af_bella`.
  6. `.github/workflows/produce_buffer.yml`: `inputs.active_voice.default: 'af_bella'`, workflow step fallbacks set to `'af_bella'`.

- **Targeted Verification Results:**
  - `tests/test_production_voice_lock.py` & `tests/test_content_quality_upgrade.py`: **25/25 PASSED**
  - `tests/test_cloud_autonomy.py`: **7/7 PASSED**
  - `tests/test_phase3_journalistic_script.py -k test_23`: **1/1 PASSED**
  - `tests/test_real_footage_and_asset_system.py -k voice`: **1/1 PASSED**
  - `tests/test_lifecycle_negative_invariants.py`: **40/40 PASSED**

---

## 4. Historical Voice Deprecations

- **`am_adam` (Adam):** Initial male test voice; retired due to flat delivery and lower audience retention `[HISTORICAL]`.
- **`af_sarah` (Sarah):** Used during earlier test phases; retired in favor of Bella's superior natural warmth and higher retention ratings. Unapproved in production; any request fails closed to `af_bella` `[HISTORICAL]`.
- **Enforcement:** `ShortsPipeline.__init__()` and `TTSEngine` contain hardcoded guards rejecting unapproved voices `[CODE VERIFIED]`.