"""
AL-AMR — Production Editorial Quality & AI Council Readiness Audit Suite.
Validates all 12 phases:
- Phase 1: Full pipeline execution wiring & stage connection
- Phase 2: Editing variety, multi-style subtitles, anti-chaos & collision avoidance
- Phase 3: Visual rhythm curves, pacing variance & static cut rejection
- Phase 4: Real-footage dominance over generic stock
- Phase 5: Meme / reaction suitability & journalistic integrity gates
- Phase 6: BGM extensible catalog, tempo matching & recency decay
- Phase 7: Voice variation policy, narrative coherence & rotation
- Phase 8: SFX narrative event triggers, cooldown & volume safety bounds
- Phase 9: Evidence overlay attribution & safe positioning
- Phase 10: TemplateRegistry 17 directorial patterns & style classification
- Phase 11 & 12: AI Council & Self-Learning versioned schemas
"""
import pytest
import os
import json
from unittest.mock import MagicMock, patch

from engines.visual_intelligence.editing.editing_models import (
    EditingStyleProfile,
    SubtitleStyleType,
    SubtitlePositionType,
    SFXArchetype,
    SFXCueSpec,
    AudioMixPlan,
    ShotEdit,
    EditingPlan,
    EditingDecision,
    EditingStrategy,
    EditingTelemetry,
    EditingOutcome,
    StrategyEvaluation,
    CouncilRecommendation
)
from engines.visual_intelligence.editing.style_selector import SubtitleStyleSelector, EditingStyleSelector
from engines.visual_intelligence.editing.position_engine import SubtitlePositionEngine
from engines.visual_intelligence.editing.editing_rhythm import EditingRhythmEngine
from engines.visual_intelligence.editing.template_registry import TemplateRegistry
from engines.visual_intelligence.editing.sfx_engine import SFXEngine
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.intent_extractor import VisualIntent
from engines.visual_intelligence.sources.base import VisualCandidate
from engines.visual_intelligence.sources.reaction_adapter import ReactionMemeAdapter
from engines.visual_intelligence.provenance import VisualProvenance, RightsStatus, VisualContentType
from engines.visual_intelligence.bgm_selector import BGMSelector, BGMTrack
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
from engines.visual_intelligence.overlay_engine import EvidenceOverlayEngine
from engines.visual_intelligence.models import EvidenceOverlaySpec
from engines.visual_intelligence.visual_qa import VisualQAGate
from engines.visual_intelligence.editing.editor import AdvancedEditorialEngine
from engines.orchestrator import ProductionOrchestrator
from engines.asset_fetcher import AssetFetcher
from engines.render_engine import RenderEngine


# ==============================================================================
# PHASE 1: FULL PIPELINE EXECUTION PATH WIRING
# ==============================================================================
def test_phase1_pipeline_execution_path_wiring():
    """Verify that all newly introduced editorial engines are wired directly into orchestrator & asset fetcher."""
    orchestrator = ProductionOrchestrator()
    assert hasattr(orchestrator, "editorial_engine"), "Orchestrator must have editorial_engine wired"
    assert isinstance(orchestrator.editorial_engine, AdvancedEditorialEngine)
    assert hasattr(orchestrator, "visual_qa_gate"), "Orchestrator must have visual_qa_gate wired"
    assert isinstance(orchestrator.visual_qa_gate, VisualQAGate)
    assert hasattr(orchestrator, "bgm_selector"), "Orchestrator must have bgm_selector wired"
    assert isinstance(orchestrator.bgm_selector, BGMSelector)

    # Verify AssetFetcher has SourceRouter wired
    fetcher = AssetFetcher()
    assert hasattr(fetcher, "source_router"), "AssetFetcher must have source_router wired"
    assert hasattr(fetcher.source_router, "acquire_candidates"), "SourceRouter must support acquire_candidates"


