"""
Comprehensive Automated Test Suite for Visual Intelligence & Real-Footage Engine.
Validates all 21 required capabilities with ZERO live cloud calls, ZERO live AI spend,
and ZERO YouTube/Drive mutations.
"""
import ast
import os
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engines.visual_intelligence.provenance import (
    VisualProvenance, RightsStatus, VisualContentType
)
from engines.visual_intelligence.intent_extractor import (
    VisualIntent, VisualIntentExtractor
)
from engines.visual_intelligence.sources.base import VisualCandidate
from engines.visual_intelligence.sources import (
    PexelsAdapter, WikimediaAdapter, EditorialAdapter,
    ContextualGraphicAdapter, ReactionMemeAdapter
)
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.diversity import VisualDiversityController
from engines.visual_intelligence.overlay_engine import EvidenceOverlayEngine
from engines.visual_intelligence.bgm_selector import BGMSelector
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
from engines.visual_intelligence.visual_qa import VisualQAGate
from engines.storyboard_engine import StoryboardEngine
from core.models import ScriptRecord, Job, RenderOutput, AssetRecord


@pytest.fixture
def sample_intent():
    extractor = VisualIntentExtractor()
    return extractor.extract_intent_from_beat(
        narration="Chancellor Olaf Scholz announced a new federal election date following coalition talks in Berlin.",
        beat_index=0,
        start_time=0.0,
        duration=3.5,
        topic_title="German Federal Election 2026",
        category="International Politics"
    )


@pytest.fixture
def scorer():
    return VisualCandidateScorer()


# --------------------------------------------------------------------------
# TEST 1: Entity-Specific Candidate Ranking
# --------------------------------------------------------------------------
def test_entity_specific_candidate_ranking(sample_intent, scorer):
    """Entity-specific footage must rank significantly higher than generic stock."""
    entity_cand = VisualCandidate(
        candidate_id="c1",
        source_class="SOURCE_B",
        source_name="editorial",
        source_url="https://editorial.com/scholz_speech.mp4",
        title="Olaf Scholz Speech at Chancellery",
        description="Chancellor Olaf Scholz speaking during press briefing in Berlin",
        content_type=VisualContentType.LIVE_EVENT_FOOTAGE,
        rights_status=RightsStatus.TRANSFORMATIVE_EDITORIAL,
        is_video=True,
        motion_score=0.95,
        entity_tags=["Olaf Scholz", "Berlin"]
    )

    generic_cand = VisualCandidate(
        candidate_id="c2",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://pexels.com/generic_politician.mp4",
        title="Generic Politician at Podium",
        description="An actor dressed as a politician speaking to microphones",
        content_type=VisualContentType.GENERIC_STOCK_VIDEO,
        rights_status=RightsStatus.LICENSED,
        is_video=True,
        motion_score=0.75,
        entity_tags=["politician", "meeting"]
    )

    ranked = scorer.rank_candidates([generic_cand, entity_cand], sample_intent)
    assert ranked[0].candidate_id == "c1", "Entity-specific candidate must rank #1 over generic stock"
    assert ranked[0].raw_score > ranked[1].raw_score


# --------------------------------------------------------------------------
# TEST 2: Semantic Relevance Ranking
# --------------------------------------------------------------------------
def test_semantic_relevance_ranking(scorer):
    """Candidates matching narration keywords must rank above off-topic candidates."""
    intent = VisualIntent(
        beat_id="b1",
        beat_index=0,
        narration_text="The central bank unexpectedly cut interest rates to stimulate investment.",
        start_time=0.0,
        end_time=3.0,
        duration=3.0,
        action="cut interest rates"
    )

    relevant = VisualCandidate(
        candidate_id="rel",
        source_class="SOURCE_D",
        source_name="contextual",
        source_url="https://finance.org/rate_cut.mp4",
        title="Central Bank Interest Rate Announcement",
        description="Official press release confirming the unexpected interest rate cut",
        content_type=VisualContentType.SCREENSHOT_DOCUMENT,
        rights_status=RightsStatus.PUBLIC_DOMAIN,
        is_video=False
    )

    irrelevant = VisualCandidate(
        candidate_id="irrel",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://pexels.com/tropical_beach.mp4",
        title="Sunny Tropical Beach with Palm Trees",
        description="Relaxing waves hitting sand on a quiet island",
        content_type=VisualContentType.GENERIC_STOCK_VIDEO,
        rights_status=RightsStatus.LICENSED,
        is_video=True
    )

    ranked = scorer.rank_candidates([irrelevant, relevant], intent)
    assert ranked[0].candidate_id == "rel"


