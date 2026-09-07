---
aliases:
  - Historical Decisions
  - Superseded Architectures
tags:
  - history
  - decisions
  - changelog
last_updated: 2026-09-07
---

# 15 — Historical Decisions & Superseded Architectures

> **Status:** `[HISTORICAL ARCHIVE & DECISION REGISTER]`  
> **Scope:** Chronological engineering pivots, rationale for decommissioned approaches, and evolution toward cloud autonomy `[HISTORICAL]`.  
> **Canonical Current State:** See [[01 — PROJECT MASTER/Project Overview|Project Overview]].

---

## 1. Decision Log & Engineering Pivots

```
                                  AL-AMR ARCHITECTURAL EVOLUTION
                                  
  PHASE 1-2: Inception & News        PHASE 3: Audio & Science Pivot      PHASE 4 (CURRENT): Canonical Autonomy
 ┌───────────────────────────┐       ┌──────────────────────────────┐    ┌────────────────────────────────┐
 │ • Historical Trivia / Wire│       │ • Mystery & Science Dual     │    │ • Pure History & Mysteries     │
 │ • Current Affairs GDELT   │ ───►  │ • Sarah (af_sarah) Tested    │───►│ • Bella (af_bella) at 1.00x    │
 │ • SFX Whooshes & Risers   │       │ • SFX Disabled               │    │ • 3-Hour Refill (0 */3 * * *)  │
 │ • Manual CLI Triggers     │       │ • BGM Loudness Bed (-30 LUFS)│    │ • Cloud Lock Hardening (900s)  │
 └───────────────────────────┘       └──────────────────────────────┘    └────────────────────────────────┘
```

---

## 2. Deep-Dive on Major Pivots

### Pivot 1: Current Affairs & Geopolitics Abandoned -> Pure Historical Mysteries
- **Historical Approach:** The system was briefly tested on harvesting live RSS wires and GDELT 2.0 to generate breaking geopolitical Shorts.
- **Why It Was Superseded:** Geopolitics carried unacceptable risks: extreme factual verification burdens, bias, 12-hour content staleness, and copyright obstacles on conflict footage.
- **Canonical Decision:** Shifted exclusively to **History / Historical Mysteries / Bizarre True Historical Events**. These stories enjoy timeless curiosity, universal global appeal, and extensive public domain archival imagery `[LIVE VERIFIED]`.

### Pivot 2: Voice Auditions -> Bella Voice Canonical Lock (`af_bella`)
- **Historical Testing:** Early phases auditioned Adam (`am_adam`) and Sarah (`af_sarah`).
- **Why Sarah Was Superseded:** Sarah's cadence was evaluated as too formal and rigid during long-form listener testing.
- **Canonical Decision:** Locked exclusively to **`af_bella`** (Bella - US Female at native 1.00x speed). Bella delivers an authentic, warm, engaging human delivery that maximizes viewer completion rates `[LIVE VERIFIED]`.

### Pivot 3: Sound Effects (SFX) Permanently Retired
- **Historical Approach:** Earlier builds inserted whooshes, risers, and meme sounds between scene cuts.
- **Why It Was Superseded:** Synthetic SFX destroyed documentary credibility and caused viewer drop-off.
- **Canonical Decision:** SFX were permanently removed from the production pipeline `[CODE VERIFIED]`.

### Pivot 4: Cloud Lock Deadlock Fix & Curated Seed Expansion (Incident 8)
- **Problem:** Dangling 3600s TTL lock files caused production halts; 10 curated seeds were exhausted.
- **Canonical Decision:** Commit `31c002c` reduced TTL to 900s, added a 120s background heartbeat, enabled GitHub API dead-runner reclamation, added `--force-unlock`, expanded seeds to 24 verified mysteries, and wired dynamic AI discovery fallback `[LIVE VERIFIED]`.