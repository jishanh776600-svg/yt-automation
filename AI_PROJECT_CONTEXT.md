# 📘 AI Handoff & Project Context: AL-AMR Autonomous Geopolitical YouTube Shorts Pipeline

> **Document Version**: 3.0  
> **Last Updated**: 2026-09-05  
> **Repository**: `https://github.com/jishanh776600-svg/yt-automation.git`  
> **Branch**: `main`  
> **Purpose**: Durable, comprehensive project architecture, operations, and handoff document for AI coding assistants and developers maintaining, diagnosing, and expanding AL-AMR — the 100% cloud-autonomous, headless, zero-local-dependency YouTube Shorts production and publishing pipeline.

---

## 1. Executive Summary & Core Mission

AL-AMR is a **100% cloud-autonomous, headless, 24/7 current-affairs and geopolitics YouTube Shorts production engine**. It transforms real-time global news into verified, high-retention vertical documentary videos (1080x1920, 30fps) without requiring a human operator, local PC, local browser, GUI automation, or home internet connection.

### Channel Focus:
* **Current Geopolitics & World Affairs**: Real-time breaking developments, diplomatic tensions, international security, defense developments, and high-interest global events.
* **Recency Hierarchy**: Strict focus on the last 0–24 hours (Tier 1 & Tier 2), falling back to 24–72 hours (Tier 3) only when breaking story density is low.
* **Journalistic Standard**: Factual claims grounded with 5W1H entity extraction and natural language inference (NLI) claim verification. Zero historical trivia fallbacks in current-affairs mode.
* **Production Aesthetics**: Pure voice narration (Sarah / `af_sarah`), word-level golden karaoke subtitle overlays (`.ass`), dynamic Ken Burns pan/zoom on real visual evidence, zero SFX, and clean documentary audio.

---

## 2. Absolute System Invariants (DO NOT VIOLATE)

> [!CAUTION]
> **CRITICAL ARCHITECTURAL CONSTRAINTS**:
> 1. **100% Cloud-Autonomous & Headless Runtime**:
>    * Production executes entirely on ephemeral cloud runners (`ubuntu-latest` on GitHub Actions) and Google Drive cloud storage.
>    * **Zero Local Dependencies**: No dependency on the user's PC, Windows OS, local filesystem, or local internet connection.
>    * **Zero GUI / Browser Dependencies**: Absolute prohibition of Chrome, Chromium, Selenium, Playwright, Puppeteer, Antigravity CLI, Antigravity `/browser`, `webbrowser.open()`, localhost callback servers, and Windows Task Scheduler.
>    * **Dev vs Prod Boundary**: Antigravity and `/browser` are development-only diagnostic tools. They are strictly prohibited from runtime production workflows.
> 2. **Buffer Replenishment Decoupled from Publishing**:
>    * Buffer production (`.github/workflows/produce_buffer.yml` via `main.py --cloud-produce`) ONLY produces verified MP4s to Google Drive `01_READY`. It **NEVER** calls YouTube upload or publishing APIs.
>    * Publishing (`.github/workflows/autopilot.yml` via `main.py --schedule-ready`) runs on an independent cron gate, claims the oldest ready video from `01_READY`, uploads to YouTube Data API v3, verifies public status, and moves it to `03_PUBLISHED`.
> 3. **Voice Permanently Locked to Sarah**:
>    * All voiceover synthesis is strictly locked to Kokoro-v1.0 ONNX `af_sarah` (`SARAH_MAX_CREATOR`). No other voice models are permitted in production.
> 4. **SFX Permanently Disabled & BGM Policy None**:
>    * Sound effects (`has_sfx=False`) are permanently disabled across all production manifests.
>    * BGM policy is strictly set to `NONE` (`has_bgm=False`) for clean, authoritative documentary voiceover.
> 5. **Fail-Closed Video QA Gate**:
>    * Videos must pass all 12 automated QA inspection checks before moving to Google Drive `01_READY`.
>    * Flawed, corrupted, or unverified videos fail closed into `04_FAILED` or local quarantine; they are never published.

---

## 3. End-to-End Modular Pipeline Architecture (Phases 1–7)

The production pipeline is organized into 7 clean, decoupled architectural layers:

```
[ LIVE NEWS INGESTION (Phase 1) ]
  ├── GDELT 2.0 Global Event API
  ├── Top Global Wire RSS Feeds (BBC, Al Jazeera, DW, France 24)
  └── Trafilatura Article Body & Metadata Extraction
            ↓
[ CLUSTERING & 5W1H EVENT CARDS (Phase 2) ]
  ├── FastEmbed Dense Semantic Embeddings (BAAI/bge-small-en-v1.5) with O(N) Cache
  ├── Pairwise Cosine + Entity Overlap Graph Clustering
  └── Gemini 5W1H Structured Entity & EventCard Extraction
            ↓
[ JOURNALISTIC SCRIPT SYNTHESIS (Phase 3) ]
  ├── 4-Beat Strict Narrative Arc (Hook, Context, Escalation, Climax/Resolution)
  ├── 21.0s – 25.5s Duration Budget (55–75 spoken words)
  ├── 5 Hook Candidates (Curiosity, Escalation, Contrast, Impact, Insider)
  └── NLI Claim Grounding against Source Articles
            ↓
[ DUAL-ROUTE VISUAL EVIDENCE RETRIEVAL (Phase 4) ]
  ├── Route A (Primary): Real Visual Evidence (Wikimedia Commons, Internet Archive, Wikidata)
  ├── Route B (Fallback): High-Relevance Thematic Stock (Pexels REST API)
  └── Beat-Level 5W1H Query Planning & Spatial Resolution Validation
            ↓
[ PRODUCTION ASSET MANIFEST (Phase 5) ]
  ├── ProductionAssetManifest Specification (JSON Schema)
  ├── 4 Timed Visual Beats with Exact Timecodes
  └── Locked Audio Spec (Voice: Sarah, SFX: Disabled, BGM: None)
            ↓
[ MEDIA CACHE, HEADLESS COMPOSITION & QA (Phase 6) ]
  ├── Local Multi-Tier Disk Cache (SHA-256 Verified, LRU Eviction)
  ├── Kokoro-v1.0 ONNX Offline Voice Synthesis + Faster-Whisper Word-Level .ass Captions
  ├── Headless FFmpeg 1080x1920 30fps Ken Burns Pan/Zoom Dynamic Video Composition
  └── Automated 12-Point QA Battery (Resolution, Audio Levels, Duration, Corruption)
            ↓
[ CLOUD ORCHESTRATION & VAULT SYNC (Phase 7) ]
  ├── CloudProductionOrchestrator (Distributed Locking, Idempotency, Deficit Calculation)
  ├── Canonical SQLite Database Sync (`00_SYSTEM/pipeline.db`)
  ├── Google Drive Vault Delivery (`01_READY`)
  └── Decoupled Publishing Gate (`.github/workflows/autopilot.yml`)
```

---

## 4. Phase-by-Phase Component Details

### Phase 1: Real-Time News Ingestion & Normalization
* **Module**: `sources/news_ingestion.py`
* **Sources**: Multi-feed RSS ingestion (BBC World, Al Jazeera, Deutsche Welle, France 24) + GDELT 2.0 API.
* **Data Contract**: `NormalizedArticle` (title, URL, publisher, UTC timestamp, full text, author, source type, language).
* **Extraction**: Trafilatura clean article body extraction with non-blocking error isolation.
* **Recency Classification**: Tier 1 (0–6h), Tier 2 (6–24h), Tier 3 (24–72h), Tier 4 (72h+ background).
* **Guarantees**: Complete removal of historical trivia seeds in current-affairs mode. Network failures on single feeds do not crash the run.

### Phase 2: High-Density Event Clustering & 5W1H EventCards
* **Module**: `intelligence/clustering.py`
* **Embedding Model**: FastEmbed ONNX `BAAI/bge-small-en-v1.5` running locally on CPU.
* **Performance Optimization**: Dense embeddings cached directly on `NormalizedArticle.embedding` ($O(N)$ inference rather than $O(N^2)$).
* **Clustering**: Connected components over graph edges satisfying semantic similarity $>0.78$ and entity token Jaccard overlap $>0.15$.
* **EventCard Extraction**: Google GenAI model (`gemini-2.5-flash` / `gemma-4-26b-a4b-it`) extracts structured 5W1H (Who, What, Where, When, Why, How, Core Conflict, Geopolitical Significance).

### Phase 3: Journalistic Script Synthesis & Fact Grounding
* **Module**: `intelligence/journalistic_script.py`
* **Format**: Exactly 4 narrative beats:
  1. `BEAT_1_HOOK` (0.0s – 5.0s, high-impact hook)
  2. `BEAT_2_CONTEXT` (5.0s – 11.5s, 5W1H factual foundation)
  3. `BEAT_3_ESCALATION` (11.5s – 18.0s, geopolitical tension/stakes)
  4. `BEAT_4_RESOLUTION` (18.0s – 24.5s, forward-looking impact)