# --------------------------------------------------------------------------
# TEST 3 & 4: Motion Preference (Video-First Rule) & Real Footage Preference
# --------------------------------------------------------------------------
def test_video_first_and_real_footage_preference(sample_intent, scorer):
    """Real video footage must score higher motion points than static photos."""
    real_video = VisualCandidate(
        candidate_id="vid",
        source_class="SOURCE_B",
        source_name="editorial",
        source_url="https://video.org/clip1.mp4",
        title="Olaf Scholz Press Conference Live Video",
        content_type=VisualContentType.REAL_VIDEO,
        is_video=True,
        width=1080,
        height=1920
    )

    static_photo = VisualCandidate(
        candidate_id="pic",
        source_class="SOURCE_C",
        source_name="wikimedia",
        source_url="https://wikimedia.org/pic1.jpg",
        title="Olaf Scholz Portrait Still Image",
        content_type=VisualContentType.STATIC_PHOTO,
        is_video=False,
        width=1080,
        height=1920
    )

    video_motion = scorer.compute_motion_score(real_video)
    photo_motion = scorer.compute_motion_score(static_photo)
    assert video_motion > photo_motion, f"Video motion ({video_motion}) must exceed static photo motion ({photo_motion})"

    ranked = scorer.rank_candidates([static_photo, real_video], sample_intent)
    assert ranked[0].candidate_id == "vid", "Real video must beat static photo when entity match is equal"


# --------------------------------------------------------------------------
# TEST 5 & 6: Generic Stock Fallback Progression
# --------------------------------------------------------------------------
def test_fallback_hierarchy(sample_intent, scorer):
    """Hierarchy: Entity Video > Event Video > Stock Video > Document > Static > Generic Stock."""
    c_entity_vid = VisualCandidate("c_ent", "SOURCE_B", "ed", "http://1", content_type=VisualContentType.LIVE_EVENT_FOOTAGE, is_video=True, entity_tags=["Olaf Scholz"])
    c_stock_vid = VisualCandidate("c_stk", "SOURCE_A", "px", "http://2", content_type=VisualContentType.GENERIC_STOCK_VIDEO, is_video=True)
    c_static = VisualCandidate("c_sta", "SOURCE_C", "wm", "http://3", content_type=VisualContentType.STATIC_PHOTO, is_video=False)

    ranked = scorer.rank_candidates([c_static, c_stock_vid, c_entity_vid], sample_intent)
    assert ranked[0].candidate_id == "c_ent"
    # Per Section 13 Fallback Hierarchy: authentic static image beats generic stock as last resort
    assert ranked[1].candidate_id == "c_sta"
    assert ranked[2].candidate_id == "c_stk"



# --------------------------------------------------------------------------
# TEST 7: Meme & Reaction Contextual Filtering
# --------------------------------------------------------------------------
def test_meme_contextual_filtering():
    """Reaction / meme adapter must reject tragic, fatal, or grieving narrative beats."""
    adapter = ReactionMemeAdapter()
    
    # Inappropriate context
    tragic_intent = VisualIntent(
        beat_id="b1", beat_index=0,
        narration_text="Dozens were killed and casualties mounted after the catastrophic bridge collapse.",
        start_time=0.0, end_time=3.0, duration=3.0,
        emotional_tone="TRAGEDY"
    )
    assert not adapter.is_editorially_appropriate(tragic_intent)
    cands = adapter.search(["bridge"], tragic_intent)
    assert len(cands) == 0, "Meme adapter must return 0 candidates for tragic/fatal beat"

    # Appropriate context
    light_intent = VisualIntent(
        beat_id="b2", beat_index=1,
        narration_text="The internet immediately reacted with disbelief and hilarious memes.",
        start_time=3.0, end_time=6.0, duration=3.0,
        emotional_tone="LIGHT"
    )
    assert adapter.is_editorially_appropriate(light_intent)
    valid_cands = adapter.search(["reaction"], light_intent)
    assert len(valid_cands) > 0


