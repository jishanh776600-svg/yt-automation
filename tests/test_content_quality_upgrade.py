"""
Targeted Verification Suite for Content Quality Upgrade & Lifecycle Hardening.
==============================================================================
Verifies:
1. Phonetic year normalization (1837 -> "eighteen thirty-seven").
2. Context-aware number handling (1908, 1518, 1966, 1830s, 700 BC, #1) while preserving quantities (500 soldiers, 100m, 50%).
3. Historical scenes reject modern anachronisms (cars, skyscrapers, asphalt).
4. Modern scenes reject antique/archival-only artwork.
5. Storyboard pacing guarantees >= 8 shots per short and max duration <= 3.5s.
6. Audio mixing with ducked BGM generates -30 LUFS bed and -14 LUFS target.
7. Missing optional SFX falls back silently without failing render.
8. Ending Strategy engine produces intentional ending mode and loop callback.
9. Pre-READY Content Quality Gate rejects mismatched/anachronistic footage.
10. Pre-READY Content Quality Gate passes compliant Shorts.
11. Publication Gateway & 03_PUBLISHED hard barrier remain strictly intact.
12. Sarah voice lock invariant strictly maintained (af_sarah only).
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engines.tts_normalizer import normalize_script_for_tts, year_to_words
from engines.visual_intelligence.intent_extractor import VisualIntentExtractor, VisualIntent
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.storyboard_engine import StoryboardEngine
from engines.audio_mixer import AudioMixer, TARGET_BGM_LUFS, TARGET_LUFS
from engines.ending_strategy import EndingStrategyEngine, EndingMode
from core.content_quality_gate import ContentQualityGate
from core.lifecycle_gateway import vault_transition_to_published, InvariantViolationError
from config.settings import APPROVED_PRODUCTION_VOICES, KOKORO_VOICE
from engines.tts_engine import APPROVED_PRODUCTION_VOICES as TTS_APPROVED_VOICES


# ------------------------------------------------------------------------------
# TEST 1: Phonetic Year Normalization (1837 -> eighteen thirty-seven)
# ------------------------------------------------------------------------------
def test_phonetic_year_normalization_1837():
    """Verify 1837 is converted to phonetic 'eighteen thirty-seven' for TTS."""
    script = "In 1837, the secret society met in London."
    normalized = normalize_script_for_tts(script)
    assert "eighteen thirty-seven" in normalized
    assert "1837" not in normalized


# ------------------------------------------------------------------------------
# TEST 2: Context-Aware Normalization and Quantity Preservation
# ------------------------------------------------------------------------------
def test_context_aware_normalization_and_preservation():
    """
    Verify historical years/dates/rankings are converted phonetically
    while physical quantities, measurements, and percentages remain intact.
    """
    # Years & dates
    assert "nineteen oh eight" in normalize_script_for_tts("The event took place in 1908.")
    assert "fifteen eighteen" in normalize_script_for_tts("During 1518 in Strasbourg.")
    assert "nineteen sixty-six" in normalize_script_for_tts("By 1966, everything changed.")
    assert "eighteen thirties" in normalize_script_for_tts("In the 1830s, new laws were passed.")
    assert "seven hundred B C" in normalize_script_for_tts("Around 700 BC, the temple was built.")
    assert "number one" in normalize_script_for_tts("This became #1 on the list.")

    # Quantities & measurements preserved
    quantities_text = "500 soldiers marched 100 meters, losing 50% of their supplies in 24 hours."
    norm_quantities = normalize_script_for_tts(quantities_text)
    assert "500 soldiers" in norm_quantities
    assert "100 meters" in norm_quantities
    assert "50%" in norm_quantities
    assert "24 hours" in norm_quantities


# ------------------------------------------------------------------------------
# TEST 3: Historical Scene Rejects Modern Footage
# ------------------------------------------------------------------------------
def test_historical_scene_rejects_modern_footage():
    """Verify historical scenes hard-reject modern anachronistic visual footage."""
    intent = VisualIntent(
        beat_id="beat_1",
        beat_index=1,
        narration_text="In 1837, Victorian London streets were shrouded in heavy fog with horse-drawn carriages.",
        start_time=0.0,
        end_time=2.5,
        duration=2.5,
        search_queries=["victorian london street cobbles horse carriage fog gas lamp"],
        era="victorian_1830s",
        environment="urban_street",
        mood="historical_mystery",
        forbidden_content=["modern cars", "skyscrapers", "smartphones", "asphalt highways", "electric lighting", "modern traffic"]
    )
    scorer = VisualCandidateScorer()

    # Incompatible candidate: modern traffic & skyscraper
    modern_candidate = {
        "title": "Modern downtown London traffic with sports cars and glass skyscrapers",
        "description": "Aerial view of asphalt highway with modern vehicles and neon signs",
        "tags": ["modern", "cars", "highway", "london"]
    }
    score, reason = scorer.evaluate_era_and_context_compatibility(intent, modern_candidate)
    assert score == 0.0
    assert "Anachronistic content" in reason

    # Compatible candidate: archival / period footage
    period_candidate = {
        "title": "Archival footage of 19th century Victorian London cobblestone alley",
        "description": "Historical vintage etching of gas lamps and horse-drawn carriages in fog",
        "tags": ["victorian", "vintage", "cobblestone", "gas lamp", "historical"]
    }
    score_p, reason_p = scorer.evaluate_era_and_context_compatibility(intent, period_candidate)
    assert score_p > 0.0


# ------------------------------------------------------------------------------
# TEST 4: Modern Scene Rejects Antique Archival Artwork
# ------------------------------------------------------------------------------
def test_modern_scene_rejects_antique_archival_artwork():
    """Verify modern scene rejects medieval/ancient archival paintings."""
    intent = VisualIntent(
        beat_id="beat_1",
        beat_index=1,
        narration_text="In a modern laboratory, scientists research pathogens using high-tech microscopes.",
        start_time=0.0,
        end_time=2.5,
        duration=2.5,
        search_queries=["modern laboratory microscope scientist researching pathogen"],
        era="modern",
        historical_classification="MODERN",
        environment="modern_laboratory",
        mood="scientific_suspense",
        forbidden_content=["ancient scrolls", "medieval paintings", "antique parchment", "renaissance tapestry"]
    )
    scorer = VisualCandidateScorer()

    antique_candidate = {
        "title": "Medieval illuminated manuscript and ancient parchment tapestry",
        "description": "Antique renaissance painting with Latin calligraphy",
        "tags": ["medieval", "ancient", "painting"]
    }
    score, reason = scorer.evaluate_era_and_context_compatibility(intent, antique_candidate)
    assert score == 0.0
    assert "Antique archival artwork" in reason or "Anachronistic" in reason


# ------------------------------------------------------------------------------
# TEST 5: Pacing Logic Guarantees Shot Count and Max Shot Duration
# ------------------------------------------------------------------------------
# TEST 5: Pacing Logic Guarantees Shot Count and Max Shot Duration
# ------------------------------------------------------------------------------
def test_storyboard_pacing_density_and_duration():
    """Verify storyboard dynamic segmentation creates >= 8 shots with max duration <= 3.5s."""
    from core.models import ScriptRecord
    engine = StoryboardEngine()
    script = ScriptRecord(
        hook="In 1837, an uncharted vessel drifted silently into London harbor.",
        context="The decks were completely deserted, yet dinner was set on the captain's table.",
        escalation="A ledger lay open, documenting a mysterious light that engulfed the sea.",
        reveal="Every clock on board had stopped at exactly three fourteen.",
        loop_twist="No bodies, no distress signals, and no sign of struggle were ever found.",
        estimated_duration_sec=23.5
    )
    shots = engine.create_storyboard(script)

    assert len(shots) >= 8, f"Expected >= 8 shots for fast short-form pacing, got {len(shots)}"
    for idx, s in enumerate(shots):
        assert s["duration"] <= 3.5, f"Shot {idx} duration {s['duration']} exceeds 3.5s ceiling"


# ------------------------------------------------------------------------------
# TEST 6: Audio Mixing Ducked BGM Configuration
# ------------------------------------------------------------------------------
def test_audio_mixing_ducked_bgm_policy():
    """Verify mix_audio with bgm_policy='DUCKED' specifies standardized -30 LUFS bed and -14 LUFS target."""
    mixer = AudioMixer()
    assert TARGET_BGM_LUFS == -30.0
    assert TARGET_LUFS == -14.0

    # Verify BGM generation method uses target_bgm_lufs
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        source_music = Path("test_music.wav")
        output_bgm = Path("test_bgm_stage_b.wav")
        
        # Test stage B generation
        with patch.object(Path, "mkdir"):
            res = mixer.generate_stage_b_bgm_only(
                source_music_path=source_music,
                output_bgm_only_path=output_bgm,
                duration=23.0
            )
            assert res == output_bgm
            # Ensure loudnorm filter with -30.0 is used in subprocess
            first_cmd = mock_run.call_args_list[0][0][0]
            cmd_str = " ".join(first_cmd)
            assert "loudnorm=I=-30.0" in cmd_str


# ------------------------------------------------------------------------------
# TEST 7: Missing Optional SFX Falls Back Silently
# ------------------------------------------------------------------------------
def test_missing_optional_sfx_silent_fallback():
    """Verify missing/empty SFX layer does not crash audio mixing and falls back cleanly."""
    mixer = AudioMixer()
    voice_path = Path("test_voice.wav")
    output_path = Path("test_master.aac")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        with patch.object(Path, "mkdir"):
            # Passing non-existent SFX layer
            master_out, bgm_out = mixer.mix_audio(
                voice_path=voice_path,
                music_path=None,
                output_path=output_path,
                duration=23.0,
                sfx_layer_path=Path("non_existent_sfx_layer_xyz.wav"),
                bgm_policy="NONE"
            )
            assert master_out == output_path
            assert bgm_out is None
            cmd = mock_run.call_args[0][0]
            # Verify only voice is mixed (no crash or invalid input stream)
            assert "-i" in cmd
            assert str(voice_path) in cmd


# ------------------------------------------------------------------------------
# TEST 8: Ending Strategy Metadata Generation
# ------------------------------------------------------------------------------
def test_ending_strategy_metadata_generation():
    """Verify EndingStrategyEngine produces valid EndingStrategyPlan with recognized mode."""
    engine = EndingStrategyEngine()
    script = "In 1518, hundreds danced uncontrollably in Strasbourg. What really sparked the plague?"
    plan = engine.plan_ending(
        script_text=script,
        topic_title="The Dancing Plague of 1518",
        category="Historical Mysteries"
    )
    assert plan.ending_mode in [
        EndingMode.SEAMLESS_LOOP.value,
        EndingMode.UNRESOLVED_MYSTERY.value,
        EndingMode.PROVOCATIVE_QUESTION.value,
        EndingMode.CONSEQUENCE_REVEAL.value
    ]
    assert len(plan.closing_sentence) > 0
    assert len(plan.viewer_prompt) > 0
    assert plan.retention_target_sec <= 3.5
    d = plan.to_dict()
    assert "ending_mode" in d
    assert "hook_callback_text" in d


# ------------------------------------------------------------------------------
# TEST 9: Content Quality Gate Rejects Deliberately Mismatched Visuals
# ------------------------------------------------------------------------------
def test_content_quality_gate_rejects_mismatched_visual():
    """Verify ContentQualityGate fails when shots contain forbidden/anachronistic footage."""
    bad_shots = [
        {"shot_id": 1, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 2, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 3, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 4, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 5, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 6, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 7, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
        {"shot_id": 8, "duration": 2.5, "visual_intent": {"era": "victorian_1830s"}},
    ]
    bad_asset_map = {
        "shot_1": {"title": "Modern asphalt highway with sports cars and neon billboards", "description": "modern city traffic"}
    }
    report = ContentQualityGate.evaluate(
        topic_title="The Ghost Ship of 1837",
        script_text="In eighteen thirty-seven, a ship drifted into harbor with no crew on board.",
        shots_data=bad_shots,
        asset_map=bad_asset_map,
        render_duration=23.0
    )
    assert not report.passed
    assert report.era_consistency == 0.0
    assert any("Anachronistic" in r for r in report.failure_reasons)


# ------------------------------------------------------------------------------
# TEST 10: Content Quality Gate Passes Compliant Shorts
# ------------------------------------------------------------------------------
def test_content_quality_gate_passes_compliant_short():
    """Verify ContentQualityGate passes well-formed, era-consistent, well-paced Short."""
    good_shots = [
        {"shot_id": i, "duration": 2.5, "visual_intent": {"era": "victorian_1830s", "mood": "mystery"}}
        for i in range(1, 10)
    ]
    good_asset_map = {
        f"shot_{i}": {"title": "Historical 19th century harbor archival etching", "description": "vintage wooden ship in fog"}
        for i in range(1, 10)
    }
    ending_plan = EndingStrategyEngine().plan_ending(
        script_text="In eighteen thirty-seven, a ship drifted into harbor. What happened to the crew?",
        topic_title="Ghost Ship of 1837"
    )
    report = ContentQualityGate.evaluate(
        topic_title="Ghost Ship of 1837",
        script_text="In eighteen thirty-seven, an empty ship drifted into London harbor.",
        shots_data=good_shots,
        asset_map=good_asset_map,
        render_duration=23.0,
        ending_plan=ending_plan
    )
    assert report.passed
    assert report.overall_quality >= 0.75
    assert len(report.failure_reasons) == 0


# ------------------------------------------------------------------------------
# TEST 11: Publication Gateway & 03_PUBLISHED Hard Barrier Intact
# ------------------------------------------------------------------------------
def test_publication_gateway_invariants_strictly_enforced():
    """Verify 03_PUBLISHED transition CANNOT occur without valid YouTube ID."""
    mock_drive = MagicMock()
    mock_db = MagicMock()
    with pytest.raises(InvariantViolationError):
        # Must raise InvariantViolationError if youtube_video_id is empty or invalid
        vault_transition_to_published(
            file_id="drive_file_123",
            youtube_video_id="invalid_id",
            db=mock_db,
            drive_engine=mock_drive,
            caller="test_verification"
        )
    mock_drive.move_file.assert_not_called()


# ------------------------------------------------------------------------------
# TEST 12: Production Voice Lock (Bella Only)
# ------------------------------------------------------------------------------
def test_production_voice_lock_bella_only():
    """Verify Bella voice lock (af_bella) is strictly configured across all settings."""
    assert APPROVED_PRODUCTION_VOICES == ["af_bella"]
    assert TTS_APPROVED_VOICES == ["af_bella"]
    assert KOKORO_VOICE == "af_bella"
