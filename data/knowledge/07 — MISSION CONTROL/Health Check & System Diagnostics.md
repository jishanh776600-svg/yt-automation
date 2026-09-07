---
aliases:
  - Health Check
  - System Diagnostics
tags:
  - mission-control
  - diagnostics
last_updated: 2026-09-07
---

# Health Check & System Diagnostics

> **Status:** `[LIVE & VERIFIED]`  
> **Diagnostic Tool:** `python main.py --health-check` `[CODE VERIFIED]`  
> **Execution Status:** 9/9 Categories Verified Healthy `[LIVE VERIFIED]`  

---

## 1. 9-Category Diagnostic Verification

```
┌────────────────────────┬────────────┬───────────────────────────────────────┐
│ Category               │ Status     │ Diagnostics                           │
├────────────────────────┼────────────┼───────────────────────────────────────┤
│ Database               │ PASS       │ Database healthy (22 tables verified, │
│                        │            │ journal_mode=wal)                     │
│ Configuration          │ PASS       │ Batch Ceiling: 8, Attempt: 12, Cap: 24│
│ YouTube Auth           │ PASS       │ Upload + Analytics scopes authorized  │
│ Google Drive           │ PASS       │ Drive Vault healthy (01_READY: 1)     │
│ External APIs          │ PASS       │ Gemini, DeepSeek, Nvidia, Groq active │
│ Local Environment      │ PASS       │ Free disk: 199.7 GB, FFmpeg confirmed │
│ Locks                  │ PASS       │ All process locks available (0 held)  │
│ Pipeline Engines       │ PASS       │ All 16 core pipeline engines healthy  │
│ Safety Guardrails      │ PASS       │ All 8 safety guardrails active        │
└────────────────────────┴────────────┴───────────────────────────────────────┘
OVERALL STATUS: SYSTEM READY FOR PRODUCTION (9/9 Passed, 0 Failures)
```