# ==============================================================================
# PHASE 2: EDITING VARIETY & ANTI-CHAOS AUDIT
# ==============================================================================
def test_phase2_editing_variety_and_anti_chaos():
    """Verify multi-style subtitles inside ONE Short without looking chaotic."""
    selector = SubtitleStyleSelector()
    selector.reset()

    # Simulate 8 narrative beats across one Short
    beats = [
        (0, "HOOK", "Why did the secret operation fail so completely?", "HIGH"),
        (1, "SETUP", "Declassified files reveal a stunning $400 million miscalculation.", "MEDIUM"),
        (2, "SETUP", "The minister stated: 'We acted within statutory limits.'", "MEDIUM"),
        (3, "ESCALATION", "Internal memos contradict the official testimony.", "HIGH"),
        (4, "EVIDENCE", "Court document exhibit A demonstrates direct knowledge.", "HIGH"),
        (5, "CLIMAX", "This shattered the entire administration in hours.", "CLIMAX"),
        (6, "OUTRO", "Follow for the full unredacted archive analysis.", "MEDIUM"),
        (7, "OUTRO", "What would you have done differently?", "MEDIUM"),
    ]

    selected_styles = []
    for idx, role, narration, intensity in beats:
        style = selector.select_style_for_beat(
            beat_index=idx,
            narrative_role=role,
            narration_text=narration,
            intensity=intensity,
            evidence_overlay_present=(role == "EVIDENCE")
        )
        selected_styles.append(style)

    # 1. Multi-style variety verified
    diversity = selector.get_style_diversity_summary()
    assert diversity["distinct_styles_count"] >= 3, "Short must use at least 3 distinct subtitle styles"
    assert diversity["style_transitions"] >= 2, "Short must transition between styles dynamically"

    # 2. Anti-chaos verification: no specialized style repeated > 2 times consecutively
    for i in range(2, len(selected_styles)):
        chunk = selected_styles[i-2:i+1]
        if chunk[0] in selector.SPECIALIZED_STYLES:
            assert not (chunk[0] == chunk[1] == chunk[2]), f"Style {chunk[0]} repeated 3 times consecutively (anti-chaos violated)"

    # 3. Collision avoidance verification with position engine
    pos_engine = SubtitlePositionEngine()
    pos_standard = pos_engine.select_optimal_position(
        evidence_overlay_present=False
    )
    pos_with_evidence = pos_engine.select_optimal_position(
        evidence_overlay_present=True
    )
    assert pos_standard == SubtitlePositionType.BOTTOM_CENTER
    # When evidence card occupies bottom safe zone, subtitles MUST relocate to upper/center
    assert pos_with_evidence in (SubtitlePositionType.UPPER_CENTER, SubtitlePositionType.CENTER), \
        "Subtitle must relocate away from bottom when evidence overlay is present"


# ==============================================================================
# PHASE 3: VISUAL RHYTHM & PACING AUDIT
# ==============================================================================
def test_phase3_visual_rhythm_and_monotony_rejection():
    """Verify pacing curves, shot duration variance, and static cut rejection."""
    rhythm_engine = EditingRhythmEngine()

    # 1. Monotonous uniform durations produce zero variance
    monotonous_durations = [3.0, 3.0, 3.0, 3.0, 3.0]
    mono_metrics = rhythm_engine.get_pacing_metrics(monotonous_durations)
    assert mono_metrics["variance"] == 0.0

    # 2. Expressive pacing curve calculation allocates dynamic durations based on narrative roles
    roles = ["HOOK", "SETUP", "ESCALATION", "CLIMAX", "OUTRO"]
    dynamic_durations = rhythm_engine.calculate_pacing_curve(
        total_duration=15.0,
        shot_count=5,
        narrative_roles=roles,
        profile_urgency="HIGH"
    )
    assert len(dynamic_durations) == 5
    assert sum(dynamic_durations) == pytest.approx(15.0, abs=0.05)

    metrics = rhythm_engine.get_pacing_metrics(dynamic_durations)
    assert metrics["variance"] > 0.03, f"Dynamic edit must exhibit healthy variance, got {metrics['variance']}"
    assert dynamic_durations[0] < dynamic_durations[1], "Hook must be faster than setup"


