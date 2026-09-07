---
aliases:
  - Publication Safety Gate
  - Safety Gate
tags:
  - publishing
  - safety
  - qa
last_updated: 2026-09-07
---

# Publication Safety Gate

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** 15-point pre-upload safety inspection guarding against accidental, malformed, or duplicate releases `[CODE VERIFIED]`.

---

## 1. The 15 Pre-Upload Verification Gates

Before any Short is claimed from `01_READY` for YouTube scheduling, `upload_engine.py` executes 15 mandatory verification checks:

1. **Vault Origin Gate:** File must physically exist in `YouTube_Shorts_Vault/01_READY/`.
2. **File Size Gate:** File must be between 8 MB and 95 MB.
3. **Format Gate:** Valid MP4 container with H.264 video and AAC audio.
4. **Resolution Gate:** Dimensions must be exactly 1080x1920 (9:16 vertical).
5. **Duration Gate:** Video duration must be within $[22.0, 25.0]\text{s}$.
6. **Voice Gate:** Narration must be verified as `af_bella` (Bella Kokoro-82M).
7. **Pause Gate:** Maximum acoustic pause $< 0.35\text{s}$.
8. **Dead Air Gate:** Cumulative dead air ratio $\le 18.0\%$.
9. **Audio Loudness Gate:** Integrated LUFS between $[-22.0, -10.0]$ LUFS.
10. **Visual Diversity Gate:** Minimum 9 distinct physical evidence scenes.
11. **Deduplication Gate:** Topic title and script shingle check vs `UploadRecord`.
12. **Niche Compliance Gate:** Zero political or military keywords.
13. **Daily Ceiling Gate:** Target calendar day must have $<3$ scheduled uploads.
14. **Slot Validity Gate:** Scheduled timestamp must be $\ge 45$ minutes in future.
15. **Database Transaction Gate:** DB record must be in `READY_TO_UPLOAD` status.

Failure of ANY gate immediately aborts the upload, quarantines the file to `04_FAILED`, and logs the forensic failure code `[CODE VERIFIED]`.