* **Word Count**: Strictly 55–75 words for natural 21–25.5s delivery.
* **Verification**: Sentence-level NLI grounding against source article snippets with citation mapping.
* **Voice Invariant**: Permanently set to Sarah (`af_sarah`).

### Phase 4: Dual-Route Visual Evidence Retrieval
* **Modules**: `retrieval/visual_sources.py`, `retrieval/visual_evidence.py`
* **Route A (Primary)**: Real visual evidence search via Wikimedia Commons REST API, Internet Archive, and Wikidata SPARQL.
* **Route B (Fallback)**: Pexels API semantic search when public domain real footage is unavailable.
* **Query Planning**: Specific entity, location, and event queries derived from the 5W1H EventCard.

### Phase 5: Production Asset Manifest
* **Module**: `core/asset_manifest.py`
* **Model**: `ProductionAssetManifest`
* **Structure**: Manifest ID, EventCard ID, 4 Visual Beats (timecodes, primary visual URL, fallback URLs, visual description, caption text), Audio Spec (voice: `af_sarah`, speed: 1.05, `has_sfx=False`, `has_bgm=False`), SEO metadata (title, description, tags).
* **Storage**: Persisted to SQLite table `production_asset_manifests`.

### Phase 6: Media Cache, Headless Composition & Video QA
* **Modules**: `storage/media_cache.py`, `retrieval/asset_fetcher.py`, `composition/headless_renderer.py`, `qa/video_qa.py`
* **Media Cache**: Multi-tier local disk cache under `data/cache/` with SHA-256 URL hashing and LRU size pruning.
* **Headless Composition**: Pure headless FFmpeg invocation generating 1080x1920 30fps vertical MP4s with Ken Burns dynamic motion and burn-in golden karaoke subtitles.
* **Automated QA Battery**:
  1. Video stream present and encoded with H.264.
  2. Resolution exactly 1080x1920 (9:16 vertical).
  3. Frame rate 25–60 fps (target 30 fps).
  4. Duration strictly between 20.0s and 26.5s.
  5. Audio stream present and encoded with AAC.
  6. Voiceover loudness normalized (-14 to -18 LUFS).
  7. Audio peak below 0.0 dBTP (no clipping).
  8. Audio stream audible (not silent, mean > -45 dB).
  9. File size healthy (2 MB to 100 MB).
  10. Container integrity verified (no MOOV atom corruption).
  11. Subtitle rendering verified.
  12. Zero SFX and zero unauthorized BGM presence.

### Phase 7: Cloud Production Orchestration & Drive Vault Integration
* **Modules**: `core/pipeline_state.py`, `intelligence/cloud_orchestrator.py`
* **Entrypoints**:
  * `python main.py --cloud-produce <count>`: Executes headless buffer replenishment.
  * `python main.py --cloud-produce <count> --dry-run`: Runs end-to-end intelligence and verification without persistent side effects.
* **Cloud Lock**: Distributed lock `00_SYSTEM/cloud_production.lock` on Google Drive prevents concurrent producer overlap.
* **Canonical DB Sync**: Downloads `00_SYSTEM/pipeline.db` from Drive, executes idempotent production, verifies QA, uploads new verified MP4s to `01_READY`, and uploads the updated database back to `00_SYSTEM/pipeline.db`.
* **Telemetry**: Emits structured JSON summary to `data/production_summary.json` with stage-by-stage timings, buffer counts, and manifest IDs.

---

## 5. Google Drive Vault Hierarchy

Google Drive serves as the central serverless persistence store and state coordination layer between independent GitHub Actions runner instances:

```
AL-AMR Vault/
├── 00_SYSTEM/
│   ├── pipeline.db              # Canonical SQLite production database
│   └── cloud_production.lock    # Distributed JSON lock (lease expiry 2 hours)
├── 01_READY/                    # Buffer of 100% QA-verified MP4 shorts awaiting publication
│   ├── SHORT_20260905_120000.mp4
│   └── SHORT_20260905_120000.json
├── 02_PROCESSING/               # Short currently being uploaded by autopilot.yml
├── 03_PUBLISHED/                # Successfully published shorts archive
│   └── SHORT_20260905_060000.mp4
└── 04_FAILED/                   # Quarantined shorts that failed upload or QA
```

