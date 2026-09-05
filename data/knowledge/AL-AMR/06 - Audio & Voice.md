---
aliases:
  - Audio & Voice
  - Narration Pacing
  - Sarah Voice Lock
tags:
  - audio
  - voice
  - tts
  - pacing
last_updated: 2026-09-05
---

# 06 — Sarah Voice Lock & Narration Pacing

> **Status:** `[CANONICAL SPECIFICATION — STRICT LOCK]`  
> **Scope:** Sarah voice lock, pause compression tuning, Audio QA gates, and BGM bed standardization.

---

## 1. Authoritative Voice Lock: Sarah (`af_sarah`)

> [!IMPORTANT]
> **PRODUCTION INVARIANT: SARAH EXCLUSIVELY LOCKED**  
> `af_sarah` (Kokoro-82M ONNX / Edge-TTS JennyNeural backup) is the sole approved voice for AL-AMR narration. Bella (`af_bella`), Adam (`am_adam`), and all other test voices are permanently decommissioned.

### Voice Profile & Characteristics
- **Voice Identifier:** `af_sarah`
- **Engine:** Kokoro-82M ONNX ($0 inference cost, runs completely offline on CPU).
- **Delivery Persona:** Authoritative documentary narrator, natural American English, clear enunciation, calm urgency.
- **Audio Mastering:** Broadcast mastering chain via FFmpeg `acompressor`, `highpass=f=75`, `equalizer=f=3200:t=q:w=1.2:g=2.2`, and EBU R128 normalization.

---

## 2. Narration Pacing & Silence Compression

### The Historical Bottleneck
During earlier phases, Kokoro TTS audio suffered from noticeable acoustic gaps (250–500ms) between sentences and after punctuation. In short-form video, dead air causes viewer drop-off within milliseconds.

### The Final Pacing Solution
1. **Calibrated Pause Generation:**
   - Sentence pause: **`0.08s`** (80ms)
   - Clause pause: **`0.03s`** (30ms)
2. **Post-Processing Silence Compression:**
   - Implemented via `TTSEngine.compress_silence_gaps()`.
   - Analyzes waveform root-mean-square (RMS) energy.
   - Any pause exceeding **`100ms`** is compressed down to 80–100ms without clipping phoneme tails or breathing naturalness.
3. **Dynamic Duration Calibration:**
   - If initial synthesis falls outside `[22.0, 25.0]s`, `TTSEngine` automatically computes the exact mathematical speed multiplier ($	ext{speed} = 	ext{current\_dur} / 23.2$) and re-synthesizes with full silence compression.

---

## 3. Hard Audio QA Gate Thresholds

The `VideoQAEngine` inspects the rendered audio track and fails closed on:
- **Maximum Silence Pause:** $> 0.35s$ (350ms) -> REJECTED.
- **Cumulative Dead Air Ratio:** $> 18.0\%$ of total runtime -> REJECTED.
- **Master Loudness:** Integrated LUFS outside `[-22.0, -10.0]` LUFS (Target: `-14.0 LUFS`) -> REJECTED.
- **Peak Ceiling:** True Peak $> 0.0$ dBTP -> REJECTED.

---

## 4. Background Music (BGM) Standardization

> [!NOTE]
> **BGM IS ENABLED IN PRODUCTION**  
> BGM was intentionally restored after an earlier experimental no-BGM phase. BGM plays throughout every Short but is strictly ducked under Sarah's voiceover.

### Approved Canonical Tracks (`assets/music/`)
1. `best_historical` — Intrinsic loudness `-19.2 LUFS` (Medieval, mysterious, ancient discoveries).
2. `emotional_sad` — Intrinsic loudness `-12.9 LUFS` (Tragic anomalies, lost civilizations, poignant stakes).
3. `flux_ambient` — Intrinsic loudness `-14.9 LUFS` (Scientific wonder, cosmic phenomena, deep sea).
4. `suspense_climax` — Intrinsic loudness `-12.1 LUFS` (High tension, countdowns, baffling reveals).

### Stage B Loudness Bed
To prevent music from overpowering narration:
- Every BGM track is normalized to **`-30.0 LUFS`** via EBU R128 (`TARGET_BGM_LUFS = -30.0`).
- Voiceover sits at **`-14.0 LUFS`**, guaranteeing voice is strictly **12 to 16 dB dominant**.

### Sound Effects (SFX) Policy
- **SFX ARE PERMANENTLY DISABLED.** No whooshes, impacts, risers, or comedic sounds are included in production audio.

---

## 5. Architectural Links
- System Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Script Formatting: [[05 - Script Engine|Script Engine]]
- Audio QA Verification: [[13 - QA & Testing|QA System]]
- Historical Context: [[15 - Historical Decisions|Historical Decisions (Bella & Pacing Fix)]]