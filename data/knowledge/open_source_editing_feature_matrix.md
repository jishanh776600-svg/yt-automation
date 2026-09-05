# Open-Source Video Editing & Clipping Architecture Matrix

This document provides a comprehensive technical audit of open-source video editing, automated clipping, and programmatic timeline systems to guide the design of the AL-AMR Advanced Editorial Engine.

---

## 1. Executive Summary & Licensing Boundaries

AL-AMR is an enterprise autonomous production system. In accordance with architectural safety rules:
- **Zero GPL/AGPL contamination**: Any capability from copyleft projects (OpenChatCut, VibeClip, Frontstage, Clips Studio) is strictly audited for conceptual patterns and **independently reimplemented in clean-room Python**. No implementation code or copyleft packages are imported or copied.
- **Permissive components**: Permissive projects (OpenReel Video - MIT, MovieGo - MIT, 
emotion-clip - MIT, Sprocket - MIT) provide structural reference models for multitrack timelines, keyframe interpolation, bezier easing, and ASS subtitle generation.

---

## 2. Comprehensive Repository Audit

### A. OpenChatCut
- **Repository URL**: https://github.com/0xsline/OpenChatCut
- **License**: AGPL-3.0
- **Relevant Implementation**: Agent-native declarative editing commands, multitrack timeline schema (layers for video, text, audio, effects), MCP (Model Context Protocol) project state exposure.
- **Direct Reuse Permitted**: **NO** (AGPL copyleft violation risk).
- **Independent Implementation Required**: **YES**.
- **AL-AMR Implementation**: engines/visual_intelligence/editing/timeline.py and 	elemetry.py.
- **Reason Selected**: Clean separation of declarative timeline representation from rendering execution.
- **Improvements for AL-AMR**: Reimplemented in Python with deterministic serialization, AI Council inspection schemas, and strict zero-network execution during tests.
- **Dependencies**: None (pure Python dataclasses).

### B. OpenReel Video
- **Repository URL**: https://github.com/Augani/openreel-video
- **License**: MIT
- **Relevant Implementation**: Browser WebCodecs multitrack timeline, keyframe animation engine (scale, translate, opacity, rotation, bezier curves), safe-zone constraints, word-level caption timing.
- **Direct Reuse Permitted**: **YES** (MIT license permits adaptation).
- **AL-AMR Implementation**: engines/visual_intelligence/editing/motion_engine.py and 	imeline.py.
- **Reason Selected**: Standardized keyframe interpolator supporting non-linear easing (ease_in, ease_out, ease_in_out, spring).
- **Improvements for AL-AMR**: Translated JS bezier math into deterministic Python easing functions generating FFmpeg zoompan and crop filter expressions.
- **Dependencies**: Standard Python math.

### C. MovieGo
- **Repository URL**: https://github.com/mowshon/moviego
- **License**: MIT
- **Relevant Implementation**: Scripted programmatic timeline composition for FFmpeg. High-level abstractions for trimming clips, audio layering, fades, and concatenation.
- **Direct Reuse Permitted**: **YES** (MIT license).
- **AL-AMR Implementation**: engines/visual_intelligence/editing/timeline.py and editor.py.
- **Reason Selected**: Robust clip trimming (in-point, out-point, duration clamping) and filtergraph chaining abstractions.
- **Improvements for AL-AMR**: Added real-footage prioritization, provenance retention, and dynamic aspect-ratio reframing.
- **Dependencies**: Standard library + existing FFmpeg wrapper.

### D. VibeClip
- **Repository URL**: https://github.com/oktaydbk54/vibeclip
- **License**: AGPL-3.0
- **Relevant Implementation**: Transcript-driven video clipping, vertical 9:16 reframing, active speaker centering, dynamic karaoke subtitle generation with word highlights.
- **Direct Reuse Permitted**: **NO** (AGPL copyleft).
- **Independent Implementation Required**: **YES**.
- **AL-AMR Implementation**: engines/visual_intelligence/editing/reframing_engine.py and subtitle_engine.py.
- **Reason Selected**: High-energy short-form pacing and punchy subtitle word animations.
- **Improvements for AL-AMR**: Built multi-style subtitle selector rather than one fixed karaoke style; added collision avoidance with faces and evidence badges.
- **Dependencies**: Faster-Whisper (already integrated in AL-AMR).

