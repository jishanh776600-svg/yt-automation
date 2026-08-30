import pytest
from pathlib import Path
from sqlalchemy.orm import Session

from core.database import SessionLocal, init_db
from core.models import Job, Topic, SystemConfig, JobLog
from engines.tts_engine import (
    get_active_voice, set_active_voice, resolve_voice_config, AVAILABLE_VOICES, TTSEngine
)
from engines.audio_mixer import AudioMixer, BGM_LIBRARY
from engines.drive_engine import DriveVaultEngine
from main import ShortsPipeline
from config.constants import JobState


@pytest.fixture
def db_session():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_voice_persistence_and_propagation(db_session: Session):
    set_active_voice(db_session, 'af_bella')
    active_v = get_active_voice(db_session)
    assert active_v == 'af_bella'

    set_active_voice(db_session, 'bm_george')
    active_v = get_active_voice(db_session)
    assert active_v == 'bm_george'

    set_active_voice(db_session, 'am_adam')
    assert get_active_voice(db_session) == 'am_adam'


def test_voice_config_resolution():
    adam = resolve_voice_config('am_adam')
    assert adam['kokoro_voice'] == 'am_adam'
    assert adam['edge_voice'] == 'en-US-GuyNeural'

    bella = resolve_voice_config('af_bella')
    assert bella['kokoro_voice'] == 'af_bella'
    assert bella['edge_voice'] == 'en-US-JennyNeural'

    george = resolve_voice_config('bm_george')
    assert george['kokoro_voice'] == 'bm_george'
    assert george['edge_voice'] == 'en-GB-RyanNeural'


def test_invalid_voice_fails_cleanly(db_session: Session):
    with pytest.raises(ValueError):
        set_active_voice(db_session, 'non_existent_voice_xyz')


def test_pipeline_voice_override(db_session: Session):
    set_active_voice(db_session, 'am_adam')
    pipeline = ShortsPipeline(voice='af_bella')
    assert pipeline.run_voice == 'af_bella'

    pipeline_default = ShortsPipeline()
    assert pipeline_default.run_voice == 'am_adam'


def test_all_four_bgm_tracks_exist():
    mixer = AudioMixer()
    for key, track_info in BGM_LIBRARY.items():
        found = False
        for fname in track_info['primary_files']:
            p = mixer.music_dir / fname
            if p.exists() and p.stat().st_size > 1000:
                found = True
                break
        assert found, f'Track {key} file not found on disk!'


def test_adaptive_bgm_topic_matching():
    mixer = AudioMixer()

    # 1. Tragic story -> emotional_sad
    path, key, mood, reason = mixer.select_bgm_track(
        category='Tragic Disasters',
        title='The Heartbreaking Famine and Great Loss',
        summary='A tragic sorrowful grief-filled story of mourning and sacrifice.',
        script_text='The terrible famine brought heartbreaking loss and death to all families.'
    )
    assert key == 'emotional_sad'

    # 2. Mystery / Cataclysm story -> flux_ambient
    path, key, mood, reason = mixer.select_bgm_track(
        category='Documented Disasters',
        title='The Bizarre Molasses Flood Cataclysm',
        summary='An unexplained strange explosion and sticky disaster that baffled scientists.',
        script_text='The mysterious cataclysmic eruption was truly bizarre and peculiar.'
    )
    assert key == 'flux_ambient'

    # 3. High tension / Heist story -> suspense_climax
    path, key, mood, reason = mixer.select_bgm_track(
        category='Heists & Escapes',
        title='The Great Train Robbery Escape',
        summary='A high-stakes ticking clock pursuit and thrilling getaway from armed pursuit.',
        script_text='The desperate chase was a race against time as the fugitive tried to escape.'
    )
    assert key == 'suspense_climax'

    # 4. Royal / War story -> best_historical
    path, key, mood, reason = mixer.select_bgm_track(
        category='Ancient Warfare',
        title='The Medieval King Imperial Crusade',
        summary='The emperor led his vast army in an epic battle to defend the dynasty crown.',
        script_text='The monarch coronation sparked a violent war across the royal kingdom.'
    )
    assert key == 'best_historical'


def test_deterministic_rotation_on_zero_keywords():
    mixer = AudioMixer()
    selected_keys = set()
    neutral_titles = [
        'Chronicle Alpha of Event 1',
        'Chronicle Beta of Event 2',
        'Chronicle Gamma of Event 3',
        'Chronicle Delta of Event 4',
        'Chronicle Epsilon of Event 5',
        'Chronicle Zeta of Event 6',
        'Chronicle Eta of Event 7',
        'Chronicle Theta of Event 8'
    ]

    for t in neutral_titles:
        path, key, mood, reason = mixer.select_bgm_track(
            category='General',
            title=t,
            summary='A general neutral observation of facts.',
            script_text='This event took place long ago and was recorded in texts.'
        )
        selected_keys.add(key)

    assert len(selected_keys) >= 3, f'Rotation collapsed: only used {selected_keys}'


def test_ready_vault_listing():
    drive_engine = DriveVaultEngine()
    ready_files = drive_engine.list_files_in_folder('01_READY')
    assert isinstance(ready_files, list)


def test_automatic_ready_staging_local(tmp_path):
    drive_engine = DriveVaultEngine()
    dummy_mp4 = tmp_path / 'test_render_1080x1920.mp4'
    dummy_mp4.write_bytes(b'dummy mp4 video bytes' * 50)

    props = {
        'job_id': 'job_test_stage_001',
        'topic_id': 'top_test_stage_001',
        'title': 'Staging Verification Short',
        'tags': 'history,test,shorts'
    }

    res = drive_engine.upload_video_to_vault(
        local_path=dummy_mp4,
        target_folder='01_READY',
        metadata_properties=props
    )
    assert res is not None
    assert 'name' in res or 'id' in res

    ready_files = drive_engine.list_files_in_folder('01_READY')
    names = [f['name'] for f in ready_files]
    assert dummy_mp4.name in names
