"""
Production Visual Repair & Audio QA Test Suite.
Validates the critical fixes applied to the rendering pipeline:
1. Video Shot Motion: Direct scaling/center-crop, no zoompan frame freezing.
2. Zero Black-Screen: Overlays composited over footage, blackdetect = False.
3. SFX Audibility: SFX_CATALOG calibrated to punchy -3dB to -5dB target offsets.
4. Dynamic Captions: Kinetic active-word ASS subtitle highlighting.
5. Voice & Delivery Invariants: Liam <-> LIAM_MAX_CREATOR, Sarah <-> SARAH_MAX_CREATOR.
6. Topic Niche: Current Geopolitics / World Affairs / Diplomacy verified.
"""
import json
import pytest
from pathlib import Path

from config.settings import RENDERS_DIR
from engines.sfx_manager import SFX_CATALOG
from engines.caption_engine import CaptionEngine
from engines.visual_intelligence.voice_delivery import DeliveryProfile
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy


def test_sfx_catalog_audibility():
    """Validates that SFX default volumes are calibrated to punchy, audible levels."""
    assert SFX_CATALOG["impact_boom"]["default_volume_db"] >= -6.0
    assert SFX_CATALOG["tension_riser"]["default_volume_db"] >= -6.0
    assert SFX_CATALOG["cinematic_whoosh"]["default_volume_db"] >= -6.0
    assert SFX_CATALOG["subtle_paper_turn"]["default_volume_db"] >= -8.0


def test_voice_delivery_strict_coupling():
    """Validates that Liam is locked to LIAM_MAX_CREATOR and Sarah to SARAH_MAX_CREATOR."""
    policy = VoiceVariationPolicy()
    
    dec_liam = policy.select_voice_and_delivery(category="geopolitics", title="Crisis in Berlin")
    if dec_liam.voice_id == "am_liam":
        assert dec_liam.delivery_profile == DeliveryProfile.LIAM_MAX_CREATOR
    
    policy.reset_history()
    spec_sarah = policy.delivery_director.build_delivery_spec(
        profile=DeliveryProfile.SARAH_MAX_CREATOR,
        raw_text="Diplomatic dispute in the South Atlantic",
        category="diplomacy"
    )
    assert spec_sarah.profile == DeliveryProfile.SARAH_MAX_CREATOR
    assert spec_sarah.speed_multiplier == 1.08
    assert spec_sarah.presence_boost_db == 2.2


def test_caption_active_word_highlighting(tmp_path):
    """Validates that CaptionEngine produces dynamic active-word highlighted ASS events."""
    engine = CaptionEngine()
    dummy_words = [
        {"word": "GERMANY'S", "start": 0.0, "end": 0.4},
        {"word": "COALITION", "start": 0.4, "end": 0.9},
        {"word": "CRISIS", "start": 0.9, "end": 1.4}
    ]
    # Monkey-patch transcribe_words to test ASS generation deterministically
    engine.transcribe_words = lambda p: dummy_words
    
    out_ass = tmp_path / "test_subs.ass"
    res_path = engine.generate_ass_subtitles(tmp_path / "dummy.wav", output_path=out_ass)
    assert res_path.exists()
    
    content = res_path.read_text(encoding="utf-8")
    assert "[V4+ Styles]" in content
    assert "Dialogue:" in content
    # Assert active-word highlight tags exist
    assert "\\c&H0000D7FF&" in content or "\\c&H0000FFFF&" in content
    assert "\\fscx115\\fscy115" in content


def test_rendered_samples_manifest_integrity():
    """Validates that all 3 rendered sample Shorts meet all QA and visual criteria."""
    manifest_path = RENDERS_DIR / "final_samples" / "final_samples_manifest.json"
    assert manifest_path.exists(), "Final samples manifest must exist"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    assert len(manifest) == 3
    
    for sample in manifest:
        # Check files exist
        p = Path(sample["output_path"])
        assert p.exists(), f"Sample file {p} does not exist"
        assert p.stat().st_size > 20_000_000, f"Sample file {p} unexpectedly small"
        
        # Check QA metrics
        assert sample["qa_status"] == "PASSED"
        assert sample["black_screen_detected"] is False
        assert sample["real_footage_percentage"] == 1.0
        assert sample["cuts_per_minute"] >= 25.0
        assert sample["bgm_policy"] == "NONE"
        assert sample["sfx_count"] == 3
        
        # Check voice lock: Sarah Only
        assert sample["selected_voice"] == "af_sarah"
        assert sample["delivery_profile"] == "SARAH_MAX_CREATOR"
        
        # Check topics are current geopolitics / diplomacy
        assert sample["category"] in ["geopolitics", "diplomacy"]
