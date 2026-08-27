# Fully Automated $0-Operating-Cost YouTube Shorts Pipeline
### Cinematic American & European Historical Stories (~23 Seconds | 1080x1920 9:16 Vertical)

---

## 1. System Overview

This system is an autonomous, end-to-end video creation, quality control, metadata optimization, and publishing pipeline for YouTube Shorts. It researches factual historical events, generates original cinematic scripts, constructs multi-shot visual sequences (Pexels + AI historical images), synthesizes documentary-style narration via Apache 2.0 open-weight TTS, mixes ducked background music and sound effects, creates word-level synchronized animated captions via Faster-Whisper, and renders broadcast-grade 1080x1920 MP4 vertical videos using FFmpeg.

---

## 2. Zero-Cost ($0) Commercial Licensing Architecture

Every component and asset is verified for $0 commercial use and YouTube monetization safety:

| Component | Technology / Provider | License | Commercial Cost | Free Limits |
| :--- | :--- | :--- | :--- | :--- |
| **Research & Fact-Checking** | Wikipedia REST API + Google AI Studio Free Tier | Open / CC-BY-SA / Gemini Free Tier | **$0.00** | 15 RPM / 1M TPM (Gemini) |
| **Stock Video & Images** | Pexels API | Pexels License | **$0.00** | 200 req/hour (20,000/month) |
| **AI Historical Visuals** | Pollinations.ai / HuggingFace Free Tier | Open / Commercial Use | **$0.00** | Unlimited standard requests |
| **Voiceover / TTS** | Kokoro-82M ONNX / Edge-TTS | Apache 2.0 / Free Model | **$0.00** | Local CPU inference |
| **Captions & Alignment** | Faster-Whisper (INT8 quantized) | MIT License | **$0.00** | Local CPU inference |
| **Background Music & SFX** | YouTube Audio Library & CC0 Archives | YouTube Monetizable / CC0 | **$0.00** | 100% Free |
| **Video Compositing** | FFmpeg 7.1 (Ken Burns motion engine) | LGPL / GPL | **$0.00** | Unlimited local rendering |
| **Publishing API** | Official Google YouTube Data API v3 | Google Cloud Free Tier | **$0.00** | 10,000 units/day (6+ Shorts/day) |

---

## 3. Project Directory Structure

```
history_shorts_pipeline/
├── config/
│   ├── constants.py          # State enums, 1080x1920 9:16 specs, duration constraints
│   └── settings.py           # Environment variables, directory paths, FFmpeg binary
├── core/
│   ├── models.py             # SQLAlchemy schema (Jobs, Topics, Sources, Claims, Scripts, Assets, QA)
│   ├── database.py           # SQLite connection & session management
│   ├── license_tracker.py    # Strict commercial license verification engine
│   └── state_machine.py      # 20-stage state machine with failure recovery
├── engines/
│   ├── topic_discovery.py    # Multi-factor historical topic discovery & scoring
│   ├── research_engine.py    # Wikipedia API & archive claim verification
│   ├── script_engine.py      # 21-25s high-retention 5-part scriptwriter
│   ├── storyboard_engine.py  # 4-7 shot visual pacing & camera motion planner
│   ├── asset_fetcher.py      # Pexels stock footage & AI image fallback engine
│   ├── tts_engine.py         # Kokoro-82M ONNX TTS engine (Apache 2.0)
│   ├── caption_engine.py     # Faster-Whisper word-level ASS caption generator
│   ├── audio_mixer.py        # Music ducking (-24 dB) & LUFS -14 normalization
│   ├── render_engine.py      # FFmpeg 9:16 1080x1920 video compositor
│   ├── qa_engine.py          # Automated video, audio, duration, and license validator
│   ├── seo_engine.py         # Anti-spam title, description & hashtag generator
│   ├── upload_engine.py      # Official YouTube Data API v3 uploader & scheduler
│   └── analytics_engine.py   # Performance tracking & 48-hour learning loop
├── dashboard/
│   ├── app.py                # FastAPI web server
│   └── templates/index.html  # Real-time state machine & review queue dashboard
├── assets/
│   ├── music/                # Royalty-free background audio tracks
│   └── sfx/                  # Cinematic whooshes, impacts, transitions
├── data/                     # Local data cache, database, renders, logs
├── main.py                   # Master CLI & automated daemon scheduler
├── .env.example              # Environment variables template
└── README.md
```

---

## 4. Setup & Running Instructions

### 1. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Populate optional keys (`GEMINI_API_KEY`, `PEXELS_API_KEY`, `CLIENT_SECRETS_FILE`).

### 2. Run Single Short Production Cycle (Test Mode)
```bash
python main.py --test
```
This will:
1. Discover & score a historical topic.
2. Fact-check dates and claims.
3. Generate a 21–25s script (48–62 words).
4. Fetch/crop 1080x1920 vertical visuals.
5. Synthesize documentary narration.
6. Generate word-level animated captions.
7. Mix and normalize audio to -14 LUFS.
8. Render the full 1080x1920 MP4 via FFmpeg.
9. Perform strict automated QA checks.
10. Stage the output safely in `data/renders/`.

### 3. Launch Real-Time Web Dashboard
```bash
python main.py --dashboard
```
Open `http://127.0.0.1:8000` in your web browser.

### 4. Run Automated Scheduled Daemon (1-3 Shorts/day)
```bash
python main.py --daemon
```

---

## 5. Automated Quality Control (QA) Standards

Before any video is approved:
- **Resolution**: Verified strictly as **1080x1920** (9:16 vertical).
- **Duration**: Verified strictly between **21.0s and 25.0s**.
- **Codecs**: H.264 video and AAC stereo audio.
- **Audio Integrity**: Narration present, music ducked to -24 dB during speech, normalized to -14 LUFS.
- **License**: 100% of used assets confirmed `commercial_use=True`.
- **Policy**: Anti-repetitive content verification.

If any check fails, the job is moved to `NEEDS_REVIEW` and blocked from publishing.
