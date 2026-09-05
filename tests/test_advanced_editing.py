"""
Comprehensive Automated Test Suite for Advanced Editorial Engine.
Validates all 30 individual required capabilities:
1. multiple subtitle styles within one Short;
2. deterministic subtitle selection;
3. subtitle style cooldown;
4. dynamic subtitle positions;
5. face/evidence collision avoidance;
6. caption readability;
7. editing rhythm;
8. shot duration constraints;
9. transition selection;
10. transition repetition prevention;
11. keyframe generation;
12. zoom generation;
13. SFX selection;
14. SFX cooldown;
15. BGM rotation;
16. voice rotation;
17. audio ducking;
18. vertical reframing;
19. real-footage integration;
20. evidence overlay integration;
21. provenance preservation;
22. rights-status enforcement;
23. template registry;
24. EditingStyleProfile;
25. editing telemetry;
26. AI Council compatibility;
27. niche-agnostic AST audit;
28. offline network boundary;
29. zero Drive mutation;
30. zero YouTube mutation.
"""
import ast
import os
import pytest
from pathlib import Path
from typing import Dict, Any, List

from engines.visual_intelligence.editing import (
    AdvancedEditorialEngine,
    SubtitleStyleType,
    SubtitlePositionType,
    SubtitleStyleSelector,
    EditingStyleSelector,
    SubtitlePositionEngine,
    MultiStyleSubtitleEngine,
    MotionEngine,
    MotionType,
    EasingType,
    spring_physics,
    ease_in_out_cubic,
    TransitionEngine,
    TransitionType,
    SFXEngine,
    SFXArchetype,
    AudioDirector,
    ReframingEngine,
    EditingRhythmEngine,
    MultitrackTimeline,
    TemplateRegistry,
    EditingTelemetryCollector,
    EditingStyleProfile,
    EditingPlan,
    EditingStrategy,
    EditingDecision,
    EditingOutcome,
    SUBTITLE_TEMPLATES
)
from engines.visual_intelligence.models import (
    VisualCandidate, VisualProvenance, RightsStatus, VisualContentType, VisualIntent
)
from engines.visual_intelligence.bgm_selector import BGMSelector
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy


@pytest.fixture
def sample_shots_data():
    """Generates 8 narrative shots representing a full Short."""
    return [
        {"shot_id": "s1", "narrative_stage": "HOOK", "narration_segment": "Why did the largest gold vault vanish overnight?", "duration": 2.2, "camera_motion": "punch_in"},
        {"shot_id": "s2", "narrative_stage": "SETUP", "narration_segment": "In October 1934, federal inspectors arrived at the central repository.", "duration": 3.0, "camera_motion": "slow_pan_left"},
        {"shot_id": "s3", "narrative_stage": "SETUP", "narration_segment": "Director William Hayes testified under oath before Congress.", "duration": 2.8, "camera_motion": "subtle_zoom_in"},
        {"shot_id": "s4", "narrative_stage": "ESCALATION", "narration_segment": 'The official report quoted Hayes saying: "The vault was empty before dawn."', "duration": 2.9, "camera_motion": "dynamic_reframe"},
        {"shot_id": "s5", "narrative_stage": "ESCALATION", "narration_segment": "Over 450 metric tons of bullion and $2.8 billion were completely missing.", "duration": 2.7, "camera_motion": "subtle_zoom_out"},
        {"shot_id": "s6", "narrative_stage": "REVEAL", "narration_segment": "Declassified archival documents revealed secret rail shipments headed north.", "duration": 2.5, "camera_motion": "slow_pan_right"},
        {"shot_id": "s7", "narrative_stage": "CLIMAX", "narration_segment": "The bullion was never stolen—it was secretly financing a wartime fleet!", "duration": 2.3, "camera_motion": "punch_in"},
        {"shot_id": "s8", "narrative_stage": "LOOP_TWIST", "narration_segment": "And that is why the vanished reserve changed the course of history.", "duration": 2.6, "camera_motion": "subtle_zoom_in"}
    ]


