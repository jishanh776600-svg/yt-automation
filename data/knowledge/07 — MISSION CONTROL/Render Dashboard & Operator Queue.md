---
aliases:
  - Render Dashboard
  - Operator Queue
  - Review Queue Hygiene
tags:
  - mission-control
  - dashboard
  - review-queue
last_updated: 2026-09-07
---

# Render Dashboard & Operator Queue

> **Status:** `[LIVE & RECONCILED — COMMIT 31c002c]`  
> **Telemetry Integration:** Direct integration with live GitHub Actions workflow telemetry `[LIVE VERIFIED]`.  
> **Review Queue Hygiene:** 119 legacy unreviewed jobs archived; active queue filtered to $<48\text{ hours}$ `[LIVE VERIFIED]`.  

---

## 1. Live Workflow Telemetry vs Stale Status Fix

Prior to commit `31c002c`, the Render dashboard reported "Last Refill Audit: SUCCEEDED" even when scheduled buffer replenishment runs were failing in GitHub Actions:
- **Root Cause:** Dashboard read from a stale local audit cache rather than live GitHub API run states.
- **Permanent Solution:** Replaced static audit checks with `dashboard/data_provider.py` querying GitHub API via `GitHubWorkflowDispatcher`. If the latest buffer run failed or deficit $>0$, the dashboard honestly reports `FAILED` and `NEEDED` `[LIVE VERIFIED]`.

---

## 2. Review Queue Cleanup & Archival

- **Legacy Clutter:** The operator review queue had accumulated 123 jobs dating back weeks.
- **Archival Action:** Added `dashboard/action_manager.py:archive_legacy_review_jobs()`, which moved 119 unreviewed legacy jobs into `status="ARCHIVED"` `[LIVE VERIFIED]`.
- **Active Queue Policy:** The dashboard now displays only jobs created within the last 48 hours, keeping the active operator review queue clean (4 current active items) `[LIVE VERIFIED]`.