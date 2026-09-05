---
aliases:
  - Short Duplicate Guard
  - Duplicate Protection
tags:
  - deduplication
  - safety
  - integrity
last_updated: 2026-09-05
---

# 08 — Short Duplicate Guard & Fingerprinting

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** Multi-layer story deduplication, title/script shingle hashing, intra-batch protection, and 90-day topic cooldowns.

---

## 1. Multi-Layer Deduplication Defense

Releasing duplicate or near-duplicate content destroys channel credibility and triggers YouTube anti-spam algorithmic penalties. AL-AMR enforces 4 independent layers of duplicate defense:

```
                  ┌─────────────────────────────────────────┐
                  │          CANDIDATE STORY DRAFT          │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ LAYER 1: SEMANTIC TOPIC DEDUPLICATION (clustering.py)                     │
│ Checks FastEmbed text embeddings against all topics produced in 90 days.  │
│ Threshold: Cosine similarity >= 0.72 -> REJECTED                          │
└──────────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ LAYER 2: INTRA-BATCH DEDUPLICATION (main.py)                             │
│ Filters multi-item batches to prevent two candidate stories covering the │
│ same underlying historical or scientific event in the same run.          │
└──────────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ LAYER 3: SHORT DUPLICATE GUARD (short_duplicate_guard.py)                 │
│ Computes 3-gram word shingles on title & full script text.                │
│ Stores fingerprint hash in short_fingerprints.db.                        │
│ Threshold: Jaccard similarity >= 0.60 -> REJECTED                         │
└──────────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ LAYER 4: PRE-CLAIM VAULT & YOUTUBE RECONCILIATION (scheduler_engine.py)   │
│ Inspects 01_READY and 02_PROCESSING against existing YouTube video IDs.   │
│ If already uploaded or scheduled -> Moves directly to 03_PUBLISHED.      │
└──────────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                           [APPROVED FOR PRODUCTION]
```

---

## 2. `ShortDuplicateGuard` Architecture

Implemented in [`intelligence/short_duplicate_guard.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/intelligence/short_duplicate_guard.py):

### Persistent Fingerprint Database (`short_fingerprints.db`)
Stored in Google Drive `00_SYSTEM/short_fingerprints.db` and synchronized to the runner disk on every execution:
- `short_id`: Manifest or job ID.
- `topic_title`: Normalized story title.
- `script_text`: Complete narration transcript.
- `duration_seconds`: Verified video duration.
- `asset_ids_json`: JSON list of all visual assets utilized.
- `fingerprint_hash`: Composite SHA-256 hash of normalized text shingles and visual IDs.

### Fail-Closed Enforcement
The duplicate guard executes **prior to voice synthesis** and **prior to vault deposit**. If the guard fails or cannot access its fingerprint database, production fails closed and halts execution safely rather than risking duplicate releases.

---

## 3. Architectural Links
- Master Overview: [[00 - Master Dashboard|AL-AMR Dashboard]]
- Content Boundaries: [[02 - Content Strategy|Content Strategy]]
- Visual Deduplication: [[07 - Visual System|Visual System]]
- Production Pipeline: [[09 - Production Pipeline|Production Pipeline]]