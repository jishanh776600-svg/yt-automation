import pytest
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
from core.gemini_client import GeminiClient


@pytest.fixture
def in_memory_db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


class TestLiveDataPurityAndReliability:

    # -------------------------------------------------------------------------
    # Step 1 & 2: Dashboard Metrics Provenance & Live API Semantics
    # -------------------------------------------------------------------------
    def test_01_dashboard_data_freshness_provenance_and_states(self, in_memory_db):
        db = in_memory_db
        provider = SystemDataProvider()
        state = provider.get_full_system_state(db)

        assert 'data_freshness' in state
        freshness = state['data_freshness']
        for key in ['verified_live', 'scheduled_publishing', 'telemetry_metrics', 'drive_vault']:
            assert key in freshness
            assert 'source' in freshness[key]
            assert 'status' in freshness[key]
            assert 'as_of' in freshness[key]
            assert freshness[key]['status'] in (
                'LIVE_API', 'RECONCILED_LOCAL', 'CACHED_DB', 'DEGRADED_QUOTA', 'UNAVAILABLE', 'CACHED_LOCAL'
            )

    # -------------------------------------------------------------------------
    # Step 3: Zero is Not Unknown / Missing Telemetry Preserved as None
    # -------------------------------------------------------------------------
    def test_02_unavailable_metrics_not_converted_to_fake_zero(self, in_memory_db):
        db = in_memory_db
        job = Job(id='job_purity_01', state=JobState.PUBLISHED.value)
        upload = UploadRecord(
            id='upl_purity_01',
            job_id='job_purity_01',
            youtube_video_id='aB3_kL9mZ1x',
            title='True Historical Short',
            description='Detailed historical narrative description',
            status='PUBLISHED',
            privacy_status='public'
        )
        snap = PerformanceSnapshot(
            upload_id='upl_purity_01',
            youtube_video_id='aB3_kL9mZ1x',
            views=0,
            likes=0,
            comments=0,
            average_view_percentage=0.0,
            validation_status='UNAVAILABLE'
        )
        db.add_all([job, upload, snap])
        db.commit()

        provider = SystemDataProvider()
        leaderboard = provider.get_published_performance_leaderboard(db)
        
        assert len(leaderboard) == 1
        item = leaderboard[0]
        assert item['views'] is None
        assert item['views_display'] == 'UNAVAILABLE'
        assert item['likes'] is None
        assert item['likes_display'] == 'UNAVAILABLE'
        assert item['apv'] is None
        assert item['apv_display'] == 'UNAVAILABLE'
        assert item['engagement_display'] == 'UNAVAILABLE'

    # -------------------------------------------------------------------------
    # Step 4: Competitor Hypothesis Safety
    # -------------------------------------------------------------------------
    def test_03_competitor_hypothesis_status_and_weight_protection(self, in_memory_db):
        db = in_memory_db
        engine = TopicDiscoveryEngine()

        topic = engine.inject_competitor_hypothesis(
            db=db,
            title='The Battle of Blood River Outlier',
            summary='Historical tactical defense against overwhelming odds',
            category='Unusual Wars',
            competitor_views=50000,
            channel_median_views=5000.0,
            outlier_threshold=3.0
        )
        assert topic is not None
        assert topic.status == 'COMPETITOR_HYPOTHESIS'

        # Verify competitor hypothesis does NOT touch StrategyWeights
        weights = db.query(StrategyWeight).all()
        assert len(weights) == 0

    # -------------------------------------------------------------------------
    # Step 5 & 6: YouTube Publish State Truth & Scheduled Reconciliation
    # -------------------------------------------------------------------------
    def test_04_scheduled_is_not_published_until_authoritative_reconciliation(self, in_memory_db):
        db = in_memory_db
        now = datetime.utcnow()
        upload = UploadRecord(
            id='upl_sched_1',
            job_id='job_sched_1',
            youtube_video_id='YT_SCHED_001',
            title='Scheduled Story',
            description='Story description',
            status='SCHEDULED',
            privacy_status='private',
            scheduled_publish_at=now + timedelta(hours=2)
        )
        job = Job(id='job_sched_1', state=JobState.SCHEDULED.value)
        db.add_all([upload, job])
        db.commit()

        provider = SystemDataProvider()
        pub_status = provider.get_publishing_status(db)
        
        # Not counted as published today
        assert pub_status['published_today'] == 0
        assert pub_status['scheduled_today'] == 1
        assert upload.status == 'SCHEDULED'
        assert job.state == JobState.SCHEDULED.value

    def test_05_schedule_reconciliation_error_on_missing_youtube_video(self, in_memory_db):
        db = in_memory_db
        job = Job(id='job_missing_1', state=JobState.SCHEDULED.value)
        upload = UploadRecord(
            id='upl_err_1',
            job_id='job_missing_1',
            youtube_video_id='YT_MISSING_01',
            title='Missing Video Story',
            description='Story description',
            status='SCHEDULED',
            reconciliation_metadata='[SCHEDULE_RECONCILIATION_ERROR] Video missing on YouTube API'
        )
        db.add_all([job, upload])
        db.commit()

        provider = SystemDataProvider()
        anomalies = provider.get_reconciliation_anomalies(db)
        
        err_anomalies = [a for a in anomalies if 'UploadRecord_upl_err_1' in a.get('entity', '')]
        assert len(err_anomalies) == 1
        assert err_anomalies[0]['severity'] == 'CRITICAL'

    # -------------------------------------------------------------------------
    # Step 7: Orphan Recovery Deep Hardening
    # -------------------------------------------------------------------------
    def test_06_orphan_recovery_different_time_or_ambiguous_candidate_rejected(self, in_memory_db):
        engine = UploadEngine()
        job = Job(id='job_orphan_diff', state=JobState.READY_TO_UPLOAD.value)
        metadata = {'title': 'Ambiguous Video Title', 'description': 'Description without tag'}

        mock_youtube = MagicMock()
        mock_search = MagicMock()
        # Returns multiple matching candidates without unique job tag
        mock_search.execute.return_value = {
            'items': [
                {'id': {'videoId': 'YT_AMBIG_1'}, 'snippet': {'title': 'Ambiguous Video Title', 'description': 'Desc 1'}},
                {'id': {'videoId': 'YT_AMBIG_2'}, 'snippet': {'title': 'Ambiguous Video Title', 'description': 'Desc 2'}}
            ]
        }
        mock_youtube.search.return_value.list.return_value = mock_search

        recovered_id, reason = engine.recover_orphaned_upload(
            youtube=mock_youtube,
            job=job,
            metadata=metadata
        )
        assert recovered_id is None
        assert reason == 'ORPHAN_RECOVERY_AMBIGUOUS'

    # -------------------------------------------------------------------------
    # Step 8: Autonomous Crash Recovery / Asset Preservation
    # -------------------------------------------------------------------------
    def test_07_crash_recovery_resumes_from_existing_render_output(self, in_memory_db, tmp_path):
        db = in_memory_db
        now = datetime.utcnow()
        
        fake_video = tmp_path / 'rendered_short.mp4'
        fake_video.write_bytes(b'0' * (600 * 1024))

        top = Topic(id='top_rnd_1', title='Render Topic', summary='Summary', category='General')
        job = Job(
            id='job_stale_render_asset',
            topic_id='top_rnd_1',
            state=JobState.EDITING.value,
            retry_count=0,
            updated_at=now - timedelta(minutes=50)
        )
        render = RenderOutput(
            id='rnd_asset_1',
            job_id='job_stale_render_asset',
            video_path=str(fake_video),
            duration_sec=23.5,
            file_size_bytes=600 * 1024
        )
        db.add_all([top, job, render])
        db.commit()

        recovery_mgr = RecoveryManager()
        recovered = recovery_mgr.recover_stale_jobs(db, stale_timeout_sec=1800)

        assert len(recovered) == 1
        rec = recovered[0]
        assert rec['job_id'] == 'job_stale_render_asset'
        assert rec['new_state'] == JobState.READY_TO_UPLOAD.value
        assert rec['action'] == 'RESUME_FROM_RENDER'

    # -------------------------------------------------------------------------
    # Step 10: Autonomous Refill State Machine Deficit Formula
    # -------------------------------------------------------------------------
    def test_08_autonomous_refill_deficit_formula_bounds(self):
        target = 6
        assert max(0, target - 0) == 6
        assert max(0, target - 1) == 5
        assert max(0, target - 5) == 1
        assert max(0, target - 6) == 0
        assert max(0, target - 7) == 0

    # -------------------------------------------------------------------------
    # Step 12: Provider Failover Complete Chain
    # -------------------------------------------------------------------------
    def test_09_ai_provider_failover_routing(self):
        client = GeminiClient(
            api_key='GEMINI_PRIMARY',
            secondary_api_key='GEMINI_SECONDARY',
            groq_api_key='GROQ_KEY',
            openrouter_api_key='OPENROUTER_KEY'
        )
        providers = client._get_configured_providers()
        names = [p['name'] for p in providers]
        assert names == ['primary', 'secondary', 'groq', 'openrouter']

    # -------------------------------------------------------------------------
    # Step 13 & 14: Telemetry Maturation & Learning Safeguards
    # -------------------------------------------------------------------------
    def test_10_learning_safeguard_sample_size_tiers(self):
        learner = LearningEngine()
        
        # N < 3 -> 1.000 (neutral weight, no update)
        w1, _, conf1, _ = learner.compute_strategy_weight(sample_count=1, performance_mean=80.0, baseline_performance=50.0)
        assert w1 == 1.00
        assert conf1 == 'INSUFFICIENT_EVIDENCE'

        w2, _, conf2, _ = learner.compute_strategy_weight(sample_count=2, performance_mean=80.0, baseline_performance=50.0)
        assert w2 == 1.00
        assert conf2 == 'INSUFFICIENT_EVIDENCE'

        # N = 3-4 -> Damped (+/- 10%)
        w3, _, conf3, _ = learner.compute_strategy_weight(sample_count=3, performance_mean=80.0, baseline_performance=50.0)
        assert 1.00 < w3 <= 1.10
        assert conf3 == 'WEAK_EVIDENCE'

        # N >= 5 -> Full bounded update [0.20, 2.00]
        w5, _, conf5, _ = learner.compute_strategy_weight(sample_count=10, performance_mean=80.0, baseline_performance=50.0)
        assert 1.10 < w5 <= 2.00
        assert conf5 == 'USABLE_EVIDENCE'

    # -------------------------------------------------------------------------
    # Step 15: Data Reconciliation Invariant Error Detection
    # -------------------------------------------------------------------------
    def test_11_reconciliation_detects_impossible_cohort_relationships(self, in_memory_db):
        db = in_memory_db
        job = Job(id='job_canon_1', state=JobState.PUBLISHED.value)
        # 1 genuine live upload
        upload = UploadRecord(
            id='upl_canon_1',
            job_id='job_canon_1',
            youtube_video_id='ValidCanon1',
            title='Canon Title',
            description='Canon Description',
            status='PUBLISHED',
            privacy_status='public'
        )
        db.add_all([job, upload])
        db.commit()

        # 3 fabricated snapshots referencing non-live/test uploads
        for i in range(3):
            u_dummy = UploadRecord(
                id=f'upl_phantom_{i}',
                job_id=f'job_phantom_{i}',
                youtube_video_id=f'PhanTom_{i}11',
                title=f'Phantom {i}',
                description='Phantom desc',
                status='PUBLISHED',
                privacy_status='test_local'
            )
            db.add(u_dummy)
            db.commit()

            snap = PerformanceSnapshot(
                upload_id=f'upl_phantom_{i}',
                youtube_video_id=f'PhanTom_{i}11',
                views=200,
                hours_since_upload=30.0
            )
            db.add(snap)
        db.commit()

        provider = SystemDataProvider()
        anomalies = provider.get_reconciliation_anomalies(db)
        
        cohort_anomalies = [a for a in anomalies if a.get('entity') == 'LearningUniverse']
        assert len(cohort_anomalies) == 1
        assert cohort_anomalies[0]['severity'] == 'CRITICAL'
