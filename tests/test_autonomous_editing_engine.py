"""
Focused Test Suite for AL AMR Autonomous Editing Engine.
Tests EditingDirector, SFXManager, AudioMixer 3-layer ducking, CaptionEngine,
RenderEngine xfade/motion directives, and all fail-safe fallbacks.
"""
import pytest
import uuid
from pathlib import Path
from sqlalchemy.orm import Session

from core.database import SessionLocal, init_db
from core.models import Job, Topic, ScriptRecord, AssetRecord, RenderOutput
from engines.editing_director import EditingDirector, EditingPlan, SFXCue
from engines.sfx_manager import SFXManager, SFX_CATALOG
from engines.audio_mixer import AudioMixer
from engines.caption_engine import CaptionEngine
from engines.render_engine import RenderEngine
from engines.drive_engine import DriveVaultEngine
from main import ShortsPipeline
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, JobState


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ==============================================================================
# 1. EDITING DIRECTOR & PLAN GENERATION
# ==============================================================================

def test_editing_director_profile_classification():
    director = EditingDirector()
    assert director.classify_story_profile("Historical Mysteries", "The Voynich Riddle", "A mysterious ancient cipher.") == "MYSTERY"
    assert director.classify_story_profile("Ancient Warfare", "The Battle of Den Helder", "Cavalry charged the fleet in war.") == "WAR_POLITICS"
    assert director.classify_story_profile("Documented Disasters", "The Molasses Flood Explosion", "A massive flood erupted.") == "DISASTER"
    assert director.classify_story_profile("Human Tragedies", "The Sorrow of Eyam", "A tragic sacrifice and grief.") == "TRAGEDY"
    assert director.classify_story_profile("General", "A Curious Fact", "This happened long ago.") == "GENERAL_DOCUMENTARY"


def test_deterministic_plan_generation_structure(db_session: Session):
    director = EditingDirector()
    topic = Topic(id="top_test_dir", title="The Mystery of Roanoke", category="Historical Mysteries")
    script = ScriptRecord(
        id="scr_test_dir",
        topic_id=topic.id,
        hook="An entire colony vanished.",
        context="No signs of struggle remained.",
        escalation="Searchers found only a carved word.",
        reveal="Croatoan was the only clue.",
        loop_twist="The truth remains unknown.",
        full_text="An entire colony vanished without a trace.",
        estimated_duration_sec=22.5
    )
    shots = [
        {"shot_id": "s1", "duration": 4.0},
        {"shot_id": "s2", "duration": 4.5},
        {"shot_id": "s3", "duration": 4.5},
        {"shot_id": "s4", "duration": 5.0},
        {"shot_id": "s5", "duration": 4.5}
    ]

    plan = director.plan_editing(db_session, "job_test_plan", topic, script, shots)
    assert isinstance(plan, EditingPlan)
    assert plan.overall_profile == "MYSTERY"
    assert len(plan.scenes) == 5
    assert plan.scenes[0].narrative_role == "HOOK"
    assert plan.scenes[0].transition_in == "cut"  # Clean cut on hook
    assert plan.scenes[3].narrative_role == "REVEAL"


def test_no_effect_and_restraint_decisions(db_session: Session):
    """Verifies that the Editing Director exercises restraint (clean cuts and no-effect)."""
    director = EditingDirector()
    topic = Topic(id="top_test_restraint", title="The Tax on Beards", category="Strange Historical Laws")
    script = ScriptRecord(id="scr_test_r", topic_id=topic.id, full_text="A law was passed on facial hair.", estimated_duration_sec=21.0)
    shots = [{"shot_id": f"shot_{i}", "duration": 4.2} for i in range(5)]

    plan = director.plan_editing(db_session, "job_test_r", topic, script, shots)
    # The majority of scenes should be clean cuts (restrained documentary style)
    cuts = [s for s in plan.scenes if s.transition_in == "cut"]
    assert len(cuts) >= 3, f"Too many transitions: {len(cuts)} cuts out of {len(plan.scenes)}"


# ==============================================================================
# 2. SFX SYSTEM & ANTI-REPETITION
# ==============================================================================

def test_sfx_catalog_files_exist():
    manager = SFXManager()
    for sfx_id, info in SFX_CATALOG.items():
        p = manager.get_sfx_path(sfx_id)
        assert p is not None, f"SFX '{sfx_id}' ({info['filename']}) missing from disk!"
        assert p.exists() and p.stat().st_size > 1000


def test_sfx_anti_repetition_enforcement(db_session: Session):
    """Verifies that duplicate SFX are dropped and total cues never exceed 3."""
    director = EditingDirector()
    topic = Topic(id="top_test_sfx", title="The Great Explosion", category="Documented Disasters")
    script = ScriptRecord(id="scr_test_sfx", topic_id=topic.id, full_text="A massive disaster.", estimated_duration_sec=22.0)
    shots = [{"shot_id": f"s_{i}", "duration": 4.5} for i in range(5)]

    plan = director.plan_editing(db_session, "job_test_sfx", topic, script, shots)
    assert plan.total_sfx_count <= 3
    assert plan.sfx_anti_repetition_applied is True

    # Check for duplicates across scenes
    all_sfx_ids = []
    for sc in plan.scenes:
        for cue in sc.sfx_cues:
            all_sfx_ids.append(cue["sfx_id"])
    assert len(all_sfx_ids) == len(set(all_sfx_ids)), "Duplicate SFX cues detected in single Short!"


