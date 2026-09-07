# 00 — Project Overview

> **Status:** `[LIVE & OPERATIONAL — CLOUD-AUTONOMOUS]` `[LIVE VERIFIED]`  
> **System Name:** AL-AMR (Autonomous Long-term Automated Media Reservoir)  
> **Domain:** Autonomous YouTube Shorts Production, Quality Assurance, Scheduling, and Telemetry Engine  
> **Repository:** `jishanh776600-svg/yt-automation`  
> **Master Portal:** [[01 — PROJECT MASTER/Project Overview|🛸 AL-AMR Master Portal]]  

---

## 1. Executive Summary

**AL-AMR** is an enterprise-grade, fully autonomous content production and publishing operation running 24/7 on zero-cost cloud infrastructure without human intervention. The engine operates independently of the developer's local PC, terminal, or network `[LIVE VERIFIED]`.

The system discovers documented historical mysteries and bizarre events, deliberates across a multi-agent AI Council (DeepSeek, Kimi K3, Nemotron, Gemini), generates 58–72 word high-retention scripts, synthesizes broadcast-quality narration with Bella (`af_bella`), sources authentic visual evidence, edits vertical 1080x1920 videos at cinematic density (>=9 scenes), conducts rigorous multi-factor automated quality control, deposits verified assets into a Google Drive cloud vault, schedules releases into a rolling 48-hour horizon on YouTube (3 Shorts/day), and harvests YouTube Analytics telemetry for closed-loop learning `[CODE VERIFIED]`.

---

## 2. Core Production Standards & Invariants

| Standard | Canonical Specification | Verification Method | Status |
|---|---|---|---|
| **System Status** | `🟢 LIVE / CLOUD-AUTONOMOUS` | GitHub Actions + Drive `00_SYSTEM` state | `[LIVE VERIFIED]` |
| **Approved Niche** | `History / Historical Mysteries / Bizarre Real-World Events` | `is_niche_compliant()` in `clustering.py` | `[LIVE VERIFIED]` |
| **Banned Content** | `ZERO Politics, Current Affairs, Warfare, Military, Generic Science Facts` | Fail-closed keyword rejection list | `[CODE VERIFIED]` |
| **Video Resolution** | `1080x1920` (9:16 Vertical Shorts format) | FFmpeg stream inspection | `[CODE VERIFIED]` |
| **Short Duration** | `22.0s – 25.0s` (Canonical target: `~23.0s`) | MediaInfo + QA duration gate | `[CODE VERIFIED]` |
| **Script Philosophy**| Conversational creator storytelling ("Tell me what happened") | 58–72 words, no academic cliches or fact dumps | `[CODE VERIFIED]` |
| **Authoritative Voice**| **`af_bella` (Bella - US Female at native 1.00x)** | Static voice lock (`af_sarah` decommissioned) | `[LIVE VERIFIED]` |
| **Narration Pacing** | Natural human creator delivery (~1.00x Kokoro) | Natural pauses, zero artificial speedups | `[LIVE VERIFIED]` |
| **Audio QA Gate** | Max pause <= 0.35s, dead air <= 18.0% | Hard audio waveform gate in `VideoQAEngine` | `[CODE VERIFIED]` |
| **Visual Requirements**| Real footage/photos throughout; **0 Script-Card Frames** | Temporal multi-checkpoint frame inspection | `[CODE VERIFIED]` |
| **Visual Deduplication**| Perceptual hashing (dHash) + 45-day cooldown | `GlobalVisualMemory` (`visual_memory.db`) | `[CODE VERIFIED]` |
| **Story Deduplication** | 3-gram word shingles & semantic similarity | `ShortDuplicateGuard` (`short_fingerprints.db`) | `[CODE VERIFIED]` |
| **Background Music** | **`ENABLED`** (4 tracks ducked below voice) | Mastered loudness `-14.0 LUFS` / bed `-30.0 LUFS` | `[CODE VERIFIED]` |
| **Sound Effects (SFX)** | **`DISABLED`** (Permanently retired) | Hard-coded production pipeline flag | `[CODE VERIFIED]` |
| **Publishing Ceiling** | Strictly <= 3 Shorts/day (`06:00, 11:00, 15:00 UTC`) | Database business day query | `[CODE VERIFIED]` |
| **Forward Horizon** | Rolling `48-Hour Coverage` | `scheduler.get_vacant_slots_in_horizon()` | `[CODE VERIFIED]` |
| **Target Vault Stock** | `6 verified Shorts` in Google Drive `01_READY` | Google Drive API inventory query | `[LIVE VERIFIED]` |
| **Autonomous Refill** | `Every 3 Hours (0 */3 * * *)` | GitHub Actions cron in `produce_buffer.yml` | `[LIVE VERIFIED]` |
| **Production Mode** | Strictly `SEQUENTIAL` (1-by-1) | Next Short starts only after deposit | `[CODE VERIFIED]` |

---

## 3. Canonical 10-Tier Hierarchy Links

- [[01 — PROJECT MASTER/Project Overview|Tier 01 — Project Master]]
- [[02 — ARCHITECTURE/Cloud & Storage Topology|Tier 02 — Architecture]]
- [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|Tier 03 — Autonomous Operations]]
- [[04 — CONTENT PRODUCTION/Production Pipeline Specification|Tier 04 — Content Production]]
- [[05 — PUBLISHING/Forward Horizon Scheduling|Tier 05 — Publishing]]
- [[06 — INTELLIGENCE/Historical Topic Discovery & Curated Seeds|Tier 06 — Intelligence]]
- [[07 — MISSION CONTROL/Operational State & Inventory|Tier 07 — Mission Control]]
- [[08 — TESTING/Verification Suite & QA Gates|Tier 08 — Testing]]
- [[09 — INCIDENTS & FIXES/Incident Register & Forensic Log|Tier 09 — Incidents & Fixes]]
- [[10 — CHANGELOG/System Master Changelog|Tier 10 — Changelog]]