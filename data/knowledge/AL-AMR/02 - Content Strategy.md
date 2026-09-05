---
aliases:
  - Content Strategy
  - Niche Policy
tags:
  - content
  - editorial
  - strategy
last_updated: 2026-09-05
---

# 02 — Authoritative Content Strategy

> **Status:** `[CANONICAL POLICY — STRICT ENFORCEMENT]`  
> **Scope:** Approved editorial niches, keyword-level rejection gates, publishing cadence rotation, and topic deduplication rules.

---

## 1. The Two Approved Production Niches

AL-AMR produces content exclusively within two high-curiosity, high-retention educational/entertainment niches:

```
                  ┌─────────────────────────────────────────┐
                  │          APPROVED CHANNEL NICHES        │
                  └────────────────────┬────────────────────┘
                                       │
            ┌──────────────────────────┴──────────────────────────┐
            ▼                                                     ▼
┌───────────────────────────────────────┐   ┌───────────────────────────────────────┐
│     NICHE A: MYSTERY & BIZARRE        │   │     NICHE B: WEIRD SCIENCE            │
│          REAL-WORLD STORIES           │   │        & UNBELIEVABLE FACTS           │
├───────────────────────────────────────┤   ├───────────────────────────────────────┤
│ • Documented bizarre events           │   │ • Quantum & astrophysics oddities     │
│ • Unexplained physical phenomena      │   │ • Deep-sea biological anomalies       │
│ • Bizarre historical discoveries      │   │ • Bizarre evolutionary mutations      │
│ • Strange architectural enigmas       │   │ • Counter-intuitive physics laws      │
│ • Ancient archaeological anomalies    │   │ • Extreme geological phenomena        │
│ • Documented missing persons/voyages  │   │ • Baffling laboratory discoveries     │
└───────────────────────────────────────┘   └───────────────────────────────────────┘
```

### Niche A: Mystery / Bizarre Real-World Stories
- **Core Hook:** Something occurred in reality that defies intuitive explanation or normal expectations.
- **Key Angles:** Documented historical records, strange archaeological excavations, physical artifacts that shouldn't exist, unexplained sounds (e.g. The Bloop), bizarre medical or societal incidents.
- **Tone:** Objective, intriguing, grounded in physical evidence, atmospheric, respectful.

### Niche B: Weird Science / Unbelievable-but-Real Facts
- **Core Hook:** A scientifically proven fact that sounds completely impossible or fabricated until the underlying mechanism is revealed.
- **Key Angles:** Deep-sea organisms with baffling biology (e.g. immortal jellyfish, siphonophores), quantum entanglement, cosmic oddities (e.g. rogue planets, fast radio bursts), strange geological formations.
- **Tone:** Energetic, wonder-inducing, intellectually stimulating, punchy.

---

## 2. Hard Fail-Closed Political & War Rejection Gate

> [!CAUTION]
> **ABSOLUTE EDITORIAL RED LINE: ZERO POLITICS, WAR, ELECTIONS, OR MILITARY COMMENTARY**  
> Conventional geopolitical news, warfare, military battles, diplomatic summits, elections, legislative debates, and political figures are strictly banned. Niche purity is fail-closed: any story matching political keywords is instantly discarded before reaching the AI Council.

### Programmatic Implementation
Implemented in [`intelligence/clustering.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/clustering.py) via `is_niche_compliant()`:

```python
BANNED_POLITICAL_KEYWORDS = [
    "war", "warfare", "ceasefire", "military", "army", "troops", "infantry", "forces",
    "diplomacy", "diplomat", "diplomatic", "treaty", "election", "elections", "voters",
    "voting", "ballot", "parliament", "congress", "senate", "minister", "prime minister",
    "president", "presidential", "spokesperson", "spokesman", "sanctions", "tariff", "tariffs",
    "bilateral", "geopolitical", "geopolitics", "pentagon", "kremlin", "white house", "nato",
    "un security council", "missile strike", "air strike", "artillery", "offensive",
    "insurgency", "coup", "foreign policy", "envoy", "ambassador", "national security",
    "ground forces", "defense secretary", "state department", "foreign ministry", "legislation",
    "lawmakers", "referendum", "regime", "geopolitic"
]
```

If any candidate title, summary, or entity matches these tokens, `is_niche_compliant` returns `(False, "REJECTED_POLITICAL_CONTENT")`.

---

## 3. Publishing Cadence & Rotation Schedule

To maintain audience diversity and algorithmic momentum, publishing rotates between the two niches on an alternating daily schedule:

| Calendar Day | Slot 1 (06:00 UTC) | Slot 2 (11:00 UTC) | Slot 3 (15:00 UTC) | Daily Ratio |
|---|---|---|---|---|
| **Day A** | 🕵️ Mystery / Bizarre | 🔬 Weird Science | 🕵️ Mystery / Bizarre | 2 Mystery : 1 Science |
| **Day B** | 🔬 Weird Science | 🕵️ Mystery / Bizarre | 🔬 Weird Science | 1 Mystery : 2 Science |
| **Day C** | *(Repeats Day A)* | *(Repeats Day A)* | *(Repeats Day A)* | 2 Mystery : 1 Science |
| **Day D** | *(Repeats Day B)* | *(Repeats Day B)* | *(Repeats Day B)* | 1 Mystery : 2 Science |

The `CloudProductionOrchestrator` inspects the recent publishing history in SQLite to dynamically prioritize candidates matching the required category for the next vacant slot.

---

## 4. Topic Deduplication & Cooldown Policy

1. **Exact Semantic Matching:** Evaluates candidate story embeddings using cosine similarity. Candidates with similarity >= 0.72 against any topic produced in the last 90 days are rejected.
2. **Entity-Action Shingles:** Extracted named entities and core actions are hashed into 3-gram shingles in `short_fingerprints.db`.
3. **No Duplicate Stories:** The channel never releases two Shorts on the same event, even if rewritten with different wording or angles.

---

## 5. Architectural Links
- System Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Script Formulation: [[05 - Script Engine|Script Engine]]
- Council Review: [[04 - AI Council|AI Council]]
- Dedup Engine: [[08 - Duplicate Protection|Short Duplicate Guard]]
- Historical Context: [[15 - Historical Decisions|Historical Decisions (Geopolitics Pivot)]]