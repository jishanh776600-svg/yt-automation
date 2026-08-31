import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.models import (
    Base, Job, Topic, ScriptRecord, RenderOutput, UploadRecord,
    PerformanceSnapshot, StrategyWeight, LearningEvent, QAReport
)
from config.constants import JobState, DAILY_SHORTS_LIMIT
from engines.learning_engine import LearningEngine
from core.gemini_client import GeminiClient, GeminiQuotaExhaustedError, GroqResponse, OpenRouterResponse
from dashboard.data_provider import SystemDataProvider


@pytest.fixture
def in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestSelfImprovementAndRefillRepair:

    def test_01_matured_telemetry_eligible_and_immature_ignored(self, in_memory_db):
        now = datetime(2026, 8, 31, 12, 0, 0)
        db = in_memory_db
        learner = LearningEngine(min_evidence_threshold=3)

        upl_mature = UploadRecord(
            id='upl_mature_1',
            job_id='job_m1',
            youtube_video_id='REAL_YT_MAT',
            title='Mature Short',
            description='Mature',
            published_at=now - timedelta(hours=30),
            status='PUBLISHED'
        )
        snap_mature = PerformanceSnapshot(
            upload_id='upl_mature_1',
            youtube_video_id='REAL_YT_MAT',
            snapshot_time=now - timedelta(hours=2),
            views=1500,
            likes=100,
            comments=10,
            average_view_percentage=65.0
        )

        upl_immature = UploadRecord(
            id='upl_immature_1',
            job_id='job_im1',
            youtube_video_id='REAL_YT_IMM',
            title='Immature Short',
            description='Immature',
            published_at=now - timedelta(hours=10),
            status='PUBLISHED'
        )
        snap_immature = PerformanceSnapshot(
            upload_id='upl_immature_1',
            youtube_video_id='REAL_YT_IMM',
            snapshot_time=now - timedelta(hours=2),
            views=1500,
            likes=100,
            comments=10,
            average_view_percentage=65.0
        )

        db.add_all([upl_mature, snap_mature, upl_immature, snap_immature])
        db.commit()

        summary = learner.run_learning_cycle(db, min_age_hours=24.0, min_views=100, now=now)
        assert summary['eligible_videos_evaluated'] == 1
        assert summary['immature_videos_count'] == 1

    def test_02_sample_size_thresholds_insufficient_weak_and_usable(self, in_memory_db):
        learner = LearningEngine(min_evidence_threshold=3, usable_evidence_threshold=5)

        # 1. N < 3 -> Insufficient Evidence (Weight held strictly neutral at 1.00)
        w1, lift1, conf1, r1 = learner.compute_strategy_weight(sample_count=2, performance_mean=70.0, baseline_performance=50.0)
        assert w1 == 1.00
        assert conf1 == 'INSUFFICIENT_EVIDENCE'

        # 2. N = 3-4 -> Weak Evidence (Conservative +-10% damped update)
        w2, lift2, conf2, r2 = learner.compute_strategy_weight(sample_count=4, performance_mean=80.0, baseline_performance=50.0)
        assert conf2 == 'WEAK_EVIDENCE'
        assert 0.90 <= w2 <= 1.10
        assert w2 > 1.00

        # 3. N >= 5 -> Usable Evidence (Full update allowed)
        w3, lift3, conf3, r3 = learner.compute_strategy_weight(sample_count=6, performance_mean=80.0, baseline_performance=50.0)
        assert conf3 == 'USABLE_EVIDENCE'
        assert 0.20 <= w3 <= 2.00
        assert w3 > w2

    def test_03_weights_strictly_bounded_within_0_20_and_2_00(self, in_memory_db):
        learner = LearningEngine(min_weight=0.20, max_weight=2.00)
        w_high, _, _, _ = learner.compute_strategy_weight(sample_count=10, performance_mean=1000.0, baseline_performance=10.0)
        assert w_high <= 2.00
        w_low, _, _, _ = learner.compute_strategy_weight(sample_count=10, performance_mean=0.0, baseline_performance=100.0)
        assert w_low >= 0.20

    def test_04_learning_event_records_audit_trail_and_deltas(self, in_memory_db):
        now = datetime(2026, 8, 31, 12, 0, 0)
        db = in_memory_db
        learner = LearningEngine(min_evidence_threshold=3, usable_evidence_threshold=5)

        # Baseline control videos (low/average performance)
        for i in range(3):
            top = Topic(id=f'top_ctrl_{i}', title=f'Control {i}', summary='Hist', category='American History')
            job = Job(id=f'job_ctrl_{i}', topic_id=f'top_ctrl_{i}', state=JobState.PUBLISHED.value)
            scr = ScriptRecord(
                id=f'scr_ctrl_{i}',
                topic_id=f'top_ctrl_{i}',
                hook='Did you know', context='C', escalation='E', reveal='R', loop_twist='L',
                full_text='Text', word_count=52, estimated_duration_sec=23.0,
                hook_archetype='DATE_TIME_ANCHOR',
                duration_target='SWEET_SPOT'
            )
            upl = UploadRecord(
                id=f'upl_ctrl_{i}',
                job_id=f'job_ctrl_{i}',
                youtube_video_id=f'CTRL_YT_{i:03d}',
                title=f'Control {i}',
                description='Desc',
                published_at=now - timedelta(hours=48),
                status='PUBLISHED'
            )
            snap = PerformanceSnapshot(
                upload_id=f'upl_ctrl_{i}',
                youtube_video_id=f'CTRL_YT_{i:03d}',
                snapshot_time=now - timedelta(hours=2),
                views=400,
                likes=10,
                comments=1,
                average_view_percentage=35.0
            )
            db.add_all([job, top, scr, upl, snap])

        # High-performing test videos with CONTRADICTION_SHOCK hook
        for i in range(5):
            top = Topic(id=f'top_lrn_{i}', title=f'Topic {i}', summary='Hist', category='Unusual Wars')
            job = Job(id=f'job_lrn_{i}', topic_id=f'top_lrn_{i}', state=JobState.PUBLISHED.value)
            scr = ScriptRecord(
                id=f'scr_lrn_{i}',
                topic_id=f'top_lrn_{i}',
                hook='Did you know', context='C', escalation='E', reveal='R', loop_twist='L',
                full_text='Text', word_count=52, estimated_duration_sec=23.0,
                hook_archetype='CONTRADICTION_SHOCK',
                duration_target='SWEET_SPOT'
            )
            upl = UploadRecord(
                id=f'upl_lrn_{i}',
                job_id=f'job_lrn_{i}',
                youtube_video_id=f'REAL_YT_{i:03d}',
                title=f'Title {i}',
                description='Desc',
                published_at=now - timedelta(hours=48),
                status='PUBLISHED'
            )
            snap = PerformanceSnapshot(
                upload_id=f'upl_lrn_{i}',
                youtube_video_id=f'REAL_YT_{i:03d}',
                snapshot_time=now - timedelta(hours=2),
                views=2500,
                likes=250,
                comments=25,
                average_view_percentage=85.0
            )
            db.add_all([job, top, scr, upl, snap])
        db.commit()

        summary = learner.run_learning_cycle(db, min_age_hours=24.0, min_views=100, now=now)
        assert summary['learning_applied_count'] > 0

        events = db.query(LearningEvent).all()
        assert len(events) > 0
        applied = [e for e in events if e.outcome == 'LEARNING_APPLIED']
        assert len(applied) > 0
        latest = applied[-1]
        assert latest.sample_size >= 3
        assert latest.confidence in ['WEAK_EVIDENCE', 'USABLE_EVIDENCE']
        assert latest.old_weight is not None
        assert latest.new_weight is not None
        assert latest.consumed_by_generation is False

        learner.mark_profile_consumed(db, job_id='job_future_generation_01')
        assert db.query(LearningEvent).filter_by(consumed_by_generation=True).count() == len(events)

    def test_05_learned_profile_injection_into_script_generation(self, in_memory_db):
        db = in_memory_db
        sw = StrategyWeight(
            id='sw_test_1',
            feature_type='hook_archetype',
            feature_value='CONTRADICTION_SHOCK',
            weight=1.45,
            sample_count=7,
            performance_mean=78.0,
            baseline_performance=50.0,
            relative_lift=56.0,
            confidence_level='USABLE_EVIDENCE'
        )
        db.add(sw)
        db.commit()

        learner = LearningEngine(min_evidence_threshold=3)
        profile_text = learner.get_learned_production_profile(db)
        assert 'CONTRADICTION_SHOCK' in profile_text
        assert 'Profile v2.' in profile_text

    def test_06_dashboard_pipeline_counter_excludes_stale_and_completed(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        j_pub = Job(id='job_pub_1', state=JobState.PUBLISHED.value, updated_at=now)
        j_rev = Job(id='job_rev_1', state=JobState.NEEDS_REVIEW.value, updated_at=now)
        j_fail = Job(id='job_fail_1', state=JobState.FAILED.value, updated_at=now)
        j_q = Job(id='job_q_1', state=JobState.QUEUED.value, updated_at=now)
        j_stale = Job(id='job_stale_1', state=JobState.SCRIPTING.value, updated_at=now - timedelta(hours=2))
        j_active = Job(id='job_act_1', state=JobState.SCRIPTING.value, updated_at=now - timedelta(seconds=30))

        db.add_all([j_pub, j_rev, j_fail, j_q, j_stale, j_active])
        db.commit()

        provider = SystemDataProvider()
        active_count = provider.get_active_pipeline_count(db)
        assert active_count == 1

    def test_07_dashboard_live_counter_requires_verified_youtube_id(self, in_memory_db):
        db = in_memory_db

        u1 = UploadRecord(id='u1', job_id='j1', youtube_video_id='11CharsGood', title='T1', description='D1', status='PUBLISHED')
        u2 = UploadRecord(id='u2', job_id='j2', youtube_video_id='TEST_MOCK_ID', title='T2', description='D2', status='PUBLISHED')
        u3 = UploadRecord(id='u3', job_id='j3', youtube_video_id='dQw4w9WgXcQ', title='T3', description='D3', status='PUBLISHED')
        u4 = UploadRecord(id='u4', job_id='j4', youtube_video_id='ValidSched1', title='T4', description='D4', status='SCHEDULED')

        db.add_all([u1, u2, u3, u4])
        db.commit()

        provider = SystemDataProvider()
        live_count = provider.get_verified_live_count(db)
        assert live_count == 1

    def test_08_daily_capacity_bounded_at_three(self, in_memory_db):
        db = in_memory_db
        from config.constants import get_business_day_bounds_utc
        today_start, today_end = get_business_day_bounds_utc()
        today_utc = today_start + timedelta(hours=10)

        u1 = UploadRecord(id='up1', job_id='j1', youtube_video_id='VidReal0001', title='T1', description='D1', status='PUBLISHED', published_at=today_start + timedelta(hours=1))
        u2 = UploadRecord(id='up2', job_id='j2', youtube_video_id='VidReal0002', title='T2', description='D2', status='PUBLISHED', published_at=today_start + timedelta(hours=2))
        u3 = UploadRecord(id='up3', job_id='j3', youtube_video_id='VidReal0003', title='T3', description='D3', status='SCHEDULED', scheduled_publish_at=datetime.utcnow() + timedelta(hours=1))

        db.add_all([u1, u2, u3])
        db.commit()

        provider = SystemDataProvider()
        pub_status = provider.get_publishing_status(db)
        assert pub_status['published_today'] == 2
        assert pub_status['scheduled_today'] == 1
        assert pub_status['total_booked_today'] == 3
        assert pub_status['remaining_capacity'] == 0
        assert pub_status['limit_reached'] is True


    def test_09_gemini_to_groq_to_openrouter_failover_hierarchy(self):
        client = GeminiClient(
            api_key='mock_primary_key',
            secondary_api_key='mock_secondary_key',
            groq_api_key='mock_groq_key',
            openrouter_api_key='mock_openrouter_key'
        )

        with patch.object(client, '_execute_request', side_effect=GeminiQuotaExhaustedError('Gemini 429')),              patch.object(client, '_execute_groq_request', side_effect=GeminiQuotaExhaustedError('Groq 429')),              patch.object(client, '_execute_openrouter_request', return_value=OpenRouterResponse(text='OpenRouter Success')):
            res = client.generate_content(model='gemini-3.6-flash', contents='Test prompt')
            assert res.text == 'OpenRouter Success'
            assert client.is_provider_exhausted('primary')
            assert client.is_provider_exhausted('secondary')
            assert client.is_provider_exhausted('groq')

    def test_10_all_providers_exhausted_results_in_clean_failure(self):
        client = GeminiClient(
            api_key='mock_primary_key',
            secondary_api_key='mock_secondary_key',
            groq_api_key='mock_groq_key',
            openrouter_api_key='mock_openrouter_key'
        )

        with patch.object(client, '_execute_request', side_effect=GeminiQuotaExhaustedError('Gemini 429')),              patch.object(client, '_execute_groq_request', side_effect=GeminiQuotaExhaustedError('Groq 429')),              patch.object(client, '_execute_openrouter_request', side_effect=GeminiQuotaExhaustedError('OpenRouter 429')):
            with pytest.raises(GeminiQuotaExhaustedError) as excinfo:
                client.generate_content(model='gemini-3.6-flash', contents='Test prompt')
            assert 'All configured AI providers exhausted' in str(excinfo.value)