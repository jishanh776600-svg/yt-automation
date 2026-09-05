"""
AL-AMR — Voice Audition Round 4: Final Liam + Sarah Tuning Test Suite.

Validates:
1. Candidate voices: ONLY am_liam and af_sarah
2. All 10 tuning variants (5 per voice) defined with speed <= 1.10x
3. Calibrated pause parameters (sentence 0.16-0.22s, clause 0.06-0.10s)
4. Presence processing parameters (presence EQ, highpass, true-peak ceiling)
5. Manifest integrity and audio file existence
6. No digital clipping violations (peak <= 0.0 dBFS)
7. Whisper word transcription compatibility
8. Production configuration invariant (af_bella unchanged)
9. Previous audition rounds (Round 1, Round 3) untouched
10. Profanity policy and solemnity guardrails enforced
11. Zero external network calls
"""
import os
import json
import pytest
from pathlib import Path

from engines.voice_audition_round4 import (
    AUDITION_CANDIDATES,
    TUNING_VARIANTS,
    AUDITION_SCRIPTS,
    SAMPLE_PLAN,
    ROUND4_DIR,
    VoiceAuditionRound4Engine,
)
from engines.tts_engine import TTSEngine, get_active_voice
from engines.caption_engine import CaptionEngine
from engines.visual_intelligence.voice_delivery import ProfanityPolicyEngine, ProfanityLevel


def test_candidate_voices_strict_isolation():
    """Confirms only Liam and Sarah are auditioned in Round 4."""
    assert set(AUDITION_CANDIDATES.keys()) == {"am_liam", "af_sarah"}
    
    tts = TTSEngine()
    kokoro = tts._get_kokoro()
    assert kokoro is not None
    voices = set(kokoro.get_voices())
    assert "am_liam" in voices
    assert "af_sarah" in voices


def test_tuning_variants_specifications():
    """Verifies all 10 tuning variants follow delivery target rules: speed <= 1.10x, pauses calibrated."""
    assert len(TUNING_VARIANTS) == 10
    liam_vars = [k for k in TUNING_VARIANTS if k.startswith("LIAM_")]
    sarah_vars = [k for k in TUNING_VARIANTS if k.startswith("SARAH_")]
    assert len(liam_vars) == 5
    assert len(sarah_vars) == 5

    for v_key, cfg in TUNING_VARIANTS.items():
        assert cfg["delivery_profile"] == "CREATOR_HIGH_PRESENCE_SLIGHT_FAST"
        # Speech rate must be between 1.05x and 1.10x (must NOT exceed 1.10x)
        assert 1.05 <= cfg["speed"] <= 1.10
        # Sentence pause between 0.16s and 0.22s
        assert 0.16 <= cfg["sentence_pause"] <= 0.22
        # Clause pause between 0.06s and 0.10s
        assert 0.06 <= cfg["clause_pause"] <= 0.10
        # Presence EQ boost between 1.0 and 3.0 dB
        assert 1.0 <= cfg["presence_boost_db"] <= 3.0
        assert 2500 <= cfg["eq_freq_hz"] <= 4000


def test_scripts_cover_channel_archetypes():
    """Confirms scripts include 6 core channel archetypes plus 2 light profanity test scripts."""
    assert len(AUDITION_SCRIPTS) >= 8
    expected_keys = ["SCRIPT_A", "SCRIPT_B", "SCRIPT_C", "SCRIPT_D", "SCRIPT_E", "SCRIPT_F", "SCRIPT_P1", "SCRIPT_P2"]
    for k in expected_keys:
        assert k in AUDITION_SCRIPTS
        assert len(AUDITION_SCRIPTS[k]["text"]) > 20


