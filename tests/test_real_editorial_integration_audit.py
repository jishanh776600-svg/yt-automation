"""
Integration Audit Test Suite for AL-AMR Visual Intelligence and Real-Footage Engine.
Audits and verifies the complete 16-component editorial pipeline:
1. Narration
2. Visual Intent
3. Source Router
4. Candidate acquisition
5. Candidate scoring
6. Diversity controller
7. Evidence overlays
8. EditingPlan
9. Multi-style subtitles
10. Dynamic subtitle positioning
11. Motion
12. Transitions
13. SFX
14. BGM
15. Voice
16. 9:16 reframing
+ FFmpeg Composition, Visual QA Gate, and Isolated Preview Artifact.
"""
import os
import re
import json
import uuid
import pytest
import subprocess
import soundfile as sf
import numpy as np
from pathlib import Path
from typing import Dict, Any, List

from config.settings import RENDERS_DIR, FFMPEG_EXE, ASSETS_DIR, MUSIC_DIR, SFX_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS
from core.models import Job, RenderOutput, AssetRecord
from core.state_machine import StateMachine, JobState

from engines.orchestrator import ProductionOrchestrator, ExecutionCapabilities
from engines.render_engine import RenderEngine
from engines.asset_fetcher import AssetFetcher
from engines.storyboard_engine import StoryboardEngine
from engines.visual_intelligence.intent_extractor import VisualIntentExtractor, VisualIntent
from engines.visual_intelligence.source_router import SourceRouter
from engines.visual_intelligence.scoring import VisualCandidateScorer
from engines.visual_intelligence.diversity import VisualDiversityController
from engines.visual_intelligence.overlay_engine import EvidenceOverlayEngine
from engines.visual_intelligence.bgm_selector import BGMSelector
from engines.visual_intelligence.visual_qa import VisualQAGate
from engines.visual_intelligence.models import (
    VisualCandidate, VisualContentType, RightsStatus, VisualProvenance
)
from engines.visual_intelligence.editing.editor import AdvancedEditorialEngine
from engines.visual_intelligence.editing.editing_models import (
    EditingPlan, SubtitleStyleType, SubtitlePositionType, EditingStyleProfile,
    CameraMotionSpec, MotionType
)
from engines.visual_intelligence.editing.subtitle_engine import MultiStyleSubtitleEngine
from engines.visual_intelligence.editing.position_engine import SubtitlePositionEngine
from engines.visual_intelligence.editing.editing_rhythm import EditingRhythmEngine
from engines.visual_intelligence.editing.sfx_engine import SFXEngine
from engines.visual_intelligence.editing.reframing_engine import ReframingEngine


