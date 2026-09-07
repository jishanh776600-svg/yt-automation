---
aliases:
  - Forward Horizon Scheduling
  - Autonomous Scheduler
tags:
  - publishing
  - scheduling
last_updated: 2026-09-07
---

# Forward Horizon Scheduling

> **Status:** `[LIVE & VERIFIED]`  
> **Forward Buffer Window:** Continuous rolling **48-Hour Coverage** `[CODE VERIFIED]`  
> **Daily Ceiling:** Strictly **<= 3 Shorts / calendar day** `[CODE VERIFIED]`  
> **Release Slots:** `06:00 UTC`, `11:00 UTC`, `15:00 UTC` `[LIVE VERIFIED]`  

---

## 1. Rolling 48-Hour Forward Horizon Architecture

Unlike naive systems that only inspect the current day, AL-AMR maintains a continuous **48-hour forward publication buffer**:

```
[NOW: Reference Time UTC]
  │
  ├─► DAY 0 (Today)     : Evaluates 06:00, 11:00, 15:00 UTC slots
  ├─► DAY 1 (Tomorrow)  : Evaluates 06:00, 11:00, 15:00 UTC slots
  └─► DAY 2 (Forward)   : Evaluates forward slots up to NOW + 48 hours
```

Implemented in [`engines/scheduler_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/scheduler_engine.py) via `get_vacant_slots_in_horizon()`:
- Scans all prospective publication slots across Today, Tomorrow, and Day+2 within a rolling 48-hour window.
- Respects the daily ceiling: **`DAILY_SHORTS_LIMIT = 3 Shorts / calendar day`**.
- If Today's 3 slots are already filled, the scheduler claims ready Shorts to fill tomorrow's vacant slots or Day+2 slots.
- Guarantees the channel never goes dark, even if cloud production is paused for 48 hours `[CODE VERIFIED]`.