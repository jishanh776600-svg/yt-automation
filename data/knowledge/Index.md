# AL-AMR // Autonomous YouTube Shorts Production Brain

*Obsidian Knowledge Vault — Operational Intelligence & System Standards*  
*Last Synchronized: 2026-09-07 (System Status: 🟢 LIVE / CLOUD-AUTONOMOUS)* `[LIVE VERIFIED]`  
*Authoritative Master Portal:* [[01 — PROJECT MASTER/Project Overview|🛸 AL-AMR Master Portal]]  
*Latest Production Commit:* **`31c002c`** on `origin/main` `[CODE VERIFIED]`  

---

## 🏛 Canonical Production Invariants

| Invariant | Operational Standard | Verification Level | Canonical Link |
|---|---|---|---|
| **System Status** | `🟢 LIVE / CLOUD-AUTONOMOUS` | `[LIVE VERIFIED]` | [[01 — PROJECT MASTER/Project Overview|Project Overview]] |
| **Canonical Voice** | **`af_bella`** (Bella Kokoro-82M at native 1.00x) | `[LIVE VERIFIED]` | [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Bella Voice Spec]] |
| **Historical Voice** | `af_sarah` & `am_adam` permanently retired | `[HISTORICAL]` | [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|Voice Evolution]] |
| **Approved Niche** | **History / Historical Mysteries / Bizarre True Historical Events / Unexplained Stories** | `[LIVE VERIFIED]` | [[01 — PROJECT MASTER/Vision & Editorial Philosophy|Vision & Niche]] |
| **Banned Topics** | **ZERO Politics, Current Affairs, Geopolitics, Warfare, Diplomacy, Generic Science** | `[CODE VERIFIED]` | [[01 — PROJECT MASTER/Vision & Editorial Philosophy|Niche Red Lines]] |
| **Target Reserve** | **`6 Verified Shorts`** in Google Drive `01_READY` | `[LIVE VERIFIED]` | [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|Buffer Replenishment]] |
| **Refill Schedule** | **Every 3 Hours (`0 */3 * * *`)** | `[LIVE VERIFIED]` | [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|3-Hour Refill Cron]] |
| **Dynamic Deficit** | `max(0, 6 - actual_01_READY_count)` | `[CODE VERIFIED]` | [[02 — ARCHITECTURE/Unified Production Controller|Unified Controller]] |
| **Cloud Locking** | `CompositeLock` (900s TTL, 120s heartbeat, dead-runner reclamation, `--force-unlock`) | `[LIVE VERIFIED]` | [[02 — ARCHITECTURE/Distributed Cloud Locking|Cloud Locking]] |
| **Daily Publish Limit**| Strictly **`3 Shorts / calendar day`** (`06:00, 11:00, 15:00 UTC`) | `[CODE VERIFIED]` | [[05 — PUBLISHING/Forward Horizon Scheduling|Forward Scheduling]] |
| **Forward Horizon** | Rolling **`48-Hour Coverage`** | `[CODE VERIFIED]` | [[05 — PUBLISHING/Forward Horizon Scheduling|Forward Horizon]] |
| **Script Word Count** | Exactly **`58 to 72 words`** (Target: ~65 words) | `[CODE VERIFIED]` | [[04 — CONTENT PRODUCTION/Script Generation & Craftsmanship|Script Craftsmanship]] |
| **Short Duration** | `22.0s – 25.0s` (Target: `~23.0s`) | `[CODE VERIFIED]` | [[08 — TESTING/Verification Suite & QA Gates|VideoQA Gates]] |
| **Scene Density** | Minimum **`9 unique evidence scenes`** (0 script cards) | `[CODE VERIFIED]` | [[04 — CONTENT PRODUCTION/Visual Evidence & Composition|Visual Evidence]] |
| **Visual Memory** | Perceptual hashing (dHash) + 45-day cooldown | `[CODE VERIFIED]` | [[04 — CONTENT PRODUCTION/Duplicate Protection & Fingerprinting|Visual Memory]] |
| **Audio Standards** | Ducked BGM bed at `-30.0 LUFS`; voice `-14.0 LUFS`; SFX disabled | `[CODE VERIFIED]` | [[04 — CONTENT PRODUCTION/Audio Mastering & BGM Standards|Audio & BGM]] |
| **Execution Layer** | 100% Cloud (GitHub Actions `produce_buffer.yml`, `autopilot.yml`) | `[LIVE VERIFIED]` | [[03 — AUTONOMOUS OPERATIONS/Zero-PC Autonomy Specification|Zero-PC Autonomy]] |
| **Persistent Vault** | Google Drive `00_SYSTEM` through `04_FAILED` | `[LIVE VERIFIED]` | [[03 — AUTONOMOUS OPERATIONS/Google Drive Vault Lifecycle|Drive Vault]] |

---

## 🗺 Operational Knowledge Map (10-Tier Canonical Hierarchy)

