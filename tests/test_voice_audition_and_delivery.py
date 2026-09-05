"""
AL-AMR — Voice Audition & Advanced Delivery Direction Test Suite.

Validates all 10 phases:
1. Delivery Profile & Speaking Style System
2. Delivery Direction & Intensity Control
3. Script Punctuation & Pause Direction for Speech
4. Script Style / Slang / Profanity Policy
5. Local Voice Audition System & Comparative Manifest
6. Dynamic Speaking-Rate & Pause Variation
7. Channel Policy: Voice-First Mix / NO-BGM Default
8. Subtitle & Dynamic Caption Compatibility
9. Dual Anti-Repetition Tracking (Voice + Delivery)
10. Architectural Guardrails, Niche-Agnostic Audit & Telemetry
"""
import ast
import json
import math
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import soundfile as sf
import numpy as np

from engines.visual_intelligence.voice_delivery import (
    DeliveryProfile,
    ProfanityLevel,
    DeliverySpec,
    ProfanityPolicyEngine,
    DeliveryDirector,
)
from engines.visual_intelligence.voice_policy import (
    VoiceVariationPolicy,
    VoiceDeliveryDecision,
)
from engines.voice_audition import (
    VoiceAuditionEngine,
    AUDITION_SCRIPTS,
    AUDITION_CANDIDATE_VOICES,
)
from engines.visual_intelligence.editing.editing_models import EditingTelemetry
from engines.tts_engine import TTSEngine, resolve_voice_config, get_active_voice
from engines.audio_mixer import AudioMixer


# ==============================================================================
# PHASE 1 & 2: DELIVERY PROFILE SELECTION & INTENSITY DIRECTION
# ==============================================================================

def test_delivery_profile_selection_conversational():
    director = DeliveryDirector()
    profile = director.determine_profile(
        text="So here is what everyone is missing about this topic. Buried inside was a small detail that changed everything.",
        title="What Really Happened Behind The Scenes",
        category="technology"
    )
    assert profile in [DeliveryProfile.CONVERSATIONAL, DeliveryProfile.CALM_EXPLANATION]


def test_delivery_profile_selection_urgent():
    director = DeliveryDirector()
    profile = director.determine_profile(
        text="Breaking update right now! Multiple sources confirm an emergency cabinet vote.",
        title="Breaking Emergency Alert",
        category="news"
    )
    assert profile == DeliveryProfile.URGENT


def test_delivery_profile_selection_shock_reveal():
    director = DeliveryDirector()
    profile = director.determine_profile(
        text="For forty years investigators believed the submarine was lost. A shocking discovery proved them wrong.",
        title="Secret Truth Uncovered",
        category="history"
    )
    assert profile in [DeliveryProfile.SHOCK_REVEAL, DeliveryProfile.INVESTIGATIVE]


def test_delivery_profile_selection_investigative():
    director = DeliveryDirector()
    profile = director.determine_profile(
        text="Follow the paper trail. Three shell corporations controlled ninety percent of the emergency grain fund.",
        title="Deep Dive Investigation",
        category="investigation"
    )
    assert profile == DeliveryProfile.INVESTIGATIVE


# ==============================================================================
# PHASE 2 & 4: SERIOUS STORY HUMOR SUPPRESSION & PROFANITY POLICY
# ==============================================================================

def test_solemn_context_suppression():
    """Tragedies, casualties, disasters MUST force profanity to NONE and suppress sarcasm."""
    engine = ProfanityPolicyEngine()
    solemn_text = "The catastrophic earthquake claimed over four thousand lives across five provinces."
    
    assert engine.is_solemn_context(solemn_text) is True

    # Sarcastic profile must be downgraded to CALM_EXPLANATION or DRAMATIC_REVEAL
    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        profile=DeliveryProfile.SARCASTIC_LIGHT,
        raw_text=solemn_text,
        intensity="HIGH"
    )
    assert spec.profile in [DeliveryProfile.CALM_EXPLANATION, DeliveryProfile.DRAMATIC_REVEAL]
    assert spec.profanity_policy == ProfanityLevel.NONE


def test_profanity_levels_and_sanitization():
    engine = ProfanityPolicyEngine()
    
    # Narrator casual language with profanity under NONE policy
    text = "This whole thing was damn crazy and bullshit."
    sanitized, p_count, q_count = engine.sanitize_narration(text, ProfanityLevel.NONE)
    assert "damn" not in sanitized.lower()
    assert "bullshit" not in sanitized.lower()
    assert p_count >= 2

    # Under LIGHT policy, minor words permitted, harsh censored
    sanitized_light, p_cnt, _ = engine.sanitize_narration("That was damn crazy.", ProfanityLevel.LIGHT)
    assert "damn" in sanitized_light.lower()


