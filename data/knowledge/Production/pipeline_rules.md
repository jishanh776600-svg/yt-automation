# Production Pipeline & Timing Rules

## 6-Stage Continuous Lifecycle
1. **01. Discovery**: Semantic deduplication & historical topic research (`[[Topics/topic_lifecycle|Topics]]`).
2. **02. Script**: 5-part retention-oriented narrative structure (`[[Scripts/retention_architecture|Scripts]]`).
3. **03. Kokoro**: Authoritative `af_bella` voiceover synthesis (`[[Voice/af_bella_canonical|Voice]]`).
4. **04. Visuals**: Multi-shot 1080x1920 video composition (`[[Visuals/composition_rules|Visuals]]`).
5. **05. Vault**: Automated upload to Google Drive `01_READY` reserve buffer.
6. **06. Live**: Scheduled publication via YouTube API (`[[Performance/publishing_and_telemetry|Publishing]]`).

## Dynamic Script & Audio Calibration
- Narration duration is the **authoritative timing measurement**.
- Target video duration: `video_duration = audio_duration + 0.6s (safety margin)`.
- Never use `-shortest` in FFmpeg; enforce synchronous render duration `-t`.
- Never truncate final spoken sentence.
- QA rejects any render where `voice_duration > video_duration - 0.6s`.
- Failures are quarantined to `[[Failures/quarantine_policy|04_FAILED]]`.