### [[01 — PROJECT MASTER/Project Overview|Tier 01 — Project Master]]
- [[01 — PROJECT MASTER/Project Overview|01. Project Overview & Mission Card]]
- [[01 — PROJECT MASTER/Vision & Editorial Philosophy|02. Vision, Goals & Niche Boundary]]
- [[01 — PROJECT MASTER/Operating Principles & Invariants|03. Operating Principles & Engineering Invariants]]
- [[01 — PROJECT MASTER/Roadmap & Observation Strategy|04. Roadmap & Autonomous Observation]]

### [[02 — ARCHITECTURE/Cloud & Storage Topology|Tier 02 — Architecture]]
- [[02 — ARCHITECTURE/Cloud & Storage Topology|01. Cloud & Storage Topology (3-Tier Model)]]
- [[02 — ARCHITECTURE/Distributed Cloud Locking|02. Distributed Cloud Locking (CompositeLock & Hardening)]]
- [[02 — ARCHITECTURE/Unified Production Controller|03. Unified Controller (CloudProductionOrchestrator)]]
- [[02 — ARCHITECTURE/Multi-Tier Database Persistence|04. Multi-Tier Database Persistence & Sync]]

### [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|Tier 03 — Autonomous Operations]]
- [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|01. Buffer Replenishment (3-Hour Cadence)]]
- [[03 — AUTONOMOUS OPERATIONS/Autonomous Publication Workflow|02. Autonomous Publication (48h Forward Scheduler)]]
- [[03 — AUTONOMOUS OPERATIONS/Google Drive Vault Lifecycle|03. Google Drive Vault Lifecycle & Security]]
- [[03 — AUTONOMOUS OPERATIONS/Zero-PC Autonomy Specification|04. Zero-PC Autonomy Specification]]

### [[04 — CONTENT PRODUCTION/Production Pipeline Specification|Tier 04 — Content Production]]
- [[04 — CONTENT PRODUCTION/Production Pipeline Specification|01. 15-Stage Sequential Production Pipeline]]
- [[04 — CONTENT PRODUCTION/Script Generation & Craftsmanship|02. High-Retention Script Craftsmanship]]
- [[04 — CONTENT PRODUCTION/Narration & Bella Voice Specification|03. Narration & Bella Voice Specification]]
- [[04 — CONTENT PRODUCTION/Visual Evidence & Composition|04. Visual Evidence & Headless FFmpeg]]
- [[04 — CONTENT PRODUCTION/Audio Mastering & BGM Standards|05. Audio Mastering & BGM Normalization]]
- [[04 — CONTENT PRODUCTION/Duplicate Protection & Fingerprinting|06. Short Duplicate Guard & Visual Memory]]

### [[05 — PUBLISHING/Forward Horizon Scheduling|Tier 05 — Publishing]]
- [[05 — PUBLISHING/Forward Horizon Scheduling|01. Rolling 48-Hour Forward Horizon]]
- [[05 — PUBLISHING/YouTube Release & Metadata Protocol|02. YouTube Release & Scheduled Metadata]]
- [[05 — PUBLISHING/Publication Safety Gate|03. 15-Point Publication Safety Gate]]

### [[06 — INTELLIGENCE/Historical Topic Discovery & Curated Seeds|Tier 06 — Intelligence]]
- [[06 — INTELLIGENCE/Historical Topic Discovery & Curated Seeds|01. 24 Curated Mystery Seeds & Dynamic AI Fallback]]
- [[06 — INTELLIGENCE/Multi-Agent AI Council|02. Multi-Agent AI Council (DeepSeek/Kimi/Nemotron)]]
- [[06 — INTELLIGENCE/Closed-Loop Telemetry & Learning Engine|03. Closed-Loop Telemetry & Learning Engine]]
- [[06 — INTELLIGENCE/Decommissioned Current-Affairs Architecture|04. Decommissioned Current-Affairs Architecture [HISTORICAL]]]

### [[07 — MISSION CONTROL/Operational State & Inventory|Tier 07 — Mission Control]]
- [[07 — MISSION CONTROL/Operational State & Inventory|01. Operational State & Vault Inventory]]
- [[07 — MISSION CONTROL/Render Dashboard & Operator Queue|02. Render Dashboard & Review Queue Hygiene]]
- [[07 — MISSION CONTROL/Health Check & System Diagnostics|03. System Diagnostics & Health Check]]

### [[08 — TESTING/Verification Suite & QA Gates|Tier 08 — Testing]]
- [[08 — TESTING/Verification Suite & QA Gates|01. 15-Point VideoQA & AudioQA Gatekeeper]]
- [[08 — TESTING/Targeted Test Suites & AST Compliance|02. Targeted Test Suites & AST Compliance]]

### [[09 — INCIDENTS & FIXES/Incident Register & Forensic Log|Tier 09 — Incidents & Fixes]]
- [[09 — INCIDENTS & FIXES/Incident Register & Forensic Log|01. Incident Register & Forensics (Incidents 1–7)]]
- [[09 — INCIDENTS & FIXES/Incident 8 — Cloud Lock Deadlock & Seed Exhaustion|02. Incident 8: Cloud Lock Deadlock & Refill Recovery]]

### [[10 — CHANGELOG/System Master Changelog|Tier 10 — Changelog]]
- [[10 — CHANGELOG/System Master Changelog|01. System Master Changelog & Commit History]]