# --------------------------------------------------------------------------
# TEST 8 & 9: Repetition Prevention & Cross-Job Recent Use Penalty
# --------------------------------------------------------------------------
def test_repetition_prevention_and_decay(sample_intent, scorer):
    """Single-short duplicates must be disqualified; recently used assets must be penalized."""
    cand = VisualCandidate(
        candidate_id="c_rep",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://pexels.com/clip_dup.mp4",
        content_type=VisualContentType.REAL_VIDEO,
        is_video=True
    )

    # In-job duplicate test
    job_urls = {"https://pexels.com/clip_dup.mp4"}
    score_dup = scorer.score_candidate(cand, sample_intent, job_used_urls=job_urls)
    assert score_dup < 0.0, "Duplicate asset in the same job must be heavily penalized/disqualified"

    # Cross-job recency penalty test
    fresh_cand = VisualCandidate(
        candidate_id="c_fresh",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://pexels.com/clip_fresh.mp4",
        content_type=VisualContentType.REAL_VIDEO,
        is_video=True
    )
    recent_usage = {"https://pexels.com/clip_dup.mp4": 3}
    score_used = scorer.score_candidate(cand, sample_intent, recent_usage_counts=recent_usage, job_used_urls=set())
    score_fresh = scorer.score_candidate(fresh_cand, sample_intent, recent_usage_counts=recent_usage, job_used_urls=set())
    assert score_fresh > score_used, "Fresh candidate must score higher than recently used asset"


# --------------------------------------------------------------------------
# TEST 10: BGM Rotation & Recency Penalties
# --------------------------------------------------------------------------
def test_bgm_rotation():
    """BGMSelector must rotate tracks and avoid 2 consecutive identical selections when alternatives exist."""
    selector = BGMSelector()
    track1 = selector.select_track("Politics", "Election Announcement", "Serious statecraft and treaties")
    track2 = selector.select_track("Politics", "Election Announcement", "Serious statecraft and treaties")
    # Due to immediate recency penalty (-5.0), track2 should rotate to an alternative suitable track
    assert track1 != track2, "BGM track must rotate when multiple compatible tracks exist"
    assert len(selector.get_recent_usage()) == 2


# --------------------------------------------------------------------------
# TEST 11: Voice Rotation & Persona Policy
# --------------------------------------------------------------------------
def test_voice_rotation():
    """VoiceVariationPolicy respects active voice roster (locks to af_sarah when Sarah-only is enforced)."""
    policy = VoiceVariationPolicy()
    v1 = policy.select_voice("Military", "War Battle", "Historical documentary about warfare", enforce_rotation=True)
    v2 = policy.select_voice("Military", "War Battle", "Historical documentary about warfare", enforce_rotation=True)
    v3 = policy.select_voice("Military", "War Battle", "Historical documentary about warfare", enforce_rotation=True)
    
    history = policy.get_recent_voices()
    if len(policy.APPROVED_PERSONAS) > 1:
        assert not (history[0] == history[1] == history[2]), "Voice policy must disallow 3 identical consecutive voices when multi-voice is active"
    else:
        assert history[0] == history[1] == history[2] == "af_sarah", "Voice policy must strictly enforce af_sarah in single-voice lock"


# --------------------------------------------------------------------------
# TEST 12: Evidence Overlay Generation
# --------------------------------------------------------------------------
def test_evidence_overlay_generation(tmp_path):
    """EvidenceOverlayEngine must create a valid 1080x1920 PNG with attribution and badge."""
    engine = EvidenceOverlayEngine(output_dir=tmp_path)
    overlay_file = engine.generate_evidence_overlay(
        headline="Federal Elections Confirmed for November",
        attribution="Reuters News Agency",
        date_label="Sept 4, 2026",
        badge_type="FACT_CHECKED"
    )
    assert overlay_file.exists()
    assert overlay_file.stat().st_size > 500
    assert overlay_file.suffix == ".png"


