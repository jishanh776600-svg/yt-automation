---
aliases:
  - YouTube Release Protocol
  - Metadata Protocol
  - YouTube Upload
tags:
  - publishing
  - youtube
  - metadata
last_updated: 2026-09-07
---

# YouTube Release & Metadata Protocol

> **Status:** `[LIVE & VERIFIED]`  
> **Upload Mode:** Strictly **Scheduled Private Upload** with `publishAt` `[CODE VERIFIED]`  
> **Zero Immediate Public Releases:** Guarantees algorithm stability and review windows `[CODE VERIFIED]`  

---

## 1. YouTube API Ingress (`upload_engine.py`)

Every video published to YouTube conforms to strict metadata guidelines:
- **Title Structure:** High-curiosity historical mystery title ($<60$ characters) ending with impactful question or hook.
- **Description:** Structured 3-paragraph summary + historical citation / archival source + 3 targeted hashtags (`#shorts`, `#history`, `#mystery`).
- **Category ID:** `27` (Education) or `22` (People & Blogs).
- **Made for Kids:** Explicitly set to `False`.
- **Privacy Status:** Initial upload is set to `privacyStatus="private"` with `publishAt` populated to the exact scheduled ISO-8601 UTC slot timestamp `[CODE VERIFIED]`.

---

## 2. Token Management & Quota Safety

- Uses Google Cloud OAuth2 client credentials stored in GitHub Secrets (`TOKEN_JSON`, `CLIENT_SECRET_JSON`).
- Video uploads consume 1,600 YouTube API quota units.
- With 3 uploads/day, daily consumption is 4,800 units, well within YouTube's standard 10,000 unit free tier ceiling `[CODE VERIFIED]`.