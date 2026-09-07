# 06 — Audio & BGM System

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Bella voice lock, pause compression tuning, EBU R128 Stage B bed normalization, and acoustic QA fingerprinting `[CODE VERIFIED]`.  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Specification]] & [[04 — CONTENT PRODUCTION/Audio Mastering & BGM Standards|Audio Mastering & BGM Standards]]

---

## 1. Authoritative Voice Lock: Bella (`af_bella`)

- **Model:** Kokoro-82M ONNX ($0 cost, local CPU execution).
- **Persona:** Warm, conversational, engaging documentary narrator at native 1.00x speed `[LIVE VERIFIED]`.
- **Decommissioned:** Sarah (`af_sarah`) and Adam (`am_adam`) are permanently retired `[HISTORICAL]`.
- **Pause Tuning:** Sentence pause = `0.08s`, clause pause = `0.03s`.
- **Silence Compression:** Maximum `100ms` pause ceiling via `TTSEngine.compress_silence_gaps()`.
- **Audio QA Gate:** Rejects any audio with max pause >= 0.35s or dead air > 18.0%.

---

## 2. Background Music (BGM) Standardization

- **BGM Status:** **ENABLED** (restored with controlled ducking).
- **Stage B Bed:** Every BGM track is normalized to **`-30.0 LUFS`** via EBU R128.
- **Master Mix:** Voiceover sits at **`-14.0 LUFS`**, guaranteeing voice is strictly 12–16 dB dominant.
- **SFX Status:** **DISABLED** (all sound effects permanently removed).
- **Approved Tracks:** `best_historical`, `emotional_sad`, `flux_ambient`, `suspense_climax`.