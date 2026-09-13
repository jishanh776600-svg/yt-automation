---
aliases:
  - QA Gates
  - VideoQAEngine
  - AudioQA
tags:
  - testing
  - qa
  - verification
last_updated: 2026-09-07
---

# Verification Suite & QA Gates

> **Status:** `[LIVE & VERIFIED]`  
> **Automated Gatekeeper:** `engines/qa_engine.py:VideoQAEngine` `[CODE VERIFIED]`  
> **Fail-Closed Standard:** A single failing metric aborts vault deposit and moves asset to `04_FAILED` `[CODE VERIFIED]`.

---

## 1. The 15 Automated VideoQA Checks

Every rendered MP4 must pass 15 programmatic tests prior to deposit into Google Drive `01_READY`:

| Test # | Check Description | Fail Condition | Enforcement Tool |
|---|---|---|---|
| 1 | **Container Integrity** | Non-zero byte, valid MP4 header | FFprobe |
| 2 | **Resolution** | Not exactly 1080x1920 (9:16) | FFprobe video stream |
| 3 | **Duration** | Runtime $<22.0\text{s}$ or $>25.0\text{s}$ | FFprobe container duration |
| 4 | **Frame Rate** | $<29.97$ or $>30.0$ fps | FFprobe stream analysis |
| 5 | **Pixel Format** | Not `yuv420p` | FFprobe stream |
| 6 | **Audio Codec** | Not AAC stereo | FFprobe audio stream |
| 7 | **Voice Consistency** | Acoustic deviation from Bella voice profile | Waveform spectral comparator |
| 8 | **Max Pause Gap** | Any silence pause $>0.35\text{s}$ (350ms) | RMS waveform scanner |
| 9 | **Dead Air Ratio** | Cumulative dead air $>18.0\%$ of runtime | RMS silence integrator |
| 10 | **Integrated Loudness** | Outside $[-22.0, -10.0]$ LUFS (Target: $-14$ LUFS) | FFmpeg `ebur128` filter |
| 11 | **True Peak** | Peak $> 0.0$ dBTP (clipping detected) | FFmpeg `ebur128` filter |
| 12 | **Black Frame Detection**| $>0.5\text{s}$ consecutive black frames | FFmpeg `blackdetect` filter |
| 13 | **Scene Count** | Fewer than 9 unique evidence scenes | Manifest frame auditor |
| 14 | **Visual Deduplication**| Intra-Short duplicate scene or cooldown violation | `GlobalVisualMemory` dHash check |
| 15 | **AV Sync** | Audio and video stream duration delta $>0.10\text{s}$ | MediaInfo stream delta |

---

## 2. Pre-READY Content Quality Gate & Negative Invariants

### Pre-READY Content Quality Gate (`core/content_quality_gate.py`)
Executes prior to Drive deposit:
- Validates semantic alignment between visual evidence era and historical narration.
- Rejects modern vehicles/technology for pre-modern historical stories.
- Enforces seamless audio loop and ending engagement strategy (`engines/ending_strategy.py`).
- Verifies total duration within bounds [22.0, 27.0]s.

### Lifecycle Negative Invariants Suite (`tests/test_lifecycle_negative_invariants.py`)
Adversarially tests 40 distinct lifecycle failure modes:
- **Result:** **40/40 PASSED** `[CODE VERIFIED]`
- Verifies that:
  - No asset can reach `03_PUBLISHED` without passing through `core.lifecycle_gateway`.
  - YouTube read-back verification fails closed if privacyStatus is not `public`.
  - Stale daemons with mismatched PIDs cannot mutate production state.
  - Candidate deduplication excludes candidate self-matching.
  - Recovery of unuploaded assets is idempotent.