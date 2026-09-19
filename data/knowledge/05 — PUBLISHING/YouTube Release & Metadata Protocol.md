---
aliases:
  - YouTube Release Protocol
  - Metadata Protocol
  - YouTube Upload
  - Public Metadata Sanitization
tags:
  - publishing
  - youtube
  - metadata
  - localization
last_updated: 2026-09-18
---

# YouTube Release & Metadata Protocol

> **Status:** `[LIVE & VERIFIED]`  
> **Upload Mode:** Strictly **Scheduled Private Upload** with `publishAt` `[CODE VERIFIED]`  
> **Zero Immediate Public Releases:** Guarantees algorithm stability and review windows `[CODE VERIFIED]`  
> **Metadata Sanitization:** Strict Public/Internal Decoupling; zero internal job IDs, zero YouTube tags `[CODE VERIFIED — 2026-09-18]`

---

## 1. YouTube API Ingress (`upload_engine.py` & `seo_engine.py`)

Every video published to YouTube conforms to strict, decoupled public metadata guidelines (enforced September 18, 2026):

- **Title Structure:** Topic-specific, high-curiosity title ($<70$ characters) ending with impactful hook or question, avoiding generic AI templates.
- **Description Grounding & Localization:**
  - 2–4 natural, engaging sentences describing the actual event or topic.
  - Places the core entity/country/organization in the first 1–2 sentences for search indexing.
  - Appends 3–5 targeted entity/topic hashtags (e.g. `#Geopolitics`, `#WorldAffairs`, `#Shorts`).
  - **Zero Internal IDs:** Sanitized via `UploadEngine.sanitize_public_description()`. All internal run traces (`[JOB_ID: ...]`, `[RUN_ID: ...]`, raw UUIDs, step counts) are permanently stripped before API ingress.
- **YouTube Tags:** **Strictly Omitted.** In accordance with modern YouTube algorithm practices where tags provide negligible discovery value and internal tags clutter metadata, the `"tags"` key is completely omitted from the upload snippet body payload `[CODE VERIFIED]`.
- **Category ID:** `27` (Education) or `22` (People & Blogs).
- **Made for Kids:** Explicitly set to `False`.
- **Privacy Status:** Initial upload is set to `privacyStatus="private"` with `publishAt` populated to the exact scheduled ISO-8601 UTC slot timestamp `[CODE VERIFIED]`.

---

## 2. Token Management & Quota Safety

- Uses Google Cloud OAuth2 client credentials stored in GitHub Secrets (`TOKEN_JSON`, `CLIENT_SECRET_JSON`).
- Video uploads consume 1,600 YouTube API quota units.
- Metadata updates (`videos.update`) consume 50 quota units.
- With 3 uploads/day, daily consumption is 4,800 units, well within YouTube's standard 10,000 unit free tier ceiling `[CODE VERIFIED]`.

---

## 3. Metadata Non-Regression Invariants (Commit `503af7d`)

1. **No Tags in Snippet:** The YouTube Data API `videos.insert` and `videos.update` request bodies must never include a `"tags"` array.
2. **Zero Internal Traces in Description:** Viewer-facing descriptions must never contain `JOB_ID`, `RUN_ID`, `PIPELINE_RUN`, or orchestration UUIDs.
3. **Preserve `publishAt` on Updates:** Any metadata fix or patch applied to a scheduled video must explicitly re-include the existing `status.publishAt` timestamp and `status.privacyStatus = "private"` to prevent accidental immediate publication or unscheduling.
4. **Historical Remediation Complete:** On 2026-09-18, all 5 pending scheduled Shorts in production (`MG3dnL_ijts`, `HDx1dAw4Lpk`, `CgzjTCAgIUU`, `6FCb4NjsZhA`, `Q6qzh3xHego`) were sanitized live, successfully stripping tags and job IDs while preserving scheduled publication slots.