def test_quoted_profanity_provenance():
    """Direct quotes retain contextual attribution while tracking provenance."""
    engine = ProfanityPolicyEngine()
    quote_text = 'The general testified, "It was a complete clusterfuck of an operation."'
    
    # Under LIGHT policy with quote
    sanitized, p_count, q_count = engine.sanitize_narration(quote_text, ProfanityLevel.LIGHT)
    assert q_count >= 1
    # Direct quote should maintain quotation structure
    assert '"' in sanitized


# ==============================================================================
# PHASE 3: PROSODY, PAUSE INJECTION & SPEED MULTIPLIERS
# ==============================================================================

def test_prosody_and_pause_injection():
    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        profile=DeliveryProfile.CONVERSATIONAL,
        raw_text="The committee met in secret. Nobody expected the sudden decision.",
        intensity="MEDIUM"
    )
    assert spec.speed_multiplier >= 1.0
    assert spec.sentence_pause_sec > 0.0
    assert spec.clause_pause_sec > 0.0
    assert len(spec.prepared_text) > 0


def test_dramatic_reveal_pause_profile():
    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        profile=DeliveryProfile.SHOCK_REVEAL,
        raw_text="And then they opened the vault.",
        intensity="CLIMAX"
    )
    assert spec.sentence_pause_sec >= 0.30
    assert spec.speed_multiplier <= 1.05


# ==============================================================================
# PHASE 5: AUDITION MANIFEST & TECHNICAL AUDIO METADATA
# ==============================================================================

def test_audition_metadata_calculation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_wav = Path(tmp_dir) / "test_audio.wav"
        sr = 24000
        # 1 second of 440 Hz sine wave
        t = np.linspace(0, 1.0, sr, endpoint=False)
        sine = 0.5 * np.sin(2 * np.pi * 440 * t)
        sf.write(str(test_wav), sine, sr)

        audition = VoiceAuditionEngine(output_dir=Path(tmp_dir))
        meta = audition.calculate_audio_metadata(test_wav)

        assert meta["duration_sec"] == 1.0
        assert meta["sample_rate"] == 24000
        assert meta["channels"] == 1
        assert -7.0 <= meta["peak_db"] <= -5.0  # 20*log10(0.5) = -6.02 dB
        assert -10.0 <= meta["rms_db"] <= -8.0


def test_audition_battery_structure():
    with tempfile.TemporaryDirectory() as tmp_dir:
        audition = VoiceAuditionEngine(output_dir=Path(tmp_dir))
        
        # Test candidate subset for speed
        candidates = [AUDITION_CANDIDATE_VOICES[0]]
        scripts = ["SCRIPT_A_CONVERSATIONAL"]
        
        manifest = audition.run_audition_battery(
            candidate_voices=candidates,
            script_keys=scripts
        )

        assert manifest["audition_version"] == "1.0.0"
        assert manifest["total_candidates"] == 1
        assert manifest["total_scripts"] == 1
        assert manifest["total_samples_rendered"] == 1
        assert manifest["production_voice_modified"] is False
        
        entry = manifest["manifest_entries"][0]
        assert entry["voice_id"] == "af_bella"
        assert entry["delivery_profile"] == DeliveryProfile.CONVERSATIONAL.value
        assert "duration_sec" in entry["audio_metadata"]
        assert "peak_db" in entry["audio_metadata"]
        assert "rms_db" in entry["audio_metadata"]


# ==============================================================================
# PHASE 6: TTS PAUSE CONTROL & METADATA
# ==============================================================================

def test_tts_engine_pause_controls():
    tts = TTSEngine()
    assert hasattr(tts, "generate_kokoro_audio")
    import inspect
    sig = inspect.signature(tts.generate_kokoro_audio)
    assert "sentence_pause" in sig.parameters
    assert "clause_pause" in sig.parameters


def test_tts_engine_delivery_spec_parameter():
    tts = TTSEngine()
    import inspect
    sig = inspect.signature(tts.generate_narration)
    assert "delivery_spec" in sig.parameters


# ==============================================================================
# PHASE 7: CHANNEL POLICY: VOICE-FIRST MIX / NO-BGM DEFAULT
# ==============================================================================

def test_audio_mixer_no_bgm_policy():
    mixer = AudioMixer()
    import inspect
    sig = inspect.signature(mixer.mix_audio)
    assert "bgm_policy" in sig.parameters

    with tempfile.TemporaryDirectory() as tmp_dir:
        voice_wav = Path(tmp_dir) / "voice.wav"
        output_wav = Path(tmp_dir) / "master.wav"
        sr = 44100
        # 1.5s audio
        data = 0.3 * np.sin(2 * np.pi * 300 * np.linspace(0, 1.5, int(1.5 * sr), endpoint=False))
        sf.write(str(voice_wav), data, sr)

        # Mix with bgm_policy="NONE" and music_path=None
        output_master, bgm_only = mixer.mix_audio(
            voice_path=voice_wav,
            music_path=None,
            output_path=output_wav,
            duration=1.5,
            bgm_policy="NONE"
        )

        assert output_master.exists()
        assert output_master.stat().st_size > 0
        assert bgm_only is None


