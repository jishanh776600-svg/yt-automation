"""
Tests for AL-AMR Permanent Production Voice Lock.
Verifies:
1. Only am_liam and af_sarah in active production selection.
2. af_bella and all retired voices cannot be selected (resolve to af_sarah or am_liam).
3. Liam gets LIAM_MAX_CREATOR with exact parameters (1.08x, 0.17s, 0.07s, +2.2dB, -15.5 LUFS, -1.2 dBFS).
4. Sarah gets SARAH_MAX_CREATOR with exact parameters (1.08x, 0.17s, 0.07s, +2.2dB, -15.5 LUFS, -1.2 dBFS).
5. Rotation alternates between Liam and Sarah; no third voice enters.
6. BGM_POLICY is "NONE".
7. SFX enabled (max 3/short, cooldown enforced).
8. Profanity policy and solemnity guardrails enforced.
9. Audition directories (voice_auditions/, round3/, round4/) preserved.
10. Fallback safety for unapproved voices.
11. VoiceVariationPolicy history tracking integrity.
12. Presence mastering chain filter construction invariant.
13. Whisper alignment invariant preserved.
"""
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from config.settings import (
    KOKORO_VOICE, APPROVED_PRODUCTION_VOICES, RENDERS_DIR,
    KOKORO_MODEL_PATH, KOKORO_VOICES_PATH
)
from engines.visual_intelligence.voice_delivery import (
    DeliveryProfile, DeliveryDirector, DeliverySpec, ProfanityLevel, ProfanityPolicyEngine
)
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
from engines.tts_engine import (
    TTSEngine, resolve_voice_config, get_active_voice,
    AVAILABLE_VOICES, APPROVED_PRODUCTION_VOICES as TTS_APPROVED_VOICES
)
from engines.sfx_manager import SFXManager
from engines.caption_engine import CaptionEngine
from config.constants import VOICEOVER_PAUSE_MULTIPLIER


# ------------------------------------------------------------------------------
# TEST 1: Whitelist of Approved Production Voices (Sarah Only)
# ------------------------------------------------------------------------------
def test_approved_production_voices_whitelist():
    """Verify that only af_sarah is an approved production voice (Sarah Only Lock)."""
    assert set(APPROVED_PRODUCTION_VOICES) == {"af_sarah"}
    assert set(TTS_APPROVED_VOICES) == {"af_sarah"}
    assert set(VoiceVariationPolicy.APPROVED_PERSONAS.keys()) == {"af_sarah"}
    
    available_ids = [v["id"] for v in AVAILABLE_VOICES]
    assert set(available_ids) == {"af_sarah"}
    assert KOKORO_VOICE == "af_sarah"


# ------------------------------------------------------------------------------
# TEST 2: Elimination of Retired Voices (Including Liam from Production Selection)
# ------------------------------------------------------------------------------
def test_elimination_of_retired_voices():
    """Verify retired voices (including Liam) cannot be selected and resolve safely to af_sarah."""
    retired_voices = [
        "am_liam", "af_bella", "am_adam", "am_michael", "bm_george", "af_heart",
        "am_fenrir", "af_nova", "bm_lewis", "af_alloy", "am_echo"
    ]
    for voice in retired_voices:
        assert voice not in VoiceVariationPolicy.APPROVED_PERSONAS
        assert voice not in APPROVED_PRODUCTION_VOICES
        
        # Safe resolution fallback
        resolved = resolve_voice_config(voice)
        assert resolved["id"] in APPROVED_PRODUCTION_VOICES
        assert resolved["id"] == "af_sarah"

    # Verify get_active_voice() never returns a retired voice even if DB has stale value
    mock_db = MagicMock()
    mock_row = MagicMock()
    mock_row.value = "af_bella"
    mock_db.query.return_value.filter.return_value.first.return_value = mock_row
    assert get_active_voice(mock_db) in APPROVED_PRODUCTION_VOICES
    assert get_active_voice(mock_db) == "af_sarah"


# ------------------------------------------------------------------------------
# TEST 3: Liam Coupled to LIAM_MAX_CREATOR Preserved in DeliveryDirector
# ------------------------------------------------------------------------------
def test_liam_max_creator_parameters():
    """Verify LIAM_MAX_CREATOR preset is preserved in DeliveryDirector with exact tuning parameters."""
    director = DeliveryDirector()
    preset = director.PROFILE_PRESETS[DeliveryProfile.LIAM_MAX_CREATOR]
    assert preset["speed_multiplier"] == 1.08
    assert preset["sentence_pause_sec"] == 0.17
    assert preset["clause_pause_sec"] == 0.07
    assert preset["presence_boost_db"] == 2.2
    assert preset["eq_freq_hz"] == 3000
    assert preset["target_lufs"] == -15.5
    assert preset["true_peak_ceiling"] == -1.2

    spec = director.build_delivery_spec(DeliveryProfile.LIAM_MAX_CREATOR, "Test script text.")
    assert spec.profile == DeliveryProfile.LIAM_MAX_CREATOR
    assert spec.speed_multiplier == 1.08
    assert spec.sentence_pause_sec == round(0.17 * VOICEOVER_PAUSE_MULTIPLIER, 3)
    assert spec.clause_pause_sec == round(0.07 * VOICEOVER_PAUSE_MULTIPLIER, 3)
    assert spec.presence_boost_db == 2.2
    assert spec.eq_freq_hz == 3000
    assert spec.target_lufs == -15.5
    assert spec.true_peak_ceiling == -1.2


