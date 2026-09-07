---
aliases:
  - Test Suites
  - AST Compliance
  - CI Testing
tags:
  - testing
  - pytest
  - ast
last_updated: 2026-09-07
---

# Targeted Test Suites & AST Compliance

> **Status:** `[LIVE & PASSING — 100+ TESTS]`  
> **CI Suite:** Comprehensive unit and integration coverage across all core engines `[CODE VERIFIED]`.

---

## 1. Test Suite Architecture

| Test Module | Coverage & Focus | Invariants Verified |
|---|---|---|
| `tests/test_cloud_lock.py` | Cloud distributed locking | TTL expiration, heartbeat refresh, dead-runner reclamation, `--force-unlock` |
| `tests/test_tts_engine.py` | Kokoro Bella synthesis | `af_bella` default, pause calibration, silence compression ($<100\text{ms}$) |
| `tests/test_qa_engine.py` | Video and Audio QA gates | Duration boundaries, pause detection, loudness compliance, black frame abort |
| `tests/test_story_dedup.py` | Topic & script deduplication | 3-gram word shingles, title similarity, intra-batch protection |
| `tests/test_niche_compliance.py` | Fail-closed niche filtering | Banned political/war tokens rejected, historical topics approved |

---

## 2. Python AST Static Architecture Compliance

To prevent architectural regression, tests run Abstract Syntax Tree (AST) static analysis over core code:
- **No Hardcoded Niche Branches:** Verified that `engines/orchestrator.py` contains zero occurrences of `if niche == ...` or domain-specific hardcoded branching `[CODE VERIFIED]`.
- **No Stale Voice Defaults:** Verified that `engines/tts_engine.py` contains zero fallback defaults to `am_adam` or `af_sarah` `[CODE VERIFIED]`.