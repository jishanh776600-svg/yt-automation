---
aliases:
  - Operating Principles
  - Engineering Invariants
  - System Rules
tags:
  - architecture
  - principles
  - invariants
last_updated: 2026-09-07
---

# Operating Principles & Engineering Invariants

> **Status:** `[CANONICAL SPECIFICATION — ENFORCED IN CODE]`  
> **Scope:** Architectural invariants, concurrency boundaries, and failure isolation rules across all AL-AMR subsystems `[CODE VERIFIED]`.

---

## 1. The 12 Inviolable Engineering Invariants

1. **Zero Local PC Dependency:** The system must run completely unattended in the cloud via GitHub Actions. If the developer's laptop is powered off or disconnected for a month, production and publishing must proceed unaffected `[LIVE VERIFIED]`.
2. **Single Distributed Controller:** All execution vectors (GitHub Actions workflows, local CLI, background daemons) must route exclusively through `CloudProductionOrchestrator` `[CODE VERIFIED]`.
3. **Sequential Execution Only:** Videos are rendered, verified, and vaulted **one at a time**. Parallel video rendering is prohibited to prevent resource exhaustion and race conditions `[CODE VERIFIED]`.
4. **Reserve Deficit Dynamism:** Buffer replenishment computes the deficit as max(0, 6 - actual_01_READY_count). If stock is >= 6, the workflow exits immediately with zero spend `[LIVE VERIFIED]`.
5. **Fail-Closed Locking:** Distributed locks (`CompositeLock`) must automatically break stale deadlocks after 900s, refresh heartbeats every 120s, reclaim dead runner locks, and support `--force-unlock` CLI override `[LIVE VERIFIED]`.
6. **Canonical Voice Invariant:** Narration is locked to `af_bella` (Bella Kokoro-82M ONNX at native 1.00x). Sarah (`af_sarah`) and Adam (`am_adam`) are permanently decommissioned. Whitelist is strictly `APPROVED_PRODUCTION_VOICES = ["af_bella"]` (Commit `b4dd8f6306368859f07352adf42deb0b1de6199a`) `[LIVE VERIFIED]`.
7. **Absolute Niche Purity:** Content is restricted strictly to Historical Mysteries and Bizarre True Historical Events. Zero tolerance for politics, war, current affairs, or generic science `[CODE VERIFIED]`.
8. **Permanent SFX Retirement:** Sound effects are permanently disabled in production. Audio mixing is strictly voiceover plus ducked background music (-30.0 LUFS) `[CODE VERIFIED]`.
9. **Zero Fabricated Metrics:** The system records and displays only live, verifiable telemetry from GitHub Actions and YouTube Analytics. Fake, placeholder, or synthetic performance stats are prohibited `[LIVE VERIFIED]`.
10. **Non-Destructive Quarantine:** Corrupted, failing, or obsolete assets are moved to `04_FAILED` or archived. No asset is silently deleted from the vault `[CODE VERIFIED]`.
11. **Authoritative Publication Gateway Barrier:** Direct file moves into `03_PUBLISHED` are blocked at code level (`drive_engine.py` raises `InvariantViolationError` if `_from_gateway=False`). Transitions into `03_PUBLISHED` must proceed exclusively through `core/lifecycle_gateway.py` with verified live YouTube read-back (`privacyStatus == 'public'`) `[CODE VERIFIED]`.
12. **Pre-READY Content Quality Gate:** No video may enter `01_READY` without passing `core/content_quality_gate.py`, verifying semantic era/visual consistency, phonetic pronunciation normalization, storyboard pacing, loop ending strategy, and duration bounds [22.0, 27.0]s `[CODE VERIFIED]`.

---

## 2. Concurrency & Locking Matrix

| Subsystem | Lock Name | Storage Location | Timeout / TTL | Behavior on Contention |
|---|---|---|---|---|
| **Buffer Maintenance** | `cloud_production` | Drive `00_SYSTEM/locks/` + PID | 900 seconds (15 min) | Graceful exit (`status=BLOCKED`), dead-runner reclamation `[CODE VERIFIED]` |
| **Scheduler / Publishing** | `cloud_publisher` | Drive `00_SYSTEM/locks/` + PID | 900 seconds (15 min) | Graceful exit (`status=BLOCKED`), dead-runner reclamation `[CODE VERIFIED]` |
| **Analytics Harvesting** | `analytics` | Drive `00_SYSTEM/locks/` + PID | 900 seconds (15 min) | Graceful exit (`status=BLOCKED`) `[CODE VERIFIED]` |
| **Stale Daemon Guard** | Local PID / Heartbeat | `data/` runtime locks | 120 seconds | Blocks unverified or orphaned local processes from mutating state `[CODE VERIFIED]` |

---

## 3. Storage Hierarchy Invariant

- **Ephemeral Cloud Runner:** Scratch disk only. Destroyed after each workflow run `[LIVE VERIFIED]`.
- **Google Drive Cloud Vault:** The canonical durable state. Holds the SQLite database, locks, and media files `[LIVE VERIFIED]`.
- **Local Machine:** Merely an administrative remote terminal. Does not host production state `[LIVE VERIFIED]`.