* **Target Buffer**: 6 verified Shorts (`TARGET_BUFFER = 6`).
* **Deficit Rule**: `produce_buffer.yml` audits `01_READY` and synthesizes only `to_produce = min(requested_count, max(0, 6 - count(01_READY)))` videos. When `count(01_READY) >= 6`, production is skipped to conserve compute and API calls.

---

## 6. GitHub Actions Automation & Decoupled Schedules

### Workflow 1: Buffer Replenishment (`produce_buffer.yml`)
* **File**: `.github/workflows/produce_buffer.yml`
* **Trigger**: Scheduled cron runs + manual `workflow_dispatch`.
* **Action**:
  ```bash
  python main.py --cloud-produce 2
  ```
* **Strict Gate**: Produces exclusively to Drive `01_READY`. Contains **NO** publishing or YouTube upload commands.

### Workflow 2: YouTube Publishing Gate (`autopilot.yml`)
* **File**: `.github/workflows/autopilot.yml`
* **Trigger**: 4 daily windows: `06:00`, `10:00`, `15:00`, `20:00` UTC (`11:30 AM`, `3:30 PM`, `8:30 PM`, `1:30 AM` IST).
* **Action**:
  ```bash
  python main.py --schedule-ready
  ```
* **Protocol**:
  1. Inspects Drive `01_READY` for the oldest verified Short.
  2. Moves file to `02_PROCESSING`.
  3. Uploads to YouTube Data API v3 as `PUBLIC`.
  4. Verifies public status via YouTube Data API call.
  5. Moves file to `03_PUBLISHED`.

---

## 7. Authentication & Credentials Matrix

All production credentials operate within free-tier quotas and are injected via GitHub Actions Repository Secrets:

| Secret Name | Loaded By | Purpose | Required in Cloud |
| :--- | :--- | :--- | :---: |
| `GEMINI_API_KEY` | `config/settings.py` | Google GenAI API (Script, 5W1H, SEO) | **Yes** |
| `PEXELS_API_KEY` | `config/settings.py` | Pexels REST API (Visual fallback) | **Yes** |
| `GDRIVE_SERVICE_ACCOUNT_JSON` | `engines/drive_engine.py` | Google Drive Vault Storage API | **Yes** |
| `TOKEN_JSON` | `engines/upload_engine.py` | YouTube Data API v3 OAuth User Token | **Yes** (Publishing only) |
| `CLIENT_SECRET_JSON` | `config/settings.py` | Google Cloud OAuth App Client Secret | **Yes** (Publishing only) |

---

## 8. Verification & Test Suite Reference

The codebase maintains a 100% passing test suite across all 7 phases:

```bash
# Execute complete Phase 1–7 test suite (194 tests)
pytest tests/test_phase1_news_ingestion.py \
       tests/test_phase2_event_clustering.py \
       tests/test_phase3_journalistic_script.py \
       tests/test_phase4_visual_evidence.py \
       tests/test_phase5_asset_manifest.py \
       tests/test_phase6_asset_fetcher.py \
       tests/test_phase6_media_cache.py \
       tests/test_phase6_video_qa.py \
       tests/test_phase6_rendering.py \
       tests/test_phase7_cloud_orchestration.py -v
```

### Dry-Run Verification Command
To verify the complete cloud pipeline end-to-end headlessly without uploading or writing to Drive:
```bash
python main.py --dry-run --cloud-produce 1
```

---

## 9. Handoff Maintenance Checklist for Future AI Agents

When diagnosing, maintaining, or expanding AL-AMR:
1. **Preserve Cloud Autonomy**: Never introduce dependencies on GUI tools, local browsers, Antigravity CLI, or Windows-specific paths.
2. **Preserve Editorial Invariants**: Voice is permanently Sarah (`af_sarah`); SFX is permanently disabled (`has_sfx=False`); BGM is `NONE`.
3. **Preserve Decoupled Publishing**: Never call YouTube upload or publishing code inside `produce_buffer.yml` or `intelligence/cloud_orchestrator.py`.
4. **Preserve FastEmbed Caching**: Always ensure `NormalizedArticle.embedding` is cached during clustering to avoid $O(N^2)$ inference latency.
5. **Preserve Schema Upgrades**: When syncing canonical `pipeline.db` from Drive, call `init_db()` immediately after download to guarantee all tables exist.
