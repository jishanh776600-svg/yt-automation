---
aliases:
  - Project Overview
  - Master Overview
  - System Overview
tags:
  - project/overview
  - system/autonomous
  - status/live
last_updated: 2026-09-07
---

# 01 — Project Overview: AL-AMR

> **System Name:** AL-AMR (Autonomous Long-term Automated Media Reservoir)  
> **Domain:** 100% Autonomous YouTube Shorts Production, Quality Assurance, Scheduling, and Telemetry Engine  
> **Repository:** `jishanh776600-svg/yt-automation` (`main` branch)  
> **Authoritative Production Commit:** `31c002c` `[CODE VERIFIED]`  
> **Active Production Voice:** `af_bella` (Bella Kokoro-82M ONNX at native 1.00x) `[LIVE VERIFIED]`  
> **Vault Storage Layer:** Google Drive Private Cloud Vault (`YouTube_Shorts_Vault`) `[LIVE VERIFIED]`  
> **Cloud Compute:** GitHub Actions (`ubuntu-latest`) `[LIVE VERIFIED]`  

---

## 1. Executive Summary

**AL-AMR** is an enterprise-grade, fully autonomous content production and publishing engine operating 24/7 on zero-cost cloud infrastructure without human intervention `[LIVE VERIFIED]`. The engine operates completely independent of the developer's local PC, local terminal, home network, or desktop applications.

The system continuously discovers documented historical mysteries and bizarre true historical events, synthesizes high-retention 58–72 word narrative scripts via a multi-agent AI Council (DeepSeek, Kimi K3, Nemotron, Gemini), generates broadcast-quality narration with Bella (`af_bella`), sources authentic visual evidence, edits 1080x1920 vertical video at cinematic density (>=9 scenes), conducts rigorous automated quality control, deposits verified assets into a Google Drive cloud vault, schedules releases into a rolling 48-hour forward horizon on YouTube (strictly 3 Shorts/day), and harvests live YouTube Analytics telemetry for closed-loop learning `[CODE VERIFIED]`.

---

## 2. Core Production Invariants & Truth Matrix

