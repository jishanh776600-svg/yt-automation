# 13 — Current-Affairs Intelligence Layer

> [!WARNING]
> **SUPERSEDED EXPERIMENT / HISTORICAL ARCHIVE**  
> The Geopolitics and Breaking News editorial direction was thoroughly evaluated and **permanently abandoned**.  
> **Active Production Strategy:** The channel focuses exclusively on **Mystery/Bizarre Real-World Stories** and **Weird Science / Unbelievable Facts**. All conventional politics, warfare, military conflict, and diplomacy are fail-closed rejected via `is_niche_compliant`.  
> **Master Reference:** [[02 - Content Strategy|Authoritative Content Strategy]] and [[15 - Historical Decisions|Historical Decisions (Geopolitics Pivot)]]

---

## 1. Architectural Overview (Historical Architecture)

The Current-Affairs Intelligence Layer introduces an autonomous, zero-cost intelligence pipeline that harvests, normalizes, clusters, scores, and corroborates real-world geopolitical events prior to script generation.

```
+---------------------------------------------------------------------------------------------------+
| ISOLATED CURRENT-AFFAIRS INTELLIGENCE PIPELINE                                                    |
+---------------------------------------------------------------------------------------------------+
| [1. LIVE SOURCES]        --> Public Wire RSS Feeds (BBC, Reuters, AP) & GDELT 2.0 API            |
|                                    │                                                              |
|                                    ▼                                                              |
| [2. NORMALIZATION]       --> Deterministic boilerplate stripping, URL canonicalization,          |
|                              entity, country, and action-stem extraction (Zero LLM cost)          |
|                                    │                                                              |
|                                    ▼                                                              |
| [3. EVENT CLUSTERING]    --> Multi-article event grouping. Distinguishes distinct events in same  |
|                              city/year by combining actors, action domains, and title tokens.     |
|                                    │                                                              |
|                                    ▼                                                              |
| [4. FRESHNESS & VELOCITY]--> Calibrated age decay: BREAKING (<3h: 100), DEVELOPING (3-12h: 90),   |
|                              FRESH (12-24h: 80), RECENT (24-48h: 60), MATURING (48-72h: 40).      |
|                                    │                                                              |
|                                    ▼                                                              |
| [5. RELEVANCE & TAXONOMY]--> Western-audience geopolitical significance filter. Maps events into  |
|                              CurrentAffairsCategory (GEOPOLITICS, GLOBAL_CONFLICT, DIPLOMACY, etc)|
|                                    │                                                              |
|                                    ▼                                                              |
| [6. EVIDENCE GATE]       --> MANDATORY INVARIANT: >= 2 independent reputable publisher domains    |
|                              required. Single-source items remain INSUFFICIENT_EVIDENCE.          |
|                                    │                                                              |
|                                    ▼                                                              |
| [7. OPPORTUNITY SCORING] --> Composite formula: (0.30 Freshness) + (0.25 Relevance) +             |
|                              (0.20 SourceBreadth) + (0.15 NarrativeTension) + (0.10 Velocity).     |
|                                    │                                                              |
|                                    ▼                                                              |
| [8. CA DEDUPLICATION]    --> Event-level signature comparison against existing SQLite topics.     |
|                              Allows distinct 2026 same-city events (e.g. military vs trade).      |
|                                    │                                                              |
|                                    ▼                                                              |
| [9. TOPIC PERSISTENCE]   --> Promotes qualifying candidates to Topic(status="APPROVED") and       |
|                              creates SourceRecord entries with canonical wire URLs.               |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Multi-Source Evidence Invariant

To guarantee absolute factual integrity and prevent single-source rumors or satire from entering production:
- **Hard Gate:** An `EventCluster` MUST have articles from at least **$\ge 2$ independent reputable publisher domains** (e.g., `bbc.com` + `reuters.com`).
- **Single-Source Rejection:** Any event covered by only 1 publisher domain is tagged `INSUFFICIENT_EVIDENCE` and will never be promoted to `status="APPROVED"`.
- **Evidence Auditability:** Every approved `Topic` has its supporting wire URLs stored in `SourceRecord` entries in SQLite.

---

## 3. Disambiguation of Same-Year / Same-City Events

In current affairs, 100% of candidate events occur in the same year (e.g. 2026). The historical `(Year, Location)` collision heuristic is superseded in this layer by a multi-dimensional event signature:
- **Action Domain Classification:** Distinguishes `DEFENSE_CONFLICT` (military strikes, troop deployments), `TRADE_ECONOMY` (tariffs, currency agreements), `DOMESTIC_POLITICS` (elections, resignations), and `DIPLOMACY` (summits, treaties).
- **Invariance Rule:** Two stories occurring in the same city (e.g. London in 2026) with distinct action domains or distinct actors (e.g., UK Defense Ministry Baltic deployment vs UK-Australia trade agreement) are recognized as completely independent events and are never rejected as duplicate collisions.

---

## 4. Current-Affairs Category Taxonomy

Configured in `config/constants.py` via `CurrentAffairsCategory`:
- `GEOPOLITICS`
- `GLOBAL_CONFLICT`
- `WORLD_POLITICS`
- `US_POLITICS`
- `EUROPE_POLITICS`
- `GLOBAL_ECONOMY`
- `DIPLOMACY`
- `SECURITY`
- `MAJOR_WORLD_EVENT`

*Note: Existing `HistoricalCategory` remains 100% untouched and functional.*

---

## 5. Isolation & Production Safety Boundaries

1. **Separation of Concerns:** The intelligence layer is located in the `intelligence/` package and has zero dependencies on `render_engine.py`, `upload_engine.py`, or `scheduler_engine.py`.
2. **Graceful Fail-Safe:** If all RSS or GDELT endpoints are unreachable or timeout, the intelligence cycle catches exceptions, logs structured notices, and returns an empty list. Downstream topic discovery automatically falls back to curated historical seeds.
3. **Zero Automated Publishing Overrun:** Production limits (`DAILY_SHORTS_LIMIT = 3`, publishing slots at 06:00, 11:00, 15:00 UTC) remain strictly locked in `scheduler_engine.py`.