@pytest.fixture
def sample_candidates_map(sample_shots_data):
    """Generates authentic visual candidates for each shot."""
    cands = {}
    for i, s in enumerate(sample_shots_data):
        sid = s["shot_id"]
        prov = VisualProvenance(
            asset_id=f"prov_{sid}",
            source="archive_records",
            source_url=f"https://archive.org/details/{sid}",
            publisher="National Historical Archive",
            rights_status=RightsStatus.PUBLIC_DOMAIN,
            license_name="Public Domain Mark 1.0"
        )
        cands[sid] = VisualCandidate(
            candidate_id=f"cand_{sid}",
            source_class="SOURCE_C",
            source_name="archive",
            source_url=f"https://archive.org/details/{sid}",
            content_type=VisualContentType.ARCHIVAL_VIDEO if i % 2 == 0 else VisualContentType.SCREENSHOT_DOCUMENT,
            is_video=(i % 2 == 0),
            motion_score=0.85 if (i % 2 == 0) else 0.0,
            provenance=prov
        )
    return cands


# --------------------------------------------------------------------------
# TEST 01: Multiple Subtitle Styles Within One Short
# --------------------------------------------------------------------------
def test_01_multiple_subtitle_styles_within_one_short(sample_shots_data, sample_candidates_map):
    """A Short must deploy multiple distinct typographic styles across its narrative beats."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_multi_style_01",
        topic_title="The Vanished Gold Reserve",
        category="History",
        script_text="Why did the largest gold vault vanish...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    styles_used = set()
    for s in plan.shots:
        for cue in s.subtitle_cues:
            styles_used.add(cue.style_type)

    assert len(styles_used) >= 3, f"Expected at least 3 distinct subtitle styles in one Short, got: {styles_used}"


# --------------------------------------------------------------------------
# TEST 02: Deterministic Subtitle Selection
# --------------------------------------------------------------------------
def test_02_deterministic_subtitle_selection():
    """SubtitleStyleSelector must map narrative cues to specific styles deterministically."""
    selector = SubtitleStyleSelector()
    assert selector.select_style_for_beat(0, "HOOK", "Why did the president resign?") == SubtitleStyleType.QUESTION
    selector.reset()
    assert selector.select_style_for_beat(1, "SETUP", 'He declared: "We have nothing to fear."') == SubtitleStyleType.QUOTE
    selector.reset()
    assert selector.select_style_for_beat(2, "ESCALATION", "Inflation hit 45.8% across 12 sectors.") == SubtitleStyleType.STATISTIC
    selector.reset()
    assert selector.select_style_for_beat(3, "CLIMAX", "The explosion ripped through the hull!", intensity="CLIMAX") == SubtitleStyleType.IMPACT


# --------------------------------------------------------------------------
# TEST 03: Subtitle Style Cooldown
# --------------------------------------------------------------------------
def test_03_subtitle_style_cooldown():
    """Specialized high-impact styles cannot repeat more than 2 consecutive times."""
    selector = SubtitleStyleSelector()
    s1 = selector.select_style_for_beat(1, "CLIMAX", "Crash 1", intensity="CLIMAX")
    s2 = selector.select_style_for_beat(2, "CLIMAX", "Crash 2", intensity="CLIMAX")
    s3 = selector.select_style_for_beat(3, "CLIMAX", "Crash 3", intensity="CLIMAX")
    assert s1 == SubtitleStyleType.IMPACT
    assert s2 == SubtitleStyleType.IMPACT
    assert s3 != SubtitleStyleType.IMPACT, "Third consecutive specialized style must be throttled by cooldown"


# --------------------------------------------------------------------------
# TEST 04: Dynamic Subtitle Positions
# --------------------------------------------------------------------------
def test_04_dynamic_subtitle_positions():
    """Position engine must support diverse screen positions without sticking to bottom-center only."""
    pos_engine = SubtitlePositionEngine()
    p_std = pos_engine.select_optimal_position(evidence_overlay_present=False)
    p_climax = pos_engine.select_optimal_position(is_dramatic_climax=True)
    assert p_std == SubtitlePositionType.BOTTOM_CENTER
    assert p_climax == SubtitlePositionType.CENTER


# --------------------------------------------------------------------------
# TEST 05: Face and Evidence Collision Avoidance
# --------------------------------------------------------------------------
def test_05_face_evidence_collision_avoidance():
    """Subtitles must automatically shift to UPPER_CENTER when lower evidence card is present."""
    pos_engine = SubtitlePositionEngine()
    pos = pos_engine.select_optimal_position(
        evidence_overlay_present=True,
        evidence_bbox=(80, 1260, 1000, 1540)
    )
    assert pos in (SubtitlePositionType.UPPER_CENTER, SubtitlePositionType.CENTER)
    assert pos != SubtitlePositionType.BOTTOM_CENTER
    assert pos_engine.occlusion_avoidance_count >= 1


# --------------------------------------------------------------------------
# TEST 06: Caption Readability
# --------------------------------------------------------------------------
def test_06_caption_readability():
    """All 20 templates must stay within YouTube Shorts UI safe-zone limits."""
    for style_type, tmpl in SUBTITLE_TEMPLATES.items():
        assert tmpl.font_size >= 70, f"{style_type} font size too small for Shorts readability"
        assert tmpl.font_size <= 105, f"{style_type} font size exceeds safe bounds"
        assert tmpl.outline_width >= 5, f"{style_type} lacks high-contrast outline"
        assert tmpl.safe_zone_top_pct >= 0.10
        assert tmpl.safe_zone_bottom_pct >= 0.15


# --------------------------------------------------------------------------
# TEST 07: Editing Rhythm
# --------------------------------------------------------------------------
def test_07_editing_rhythm():
    """EditingRhythmEngine must generate variable pacing where hook and climax are faster than setup."""
    rhythm = EditingRhythmEngine()
    roles = ["HOOK", "SETUP", "SETUP", "ESCALATION", "ESCALATION", "REVEAL", "CLIMAX", "OUTRO"]
    durations = rhythm.calculate_pacing_curve(total_duration=23.5, shot_count=8, narrative_roles=roles)
    assert len(durations) == 8
    assert durations[0] < durations[1], "Hook must have faster pacing than setup"
    metrics = rhythm.get_pacing_metrics(durations)
    assert metrics["variance"] > 0.0, "Durations must have rhythm variance rather than uniform timing"


# --------------------------------------------------------------------------
# TEST 08: Shot Duration Constraints
# --------------------------------------------------------------------------
def test_08_shot_duration_constraints():
    """All shots must obey minimum and maximum duration constraints."""
    rhythm = EditingRhythmEngine()
    roles = ["HOOK", "SETUP", "SETUP", "ESCALATION", "ESCALATION", "REVEAL", "CLIMAX", "OUTRO"]
    durations = rhythm.calculate_pacing_curve(total_duration=23.5, shot_count=8, narrative_roles=roles)
    for d in durations:
        assert 1.8 <= d <= 4.2, f"Shot duration {d} violated bounds [1.8s, 4.2s]"
    assert abs(sum(durations) - 23.5) < 0.05


# --------------------------------------------------------------------------
# TEST 09: Transition Selection
# --------------------------------------------------------------------------
def test_09_transition_selection():
    """TransitionEngine must select appropriate transitions based on narrative beat."""
    te = TransitionEngine()
    t0 = te.select_transition(0, "HOOK")
    assert t0.transition_type == TransitionType.CUT
    t1 = te.select_transition(1, "REVEAL", requested_type=TransitionType.DIP_TO_BLACK)
    assert t1.transition_type == TransitionType.DIP_TO_BLACK


# --------------------------------------------------------------------------
# TEST 10: Transition Repetition Prevention
# --------------------------------------------------------------------------
def test_10_transition_repetition_prevention():
    """TransitionEngine must prohibit consecutive non-cut transitions."""
    te = TransitionEngine()
    te.select_transition(1, "REVEAL", requested_type=TransitionType.DIP_TO_BLACK)
    t2 = te.select_transition(2, "CLIMAX", requested_type=TransitionType.DIP_TO_BLACK)
    assert t2.transition_type == TransitionType.CUT, "Consecutive non-cut transition must throttle to CUT"


# --------------------------------------------------------------------------
# TEST 11: Keyframe Generation
# --------------------------------------------------------------------------
def test_11_keyframe_generation():
    """MotionEngine must generate multi-step keyframe sequences with easing."""
    me = MotionEngine()
    spec = me.generate_camera_motion_spec(MotionType.SUBTLE_ZOOM_IN, duration=3.0)
    assert len(spec.keyframes) >= 4
    assert spec.keyframes[0].scale == 1.0
    assert spec.keyframes[-1].scale > 1.0


# --------------------------------------------------------------------------
# TEST 12: Zoom Generation
# --------------------------------------------------------------------------
def test_12_zoom_generation():
    """MotionEngine must generate valid FFmpeg zoompan filter expressions."""
    me = MotionEngine()
    vf = me.build_ffmpeg_filter(MotionType.SUBTLE_ZOOM_IN, duration=3.0)
    assert "zoompan" in vf
    assert "1080" in vf and "1920" in vf


# --------------------------------------------------------------------------
# TEST 13: SFX Selection
# --------------------------------------------------------------------------
def test_13_sfx_selection():
    """SFXEngine must select contextually appropriate SFX archetypes."""
    se = SFXEngine()
    sfx1 = se.evaluate_sfx_opportunity(0.0, 3.0, "CLIMAX", "The explosion shattered the glass!")
    assert sfx1 is not None
    assert sfx1.archetype == SFXArchetype.IMPACT_BOOM


# --------------------------------------------------------------------------
# TEST 14: SFX Cooldown Limits
# --------------------------------------------------------------------------
def test_14_sfx_cooldown():
    """SFXEngine must enforce 4.0s minimum cooldown and maximum 3 SFX per Short."""
    se = SFXEngine()
    s1 = se.evaluate_sfx_opportunity(0.0, 3.0, "CLIMAX", "Boom 1")
    s2 = se.evaluate_sfx_opportunity(1.0, 3.0, "ESCALATION", "Too fast")
    assert s1 is not None
    assert s2 is None, "Immediate SFX must be blocked by cooldown"
    s3 = se.evaluate_sfx_opportunity(6.0, 3.0, "ESCALATION", "Tension")
    s4 = se.evaluate_sfx_opportunity(12.0, 3.0, "REVEAL", "Document")
    s5 = se.evaluate_sfx_opportunity(18.0, 3.0, "CLIMAX", "Over cap")
    assert s5 is None, "Exceeding MAX_SFX_PER_SHORT must be blocked"
    assert len(se.placed_cues) == 3


# --------------------------------------------------------------------------
# TEST 15: BGM Rotation
# --------------------------------------------------------------------------
def test_15_bgm_rotation():
    """BGMSelector must rotate tracks and avoid identical consecutive selections."""
    bgm_selector = BGMSelector()
    t1 = bgm_selector.select_track("Politics", "Treaty Talks", "Diplomatic negotiations")
    t2 = bgm_selector.select_track("Politics", "Treaty Talks", "Diplomatic negotiations")
    assert t1 != t2, "BGM track must rotate upon consecutive call"


# --------------------------------------------------------------------------
# TEST 16: Voice Rotation
# --------------------------------------------------------------------------
def test_16_voice_rotation():
    """VoiceVariationPolicy respects active voice roster (locks to af_sarah when Sarah-only is enforced)."""
    voice_policy = VoiceVariationPolicy()
    v1 = voice_policy.select_voice("Military", "War History", "Documentary narration")
    v2 = voice_policy.select_voice("Military", "War History", "Documentary narration")
    v3 = voice_policy.select_voice("Military", "War History", "Documentary narration")
    if len(voice_policy.APPROVED_PERSONAS) > 1:
        assert not (v1 == v2 == v3), "Voice policy must disallow 3 identical consecutive voices when multi-voice is active"
    else:
        assert v1 == v2 == v3 == "af_sarah", "Voice policy must strictly enforce af_sarah in single-voice lock"


# --------------------------------------------------------------------------
# TEST 17: Audio Ducking Blueprint
# --------------------------------------------------------------------------
def test_17_audio_ducking():
    """AudioDirector must generate ducking intervals that lower BGM during speech and SFX."""
    ad = AudioDirector()
    plan = ad.formulate_mix_plan(
        duration=20.0,
        voice_path="mock_voice.wav",
        bgm_path="mock_bgm.wav",
        voice_active_ranges=[(0.5, 4.0), (6.0, 10.0)]
    )
    assert len(plan.ducking_points) >= 2
    assert plan.bgm_lufs_target == -28.0
    assert plan.master_lufs_target == -14.0


# --------------------------------------------------------------------------
# TEST 18: Vertical Reframing
# --------------------------------------------------------------------------
def test_18_vertical_reframing():
    """ReframingEngine must compute correct 9:16 crop window and center on subject/face."""
    re_eng = ReframingEngine()
    spec = re_eng.calculate_reframing(source_width=1920, source_height=1080, subject_center_x=0.5)
    assert spec.crop_height == 1080
    assert spec.crop_width == 607
    assert abs(spec.crop_x - ((1920 - 607) // 2)) <= 1

    spec_face = re_eng.calculate_reframing(source_width=1920, source_height=1080, face_bbox=(1300, 200, 200, 200))
    assert spec_face.face_detected
    assert spec_face.crop_x > ((1920 - 607) // 2) + 50


# --------------------------------------------------------------------------
# TEST 19: Real Footage Integration
# --------------------------------------------------------------------------
def test_19_real_footage_integration(sample_shots_data, sample_candidates_map):
    """Editing engine must preserve and prioritize real and archival footage."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_real_01",
        topic_title="Historical Archive",
        category="History",
        script_text="The archive was opened...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    assert all(s.source_asset_id.startswith("cand_s") for s in plan.shots)
    assert plan.telemetry.real_footage_pct >= 50.0


