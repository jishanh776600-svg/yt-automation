---
aliases:
  - Production Pipeline
  - Sequential Production
tags:
  - pipeline
  - production
  - orchestrator
last_updated: 2026-09-05
---

# 09 — Sequential Production & Refill Controller

> **Status:** `[CANONICAL INVARIANT — STRICT ENFORCEMENT]`  
> **Scope:** Sequential 1-by-1 production invariant, reserve deficit math, CloudProductionOrchestrator execution, and fail-closed deposit rules.

---

## 1. The Critical Sequential Production Invariant

> [!CAUTION]
> **ARCHITECTURAL INVARIANT: STRICTLY SEQUENTIAL PRODUCTION**  
> Videos are produced, rendered, QA-verified, and deposited **strictly ONE AT A TIME**. Under no circumstances does the system spawn parallel render processes or generate 6 scripts simultaneously.

```
CORRECT (SEQUENTIAL EXECUTION):
Script 1 ──► Council ──► Visuals ──► TTS ──► Render ──► QA ──► Deposit 01_READY ──► DB Sync
                                                                                          │
┌─────────────────────────────────────────────────────────────────────────────────────────┘
▼
Script 2 ──► Council ──► Visuals ──► TTS ──► Render ──► QA ──► Deposit 01_READY ──► DB Sync
                                                                                          │
┌─────────────────────────────────────────────────────────────────────────────────────────┘
▼
Script 3 ──► ...

INCORRECT (STRICTLY BANNED):
Spawn 6 parallel threads ──► Run 6 Kokoro processes ──► Overwrite state / crash memory
```

### Why Sequential Production is Mandatory
1. **Runner Memory & FFmpeg Safety:** Cloud runners (`ubuntu-latest` 2-core / 7GB RAM) will suffer OOM crashes if multiple video rendering tasks compete for RAM.
2. **Deterministic Visual Memory:** Short 2 needs the updated `visual_memory.db` state from Short 1 so it knows which assets were just used and cannot be repeated.
3. **Graceful Failure Isolation:** If Short 1 fails QA or runs out of API tokens, the runner halts cleanly without wasting compute on subsequent Shorts.

---

## 2. Reserve Deficit Mathematics

The reserve buffer target is fixed at **`TARGET_BUFFER = 6 Shorts`** in Google Drive `01_READY`.

The orchestrator dynamically calculates the exact missing deficit:

$$	ext{Deficit} = \max(0, 	ext{TARGET\_BUFFER} - 	ext{CURRENT\_READY\_COUNT})$$

```
+---------------+---------------------+------------------------+------------------------------------+
| Ready In Vault| Calculated Deficit  | Production Target      | Autonomous Pipeline Action         |
+---------------+---------------------+------------------------+------------------------------------+
|       0       |          6          |           6            | Full sequential refill (6 cycles)  |
|       1       |          5          |           5            | Multi-item sequential refill (5)   |
|       2       |          4          |           4            | Multi-item sequential refill (4)   |
|       3       |          3          |           3            | Multi-item sequential refill (3)   |
|       4       |          2          |           2            | Multi-item sequential refill (2)   |
|       5       |          1          |           1            | Single replenishment cycle (1)     |
|   6 or more   |          0          |           0            | IDLE (Zero compute / Zero spend)   |
+---------------+---------------------+------------------------+------------------------------------+
```

---

## 3. End-to-End Production Stages

Executed by [`intelligence/cloud_orchestrator.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/cloud_orchestrator.py):

1. **Stage 1: Distributed Lock Acquisition:** Acquires `CompositeLock` (`production` + `CloudLockManager`).
2. **Stage 2: Canonical Database Download:** Synchronizes `pipeline.db` and auxiliary DBs from `00_SYSTEM/`.
3. **Stage 3: Vault Inventory Audit:** Queries Drive `01_READY` using `is_valid_ready_short()` to establish true verified stock.
4. **Stage 4: News Ingestion & Niche Filtering:** Ingests live news wires; filters strictly via `is_niche_compliant()` (rejects all politics).
5. **Stage 5: Multi-Agent AI Council Deliberation:** DeepSeek, Kimi K3, and Nemotron analyze, critique, and synthesize the narrative.
6. **Stage 6: Council Quality Gate:** Validates 62–70 words, 0 clichés, curiosity hook.
7. **Stage 7: Visual Evidence Retrieval:** Sourcing authentic photos/records via `VisualEvidenceRetrievalEngine`.
8. **Stage 8: Production Asset Manifest:** Assembles beat-by-beat timeline with Ken Burns directives and transitions.
9. **Stage 9: Kokoro Sarah Narration:** Synthesizes `af_sarah` with 0.08s sentence, 0.03s clause, and 100ms silence compression.
10. **Stage 10: Headless Video Composition:** FFmpeg renders 1080x1920 MP4 with burned-in karaoke ASS subtitles and ducked BGM.
11. **Stage 11: Multi-Factor Video QA:** Evaluates pauses (<0.35s), dead air (<=18%), duration (22–25s), and black frames.
12. **Stage 12: Vault Deposit:** Uploads verified video directly into Google Drive `01_READY`.
13. **Stage 13: State Persistence & Release:** Updates SQLite and auxiliary DBs; synchronizes back to `00_SYSTEM/`; releases locks.

---

## 4. Architectural Links
- Master Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Council Review: [[04 - AI Council|AI Council]]
- Audio Synthesis: [[06 - Audio & Voice|Audio & Voice]]
- Cloud Vault: [[12 - Google Drive Vault|Google Drive Vault]]
- Forward Scheduling: [[10 - Scheduling & Autopilot|Autonomous Scheduler]]