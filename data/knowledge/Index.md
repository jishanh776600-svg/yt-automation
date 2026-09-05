# AL-AMR // Autonomous YouTube Shorts Production Brain

*Obsidian Knowledge Vault — Operational Intelligence & System Standards*  
*Last Synchronized: 2026-09-05 (System Status: 🟢 LIVE / CLOUD-AUTONOMOUS)*  
*Authoritative Master Portal:* [[00 - Master Dashboard|🛸 AL-AMR Master Dashboard]]

---

## 🏛 Core System Invariants

| Invariant | Operational Standard | Enforcement |
|---|---|---|
| **System Status** | `🟢 LIVE / CLOUD-AUTONOMOUS` | GitHub Actions + Drive `00_SYSTEM` state |
| **Canonical Voice** | **`af_sarah`** (Sarah - US Female) | [[Voice/af_sarah_canonical|af_sarah]] (Bella decommissioned) |
| **Approved Niches** | `1. Mystery/Bizarre` & `2. Weird Science` | [[02 - Content Strategy|Content Strategy]] (`is_niche_compliant`) |
| **Banned Topics** | `ZERO Politics, War, Military, Diplomacy` | Fail-closed keyword rejection gate |
| **Publishing Rotation**| `Day A (2 Mystery + 1 Science)` / `Day B (1 Mystery + 2 Science)` | Alternating daily cadence |
| **Daily Publish Limit**| Strictly **`3 Shorts / day`** | `06:00 UTC`, `11:00 UTC`, `15:00 UTC` |
| **Forward Horizon** | Rolling **`48-Hour Coverage`** | [[10 - Scheduling & Autopilot|Autonomous Scheduler]] |
| **Target Reserve** | **`6 Verified Shorts`** in `01_READY` | [[09 - Production Pipeline|Sequential Production Refill]] |
| **Target Duration** | `22.0s – 25.0s` (Target: `~23.2s`) | Duration calibration in `TTSEngine` |
| **Script Word Count** | Exactly **`62 to 70 words`** | [[04 - AI Council|Council Quality Gate]] |
| **Narration Pacing** | `0.08s sentence` / `0.03s clause` / `100ms cap` | [[06 - Audio & Voice|Audio & Voice Pacing]] |
| **Audio QA Gate** | `Max pause < 0.35s` / `Dead air <= 18%` | [[13 - QA & Testing|Multi-Factor QA System]] |
| **Scene Density** | Minimum **`9 unique scenes`** (Target 10–12) | [[07 - Visual System|Visual System]] |
| **Deduplication** | Perceptual hashing (dHash) + 90-day cooldown | [[08 - Duplicate Protection|Short Duplicate Guard]] |
| **Audio Mixing** | Ducked BGM across 4 tracks; SFX disabled | Stage B bed at `-30.0 LUFS`, voice `-14.0 LUFS` |
| **Execution Layer** | GitHub Actions (`produce_buffer.yml`, `autopilot.yml`) | [[11 - Cloud Infrastructure|Cloud Infrastructure]] |
| **Persistent Vault** | Google Drive `00_SYSTEM` through `04_FAILED` | [[12 - Google Drive Vault|Google Drive Vault]] |

---

## 🗺 Operational Workflow Topology

```
[[02 - Content Strategy|01. Live News & Event Ingestion]] ──► is_niche_compliant (Reject Politics)
                           │
                           ▼
[[04 - AI Council|02. AI Council Deliberation]] ────────────► DeepSeek + Kimi K3 + Nemotron
                           │
                           ▼
[[05 - Script Engine|03. High-Retention Scripting]] ────────► 62-70 words, 22-25s, 0 clichés
                           │
                           ▼
[[06 - Audio & Voice|04. Kokoro Sarah Narration]] ──────────► af_sarah, 0.08s/0.03s, 100ms compression
                           │
                           ▼
[[07 - Visual System|05. Visual Evidence & Manifest]] ──────► >=9 unique scenes, dHash dedup
                           │
                           ▼
[[09 - Production Pipeline|06. Sequential Rendering & QA]] ─► 1-by-1 render, Audio & Video QA
                           │
                           ▼
[[12 - Google Drive Vault|07. Drive 01_READY Deposit]] ─────► Reserve Buffer (Target: 6 Shorts)
                           │
                           ▼
[[10 - Scheduling & Autopilot|08. 48-Hour Forward Scheduler]] ──► 3 slots/day (06:00, 11:00, 15:00 UTC)
                           │
                           ▼
[[17 - Operational Metrics|09. Closed-Loop Telemetry]] ─────► 24h maturation, APV/AVD learning
```

---

## 📂 Canonical Knowledge Directory (AL-AMR Vault)

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

---

## 🏛 Legacy & Specialized Sub-Domains
- [[Voice/af_sarah_canonical|Canonical Voice: af_sarah]]
- [[Voice/af_bella_canonical|Decommissioned Voice: af_bella]]
- [[BGM/acoustic_standards|BGM Acoustic Standards & Bed Normalization]]
- [[SFX/sfx_integration|Decommissioned SFX System]]
- [[13 - Current Affairs Intelligence Layer|Superseded Geopolitics Experiment]]