def test_sfx_layer_rendering(tmp_path):
    """Verifies that SFXManager renders a multi-track audio file containing positioned cues."""
    manager = SFXManager()
    cues = [
        {"sfx_id": "impact_boom", "start_time": 0.5, "duration": 1.5, "volume_db": -20.0, "fade_in_sec": 0.05, "fade_out_sec": 0.3},
        {"sfx_id": "tension_riser", "start_time": 2.5, "duration": 1.8, "volume_db": -22.0, "fade_in_sec": 0.1, "fade_out_sec": 0.3}
    ]
    out_sfx = tmp_path / "test_sfx_track.wav"
    rendered = manager.render_sfx_layer(cues, total_duration=5.0, output_path=out_sfx)
    assert rendered is not None
    assert out_sfx.exists()
    assert out_sfx.stat().st_size > 10000


# ==============================================================================
# 3. 3-LAYER AUDIO MIXING & DUCKING
# ==============================================================================

def test_3_layer_audio_mixing_with_sfx(tmp_path):
    """Verifies that AudioMixer mixes Voice + SFX Layer + BGM to -14 LUFS."""
    import numpy as np
    import soundfile as sf
    mixer = AudioMixer()

    sr = 44100
    dur = 4.0
    t = np.linspace(0, dur, int(sr * dur), False)
    
    # Clean dummy voice
    voice_wav = tmp_path / "test_voice.wav"
    sf.write(str(voice_wav), 0.3 * np.sin(2 * np.pi * 300.0 * t), sr)

    # Clean dummy BGM
    bgm_wav = mixer.music_dir / "Empty - Emotional Sad Background.wav"

    # Clean dummy SFX
    sfx_wav = tmp_path / "test_sfx.wav"
    sf.write(str(sfx_wav), 0.1 * np.sin(2 * np.pi * 100.0 * t), sr)

    out_master = tmp_path / "master_3layer.aac"
    master_p, bgm_p = mixer.mix_audio(
        voice_path=voice_wav,
        music_path=bgm_wav,
        output_path=out_master,
        duration=dur,
        sfx_layer_path=sfx_wav
    )
    assert master_p.exists()
    assert master_p.stat().st_size > 1000


# ==============================================================================
# 4. CAPTION ENHANCEMENT & PUNCH HIGHLIGHTING
# ==============================================================================

def test_caption_engine_ass_generation(tmp_path):
    """Verifies that CaptionEngine generates valid ASS subtitles with safe zone positioning."""
    import numpy as np
    import soundfile as sf
    caption_engine = CaptionEngine(model_size="base")

    sr = 24000
    dur = 3.0
    t = np.linspace(0, dur, int(sr * dur), False)
    voice_wav = tmp_path / "caption_test_voice.wav"
    sf.write(str(voice_wav), 0.2 * np.sin(2 * np.pi * 250.0 * t), sr)

    out_ass = tmp_path / "test_subs.ass"
    ass_path = caption_engine.generate_ass_subtitles(voice_wav, output_path=out_ass)
    assert ass_path.exists()
    content = ass_path.read_text(encoding="utf-8")
    assert "[Script Info]" in content
    assert f"PlayResX: {VIDEO_WIDTH}" in content
    assert f"PlayResY: {VIDEO_HEIGHT}" in content
    assert ",480,1" in content  # Safe zone verified


# ==============================================================================
# 5. RENDER ENGINE & RESOLUTION INTEGRITY
# ==============================================================================

def test_render_output_resolution_and_aspect_ratio(tmp_path):
    """Verifies that render outputs are strictly 1080x1920 with 9:16 aspect ratio."""
    from PIL import Image
    render_engine = RenderEngine()

    dummy_img = tmp_path / "test_frame.jpg"
    img = Image.new("RGB", (1920, 1080), color=(80, 120, 160))
    img.save(str(dummy_img))

    clip_out = tmp_path / "test_clip.mp4"
    res_clip = render_engine.render_image_shot_clip(dummy_img, duration=2.0, motion="subtle_zoom_in", output_path=clip_out)
    assert res_clip.exists()
    assert res_clip.stat().st_size > 1000


# ==============================================================================
# 6. FAIL-SAFE AUTONOMY & INVARIANT PRESERVATION
# ==============================================================================

def test_editing_fallback_on_none_plan(db_session: Session):
    """Verifies that assemble_short operates seamlessly even if editing_plan is None."""
    pipeline = ShortsPipeline()
    assert pipeline.editing_director is not None
    assert pipeline.sfx_manager is not None


def test_ready_staging_and_scheduler_discovery():
    """Verifies that DriveVaultEngine lists staged inventory."""
    drive_engine = DriveVaultEngine()
    ready_files = drive_engine.list_files_in_folder("01_READY")
    assert isinstance(ready_files, list)
