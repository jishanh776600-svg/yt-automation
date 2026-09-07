---
aliases:
  - Production Pipeline
  - Pipeline Specification
  - Sequential Production
tags:
  - production
  - pipeline
  - architecture
last_updated: 2026-09-07
---

# 04 — Production Pipeline Specification

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** End-to-end 15-stage sequential pipeline from topic selection to Google Drive vault deposit `[CODE VERIFIED]`.

---

## 1. The 15-Stage Sequential Pipeline

AL-AMR produces videos strictly **ONE AT A TIME**. Short $N+1$ never begins until Short $N$ has completely passed VideoQA and deposited into Google Drive `01_READY` `[CODE VERIFIED]`.

```mermaid
flowchart TD
    S1["1. Topic Selection<br/>(CURATED_HISTORICAL_SEEDS or Dynamic Fallback)"] --> S2["2. Historical Fact Verification<br/>(Gemini Grounding & Eras)"]
    S2 --> S3["3. AI Council Deliberation<br/>(DeepSeek + Kimi + Nemotron)"]
    S3 --> S4["4. Council Quality Gate<br/>(58-72 words, 0 clichés, hook in 1-2s)"]
    S4 --> S5["5. Visual Storyboarding<br/>(>=9 unique evidence scenes)"]
    S5 --> S6["6. Visual Asset Acquisition<br/>(Archival Scans, Photos, Public Domain)"]
    S6 --> S7["7. Visual Deduplication Gate<br/>(dHash vs visual_memory.db)"]
    S7 --> S8["8. Bella TTS Narration<br/>(Kokoro-82M af_bella at 1.00x native)"]
    S8 --> S9["9. Silence Compression & Calibration<br/>(Max 100ms pause, 22.0-25.0s target)"]
    S9 --> S10["10. ASS Subtitle Generation<br/>(Word-level timestamps, highlight colors)"]
    S10 --> S11["11. BGM Bed Synthesis<br/>(4 approved tracks ducked to -30.0 LUFS)"]
    S11 --> S12["12. Headless FFmpeg Composition<br/>(1080x1920 9:16 vertical render)"]
    S12 --> S13["13. 15-Point VideoQA Audit<br/>(Pause <0.35s, Dead air <=18%, 0 black frames)"]
    S13 --> S14["14. Google Drive Vault Deposit<br/>(Upload to YouTube_Shorts_Vault/01_READY)"]
    S14 --> S15["15. Canonical State Commit<br/>(Update youtube_automation.db in 00_SYSTEM)"]
```

---

## 2. Technical Production Specifications

- **Narration Voice:** `af_bella` (Bella Kokoro-82M ONNX at native 1.00x) `[LIVE VERIFIED]`.
- **Target Word Count:** 58 to 72 words (Canonical sweet spot: $\sim 65$ words) `[CODE VERIFIED]`.
- **Video Duration:** 22.0s to 25.0s (Target: $\sim 23.0$ seconds) `[CODE VERIFIED]`.
- **Resolution & Aspect:** 1080x1920 (9:16 vertical video) `[CODE VERIFIED]`.
- **Frame Rate:** 30.0 fps progressive `[CODE VERIFIED]`.
- **Visual Evidence Ratio:** Minimum 9 unique physical evidence scenes (0 script-card frames) `[CODE VERIFIED]`.
- **Audio Mix:** Voiceover at -14.0 LUFS; BGM ducked to -30.0 LUFS; SFX permanently disabled `[CODE VERIFIED]`.