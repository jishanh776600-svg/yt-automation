---
aliases:
  - Visual Evidence
  - Visual Composition
  - Evidence Sourcing
tags:
  - production
  - visuals
  - ffmpeg
last_updated: 2026-09-07
---

# Visual Evidence & Composition

> **Status:** `[LIVE & VERIFIED]`  
> **Standard:** Authentic historical evidence throughout; **Zero Script-Card Frames** `[CODE VERIFIED]`.  
> **Density:** Minimum **9 unique evidence scenes** (Target 10–12 beats) `[CODE VERIFIED]`.  

---

## 1. Authentic Visual Sourcing

Every AL-AMR video must ground its narration in authentic physical reality. Stock footage of random modern people or generic digital abstractions is strictly prohibited:

- **Primary Sources:** High-resolution scans of archival manuscripts, historical photographs, museum artifacts, archaeological excavation photos, authentic expedition maps, and public-domain film reels `[CODE VERIFIED]`.
- **Script-Aware Visual Intelligence (`engines/visual_intelligence/`):** Analyzes script entity, setting, and temporal intent to formulate precise search queries rather than generic stock lookups `[CODE VERIFIED]`.
- **Era & Context Consistency Gate:** Programmatically cross-validates asset era tags against the script's chronological setting. Rejects modern footage/cars for 18th/19th century events, and rejects antique engravings for 20th-century events `[CODE VERIFIED]`.
- **Zero Script-Cards:** Text-on-screen summary cards (which cause immediate viewer swiping) are prohibited. All text is delivered via styled ASS subtitles over authentic imagery `[CODE VERIFIED]`.

---

## 2. Headless FFmpeg Composition Engine & Storyboard Pacing

Implemented in `engines/video_engine.py` and `engines/storyboard_engine.py`:
- **Canvas:** 1080x1920 (9:16 vertical orientation).
- **Dynamic Storyboard Pacing:** Scene durations scale dynamically between 1.8s and 2.5s according to narrative tension (opening hook, build-up, reveal, loop conclusion) `[CODE VERIFIED]`.
- **Dynamic Motion (Ken Burns):** Gentle, slow pan and zoom across archival imagery (zoom factor 1.05x–1.15x) to maintain visual momentum without causing motion sickness `[CODE VERIFIED]`.
- **Subtitle Styling:** Advanced SubStation Alpha (ASS) karaoke rendering with highlighted active spoken words and high-contrast dark drop shadows `[CODE VERIFIED]`.

---

## 3. Pre-READY Content Quality Gate

Implemented in [`core/content_quality_gate.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/core/content_quality_gate.py):
- Before an assembled Short can be deposited into `01_READY`, the Pre-READY gate verifies:
  1. Semantic match between script beats and visual metadata.
  2. Visual uniqueness (minimum 9 distinct evidence scenes).
  3. Total video duration within [22.0s, 27.0s].
  4. Audio presence and absence of black frames.
- Any discrepancy immediately halts deposit and prevents unverified assets from entering the production reserve `[CODE VERIFIED]`.