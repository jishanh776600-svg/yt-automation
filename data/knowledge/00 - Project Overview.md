# 00 — Project Overview

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **System Name:** AL AMR (Autonomous Long-term Automated Media Reservoir)  
> **Domain:** Autonomous YouTube Shorts Production, Quality Assurance, Scheduling, and Telemetry Engine  
> **Repository:** `jishanh776600-svg/yt-automation`  
> **Latest Milestone:** Step 27 (Root-Cause Audit & Reserve Refill Hardening) + BGM Loudness Standardization  

---

## 1. Executive Summary

**AL AMR** is an enterprise-grade, fully autonomous content production and publishing operation designed to run indefinitely on zero-cost infrastructure. The engine autonomously discovers under-explored historical topics, verifies historical accuracy, generates high-retention 5-beat documentary scripts, synthesizes broadcast-quality narration, sources high-resolution archival and AI-reconstructed visual assets, mixes adaptive background audio with acoustic fingerprinting, renders vertical 1080x1920 videos, executes multi-factor automated quality control, deposits verified assets into a 3-tier Google Drive vault, schedules public YouTube releases, harvests live YouTube Analytics telemetry, and updates strategy weights via closed-loop reinforcement learning.

```
+---------------------------------------------------------------------------------------------------+
| END-TO-END AUTONOMOUS PIPELINE FLOW                                                                |
+---------------------------------------------------------------------------------------------------+
| [1. TOPIC DISCOVERY]  --> [2. FACT VERIFICATION]  --> [3. RETENTION SCRIPTING]                     |
|           │                         │                               │                             |
|           ▼                         ▼                               ▼                             |
| [4. ASSET INGESTION]  --> [5. KOKORO TTS AUDIO]   --> [6. ACOUSTIC BGM MIXING]                    |
|           │                         │                               │                             |
|           ▼                         ▼                               ▼                             |
| [7. VERTICAL FFMPEG]  --> [8. MULTI-FACTOR QA]    --> [9. GOOGLE DRIVE VAULT (01_READY)]          |
|           │                         │                               │                             |
|           ▼                         ▼                               ▼                             |
| [10. YT SCHEDULING]   --> [11. ANALYTICS HARVEST] --> [12. UCB1 LEARNING ENGINE]                  |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Core Production Standards & Invariants

| Standard | Canonical Specification | Verification Method | Enforcement Level |
|---|---|---|---|
| **Video Resolution** | `1080x1920` (9:16 Vertical Shorts format) | FFmpeg stream inspection | `STRICT` (Non-negotiable) |
| **Framerate** | `30.0 FPS` progressive scan | FFmpeg container metadata | `STRICT` |
| **Duration Target** | `21.0s – 25.0s` (Container margin up to `26.2s`) | MediaInfo + QA duration gate | `STRICT` (Anti-truncation) |
| **TTS Narration Model** | Kokoro-82M ONNX (`af_bella` American English) | Local offline neural synthesis | `STRICT` (100% Zero-cost) |
| **Voice Consistency** | `af_bella` exclusively across all channel output | Static voice configuration | `STRICT` |
| **Master Loudness** | `-14.0 LUFS` integrated (Broadcast standard) | EBU R128 acoustic filter audit | `STRICT` (`-17.0` to `-11.0` range) |
| **Peak Audio Ceiling** | True Peak $\le 0.0	ext{ dBTP}$ (Target $-1.0	ext{ dBTP}$) | FFmpeg volumedetect / peak | `STRICT` (Zero clipping) |
| **BGM Bed Loudness** | `-30.0 LUFS` standardized Stage B bed | EBU R128 Stage B normalization | `STRICT` ($\ge 12	ext{ dB}$ below voice) |
| **Outro Breathing Room** | $\ge 0.6	ext{s}$ trailing video after speech ends | Audio duration vs video duration | `STRICT` (Prevents speech cutoff) |
| **Visual Beat Cadence** | 7 to 10 visual cuts per 22-second Short | Scene director shot manifest | `STRICT` (High viewer retention) |
| **Asset Provenance** | SHA-256 asset hash + Source Manifest | SQLite `AssetRecord` table | `STRICT` (Full auditability) |
| **Commercial Rights** | Commercial use permitted ($0 cost, CC0, Pexels, MIT, PD) | LicenseTracker verification | `STRICT` (Zero copyright risk) |
| **Publishing Ceiling** | $\le 3	ext{ Shorts/day}$ (`06:00, 11:00, 15:00 UTC`) | Database business day query | `STRICT` (Anti-spam protection) |
| **Target Vault Stock** | `6` verified Shorts in Google Drive `01_READY` | Google Drive API inventory query | `STRICT` (Durable reserve buffer) |

---

## 3. Key Architectural Links

- [[01 - Architecture|01. Architecture Overview & System Components]]
- [[02 - Production Pipeline|02. Complete Production Pipeline Deep-Dive]]
- [[03 - AI Provider Strategy|03. AI Provider Hierarchy & Economics]]
- [[04 - Reserve & Publishing System|04. Reserve Contract & Publishing Engine]]
- [[05 - Analytics & Learning Engine|05. YouTube Analytics & Reinforcement Learning]]
- [[06 - Audio & BGM System|06. Audio Engineering & BGM Standardization]]
- [[07 - Testing & Verification|07. Testing Infrastructure & Regression Suites]]
- [[08 - Failure Forensics & Fixes|08. Real-World Production Failures & Root-Cause Fixes]]
- [[09 - Operational State|09. Current Operational State & Inventory]]
- [[10 - Decisions & Engineering Principles|10. Engineering Principles & Operating Philosophy]]
- [[11 - Commercial Product Roadmap|11. Future Commercial Product Roadmap]]
- [[12 - Change Log|12. Chronological Engineering Change Log]]