import pytest
import math
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Base, Job, Topic, UploadRecord, PerformanceSnapshot,
    StrategyWeight, RenderOutput, ScriptRecord, JobState
)
from engines.upload_engine import UploadEngine
from engines.learning_engine import LearningEngine
from engines.topic_discovery import TopicDiscoveryEngine
from dashboard.data_provider import SystemDataProvider
from core.recovery_manager import RecoveryManager


@pytest.fixture
def in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


class TestHighValueHardening:

    # -------------------------------------------------------------------------
    # A. Resumable Upload
    # -------------------------------------------------------------------------
    def test_01_resumable_upload_chunk_and_resumable_configuration(self):
        engine = UploadEngine()
        assert hasattr(engine, 'recover_orphaned_upload')
        assert hasattr(engine, 'schedule_short')

    # -------------------------------------------------------------------------
    # B. Orphan Recovery
    # -------------------------------------------------------------------------
    def test_02_orphan_recovery_high_confidence_job_tag(self, in_memory_db):
        db = in_memory_db
        job = Job(id='job_alpha_123', state=JobState.READY_TO_UPLOAD.value)
        metadata = {'title': 'The Strange Battle of 1859', 'description': 'Story'}

        mock_youtube = MagicMock()
        mock_search_request = MagicMock()
        mock_search_request.execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'YT_RECOV_001'},
                    'snippet': {
                        'title': 'The Strange Battle of 1859',
                        'description': 'Historical Short\n\n[JOB_ID: job_alpha_123]'
                    }
                }
            ]
        }
        mock_youtube.search.return_value.list.return_value = mock_search_request

        engine = UploadEngine()
        vid_id, reason = engine.recover_orphaned_upload(
            youtube=mock_youtube,
            job=job,
            metadata=metadata
        )

        assert vid_id == 'YT_RECOV_001'
        assert 'HIGH_CONFIDENCE_JOB_TAG' in reason

    def test_03_orphan_recovery_ambiguous_candidates_rejected(self, in_memory_db):
        db = in_memory_db
        job = Job(id='job_beta_456', state=JobState.READY_TO_UPLOAD.value)
        metadata = {'title': 'The Great Molasses Flood', 'description': 'Story'}

        mock_youtube = MagicMock()
        mock_search_request = MagicMock()
        mock_search_request.execute.return_value = {
            'items': [
                {
                    'id': {'videoId': 'YT_MOLASSES_1'},
                    'snippet': {'title': 'The Great Molasses Flood', 'description': 'Old upload'}
                },
                {
                    'id': {'videoId': 'YT_MOLASSES_2'},
                    'snippet': {'title': 'The Great Molasses Flood', 'description': 'Another copy'}
                }
            ]
        }
        mock_youtube.search.return_value.list.return_value = mock_search_request

        engine = UploadEngine()
        vid_id, reason = engine.recover_orphaned_upload(
            youtube=mock_youtube,
            job=job,
            metadata=metadata
        )

        assert vid_id is None
        assert reason == 'ORPHAN_RECOVERY_AMBIGUOUS'

    # -------------------------------------------------------------------------
    # C. UCB1 Multi-Armed Bandit Exploration
    # -------------------------------------------------------------------------
    def test_04_ucb1_formula_and_cold_start_handling(self):
        learner = LearningEngine()
        
        # Cold start (0 observations) returns 999.0 priority
        cold_score = learner.compute_ucb1_score(weight=1.00, sample_count=0, total_samples=10)
        assert cold_score == 999.0

        # Normal UCB1: mu = 1.10, n = 5, N = 20, c = 1.414
        # exploration_bonus = 1.414 * sqrt(ln(20) / 5) = 1.414 * sqrt(2.9957 / 5) = 1.414 * 0.774 = 1.0945
        # total = 1.10 + 1.0945 = 2.1945
        score = learner.compute_ucb1_score(weight=1.10, sample_count=5, total_samples=20, exploration_c=1.414)
        expected = round(1.10 + 1.414 * math.sqrt(math.log(20) / 5), 4)
        assert score == expected

    def test_05_ucb1_deterministic_strategy_recommendation(self, in_memory_db):
        db = in_memory_db
        learner = LearningEngine()

        # Arm A: Proven winner (weight 1.30, N=15)
        # Arm B: Under-tested arm (weight 1.15, N=2) -> should have higher UCB1 bonus
        sw1 = StrategyWeight(
            id='sw_a', feature_type='hook_archetype', feature_value='DATE_TIME_ANCHOR',
            weight=1.30, sample_count=15, performance_mean=65.0, baseline_performance=50.0
        )
        sw2 = StrategyWeight(
            id='sw_b', feature_type='hook_archetype', feature_value='CONTRADICTION_SHOCK',
            weight=1.15, sample_count=2, performance_mean=58.0, baseline_performance=50.0
        )
        db.add_all([sw1, sw2])
        db.commit()

        # UCB1 mode
        rec = learner.get_strategy_recommendation(db, mode='UCB1')
        assert 'hook_archetype' in rec['recommendations']
        assert rec['mode'] == 'UCB1'
        assert 'ucb1_scores' in rec

        # Pure exploitation mode picks Arm A (highest weight 1.30)
        rec_exp = learner.get_strategy_recommendation(db, mode='EXPLOITATION')
        assert rec_exp['recommendations']['hook_archetype'] == 'DATE_TIME_ANCHOR'

    # -------------------------------------------------------------------------
    # D. Competitor Outlier Velocity Prior
    # -------------------------------------------------------------------------
    def test_06_competitor_outlier_velocity_evaluation(self):
        engine = TopicDiscoveryEngine()

        # Missing data -> UNAVAILABLE (no zero or 1 substituted)
        res_none = engine.evaluate_competitor_outlier(competitor_views=None, channel_median_views=1000.0)
        assert res_none['status'] == 'UNAVAILABLE'
        assert res_none['outlier_ratio'] is None

        res_zero_med = engine.evaluate_competitor_outlier(competitor_views=5000, channel_median_views=0.0)
        assert res_zero_med['status'] == 'UNAVAILABLE'

        # Outlier candidate (15k views / 2k median = 7.5x >= 3.0x threshold)
        res_outlier = engine.evaluate_competitor_outlier(competitor_views=15000, channel_median_views=2000.0, outlier_threshold=3.0)
        assert res_outlier['status'] == 'VALID'
        assert res_outlier['outlier_ratio'] == 7.5
        assert res_outlier['is_outlier'] is True
        assert res_outlier['classification'] == 'COMPETITOR_OUTLIER_HYPOTHESIS'

        # Standard performance (2.5k views / 2k median = 1.25x < 3.0x threshold)
        res_std = engine.evaluate_competitor_outlier(competitor_views=2500, channel_median_views=2000.0, outlier_threshold=3.0)
        assert res_std['is_outlier'] is False
        assert res_std['classification'] == 'STANDARD_PERFORMANCE'

    def test_07_competitor_hypothesis_injection_preserves_invariants(self, in_memory_db):
        db = in_memory_db
        engine = TopicDiscoveryEngine()

        topic = engine.inject_competitor_hypothesis(
            db=db,
            title='The Liechtenstein Army Miracle of 1866',
            summary='Eighty soldiers went to war and eighty-one returned after making a friend',
            category='Unusual Wars',
            competitor_views=25000,
            channel_median_views=3000.0,
            outlier_threshold=3.0
        )
        assert topic is not None
        assert topic.title == 'The Liechtenstein Army Miracle of 1866'
        assert topic.status == 'COMPETITOR_HYPOTHESIS'

        # Duplicate injection is rejected by semantic gate
        dup_topic = engine.inject_competitor_hypothesis(
            db=db,
            title='The Liechtenstein Army Miracle of 1866',
            summary='Eighty soldiers went to war and eighty-one returned after making a friend',
            category='Unusual Wars',
            competitor_views=30000,
            channel_median_views=3000.0
        )
        assert dup_topic is None

    # -------------------------------------------------------------------------
    # E. Dashboard API Freshness & Degradation
    # -------------------------------------------------------------------------
    def test_08_dashboard_data_freshness_metadata(self, in_memory_db):
        db = in_memory_db
        provider = SystemDataProvider()
        state = provider.get_full_system_state(db)

        assert 'data_freshness' in state
        freshness = state['data_freshness']
        assert 'verified_live' in freshness
        assert 'scheduled_publishing' in freshness
        assert 'telemetry_metrics' in freshness
        assert 'drive_vault' in freshness
        assert freshness['verified_live']['status'] in ('LIVE_API', 'RECONCILED_LOCAL', 'CACHED_DB')

    # -------------------------------------------------------------------------
    # F. Autonomous Recovery Improvement
    # -------------------------------------------------------------------------
    def test_09_stale_job_preserves_valid_completed_assets(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_recov_1', title='Topic 1', summary='Summary', category='General')
        job = Job(
            id='job_stale_render',
            topic_id='top_recov_1',
            state=JobState.EDITING.value,
            retry_count=0,
            updated_at=now - timedelta(minutes=45)
        )
        # Create a valid completed ScriptRecord
        script = ScriptRecord(
            id='scr_stale_1',
            topic_id='top_recov_1',
            hook='Hook', context='C', escalation='E', reveal='R', loop_twist='L',
            full_text='Completed valid script text', word_count=52, estimated_duration_sec=23.0
        )
        db.add_all([top, job, script])
        db.commit()

        recovery_mgr = RecoveryManager()
        recovered = recovery_mgr.recover_stale_jobs(db, stale_timeout_sec=1800)

        assert len(recovered) == 1
        rec_info = recovered[0]
        assert rec_info['job_id'] == 'job_stale_render'
        # Resumes from SCRIPT_READY rather than blindly resetting to QUEUED
        assert rec_info['new_state'] == JobState.SCRIPT_READY.value
        assert rec_info['action'] == 'RESUME_FROM_SCRIPT'
