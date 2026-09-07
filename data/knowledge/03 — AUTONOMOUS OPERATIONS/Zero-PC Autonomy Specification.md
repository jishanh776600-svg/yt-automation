---
aliases:
  - Zero-PC Autonomy
  - Cloud Autonomy
tags:
  - operations
  - autonomy
last_updated: 2026-09-07
---

# Zero-PC Autonomy Specification

> **Status:** `[LIVE & VERIFIED — 100% UNATTENDED]`  
> **Specification:** Complete operational independence from developer hardware, local networks, or desktop software `[LIVE VERIFIED]`.

---

## 1. Zero-PC Autonomy Audit Matrix

| System Component | Execution Location | Local PC Dependency | Verification |
|---|---|---|---|
| **Topic Discovery** | GitHub Actions Runner | **0%** (Runs headless Python in cloud) | `[LIVE VERIFIED]` |
| **Script Deliberation** | GitHub Actions Runner | **0%** (Calls cloud AI APIs via runner secrets) | `[LIVE VERIFIED]` |
| **TTS Narration (Bella)** | GitHub Actions Runner | **0%** (Kokoro-82M ONNX runs on cloud runner CPU) | `[LIVE VERIFIED]` |
| **Visual Evidence Retrieval** | GitHub Actions Runner | **0%** (Pexels / Wikimedia / Archival web APIs) | `[LIVE VERIFIED]` |
| **Video Composition (FFmpeg)** | GitHub Actions Runner | **0%** (FFmpeg runs headless on `ubuntu-latest`) | `[LIVE VERIFIED]` |
| **Video & Audio QA** | GitHub Actions Runner | **0%** (Waveform & frame inspection in cloud) | `[LIVE VERIFIED]` |
| **State Storage & Locking** | Google Drive API | **0%** (Durable cloud storage `00_SYSTEM`) | `[LIVE VERIFIED]` |
| **YouTube Publishing** | GitHub Actions Runner | **0%** (YouTube Data API v3 via runner secrets) | `[LIVE VERIFIED]` |
| **Telemetry Harvesting** | GitHub Actions Runner | **0%** (YouTube Analytics API in cloud) | `[LIVE VERIFIED]` |
| **Render Web Dashboard** | Render Cloud Container | **0%** (Hosted on Render 24/7 web service) | `[LIVE VERIFIED]` |

---

## 2. The Local Machine Role

The developer's local PC functions purely as:
1. **Source Code Repository Clone:** For Git version control and code edits.
2. **Obsidian Vault Viewer:** For browsing Markdown documentation in Obsidian.
3. **Emergency Administrative Console:** For optional manual CLI maintenance (`--health-check`, `--force-unlock`).

Production execution does not require the developer's laptop to be open, powered on, or connected to the internet `[LIVE VERIFIED]`.