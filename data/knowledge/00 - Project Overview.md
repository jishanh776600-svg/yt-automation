# 00 — Project Overview

> **Status:** `[LIVE & OPERATIONAL — CLOUD-AUTONOMOUS]`  
> **System Name:** AL-AMR (Autonomous Long-term Automated Media Reservoir)  
> **Domain:** Autonomous YouTube Shorts Production, Quality Assurance, Scheduling, and Telemetry Engine  
> **Repository:** `jishanh776600-svg/yt-automation`  
> **Master Portal:** [[00 - Master Dashboard|🛸 AL-AMR Master Dashboard]]

---

## 1. Executive Summary

**AL-AMR** is an enterprise-grade, fully autonomous content production and publishing operation running 24/7 on zero-cost cloud infrastructure without human intervention. The engine operates independently of the developer's local PC, terminal, or network.

The system discovers real-world discoveries and anomalies, deliberates across a multi-agent AI Council (DeepSeek, Kimi K3, Nemotron), generates 62–70 word high-retention scripts, synthesizes broadcast-quality narration with authoritative human delivery (Sarah / `af_sarah`), sources authentic visual evidence, edits vertical 1080x1920 videos at cinematic density (>=9 scenes), conducts rigorous multi-factor automated quality control, deposits verified assets into a Google Drive cloud vault, schedules releases into a rolling 48-hour horizon on YouTube (3 Shorts/day), and harvests YouTube Analytics telemetry for closed-loop learning.

---

## 2. Core Production Standards & Invariants

| Standard | Canonical Specification | Verification Method | Status |
|---|---|---|---|
| **System Status** | `🟢 LIVE / CLOUD-AUTONOMOUS` | GitHub Actions + Drive `00_SYSTEM` state | `LIVE` |
| **Approved Niches** | `1. Mystery / Bizarre Stories` & `2. Weird Science` | `is_niche_compliant()` in `clustering.py` | `ENFORCED` |
| **Banned Content** | `ZERO Politics, War, Military, Diplomacy` | Fail-closed keyword rejection list | `ENFORCED` |
| **Video Resolution** | `1080x1920` (9:16 Vertical Shorts format) | FFmpeg stream inspection | `ENFORCED` |
| **Short Duration** | `22.0s – 25.0s` (Canonical target: `~23.2s`) | MediaInfo + QA duration gate | `ENFORCED` |
| **Script Length** | Exactly `62 to 70 words` (High retention) | Council Quality Gate in `JournalisticScriptEngine` | `ENFORCED` |
| **Authoritative Voice** | **`af_sarah` (Sarah - US Female)** | Static voice lock (`af_bella` decommissioned) | `ENFORCED` |
| **Narration Pacing** | `0.08s sentence` / `0.03s clause` / `100ms cap` | Pause tuning + silence compression | `ENFORCED` |
| **Audio QA Gate** | Max pause $< 0.35$s, dead air $\le 18.0\%$ | Hard audio waveform gate in `VideoQAEngine` | `ENFORCED` |
| **Scene Density** | Minimum `9 unique scenes` (Target: 10–12) | Manifest cut count validation | `ENFORCED` |
| **Visual Deduplication**| Perceptual hashing (dHash) + 45-day cooldown | `GlobalVisualMemory` (`visual_memory.db`) | `ENFORCED` |
| **Story Deduplication** | 3-gram word shingles & semantic similarity | `ShortDuplicateGuard` (`short_fingerprints.db`) | `ENFORCED` |
| **Background Music** | **`ENABLED`** (4 tracks ducked 12–16dB below voice)| Stage B bed at `-30.0 LUFS`, voice `-14.0 LUFS` | `ENFORCED` |
| **Sound Effects (SFX)** | **`DISABLED`** (Permanently retired) | Hard-coded production pipeline flag | `ENFORCED` |
| **Publishing Ceiling** | Strictly $\le 3$ Shorts/day (`06:00, 11:00, 15:00 UTC`) | Database business day query | `ENFORCED` |
| **Forward Horizon** | Rolling `48-Hour Coverage` | `scheduler.get_vacant_slots_in_horizon()` | `ENFORCED` |
| **Target Vault Stock** | `6 verified Shorts` in Google Drive `01_READY` | Google Drive API inventory query | `ENFORCED` |
| **Production Mode** | Strictly `SEQUENTIAL` (1-by-1) | Next Short starts only after deposit | `ENFORCED` |

---

## 3. Canonical AL-AMR Knowledge Links

- [[00 - Master Dashboard|00. Master Operational Dashboard]]
- [[01 - Vision & Goals|01. Vision & Core Philosophy]]
- [[02 - Content Strategy|02. Authoritative Content Strategy]]
- [[03 - Architecture|03. Cloud Architecture & Distributed Locking]]
- [[04 - AI Council|04. Multi-Agent AI Council Architecture]]
- [[05 - Script Engine|05. High-Retention Journalistic Scripting]]
- [[06 - Audio & Voice|06. Sarah Voice Lock & Narration Pacing]]
- [[07 - Visual System|07. Visual Evidence & Global Visual Memory]]
- [[08 - Duplicate Protection|08. Short Duplicate Guard & Fingerprinting]]
- [[09 - Production Pipeline|09. Sequential Production & Refill Controller]]
- [[10 - Scheduling & Autopilot|10. 48-Hour Forward Horizon Scheduler]]
- [[11 - Cloud Infrastructure|11. GitHub Actions Cloud Execution]]
- [[12 - Google Drive Vault|12. Google Drive Vault & Database Persistence]]
- [[13 - QA & Testing|13. Multi-Factor Video & Audio QA System]]
- [[14 - Deployment & Operational State|14. Deployment Status & Live State]]
- [[15 - Historical Decisions|15. Historical Decisions & Superseded Architectures]]
- [[16 - Roadmap|16. Project Roadmap & Operational Observation]]
- [[17 - Operational Metrics|17. Closed-Loop Telemetry & YouTube Analytics]]