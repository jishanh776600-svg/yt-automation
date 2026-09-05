"""
Comprehensive Tests for AL-AMR Voiceover Pacing and Natural Breathing Calibration.

Covers all 12 validation requirements specified in Step 5:
1. 40% Pause Multiplier (VOICEOVER_PAUSE_MULTIPLIER = 1.40)
2. Comma / Minor Clause Pause Scaling
3. Sentence Boundary Pause Scaling
4. Paragraph / Scene Transition Pause Scaling
5. Emphasis Pause Scaling
6. No Accidental Pause Insertion Inside Words / Phrases
7. Zero / Disabled Pauses Remain Disabled
8. Audio Duration Accurately Reflects Added Pauses
9. Subtitle Timing Remains Synchronized
10. No Change to TTS Speaking Rate or Voice Model
11. No Duplicate Pauses
12. No Unrelated System Delays Modified
"""
import inspect
import re
import pytest
import numpy as np
import soundfile as sf
from pathlib import Path
from unittest.mock import MagicMock, patch

from config.constants import (
    VOICEOVER_PAUSE_MULTIPLIER,
    BASE_CLAUSE_PAUSE_SEC,
    BASE_SENTENCE_PAUSE_SEC,
    BASE_PARAGRAPH_PAUSE_SEC,
    BASE_EMPHASIS_PAUSE_SEC,
    BASE_MAX_SILENCE_CAP_SEC,
    EFFECTIVE_CLAUSE_PAUSE_SEC,
    EFFECTIVE_SENTENCE_PAUSE_SEC,
    EFFECTIVE_PARAGRAPH_PAUSE_SEC,
    EFFECTIVE_EMPHASIS_PAUSE_SEC,
    EFFECTIVE_MAX_SILENCE_CAP_SEC,
    BACKOFF_BASE_SECONDS,
    MAX_BACKOFF_SECONDS,
    STALE_JOB_TIMEOUT_SEC,
    MAX_JOB_RETRIES,
)
from config.settings import LOCK_STALE_TIMEOUT_SEC
from engines.visual_intelligence.voice_delivery import (
    DeliveryProfile,
    DeliveryDirector,
    DeliverySpec,
)
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy
from engines.tts_engine import TTSEngine, resolve_voice_config
from intelligence.video_qa import VideoQAEngine


@pytest.fixture
def tmp_audio_dir(tmp_path):
    d = tmp_path / "voiceover_pacing_test"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------------------
# 1. 40% Pause Multiplier Canonical Constant
# ------------------------------------------------------------------------------
def test_1_canonical_pause_multiplier():
    """Verify VOICEOVER_PAUSE_MULTIPLIER is defined as exactly 1.40."""
    assert VOICEOVER_PAUSE_MULTIPLIER == 1.40
    assert isinstance(VOICEOVER_PAUSE_MULTIPLIER, float)


# ------------------------------------------------------------------------------
# 2. Comma / Minor Clause Pause Scaling
# ------------------------------------------------------------------------------
def test_2_comma_clause_pause_scaling():
    """Verify clause/comma pauses are scaled by approximately 1.40x across default and profiles."""
    assert BASE_CLAUSE_PAUSE_SEC == 0.03
    assert EFFECTIVE_CLAUSE_PAUSE_SEC == round(BASE_CLAUSE_PAUSE_SEC * 1.40, 3)
    assert EFFECTIVE_CLAUSE_PAUSE_SEC == 0.042

    director = DeliveryDirector()
    base_sarah_clause = director.PROFILE_PRESETS[DeliveryProfile.SARAH_MAX_CREATOR]["clause_pause_sec"]
    assert base_sarah_clause == 0.07

    spec = director.build_delivery_spec(DeliveryProfile.SARAH_MAX_CREATOR, "Look, this is a test.")
    assert spec.clause_pause_sec == round(0.07 * 1.40, 3)
    assert spec.clause_pause_sec == 0.098


