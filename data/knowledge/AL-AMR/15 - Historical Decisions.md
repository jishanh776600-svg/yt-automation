---
aliases:
  - Historical Decisions
  - Superseded Architectures
tags:
  - history
  - decisions
  - changelog
last_updated: 2026-09-05
---

# 15 — Historical Decisions & Superseded Architectures

> **Status:** `[HISTORICAL ARCHIVE & DECISION REGISTER]`  
> **Scope:** Chronological engineering pivots, rationale for decommissioned approaches, and evolution toward cloud autonomy.

---

## 1. Decision Log & Engineering Pivots

```
                                  AL-AMR ARCHITECTURAL EVOLUTION
                                  
  PHASE 1-3: Monolithic Local         PHASE 4-6: Hardening & Council      PHASE 7-8: 100% Cloud Autonomous
 ┌───────────────────────────┐       ┌──────────────────────────────┐    ┌────────────────────────────────┐
 │ • Historical Trivia Seeds │       │ • Geopolitics Wire Research  │    │ • Mystery & Weird Science Only │
 │ • Adam / Bella Narration  │ ───►  │ • Multi-Agent AI Council     │───►│ • Sarah (af_sarah) Locked      │
 │ • SFX Whooshes & Risers   │       │ • SFX Disabled               │    │ • Silence Compression <=100ms │
 │ • Manual CLI Triggers     │       │ • BGM Loudness Bed (-30 LUFS)│    │ • GitHub Actions 24/7 Autopilot│
 └───────────────────────────┘       └──────────────────────────────┘    └────────────────────────────────┘
```

---

## 2. Deep-Dive on Major Pivots

### Pivot 1: Geopolitics & Breaking News Abandoned -> Mystery & Weird Science
- **Historical Approach:** The system was briefly configured to harvest live RSS wires from Reuters/AP to generate breaking geopolitical Shorts.
- **Why It Was Superseded:** Geopolitics carried unacceptable risks: extreme factual verification burdens, high controversy/bias risk, rapid staleness, and difficulty finding copyright-free footage of current conflicts.
- **Final Decision:** Shifted exclusively to **Mystery/Bizarre Real-World Stories** and **Weird Science / Unbelievable Facts**. These topics have timeless curiosity, universal appeal, and rich archival imagery.

### Pivot 2: Bella Voice Decommissioned -> Sarah Voice Locked
- **Historical Approach:** Bella (`af_bella`) was tested as the primary high-energy female voice.
- **Why It Was Superseded:** Extended audition testing revealed that while Bella was fast, her delivery lacked gravitas and authority for deep mysteries and scientific phenomena.
- **Final Decision:** Locked exclusively to **`af_sarah`** (Sarah - US Female). Sarah delivers an authoritative, grounded documentary cadence that maximizes viewer trust and retention.

### Pivot 3: Sarah Narration Pacing & Silence Compression
- **Historical Approach:** Kokoro TTS naturally generated 250–500ms acoustic tails between sentences, creating audible dead air.
- **Why It Was Superseded:** In mobile short-form video, dead air causes instant swipe-aways.
- **Final Decision:** Implemented a three-part pacing overhaul:
  1. High word density: 62 to 70 words per ~23s Short.
  2. Tight synthesis pauses: 0.08s sentence, 0.03s clause.
  3. Waveform silence compression: Any pause > 100ms is compressed down to 80–100ms via `TTSEngine.compress_silence_gaps()`.
  4. Audio QA gate: Fails closed if max pause exceeds 0.35s or cumulative dead air exceeds 18%.

### Pivot 4: Sound Effects (SFX) Permanently Disabled
- **Historical Approach:** Earlier versions inserted whooshes, risers, and impact booms between visual cuts.
- **Why It Was Superseded:** Synthetic SFX distracted from the documentary tone and clashed with speech clarity.
- **Final Decision:** SFX were permanently removed from the production pipeline.

### Pivot 5: Background Music (BGM) Restored with Controlled Ducking
- **Historical Approach:** BGM was temporarily disabled to isolate narration testing.
- **Why It Was Superseded:** Zero-BGM video felt sterile and unfinished.
- **Final Decision:** BGM was restored across 4 curated tracks normalized to an EBU R128 bed of `-30.0 LUFS`, ensuring voice sits 12–16 dB above music at all times.

### Pivot 6: Local Script Execution -> 100% Cloud Autonomy
- **Historical Approach:** Dependent on developer running `python main.py --maintain-buffer` and `python main.py --schedule-ready` locally.
- **Why It Was Superseded:** Not sustainable for 24/7 operation.
- **Final Decision:** Migrated entire execution to GitHub Actions cron runners backed by Google Drive as durable state storage.

---

## 3. Architectural Links
- Current Dashboard: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Content Strategy: [[02 - Content Strategy|Content Strategy]]
- Voice Specification: [[06 - Audio & Voice|Audio & Voice]]
- Cloud Architecture: [[03 - Architecture|System Architecture]]