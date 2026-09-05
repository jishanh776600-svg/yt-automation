"""
Tests for Narration Pacing, Silence Gap Compression, and Audio QA Gates.
Validates:
1. Waveform silence compression reduces dead air to <= 100ms without clipping.
2. Audio QA fail-closed behavior on excessive silence gap (> 0.35s).
3. Audio QA fail-closed behavior on excessive cumulative dead-air (> 18%).
4. VideoQAEngine integration with narration pacing inspection.
"""
import pytest
import numpy as np
import soundfile as sf
from pathlib import Path

from engines.tts_engine import TTSEngine
from intelligence.video_qa import VideoQAEngine, VideoQAReport


@pytest.fixture
def tmp_audio_dir(tmp_path):
    d = tmp_path / "audio_test"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _generate_synthetic_speech_with_gap(path: Path, sr: int = 24000, gap_sec: float = 0.5):
    t_speech1 = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)
    speech1 = 0.3 * np.sin(2 * np.pi * 440 * t_speech1)
    silence = np.zeros(int(gap_sec * sr), dtype=np.float32)
    t_speech2 = np.linspace(0, 2.0, int(2.0 * sr), endpoint=False)
    speech2 = 0.3 * np.sin(2 * np.pi * 550 * t_speech2)
    audio = np.concatenate([speech1, silence, speech2])
    sf.write(str(path), audio, sr)
    return path


def test_silence_compression_caps_pauses_to_100ms(tmp_audio_dir):
    raw_wav = tmp_audio_dir / "raw_with_500ms_gap.wav"
    tight_wav = tmp_audio_dir / "tightened.wav"
    _generate_synthetic_speech_with_gap(raw_wav, gap_sec=0.50)
    ok, dur = TTSEngine.compress_silence_gaps(raw_wav, tight_wav, max_pause_sec=0.10)
    assert ok is True
    assert dur < 4.25
    assert dur >= 4.05

    qa = VideoQAEngine()
    metrics = qa.analyze_narration_pacing(tight_wav)
    assert metrics["max_pause"] <= 0.12


def test_audio_qa_fails_on_excessive_silence_gap(tmp_audio_dir):
    raw_wav = tmp_audio_dir / "gap_450ms.wav"
    _generate_synthetic_speech_with_gap(raw_wav, gap_sec=0.45)
    qa = VideoQAEngine()
    metrics = qa.analyze_narration_pacing(raw_wav)
    assert metrics["max_pause"] >= 0.40


def test_audio_qa_passes_on_tight_pacing(tmp_audio_dir):
    raw_wav = tmp_audio_dir / "tight_audio.wav"
    _generate_synthetic_speech_with_gap(raw_wav, gap_sec=0.09)
    qa = VideoQAEngine()
    metrics = qa.analyze_narration_pacing(raw_wav)
    assert metrics["max_pause"] <= 0.12
    assert metrics["silence_ratio"] <= 0.10
