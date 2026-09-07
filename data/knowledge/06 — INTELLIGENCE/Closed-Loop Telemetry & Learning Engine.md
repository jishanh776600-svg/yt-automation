---
aliases:
  - Telemetry & Learning
  - Closed-Loop Learning
  - Analytics Engine
tags:
  - intelligence
  - analytics
  - telemetry
last_updated: 2026-09-07
---

# Closed-Loop Telemetry & Learning Engine

> **Status:** `[LIVE & HARVESTING]`  
> **Telemetry Policy:** Strictly **LIVE CLOUD TRUTH ONLY**; zero hardcoded, synthetic, or fake metrics `[LIVE VERIFIED]`.  
> **Maturation Gate:** Videos must be published for $\ge 24\text{ hours}$ before analytics harvesting `[CODE VERIFIED]`.  

---

## 1. Analytics Harvesting Architecture

Executed by GitHub Actions on scheduled cadence (`harvest_analytics.yml`):

```mermaid
flowchart TD
    CRON["Daily Trigger (harvest_analytics.yml)"] --> DB["Query UploadRecord (status=PUBLISHED)"]
    DB --> GATE{"Published > 24 Hours Ago?"}
    GATE -->|No: Immature| SKIP["Skip (Preserve statistical validity)"]
    GATE -->|Yes: Mature| API["Call YouTube Analytics API & Data API v3"]
    API --> STORE["Store Snapshot in PerformanceSnapshot (SQLite)"]
    API --> APV["Calculate APV (Average Percentage Viewed)"]
    STORE --> WEIGHTS["Update Topic & Hook Weights via UCB1"]
```

---

## 2. Telemetry Grounding Rule: Zero Fake Data

- The system strictly forbids placeholder views, simulated CTRs, or fabricated retention graphs.
- Every metric stored in `PerformanceSnapshot` originates directly from authenticated Google YouTube Analytics API endpoints.
- If an endpoint returns 0 views (e.g. for newly released Shorts), the raw zero is recorded honestly `[LIVE VERIFIED]`.