---
aliases:
  - Publication Workflow
  - autopilot.yml
  - Autonomous Scheduler
tags:
  - operations
  - publishing
  - autopilot
last_updated: 2026-09-07
---

# Autonomous Publication Workflow (`autopilot.yml`)

> **Status:** `[LIVE & VERIFIED]`  
> **Trigger:** Cron `0 6,11,15 * * *` (Daily 06:00, 11:00, 15:00 UTC) `[LIVE VERIFIED]`  
> **Forward Horizon:** Rolling 48 hours forward coverage `[CODE VERIFIED]`  
> **Daily Ceiling:** Strictly <= 3 Shorts per calendar day `[CODE VERIFIED]`  

---

## 1. Publication Cadence (3 Daily Slots)

AL-AMR enforces a strict 3-Short daily publication schedule aligned to global viewership peaks:

| Slot | UTC Time | IST Time (Asia/Kolkata) | Target Global Audience |
|---|---|---|---|
| **Slot 1** | `06:00 UTC` | `11:30 AM IST` | Morning APAC & Midday Europe commute |
| **Slot 2** | `11:00 UTC` | `04:30 PM IST` | Afternoon Europe & Early morning Americas |
| **Slot 3** | `15:00 UTC` | `08:30 PM IST` | Peak US East Coast & Evening Europe |

---

## 2. 48-Hour Forward Horizon Audit

Executed in `engines/scheduler_engine.py:get_vacant_slots_in_horizon()`:
- Inspects slots for **Day 0 (Today)**, **Day 1 (Tomorrow)**, and **Day 2 (Forward)**.
- If today's 3 slots are filled, scheduler claims ready Shorts to fill tomorrow's vacant slots `[CODE VERIFIED]`.
- All videos are uploaded as **scheduled private uploads** on YouTube with `publishAt` timestamps.
- **Zero Immediate Public Uploads:** Prevents algorithm shock and preserves consistent release cadence `[CODE VERIFIED]`.