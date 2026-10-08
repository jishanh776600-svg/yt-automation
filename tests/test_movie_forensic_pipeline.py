"""
Unit tests for Movie Forensic Pipeline (5-Layer Verification System).
Tests all 5 passes for zero visual mismatch and zero hallucination.
"""

import json
from pathlib import Path
from intelligence.movie_forensic_pipeline import (
    VisualMicroStudyEngine,
    DialogueAudioStudyEngine,
    DualCrossChecker,
    PreSliceClipVerifier,
    PostRenderFinalQA,
    VisualShot,
    SrtBeat,
)


def test_pass1_visual_micro_study_shot_detection(tmp_path):
    engine = VisualMicroStudyEngine(cache_dir=tmp_path)
    # Mock duration
    engine.get_movie_duration = lambda path: 120.0  # 2 minute mock movie

    shots = engine.detect_shots("mock_movie.mp4", sample_step_sec=10.0)
    assert len(shots) == 12
    assert shots[0].start_sec == 0.0
    assert shots[0].end_sec == 10.0
    assert shots[0].keyframe_sec == 5.0
    assert shots[-1].end_sec == 120.0


def test_pass2_srt_parsing_and_sound_cues(tmp_path):
    engine = DialogueAudioStudyEngine(cache_dir=tmp_path)
    mock_srt = """
1
00:04:15,200 --> 00:04:18,500
[tires screeching]
CHRIS: Did you hear that?

2
00:04:19,100 --> 00:04:22,800
JESSIE: Look at the road... there is barbed wire!
(loud crash)
"""
    beats = engine.parse_srt(mock_srt, "wrong_turn_2003")
    assert len(beats) == 2
    assert beats[0].start_sec == 255.20
    assert "tires screeching" in beats[0].sound_cues
    assert beats[0].text == "CHRIS: Did you hear that?"
    assert beats[1].speakers == ["JESSIE"]
    assert "loud crash" in beats[1].sound_cues


def test_pass3_dual_cross_check_grounding(tmp_path):
    visual_cat = {
        "shots": [
            {"shot_index": 1, "start_sec": 250.0, "end_sec": 258.0},
            {"shot_index": 2, "start_sec": 258.0, "end_sec": 265.0},
        ]
    }
    srt_cat = {
        "beats": [
            {
                "index": 1,
                "start_sec": 255.0,
                "end_sec": 258.0,
                "text": "The tires are shredded by barbed wire",
                "sound_cues": ["tires screeching"],
            }
        ]
    }
    checker = DualCrossChecker(visual_cat, srt_cat)
    grounded = checker.ground_beat(
        beat_num=1,
        target_action="car tire puncture by barbed wire",
        time_window_start=250.0,
        time_window_end=265.0,
        keywords=["wire", "tires", "shredded"],
    )
    assert grounded.is_verified is True
    assert grounded.visual_shot_index == 1
    assert "tires are shredded" in grounded.srt_dialogue_evidence
    assert grounded.clip_confidence >= 0.90


def test_pass4_pre_slice_clip_verifier(monkeypatch):
    verifier = PreSliceClipVerifier()
    # Mock subprocess to simulate clean video slice
    class MockRes:
        stderr = "video frame count 120"
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockRes())
    res = verifier.verify_clip_slice("mock.mp4", 10.0, 5.0)
    assert res.passed is True
    assert len(res.issues) == 0


def test_pass5_post_render_final_qa_gate(tmp_path):
    fake_video = tmp_path / "final_short.mp4"
    fake_video.write_text("fake video bytes")

    qa = PostRenderFinalQA(min_confidence_threshold=0.80)
    
    # 1. Test passing video
    passing_beats = [
        {"beat_id": "b1", "confidence": 0.95},
        {"beat_id": "b2", "confidence": 0.88},
    ]
    res_pass = qa.audit_final_short(str(fake_video), passing_beats)
    assert res_pass.passed is True
    assert res_pass.overall_confidence > 0.90

    # 2. Test rejecting video (mismatched beat)
    failing_beats = [
        {"beat_id": "b1", "confidence": 0.95},
        {"beat_id": "b2", "confidence": 0.50},  # Low confidence mismatch!
    ]
    res_fail = qa.audit_final_short(str(fake_video), failing_beats)
    assert res_fail.passed is False
    assert 2 in res_fail.failed_beats