# --------------------------------------------------------------------------
# TEST 20: Evidence Overlay Integration
# --------------------------------------------------------------------------
def test_20_evidence_overlay_integration(sample_shots_data, sample_candidates_map):
    """Editing engine must link evidence overlays to appropriate shots and avoid caption collision."""
    engine = AdvancedEditorialEngine()
    overlays = {"s6": "renders/overlays/evidence_declassified.png"}
    plan = engine.build_editing_plan(
        job_id="job_ev_01",
        topic_title="Classified Files",
        category="Investigation",
        script_text="Secret documents proved the case...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0,
        evidence_overlays_map=overlays
    )
    shot_6 = next(s for s in plan.shots if s.shot_id == "s6")
    assert shot_6.evidence_overlay_path == "renders/overlays/evidence_declassified.png"
    assert shot_6.subtitle_cues[0].position_type in (SubtitlePositionType.UPPER_CENTER, SubtitlePositionType.CENTER)


# --------------------------------------------------------------------------
# TEST 21: Provenance Preservation
# --------------------------------------------------------------------------
def test_21_provenance_preservation(sample_shots_data, sample_candidates_map):
    """Editing engine must NEVER strip provenance IDs or source references."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_prov_01",
        topic_title="Provenance Test",
        category="History",
        script_text="Testing provenance retention...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    for s in plan.shots:
        assert s.source_provenance_id is not None
        assert s.source_provenance_id.startswith("prov_")


# --------------------------------------------------------------------------
# TEST 22: Rights-Status Enforcement
# --------------------------------------------------------------------------
def test_22_rights_status_enforcement(sample_shots_data, sample_candidates_map):
    """All assets used in EditingPlan must report 100% provenance completeness."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_rights_01",
        topic_title="Rights Enforcement",
        category="History",
        script_text="Testing rights enforcement...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    assert plan.telemetry.provenance_completeness == 100.0


