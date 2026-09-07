---
aliases:
  - Operational State
  - Drive Inventory
  - Live State
tags:
  - mission-control
  - state
  - inventory
last_updated: 2026-09-07
---

# Operational State & Inventory

> **Status:** `[SINGLE SOURCE OF OPERATIONAL TRUTH]`  
> **Last Audited:** `2026-09-07 15:00 UTC`  
> **Overall Verdict:** **`🟢 LIVE / CLOUD-AUTONOMOUS`** `[LIVE VERIFIED]`  
> **Authoritative Commit:** **`31c002c`** on `origin/main` `[CODE VERIFIED]`  

---

## 1. Google Drive Vault Inventory (`YouTube_Shorts_Vault`)

| Vault Tier | Folder Path | Item Count | Status | Notes |
|---|---|---|---|---|
| **00_SYSTEM** | `YouTube_Shorts_Vault/00_SYSTEM` | Synchronized | Healthy | Contains `youtube_automation.db`, `visual_memory.db`, `short_fingerprints.db`, and `locks/`. |
| **01_READY** | `YouTube_Shorts_Vault/01_READY` | **1 Short** | Verified Reserve | Verified Short: `short_man_c85a0dd30bda.mp4` (Bella, 1.00x). Deficit = 5. `[LIVE VERIFIED]` |
| **02_PROCESSING** | `YouTube_Shorts_Vault/02_PROCESSING` | 0 Shorts | Idle | In-flight scheduled uploads. |
| **03_PUBLISHED** | `YouTube_Shorts_Vault/03_PUBLISHED` | 22 Shorts | Live | Live mature videos on YouTube. |
| **04_FAILED** | `YouTube_Shorts_Vault/04_FAILED` | 5 Files | Quarantined | Obsolete test files safely isolated. |

---

## 2. Live Verified Production Short in 01_READY

- **File Name:** `short_man_c85a0dd30bda.mp4`
- **Drive File ID:** `1I3X-S4OsuWUW4Ubv8v7nB-nI760dLMzx`
- **Production Run:** GitHub Actions Run #47 (`34054429381`) executed on 2026-09-07 (14m 26s runtime) `[LIVE VERIFIED]`.
- **Narration Voice:** `af_bella` (Bella Kokoro-82M ONNX at native 1.00x).
- **QA Verification:** Passed all 15 video, audio, and duration gates cleanly `[LIVE VERIFIED]`.