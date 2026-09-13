# 06 — Audio & BGM System

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Bella voice lock, pause compression tuning, EBU R128 Stage B bed normalization, and acoustic QA fingerprinting `[CODE VERIFIED]`.  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Specification]] & [[04 — CONTENT PRODUCTION/Audio Mastering & BGM Standards|Audio Mastering & BGM Standards]]

---

## 1. Authoritative Voice Lock: Bella (`af_bella`)

- **Model:** Kokoro-82M ONNX ($0 cost, local CPU execution on ephemeral runners).
- **Persona:** Warm, conversational, engaging documentary narrator at native 1.00x speed `[LIVE VERIFIED]`.
- **Whitelist:** `APPROVED_PRODUCTION_VOICES = ["af_bella"]` (Commit `b4dd8f6306368859f07352adf42deb0b1de6199a`) `[CODE VERIFIED]`.
- **Decommissioned:** Sarah (`af_sarah`) and Adam (`am_adam`) are permanently retired. Any request for unapproved voices fails closed to `af_bella` `[HISTORICAL]`.
- **Pause Tuning:** Sentence pause = `0.08s`, clause pause = `0.03s`.
- **Silence Compression:** Maximum `100ms` pause ceiling via `TTSEngine.compress_silence_gaps()`.
- **Audio QA Gate:** Rejects any audio with max pause >= 0.35s or dead air > 18.0%.

---

## 2. Phonetic Pronunciation Normalization

Implemented in [`engines/tts_normalizer.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/tts_normalizer.py):
- Context-aware year/number normalizer converts dates (e.g. "1837" -> "eighteen thirty-seven") and numerals into natural phonetic speech.
- Eliminates robotic quantity-style date readings while preserving historical proper nouns `[CODE VERIFIED]`.

---

## 3. Background Music (BGM) Standardization

- **BGM Status:** **ENABLED** (restored with controlled ducking).
- **Stage B Bed:** Every BGM track is normalized to **`-30.0 LUFS`** via EBU R128.
- **Master Mix:** Voiceover sits at **`-14.0 LUFS`**, guaranteeing voice is strictly 12–16 dB dominant.
- **SFX Status:** **DISABLED** (all sound effects permanently removed from production pipeline).
- **Approved Tracks:** `best_historical`, `emotional_sad`, `flux_ambient`, `suspense_climax`.