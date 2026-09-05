# 02 — Production Pipeline

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** End-to-end multi-stage pipeline specification from live discovery to YouTube publishing.  
> **Master Reference:** [[09 - Production Pipeline|Sequential Production & Refill Controller]]

---

## 1. End-to-End Pipeline Stages

```
INGESTION & CLUSTERING (is_niche_compliant)
       │
       ▼
AI COUNCIL DELIBERATION (DeepSeek + Kimi K3 + Nemotron)
       │
       ▼
COUNCIL QUALITY GATE (62-70 words, 0 clichés, hook in 1-2s)
       │
       ▼
VISUAL EVIDENCE RETRIEVAL (Archival, Scientific Scans, Photos)
       │
       ▼
PRODUCTION ASSET MANIFEST (>=9 scenes, Ken Burns directives)
       │
       ▼
KOKORO SARAH NARRATION (af_sarah, 0.08s/0.03s pauses, 100ms compression)
       │
       ▼
HEADLESS FFMPEG COMPOSITION (1080x1920, karaoke ASS subtitles, ducked BGM)
       │
       ▼
MULTI-FACTOR QA AUDIT (Pause <0.35s, Dead air <=18%, 22-25s duration)
       │
       ▼
VAULT DEPOSIT (Google Drive 01_READY) & DB STATE PERSISTENCE (00_SYSTEM)
```

### Critical Sequential Invariant
Videos are produced, rendered, QA-audited, and deposited **strictly ONE AT A TIME**. Parallel rendering across multiple threads is explicitly prohibited.

---

## 2. Production Specifications
- **Authoritative Voice:** `af_sarah` (Sarah - US Female) exclusively.
- **Word Target:** Exactly 62 to 70 words.
- **Duration Target:** 22.0s to 25.0s (canonical target: ~23.2s).
- **Scene Count:** Minimum 9 unique scenes (target 10–12).
- **Audio Mixing:** Subtle BGM ducked 12–16dB below voiceover; SFX permanently disabled.
- **QA Enforcement:** Fails closed if max pause $\ge 0.35$s or dead air $> 18.0\%$.