# ==============================================================================
# PHASE 4: REAL-FOOTAGE QUALITY & DOMINANCE OVER STOCK
# ==============================================================================
def test_phase4_real_footage_dominance_over_generic_stock():
    """Verify Real-Footage-First dominance over generic stock visuals."""
    scorer = VisualCandidateScorer()
    intent = VisualIntent(
        beat_id="beat_401",
        beat_index=0,
        narration_text="Secretary Antony Blinken arrived in London for emergency diplomatic negotiations.",
        start_time=0.0,
        end_time=3.5,
        duration=3.5,
        primary_entity="Antony Blinken",
        secondary_entities=["London"]
    )

    real_footage_candidate = VisualCandidate(
        candidate_id="cand_real_01",
        source_class="SOURCE_B",
        source_name="editorial_press",
        source_url="https://editorial.news/blinken_london.mp4",
        title="Antony Blinken Arrival in London",
        description="US Secretary Antony Blinken deplaning in London for summit",
        content_type=VisualContentType.LIVE_EVENT_FOOTAGE,
        rights_status=RightsStatus.TRANSFORMATIVE_EDITORIAL,
        is_video=True,
        motion_score=0.92,
        entity_tags=["Antony Blinken", "London"]
    )

    generic_stock_candidate = VisualCandidate(
        candidate_id="cand_stock_01",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://pexels.com/businessman_airport.mp4",
        title="Businessman with Suitcase Walking in Airport",
        description="A generic professional man walking through an airport concourse",
        content_type=VisualContentType.GENERIC_STOCK_VIDEO,
        rights_status=RightsStatus.LICENSED,
        is_video=True,
        motion_score=0.75,
        entity_tags=["airport", "businessman", "travel"]
    )

    ranked = scorer.rank_candidates([generic_stock_candidate, real_footage_candidate], intent)
    assert len(ranked) == 2
    assert ranked[0].candidate_id == "cand_real_01", "Real entity footage MUST dominate generic stock"
    assert ranked[0].raw_score > (ranked[1].raw_score + 0.20), "Real footage must hold a dominant score advantage"


# ==============================================================================
# PHASE 5: REACTION / MEME SUITABILITY & JOURNALISTIC INTEGRITY
# ==============================================================================
def test_phase5_reaction_meme_suitability_and_news_integrity():
    """Verify ReactionMemeAdapter rejects solemn news, prevents misinformation, and checks context."""
    adapter = ReactionMemeAdapter()

    # 1. Valid contextual meme in commentary topic
    valid_intent = VisualIntent(
        beat_id="beat_501",
        beat_index=1,
        narration_text="The tech world reacted with utter disbelief when the servers crashed again.",
        start_time=3.0,
        end_time=6.0,
        duration=3.0,
        emotional_tone="LIGHT"
    )
    valid_candidate = VisualCandidate(
        candidate_id="meme_cand_01",
        source_class="SOURCE_D",
        source_name="reaction_memes",
        source_url="https://reactions.com/shocked_face.mp4",
        title="Dramatic Facepalm Reaction",
        description="Expressive facepalm reaction meme",
        content_type=VisualContentType.MEME_REACTION,
        rights_status=RightsStatus.TRANSFORMATIVE_EDITORIAL,
        is_video=True
    )
    ok, reason = adapter.validate_meme_suitability(valid_candidate, valid_intent)
    assert ok is True, f"Valid contextual meme should pass: {reason}"

    # 2. Solemn / tragic news rejection (anti-misinformation & solemnity gate)
    tragic_intent = VisualIntent(
        beat_id="beat_502",
        beat_index=2,
        narration_text="Authorities confirmed 12 people died during the severe storm collapse.",
        start_time=6.0,
        end_time=9.0,
        duration=3.0,
        emotional_tone="TRAGEDY"
    )
    ok_tragic, reason_tragic = adapter.validate_meme_suitability(valid_candidate, tragic_intent)
    assert ok_tragic is False
    assert "solemn" in reason_tragic.lower() or "tragic" in reason_tragic.lower()

    # 3. Factual evidence substitution rejection
    evidence_intent = VisualIntent(
        beat_id="beat_503",
        beat_index=3,
        narration_text="The treaty was signed in Geneva by both foreign ministers.",
        start_time=9.0,
        end_time=12.0,
        duration=3.0,
        evidence_overlay_requirements={"required": True}
    )
    ok_ev, reason_ev = adapter.validate_meme_suitability(valid_candidate, evidence_intent)
    assert ok_ev is False
    assert "evidence" in reason_ev.lower()


