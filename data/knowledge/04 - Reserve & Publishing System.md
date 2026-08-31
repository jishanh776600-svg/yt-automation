# 04 — Reserve & Publishing System

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** 6-Short reserve contract, producer/publisher decoupling, daily publishing limits, and self-maintaining equilibrium.  

---

## 1. Formal Reserve Contract

$$	ext{READY\_TARGET} = 6	ext{ Shorts in Google Drive Vault } 	exttt{01\_READY}$$
$$	ext{Deficit} = \max(0, 	ext{READY\_TARGET} - 	ext{CURRENT\_READY\_COUNT})$$

```
+---------------+---------------------+------------------------+------------------------------------+
| Ready In Vault| Calculated Deficit  | Batch Target Size      | Autonomous Pipeline Action         |
+---------------+---------------------+------------------------+------------------------------------+
|       0       |          6          |           6            | Full autonomous refill cycle       |
|       1       |          5          |           5            | Multi-item deficit refill          |
|       2       |          4          |           4            | Multi-item deficit refill          |
|       3       |          3          |           3            | Multi-item deficit refill          |
|       4       |          2          |           2            | Multi-item deficit refill          |
|       5       |          1          |           1            | Single replenishment cycle         |
|       6       |          0          |           0            | IDLE (Zero API / Render / Vault)   |
+---------------+---------------------+------------------------+------------------------------------+
```

---

## 2. Decoupled Producer & Publisher Architecture

```
+---------------------------------------------------------------------------------------------------+
| DECOUPLED LIFECYCLE                                                                               |
+---------------------------------------------------------------------------------------------------+
|                                                                                                   |
| [PRODUCER] (produce_buffer.yml @ 02:00 UTC)                                                       |
|   1. Audits Drive Vault 01_READY.                                                                 |
|   2. Computes Deficit = max(0, 6 - Stock).                                                        |
|   3. If Deficit == 0 -> Exits immediately (Zero cost).                                            |
|   4. If Deficit > 0 -> Produces verified Shorts sequentially until 01_READY reaches 6.            |
|                                                                                                   |
| [PUBLISHER] (autopilot.yml @ 06:00, 11:00, 15:00 UTC)                                             |
|   1. Audits published_today + scheduled_today in current business day.                           |
|   2. If total >= 3 -> Exits immediately (Publishing ceiling respected).                           |
|   3. If total < 3 -> Claims oldest Short from 01_READY -> Moves to 02_SCHEDULED -> Schedules on YT.|
|                                                                                                   |
| [EQUILIBRIUM]                                                                                     |
|   Publisher consumes 1 Short -> Stock drops to 5 -> Producer runs -> Restores stock to 6.        |
+---------------------------------------------------------------------------------------------------+
```

---

## 3. Business Calendar Bounds & Invariants

- **Canonical Business Timezone**: `Asia/Kolkata` (IST = UTC+5:30)
- **Daily Publishing Limit**: Exactly **3 Shorts/day** (`DAILY_SHORTS_LIMIT = 3`).
- **Publishing Slots**:
  1. `06:00 UTC` (11:30 AM IST)
  2. `11:00 UTC` (04:30 PM IST)
  3. `15:00 UTC` (08:30 PM IST) — Business day cutoff.
- **Safety Invariant**: $	ext{published\_today} + 	ext{scheduled\_today} \le 3$.
- **Idempotency**: Scheduling queries check YouTube video status and existing database records to guarantee zero duplicate uploads.