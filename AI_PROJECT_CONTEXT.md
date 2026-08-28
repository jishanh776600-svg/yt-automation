# 📘 AI Handoff & Project Context: Autonomous YouTube Shorts Production Pipeline

> **Document Version**: 2.0  
> **Last Updated**: 2026-08-28  
> **Repository**: `https://github.com/jishanh776600-svg/yt-automation.git`  
> **Purpose**: Durable, comprehensive project handoff document for AI coding assistants and developers maintaining, diagnosing, and expanding this autonomous YouTube channel pipeline.

---

## 1. Project Purpose

This project is an **autonomous, 24/7 $0-cost YouTube Shorts creation, QA, publishing, and self-learning pipeline** focused on high-retention historical documentaries and bizarre true events.

### End-to-End Objective:
1. Discover high-engagement, factual historical topics across curated categories.
2. Fact-check claims against historical archives (Wikipedia API).
3. Script 21–25 second viral documentary narratives with 5 hook variations.
4. Plan 5 visual scenes and fetch unique 1080x1920 portrait imagery (Pexels API + anti-duplication tracking).
5. Synthesize voiceover using an offline ONNX TTS engine (Kokoro-v1.0).
6. Transcribe word-level golden karaoke subtitle overlays (`.ass`) using local Faster-Whisper.
7. Select an authentic background music track from a 4-track local library using Gemini AI mood classification + deterministic keyword fallbacks.
8. Render 1080x1920 60fps MP4 vertical video with Ken Burns dynamic motion (FFmpeg).
9. Perform a 12-point quality assurance (QA) inspection including FFT cross-correlation BGM identity verification extracted directly from the final MP4.
10. Automatically upload and publicly publish to YouTube (OAuth 2.0 YouTube Data API v3).
11. Collect view retention/engagement metrics, compute rolling baselines, and persist self-learning patterns across independent cloud runs.

---

## 2. Current Architecture & Directory Structure

