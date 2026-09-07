---
aliases:
  - Audio & Voice
  - Narration Pacing
  - Bella Voice Lock
tags:
  - audio
  - voice
  - tts
  - pacing
last_updated: 2026-09-07
---

# 06 — Bella Voice Lock & Narration Pacing

> **Status:** `[CANONICAL SPECIFICATION — STRICT LOCK]` `[LIVE VERIFIED]`  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Specification]]  
> **Active Voice:** **`af_bella`** (Bella - US Female at native 1.00x) `[LIVE VERIFIED]`  
> **Decommissioned Voices:** `af_sarah` and `am_adam` are permanently decommissioned `[HISTORICAL]`  

---

## 1. Authoritative Voice Lock: Bella (`af_bella`)

> [!IMPORTANT]
> **PRODUCTION INVARIANT: BELLA EXCLUSIVELY LOCKED** `[LIVE VERIFIED]`  
> `af_bella` (Kokoro-82M ONNX / Edge-TTS JennyNeural backup) is the sole approved voice for AL-AMR narration. Sarah (`af_sarah`), Adam (`am_adam`), and all other test voices are permanently decommissioned.

### Voice Profile & Characteristics
- **Voice Identifier:** `af_bella` `[LIVE VERIFIED]`
- **Engine:** Kokoro-82M ONNX ($0 inference cost, runs completely offline on CPU) `[CODE VERIFIED]`.
- **Delivery Persona:** Warm, engaging, intelligent documentary narrator with natural human pacing.
- **Speed:** Native `1.00x` speed (no artificial audio warping) `[LIVE VERIFIED]`.
- **Live Verification:** GitHub Actions Run #47 (`short_man_c85a0dd30bda.mp4`) deposited into Drive `01_READY` with verified Bella narration `[LIVE VERIFIED]`.

---

## 2. Narration Pacing & Silence Compression

1. **Calibrated Pause Generation:**
   - Sentence pause: **`0.08s`** (80ms)
   - Clause pause: **`0.03s`** (30ms)
2. **Post-Processing Silence Compression:**
   - Implemented via `TTSEngine.compress_silence_gaps()`.
   - Any silence gap exceeding **`100ms`** is compressed down to 80–100ms without clipping phonemes `[CODE VERIFIED]`.
3. **Hard Audio QA Gate:**
   - Max pause $< 0.35\text{s}$.
   - Dead air $\le 18.0\%$ `[CODE VERIFIED]`.

---

## 3. Voice Evolution History

- **Adam (`am_adam`):** Initial test voice; retired due to flat tone `[HISTORICAL]`.
- **Sarah (`af_sarah`):** Used during earlier test phases; superseded by Bella's superior natural warmth and listener retention `[HISTORICAL]`.