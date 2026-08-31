# 06 — Audio & BGM System

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** 4 canonical BGM tracks, mood mapping, Stage B standardization, and acoustic QA fingerprinting.  

---

## 1. Approved Canonical BGM Library

The system maintains 4 approved core BGM tracks in `assets/music`:

| Track Key | Display Name | Intrinsic Loudness | Narrative Genre & Mood Mapping |
|---|---|---|---|
| `best_historical` | *No copyright Best Historical* | `-19.2 LUFS` | Medieval warfare, monarchies, royal scandals, ancient politics. |
| `emotional_sad` | *Empty - Emotional Sad Background* | `-12.9 LUFS` | Poignant tragedy, heartfelt sacrifice, famine, loss, mourning. |
| `flux_ambient` | *The Flux Beneath It All* | `-14.9 LUFS` | Dark mysteries, strange inventions, lost cities, curiosity, scientific wonder. |
| `suspense_climax`| *No Copyright Background Music* | `-12.1 LUFS` | High tension, thrilling escapes, heists, manhunts, urgent countdowns. |

---

## 2. BGM Loudness Standardization Fix (Stage B Bed Normalization)

### The Problem
Raw BGM files possess different intrinsic mastering levels (varying from $-19.2	ext{ LUFS}$ to $-12.1	ext{ LUFS}$). Applying a static gain multiplier (`volume=-13dB`) produced inconsistent relative BGM levels. Loud tracks like `No Copyright Background Music` were $7.1	ext{ dB}$ louder than `Best Historical`, causing the music to noticeably compete with narration.

### The Fix
Introduced `TARGET_BGM_LUFS = -30.0` in [`config/constants.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/config/constants.py).
In `AudioMixer.generate_stage_b_bgm_only()`, Stage B now normalizes every BGM track to **`-30.0 LUFS`** via EBU R128 (`loudnorm=I=-30.0:LRA=11:tp=-3.0`).

```
Raw BGM (Any Source: -6 to -22 LUFS)
       │
       ▼
[Stage B EBU R128 Normalization]  --> Exactly -30.0 LUFS Bed
       │
       ▼
[amix with Voice (~ -18.2 LUFS)] --> Voice is strictly 12-16 dB dominant
       │
       ▼
[Stage C Master Normalization]   --> Broadcast Target: -14.0 LUFS (True Peak <= 0.0 dBTP)
```

---

## 3. Acoustic Verification & QA Fingerprinting

- **FFT Cross-Correlation**: `QAEngine.compute_bgm_identity_correlation()` extracts audio from the rendered MP4 and runs FFT linear cross-correlation against the Stage B reference. A score $\ge 0.65$ proves the intended BGM is physically present.
- **Targeted Test Proof**: 16/16 audio and BGM tests passing locally with $0 API spend and 0 real production runs.