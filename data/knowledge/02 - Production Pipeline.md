# 02 — Production Pipeline

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** End-to-end multi-stage pipeline specification from topic selection to YouTube publishing `[CODE VERIFIED]`.  
> **Master Reference:** [[04 — CONTENT PRODUCTION/Production Pipeline Specification|Production Pipeline Specification]]

---

## 1. End-to-End Pipeline Stages

```
TOPIC DISCOVERY (24 Curated Historical Seeds + Dynamic Gemini AI Fallback)
       │
       ▼
AI COUNCIL DELIBERATION (DeepSeek + Kimi K3 + Nemotron + Gemini)
       │
       ▼
COUNCIL QUALITY GATE (58-72 words, 0 clichés, hook in 1-2s)
       │
       ▼
VISUAL EVIDENCE RETRIEVAL (Archival Scans, Photos, Public Domain Artifacts)
       │
       ▼
PRODUCTION ASSET MANIFEST (>=9 scenes, Ken Burns directives, dHash dedup)
       │
       ▼
KOKORO BELLA NARRATION (af_bella at native 1.00x, 0.08s/0.03s pauses, 100ms compression)
       │
       ▼
HEADLESS FFMPEG COMPOSITION (1080x1920, karaoke ASS subtitles, ducked BGM, 0 SFX)
       │
       ▼
MULTI-FACTOR QA AUDIT (Pause <0.35s, Dead air <=18%, 22-25s duration)
       │
       ▼
VAULT DEPOSIT (Google Drive 01_READY) & DB STATE PERSISTENCE (00_SYSTEM)
```

### Critical Sequential Invariant
Videos are produced, rendered, QA-audited, and deposited **strictly ONE AT A TIME**. Parallel rendering across multiple threads is explicitly prohibited `[CODE VERIFIED]`.

---

## 2. Production Specifications
- **Authoritative Voice:** `af_bella` (Bella - US Female at native 1.00x) exclusively `[LIVE VERIFIED]`.
- **Word Target:** Exactly 58 to 72 words (Target: ~65 words).
- **Duration Target:** 22.0s to 25.0s (canonical target: ~23.0s).
- **Scene Count:** Minimum 9 unique scenes (target 10–12).
- **Audio Mixing:** Subtle BGM ducked 12–16dB below voiceover; SFX permanently disabled.
- **QA Enforcement:** Fails closed if max pause >= 0.35s or dead air > 18.0%.