---
aliases:
  - Duplicate Protection
  - Content Fingerprinting
  - Global Visual Memory
tags:
  - production
  - deduplication
  - safety
last_updated: 2026-09-07
---

# Duplicate Protection & Fingerprinting

> **Status:** `[LIVE & VERIFIED]`  
> **Story Protection:** `ShortDuplicateGuard` (3-gram script shingles & semantic similarity) `[CODE VERIFIED]`  
> **Visual Protection:** `GlobalVisualMemory` (perceptual dHash + 45-day cooldown) `[CODE VERIFIED]`  

---

## 1. Multi-Tier Deduplication Architecture

To ensure the channel never produces repetitive content, AL-AMR enforces three distinct layers of deduplication:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      AL-AMR DEDUPLICATION DEFENSE                           │
├──────────────────────┬──────────────────────────────────────────────────────┤
│ 1. Topic History     │ Checks SQLite Topic and UploadRecord tables.         │
│                      │ Excludes in-flight, scheduled, and published topics. │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ 2. Script Shingles   │ ShortDuplicateGuard: Computes 3-gram word shingles.  │
│                      │ Jaccard similarity > 0.35 triggers immediate reject.  │
├──────────────────────┼──────────────────────────────────────────────────────┤
│ 3. Perceptual dHash  │ GlobalVisualMemory: Computes difference hashes of    │
│                      │ visual frames. Hamming distance <= 10 rejected.      │
└──────────────────────┴──────────────────────────────────────────────────────┘
```

---

## 2. Global Visual Memory (`visual_memory.db`)

Implemented in `core/visual_memory.py`:
- Tracks every visual asset utilized across the lifetime of the channel.
- Imposes a **45-day cooldown period** on any reused image or video frame.
- Zero intra-Short duplicates: An asset cannot appear twice in the same Short `[CODE VERIFIED]`.