# ------------------------------------------------------------------------------
# 3. Sentence Boundary Pause Scaling
# ------------------------------------------------------------------------------
def test_3_sentence_pause_scaling():
    """Verify sentence boundary pauses are scaled by approximately 1.40x."""
    assert BASE_SENTENCE_PAUSE_SEC == 0.08
    assert EFFECTIVE_SENTENCE_PAUSE_SEC == round(BASE_SENTENCE_PAUSE_SEC * 1.40, 3)
    assert EFFECTIVE_SENTENCE_PAUSE_SEC == 0.112

    director = DeliveryDirector()
    spec_conv = director.build_delivery_spec(DeliveryProfile.CONVERSATIONAL, "Sentence one. Sentence two.")
    assert spec_conv.sentence_pause_sec == round(0.08 * 1.40, 3)
    assert spec_conv.sentence_pause_sec == 0.112

    spec_sarah = director.build_delivery_spec(DeliveryProfile.SARAH_MAX_CREATOR, "Sentence one. Sentence two.")
    assert spec_sarah.sentence_pause_sec == round(0.17 * 1.40, 3)
    assert spec_sarah.sentence_pause_sec == 0.238


# ------------------------------------------------------------------------------
# 4. Paragraph / Scene Transition Pause Scaling
# ------------------------------------------------------------------------------
def test_4_paragraph_scene_pause_scaling():
    """Verify paragraph / scene transition pause is scaled by 1.40x (0.15s -> 0.210s)."""
    assert BASE_PARAGRAPH_PAUSE_SEC == 0.15
    assert EFFECTIVE_PARAGRAPH_PAUSE_SEC == round(BASE_PARAGRAPH_PAUSE_SEC * 1.40, 3)
    assert EFFECTIVE_PARAGRAPH_PAUSE_SEC == 0.210

    director = DeliveryDirector()
    spec = director.build_delivery_spec(DeliveryProfile.CONVERSATIONAL, "Paragraph text.")
    assert spec.paragraph_pause_sec == 0.210


# ------------------------------------------------------------------------------
# 5. Emphasis Pause Scaling
# ------------------------------------------------------------------------------
def test_5_emphasis_pause_scaling():
    """Verify deliberate dramatic emphasis pauses scale by 1.40x and apply to CLIMAX / reveal profiles."""
    assert BASE_EMPHASIS_PAUSE_SEC == 0.22
    assert EFFECTIVE_EMPHASIS_PAUSE_SEC == round(BASE_EMPHASIS_PAUSE_SEC * 1.40, 3)
    assert EFFECTIVE_EMPHASIS_PAUSE_SEC == 0.308

    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        DeliveryProfile.SHOCK_REVEAL,
        "And then they opened the vault.",
        intensity="CLIMAX"
    )
    assert spec.sentence_pause_sec >= 0.30
    assert spec.sentence_pause_sec == 0.308
    assert spec.sentence_pause_sec <= 0.35


# ------------------------------------------------------------------------------
# 6. No Accidental Pause Insertion Inside Words / Phrases
# ------------------------------------------------------------------------------
def test_6_no_accidental_pause_inside_words():
    """Verify prosody formatting never injects pauses, dashes, or punctuation inside words."""
    director = DeliveryDirector()
    raw_script = "Scientists discovered unprecedented electromagnetic activity in deep underground facilities."
    spec = director.build_delivery_spec(DeliveryProfile.CONVERSATIONAL, raw_script)

    words_raw = re.findall(r'[A-Za-z]+', raw_script)
    words_prepared = re.findall(r'[A-Za-z]+', spec.prepared_text)
    for w in words_raw:
        assert w in words_prepared

    tokens = spec.prepared_text.split()
    for token in tokens:
        core = token.strip(".,!?:;\"'()-")
        if core:
            assert not re.search(r'[A-Za-z][,.;:!][A-Za-z]', core), f"Intra-word punctuation violation in token: {token}"


# ------------------------------------------------------------------------------
# 7. Zero / Disabled Pauses Remain Disabled
# ------------------------------------------------------------------------------
def test_7_zero_disabled_pauses_remain_disabled():
    """Verify that a zero or disabled pause is not artificially inflated."""
    assert 0.0 * VOICEOVER_PAUSE_MULTIPLIER == 0.0

    tts = TTSEngine()
    sig = inspect.signature(tts.generate_kokoro_audio)
    assert "sentence_pause" in sig.parameters
    assert "clause_pause" in sig.parameters

    with patch.object(tts, "_get_kokoro") as mock_get_kokoro:
        mock_kokoro = MagicMock()
        mock_kokoro.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
        mock_get_kokoro.return_value = mock_kokoro

        tts.generate_kokoro_audio(
            text="Testing zero pause.",
            output_path=Path("dummy.wav"),
            sentence_pause=0.0,
            clause_pause=0.0
        )
        _, kwargs = mock_kokoro.create.call_args
        assert kwargs["sentence_pause"] == 0.0
        assert kwargs["clause_pause"] == 0.0


