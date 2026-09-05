# Editing Strategy Telemetry & AI Council Foundation

## 1. Architecture Objective
AL-AMR does not make speculative claims about AI self-learning without measurement.
The editing engine exposes structured, measurable telemetry for every decision made during the video assembly.

This enables future AI Council agents to:
1. Inspect the exact directorial choices for every produced video.
2. Compare competing editorial strategies across jobs (e.g. High Caption Density vs Minimalist Kinetic; Punchy 1.8s cuts vs Documentary 3.2s cuts).
3. Correlate strategies with downstream YouTube analytics (audience retention curve, swipe-away rate, watch time).

---

## 2. Telemetry Schema
Every EditingPlan generates an EditingTelemetry record containing:
- job_id: Unique production job identifier.
- editing_profile: Directorial profile used (e.g. NEWS, INVESTIGATIVE, DRAMATIC).
- shot_count: Total shots in the sequence.
- vg_shot_duration: Mean duration of visual shots.
- shot_duration_variance: Pacing variability across the Short.
- subtitle_styles_used: List of distinct subtitle templates deployed.
- subtitle_style_transitions: Number of style shifts within the video.
- subtitle_positions_used: Distinct screen coordinates utilized (avoiding visual monotony).
- caption_occlusion_avoidances: Number of times captions shifted position to avoid covering a face or evidence overlay.
- 	ransitions_used: Breakdown of transition types (cuts, crossfades, dips, whips).
- sfx_count: Number of sound effect cues.
- sfx_types_used: Archetypes placed (whoosh, boom, tension riser, etc.).
- camera_motions_used: Camera motion distribution (pans, zooms, keyframe scales).
- gm_track: Background track ID.
- gm_ducking_points: Number of audio ducking transitions applied.
- oice_id: TTS voice persona used.
- 
eal_footage_pct: Percentage of authentic/editorial footage.
- evidence_overlay_count: Number of verified lower-third graphic overlays.
- provenance_completeness: Provenance verification rate (target: 100%).

---

## 3. AI Council Strategy Models
The future AI Council interacts with these clean interfaces:
- EditingStrategy: A parameter bundle specifying pacing, style density, motion aggressiveness, and sound design.
- EditingDecision: An individual decision log (e.g. \'selected style IMPACT for shot 4 due to narrative escalation\').
- EditingTelemetry: Aggregate measurable metrics for the completed video.
- EditingOutcome: Downstream performance metrics linked to the strategy (retention at 3s, retention at 15s, completion rate).
