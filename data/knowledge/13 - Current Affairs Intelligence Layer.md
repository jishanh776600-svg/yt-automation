# 13 — Current-Affairs Intelligence Layer

> [!WARNING]
> **SUPERSEDED EXPERIMENT / HISTORICAL ARCHIVE** `[HISTORICAL]`  
> The Geopolitics, Breaking News, and Current Affairs editorial direction was thoroughly evaluated and **permanently abandoned**.  
> **Active Canonical Strategy:** The channel focuses exclusively on **History / Historical Mysteries / Bizarre True Historical Events / Unexplained Historical Stories**. All conventional politics, warfare, military conflict, elections, and diplomacy are fail-closed rejected via `is_niche_compliant`.  
> **Master Reference:** [[01 — PROJECT MASTER/Vision & Editorial Philosophy|Vision & Editorial Philosophy]] and [[06 — INTELLIGENCE/Decommissioned Current-Affairs Architecture|Decommissioned Current-Affairs Architecture]]

---

## 1. Architectural Overview (Historical Experiment)

The Current-Affairs Intelligence Layer introduced an experimental pipeline that harvested, normalized, clustered, and corroborated real-world geopolitical events prior to script generation `[HISTORICAL]`.

```
+---------------------------------------------------------------------------------------------------+
| ISOLATED CURRENT-AFFAIRS INTELLIGENCE PIPELINE [HISTORICAL - DECOMMISSIONED]                       |
+---------------------------------------------------------------------------------------------------+
| [1. LIVE SOURCES]        --> Public Wire RSS Feeds (BBC, Reuters, AP) & GDELT 2.0 API            |
|                                    │                                                              |
|                                    ▼                                                              |
| [2. NORMALIZATION]       --> Deterministic boilerplate stripping, URL canonicalization            |
|                                    │                                                              |
|                                    ▼                                                              |
| [3. EVENT CLUSTERING]    --> Multi-article event grouping                                         |
|                                    │                                                              |
|                                    ▼                                                              |
| [4. FRESHNESS & VELOCITY]--> Calibrated age decay (<3h: 100, 3-12h: 90, 12-24h: 80)              |
|                                    │                                                              |
|                                    ▼                                                              |
| [5. EVIDENCE GATE]       --> >= 2 independent reputable publisher domains required                |
|                                    │                                                              |
|                                    ▼                                                              |
| [6. TOPIC PERSISTENCE]   --> Stored in SQLite Topic tables                                         |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Rationale for Permanent Decommissioning

1. **Verification Liability:** High risk of reporting errors on developing stories.
2. **Rapid Audience Decay:** Breaking news loses 80%+ viewership velocity within 24 hours.
3. **Monetization Sensitivity:** YouTube advertiser-friendly guidelines frequently flag conflict/political events.
4. **Canonical Production Target:** Evergreen Historical Mysteries guarantee long-term algorithmic shelf life, universal appeal, and verified public domain physical evidence `[LIVE VERIFIED]`.