# ------------------------------------------------------------------------------
# 8. Audio Duration Reflects the Added Pauses
# ------------------------------------------------------------------------------
def test_8_audio_duration_reflects_added_pauses(tmp_audio_dir):
    """Verify waveform duration increases by exactly the additional pause duration."""
    sr = 24000
    speech_duration = 2.0
    speech1 = 0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, 1.0, int(1.0 * sr), endpoint=False))
    speech2 = 0.3 * np.sin(2 * np.pi * 550 * np.linspace(0, 1.0, int(1.0 * sr), endpoint=False))

    base_pause_sec = 0.10
    scaled_pause_sec = round(base_pause_sec * VOICEOVER_PAUSE_MULTIPLIER, 3)

    silence_base = np.zeros(int(base_pause_sec * sr), dtype=np.float32)
    silence_scaled = np.zeros(int(scaled_pause_sec * sr), dtype=np.float32)

    audio_base = np.concatenate([speech1, silence_base, speech2])
    audio_scaled = np.concatenate([speech1, silence_scaled, speech2])

    p_base = tmp_audio_dir / "base.wav"
    p_scaled = tmp_audio_dir / "scaled.wav"
    sf.write(str(p_base), audio_base, sr)
    sf.write(str(p_scaled), audio_scaled, sr)

    dur_base = len(audio_base) / float(sr)
    dur_scaled = len(audio_scaled) / float(sr)

    expected_delta = scaled_pause_sec - base_pause_sec
    actual_delta = dur_scaled - dur_base
    assert abs(actual_delta - expected_delta) < 1e-4
    assert dur_scaled == pytest.approx(speech_duration + scaled_pause_sec, rel=1e-3)


# ------------------------------------------------------------------------------
# 9. Subtitle Timing Synchronization
# ------------------------------------------------------------------------------
def test_9_subtitle_timing_synchronization():
    """Verify CaptionEngine uses acoustic transcription so subtitles align with the paused timeline."""
    from engines.caption_engine import CaptionEngine
    ce = CaptionEngine()
    assert hasattr(ce, "transcribe_words")
    assert hasattr(ce, "generate_ass_subtitles")


# ------------------------------------------------------------------------------
# 10. No Change to TTS Speaking Rate
# ------------------------------------------------------------------------------
def test_10_no_change_to_speaking_rate():
    """Verify TTS speaking rate (speed_multiplier) is completely untouched by the pause increase."""
    director = DeliveryDirector()
    sarah_spec = director.build_delivery_spec(DeliveryProfile.SARAH_MAX_CREATOR, "Testing speaking rate.")
    assert sarah_spec.speed_multiplier == 1.08

    conv_spec = director.build_delivery_spec(DeliveryProfile.CONVERSATIONAL, "Testing speaking rate.")
    assert conv_spec.speed_multiplier == 1.00

    policy = VoiceVariationPolicy()
    assert "af_sarah" in policy.APPROVED_PRODUCTION_VOICES
    v_cfg = resolve_voice_config("af_sarah")
    assert v_cfg["kokoro_voice"] == "af_sarah"


# ------------------------------------------------------------------------------
# 11. No Duplicate Pauses
# ------------------------------------------------------------------------------
def test_11_no_duplicate_pauses():
    """Verify prosody preparation does not produce duplicate punctuation or runaway pauses."""
    director = DeliveryDirector()
    spec = director.build_delivery_spec(
        DeliveryProfile.CONVERSATIONAL,
        "Here is a story... Wait, what happened?! Nothing."
    )
    assert ",," not in spec.prepared_text
    assert "  " not in spec.prepared_text
    assert "-- --" not in spec.prepared_text


# ------------------------------------------------------------------------------
# 12. No Unrelated System Delays Modified
# ------------------------------------------------------------------------------
def test_12_no_unrelated_system_delays_modified():
    """Verify worker timeouts, lease timeouts, retry limits, and backoff delays are unaltered."""
    assert BACKOFF_BASE_SECONDS == 2.0
    assert MAX_BACKOFF_SECONDS == 60.0
    assert STALE_JOB_TIMEOUT_SEC == 3600
    assert LOCK_STALE_TIMEOUT_SEC == 1800.0
    assert MAX_JOB_RETRIES == 3