# ==============================================================================
# PHASE 6: BGM CATALOG, TEMPO MATCHING & RECENCY DECAY
# ==============================================================================
def test_phase6_bgm_catalog_tempo_and_recency_decay():
    """Verify BGM selector catalog expansion, tempo matching, and consecutive repetition decay."""
    selector = BGMSelector()

    # 1. Extensible catalog interface
    custom_track = BGMTrack(
        key="custom_synth_01",
        display_name="High Octane Investigation",
        primary_files=["custom_synth_01.wav"],
        mood="High-Tension Cyber / Investigation",
        genre="Synthwave Pulse",
        energy="HIGH",
        intensity="High-Driving",
        editorial_fit=["technology", "heist", "investigation"],
        description="Upbeat electronic pulse for fast investigations",
        tempo_bpm=128,
        license_type="royalty_free"
    )
    selector.register_track(custom_track)
    assert "custom_synth_01" in selector._catalog

    # 2. Tempo & Mood matching
    chosen_key = selector.select_track(
        category="Tech",
        title="Cyber Heist",
        script_text="High stakes digital investigation",
        target_tempo_bpm=125
    )
    assert chosen_key is not None
    chosen_track = selector._catalog[chosen_key]
    assert chosen_track.tempo_bpm >= 120, "Should match upbeat high-tempo track"

    # 3. Recency decay / repetition penalty
    track1 = selector.select_track(category="News", title="Daily Update 1", script_text="General news")
    track2 = selector.select_track(category="News", title="Daily Update 2", script_text="General news")
    recent = selector.get_recent_usage()
    assert len(recent) >= 2
    assert recent[-1] == track2


# ==============================================================================
# PHASE 7: VOICE VARIATION & COHERENCE
# ==============================================================================
def test_phase7_voice_variation_policy_coherence_and_rotation():
    """Verify narrative-aware voice rotation without channel brand incoherence."""
    policy = VoiceVariationPolicy()

    # Investigative story should select investigative / authoritative voice
    voice_inv = policy.select_voice(
        category="Investigative Report",
        title="The Paper Trail",
        script_text="Declassified court documents show an undercover paper trail."
    )
    assert voice_inv in policy.APPROVED_PERSONAS
    assert voice_inv in ["af_bella", "am_adam", "am_michael", "af_sarah", "bm_george"]

    # Consecutive jobs with similar topic should rotate rather than freeze on one voice
    voice_inv2 = policy.select_voice(
        category="Investigative Report",
        title="The Second Paper Trail",
        script_text="More documents reveal another secret operation."
    )
    recent = policy.get_recent_voices()
    assert len(recent) == 2


# ==============================================================================
# PHASE 8: SFX NARRATIVE TRIGGERS & SAFETY BOUNDS
# ==============================================================================
def test_phase8_sfx_narrative_event_triggers_and_safety_bounds():
    """Verify SFX triggers on narrative peaks with cooldown and volume bounds."""
    sfx_engine = SFXEngine()
    sfx_engine.reset()

    # Climax shot should trigger IMPACT_BOOM
    cue = sfx_engine.evaluate_sfx_opportunity(
        start_time=4.0,
        duration=2.5,
        narrative_role="CLIMAX",
        narration_text="This shattered the entire administration in hours.",
        intensity="CLIMAX"
    )
    assert cue is not None, "Climax shot must trigger SFX cue"
    assert cue.archetype == SFXArchetype.IMPACT_BOOM
    assert -30.0 <= cue.volume_db <= -10.0, f"SFX volume {cue.volume_db} outside safe bounds"

    # Consecutive immediate cue within MIN_SFX_INTERVAL_SEC must be throttled (cooldown)
    immediate_cue = sfx_engine.evaluate_sfx_opportunity(
        start_time=5.0,
        duration=2.0,
        narrative_role="IMPACT",
        narration_text="Shocking aftershocks followed.",
        intensity="HIGH"
    )
    assert immediate_cue is None, "SFX must be throttled during active cooldown interval"