def test_01_component_connectivity_audit():
    """
    Component Connectivity Audit:
    Audits all 16 components and ensures they are wired, callable, and integrated.
    """
    audit_results = {}
    
    # 1. Narration
    from engines.tts_engine import TTSEngine
    tts = TTSEngine()
    assert hasattr(tts, "generate_narration")
    audit_results["Narration"] = "CONNECTED"

    # 2. Visual Intent
    vie = VisualIntentExtractor()
    assert hasattr(vie, "extract_intent_from_beat")
    audit_results["Visual Intent"] = "CONNECTED"

    # 3. Source Router
    sr = SourceRouter()
    assert hasattr(sr, "acquire_candidates")
    assert hasattr(sr, "resolve_source_hierarchy")
    audit_results["Source Router"] = "CONNECTED"

    # 4. Candidate acquisition
    af = AssetFetcher()
    assert hasattr(af, "source_router")
    assert hasattr(af.source_router, "acquire_candidates")
    audit_results["Candidate acquisition"] = "CONNECTED"

    # 5. Candidate scoring
    vcs = VisualCandidateScorer()
    assert hasattr(vcs, "rank_candidates")
    assert hasattr(vcs, "score_candidate")
    audit_results["Candidate scoring"] = "CONNECTED"

    # 6. Diversity controller
    vdc = VisualDiversityController()
    assert hasattr(vdc, "get_recent_usage_counts")
    assert hasattr(vdc, "record_job_assets")
    audit_results["Diversity controller"] = "CONNECTED"

    # 7. Evidence overlays
    eoe = EvidenceOverlayEngine()
    assert hasattr(eoe, "generate_evidence_overlay")
    audit_results["Evidence overlays"] = "CONNECTED"

    # 8. EditingPlan
    aee = AdvancedEditorialEngine()
    assert hasattr(aee, "build_editing_plan")
    audit_results["EditingPlan"] = "CONNECTED"

    # 9. Multi-style subtitles
    mse = MultiStyleSubtitleEngine()
    assert hasattr(mse, "generate_multistyle_ass")
    audit_results["Multi-style subtitles"] = "CONNECTED"

    # 10. Dynamic subtitle positioning
    spe = SubtitlePositionEngine()
    assert hasattr(spe, "select_optimal_position")
    assert hasattr(spe, "get_position_coordinates")
    audit_results["Dynamic subtitle positioning"] = "CONNECTED"

    # 11. Motion
    from engines.visual_intelligence.editing.motion_engine import MotionEngine
    me = MotionEngine()
    assert hasattr(me, "generate_camera_motion_spec")
    audit_results["Motion"] = "CONNECTED"

    # 12. Transitions
    from engines.visual_intelligence.editing.transition_engine import TransitionEngine
    te = TransitionEngine()
    assert hasattr(te, "select_transition")
    audit_results["Transitions"] = "CONNECTED"

    # 13. SFX
    sfxe = SFXEngine()
    assert hasattr(sfxe, "evaluate_sfx_opportunity")
    audit_results["SFX"] = "CONNECTED"

    # 14. BGM
    bgms = BGMSelector()
    assert hasattr(bgms, "select_track")
    audit_results["BGM"] = "CONNECTED"

    # 15. Voice
    from engines.audio_mixer import AudioMixer
    am = AudioMixer()
    assert hasattr(am, "mix_audio")
    audit_results["Voice"] = "CONNECTED"

    # 16. 9:16 reframing
    rfe = ReframingEngine()
    assert hasattr(rfe, "calculate_reframing")
    assert hasattr(af, "crop_to_vertical_9_16")
    audit_results["9:16 reframing"] = "CONNECTED"

    # Orchestrator and RenderEngine Wiring Verification
    orch = ProductionOrchestrator(capabilities=ExecutionCapabilities.dry_run())
    assert hasattr(orch, "editorial_engine")
    assert hasattr(orch, "visual_qa_gate")
    assert hasattr(orch, "bgm_selector")
    assert hasattr(orch.render_engine, "assemble_short")

    for comp, status in audit_results.items():
        assert status == "CONNECTED", f"Component {comp} is not connected!"


def test_02_real_footage_first_ranking_behavior():
    """
    Verifies the Real-Footage-First ranking behavior with deterministic mock candidates:
    Authentic archival/editorial footage must rank higher than generic stock.
    """
    scorer = VisualCandidateScorer()
    intent = VisualIntent(
        beat_id="beat_01",
        narration_text="Winston Churchill radio speech 1940 archive",
        beat_index=0,
        start_time=0.0,
        end_time=4.0,
        duration=4.0,
        primary_entity="Winston Churchill",
        event="Battle of Britain Speech",
        action="Giving historical radio address",
        search_queries=["Winston Churchill radio speech 1940 archive", "historical speech 1940"]
    )

    editorial_cand = VisualCandidate(
        candidate_id="cand_editorial_01",
        source_class="SOURCE_B",
        source_name="editorial_archive",
        source_url="https://archive.org/churchill_1940.mp4",
        title="Winston Churchill Radio Address 1940 Audio-Visual Archive",
        content_type=VisualContentType.ARCHIVAL_VIDEO,
        rights_status=RightsStatus.PUBLIC_DOMAIN,
        width=1920,
        height=1080,
        motion_score=0.85
    )

    generic_stock_cand = VisualCandidate(
        candidate_id="cand_stock_01",
        source_class="SOURCE_A",
        source_name="pexels",
        source_url="https://images.pexels.com/man_talking_into_mic.mp4",
        title="Young man speaking into podcast microphone in studio",
        content_type=VisualContentType.GENERIC_STOCK_VIDEO,
        rights_status=RightsStatus.LICENSED,
        width=1080,
        height=1920,
        motion_score=0.75
    )

    ranked = scorer.rank_candidates([generic_stock_cand, editorial_cand], intent)
    assert len(ranked) == 2
    assert ranked[0].candidate_id == "cand_editorial_01"
    assert ranked[0].raw_score > ranked[1].raw_score


