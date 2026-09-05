# Canonical Narration Voice: af_sarah

> **Status:** `[CANONICAL AUTHORITATIVE VOICE — STRICT LOCK]`  
> **Supersedes:** `af_bella` (Decommissioned) and `am_adam` (Retired)  
> **Master Reference:** [[06 - Audio & Voice|Sarah Voice Lock & Narration Pacing]]

---

## 1. Overview
`af_sarah` is the sole authorized production voice for all AL-AMR YouTube Shorts narration across both approved niches (*Mystery/Bizarre* and *Weird Science*).

---

## 2. Voice Characteristics & Profile
- **Voice Identifier:** `af_sarah`
- **Engine:** Kokoro-82M ONNX (Zero GPU dependency, ultra-fast CPU inference, $0 cost)
- **Backup Cloud Provider:** Edge-TTS `en-US-JennyNeural` (High-fidelity neural fallback)
- **Gender & Accent:** American English Female
- **Persona:** Authoritative, calm urgency, engaging documentary narrator
- **Target Sample Rate:** 24,000 Hz resampled to 44,100 Hz broadcast standard
- **Mastering Chain:** Broadcast studio presence (`acompressor`, highpass 75Hz, peak EQ at 3.2kHz, EBU R128 normalization)

---

## 3. Pacing & Pause Specifications
- **Sentence Pause:** Exactly **`0.08s`** (80ms)
- **Clause Pause:** Exactly **`0.03s`** (30ms)
- **Silence Compression:** Maximum **`100ms`** gap ceiling via `TTSEngine.compress_silence_gaps()`
- **Audio QA Thresholds:**
  - Maximum pause: $< 0.35s$ (Hard rejection if $\ge 0.35s$)
  - Dead air ratio: $\le 18.0\%$ (Hard rejection if $> 18.0\%$)

---

## 4. Production Invariants
1. All configuration files (`config/settings.py`, `engines/tts_engine.py`, workflows) resolve strictly to `af_sarah`.
2. Fallback to `af_bella`, `am_adam`, or other voices is strictly prohibited in production.
3. Every rendered video is verified by `drive_engine.verify_sarah_voice()` before vault deposit or scheduling.