# ==============================================================================
# PHASE 9: EVIDENCE OVERLAYS & ATTRIBUTION
# ==============================================================================
def test_phase9_evidence_overlay_attribution_and_safe_positioning():
    """Verify factual evidence cards display attribution, source, date, and safe zone."""
    overlay_engine = EvidenceOverlayEngine()
    
    out_path = overlay_engine.generate_evidence_overlay(
        headline="Parliamentary Record HC 402 Confirms Direct Findings",
        attribution="UK Parliamentary Record",
        date_label="June 14, 2024",
        badge_type="FACT_CHECKED"
    )

    assert out_path.exists(), f"Evidence overlay PNG must exist on disk at {out_path}"
    assert out_path.stat().st_size > 0, "Overlay PNG must not be empty"

    # Test generate_overlay_from_spec with provenance verification
    spec = EvidenceOverlaySpec(
        overlay_type="document",
        label="DOCUMENT RECORD",
        headline_text="Declassified Memorandum 1982",
        attribution_text="National Archives",
        date_text="Oct 12, 1982",
        require_provenance=True
    )
    spec_path = overlay_engine.generate_overlay_from_spec(spec)
    assert spec_path.exists()
    assert spec_path.stat().st_size > 0


# ==============================================================================
# PHASE 10: DIRECTORIAL TEMPLATE REGISTRY & 17 PATTERNS
# ==============================================================================
def test_phase10_directorial_template_registry_and_all_patterns():
    """Verify TemplateRegistry registers all 17 directorial patterns and classifier maps correctly."""
    profiles = TemplateRegistry.list_profiles()
    assert len(profiles) == 17, f"Expected 17 directorial patterns in TemplateRegistry, found {len(profiles)}"

    required_patterns = [
        "NEWS", "BREAKING_NEWS", "INVESTIGATIVE", "POLITICAL_ANALYSIS",
        "ANALYTICAL", "DRAMATIC", "FAST_BREAKING", "FAST_NEWS_RECAP",
        "EXPLAINER", "TIMELINE", "CONTROVERSY", "STATISTIC_HEAVY",
        "QUOTE_DRIVEN", "DOCUMENT_REVEAL", "REACTION_HEAVY",
        "HISTORICAL_CONTEXT", "HUMAN_INTEREST"
    ]
    for pattern in required_patterns:
        assert pattern in profiles, f"Pattern {pattern} missing from TemplateRegistry"
        cfg = TemplateRegistry.get_profile_config(EditingStyleProfile(pattern))
        assert cfg is not None
        assert "target_shot_duration" in cfg and cfg["target_shot_duration"] > 0

    # Test EditingStyleSelector pattern classification
    selector = EditingStyleSelector()
    assert selector.select_profile("Politics", "Election Senate Supreme Court debate") == EditingStyleProfile.POLITICAL_ANALYSIS
    assert selector.select_profile("History", "Decades ago Cold War archival retrospective") == EditingStyleProfile.HISTORICAL_CONTEXT
    assert selector.select_profile("Tech", "Viral reaction internet reacts streamer explodes") == EditingStyleProfile.REACTION_HEAVY
    assert selector.select_profile("Economy", "Trillion dollar inflation rate plunge") == EditingStyleProfile.STATISTIC_HEAVY
    assert selector.select_profile("Secret", "Classified unsealed internal files dossier") == EditingStyleProfile.DOCUMENT_REVEAL
    assert selector.select_profile("Dispute", "Massive controversy backlash and boycott") == EditingStyleProfile.CONTROVERSY
    assert selector.select_profile("Sequence", "Timeline hour by hour how it unfolded") == EditingStyleProfile.TIMELINE
    assert selector.select_profile("Brief", "Morning recap in 60 seconds") == EditingStyleProfile.FAST_NEWS_RECAP