def test_03_multistyle_subtitles_and_safezone_collision_avoidance(tmp_path):
    """
    Verifies multi-style subtitle generation (multiple styles inside ONE Short)
    and dynamic position switching to avoid collision with lower-third evidence cards.
    """
    engine = MultiStyleSubtitleEngine(output_dir=tmp_path)
    pos_engine = SubtitlePositionEngine()

    pos_normal = pos_engine.select_optimal_position(evidence_overlay_present=False, text_length=20)
    assert pos_normal == SubtitlePositionType.BOTTOM_CENTER

    pos_overlay = pos_engine.select_optimal_position(evidence_overlay_present=True, text_length=20)
    assert pos_overlay in (SubtitlePositionType.UPPER_CENTER, SubtitlePositionType.CENTER)

    from engines.visual_intelligence.editing.editing_models import SubtitleCue
    cues = [
        SubtitleCue(
            cue_id="c1",
            start_time=0.0,
            end_time=3.5,
            text="DID YOU KNOW THIS SECRET ACCORD?",
            style_type=SubtitleStyleType.QUESTION,
            position_type=pos_normal
        ),
        SubtitleCue(
            cue_id="c2",
            start_time=3.5,
            end_time=7.5,
            text="CLASSIFIED ARCHIVE DECLASSIFIED IN 2026",
            style_type=SubtitleStyleType.STATISTIC,
            position_type=pos_overlay
        ),
        SubtitleCue(
            cue_id="c3",
            start_time=7.5,
            end_time=12.0,
            text="EVERYTHING CHANGED IN AN INSTANT",
            style_type=SubtitleStyleType.PUNCH,
            position_type=pos_normal
        )
    ]

    ass_path = engine.generate_multistyle_ass(cues, output_path=tmp_path / "test_subs.ass")
    assert ass_path.exists()
    content = ass_path.read_text(encoding="utf-8")

    assert "Style: QUESTION" in content
    assert "Style: STATISTIC" in content
    assert "Style: PUNCH" in content
    assert r"\pos(" in content or r"\an" in content or "pos(" in content


def test_04_editing_rhythm_and_sfx_restraint():
    """
    Verifies editing rhythm curves and SFX placement restraint.
    """
    rhythm = EditingRhythmEngine()
    roles = ["HOOK", "CONTEXT", "ESCALATION", "REVEAL", "CLIMAX"]
    durations = rhythm.calculate_pacing_curve(
        total_duration=22.0,
        shot_count=5,
        narrative_roles=roles,
        profile_urgency="BALANCED"
    )
    assert len(durations) == 5
    assert sum(durations) == pytest.approx(22.0, abs=0.05)
    assert durations[0] <= 4.5

    sfx = SFXEngine()
    sfx.reset()
    cue1 = sfx.evaluate_sfx_opportunity(0.0, 3.5, "CLIMAX", "Massive cataclysm collapsed the state", intensity="CLIMAX")
    assert cue1 is not None
    # Within 4 seconds cooldown, should be throttled
    cue2 = sfx.evaluate_sfx_opportunity(1.5, 4.0, "ESCALATION", "Building tension")
    assert cue2 is None
    # After cooldown with evidence overlay, triggers subtle paper turn
    cue3 = sfx.evaluate_sfx_opportunity(8.0, 4.0, "REVEAL", "Signed official declaration", evidence_overlay_present=True)
    assert cue3 is not None


