---
aliases:
  - Historical Topic Discovery
  - Curated Seeds
  - Topic Discovery
tags:
  - intelligence
  - topics
  - discovery
last_updated: 2026-09-07
---

# Historical Topic Discovery & Curated Seeds

> **Status:** `[LIVE & VERIFIED — COMMIT 31c002c]`  
> **Scope:** Curated historical mystery seed library, dynamic Gemini AI topic discovery fallback, and curiosity scoring `[CODE VERIFIED]`.

---

## 1. The 24 Curated Historical Seeds (`CURATED_HISTORICAL_SEEDS`)

Implemented in [`engines/topic_discovery.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/topic_discovery.py):
Expanded from 10 exhausted seeds to 24 verified, non-duplicate historical mysteries in commit `31c002c` following Incident 8:

1. `The Mary Celeste (1872)` — Intact ghost ship found abandoned in the Atlantic.
2. `The Dancing Plague of 1518` — Hundreds danced uncontrollably until death in Strasbourg.
3. `The Voynich Manuscript` — Carbon-dated 15th-century codex written in an undecipherable script.
4. `The Antikythera Mechanism` — Ancient Greek geared analog computer calculating celestial orbits.
5. `The Dyatlov Pass Incident (1959)` — Nine experienced hikers perished under bizarre trauma in the Urals.
6. `The Tanguska Event (1908)` — Megaton-class atmospheric blast flattened 80 million Siberian trees.
7. `The Devil's Footprints (1855)` — Single-file hoof prints spanned 100 miles across Devon snow.
8. `The Disappearance of the Flannan Isle Keepers (1900)` — Three lighthouse keepers vanished without a trace.
9. `The Roman Dodecahedron` — Dozens of hollow 12-sided bronze artifacts with zero historical explanation.
10. `The Oak Island Money Pit` — Baffling booby-trapped flood tunnels beneath Nova Scotia.
11. `The Miracle of the Sun (1917)` — 70,000 witnesses saw the sun spin and plunge toward Earth.
12. `The Green Children of Woolpit (12th Century)` — Siblings with green skin speaking an unknown language.
13. `The Taos Hum` — Low-frequency persistent acoustic anomaly heard by 2% of Taos residents.
14. `The Lost Colony of Roanoke (1590)` — 115 English settlers vanished leaving only "CROATOAN".
15. `The Wow! Signal (1977)` — 72-second narrowband radio burst from Sagittarius.
16. `The SS Ourang Medan (1948)` — Dutch freighter found adrift with crew frozen in terror.
17. `The Toxic Lady (Gloria Ramirez, 1994)` — Hospitalized patient whose blood fumes sicken emergency staff.
18. `The Lead Masks Case (1966)` — Two Brazilian technicians found dead wearing lead eye-masks.
19. `The Lake Anjikuni Village Vanishing (1930)` — An entire Inuit village found abruptly abandoned.
20. `The Bizarre Balloon Duel of 1808` — Two Frenchmen fought a duel over Paris in hot air balloons.
21. `The London Beer Flood of 1814` — A 323,000-gallon vat ruptured, flooding the streets with beer.
22. `The Great Molasses Flood of 1919` — A 2.3-million-gallon wave of molasses engulfed Boston at 35 mph.
23. `The Emu War of 1932` — Australian military deployed machine guns against 20,000 flightless birds.
24. `The Battle of Karansebes (1788)` — An army clashed with itself in darkness, suffering 1,000+ casualties.

---

## 2. Dynamic AI Discovery Fallback

When all curated seeds have been produced or quarantined, `intelligence/cloud_orchestrator.py` invokes `TopicDiscoveryEngine._discover_historical_topics()`:
- Calls Gemini 1.5/2.0 Pro/Flash with structured historical prompts.
- Prompts request obscure, verified, bizarre historical events from accredited historical archives.
- Extracted topics are checked against `ShortDuplicateGuard` and `is_niche_compliant()` before approval `[CODE VERIFIED]`.