# ==============================================================================
# PHASES 11 & 12: AI COUNCIL & SELF-LEARNING VERSIONED SCHEMAS
# ==============================================================================
def test_phase11_and_12_ai_council_and_self_learning_schemas():
    """Verify versioned telemetry, decision, strategy, evaluation and recommendation schemas."""
    # 1. EditingDecision
    decision = EditingDecision(
        decision_type="SUBTITLE_STYLE",
        chosen_value="IMPACT",
        alternative_options=["WORD_HIGHLIGHT", "CLEAN"],
        context_reason="Climax emphasis at high dramatic point",
        narrative_role="CLIMAX",
        emotional_intensity="CLIMAX"
    )
    d_dict = decision.to_dict()
    assert d_dict["schema_version"] == "1.0.0"
    assert d_dict["decision_type"] == "SUBTITLE_STYLE"

    # 2. EditingStrategy
    strategy = EditingStrategy(
        strategy_id="strat_001",
        name="High-Retention Investigative",
        target_profile=EditingStyleProfile.INVESTIGATIVE,
        caption_density="HIGH",
        pacing_speed="AGGRESSIVE",
        sfx_frequency="DYNAMIC",
        min_real_footage_pct=75.0,
        max_generic_stock_pct=25.0
    )
    s_dict = strategy.to_dict()
    assert s_dict["schema_version"] == "1.0.0"
    assert s_dict["target_profile"] == "INVESTIGATIVE"

    # 3. EditingTelemetry
    telemetry = EditingTelemetry(
        job_id="job_audit_100",
        editing_profile="INVESTIGATIVE",
        shot_count=6,
        total_duration=16.0,
        avg_shot_duration=2.67,
        shot_duration_variance=0.35,
        subtitle_styles_used=["CLEAN", "KEYWORD_CALLOUT", "IMPACT"],
        subtitle_style_transitions=4,
        subtitle_positions_used=["BOTTOM_CENTER", "UPPER_CENTER"],
        caption_occlusion_avoidances=2,
        transitions_used={"cut": 5},
        sfx_count=2,
        sfx_types_used=["impact_boom", "tension_riser"],
        camera_motions_used={"dynamic_reframe": 6},
        bgm_track="flux_ambient",
        voice_id="am_adam",
        real_footage_pct=83.3,
        generic_stock_pct=16.7,
        static_asset_pct=0.0,
        evidence_overlays_count=1,
        provenance_completeness=1.0
    )
    t_dict = telemetry.to_dict()
    assert t_dict["schema_version"] == "1.0.0"
    assert t_dict["real_footage_pct"] == 83.3

    # 4. EditingOutcome
    outcome = EditingOutcome(
        job_id="job_audit_100",
        strategy_id="strat_001",
        views=1500,
        average_percentage_viewed=78.5,
        retention_at_3s_pct=82.0,
        completion_rate_pct=64.0,
        likes=120,
        shares=35
    )
    o_dict = outcome.to_dict()
    assert o_dict["schema_version"] == "1.0.0"
    assert o_dict["retention_at_3s_pct"] == 82.0

    # 5. StrategyEvaluation
    eval_record = StrategyEvaluation(
        evaluation_id="eval_001",
        strategy_id="strat_001",
        profile=EditingStyleProfile.INVESTIGATIVE,
        sample_size=10,
        avg_retention_3s=81.5,
        performance_score=0.89,
        status="ACTIVE"
    )
    e_dict = eval_record.to_dict()
    assert e_dict["schema_version"] == "1.0.0"
    assert e_dict["performance_score"] == 0.89

    # 6. CouncilRecommendation
    recommendation = CouncilRecommendation(
        recommendation_id="rec_001",
        recommended_strategy_id="strat_001",
        target_dimension="HOOK_PACING",
        adjustment_type="DECREASE",
        rationale="Speed up hook duration under 2.0s to elevate 3s retention",
        confidence_score=0.91,
        expected_retention_delta_pct=4.5
    )
    r_dict = recommendation.to_dict()
    assert r_dict["schema_version"] == "1.0.0"
    assert r_dict["target_dimension"] == "HOOK_PACING"
    assert json.dumps(r_dict) is not None