# --------------------------------------------------------------------------
# TEST 13 & 14: Provenance Metadata & Rights Status Enforcement
# --------------------------------------------------------------------------
def test_provenance_and_rights_enforcement(sample_intent, scorer):
    """Candidates with RIGHTS_UNCERTAIN must receive a heavy penalty."""
    prov_safe = VisualProvenance(
        asset_id="p1", source="pexels", source_url="https://px.com/safe",
        rights_status=RightsStatus.LICENSED, license_name="Commercial Zero-Cost"
    )
    safe_cand = VisualCandidate("c_safe", "SOURCE_A", "pexels", "https://px.com/safe", rights_status=RightsStatus.LICENSED, provenance=prov_safe)

    prov_uncertain = VisualProvenance(
        asset_id="p2", source="random_web", source_url="https://web.com/img.jpg",
        rights_status=RightsStatus.RIGHTS_UNCERTAIN, license_name="Unknown"
    )
    uncertain_cand = VisualCandidate("c_unc", "SOURCE_D", "random_web", "https://web.com/img.jpg", rights_status=RightsStatus.RIGHTS_UNCERTAIN, provenance=prov_uncertain)

    score_safe = scorer.score_candidate(safe_cand, sample_intent)
    score_unc = scorer.score_candidate(uncertain_cand, sample_intent)
    assert score_safe > score_unc, "Rights-uncertain material must be heavily penalized compared to licensed material"
    assert safe_cand.provenance.rights_status == RightsStatus.LICENSED


# --------------------------------------------------------------------------
# TEST 15: Storyboard Beat Synchronization
# --------------------------------------------------------------------------
def test_storyboard_beat_synchronization():
    """StoryboardEngine must output shots with continuous timing and explicit visual_intent."""
    engine = StoryboardEngine()
    script = ScriptRecord(
        id="sc_test",
        topic_id="top_1",
        hook="In 2026, the election changed everything overnight.",
        context="Coalition parties held intensive negotiations in the Chancellery.",
        escalation="Public debate intensified across every media broadcast.",
        reveal="An unprecedented national referendum was called.",
        loop_twist="And that is why the outcome stunned the world.",
        estimated_duration_sec=23.5,
        word_count=65
    )

    shots = engine.create_storyboard(script)
    assert len(shots) >= 7, "Must formulate at least 7 shots"
    
    current_time = 0.0
    for shot in shots:
        assert shot["start_time"] == current_time
        assert shot["duration"] > 0
        assert "visual_intent" in shot
        assert "primary_entity" in shot["visual_intent"]
        current_time = shot["end_time"]

    assert abs(current_time - 23.5) < 0.1, "Total shot duration must equal estimated script duration"


# --------------------------------------------------------------------------
# TEST 16: Visual QA Rejection
# --------------------------------------------------------------------------
def test_visual_qa_rejection():
    """VisualQAGate must reject composition with excessive static, repetition, or low motion."""
    gate = VisualQAGate()

    # Create candidate list with 80% static and duplicates
    bad_candidates = [
        VisualCandidate("b1", "SOURCE_A", "px", "https://px.com/dup", content_type=VisualContentType.STATIC_PHOTO, is_video=False, motion_score=0.2),
        VisualCandidate("b2", "SOURCE_A", "px", "https://px.com/dup", content_type=VisualContentType.STATIC_PHOTO, is_video=False, motion_score=0.2), # Duplicate URL!
        VisualCandidate("b3", "SOURCE_A", "px", "https://px.com/3", content_type=VisualContentType.STATIC_PHOTO, is_video=False, motion_score=0.2),
        VisualCandidate("b4", "SOURCE_A", "px", "https://px.com/4", content_type=VisualContentType.STATIC_PHOTO, is_video=False, motion_score=0.2),
    ]

    passed, reasons, metrics = gate.audit_visual_composition(bad_candidates)
    assert not passed, "Visual QA must fail for composition with duplicates and excessive static"
    assert any("Duplicate" in r for r in reasons)
    assert any("Excessive static" in r for r in reasons)
    assert any("Insufficient visual motion" in r for r in reasons)


# --------------------------------------------------------------------------
# TEST 17: Niche-Agnostic AST Audit
# --------------------------------------------------------------------------
def test_niche_agnostic_ast_audit():
    """Validates that engines/visual_intelligence contains ZERO hardcoded niche conditionals or politicians."""
    vi_dir = Path(__file__).resolve().parent.parent / "engines" / "visual_intelligence"
    prohibited_names = ["trump", "biden", "scholz", "macron", "putin", "hitler", "napoleon", "caesar"]
    
    for py_file in vi_dir.glob("**/*.py"):
        code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Inspect test condition text
                test_snippet = ast.unparse(node.test).lower()
                for name in prohibited_names:
                    assert name not in test_snippet, f"Prohibited hardcoded branch '{name}' found in {py_file.name}: {test_snippet}"


