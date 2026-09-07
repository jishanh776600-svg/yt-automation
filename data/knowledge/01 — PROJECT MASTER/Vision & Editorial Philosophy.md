---
aliases:
  - Vision & Goals
  - Editorial Philosophy
  - Channel Niche Policy
tags:
  - editorial
  - vision
  - niche
last_updated: 2026-09-07
---

# Vision & Editorial Philosophy: AL-AMR

> **Status:** `[CANONICAL POLICY — STRICT ENFORCEMENT]`  
> **Approved Channel Niche:** **History / Historical Mysteries / Bizarre True Historical Events / Unexplained Historical Stories** `[LIVE VERIFIED]`  
> **Forbidden Subjects:** Politics, Geopolitics, Warfare, Military Conflicts, Diplomacy, Current Affairs, Generic Science Facts `[CODE VERIFIED]`  

---

## 1. The Core Editorial Philosophy

AL-AMR is built on a single high-retention storytelling principle:
**"Documented reality is more captivating than fiction when narrated with cinematic pacing and authenticated evidence."** `[DESIGNED]`

Rather than generic educational lectures or encyclopedic recitations, each AL-AMR Short is an immersive 22–25 second forensic reconstruction of an authentic historical enigma `[CODE VERIFIED]`.

### The Three Hallmarks of an AL-AMR Story
1. **Concrete Historical Grounding:** The event actually happened in documented human history, supported by archival records, expedition logs, artifacts, or official reports `[CODE VERIFIED]`.
2. **The Curiosity Chasm:** The story opens with a jarring historical contradiction or mystery within the first 1.5 seconds, withholding the resolution until the final beats `[CODE VERIFIED]`.
3. **Conversational Human Delivery:** Narrated in the warm, engaging, authoritative voice of Bella (`af_bella`), avoiding AI cliches, academic pomposity, or sensational clickbait `[LIVE VERIFIED]`.

---

## 2. Niche Boundary Specification

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       AL-AMR CANONICAL NICHE BOUNDARY                       │
├──────────────────────────────────────┬──────────────────────────────────────┤
│    ✅ APPROVED CORE CONTENT           │    ❌ PERMANENTLY BANNED CONTENT     │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ • Historical enigmas & mysteries     │ • Geopolitics & international news   │
│ • Bizarre documented historical incidents │ • Wars, military battles, weapons │
│ • Ancient archaeological anomalies   │ • Elections, politicians, diplomacy  │
│ • Documented missing expeditions     │ • Contemporary current affairs       │
│ • Strange physical artifacts         │ • Generic pop-science / trivia dumps │
│ • Baffling historical coincidences   │ • Partisan or ideological commentary │
└──────────────────────────────────────┴──────────────────────────────────────┘
```

### Approved Topic Archetypes
- **The Bizarre Coincidence / Law:** E.g., The Kettle War of 1784, The Dancing Plague of 1518, The London Beer Flood of 1814.
- **The Lost / Unexplained Artifact:** E.g., The Voynich Manuscript, The Antikythera Mechanism, The Roman Dodecahedron.
- **The Mysterious Disappearance / Voyage:** E.g., The Mary Celeste, The Franklin Expedition, The Dyatlov Pass Incident.
- **The Baffling Historic Miracle / Event:** E.g., The Miracle of the Sun (1917), The Devil's Footprints (1855).

---

## 3. Fail-Closed Editorial Quality Gates

To prevent niche drift or accidental ingestion of current news:
- **Keyword Filtering (`is_niche_compliant`):** Evaluated in `intelligence/clustering.py` against over 45 banned political and warfare terms. Any candidate matching even a single banned token is discarded instantly `[CODE VERIFIED]`.
- **Historical Grounding Check:** Candidate stories must specify a verified historical era, location, and entity `[CODE VERIFIED]`.
- **AI Council Quality Consensus:** The Multi-Agent Council (DeepSeek, Kimi K3, Nemotron) rejects any draft containing generic "Today..." news openings, modern political framing, or academic filler `[CODE VERIFIED]`.

---

## 4. Historical Niche Evolution

- **Phase 1 (Conception):** Multidisciplinary trivia and generic science facts `[HISTORICAL]`.
- **Phase 2 (Pivot Experiment):** Current Affairs and Geopolitical breaking news layer `[HISTORICAL - ABANDONED]`. Discarded due to ephemeral shelf-life, monetization volatility, and high verification liability.
- **Phase 3 (Canonical Lock):** Pure Historical Mysteries, Bizarre True Events, and Unexplained Historical Stories `[LIVE VERIFIED]`.