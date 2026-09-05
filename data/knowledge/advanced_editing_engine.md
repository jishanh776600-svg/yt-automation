# Advanced Editorial Engine Architecture

## 1. Overview
The AL-AMR Advanced Editorial Engine transforms the raw assets of an autonomous Short (narration beats, real-world footage, archival clips, official documents, evidence overlays, voice recordings, and background music) into a professional, human-edited, multitrack video production.

Instead of displaying generic stock clips with repetitive bottom-center subtitles, the engine produces a deterministic, serialized EditingPlan with:
1. Intelligent visual pacing and rhythm.
2. Narrative-aligned camera motions, keyframed scale/crop/pan, and easing curves.
3. Multi-style subtitle streams where distinct typographic treatments and screen coordinates are assigned dynamically within the SAME Short.
4. Safe-zone and face/evidence collision avoidance.
5. Semantic sound design (SFX) synchronized to narrative beats with frequency caps and cooldowns.
6. 3-tier prioritized audio ducking (Voice > SFX > BGM).
7. Vertical 9:16 reframing with subject awareness.
8. Complete provenance retention and measurable telemetry for the AI Council.

---

## 2. Directory Structure
`
engines/visual_intelligence/editing/
├── __init__.py               # Unified exports
├── editing_models.py         # Dataclasses: EditingPlan, ShotEdit, Keyframe, SubtitleCue, etc.
├── timeline.py               # Multitrack timeline composition and duration validation
├── style_selector.py         # EditingStyleSelector and SubtitleStyleSelector with cooldowns
├── subtitle_templates.py     # Comprehensive 20-style Subtitle Template Registry
├── subtitle_engine.py        # Multi-style ASS subtitle generator with word-level highlights
├── position_engine.py        # Dynamic subtitle positioning and 2D collision avoidance
├── motion_engine.py          # Keyframes, zooms, pans, spring physics, and freeze-frames
├── transition_engine.py      # Transition registry (cuts, dissolves, whips) with anti-repetition
├── editing_rhythm.py         # Visual change frequency and shot pacing controller
├── sfx_engine.py             # SFX intelligence, category matching, and volume calibration
├── audio_mixer.py            # Audio priority hierarchy, BGM ducking, and normalization
├── reframing_engine.py       # Subject-aware 9:16 vertical crop and safe-zone preservation
├── template_registry.py      # Versioned data-driven template store
├── telemetry.py              # Telemetry collector and AI Council interfaces
└── editor.py                 # AdvancedEditorialEngine orchestrator
`

---

## 3. Core Data Flow
`
ScriptRecord + Narration Audio
       │
       ▼
StoryboardEngine (7-10 Beats with VisualIntent)
       │
       ▼
SourceRouter (Classes A-D: Real, Archival, Official, Contextual)
       │
       ▼
VisualCandidateScorer (12-factor ranking, motion preference)
       │
       ▼
AdvancedEditorialEngine:
  ├── EditingStyleSelector (NEWS, INVESTIGATIVE, DRAMATIC, etc.)
  ├── EditingRhythmEngine (Calculates beat durations, cuts, emphasis points)
  ├── SubtitleStyleSelector (Assigns styles per beat: HOOK, IMPACT, QUOTE, STAT)
  ├── SubtitlePositionEngine (Calculates positions avoiding faces/overlays)
  ├── MotionEngine (Generates punch-in, pans, keyframe curves)
  ├── TransitionEngine (Selects cuts, whips, dissolves with cooldown)
  ├── SFXEngine (Places restrained sound cues with volume attenuation)
  └── AudioDirector (Calculates BGM ducking envelopes)
       │
       ▼
Deterministic EditingPlan (Serializable JSON)
       │
       ▼
RenderEngine (FFmpeg compilation) + VisualQAGate
`