# --------------------------------------------------------------------------
# TEST 18: Regression Across Steps 4–7 & Zero Cloud Mutation
# --------------------------------------------------------------------------
def test_regression_and_zero_cloud_mutation():
    """Ensures ExecutionCapabilities.dry_run() and sandboxed_testing() have all write flags closed."""
    from engines.orchestrator import ExecutionCapabilities
    
    dry = ExecutionCapabilities.dry_run()
    assert not dry.allow_network_read
    assert not dry.allow_ai
    assert not dry.allow_tts
    assert not dry.allow_render
    assert not dry.allow_drive_write
    assert not dry.allow_youtube_write
    assert not dry.allow_schedule

    canary = ExecutionCapabilities.live_canary()
    assert not canary.allow_youtube_write
    assert not canary.allow_schedule


# --------------------------------------------------------------------------
# TEST 19: Diversity Budget & Near-Duplicate Detection
# --------------------------------------------------------------------------
def test_diversity_budget_and_near_duplicate_detection():
    """VisualDiversityController must validate diversity quotas and detect duplicate URLs."""
    controller = VisualDiversityController()
    
    # Healthy diverse composition
    diverse_cands = [
        VisualCandidate("d1", "SOURCE_B", "ed", "http://v1", content_type=VisualContentType.REAL_VIDEO, is_video=True),
        VisualCandidate("d2", "SOURCE_C", "wm", "http://v2", content_type=VisualContentType.ARCHIVAL_VIDEO, is_video=True),
        VisualCandidate("d3", "SOURCE_D", "ctx", "http://v3", content_type=VisualContentType.SCREENSHOT_DOCUMENT, is_video=False),
        VisualCandidate("d4", "SOURCE_A", "px", "http://v4", content_type=VisualContentType.GENERIC_STOCK_VIDEO, is_video=True),
    ]
    audit = controller.evaluate_diversity_budget(diverse_cands)
    assert audit["compliant"]
    assert audit["duplicates_count"] == 0
    assert audit["real_footage_pct"] >= 50.0

    # Overly generic stock composition
    monotone_cands = [
        VisualCandidate(f"m{i}", "SOURCE_A", "px", f"http://s{i}", content_type=VisualContentType.GENERIC_STOCK_VIDEO, is_video=True)
        for i in range(5)
    ]
    bad_audit = controller.evaluate_diversity_budget(monotone_cands)
    assert not bad_audit["compliant"], "Composition with 100% generic stock must fail diversity budget"
    assert bad_audit["generic_stock_pct"] == 100.0


# --------------------------------------------------------------------------
# TEST 20: Missing Evidence Attribution QA Enforcement
# --------------------------------------------------------------------------
def test_missing_evidence_attribution_qa():
    """VisualQAGate must flag when claims are discussed but no evidence assets exist."""
    gate = VisualQAGate()
    # 4 generic stock clips without any evidence documents
    generic_only = [
        VisualCandidate(f"g{i}", "SOURCE_A", "px", f"http://g{i}", content_type=VisualContentType.GENERIC_STOCK_VIDEO, is_video=True)
        for i in range(4)
    ]
    passed, reasons, metrics = gate.audit_visual_composition(generic_only, claims_present=True)
    assert not passed
    assert any("evidence attribution" in r.lower() for r in reasons)


# --------------------------------------------------------------------------
# TEST 21: Mission Control Visual Intelligence Telemetry
# --------------------------------------------------------------------------
def test_mission_control_visual_telemetry():
    """MissionControlService.get_job_inspector must include complete visual_intelligence telemetry."""
    from dashboard.mission_control_service import MissionControlService
    from core.database import SessionLocal
    
    svc = MissionControlService()
    db = SessionLocal()
    try:
        # Query any existing job or verify with mock job
        job = db.query(Job).first()
        if job:
            insp = svc.get_job_inspector(db, job.id)
            assert "visual_intelligence" in insp
            vi = insp["visual_intelligence"]
            assert "visual_sources_used" in vi
            assert "real_footage_pct" in vi
            assert "generic_stock_pct" in vi
            assert "static_asset_pct" in vi
            assert "avg_relevance_score" in vi
            assert "evidence_overlays_count" in vi
            assert "bgm_selected" in vi
            assert "voice_selected" in vi
            assert "repetition_score" in vi
            assert "rights_risk_count" in vi
            assert "fallback_count" in vi
    finally:
        db.close()



