---
aliases:
  - Audio Mastering
  - BGM Standards
  - Acoustic Standards
tags:
  - production
  - audio
  - bgm
last_updated: 2026-09-07
---

# Audio Mastering & BGM Standards

> **Status:** `[LIVE & VERIFIED]`  
> **Background Music (BGM):** **`ENABLED`** (Normalized to -30.0 LUFS Stage B bed) `[CODE VERIFIED]`  
> **Sound Effects (SFX):** **`PERMANENTLY DISABLED`** (Zero whooshes, memes, or synthetic SFX) `[CODE VERIFIED]`  
> **Voice Dominance:** Voiceover sits at **`-14.0 LUFS`** (Voice is strictly 12–16 dB dominant over BGM) `[CODE VERIFIED]`  

---

## 1. Permanent SFX Retirement

By editorial mandate, Sound Effects (SFX) are permanently disabled across all AL-AMR production pipelines:
- **Reasoning:** In historical mystery storytelling, cartoonish whooshes, chime effects, and meme sound effects destroy credibility and cause audience drop-off.
- **Enforcement:** Hardcoded pipeline flag `has_sfx = False` in `engines/video_engine.py` and `engines/audio_mixer.py`. Existing SFX files in `data/assets/sfx/` remain archived but are never mixed into production videos `[CODE VERIFIED]`.

---

## 2. EBU R128 Stage B Bed Normalization

Implemented in `engines/audio_mixer.py:generate_stage_b_bgm_only()`:
- **Raw BGM Problem:** Raw library tracks varied wildly from -19.2 LUFS to -12.1 LUFS, causing inconsistent loudness.
- **Stage B Solution:** Every BGM track is pre-mastered to **`-30.0 LUFS`** integrated loudness via FFmpeg `loudnorm`.
- **Master Audio Mix:**
  - Narration (Bella): Normalized to **`-14.0 LUFS`** ($\pm 1.0\text{ LUFS}$).
  - BGM Bed: Normalized to **`-30.0 LUFS`**.
  - Final Ducked Mix: Guarantees narration is effortlessly intelligible with zero acoustic masking `[CODE VERIFIED]`.
- **Approved BGM Library:**
  1. `best_historical` — Contemplative, historical strings.
  2. `emotional_sad` — Melancholic, mystery undertones.
  3. `flux_ambient` — Minimalist atmospheric tension.
  4. `suspense_climax` — Escalating dramatic revelation.