```
yt-automation/
├── .github/
│   └── workflows/
│       └── autopilot.yml          # GitHub Actions 24/7 cron runner (4 runs/day)
├── assets/
│   ├── fonts/                     # Montserrat-Bold & other ASS subtitle fonts
│   ├── music/                     # 4 approved BGM tracks (.mp3 & .wav)
│   │   ├── Empty - Emotional Sad Background.mp3 / .wav
│   │   ├── No Copyright Background Music.mp3 / .wav
│   │   ├── No copyright Best Historical.mp3 / .wav
│   │   └── The Flux Beneath It All.mp3 / .wav
│   └── sfx/                       # Whooshes, risers, and transition sound effects
├── config/
│   ├── __init__.py
│   ├── constants.py               # Enums, video specs, duration constraints, daily limits
│   └── settings.py                # Environment loading, dynamic paths, provider configs
├── core/
│   ├── __init__.py
│   ├── database.py                # SQLite database session and connection setup
│   ├── license_tracker.py         # Commercial CC0 / Pexels license compliance verification
│   ├── models.py                  # SQLAlchemy ORM schemas (Job, Topic, Render, Upload, etc.)
│   └── state_machine.py           # 20-state pipeline lifecycle and transitions
├── dashboard/
│   ├── __init__.py
│   ├── app.py                     # FastAPI web dashboard for monitoring jobs and analytics
│   ├── static/                    # Dashboard CSS/JS assets
│   └── templates/                 # Jinja2 HTML templates
├── data/                          # Runtime data directory (ephemeral in cloud, persisted locally)
│   ├── database/
│   │   └── pipeline.db            # SQLite relational database
│   ├── captions/                  # Generated .ass karaoke subtitle files
│   ├── LEARNING_LOG.md            # Markdown performance intelligence log
│   ├── renders/                   # Generated 1080x1920 MP4s and master audio mixes
│   └── voice/                     # Synthesized .wav voiceover narrations
├── engines/
│   ├── __init__.py
│   ├── analytics_engine.py        # Orchestrates the feedback loop
│   ├── asset_fetcher.py           # Pexels API photo search + anti-duplication database tracking
│   ├── audio_mixer.py             # 3-stage audio pipeline (Voice, BGM-only, Master Mix)
│   ├── caption_engine.py          # Faster-Whisper word-level subtitle generation
│   ├── experiment_manager.py      # 60/30/10 content formula and A/B hypothesis engine
│   ├── learning_engine.py         # Extracts winning patterns and updates confidence scores
│   ├── metrics_collector.py       # Queries YouTube Data API v3 and Analytics API
│   ├── qa_engine.py               # 12-point QA battery + FFT BGM cross-correlation audit
│   ├── render_engine.py           # FFmpeg video compositing with Ken Burns zoom/pan effects
│   ├── report_generator.py        # Generates structured performance intelligence summaries
│   ├── research_engine.py         # Wikipedia-API factual archive retrieval
│   ├── script_engine.py           # Gemini 3.6 Flash 5-hook scriptwriter
│   ├── seo_engine.py              # Gemini 3.6 Flash high-CTR title, description & tag creator
│   ├── storyboard_engine.py       # Gemini 3.6 Flash 5-scene visual storyboard planner
│   ├── topic_discovery.py         # Curated + dynamic topic generation
│   ├── tts_engine.py              # Kokoro ONNX offline voice synthesis
│   ├── upload_engine.py           # YouTube Data API v3 upload & status verification
│   └── video_analyzer.py          # Classifies videos (Breakout/Solid/Underperforming)
├── tests/
│   ├── test_all_4_bgm_tracks.py   # Unit test verifying discovery, mix, render of all 4 tracks
│   ├── test_bgm_qa_rejection.py   # Verifies BGM QA passes genuine music and rejects noise
│   ├── test_bgm_system.py         # Tests mood selection rules and loudness normalization
│   ├── test_database.py           # Database CRUD test suite
│   ├── test_end_to_end_render.py  # Full pipeline integration render test
│   └── test_learning_feedback_loop.py # Performance intelligence loop verification
├── .env.example                   # Template of required environment variables
├── AI_PROJECT_CONTEXT.md          # THIS FILE (Permanent handoff guide)
├── client_secret.json             # Google Cloud OAuth 2.0 Client credentials
├── main.py                        # Master CLI and orchestrator entrypoint
├── requirements.txt               # Complete Python package dependencies
└── token.json                     # Permanent Google Cloud OAuth 2.0 authorized user token
```

---

## 3. Automation Flow

Every scheduled run follows this exact sequence:

```mermaid
graph TD
    A[GitHub Actions / Scheduler Trigger] --> B[Continuous Learning Feedback Loop]
    B --> C[Topic Selection & Wikipedia Fact-Checking]
    C --> D[Script Generation: 5 Hook Variants + Narrative Body]
    D --> E[Storyboard Planning: 5 Visual Search Queries]
    E --> F[Asset Fetcher: Pexels API + Anti-Duplication Check]
    F --> G[Voiceover Synthesis: Kokoro-v1.0 ONNX CPU]
    G --> H[Subtitle Generation: Faster-Whisper Word Timing ASS]
    H --> I[BGM Selection: Gemini AI Mood Matcher / Fallback]
    I --> J[Audio Mixing: 3-Stage Mix at -13dB & -14 LUFS]
    J --> K[Video Rendering: FFmpeg 1080x1920 Ken Burns Composite]
    K --> L[QA Engine: 12-Point Inspection + FFT BGM Verification]
    L -->|QA Failed| M[Auto-Repair Loop: Re-mix & Re-render Once]
    M --> L
    L -->|QA Passed| N{Production Mode?}
    N -->|TEST_MODE=true| O[Save MP4 Locally / Desktop & Stop]
    N -->|TEST_MODE=false| P[Upload to YouTube via Data API v3]
    P --> Q[Two-Step Verification: Confirm PUBLIC Status]
    Q --> R[Commit Learning Log & Database [skip ci]]
```

---

## 4. Current GitHub Actions Cloud Setup