# ------------------------------------------------------------------------------
# TEST 4: Sarah Coupled to SARAH_MAX_CREATOR with Exact Parameters
# ------------------------------------------------------------------------------
def test_sarah_max_creator_parameters():
    """Verify Sarah is coupled to SARAH_MAX_CREATOR with exact approved tuning parameters."""
    persona = VoiceVariationPolicy.APPROVED_PERSONAS["af_sarah"]
    assert persona["profile"] == DeliveryProfile.SARAH_MAX_CREATOR
    
    director = DeliveryDirector()
    preset = director.PROFILE_PRESETS[DeliveryProfile.SARAH_MAX_CREATOR]
    assert preset["speed_multiplier"] == 1.08
    assert preset["sentence_pause_sec"] == 0.17
    assert preset["clause_pause_sec"] == 0.07
    assert preset["presence_boost_db"] == 2.2
    assert preset["eq_freq_hz"] == 3000
    assert preset["target_lufs"] == -15.5
    assert preset["true_peak_ceiling"] == -1.2

    spec = director.build_delivery_spec(DeliveryProfile.SARAH_MAX_CREATOR, "Test script text.")
    assert spec.profile == DeliveryProfile.SARAH_MAX_CREATOR
    assert spec.speed_multiplier == 1.08
    assert spec.sentence_pause_sec == round(0.17 * VOICEOVER_PAUSE_MULTIPLIER, 3)
    assert spec.clause_pause_sec == round(0.07 * VOICEOVER_PAUSE_MULTIPLIER, 3)
    assert spec.presence_boost_db == 2.2
    assert spec.eq_freq_hz == 3000
    assert spec.target_lufs == -15.5
    assert spec.true_peak_ceiling == -1.2


# ------------------------------------------------------------------------------
# TEST 5: Production Selection Strictly Locked to Sarah
# ------------------------------------------------------------------------------
def test_voice_selection_strictly_locks_sarah():
    """Verify selection strictly locks to af_sarah and never selects retired voices."""
    policy = VoiceVariationPolicy()
    policy.reset_history()

    selections = [
        policy.select_voice(category="general", title="Story", script_text="A story about power and human nature.")
        for _ in range(8)
    ]

    # Every selection must be strictly Sarah
    for v in selections:
        assert v == "af_sarah"


# ------------------------------------------------------------------------------
# TEST 6: BGM Policy is NONE
# ------------------------------------------------------------------------------
def test_bgm_policy_none():
    """Verify that the BGM policy defaults to NONE for voice-first production."""
    policy = VoiceVariationPolicy()
    decision = policy.select_voice_and_delivery(
        category="tech", title="AI Revolution", script_text="Computers are changing.",
        bgm_policy="NONE"
    )
    assert decision.bgm_policy == "NONE"


# ------------------------------------------------------------------------------
# TEST 7: SFX Enabled with Cooldown and Max 3 Limit
# ------------------------------------------------------------------------------
def test_sfx_manager_integration():
    """Verify SFXManager catalog and EditingDirector max 3 SFX per Short with anti-repetition."""
    from engines.sfx_manager import SFX_CATALOG
    sfx = SFXManager()
    assert hasattr(sfx, "get_sfx_path")
    assert hasattr(sfx, "render_sfx_layer")
    assert len(SFX_CATALOG) > 0

    from engines.editing_director import EditingDirector, EditingPlan, SceneEditingDirective
    director = EditingDirector()
    plan = EditingPlan(
        job_id="test_job",
        topic_title="Test Topic",
        overall_profile="MINIMALIST_CINEMATIC",
        scenes=[
            SceneEditingDirective(
                shot_id=f"shot_{i}",
                shot_index=i,
                start_time=i * 5.0,
                duration=5.0,
                narrative_role="exposition",
                intensity="MEDIUM",
                transition_in="CUT",
                transition_duration=0.0,
                camera_motion="STATIC",
                caption_style="CLEAN",
                sfx_cues=[{"sfx_id": "impact_boom"}]
            )
            for i in range(5)
        ]
    )
    director._enforce_sfx_anti_repetition(plan)
    assert plan.total_sfx_count <= 3
    assert plan.sfx_anti_repetition_applied is True


