# System Invariants & Durable Architecture

## Storage Architecture
- **SQLite**: Ephemeral operational state and relational metadata.
- **Google Drive**: Authoritative physical file storage and vault backup.
- **Obsidian Brain (`data/knowledge/`)**: Human-readable knowledge repository and graph.

## Invariants
- `TARGET_RESERVE_BUFFER = 6`
- `DAILY_SHORTS_LIMIT = 3`
- `CANONICAL_VOICE = "af_bella"`
- `PUBLISHING_SLOTS = 06:00, 11:00, 15:00 UTC`