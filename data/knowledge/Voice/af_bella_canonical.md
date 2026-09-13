# Canonical Narration Voice: af_bella

> **Status:** `[AUTHORITATIVE PRODUCTION VOICE — LIVE VERIFIED]`  
> **Active Voice:** **`af_bella`** (Bella - US Female, Kokoro-82M ONNX) `[LIVE VERIFIED]`  
> **Production Whitelist:** `APPROVED_PRODUCTION_VOICES = ["af_bella"]` `[CODE VERIFIED]`  
> **Latest Corrective Commit:** `b4dd8f6306368859f07352adf42deb0b1de6199a` `[CODE VERIFIED]`  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Specification]]

---

## 1. Authoritative Identity & Standards
- **Voice Identifier**: `af_bella`
- **Model / Engine**: Kokoro-82M ONNX (Zero GPU dependency, ultra-fast CPU inference on cloud runners).
- **Format**: 24kHz / 44.1kHz 16-bit PCM WAV.
- **Speed & Cadence**: Native `1.00x` speed with conversational creator warmth.
- **Pause Calibration**: Sentence pause `0.08s` (80ms), clause/comma pause `0.03s` (30ms).
- **Silence Compression**: RMS silence compression capping gaps at `100ms` via `TTSEngine.compress_silence_gaps()`.
- **Audio QA Limits**: Max pause $< 0.35\text{s}$, cumulative dead air $\le 18.0\%$.

---

## 2. Surgical Rollback from Erroneous Sarah Lock
An earlier content-quality hardening change inadvertently locked production defaults to `af_sarah`. That configuration was erroneous and has been strictly rolled back.
- **Commit**: `b4dd8f6306368859f07352adf42deb0b1de6199a` (`fix(voice): restore af_bella as single authoritative production voice and finalize content quality upgrade`).
- **Enforcement**: `af_sarah` is classified as retired/unapproved. All resolution paths, workflow fallbacks, and runtime defaults resolve strictly to `af_bella`.

---

## 3. Configuration Locations in Codebase
1. `config/settings.py`: `KOKORO_VOICE = "af_bella"`, `APPROVED_PRODUCTION_VOICES = ["af_bella"]`.
2. `engines/tts_engine.py`: `APPROVED_PRODUCTION_VOICES = ["af_bella"]`, `AVAILABLE_VOICES` updated to Bella canonical, `resolve_voice_config()` and `generate_narration()` default and fail closed to `af_bella`.
3. `engines/visual_intelligence/voice_policy.py`: `APPROVED_PERSONAS` restores `af_bella` with `DeliveryProfile.CONVERSATIONAL`, `APPROVED_PRODUCTION_VOICES = ["af_bella"]`.
4. `engines/orchestrator.py`: Voice override check locked strictly to `af_bella`.
5. `main.py`: Runtime DB initialization and CLI fallback coerced to `af_bella`.
6. `.github/workflows/produce_buffer.yml`: `inputs.active_voice.default: 'af_bella'`, `KOKORO_VOICE` step fallback `'af_bella'`, `VOICE_FLAG` fallback `'af_bella'`.

---

## 4. Verification Evidence
- `tests/test_production_voice_lock.py` & `tests/test_content_quality_upgrade.py`: **25/25 PASSED**
- `tests/test_cloud_autonomy.py`: **7/7 PASSED**
- `tests/test_phase3_journalistic_script.py -k test_23`: **1/1 PASSED**
- `tests/test_real_footage_and_asset_system.py -k voice`: **1/1 PASSED**
- `tests/test_lifecycle_negative_invariants.py`: **40/40 PASSED**