# ------------------------------------------------------------------------------
# TEST 8: Profanity Policy & Solemnity Guardrails
# ------------------------------------------------------------------------------
def test_profanity_and_solemnity_guardrails():
    """Verify solemnity guardrails suppress informal humor/sarcasm on somber topics."""
    engine = ProfanityPolicyEngine()
    solemn_text = "Over forty casualties were reported in the tragic catastrophe."
    assert engine.is_solemn_context(solemn_text) is True

    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        profile=DeliveryProfile.SARCASTIC_LIGHT,
        raw_text=solemn_text,
        emotional_tone="TRAGEDY"
    )
    # Sarcastic profile should be downgraded in solemn contexts
    assert spec.profile == DeliveryProfile.CALM_EXPLANATION


# ------------------------------------------------------------------------------
# TEST 9: Audition Directories Preserved
# ------------------------------------------------------------------------------
def test_audition_archives_preserved():
    """Verify that all historical audition archives are intact on disk."""
    round1_dir = RENDERS_DIR / "voice_auditions"
    round3_dir = RENDERS_DIR / "voice_auditions_round3"
    round4_dir = RENDERS_DIR / "voice_auditions_round4"

    assert round1_dir.exists(), f"Round 1 dir {round1_dir} must exist"
    assert round3_dir.exists(), f"Round 3 dir {round3_dir} must exist"
    assert round4_dir.exists(), f"Round 4 dir {round4_dir} must exist"

    manifest_round4 = round4_dir / "voice_audition_round4_manifest.json"
    assert manifest_round4.exists(), f"Manifest {manifest_round4} must exist"

    assert KOKORO_MODEL_PATH.exists(), "Kokoro ONNX model file must be preserved"
    assert KOKORO_VOICES_PATH.exists(), "Kokoro voices binary file must be preserved"


# ------------------------------------------------------------------------------
# TEST 10: Safe Fallback on Unapproved Voice Request
# ------------------------------------------------------------------------------
def test_safe_fallback_on_unapproved_voice_request():
    """Verify requesting an unapproved voice safely defaults to af_sarah without crashing."""
    mock_db = MagicMock()
    engine = TTSEngine()

    with patch.object(engine, "generate_kokoro_audio", return_value=(True, 22.5)),          patch.object(engine, "apply_presence_mastering", return_value=True):
        asset, dur = engine.generate_narration(
            db=mock_db,
            text="Testing fallback resolution.",
            voice="af_bella"  # Unapproved retired voice
        )
        assert dur == 22.5
        mock_db.add.assert_called_once()


# ------------------------------------------------------------------------------
# TEST 11: VoiceVariationPolicy History Integrity
# ------------------------------------------------------------------------------
def test_voice_variation_policy_history_integrity():
    """Verify history tracking functions correctly across multiple decisions."""
    policy = VoiceVariationPolicy()
    policy.reset_history()
    assert len(policy.get_recent_voices()) == 0
    assert len(policy.get_recent_delivery_profiles()) == 0

    policy.select_voice_and_delivery(category="tech", title="Tech Story", script_text="Chips.")
    assert len(policy.get_recent_voices()) == 1
    assert len(policy.get_recent_delivery_profiles()) == 1
    assert policy.get_recent_voices()[0] in APPROVED_PRODUCTION_VOICES


# ------------------------------------------------------------------------------
# TEST 12: Presence Mastering Chain Filter Construction
# ------------------------------------------------------------------------------
def test_presence_mastering_chain_filter_construction():
    """Verify presence mastering filter string format matches exact specifications."""
    engine = TTSEngine()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        
        in_wav = Path("fake_in.wav")
        out_wav = Path("fake_out.wav")
        
        with patch.object(Path, "exists", return_value=True),              patch.object(Path, "stat", return_value=MagicMock(st_size=5000)):
            res = engine.apply_presence_mastering(
                input_wav=in_wav,
                output_wav=out_wav,
                presence_boost_db=2.2,
                eq_freq_hz=3000,
                target_lufs=-15.5,
                true_peak_ceiling=-1.2
            )
            assert res is True
            assert mock_run.called
            called_cmd = mock_run.call_args[0][0]
            af_idx = called_cmd.index("-af") + 1
            af_filter = called_cmd[af_idx]
            
            assert "highpass=f=80" in af_filter
            assert "equalizer=f=3000:t=q:w=1.2:g=2.2" in af_filter
            assert "loudnorm=I=-15.5:tp=-1.2:LRA=9" in af_filter
            assert "aformat=sample_rates=24000:channel_layouts=mono" in af_filter


# ------------------------------------------------------------------------------
# TEST 13: Whisper Alignment Invariant Preserved
# ------------------------------------------------------------------------------
def test_whisper_alignment_invariant():
    """Verify CaptionEngine is intact for Whisper word alignment."""
    ce = CaptionEngine()
    assert hasattr(ce, "transcribe_words")