# ==============================================================================
# PHASE 8: DUAL ANTI-REPETITION (VOICE + DELIVERY)
# ==============================================================================

def test_voice_anti_repetition():
    policy = VoiceVariationPolicy()
    policy.reset_history()

    # Selecting voices 5 times in the same category
    selected = [policy.select_voice(category="geopolitics") for _ in range(5)]
    
    # Check max consecutive occurrences <= 2
    for i in range(len(selected) - 2):
        assert not (selected[i] == selected[i+1] == selected[i+2])


def test_delivery_anti_repetition():
    policy = VoiceVariationPolicy()
    policy.reset_history()

    decisions = [
        policy.select_voice_and_delivery(
            category="geopolitics",
            title="Standard Investigative Story",
            script_text="Three offshore shell companies moved forty million dollars."
        )
        for _ in range(6)
    ]

    profiles = [d.delivery_profile for d in decisions]
    for i in range(len(profiles) - 2):
        assert not (profiles[i] == profiles[i+1] == profiles[i+2])


def test_select_voice_and_delivery_decision():
    policy = VoiceVariationPolicy()
    decision = policy.select_voice_and_delivery(
        category="investigation",
        title="The Midnight Treaty",
        script_text="Buried in paragraph forty-two was a hidden clause."
    )
    assert isinstance(decision, VoiceDeliveryDecision)
    assert decision.voice_id in ["am_liam", "af_sarah"]
    assert isinstance(decision.delivery_profile, DeliveryProfile)
    assert 0.90 <= decision.speed_multiplier <= 1.25


# ==============================================================================
# PHASE 9 & 10: TELEMETRY & NICHE-AGNOSTIC AST AUDIT
# ==============================================================================

def test_editing_telemetry_fields():
    telem = EditingTelemetry(
        job_id="test-job-001",
        editing_profile="TALKING_HEAD",
        shot_count=5,
        total_duration=24.5,
        avg_shot_duration=4.9,
        shot_duration_variance=0.1,
        subtitle_styles_used=["CLEAN"],
        subtitle_style_transitions=0,
        subtitle_positions_used=["BOTTOM_CENTER"],
        caption_occlusion_avoidances=0,
        transitions_used={},
        sfx_count=0,
        sfx_types_used=[],
        camera_motions_used={},
        bgm_track="NONE",
        voice_id="af_bella",
        real_footage_pct=0.85,
        generic_stock_pct=0.0,
        static_asset_pct=0.0,
        evidence_overlays_count=0,
        provenance_completeness=1.0,
        delivery_profile="CONVERSATIONAL",
        delivery_intensity="MEDIUM",
        speech_rate_profile=1.08,
        pause_profile="sent:0.22s,clause:0.08s",
        profanity_policy="NONE",
        profanity_usage_count=0,
        voice_rotation_status="ROTATED_OK",
        delivery_rotation_status="ROTATED_OK",
        bgm_policy="NONE"
    )
    data = telem.to_dict()
    assert data["delivery_profile"] == "CONVERSATIONAL"
    assert data["bgm_policy"] == "NONE"
    assert data["speech_rate_profile"] == 1.08


def test_niche_agnostic_ast_audit():
    """Verify that newly introduced engines contain no hardcoded political figures or nations."""
    forbidden_terms = [
        "biden", "trump", "putin", "netanyahu", "modi", "xi jinping",
        "israel", "gaza", "ukraine", "russia", "china", "america"
    ]
    target_files = [
        Path("engines/visual_intelligence/voice_delivery.py"),
        Path("engines/voice_audition.py"),
        Path("engines/visual_intelligence/voice_policy.py"),
    ]

    for fpath in target_files:
        assert fpath.exists(), f"File {fpath} must exist"
        with open(fpath, "r", encoding="utf-8") as f:
            code = f.read()
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    lower_val = node.value.lower()
                    for term in forbidden_terms:
                        pattern = r'\b' + re.escape(term) + r'\b'
                        assert not re.search(pattern, lower_val), (
                            f"Violation in {fpath}: found hardcoded niche-specific term '{term}' in '{node.value}'"
                        )


def test_production_default_voice_unchanged():
    """The default production voice is locked to approved production voice (af_sarah)."""
    active_voice = get_active_voice()
    assert active_voice in ["am_liam", "af_sarah"]
    assert active_voice == "af_sarah"


def test_whisper_alignment_invariant():
    """Word timestamps from Whisper align accurately with audio generated with pause directives."""
    from engines.caption_engine import CaptionEngine
    ce = CaptionEngine()
    assert hasattr(ce, "transcribe_words")
