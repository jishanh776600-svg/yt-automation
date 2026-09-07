---
aliases:
  - Database Sync
  - State Persistence
tags:
  - architecture
  - database
  - persistence
last_updated: 2026-09-07
---

# Multi-Tier Database Persistence & Synchronization

> **Status:** `[LIVE & VERIFIED]`  
> **Scope:** SQLite transaction management, Google Drive `00_SYSTEM` sync, and SHA256 integrity verification `[CODE VERIFIED]`.

---

## 1. Database Architecture & Roles

AL-AMR maintains three dedicated SQLite databases:

| Database File | Role & Contents | Concurrency Mode |
|---|---|---|
| `youtube_automation.db` | Primary pipeline state: Jobs, Scripts, Videos, Uploads, Schedules, SystemConfig | `journal_mode = WAL` `[CODE VERIFIED]` |
| `visual_memory.db` | Global visual memory: Perceptual dHash values, SHA256 hashes, usage timestamps | `journal_mode = WAL` `[CODE VERIFIED]` |
| `short_fingerprints.db` | Content deduplication: 3-gram script shingles, semantic story embeddings | `journal_mode = WAL` `[CODE VERIFIED]` |

---

## 2. Cloud Synchronization Protocol (`database_sync.py`)

Because GitHub Actions runners are ephemeral, database persistence is achieved via bidirectional synchronization with Google Drive `YouTube_Shorts_Vault/00_SYSTEM/`:

1. **Pre-Execution Ingress:**
   - Runner queries `00_SYSTEM` for `youtube_automation.db`.
   - Downloads file to local workspace and computes local SHA256.
   - Verifies SQLite integrity using `PRAGMA integrity_check;` `[CODE VERIFIED]`.

2. **Post-Execution Egress:**
   - Commits all open SQLite transactions and executes `PRAGMA wal_checkpoint(TRUNCATE);`.
   - Uploads updated database files to `00_SYSTEM` using Google Drive multipart upload.
   - Re-queries Drive file metadata to confirm byte-size and SHA256 match `[CODE VERIFIED]`.