### E. Frontstage
- **Repository URL**: https://github.com/x777/frontstage
- **License**: GPL-3.0
- **Relevant Implementation**: AI-native multi-track editor, track collision detection, and automated timing adjustments.
- **Direct Reuse Permitted**: **NO** (GPL copyleft).
- **Independent Implementation Required**: **YES**.
- **AL-AMR Implementation**: engines/visual_intelligence/editing/position_engine.py and editing_rhythm.py.
- **Reason Selected**: Collision avoidance logic between overlapping visual elements on separate tracks.
- **Improvements for AL-AMR**: Pure mathematical 2D bounding box occlusion scoring for subtitles vs lower-thirds vs face bounding boxes.
- **Dependencies**: Standard library.

### F. remotion-clip (Remotion Ecosystem)
- **Repository URL**: https://github.com/remotion-dev/remotion
- **License**: MIT / Permissive for tooling
- **Relevant Implementation**: Declarative React timeline compositions, frame-exact time mapping, kinetic typography layouts, spring-physics motion curves.
- **Direct Reuse Permitted**: **YES** (Conceptual adaptation).
- **AL-AMR Implementation**: engines/visual_intelligence/editing/subtitle_templates.py and motion_engine.py.
- **Reason Selected**: Industry standard for programmatic kinetic subtitles and motion design.
- **Improvements for AL-AMR**: Reimplemented spring physics equations in Python to produce frame-accurate ASS subtitle scaling tags and FFmpeg parameters.
- **Dependencies**: Standard math library.

### G. Clips Studio (Clips Kitty)
- **Repository URL**: https://github.com/ColinGPT9/clips-studio
- **License**: AGPL-3.0
- **Relevant Implementation**: Multimodal clip selection, speaker-aware face tracking bounding boxes, safe-zone preservation for 9:16 vertical exports.
- **Direct Reuse Permitted**: **NO** (AGPL copyleft).
- **Independent Implementation Required**: **YES**.
- **AL-AMR Implementation**: engines/visual_intelligence/editing/reframing_engine.py and position_engine.py.
- **Reason Selected**: Safe-zone rules preventing UI clipping by TikTok/YouTube Shorts native overlays (like, comment, channel title).
- **Improvements for AL-AMR**: Formalized YouTube Shorts safe zone boundaries (top 15%, bottom 20%, right 15%) into deterministic collision constraints.
- **Dependencies**: None.

### H. Sprocket
- **Repository URL**: https://github.com/SprocketVideo/Sprocket
- **License**: MIT
- **Relevant Implementation**: Non-destructive timeline layering, transition blending curves (crossfade, dip, whip, wipe), audio envelope ducking.
- **Direct Reuse Permitted**: **YES** (MIT license).
- **AL-AMR Implementation**: engines/visual_intelligence/editing/transition_engine.py and udio_mixer.py.
- **Reason Selected**: Clean transition registry with explicit duration limits and volume curve smoothing.
- **Improvements for AL-AMR**: Pacing-aware transition selection enforcing anti-repetition cooldowns (e.g. no consecutive whip transitions).
- **Dependencies**: Standard library.

---

## 3. Capability Selection & Architecture Synthesis

| Capability | Best Reference | Strategy | Final AL-AMR Module |
|---|---|---|---|
| **Declarative Timeline Model** | OpenChatCut / MovieGo | Clean-room independent implementation | editing_models.py, 	imeline.py |
| **Multitrack Track Layering** | OpenReel / Sprocket | Adapted MIT architecture | 	imeline.py |
| **Multi-Style Subtitle Engine** | remotion-clip / VibeClip | Independent multi-template system | subtitle_engine.py, subtitle_templates.py |
| **Intelligent Style Selection** | AL-AMR Original Design | Narrative beat & intensity routing | style_selector.py |
| **Dynamic Subtitle Positioning** | Clips Studio / Frontstage | Independent 2D occlusion scoring | position_engine.py |
| **Keyframes & Camera Motion** | OpenReel / Remotion | Adapted math & spring physics | motion_engine.py |
| **Transition Registry** | Sprocket | Adapted with anti-repetition gate | 	ransition_engine.py |
| **Editing Rhythm Engine** | AL-AMR Original Design | Story density & pacing controller | editing_rhythm.py |
| **SFX Intelligence** | AL-AMR Original Design | Semantic archetype matching | sfx_engine.py |
| **Audio Mixing & Ducking** | Sprocket | Adapted 3-tier priority mixer | udio_mixer.py |
| **Vertical Reframing (9:16)** | VibeClip / Clips Studio | Independent subject-aware reframing | 
eframing_engine.py |
| **AI Council Telemetry** | OpenChatCut | Clean-room telemetry models | 	elemetry.py |