* **Workflow File**: `.github/workflows/autopilot.yml`
* **Workflow Name**: `YouTube Shorts Cloud Autopilot`
* **Cron Expression**: `0 6,10,15,20 * * *` (Runs strictly 4 times daily)
* **Schedule Windows**:
  * `06:00 UTC` = **11:30 AM IST** (Morning audience window)
  * `10:00 UTC` = **03:30 PM IST** (European morning / India afternoon break)
  * `15:00 UTC` = **08:30 PM IST** (Major Peak: US East Coast morning & India evening)
  * `20:00 UTC` = **01:30 AM IST** (Major Peak: US West Coast afternoon & US East Coast evening)
* **Manual Dispatch**: Enabled via `workflow_dispatch` for on-demand testing.
* **Runner Environment**: `ubuntu-latest` (Python 3.11).
* **Concurrency Lock**: `concurrency.group: youtube-autopilot` (`cancel-in-progress: false`) ensures jobs never overlap or generate duplicate videos.

### Required GitHub Repository Secrets:
1. `GEMINI_API_KEY`: Google Gemini API key for script, storyboard, BGM, and SEO generation.
2. `PEXELS_API_KEY`: Pexels stock photo API key for visual retrieval.
3. `TOKEN_JSON`: Full JSON content of the permanent `token.json` OAuth credential.
4. `CLIENT_SECRET_JSON`: Full JSON content of `client_secret.json`.

---

## 5. Authentication & Credentials Architecture

All credentials operate at **$0 cost** within free tiers. **Never commit raw credentials to Git.**

| Credential Name | Storage Location | Loaded By | Purpose | Cloud Requirement |
| :--- | :--- | :--- | :--- | :--- |
| `GEMINI_API_KEY` | `.env` / GitHub Secret | `config/settings.py` | Google GenAI SDK (`gemini-3.6-flash`) | **Mandatory** |
| `PEXELS_API_KEY` | `.env` / GitHub Secret | `config/settings.py` | Pexels REST API (Photo search) | **Mandatory** |
| `token.json` | Project root / GitHub Secret | `upload_engine.py`, `metrics_collector.py` | YouTube Data API v3 OAuth 2.0 User Token | **Mandatory** |
| `client_secret.json`| Project root / GitHub Secret | `config/settings.py` | Google Cloud OAuth App Client Secret | **Mandatory** |

> [!IMPORTANT]
> **Token Permanence Note**: The Google Cloud OAuth Consent Screen is set to **"In production"** mode. Therefore, the OAuth refresh token in `token.json` **never expires** unless manually revoked.

---

## 6. Current Production Configuration

* **Daily Output Limit**: Exactly **`4 Shorts/day`** (`DAILY_SHORTS_LIMIT = 4` in `config/constants.py`).
* **Target Video Specs**: `1080x1920` (9:16 vertical), 30 fps, H.264 video, AAC stereo audio.
* **Duration Limits**: Strict `21.0s` to `25.5s` (Optimized for YouTube Shorts loop retention).
* **Audio Mixing Standard**:
  * Voiceover: Primary and dominant.
  * BGM Level: `-13.0 dB` relative to narration (`normalize=0` in `amix` to prevent volume halving).
  * Fade Transitions: `0.8s` fade-in, `1.5s` fade-out.
  * Master Loudness: `-14.0 LUFS` ($\pm 1.5$ dB) via `loudnorm`.
* **Visibility**: Strictly `PUBLIC` on upload.

---

## 7. The 4 Approved Background Music Tracks

The pipeline operates strictly with the 4 local audio files in `assets/music/`. **Do NOT generate synthetic AI audio.**

| Track File | Key | Targeted Mood & Atmosphere | Prioritized Niches |
| :--- | :--- | :--- | :--- |
| **`No copyright Best Historical.wav / .mp3`** | `best_historical` | Historical / Serious Documentary / War / Disaster / Bizarre Events | Military battles, historic riots, bizarre laws, royal court drama. |
| **`Empty - Emotional Sad Background.mp3 / .wav`** | `emotional_sad` | Emotional / Sad / Mournful / Poignant / Human Tragedy | Tragic sacrifices, catastrophic losses, poignant farewells, grief. |
| **`The Flux Beneath It All.mp3 / .wav`** | `flux_ambient` | Dark / Mysterious / Curious / Scientific Wonder / Intrigue | Lost civilizations, ancient ciphers, strange inventions, riddles. |
| **`No Copyright Background Music.wav / .mp3`** | `suspense_climax` | High Tension / Suspense / Dramatic Build-Up / Thriller | Heists, manhunts, high-stakes escapes, urgent races against time. |

