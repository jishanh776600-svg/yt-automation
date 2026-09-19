---
aliases:
  - Historical Topic Discovery
  - Curated Seeds
  - Topic Discovery
  - Niche Guard
tags:
  - intelligence
  - topics
  - discovery
  - niche-guard
last_updated: 2026-09-19
---

# Historical Topic Discovery & Curated Seeds

> **Status:** `[LIVE & HARDENED — COMMIT 2026-09-19]`  
> **Scope:** Curated historical mystery seed library (75 verified seeds), canonical `NicheGuard` boundary gate, negative academic/medical/environmental exclusion filters, and dynamic Gemini AI topic discovery fallback.

---

## 1. The Canonical Topic Niche Guard (`intelligence/niche_guard.py`)

Implemented following the September 2026 YouTube Shorts Feed distribution collapse (documented in `data/knowledge/09 — INCIDENTS & FIXES/YOUTUBE_SHORTS_DISTRIBUTION_FORENSIC_SEP_2026.md`).

### Channel Niche Definition
The Forgotten Files channel audience is strictly anchored to:
- **Historical mysteries & enigmas**
- **Historical disappearances & vanishings**
- **Folklore, legends, and mythological events**
- **Archaeological mysteries & lost civilizations / artifacts**
- **Historical disasters & bizarre documented incidents**
- **Historical curiosities & unusual wars**

### Negative Exclusion Categories
The system authoritatively rejects semantic equivalents of modern academic science:
1. `MODERN_MEDICAL_RESEARCH`: Modern cancer, oncology, chemotherapy, tumors, immunotherapy, clinical trials, young adult epidemiology, pharmaceutical breakthroughs.
2. `MODERN_GENETICS_RESEARCH`: Modern genetics, CRISPR, gene editing, cellular aging, telomeres, longevity genes, bat DNA research.
3. `MODERN_ENVIRONMENTAL_RESEARCH`: Modern clearcutting, boreal forests, forest fragmentation, climate change studies, carbon emissions, microplastics, plastic-waste food conversion, industrial logging.
4. `PRESS_RELEASE_SCIENCE`: University press-release phrasing (`study led by`, `researchers at`, `study finds`, `study reveals`, `published in Nature/Science/Cell`).
5. `MODERN_ACADEMIC_SCIENCE`: Generic physics, astrophysics (`supermassive black hole winds`, `exoplanet atmospheres`), and paleontology lab studies without human antiquity (`125-million-year-old crocodile UV camouflage`).

### Historical Context Exceptions
A scientific or medical subject is allowed ONLY when the primary narrative subject is historical/archaeological:
- `ALLOWED`: Ancient Roman medical texts, Roman Lycurgus Cup nanotechnology, ancient self-healing concrete, medieval legends of life extension, ancient astronomical observations (1054 supernova).
- `REJECTED`: Modern laboratory studies, clinical trials, and university press releases about contemporary phenomena.

---

## 2. Curated Historical Seed Corpus (`CURATED_HISTORICAL_SEEDS`)

Implemented in [`engines/topic_discovery.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/topic_discovery.py):
Maintains **75+ verified, non-duplicate historical mysteries** across documented categories:
- Documented Disasters (London Beer Flood 1814, Halifax Explosion 1917, Kentucky Meat Shower 1876, Great Molasses Flood 1919)
- Unusual Wars & Battles (38-Minute Anglo-Zanzibar War 1896, Liechtensteiner Army 1866, Pig War 1859, Emu War 1932, Battle of Karansebes 1788)
- Forgotten Historical Figures & Feats (Unsinkable Violet Jessop, Soldier Tarrare, Dr. James Barry, Balloon Duel of 1808)
- Archaeological & Historical Enigmas (Antikythera Mechanism, Voynich Manuscript, Roman Dodecahedron, Göbekli Tepe, Lycurgus Cup)
- Famous Disappearances (Roanoke Colony 1590, Mary Celeste 1872, Flannan Isle Keepers 1900, Flight 19, Ambrose Bierce)

All 75 curated seeds are verified to score >= 50.0 and pass `NicheGuard` with 100% compliance.

---

## 3. Multi-Tier Discovery Fallback Chain

When candidate replenishment is requested:
1. **Unproduced Database Topics**: Queried from SQLite `Topic` table and strictly filtered through `NicheGuard.evaluate()`. Off-niche topics are rejected and skipped.
2. **Dynamic Gemini AI Discovery**: Invokes Gemini with strict negative constraints against oncology, genetics, and press-release science. All AI-returned candidates must pass `NicheGuard.evaluate()` before insertion.
3. **Curated Historical Seeds**: Evaluates `CURATED_HISTORICAL_SEEDS` with `calculate_topic_score()` and Gate 15 deduplication. If candidate score < 45.0 or duplicate, proceeds to the next seed.
4. **Refill Invariant**: Candidate rejection continues the search loop rather than causing starvation. Offline curated seeds guarantee production continuity.