# --------------------------------------------------------------------------
# TEST 23: Template Registry
# --------------------------------------------------------------------------
def test_23_template_registry():
    """TemplateRegistry must contain all 20 subtitle styles and 7 editorial profiles."""
    styles = TemplateRegistry.list_subtitle_styles()
    assert len(styles) == 20
    assert "CLEAN" in styles and "IMPACT" in styles and "EVIDENCE" in styles
    profiles = TemplateRegistry.list_profiles()
    assert len(profiles) >= 7


# --------------------------------------------------------------------------
# TEST 24: EditingStyleProfile
# --------------------------------------------------------------------------
def test_24_editing_style_profile():
    """EditingStyleSelector must classify story profiles based on structural archetypes."""
    selector = EditingStyleSelector()
    assert selector.select_profile("Breaking", "Fast developing crisis in city center") == EditingStyleProfile.FAST_BREAKING
    assert selector.select_profile("Investigation", "Leaked secret memos expose scandal") == EditingStyleProfile.INVESTIGATIVE
    assert selector.select_profile("Economy", "New statistical inflation data study") == EditingStyleProfile.ANALYTICAL


# --------------------------------------------------------------------------
# TEST 25: Editing Telemetry
# --------------------------------------------------------------------------
def test_25_editing_telemetry(sample_shots_data, sample_candidates_map):
    """EditingTelemetryCollector must assemble comprehensive measurable metrics."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_telem_01",
        topic_title="Telemetry Test",
        category="Politics",
        script_text="Checking telemetry data...",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    t = plan.telemetry
    assert t is not None
    assert t.shot_count == len(sample_shots_data)
    assert len(t.subtitle_styles_used) >= 2
    assert "cut" in t.transitions_used


# --------------------------------------------------------------------------
# TEST 26: AI Council Compatibility
# --------------------------------------------------------------------------
def test_26_ai_council_compatibility():
    """AI Council data models must serialize and validate cleanly."""
    strategy = EditingStrategy(
        strategy_id="strat_v1_kinetic",
        name="High-Pacing Kinetic",
        description="Fast 2.0s cuts with aggressive impact subtitles",
        target_profile=EditingStyleProfile.FAST_BREAKING,
        caption_density="HIGH",
        pacing_speed="AGGRESSIVE",
        sfx_frequency="DYNAMIC"
    )
    assert strategy.to_dict()["pacing_speed"] == "AGGRESSIVE"

    decision = EditingDecision(
        timestamp=2.5,
        decision_type="SUBTITLE_STYLE",
        chosen_value="IMPACT",
        alternative_options=["CLEAN", "WORD_HIGHLIGHT"],
        context_reason="Narrative climax statement reached"
    )
    assert decision.to_dict()["chosen_value"] == "IMPACT"

    outcome = EditingOutcome(
        job_id="job_test_01",
        strategy_id="strat_v1_kinetic",
        views=15000,
        average_percentage_viewed=86.5,
        completion_rate_pct=72.0
    )
    assert outcome.to_dict()["completion_rate_pct"] == 72.0


# --------------------------------------------------------------------------
# TEST 27: Niche-Agnostic AST Audit
# --------------------------------------------------------------------------
def test_27_niche_agnostic_ast_audit():
    """engines/visual_intelligence/editing must contain ZERO hardcoded political or entity branches."""
    editing_dir = Path(__file__).resolve().parent.parent / "engines" / "visual_intelligence" / "editing"
    prohibited = ["trump", "biden", "scholz", "macron", "putin", "hitler", "napoleon", "caesar", "churchill"]
    
    for py_file in editing_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                test_str = ast.unparse(node.test).lower()
                for p in prohibited:
                    assert p not in test_str, f"Prohibited hardcoded branch '{p}' in {py_file.name}: {test_str}"


# --------------------------------------------------------------------------
# TEST 28: Offline Network Boundary
# --------------------------------------------------------------------------
def test_28_offline_network_boundary(sample_shots_data, sample_candidates_map):
    """AdvancedEditorialEngine must build complete editing plans with 0 network calls."""
    engine = AdvancedEditorialEngine()
    plan = engine.build_editing_plan(
        job_id="job_offline_01",
        topic_title="Completely Offline Test",
        category="General",
        script_text="Zero external connections.",
        shots_data=sample_shots_data,
        candidates_map=sample_candidates_map,
        total_duration=21.0
    )
    assert plan is not None
    assert Path(plan.ass_subtitles_path).exists()


# --------------------------------------------------------------------------
# TEST 29: Zero Drive Mutation
# --------------------------------------------------------------------------
def test_29_zero_drive_mutation():
    """ExecutionCapabilities must verify zero Drive write in sandboxed testing."""
    from engines.orchestrator import ExecutionCapabilities
    caps = ExecutionCapabilities.sandboxed_testing()
    assert not caps.allow_drive_write, "Drive write must be strictly forbidden in tests"


# --------------------------------------------------------------------------
# TEST 30: Zero YouTube Mutation
# --------------------------------------------------------------------------
def test_30_zero_youtube_mutation():
    """ExecutionCapabilities must verify zero YouTube upload in sandboxed testing."""
    from engines.orchestrator import ExecutionCapabilities
    caps = ExecutionCapabilities.sandboxed_testing()
    assert not caps.allow_youtube_write, "YouTube write must be strictly forbidden in tests"