| Dimension | Canonical Current State | Verification Level | Enforcement Mechanism |
|---|---|---|---|
| **Editorial Niche** | **History / Historical Mysteries / Bizarre True Historical Events / Unexplained Historical Stories** | `[LIVE VERIFIED]` | `is_niche_compliant()` in `clustering.py` + `CURATED_HISTORICAL_SEEDS` |
| **Banned Content** | **ZERO Politics, Current Affairs, Geopolitics, Warfare, Elections, or Generic Science** | `[CODE VERIFIED]` | Fail-closed keyword rejection list in `intelligence/clustering.py` |
| **Active Narration Voice** | **`af_bella` (Bella Kokoro-82M ONNX at native 1.00x speed)** | `[LIVE VERIFIED]` | Static voice lock in `engines/tts_engine.py` (Run #47 verified: `short_man_c85a0dd30bda.mp4`) |
| **Decommissioned Voice** | **`af_sarah` (Sarah) & `am_adam` (Adam) permanently decommissioned** | `[HISTORICAL]` | Hard rejection guards in `ShortsPipeline.__init__()` and `TTSEngine` |
| **Buffer Reserve Target** | **`6 Verified Shorts` in Google Drive `01_READY`** | `[LIVE VERIFIED]` | Drive API query in `produce_buffer.yml` & `maintain_buffer()` |
| **Autonomous Refill Cycle** | **Every 3 hours (`0 */3 * * *`)** | `[LIVE VERIFIED]` | GitHub Actions cron trigger in `.github/workflows/produce_buffer.yml` |
| **Refill Computation** | **Dynamic deficit: max(0, 6 - actual_01_READY_count)** | `[CODE VERIFIED]` | `CloudProductionOrchestrator.run_production_cycle(target_buffer=6)` |
| **Execution Environment** | **100% Cloud Autonomy (GitHub Actions `ubuntu-latest`)** | `[LIVE VERIFIED]` | Zero local PC dependency; state persisted to Drive `00_SYSTEM` |
| **Distributed Cloud Lock** | **`CompositeLock` with 900s TTL, 120s heartbeat, dead-runner reclamation, `--force-unlock`** | `[LIVE VERIFIED]` | `core/cloud_lock.py` hardened against deadlocks (Commit `31c002c`) |
| **Review Queue Hygiene** | **119 legacy unreviewed jobs archived; active queue filtered to <48h** | `[LIVE VERIFIED]` | `dashboard/action_manager.py:archive_legacy_review_jobs()` |
| **Video Resolution** | **`1080x1920` (9:16 Vertical Shorts format)** | `[CODE VERIFIED]` | Headless FFmpeg video composer |
| **Short Duration** | **`22.0s – 25.0s` (Target: ~23.0s)** | `[CODE VERIFIED]` | `VideoQAEngine` duration gate |
| **Visual Density** | **>= 9 unique physical evidence scenes (0 script-card frames)** | `[CODE VERIFIED]` | Multi-checkpoint temporal frame inspection |
| **Visual Deduplication** | **Perceptual hashing (dHash) + 45-day cooldown** | `[CODE VERIFIED]` | `GlobalVisualMemory` (`visual_memory.db`) |
| **Story Deduplication** | **3-gram word shingles & title semantic similarity** | `[CODE VERIFIED]` | `ShortDuplicateGuard` (`short_fingerprints.db`) |
| **Background Music** | **ENABLED: 4 approved tracks ducked to -30.0 LUFS Stage B bed** | `[CODE VERIFIED]` | Master voiceover at -14.0 LUFS (12–16 dB voice dominance) |
| **Sound Effects (SFX)** | **PERMANENTLY DISABLED (zero whooshes, memes, or synthetic SFX)** | `[CODE VERIFIED]` | Hardcoded `has_sfx=False` production flag |
| **Publishing Ceiling** | **Strictly <= 3 Shorts/day (`06:00, 11:00, 15:00 UTC`)** | `[CODE VERIFIED]` | `engines/scheduler_engine.py` slot audit |
| **Forward Horizon** | **Rolling 48-Hour Coverage** | `[CODE VERIFIED]` | `scheduler.get_vacant_slots_in_horizon()` |
| **Production Mode** | **Strictly SEQUENTIAL (1 Short at a time)** | `[CODE VERIFIED]` | Short N+1 begins only after Short N passes QA and deposits |

---

## 3. Master Navigation Index

- **Tier 01 — Project Master**: [[01 — PROJECT MASTER/Project Overview|Overview]] | [[01 — PROJECT MASTER/Vision & Editorial Philosophy|Vision & Niche]] | [[01 — PROJECT MASTER/Operating Principles & Invariants|Operating Principles]] | [[01 — PROJECT MASTER/Roadmap & Observation Strategy|Roadmap]]
- **Tier 02 — Architecture**: [[02 — ARCHITECTURE/Cloud & Storage Topology|Storage Topology]] | [[02 — ARCHITECTURE/Distributed Cloud Locking|Cloud Locking]] | [[02 — ARCHITECTURE/Unified Production Controller|Production Controller]] | [[02 — ARCHITECTURE/Multi-Tier Database Persistence|Database Sync]]
- **Tier 03 — Autonomous Operations**: [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|Buffer Replenishment]] | [[03 — AUTONOMOUS OPERATIONS/Autonomous Publication Workflow|Autonomous Publication]] | [[03 — AUTONOMOUS OPERATIONS/Google Drive Vault Lifecycle|Drive Vault Lifecycle]] | [[03 — AUTONOMOUS OPERATIONS/Zero-PC Autonomy Specification|Zero-PC Autonomy]]
- **Tier 04 — Content Production**: [[04 — CONTENT PRODUCTION/Production Pipeline Specification|Pipeline Spec]] | [[04 — CONTENT PRODUCTION/Script Generation & Craftsmanship|Script Craftsmanship]] | [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Spec]] | [[04 — CONTENT PRODUCTION/Visual Evidence & Composition|Visual Evidence]] | [[04 — CONTENT PRODUCTION/Audio Mastering & BGM Standards|Audio & BGM]] | [[04 — CONTENT PRODUCTION/Duplicate Protection & Fingerprinting|Duplicate Protection]]
- **Tier 05 — Publishing**: [[05 — PUBLISHING/Forward Horizon Scheduling|Forward Scheduling]] | [[05 — PUBLISHING/YouTube Release & Metadata Protocol|Release Protocol]] | [[05 — PUBLISHING/Publication Safety Gate|Safety Gate]]
- **Tier 06 — Intelligence**: [[06 — INTELLIGENCE/Historical Topic Discovery & Curated Seeds|Historical Discovery & Seeds]] | [[06 — INTELLIGENCE/Multi-Agent AI Council|AI Council]] | [[06 — INTELLIGENCE/Closed-Loop Telemetry & Learning Engine|Telemetry Learning]] | [[06 — INTELLIGENCE/Decommissioned Current-Affairs Architecture|Historical Decommissioned Specs]]
- **Tier 07 — Mission Control**: [[07 — MISSION CONTROL/Operational State & Inventory|Operational State]] | [[07 — MISSION CONTROL/Render Dashboard & Operator Queue|Dashboard & Review Queue]] | [[07 — MISSION CONTROL/Health Check & System Diagnostics|Health Checks]]
- **Tier 08 — Testing**: [[08 — TESTING/Verification Suite & QA Gates|QA Gates & Verification]] | [[08 — TESTING/Targeted Test Suites & AST Compliance|Test Suites & AST]]
- **Tier 09 — Incidents & Fixes**: [[09 — INCIDENTS & FIXES/Incident Register & Forensic Log|Incident Register]] | [[09 — INCIDENTS & FIXES/Incident 8 — Cloud Lock Deadlock & Seed Exhaustion|Incident 8 Post-Mortem]]
- **Tier 10 — Changelog**: [[10 — CHANGELOG/System Master Changelog|Master Changelog]]