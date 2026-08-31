# 02 — Production Pipeline

> **Status:** `[VERIFIED & OPERATIONAL]`  
> **Scope:** End-to-end multi-stage pipeline specification from topic selection to YouTube publishing.  

---

## 1. Pipeline Stages Deep-Dive

### Stage 1: Historical Topic Discovery & Semantic Deduplication
- **Engine**: [`engines/topic_discovery.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/topic_discovery.py)
- **Mechanism**: Samples from 11 diverse historical categories (American History, European History, Strange Historical Laws, Unusual Wars, Historical Mysteries, Strange Inventions, Lost Places, Unusual Borders, Unexpected Coincidences, Documented Disasters, Forgotten Figures).
- **Deduplication Gate**: Computes token cosine similarity and Levenshtein distance against all historical topics in SQLite. Reselects if similarity $\ge 0.65$.
- **Seed Inventory**: 16 curated high-retention seed anchors with pre-verified historical facts.

### Stage 2: Fact Verification & Temporal Anti-Anachronism Guardrails
- **Engine**: [`engines/fact_verifier.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/fact_verifier.py)
- **Mechanism**: Validates historical claims, dates, names, and geographic locations.
- **Anachronism Defense**: Rejects concepts that did not exist during the documented era (e.g. Victorian electronics or Renaissance steam locomotives).
- **Poison-Pill Quarantine**: If a topic fails fact-checking, it is tagged `RESEARCH_FAILURE` and quarantined from the active execution.

### Stage 3: 5-Beat Retention Scripting
- **Engine**: [`engines/script_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/script_engine.py)
- **Structure**:
  1. **Beat 1: The Hook** (0.0s – 4.5s, 8–11 words): High-novelty pattern interrupt.
  2. **Beat 2: The Context** (4.5s – 9.0s, 9–12 words): Historical setting and stakes.
  3. **Beat 3: The Escalation** (9.0s – 13.5s, 9–12 words): The conflict or bizarre complication.
  4. **Beat 4: The Reveal** (13.5s – 18.0s, 9–12 words): The climactic historical outcome.
  5. **Beat 5: The Loop Twist** (18.0s – 22.5s, 8–11 words): Irony or seamless transition back to the hook.
- **Calibration**: Strictly **48 to 52 words** total, yielding **21.5s to 23.5s** of narration at 2.2 words/second.

### Stage 4: Visual Asset Sourcing & Directing
- **Engines**: [`engines/asset_fetcher.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/asset_fetcher.py), [`engines/storyboard_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/storyboard_engine.py), [`engines/editing_director.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/editing_director.py)
- **Hierarchy**:
  1. **Archival Primary**: Wikimedia Commons historical photos, maps, engravings, and paintings (Public Domain / CC0).
  2. **Generative Reconstruction**: Pollinations AI for photorealistic period reconstructions (Tagged `GENERATED_RECONSTRUCTION`, `is_generated_reconstruction: True`).
  3. **Atmospheric B-Roll**: Pexels commercial stock video ($0 cost, commercial license verified).
- **Visual Beats**: 7 to 10 scene cuts per Short with Ken Burns camera motion (subtle zoom-in, pan-left, zoom-out).

### Stage 5: Neural Voice Synthesis (Kokoro-82M)
- **Engine**: [`engines/tts_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/tts_engine.py)
- **Model**: Kokoro-82M ONNX model running locally ($0 API cost, zero cloud dependencies).
- **Voice**: `af_bella` (Female American English, authoritative documentary cadence).
- **Sample Rate**: 24,000 Hz resampled to 44,100 Hz broadcast standard.

### Stage 6: 3-Stage Audio Mixing & BGM Standardization
- **Engine**: [`engines/audio_mixer.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/audio_mixer.py)
- **Stage A**: Voiceover narration isolation.
- **Stage B**: Standalone BGM bed normalized to **`-30.0 LUFS`** with fade-in (0.8s) and fade-out (1.5s).
- **Stage C**: Master mix combined with optional SFX cues, mastered via EBU R128 `loudnorm` to **`-14.0 LUFS`** with True Peak ceiling **`-1.0 dBTP`**.

### Stage 7: Vertical FFmpeg Video Composition
- **Engine**: [`engines/render_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/render_engine.py)
- **Resolution**: Exactly `1080x1920` (9:16 vertical).
- **Subtitles**: Dynamic ASS burned-in subtitles with word-level highlight synchronization.
- **Video Bitrate**: 14,000 kbps (H.264 High Profile, Level 4.2).
- **Audio Bitrate**: 256 kbps (AAC stereo).

### Stage 8: Automated Multi-Factor Quality Control (QA Gate)
- **Engine**: [`engines/qa_engine.py`](file:///C:/Users/jisha/OneDrive/Desktop/yt%20automation/engines/qa_engine.py)
- **Inspection Checklist**:
  1. Resolution: Exactly `1080x1920`.
  2. Duration: Strictly `21.0s – 26.2s` (accommodates 0.6s outro padding).
  3. Narration Safety: Voice duration $\le 	ext{Video Duration} - 0.6	ext{s}$.
  4. Audio Quality: Master loudness in `[-22.0, -10.0] LUFS`, True Peak $\le 0.0	ext{ dBTP}$, zero clipping.
  5. BGM Identity Verification: FFT linear cross-correlation fingerprint score $\ge 0.65$.
  6. Licensing: 100% of assets verified commercial use ($0 cost).
  7. Publishing Limit: Published today $< 3$ Shorts.
- **Gate Outcome**: If passed, transitions job to `READY_TO_UPLOAD` and uploads to Drive `01_READY`. If failed, moves job to `NEEDS_REVIEW`.