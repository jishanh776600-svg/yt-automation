# Canonical Narration Voice: af_bella

## Overview
`af_bella` is the authoritative permanent voice for all AL AMR historical YouTube Shorts narration.

## Configuration & Standards
- **Voice Identifier**: `af_bella`
- **Engine**: Kokoro-v1.0 ONNX (Zero GPU dependency, ultra-fast CPU inference)
- **Format**: 24kHz / 44.1kHz 16-bit PCM WAV
- **Speed / Pacing**: 1.05x normal conversational speed (~2.3 to 2.6 words/sec)
- **Word Target**: 50 to 56 words for ~22.0 to 24.0s of clean narration
- **Outro Breathing Room**: Exactly +0.6s visual and audio buffer after final syllable

## Voice Invariants
1. All modules (`tts_engine.py`, `settings.py`, workflows, preview UI, E2E) resolve to `af_bella`.
2. Fallback to `am_adam` or other voices is strictly prohibited in production.
- **Pipeline Integration**: Implemented in [[Production/pipeline_rules|Pipeline Rules]].