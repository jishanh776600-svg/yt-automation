# 12 — Change Log

> **Status:** `[CHRONOLOGICAL ENGINEERING LOG]`  
> **Scope:** Milestone history from initial autonomy through latest hardening.  

---

| Date / Milestone | Commit SHA | Primary Goal | Implementation | Test Status | Real Validation Outcome |
|---|---|---|---|---|---|
| **Step 6** | `38ebd67` | Cloud Autonomy | Autonomous GitHub Actions workflow execution | 72 Passing | Verified initial cloud runner execution |
| **Step 8** | `6739915` | YouTube Scope Audit | YouTube API scope audit and reserve stability | 90 Passing | Validated scope isolation |
| **Step 9** | `3a27faf` | Visual Engine 2.0 | Multi-cut 7-10 visual beat architecture | 96 Passing | Verified visual pacing |
| **Step 10** | `901c9b1` | Visual Diversity | Asset quality and historical relevance proof | 103 Passing | Verified asset manifest logging |
| **Step 11** | `847f36e` | Historical Authenticity | Anachronism defense and temporal verification | 109 Passing | Verified fact filtering |
| **Step 12** | `dc4c34b` | Archival Ingestion | Wikimedia Commons ingestion with SHA-256 provenance | 113 Passing | Verified archival asset retrieval |
| **Step 13** | `adaf6a4` | Empirical Stress Test | Multi-Short continuous production stress test | 120 Passing | Verified pipeline stability |
| **Step 14** | `b7f12f4` | Operational Readiness | Reserve observation invariants and lock handling | 125 Passing | Verified operational readiness |
| **Step 15** | `1c1fe69` | Provider Economics | Multi-provider fallback and capacity engineering | 130 Passing | Verified provider failover cascade |
| **Step 16** | `081f235` | Token Economics | Billing-accurate token calculation ($0.000495/Short) | 135 Passing | Verified token measurement |
| **Step 17** | `66fe531` | Reserve Self-Maintenance| Multi-cycle reserve replenishment proof | 140 Passing | Verified deficit replenishment |
| **Step 18** | `8848723` | Analytics OAuth | AVD/APV telemetry parsing and OAuth audit | 145 Passing | Verified telemetry extraction |
| **Step 18b** | `d499dfc` | OAuth Distinction | Public metrics harvesting vs private analytics safety | 149 Passing | Verified boundary safety |
| **Step 19** | `c069208` | Analytics Consent | Interactive OAuth consent flow for yt-analytics scope | 153 Passing | Added yt-analytics.readonly to token.json |
| **Step 20** | `accbc91` | Service Enablement | Verification of GCP Analytics service status | 157 Passing | Diagnosed disabled GCP API blocker |
| **Step 21** | `42d47ed` | Boundary Checks | Analytics enablement boundary verification | 160 Passing | Prepared GCP enablement guidance |
| **Step 24** | `63135d1` | Telemetry Attribution | Video-level analytics attribution and UCB1 learning | 165 Passing | Live query AVD 17.0s, APV 75.46% verified |
| **Step 25** | `464fb45` | Self-Healing Producer | Prompt hardening and run-level topic quarantine | 172 Passing | Verified recovery from topic failure |
| **Step 26** | `feabff8` | Failure Injection | Adversarial injection of failed candidates | 179 Passing | Verified topic advancement to replacement |
| **Step 27** | `1fe26b7` | Root-Cause Audit | Reserve contract hardening & lock encapsulation | 188 Passing | Cloud Run 33419597117 deposited 3 Shorts to 6/6 |
| **BGM Fix** | `80de94b` | BGM Loudness | EBU R128 Stage B bed normalization (-30.0 LUFS) | 16 Audio Passing | Zero API spend, verified voice dominance |
| **HTTP 500 Fix** | `80b1f65` | Production HTTP 500 | Replaced `dateutil.parser.isoparse` with stdlib `_parse_yt_iso()` in `dashboard/data_provider.py` and `engines/scheduler_engine.py` | Local 200 OK verified | `https://al-amr.onrender.com` restored to HTTP 200 |
| **Bella + Dedup Fix** | `2f1098e` | Voice Default + Duplicate Prevention | Anchored `af_bella` at all 4 code layers; strengthened dedup across topic discovery, Drive pre-claim, Gate 15, intra-batch | 8/8 targeted tests pass | All tests PASS locally; DB `active_voice` set to `af_bella` |
| **Refill Hotfix** | `f554d99` | Broken Stock Refill | Restored `exclude_topic_id=t.id` in `discover_topics`; removed destructive `t.status="COMPLETED"` mutation; repaired 48 falsely-blocked topics in DB | Compile + DB count verified | DB: APPROVED 16, DISCOVERED 427; `produce_buffer.yml` unblocked |
| **Step 34** | pending | Script Generation Quota Conservation | 1-call multi-topic script batching with exact count, word target (45-68), critic evaluation, and selective per-topic recovery; Groq model fixed to `llama-3.1-8b-instant` | 8/8 targeted tests pass | Batch script cache + failover isolation verified |
| **Step 35** | pending | DeepSeek V4 Pro Fallback Integration | Appended DeepSeek V4 Pro as final fallback after OpenRouter in `core/gemini_client.py`; configured `DEEPSEEK_MODEL = "deepseek-v4-pro"` and `DEEPSEEK_API_KEY` secret reading; batch-generation compatibility verified | 5/5 targeted tests pass | New order: Primary -> Secondary -> Groq -> OpenRouter -> DeepSeek V4 Pro |