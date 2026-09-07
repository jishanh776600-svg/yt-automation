---
aliases:
  - Cloud Infrastructure
  - GitHub Actions Workflows
tags:
  - cloud
  - github-actions
  - devops
last_updated: 2026-09-07
---

# 11 — GitHub Actions Cloud Execution

> **Status:** `[LIVE & VERIFIED]`  
> **Master Reference:** [[03 — AUTONOMOUS OPERATIONS/Buffer Replenishment Workflow|Buffer Replenishment]] & [[03 — AUTONOMOUS OPERATIONS/Zero-PC Autonomy Specification|Zero-PC Autonomy]]  
> **Refill Cron:** Every 3 Hours (`0 */3 * * *`) `[LIVE VERIFIED]`  
> **Publisher Cron:** Daily 3 Slots (`0 6,11,15 * * *`) `[LIVE VERIFIED]`  

---

## 1. Cloud Execution Topology

All AL-AMR operations execute inside ephemeral virtual environments provided by GitHub Actions (`ubuntu-latest`):

```
+---------------------------------------------------------------------------------------------------+
| GITHUB ACTIONS WORKFLOW TOPOLOGY                                                                  |
+---------------------------------------------------------------------------------------------------+
| 1. produce_buffer.yml (CRON: 0 */3 * * * - Every 3 Hours UTC)                                     |
|    - Runner: ubuntu-latest (Python 3.11, FFmpeg, fonts-dejavu-core)                               |
|    - Inputs: target_buffer (default 6), force_unlock (boolean)                                    |
|    - Secrets: GEMINI_API_KEY, DEEPSEEK_API_KEY, NVIDIA_API_KEY, GROQ_API_KEY, TOKEN_JSON, etc.    |
|    - Action: Downloads DB from 00_SYSTEM -> Audits 01_READY -> Produces deficit -> Uploads DB.    |
|    - Live Verification: Run #47 succeeded in 14m 26s, deposited short_man_c85a0dd30bda.mp4.       |
|                                                                                                   |
| 2. autopilot.yml (CRON: 0 6,11,15 * * * - Daily 06:00, 11:00, 15:00 UTC)                         |
|    - Runner: ubuntu-latest (Python 3.11, lightweight dependencies)                                |
|    - Secrets: TOKEN_JSON, CLIENT_SECRET_JSON, PEXELS_API_KEY, GEMINI_API_KEY                      |
|    - Action: Reconciles live Shorts -> Audits 48h horizon -> Schedules eligible READY Shorts.     |
|                                                                                                   |
| 3. verify_database_sync.yml (WORKFLOW_DISPATCH - On-demand verification)                          |
|    - Verifies round-trip sync integrity: Download -> SHA256 check -> Upload -> Re-download.      |
|    - Confirms zero data loss across ephemeral runner lifecycles.                                  |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Secrets & Credential Management

All sensitive production secrets are securely injected from GitHub Repository Secrets into the runner environment at runtime:

| Secret Name | Purpose & Scope |
|---|---|
| `TOKEN_JSON` | Google OAuth2 user refresh & access token (YouTube + Google Drive scopes). |
| `CLIENT_SECRET_JSON` | Google Cloud project OAuth2 client credentials. |
| `GEMINI_API_KEY` | Google Gemini Flash & Pro primary reasoning and fact verification. |
| `GEMINI_API_KEY_SECONDARY` | Backup Google Gemini API key for quota failover. |
| `DEEPSEEK_API_KEY` | DeepSeek API key for AI Council story ideation and hook generation. |
| `NVIDIA_API_KEY` | NVIDIA NIM API key for Nemotron Council chair (factual grounding & visual feasibility). |
| `GROQ_API_KEY` | Groq high-speed Llama-3.3 inference for low-latency emergency fallbacks. |
| `OPENROUTER_API_KEY` | OpenRouter secondary multi-model gateway. |
| `PEXELS_API_KEY` | Pexels commercial stock media API key for supplementary visual sourcing. |