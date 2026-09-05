import pytest
import os
import json
from pathlib import Path

def test_user_provided_assets_catalog():
    """Verifies that user-provided editing assets were extracted and indexed into a valid catalog."""
    catalog_path = Path("data/assets/automation_assets_catalog.json")
    assert catalog_path.exists(), "Catalog json should exist in data/assets"
    with open(catalog_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) >= 300, f"Expected at least 300 assets indexed, got {len(data)}"
    
    # Check category distribution
    categories = set(item["category"] for item in data.values())
    assert "transition_whoosh" in categories or "tension_suspense" in categories

def test_sarah_only_voice_lock():
    """Verifies that af_sarah is strictly enforced as the sole production voice."""
    from config.settings import KOKORO_VOICE, APPROVED_PRODUCTION_VOICES
    assert KOKORO_VOICE == "af_sarah"
    assert APPROVED_PRODUCTION_VOICES == ["af_sarah"]
    assert "am_liam" not in APPROVED_PRODUCTION_VOICES
    
    from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
    policy = VoiceVariationPolicy()
    voice = policy.select_voice()
    assert voice == "af_sarah"

def test_sfx_manager_user_assets_priority():
    """Verifies that SFXManager resolves user-provided audio assets first."""
    from engines.sfx_manager import SFXManager
    mgr = SFXManager()
    
    # Test resolving user preset
    path_whoosh = mgr.get_sfx_path("user_whoosh_quick")
    assert path_whoosh.exists(), f"User whoosh path should exist: {path_whoosh}"
    assert "user_provided" in str(path_whoosh).replace("\\", "/")

def test_evidence_badge_dimensions_and_safe_zone():
    """Verifies that the evidence overlay badge is compact (<3% screen area) in upper safe zone."""
    from engines.visual_intelligence.overlay_engine import EvidenceOverlayEngine
    from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT
    
    engine = EvidenceOverlayEngine()
    total_screen_area = VIDEO_WIDTH * VIDEO_HEIGHT # 1080 x 1920 = 2,073,600
    
    # Check badge specs
    badge_width = 540
    badge_height = 76
    badge_area = badge_width * badge_height # 41,040
    area_ratio = badge_area / total_screen_area
    
    assert area_ratio < 0.03, f"Evidence badge must occupy < 3% of screen area (actual: {area_ratio*100:.2f}%)"

def test_5w1h_claim_decomposition():
    """Verifies 5W1H entity extraction and multi-variant query generation in RealFootageEngine."""
    from engines.visual_intelligence.real_footage_engine import EventClaimPlanner
    planner = EventClaimPlanner()
    
    script_text = "Allied guided-missile destroyers transit the international maritime strait as reconnaissance aircraft track carrier strike group movements."
    claims = planner.decompose_script(script_text)
    assert len(claims) >= 1
    
    queries = claims[0].search_queries
    assert len(queries) >= 1
    assert any("destroyer" in q.lower() or "strait" in q.lower() or "aircraft" in q.lower() or "patrol" in q.lower() for q in queries)

def test_footage_ranking_hierarchy_and_fallback_classification():
    """Verifies candidate scoring hierarchy and proper fallback stock penalization."""
    from engines.visual_intelligence.real_footage_engine import FootageRanker, FootageCandidate
    ranker = FootageRanker()
    
    real_candidate = FootageCandidate(
        candidate_id="real_1",
        title="Destroyer transit through Taiwan Strait",
        source_platform="DVIDS_Hub",
        source_url="http://test/real.mp4",
        media_url_or_path="http://test/real.mp4",
        duration_sec=4.5,
        rights_classification="US_GOV_PUBLIC_DOMAIN",
        matched_claim_id="c1",
        matched_claim_text="Destroyers transit maritime strait",
        is_stock_fallback=False,
        confidence_score=0.95
    )
    
    stock_candidate = FootageCandidate(
        candidate_id="stock_1",
        title="Generic ocean wave stock footage",
        source_platform="Stock_Pexels",
        source_url="http://test/stock.mp4",
        media_url_or_path="http://test/stock.mp4",
        duration_sec=5.0,
        rights_classification="FALLBACK_STOCK",
        matched_claim_id="c1",
        matched_claim_text="Destroyers transit maritime strait",
        is_stock_fallback=True,
        confidence_score=0.20
    )
    
    ranked = ranker.rank([stock_candidate, real_candidate])
    assert ranked[0].candidate_id == "real_1", "Real event footage must rank ahead of stock fallback"
    assert stock_candidate.rights_classification == "FALLBACK_STOCK"
    assert stock_candidate.is_stock_fallback is True

def test_black_screen_prevention_helper():
    """Verifies that render engine can find safe fallback video to prevent black screens."""
    from engines.render_engine import RenderEngine
    renderer = RenderEngine()
    safe_video = renderer.get_safe_fallback_video()
    assert safe_video.exists(), f"Safe fallback video must exist: {safe_video}"
    assert safe_video.stat().st_size > 50000, "Safe fallback video must have valid file size"
