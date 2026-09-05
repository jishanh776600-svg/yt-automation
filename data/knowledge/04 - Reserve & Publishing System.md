# 04 — Reserve & Publishing System

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** 6-Short reserve contract, 48-hour forward horizon scheduling, daily publishing limits, and vault folder reconciliation.  
> **Master Reference:** [[10 - Scheduling & Autopilot|48-Hour Forward Horizon Scheduler]]

---

## 1. Formal Reserve Contract

$$	ext{READY\_TARGET} = 6 	ext{ Verified Shorts in Google Drive Vault } 	exttt{01\_READY}$$
$$	ext{Deficit} = \max(0, 	ext{READY\_TARGET} - 	ext{CURRENT\_READY\_COUNT})$$

- Production produces only the missing deficit sequentially.
- If verified stock $\ge 6$, the production loop exits immediately with zero compute spend.

---

## 2. Rolling 48-Hour Forward Horizon

Implemented in `scheduler_engine.py`:
- Inspects publication slots across Today, Tomorrow, and Day+2.
- Respects the daily publishing ceiling: **`DAILY_SHORTS_LIMIT = 3 Shorts / calendar day`**.
- Slots: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`.
- If today's 3 slots are filled, the scheduler proactively schedules tomorrow's vacant slots or Day+2 slots.
- All uploads are created with `privacyStatus="private"` and `publishAt=slot` for automated release by YouTube.

---

## 3. Lifecycle Folder Reconciliation
- `01_READY`: Verified production reserve waiting for scheduling.
- `02_PROCESSING`: Claimed by scheduler; uploaded as scheduled private video on YouTube.
- `03_PUBLISHED`: Publicly released on YouTube; confirmed by `reconcile_scheduled_uploads()`.
- `04_FAILED`: Quarantined assets failing QA; never returned to `01_READY`.