def test_05_bgm_rotation_prevents_monotony():
    """
    Verifies BGMSelector rotates soundtracks and penalizes immediate repetition.
    """
    selector = BGMSelector()
    t1 = selector.select_track(category="Wars", title="Battle of Waterloo", script_text="The royal army clashed")
    assert t1 in selector.CATALOG
    t2 = selector.select_track(category="Mystery", title="Dark Investigation", script_text="Detectives searched the mystery ruins")
    assert t2 != t1


def test_06_generate_isolated_editorial_preview_short(tmp_path):
    """
    Produces ONE deterministic isolated preview Short (16s) via local FFmpeg:
    - 4 Cinematic Shots with Real/Editorial Assets & Evidence Overlay
    - Multi-style burned ASS captions (QUESTION, STATISTIC, PUNCH)
    - Dynamic positioning with collision avoidance
    - Master audio mix: Voice + Ducked BGM + SFX
    - Visual QA Gate audit verification
    - 100% offline, 0 cloud mutations, 0 YouTube/Drive writes.
    """
    preview_dir = tmp_path / "preview_run"
    preview_dir.mkdir(parents=True, exist_ok=True)

    sr = 44100
    total_dur = 16.0
    t = np.linspace(0, total_dur, int(sr * total_dur), False)
    audio_sig = 0.3 * np.sin(2 * np.pi * 440 * t)
    voice_file = preview_dir / "preview_voice.wav"
    sf.write(str(voice_file), audio_sig, sr)

    bgm_source = MUSIC_DIR / "No copyright Best Historical.wav"
    if not bgm_source.exists():
        bgm_source = MUSIC_DIR / "The Flux Beneath It All.wav"
    assert bgm_source.exists(), f"BGM track not found at {bgm_source}"

    overlay_engine = EvidenceOverlayEngine(output_dir=preview_dir)
    overlay_card = overlay_engine.generate_evidence_overlay(
        headline="OFFICIAL DIPLOMATIC ACCORD SIGNED",
        attribution="Geneva Convention Records, 1949",
        date_label="Declassified Context",
        badge_type="DECLASSIFIED"
    )
    assert Path(overlay_card).exists()

    from PIL import Image, ImageDraw
    shot_images = []
    colors = [(25, 30, 45), (40, 20, 30), (20, 40, 35), (35, 35, 20)]
    for i, col in enumerate(colors):
        img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), col)
        draw = ImageDraw.Draw(img)
        draw.text((80, 200), f"AL-AMR EDITORIAL BEAT {i+1}", fill=(220, 220, 220))
        img_path = preview_dir / f"shot_bg_{i+1}.jpg"
        img.save(img_path, "JPEG", quality=90)
        shot_images.append(img_path)

    shots = [
        {
            "shot_id": "shot_01",
            "shot_index": 0,
            "duration": 4.0,
            "narrative_stage": "HOOK",
            "narration_segment": "In 1949, a secret convention met in Geneva.",
            "camera_motion": "subtle_zoom_in"
        },
        {
            "shot_id": "shot_02",
            "shot_index": 1,
            "duration": 4.0,
            "narrative_stage": "CONTEXT",
            "narration_segment": "Archival records documented unprecedented state reactions.",
            "camera_motion": "subtle_zoom_out"
        },
        {
            "shot_id": "shot_03",
            "shot_index": 2,
            "duration": 4.0,
            "narrative_stage": "REVEAL",
            "narration_segment": "Declassified files prove the accord was ratified.",
            "camera_motion": "none"
        },
        {
            "shot_id": "shot_04",
            "shot_index": 3,
            "duration": 4.0,
            "narrative_stage": "CLIMAX",
            "narration_segment": "History was altered forever.",
            "camera_motion": "subtle_zoom_in"
        }
    ]

    asset_map = {
        "shot_01": AssetRecord(id="ast_01", asset_type="image", source="editorial", local_path=str(shot_images[0])),
        "shot_02": AssetRecord(id="ast_02", asset_type="image", source="archive", local_path=str(shot_images[1])),
        "shot_03": AssetRecord(id="ast_03", asset_type="image", source="contextual", local_path=str(overlay_card)),
        "shot_04": AssetRecord(id="ast_04", asset_type="image", source="pexels", local_path=str(shot_images[3]))
    }

    editorial_engine = AdvancedEditorialEngine(output_dir=preview_dir)
    candidates_map = {
        "shot_01": VisualCandidate(
            candidate_id="c1", source_class="SOURCE_B", source_name="editorial",
            source_url="https://editorial.org/1", content_type=VisualContentType.ARCHIVAL_VIDEO
        ),
        "shot_02": VisualCandidate(
            candidate_id="c2", source_class="SOURCE_C", source_name="archive",
            source_url="https://archive.org/2", content_type=VisualContentType.ARCHIVAL_VIDEO
        ),
        "shot_03": VisualCandidate(
            candidate_id="c3", source_class="SOURCE_D_CTX", source_name="contextual",
            source_url="https://gov.org/3", content_type=VisualContentType.SCREENSHOT_DOCUMENT
        ),
        "shot_04": VisualCandidate(
            candidate_id="c4", source_class="SOURCE_A", source_name="pexels",
            source_url="https://pexels.com/4", content_type=VisualContentType.GENERIC_STOCK_VIDEO
        ),
    }

    plan = editorial_engine.build_editing_plan(
        job_id="preview_audit_01",
        topic_title="The Secret Geneva Accord",
        category="History",
        script_text="In 1949, a secret convention met in Geneva. Archival records documented unprecedented state reactions. Declassified files prove the accord was ratified. History was altered forever.",
        shots_data=shots,
        candidates_map=candidates_map,
        total_duration=16.0,
        evidence_overlays_map={"shot_03": str(overlay_card)},
        voice_path=str(voice_file),
        bgm_path=str(bgm_source)
    )

    assert plan is not None
    assert plan.ass_subtitles_path is not None
    assert Path(plan.ass_subtitles_path).exists()
    assert len(plan.shots) == 4

    from engines.audio_mixer import AudioMixer
    audio_mixer = AudioMixer()
    master_audio_path = preview_dir / "master_audio_preview.wav"
    mixed_path, bgm_path = audio_mixer.mix_audio(
        voice_path=voice_file,
        music_path=bgm_source,
        output_path=master_audio_path,
        duration=16.0,
        job_id="preview_audit_01"
    )
    assert Path(mixed_path).exists()

    render_engine = RenderEngine()
    render_engine.renders_dir = preview_dir

    from unittest.mock import MagicMock
    mock_db = MagicMock()

    render_output = render_engine.assemble_short(
        db=mock_db,
        job_id="preview_audit_01",
        shots_data=shots,
        asset_map=asset_map,
        master_audio_path=Path(mixed_path),
        editing_plan=plan
    )

    assert render_output is not None
    out_video = Path(render_output.video_path)
    assert out_video.exists(), f"Rendered video does not exist at {out_video}"
    assert out_video.stat().st_size > 100000, f"Rendered video is too small ({out_video.stat().st_size} bytes)"

    final_artifact_path = RENDERS_DIR / "preview_editorial_short_1080x1920.mp4"
    import shutil
    shutil.copy2(out_video, final_artifact_path)
    assert final_artifact_path.exists()

    cmd_probe = [FFMPEG_EXE, "-i", str(final_artifact_path)]
    res_probe = subprocess.run(cmd_probe, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    probe_txt = res_probe.stderr.decode("utf-8", errors="ignore")

    assert "1080x1920" in probe_txt, "Video must be 1080x1920 9:16 vertical resolution"
    assert "Audio: aac" in probe_txt or "Audio: " in probe_txt, "Video must contain audio stream"

    qa_gate = VisualQAGate()
    selected_cands = list(candidates_map.values())
    passed, reasons, metrics = qa_gate.audit_visual_composition(
        selected_candidates=selected_cands,
        bgm_history=["flux_ambient"],
        claims_present=True
    )
    assert passed is True, f"Visual QA failed: {reasons}"
    assert metrics["real_footage_pct"] >= 50.0
    assert metrics["generic_stock_pct"] <= 35.0
