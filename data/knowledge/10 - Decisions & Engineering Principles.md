# 10 — Decisions & Engineering Principles

> **Status:** `[CORE GOVERNANCE]`  
> **Scope:** Fundamental engineering rules, architectural invariants, and operational principles.  

---

## 1. Core Engineering Principles

1. **Fix Root Causes, Not Symptoms**:
   Never patch a symptom with retry loops or superficial workarounds. Identify the exact architectural failure mechanism and resolve it permanently.

2. **No "Success After Retries" Policy**:
   The objective of engineering fixes is never "eventually succeeds after repeated runs." The standard is: **Diagnose $	o$ Inspect $	o$ Implement $	o$ Targeted Test $	o$ Minimal Regression $	o$ Exactly ONE Justified Real-World Validation**.

3. **Zero AI/API Consumption for Code Debugging**:
   Never consume paid AI inference credits (Gemini, Groq, OpenRouter) or production tokens to test local formatting, lock handling, audio filters, or database schemas. Use deterministic local fixtures and mocks.

4. **Real Cloud Runs Are Validation, Not Debugging**:
   Production workflows (`produce_buffer.yml`, `autopilot.yml`) are executed only after 100% of local unit, regression, and simulation tests pass.

5. **Truthful Unavailable States (Data Purity)**:
   Missing metrics must remain `None` and display as `"UNAVAILABLE"`. Zero is never substituted for missing views, AVD, or APV.

6. **Every Failure Becomes a Regression Test**:
   Any bug discovered in production or testing must have a corresponding automated regression test added to prevent recurrence.

7. **Human Verification on External Account Boundaries**:
   OAuth scopes, billing settings, Google Cloud API enablement, and channel-level permissions require human review and consent.

8. **Never Mutate Persistent State Inside Filtering Loops**:
   Topic status, job state, or any persistent DB field must never be written as a side-effect of a candidate-selection scan. Use in-memory exclusion sets (`excluded_ids: Set[str]`) to track what has been processed within a run. Persistent status transitions (e.g. `COMPLETED`, `REJECTED`) require explicit, separately-tested code paths that can be reasoned about in isolation.

9. **Self-Reference Guard in Corpus Deduplication**:
   When checking if a candidate is a duplicate against a corpus built from the same database, the candidate's own ID (`exclude_topic_id`) must always be passed to prevent self-matching. A topic that has historical jobs attached (even in `QUEUED`/`NEEDS_REVIEW` state) will appear in the corpus and match itself if this guard is absent.