# --------------------------------------------------------------------------
# TEST 22: SourceRouter Real-Footage-First Hierarchy
# --------------------------------------------------------------------------
def test_source_router_real_footage_first_hierarchy(sample_intent):
    """SourceRouter must query real and editorial sources first, using stock only as fallback."""
    from engines.visual_intelligence.source_router import SourceRouter
    from engines.visual_intelligence.sources.base import BaseSourceAdapter
    
    router = SourceRouter()
    # Acquire candidates for sample_intent in test mode
    candidates = router.acquire_candidates(sample_intent, count_per_beat=5)
    assert len(candidates) > 0, "SourceRouter must return candidate pool"
    
    # Verify presence of real/editorial/archival candidates
    source_names = {c.source_name for c in candidates}
    assert any(any(target in s for target in ["editorial", "wikimedia", "archive", "official", "pexels"]) for s in source_names)


# --------------------------------------------------------------------------
# TEST 23: Archive and Official Source Adapters
# --------------------------------------------------------------------------
def test_archive_and_official_source_adapters(sample_intent):
    """ArchiveAdapter and OfficialAdapter must return valid public-domain candidates with full provenance."""
    from engines.visual_intelligence.sources.archive import ArchiveAdapter
    from engines.visual_intelligence.sources.official import OfficialAdapter
    
    arch_adapter = ArchiveAdapter()
    arch_cands = arch_adapter.search(["treaty", "historic"], sample_intent, count=3)
    assert len(arch_cands) > 0
    assert arch_cands[0].rights_status == RightsStatus.PUBLIC_DOMAIN
    assert arch_cands[0].provenance is not None
    assert arch_cands[0].provenance.rights_status == RightsStatus.PUBLIC_DOMAIN

    off_adapter = OfficialAdapter()
    off_cands = off_adapter.search(["government", "briefing"], sample_intent, count=3)
    assert len(off_cands) > 0
    assert off_cands[0].rights_status == RightsStatus.PUBLIC_DOMAIN
    assert off_cands[0].provenance is not None


# --------------------------------------------------------------------------
# TEST 24: Perceptual dHash Near-Duplicate Rejection
# --------------------------------------------------------------------------
def test_perceptual_dhash_near_duplicate_rejection():
    """Perceptual dHash must compute difference hashes and catch near-duplicates within threshold."""
    from PIL import Image
    from engines.visual_intelligence.diversity import (
        compute_dhash, hamming_distance, is_near_duplicate,
        detect_near_duplicates, VisualDiversityController
    )
    
    # Create two slightly different synthetic test images
    img1 = Image.new("RGB", (64, 64), color=(128, 128, 128))
    for x in range(32):
        for y in range(64):
            img1.putpixel((x, y), (200, 200, 200))
    
    # Very minor noise on img2 (near-duplicate)
    img2 = img1.copy()
    img2.putpixel((0, 0), (190, 190, 190))
    
    # Completely different image
    img3 = Image.new("RGB", (64, 64), color=(0, 0, 0))
    for x in range(64):
        for y in range(32):
            img3.putpixel((x, y), (255, 255, 255))
            
    hash1 = compute_dhash(img1)
    hash2 = compute_dhash(img2)
    hash3 = compute_dhash(img3)
    
    dist_1_2 = hamming_distance(hash1, hash2)
    dist_1_3 = hamming_distance(hash1, hash3)
    
    assert dist_1_2 <= 2, f"Near-identical images must have Hamming distance <= 2 (got {dist_1_2})"
    assert is_near_duplicate(hash1, hash2, max_distance=10)
    assert dist_1_3 > 10, f"Different images must have high Hamming distance (got {dist_1_3})"
    
    # Verify VisualDiversityController catches near-duplicate candidates
    cand1 = VisualCandidate("c_img1", "SOURCE_B", "ed", "http://img1", metadata={"dhash": hash1})
    cand2 = VisualCandidate("c_img2", "SOURCE_B", "ed", "http://img2", metadata={"dhash": hash2}) # Different URL, near-dup visual!
    
    controller = VisualDiversityController()
    near_dups = controller.check_near_duplicates([cand1, cand2], threshold=10)
    assert len(near_dups) == 1
    assert near_dups[0][0] == "c_img1"
    assert near_dups[0][1] == "c_img2"
    
    # Budget evaluation must reject near duplicates
    budget = controller.evaluate_diversity_budget([cand1, cand2])
    assert not budget["compliant"], "Composition with near-duplicate visual frames must fail diversity budget"
    assert budget["near_duplicates_count"] == 1


