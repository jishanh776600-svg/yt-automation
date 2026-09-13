---
aliases:
  - System Changelog
  - Change Log
  - Master Changelog
tags:
  - changelog
  - history
  - commits
last_updated: 2026-09-07
---

# 10 — System Master Changelog: AL-AMR

> **Status:** `[SINGLE SOURCE OF SYSTEM EVOLUTION TRUTH]`  
> **Current Authoritative Commit:** `b4dd8f6306368859f07352adf42deb0b1de6199a` on `origin/main` `[CODE VERIFIED]`  

---

## Chronological Release Register

| Release / Step | Date | Milestone & Description | Verification Evidence | Claim Status |
|---|---|---|---|---|
| **Step 48** | 2026-09-13 | **Surgical Rollback & Authoritative Voice Lock to Bella (`af_bella`)**<br/>Commit `b4dd8f6306368859f07352adf42deb0b1de6199a`. Restored `af_bella` as the sole authoritative production voice across all configuration files, engines (`tts_engine.py`, `visual_intelligence/voice_policy.py`, `orchestrator.py`, `main.py`), and GitHub Actions workflows (`produce_buffer.yml`). Locked whitelist to `APPROVED_PRODUCTION_VOICES = ["af_bella"]`. Unapproved voice requests fail closed to `af_bella`. | 25/25 targeted voice/content tests, 7/7 cloud autonomy tests, and 40/40 negative lifecycle invariant tests passed cleanly. | `[CODE VERIFIED]` |
| **Step 47** | 2026-09-13 | **Content Quality Upgrade & Autonomous Video Assembly Hardening**<br/>Implemented script-aware visual intelligence, era & context consistency validation, phonetic pronunciation normalization for historical numbers/years (`engines/tts_normalizer.py`), dynamic storyboard pacing (`engines/storyboard_engine.py`), ducked BGM with permanent SFX disablement, seamless narrative ending & loop strategy (`engines/ending_strategy.py`), and pre-READY Content Quality Gate (`core/content_quality_gate.py`). | 12/12 content quality tests passed; full automated assembly pipeline verified. | `[CODE VERIFIED]` |
| **Step 46** | 2026-09-07 | **Lifecycle Hardening & Authoritative Publication Gateway Barrier**<br/>Commits `846cfb7`, `036a7c3`, `a888e6f`, `b626812`, `9a1ebc5`. Hardened publication gateway (`core/lifecycle_gateway.py`), enforced physical `03_PUBLISHED` barrier in Drive vault (`_from_gateway` check), implemented strict YouTube read-back verification (`privacyStatus == 'public'`), eliminated stale daemon mutations via heartbeat/PID checks, segregated producer and publisher concurrency locks, and safely recovered 7 falsely-published Bella Shorts back to `01_READY` with 100% DB and Drive consistency. | 40/40 adversarial negative invariant tests passed. | `[CODE VERIFIED]` |
| **Step 45** | 2026-09-07 | **Obsidian Master Documentation Reconciliation**<br/>Complete vault audit and reconciliation into 10-tier canonical hierarchy. Purged all contradictory claims regarding voice (`af_bella` confirmed canonical, `af_sarah` tagged historical), niche (strictly History / Historical Mysteries, zero politics/current affairs), 3-hour buffer refill (`0 */3 * * *`), lock hardening (900s TTL + heartbeat + dead-runner reclamation), and honest telemetry. | Full vault grep verification; 100% classification compliance. | `[CODE VERIFIED]` |
| **Step 44** | 2026-09-07 | **Incident 8 Fixes: Cloud Lock Hardening & Refill Recovery**<br/>Commit `31c002c`. Shortened cloud lock TTL to 900s, added 120s background heartbeat thread, implemented GitHub API dead-runner reclamation, added `--force-unlock` CLI override and workflow input. Expanded `CURATED_HISTORICAL_SEEDS` to 24 verified historical mysteries + added dynamic Gemini AI discovery fallback. Reconciled Render dashboard with live GitHub workflow telemetry and archived 119 legacy unreviewed review queue jobs. | GitHub Actions Run #47 (`34054429381`) succeeded in 14m 26s; deposited Bella Short `short_man_c85a0dd30bda.mp4` (Drive ID `1I3X-S4OsuWUW4Ubv8v7nB-nI760dLMzx`) into `01_READY`. | `[LIVE VERIFIED]` |
| **Step 43** | 2026-09-05 | **100% Cloud Autonomy & 48-Hour Horizon Scheduler**<br/>Commit `54112e7`. Implemented `CompositeLock` integrating local ProcessLock with Drive `CloudLockManager`. Engineered rolling 48-hour forward horizon scheduler (`autopilot.yml`) targeting 3 daily slots (`06:00, 11:00, 15:00 UTC`). Enforced zero local PC dependency. | Ephemeral runner tests pass; round-trip database synchronization verified. | `[LIVE VERIFIED]` |
| **Step 42** | 2026-09-04 | **Unified Cloud Production Orchestrator**<br/>Built `intelligence/cloud_orchestrator.py` as single canonical controller across cloud workflows, CLI, and daemons. Added linear state progression, QA hard gate, and crash recovery. | 23/23 orchestration tests pass. | `[CODE VERIFIED]` |
| **Step 41** | 2026-09-03 | **Refill Recovery & Deduplication Fixes**<br/>Commit `f554d99`. Fixed false-COMPLETED topic pollution and self-matching topic deduplication. Restored clean candidate topic progression. | 8/8 targeted dedup tests pass. | `[CODE VERIFIED]` |
| **Step 40** | 2026-09-03 | **Bella Voice Canonical Default Enforcement**<br/>Commit `2f1098e`. Coerced all stale `am_adam` database rows and code defaults to `af_bella` at native 1.00x speed. Added dual guards rejecting decommissioned voices. | 8/8 voice tests pass; native Bella generation confirmed. | `[LIVE VERIFIED]` |
| **Step 39** | 2026-09-03 | **Production HTTP 500 Fix (`python-dateutil`)**<br/>Commit `80b1f65`. Replaced unlisted `python-dateutil` with stdlib-only `datetime.fromisoformat()` helper with explicit UTC normalization. | Live Render deployment `/health` returned HTTP 200. | `[LIVE VERIFIED]` |
| **Step 38** | 2026-09-02 | **EBU R128 Stage B BGM Bed Normalization**<br/>Standardized BGM bed to `-30.0 LUFS` with master voiceover at `-14.0 LUFS` (12–16 dB voice dominance). Permanently retired all Sound Effects (SFX). | FFmpeg loudnorm verification across all 4 approved library tracks. | `[CODE VERIFIED]` |
| **Step 37** | 2026-09-01 | **Current-Affairs Intelligence Layer Experiment**<br/>Built RSS wire scrapers, GDELT 2.0 adapters, and entity clustering. | Evaluated and permanently abandoned in favor of Evergreen Historical Mysteries. | `[HISTORICAL]` |
| **Step 1–36**| 2026-08-15 | **Core Pipeline Inception & Early Audio/Video Engines**<br/>Initial creation of Kokoro TTS synthesis, headless FFmpeg video composer, SQLite persistence, and multi-agent AI Council. | Baseline pipeline operational. | `[HISTORICAL]` |