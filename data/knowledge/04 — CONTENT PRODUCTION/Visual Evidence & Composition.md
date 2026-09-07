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
- **Zero Script-Cards:** Text-on-screen summary cards (which cause immediate viewer swiping) are prohibited. All text is delivered via styled ASS subtitles over authentic imagery `[CODE VERIFIED]`.

---

## 2. Headless FFmpeg Composition Engine

Implemented in `engines/video_engine.py`:
- **Canvas:** 1080x1920 (9:16 vertical orientation).
- **Dynamic Motion (Ken Burns):** Gentle, slow pan and zoom across archival imagery (zoom factor 1.05x–1.15x) to maintain visual momentum without causing motion sickness `[CODE VERIFIED]`.
- **Scene Transition Pacing:** Each scene lasts between 1.8s and 2.5s, precisely timed to match script beat transitions `[CODE VERIFIED]`.
- **Subtitle Styling:** Advanced SubStation Alpha (ASS) karaoke rendering with highlighted active spoken words and high-contrast dark drop shadows `[CODE VERIFIED]`.