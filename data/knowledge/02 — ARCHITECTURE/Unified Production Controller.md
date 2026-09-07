---
aliases:
  - Unified Controller
  - CloudProductionOrchestrator
tags:
  - architecture
  - orchestrator
last_updated: 2026-09-07
---

# Unified Production Controller: CloudProductionOrchestrator

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Canonical orchestration entrypoint unifying GitHub Actions, local CLI, and daemon execution vectors `[CODE VERIFIED]`.

---

## 1. Single Canonical Controller Architecture

To prevent behavioral drift between cloud runs and manual testing, all video production routes through a single canonical controller:
[`intelligence/cloud_orchestrator.py:CloudProductionOrchestrator`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/cloud_orchestrator.py) `[CODE VERIFIED]`.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       CANONICAL EXECUTION INGRESS                           │
├──────────────────────────┬──────────────────────────┬───────────────────────┤
│ GitHub Actions Workflow  │ Local Maintenance CLI    │ Continuous Daemon     │
│ `produce_buffer.yml`     │ `python main.py          │ `python main.py       │
│ (Cron: 0 */3 * * *)      │   --maintain-buffer 6`   │   --daemon`           │
└────────────┬─────────────┴────────────┬─────────────┴───────────┬───────────┘
             │                          │                         │
             └──────────────────────────┼─────────────────────────┘
                                        ▼
                     ┌────────────────────────────────────┐
                     │    CloudProductionOrchestrator     │
                     │  .run_production_cycle(target=6)   │
                     └──────────────────┬─────────────────┘
                                        ▼
                     ┌────────────────────────────────────┐
                     │ 1. CompositeLock Acquisition       │
                     │ 2. Google Drive Inventory Audit    │
                     │ 3. Sequential Deficit Production   │
                     │ 4. VideoQA Validation Hard Gate    │
                     │ 5. Drive Vault Deposit & DB Sync   │
                     └────────────────────────────────────┘
```

---

## 2. Dynamic Refill Algorithm

```python
ready_count = drive_engine.get_ready_stock_count()
deficit = max(0, target_buffer - ready_count)

if deficit == 0:
    logger.info("Ready stock (%d) >= target (%d). Exiting with zero compute spend.", ready_count, target_buffer)
    return {"status": "SUCCESS", "deficit": 0, "produced": 0}
```

The orchestrator guarantees that if the reserve is already satisfied, zero API quota and zero render time are consumed `[CODE VERIFIED]`.