---

## 8. Continuous Self-Learning & State Persistence

The pipeline contains a closed feedback loop (`MEASURE -> ANALYZE -> LEARN -> TEST -> REPORT`):
1. **Metrics Collection**: `MetricsCollector` queries YouTube Data API v3 and Analytics API for all uploaded Shorts (Views, APV, AVD, Engagement).
2. **Analysis**: `VideoAnalyzer` classifies uploads as *Breakout* ($>1.25\times$ median), *Solid* ($0.75\times - 1.25\times$), or *Underperforming* ($<0.75\times$).
3. **Knowledge Base**: `LearningEngine` extracts root-cause hypotheses and updates the `ContentPattern` table in SQLite with confidence scores.
4. **Cloud Persistence**: After every cloud run, step 60 of `.github/workflows/autopilot.yml` automatically commits `data/LEARNING_LOG.md` and `data/database/pipeline.db` back to the GitHub repository using `[skip ci]`.
5. **Continuous Optimization**: Subsequent cloud runs check out this updated database and condition topic/hook generation on learned winning patterns using the 60/30/10 content formula.

---

## 9. Quality Assurance (QA) & FFT Acoustic Verification

The QA engine (`engines/qa_engine.py`) inspects the **final rendered MP4 file** directly before upload:
1. **Video Stream**: 1080x1920 resolution, H.264 codec, 21.0–25.5s duration.
2. **Audio Integrity**: AAC audio stream present, not silent (peak $> -30$ dB, mean $> -45$ dB), no clipping (peak $\le 0.0$ dBTP).
3. **Master Loudness**: Broadcast standard `-22.0` to `-10.0` LUFS (centered at `-14.0` LUFS).
4. **FFT Cross-Correlation BGM Verification**: Extracts audio from the rendered MP4 and computes cross-spectral FFT correlation against the reference Stage B BGM.
   * **Score $\ge 0.65$**: Confirms the genuine BGM track is physically present underneath narration $\to$ **PASS**.
   * **Score $< 0.65$**: Flags missing BGM or synthetic noise $\to$ **STRICT FAIL**.
5. **Fail-Safe Auto-Repair**: If QA fails, the system automatically remixes with `No copyright Best Historical.wav` and re-renders once before evaluating upload.

---

## 10. Quota, Rate Limit & Resource Ledger

| Resource | Actual Code Usage / Short | Projected 4/Day Usage | Official Free Tier Allowance | Remaining Daily Buffer | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **YouTube Data API v3** | `1,602 units` | **`6,408 units/day`** | `10,000 units/day` | **`3,592 units/day`** (35.9%) | ✅ **SAFE** |
| **Gemini 3.6 Flash** | `5 requests` | **`20 requests/day`** | `1,500 requests/day` (15 RPM) | **`1,480 requests/day`** (98.7%) | ✅ **SAFE** |
| **Pexels Photo API** | `5 requests` | **`20 requests/day`** (~600/mo) | `20,000 requests/month` | **`19,400 requests/mo`** (97.0%) | ✅ **SAFE** |
| **GitHub Actions Compute** | `~2.5 - 3.0 min` | **`~12 min/day`** (~360 min/mo) | `2,000 min/month` (Private Repo) | **`1,640 min/month`** (82.0%) | ✅ **SAFE** |
| **Kokoro-ONNX Voice** | `~2.5s local CPU` | `0 external calls / $0.00` | **Unlimited** (Local Engine) | **100% Free** | ✅ **SAFE** |
| **Faster-Whisper** | `~2.0s local CPU` | `0 external calls / $0.00` | **Unlimited** (Local Engine) | **100% Free** | ✅ **SAFE** |

---

## 11. Maintenance Guide for Future AI Agents

