import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Base, Job, Topic, UploadRecord, PerformanceSnapshot,
    StrategyWeight, LearningEvent, JobState
)
from engines.learning_engine import LearningEngine
from dashboard.data_provider import SystemDataProvider


@pytest.fixture
def in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


class TestNextLevelAutonomousIntelligence:

    def test_01_analytics_universe_invariant_guarantee(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_1', title='Test Topic', summary='Summary', category='General History')
        db.add(top)

        for i in range(5):
            job = Job(id=f'job_real_{i}', topic_id='top_1', state=JobState.PUBLISHED.value)
            upl = UploadRecord(
                id=f'upl_real_{i}',
                job_id=f'job_real_{i}',
                youtube_video_id=f'REAL_YT_{i:03d}',
                title=f'Real Short #{i}',
                description='Real Description',
                status='PUBLISHED',
                privacy_status='public',
                published_at=now - timedelta(days=2)
            )
            db.add_all([job, upl])

        for i in range(10):
            job_mock = Job(id=f'job_test_{i}', topic_id='top_1', state=JobState.PUBLISHED.value)
            upl_mock = UploadRecord(
                id=f'upl_test_{i}',
                job_id=f'job_test_{i}',
                youtube_video_id=f'TEST_YT_{i:03d}',
                title=f'Test Short #{i}',
                description='Mock Description',
                status='PUBLISHED',
                privacy_status='test_local',
                published_at=now - timedelta(days=5)
            )
            db.add_all([job_mock, upl_mock])
        db.commit()

        learner = LearningEngine()
        universe = learner.get_verified_analytics_universe(db, now=now)

        assert universe['verified_live_count'] == 5
        assert universe['total_analytics_cohort'] == 5
        assert universe['mature_count'] + universe['maturing_count'] <= universe['verified_live_count']
        assert universe['data_integrity_error'] is None

    def test_02_duplicate_telemetry_snapshots_count_as_one_video(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_1', title='Test Topic', summary='Summary', category='General History')
        job = Job(id='job_krakatoa', topic_id='top_1', state=JobState.PUBLISHED.value)
        upl = UploadRecord(
            id='upl_krakatoa',
            job_id='job_krakatoa',
            youtube_video_id='0atnSrRGRmg',
            title='Krakatoa Explosion',
            description='Explosion Description',
            status='PUBLISHED',
            privacy_status='public',
            published_at=now - timedelta(days=3)
        )
        db.add_all([top, job, upl])
        db.commit()

        for h in range(50):
            snap = PerformanceSnapshot(
                upload_id='upl_krakatoa',
                youtube_video_id='0atnSrRGRmg',
                snapshot_time=now - timedelta(hours=50 - h),
                views=100 + h * 10,
                average_view_percentage=75.0,
                validation_status='VALID_REAL'
            )
            db.add(snap)
        db.commit()

        learner = LearningEngine()
        universe = learner.get_verified_analytics_universe(db, now=now)

        assert universe['verified_live_count'] == 1
        assert universe['total_analytics_cohort'] == 1
        assert universe['mature_count'] == 1
        assert universe['maturing_count'] == 0

    def test_03_mock_and_invalid_youtube_ids_excluded(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_1', title='Test Topic', summary='Summary', category='General History')
        db.add(top)

        invalid_records = [
            ('upl_1', 'dQw4w9WgXcQ', 'Rickroll'),
            ('upl_2', 'TEST_ABC123', 'Test Prefix'),
            ('upl_3', 'yt_loop_001', 'Loop Prefix'),
            ('upl_4', 'short_id', 'Too short'),
            ('upl_5', 'way_too_long_youtube_id_12345', 'Too long'),
            ('upl_6', '', 'Empty ID')
        ]
        for uid, ytid, title in invalid_records:
            job = Job(id=f'job_{uid}', topic_id='top_1', state=JobState.PUBLISHED.value)
            upl = UploadRecord(
                id=uid,
                job_id=f'job_{uid}',
                youtube_video_id=ytid,
                title=title,
                description='Desc',
                status='PUBLISHED',
                privacy_status='public',
                published_at=now - timedelta(days=2)
            )
            db.add_all([job, upl])
        db.commit()

        learner = LearningEngine()
        universe = learner.get_verified_analytics_universe(db, now=now)

        assert universe['verified_live_count'] == 0
        assert universe['total_analytics_cohort'] == 0

    def test_04_maturation_and_telemetry_thresholds(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_1', title='Test Topic', summary='Summary', category='General History')
        db.add(top)

        job1 = Job(id='j1', topic_id='top_1', state=JobState.PUBLISHED.value)
        upl_1 = UploadRecord(id='u1', job_id='j1', youtube_video_id='REAL_YT_001', title='Short 1', description='Desc1', status='PUBLISHED', published_at=now - timedelta(hours=12))
        snap_1 = PerformanceSnapshot(upload_id='u1', youtube_video_id='REAL_YT_001', views=500)

        job2 = Job(id='j2', topic_id='top_1', state=JobState.PUBLISHED.value)
        upl_2 = UploadRecord(id='u2', job_id='j2', youtube_video_id='REAL_YT_002', title='Short 2', description='Desc2', status='PUBLISHED', published_at=now - timedelta(hours=48))
        snap_2 = PerformanceSnapshot(upload_id='u2', youtube_video_id='REAL_YT_002', views=20)

        job3 = Job(id='j3', topic_id='top_1', state=JobState.PUBLISHED.value)
        upl_3 = UploadRecord(id='u3', job_id='j3', youtube_video_id='REAL_YT_003', title='Short 3', description='Desc3', status='PUBLISHED', published_at=now - timedelta(hours=48))
        snap_3 = PerformanceSnapshot(upload_id='u3', youtube_video_id='REAL_YT_003', views=500)

        db.add_all([job1, upl_1, snap_1, job2, upl_2, snap_2, job3, upl_3, snap_3])
        db.commit()

        learner = LearningEngine()
        universe = learner.get_verified_analytics_universe(db, now=now)

        assert universe['verified_live_count'] == 3
        assert universe['mature_count'] == 1
        assert universe['maturing_count'] == 2

    def test_05_statistical_evidence_thresholds_and_bounds(self, in_memory_db):
        learner = LearningEngine()

        w1, lift1, conf1, r1 = learner.compute_strategy_weight(sample_count=2, performance_mean=80.0, baseline_performance=50.0)
        assert w1 == 1.000
        assert conf1 == 'INSUFFICIENT_EVIDENCE'

        w2, lift2, conf2, r2 = learner.compute_strategy_weight(sample_count=4, performance_mean=80.0, baseline_performance=50.0)
        assert 0.90 <= w2 <= 1.10
        assert conf2 == 'WEAK_EVIDENCE'

        w3, lift3, conf3, r3 = learner.compute_strategy_weight(sample_count=10, performance_mean=90.0, baseline_performance=50.0)
        assert 1.10 < w3 <= 2.00
        assert conf3 == 'USABLE_EVIDENCE'

        w4, lift4, conf4, r4 = learner.compute_strategy_weight(sample_count=20, performance_mean=1000.0, baseline_performance=10.0)
        assert w4 == 1.80

    def test_06_dashboard_data_provider_authoritative_sync(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()

        top = Topic(id='top_1', title='Test Topic', summary='Summary', category='General History')
        db.add(top)

        for i in range(3):
            job = Job(id=f'job_auth_{i}', topic_id='top_1', state=JobState.PUBLISHED.value)
            upl = UploadRecord(
                id=f'upl_authoritative_{i}',
                job_id=f'job_auth_{i}',
                youtube_video_id=f'REAL_YT_{i:03d}',
                title=f'Authoritative #{i}',
                description=f'Desc #{i}',
                status='PUBLISHED',
                privacy_status='public',
                published_at=now - timedelta(days=2)
            )
            snap = PerformanceSnapshot(
                upload_id=f'upl_authoritative_{i}',
                youtube_video_id=f'REAL_YT_{i:03d}',
                views=250,
                average_view_percentage=80.0
            )
            db.add_all([job, upl, snap])
        db.commit()

        provider = SystemDataProvider()
        live_count = provider.get_verified_live_count(db)
        learning = provider.get_learning_status(db)

        assert live_count == 3
        assert learning['mature_videos_count'] == 3
        assert learning['immature_videos_count'] == 0
        assert learning['total_analytics_cohort'] == 3
        assert learning['data_integrity_error'] is None

    def test_07_reserve_buffer_deficit_calculations(self, in_memory_db):
        provider = SystemDataProvider()

        assert provider.get_buffer_status(ready_stock=0)['needed_replenishment'] == 6
        assert provider.get_buffer_status(ready_stock=5)['needed_replenishment'] == 1
        assert provider.get_buffer_status(ready_stock=6)['needed_replenishment'] == 0
        assert provider.get_buffer_status(ready_stock=10)['needed_replenishment'] == 0