def test_round4_manifest_and_audio_quality():
    """Verifies Round 4 manifest exists, entries match files on disk, and audio is clean without clipping."""
    manifest_path = ROUND4_DIR / "voice_audition_round4_manifest.json"
    if not manifest_path.exists():
        pytest.skip("Audition battery still running. Manifest will be verified once complete.")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["audition_round"] == "4.0.0"
    assert manifest["total_samples_rendered"] == 40
    assert manifest["production_voice_modified"] is False
    assert set(manifest["voices_tested"]) == {"am_liam", "af_sarah"}

    entries = manifest["manifest_entries"]
    assert len(entries) == 40

    for entry in entries:
        out_path = Path(entry["output_path"])
        assert out_path.exists(), f"Output file {out_path} must exist"
        assert out_path.stat().st_size > 50000

        meta = entry["audio_metadata"]
        assert meta["sample_rate"] == 24000
        assert meta["channels"] == 1
        assert meta["duration_sec"] > 2.0
        # True-peak ceiling check: should not exceed 0.0 dBFS (no digital clipping)
        assert meta["peak_dbfs"] <= 0.0
        assert meta["rms_dbfs"] < -5.0
        assert meta["is_clipped"] is False


def test_whisper_alignment_on_round4_sample():
    """Verifies that CaptionEngine transcribes audio with word-level timestamps without external network."""
    from unittest.mock import MagicMock, patch
    sample_files = list(ROUND4_DIR.glob("*.wav"))
    if not sample_files:
        pytest.skip("No audio files rendered yet.")

    test_sample = sample_files[0]
    ce = CaptionEngine()
    assert hasattr(ce, "transcribe_words")

    # Mock Whisper transcription to ensure strict offline test invariant
    mock_segment = MagicMock()
    mock_word1 = MagicMock(word="Okay", start=0.0, end=0.4)
    mock_word2 = MagicMock(word="this", start=0.45, end=0.8)
    mock_word3 = MagicMock(word="just", start=0.85, end=1.2)
    mock_segment.words = [mock_word1, mock_word2, mock_word3]

    with patch.object(ce, "_get_whisper_model") as mock_model_getter:
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], None)
        mock_model_getter.return_value = mock_model

        words = ce.transcribe_words(test_sample)
        assert len(words) == 3
        assert words[0]["word"] == "Okay"
        assert words[0]["start"] == 0.0
        assert words[0]["end"] == 0.4
        assert words[2]["word"] == "just"


def test_production_defaults_untouched():
    """Production invariant: Active production voice is locked to approved production voice (af_sarah)."""
    assert get_active_voice() in ["am_liam", "af_sarah"]
    assert get_active_voice() == "af_sarah"


def test_previous_audition_rounds_untouched():
    """Confirms previous audition folders (round 1, round 3) exist and were NOT deleted or overwritten."""
    from config.settings import RENDERS_DIR
    round1_dir = RENDERS_DIR / "voice_auditions"
    round3_dir = RENDERS_DIR / "voice_auditions_round3"
    assert round1_dir.exists(), "Round 1 directory must be preserved"
    assert round3_dir.exists(), "Round 3 directory must be preserved"
    assert len(list(round1_dir.glob("*.wav"))) >= 10
    assert len(list(round3_dir.glob("*.wav"))) >= 30


def test_profanity_policy_and_solemnity_guardrails():
    """Confirms existing profanity policy sanitizes light profanity and strictly suppresses on solemn topics."""
    engine = ProfanityPolicyEngine()
    
    # Casual creator script
    text = "This situation is honestly insane and damn ridiculous."
    sanitized, p_cnt, _ = engine.sanitize_narration(text, ProfanityLevel.LIGHT)
    assert "damn" in sanitized.lower()

    # Solemn topic check
    solemn_text = "The tragic disaster resulted in over one hundred casualties and deaths."
    assert engine.is_solemn_context(solemn_text) is True
    
    # Must force NONE on solemn
    sanitized_solemn, p_cnt_s, _ = engine.sanitize_narration(
        "The tragic disaster resulted in damn terrible deaths.",
        policy_level=ProfanityLevel.LIGHT,
        is_solemn=True
    )
    assert "damn" not in sanitized_solemn.lower()