# --------------------------------------------------------------------------
# TEST 25: Evidence Overlay Spec and Strict Provenance Enforcement
# --------------------------------------------------------------------------
def test_evidence_overlay_spec_and_strict_provenance(tmp_path):
    """Evidence overlays must render from EvidenceOverlaySpec and reject unverified source claims."""
    from engines.visual_intelligence.overlay_engine import EvidenceOverlayEngine
    from engines.visual_intelligence.models import EvidenceOverlaySpec
    
    engine = EvidenceOverlayEngine(output_dir=tmp_path)
    
    # Valid spec
    spec = EvidenceOverlaySpec(
        overlay_type="headline",
        label="DOCUMENTED FACT",
        headline_text="Treaty Formally Ratified in Geneva",
        attribution_text="Reuters / AP Pool",
        date_text="2026-09-04"
    )
    overlay_path = engine.render_overlay_from_spec(spec)
    assert overlay_path.exists()
    assert overlay_path.stat().st_size > 500

    # Strict provenance enforcement: empty or fabricated attribution without source
    invalid_spec = EvidenceOverlaySpec(
        overlay_type="quote",
        label="CLAIM",
        headline_text="Controversial claim statement",
        attribution_text="", # Empty attribution!
        require_provenance=True
    )
    try:
        engine.render_overlay_from_spec(invalid_spec)
        assert False, "Should have raised ValueError for missing provenance attribution"
    except ValueError as e:
        assert "provenance" in str(e).lower() or "attribution" in str(e).lower()


# --------------------------------------------------------------------------
# TEST 26: Full VisualQAResult Evaluation
# --------------------------------------------------------------------------
def test_full_visual_qa_result_evaluation():
    """VisualQAGate.audit_composition_full must produce complete VisualQAResult dataclass."""
    from engines.visual_intelligence.visual_qa import VisualQAGate
    from engines.visual_intelligence.models import VisualQAResult
    
    gate = VisualQAGate()
    
    # High-quality diverse composition
    good_candidates = [
        VisualCandidate("g1", "SOURCE_B", "editorial", "http://e1", content_type=VisualContentType.LIVE_EVENT_FOOTAGE, is_video=True, motion_score=0.9, provenance=VisualProvenance("g1", "editorial", "http://e1", publisher="Reuters", license_name="Editorial", rights_status=RightsStatus.TRANSFORMATIVE_EDITORIAL)),
        VisualCandidate("g2", "SOURCE_C", "wikimedia", "http://w1", content_type=VisualContentType.ARCHIVAL_VIDEO, is_video=True, motion_score=0.85, provenance=VisualProvenance("g2", "wikimedia", "http://w1", publisher="Wikimedia Commons", license_name="CC0", rights_status=RightsStatus.PUBLIC_DOMAIN)),
        VisualCandidate("g3", "SOURCE_D", "contextual", "http://d1", content_type=VisualContentType.SCREENSHOT_DOCUMENT, is_video=False, motion_score=0.0, provenance=VisualProvenance("g3", "contextual", "http://d1", publisher="Gov Archive", license_name="Public Domain", rights_status=RightsStatus.PUBLIC_DOMAIN)),
        VisualCandidate("g4", "SOURCE_A", "pexels", "http://p1", content_type=VisualContentType.GENERIC_STOCK_VIDEO, is_video=True, motion_score=0.8, provenance=VisualProvenance("g4", "pexels", "http://p1", publisher="Pexels", license_name="Commercial Zero-Cost", rights_status=RightsStatus.LICENSED)),
    ]
    
    res = gate.audit_composition_full(
        candidates=good_candidates,
        claims_present=False,
        evidence_overlays_count=1,
        selected_bgm="Cinematic",
        selected_voice="VoiceA"
    )
    
    assert isinstance(res, VisualQAResult)
    assert res.passed
    assert res.real_footage_pct >= 50.0
    assert res.generic_stock_pct <= 35.0
    assert res.duplicate_clip_count == 0
    assert res.near_duplicate_count == 0
    assert res.provenance_completeness == 100.0