### Diagnosing Cloud Failures
1. Check GitHub Actions run logs under the **Actions** tab in the repository.
2. Check `data/LEARNING_LOG.md` and `pipeline.db` for the failed job's state history and QA report reasons.
3. Common error resolutions:
   * **Gemini 429 Quota Exceeded**: The pipeline has automatic semantic fallbacks. If persistent, verify the API key has available requests in Google AI Studio.
   * **YouTube Upload 401 Unauthorized**: Re-verify `token.json` secrets in GitHub Secrets.

### Running Local Test Pipeline
To run a safe local test that verifies the full pipeline (rendering, BGM mixing, QA) **WITHOUT publishing to YouTube**:
```bash
python main.py --test --force
```
* The final verified MP4 will be saved to your Desktop / `data/renders/VERIFIED_SHORT_TEST_OUTPUT.mp4`.
* YouTube upload is 100% bypassed in test mode.

### Running Test Suites
```bash
# Run all unit and integration tests
python -m unittest discover -s tests -p "test_*.py"

# Test specific BGM verification suite
python -m unittest tests/test_all_4_bgm_tracks.py
python -m unittest tests/test_bgm_qa_rejection.py
```

---

## 12. Important Architectural Decisions & Rationale

1. **Why Kokoro-ONNX & Faster-Whisper?**  
   Running TTS and transcription locally on CPU removes external API rate limits and paid per-character fees, ensuring 100% $0-cost predictability.
2. **Why 4 Specific BGM Tracks Instead of Synthetic Generation?**  
   Synthetic procedural wave generation sounded artificial and produced noise. High-quality converted royalty-free tracks provide broadcast documentary quality.
3. **Why FFT Cross-Correlation in QA?**  
   Simple volume/energy checks caused false positives when noise existed. FFT cross-correlation mathematically verifies that the exact chosen BGM track is inside the MP4 container.
4. **Why Commit SQLite Database to Git in GitHub Actions?**  
   GitHub Actions runners are ephemeral. Committing `pipeline.db` and `LEARNING_LOG.md` with `[skip ci]` provides serverless persistent state across scheduled runs.

---

## 13. Critical Rules: DO NOT BREAK

> [!CAUTION]
> **DO NOT VIOLATE THE FOLLOWING CONSTRAINTS:**
> 1. **Do NOT generate synthetic AI audio**: Only use the 4 genuine tracks in `assets/music/`.
> 2. **Do NOT remove `normalize=0` from FFmpeg `amix`**: FFmpeg default behavior halves audio volume when mixing 2 inputs; `normalize=0` maintains audible BGM level.
> 3. **Do NOT hardcode laptop absolute paths**: Always use `PROJECT_ROOT` and `Path` objects.
> 4. **Do NOT bypass the daily limit check**: `DAILY_SHORTS_LIMIT = 4` prevents exceeding the 10,000-unit YouTube quota.
> 5. **Do NOT upload in `TEST_MODE=true`**: Maintain absolute test isolation.

---

## 14. Future Work & Planned Enhancements

* [ ] Add automated multi-language translation and subtitle localization.
* [ ] Integrate YouTube Community tab automated polling based on high-performing Short topics.
* [ ] Implement automated A/B thumbnail title experiment tracking when YouTube Shorts natively supports custom thumbnail A/B testing.

---

## 15. Handoff Checklist for New AI Agent

If you are a new AI agent taking over this repository:
1. **Read this document thoroughly**: Understand the 20-state machine, audio mixing standards, and GitHub Actions cron schedule.
2. **Inspect `config/settings.py` and `config/constants.py`**: Understand the dynamic path setup and rate limit constants.
3. **Never alter working audio mixing or QA algorithms without running `tests/test_all_4_bgm_tracks.py` and `tests/test_bgm_qa_rejection.py`**.
4. **When modifying cloud workflows**, remember that environment variables are populated from GitHub Secrets.
5. **The system is fully autonomous**: 4 Shorts per day at `06:00`, `10:00`, `15:00`, and `20:00` UTC (`11:30 AM`, `3:30 PM`, `8:30 PM`, `1:30 AM` IST). Maintain the schedule and zero-cost integrity.
