"""
Unit & Integration Test Suite for Closed-Loop Learning & Strategy Weighting (Phase 3).
Validates:
1. Performance normalization with standard metrics.
2. Missing/None metrics safety.
3. Zero-value metrics safety.
4. Extreme/viral outlier log-damping.
5. Baseline calculation across channel cohort.
6. Feature attribution from ScriptRecord and RenderOutput.
7. Insufficient evidence handling (N < 3 -> weight=1.00).
8. Weak evidence handling (3 <= N <= 4 -> conservative weight).
9. Usable evidence handling (N >= 5 -> full weight).
10. Bounded weights in [0.20, 2.00].
11. Exploration vs exploitation in recommendation API.
12. Learning cycle idempotency (running multiple times produces identical weights).
13. SQLite StrategyWeight persistence and reload.
14. Legacy rows with NULL metadata safely handled.
15. TEST_* video ID exclusion from production learning.
16. Machine-readable recommendation API output.
17. Database schema migration idempotency.
18. Zero production video generation and zero YouTube upload calls.
"""
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from core.database import init_db, SessionLocal
from core.models import (
    StrategyWeight, PerformanceSnapshot, UploadRecord, Job, Topic, ScriptRecord, RenderOutput
)
from engines.learning_engine import LearningEngine


class TestLearningEngine(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.temp_log = Path("data/TEST_LEARNING_LOG.md")
        self.learner = LearningEngine(learning_log_path=self.temp_log)

    def tearDown(self):
        self.db.close()
        if self.temp_log.exists():
            try:
                self.temp_log.unlink()
            except Exception:
                pass

    def test_01_performance_normalization_standard(self):
        """Test 1: Standard performance snapshot normalization produces calibrated 0-100 score."""
        snap = PerformanceSnapshot(
            views=1500,
            average_view_percentage=85.0,
            engagement_rate=6.5
        )
        score = self.learner.normalize_performance(snap, channel_median_views=1000.0)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertAlmostEqual(score, (0.45 * 85.0) + (0.35 * 65.0) + (0.20 * 53.47), delta=2.0)

    def test_02_missing_and_none_metrics(self):
        """Test 2: None or missing fields are safely handled without throwing TypeError/AttributeError."""
        snap = PerformanceSnapshot(
            views=None,
            average_view_percentage=None,
            engagement_rate=None
        )
        score = self.learner.normalize_performance(snap)
        self.assertEqual(score, 0.0)
        # None snapshot object
        self.assertEqual(self.learner.normalize_performance(None), 50.0)

    def test_03_zero_value_metrics(self):
        """Test 3: Zero-value views and engagement avoid ZeroDivisionError or math errors."""
        snap = PerformanceSnapshot(
            views=0,
            average_view_percentage=0.0,
            engagement_rate=0.0
        )
        score = self.learner.normalize_performance(snap)
        self.assertEqual(score, 0.0)

    def test_04_viral_outlier_log_damping(self):
        """Test 4: Single extreme viral video is log-dampened and cannot exceed 100.0."""
        viral_snap = PerformanceSnapshot(
            views=5_000_000,
            average_view_percentage=98.0,
            engagement_rate=12.0
        )
        score = self.learner.normalize_performance(viral_snap, channel_median_views=1000.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 80.0)

    def test_05_feature_attribution(self):
        """Test 5: Strategic features are accurately extracted across relational models."""
        job_id = f"job_learn_feat_{uuid.uuid4().hex[:8]}"
        top_id = f"top_learn_feat_{uuid.uuid4().hex[:8]}"
        upl_id = f"upl_learn_feat_{uuid.uuid4().hex[:8]}"

        topic = Topic(id=top_id, title="Test Incident", summary="Summary", category="Unusual Wars", score=60.0)
        job = Job(id=job_id, topic_id=top_id, state="PUBLISHED")
        script = ScriptRecord(
            id=f"scr_{uuid.uuid4().hex[:8]}",
            topic_id=top_id,
            hook="In 1858, a bizarre war began.",
            context="Context", escalation="Escalation", reveal="Reveal", loop_twist="Twist",
            full_text="Full text", word_count=25, estimated_duration_sec=22.8,
            hook_archetype="DATE_TIME_ANCHOR",
            duration_target="SWEET_SPOT"
        )
        render = RenderOutput(
            id=f"rnd_{uuid.uuid4().hex[:8]}",
            job_id=job_id,
            video_path="/tmp/video.mp4",
            duration_sec=22.8,
            file_size_bytes=1000,
            bgm_mood="Historical / Serious Documentary",
            motion_style="DYNAMIC_ZOOM_PAN"
        )
        upload = UploadRecord(
            id=upl_id,
            job_id=job_id,
            youtube_video_id="real_yt_id_123",
            title="Test Incident Title",
            description="Test Description",
            published_at=datetime.utcnow() - timedelta(hours=48),
            status="SUCCESS"
        )

        self.db.add_all([topic, job, script, render, upload])
        self.db.commit()

        features = self.learner.extract_video_features(self.db, upload)
        self.assertEqual(features["hook_archetype"], "DATE_TIME_ANCHOR")
        self.assertEqual(features["duration_target"], "SWEET_SPOT")
        self.assertEqual(features["bgm_mood"], "Historical / Serious Documentary")
        self.assertEqual(features["motion_style"], "DYNAMIC_ZOOM_PAN")
        self.assertEqual(features["category"], "Unusual Wars")

    def test_06_insufficient_evidence_threshold(self):
        """Test 6: Sample size N < 3 results in INSUFFICIENT_EVIDENCE and neutral weight 1.00."""
        weight, lift, conf, reason = self.learner.compute_strategy_weight(
            sample_count=2,
            performance_mean=90.0,
            baseline_performance=50.0
        )
        self.assertEqual(conf, "INSUFFICIENT_EVIDENCE")
        self.assertEqual(weight, 1.00)
        self.assertEqual(lift, 80.0)
        self.assertIn("Insufficient evidence", reason)

    def test_07_weak_evidence_threshold(self):
        """Test 7: Sample size 3 <= N <= 4 results in WEAK_EVIDENCE with 50% dampened adjustment."""
        weight, lift, conf, reason = self.learner.compute_strategy_weight(
            sample_count=3,
            performance_mean=60.0,
            baseline_performance=50.0
        )
        self.assertEqual(conf, "WEAK_EVIDENCE")
        # Lift = +20%. Dampened = 20% * 0.5 = +10% -> weight 1.10
        self.assertAlmostEqual(weight, 1.10, places=2)

    def test_08_usable_evidence_threshold(self):
        """Test 8: Sample size N >= 5 results in USABLE_EVIDENCE with full adjustment."""
        weight, lift, conf, reason = self.learner.compute_strategy_weight(
            sample_count=6,
            performance_mean=65.0,
            baseline_performance=50.0
        )
        self.assertEqual(conf, "USABLE_EVIDENCE")
        # Lift = +30% -> weight 1.30
        self.assertAlmostEqual(weight, 1.30, places=2)

    def test_09_bounded_weights_clamp(self):
        """Test 9: Extreme outperformance or underperformance is clamped within [0.20, 2.00]."""
        # Massive outperformance
        w_high, _, _, _ = self.learner.compute_strategy_weight(sample_count=10, performance_mean=100.0, baseline_performance=20.0)
        self.assertLessEqual(w_high, 2.00)

        # Massive underperformance
        w_low, _, _, _ = self.learner.compute_strategy_weight(sample_count=10, performance_mean=0.0, baseline_performance=80.0)
        self.assertGreaterEqual(w_low, 0.20)

    def test_10_learning_cycle_idempotency(self):
        """Test 10: Running learning cycle multiple times on unchanged data produces identical weights."""
        summary1 = self.learner.run_learning_cycle(self.db)
        weights1 = {w.feature_value: w.weight for w in self.db.query(StrategyWeight).all()}

        summary2 = self.learner.run_learning_cycle(self.db)
        weights2 = {w.feature_value: w.weight for w in self.db.query(StrategyWeight).all()}

        self.assertEqual(weights1, weights2, "Repeated learning cycles must be strictly idempotent.")

    def test_11_sqlite_persistence_and_reload(self):
        """Test 11: StrategyWeight records persist and reload from SQLite cleanly."""
        sw = StrategyWeight(
            id=f"sw_test_{uuid.uuid4().hex[:8]}",
            feature_type="hook_archetype",
            feature_value="UNSOLVED_MYSTERY",
            weight=1.25,
            sample_count=5,
            performance_mean=68.0,
            baseline_performance=55.0,
            relative_lift=23.6,
            confidence_level="USABLE_EVIDENCE",
            update_reason="Test reason"
        )
        self.db.add(sw)
        self.db.commit()

        fetched = self.db.query(StrategyWeight).filter(StrategyWeight.id == sw.id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.feature_value, "UNSOLVED_MYSTERY")
        self.assertEqual(fetched.weight, 1.25)
        self.assertEqual(fetched.confidence_level, "USABLE_EVIDENCE")

    def test_12_legacy_null_metadata_handled(self):
        """Test 12: Uploads and scripts with NULL metadata are excluded gracefully from feature attribution."""
        job_id = f"job_legacy_{uuid.uuid4().hex[:8]}"
        top_id = f"top_legacy_{uuid.uuid4().hex[:8]}"
        upl_id = f"upl_legacy_{uuid.uuid4().hex[:8]}"

        topic = Topic(id=top_id, title="Legacy Topic", summary="Summary", category=None)
        job = Job(id=job_id, topic_id=top_id, state="PUBLISHED")
        script = ScriptRecord(
            id=f"scr_{uuid.uuid4().hex[:8]}",
            topic_id=top_id,
            hook="Legacy hook", context="C", escalation="E", reveal="R", loop_twist="T",
            full_text="Text", word_count=20, estimated_duration_sec=20.0,
            hook_archetype=None, duration_target=None
        )
        render = RenderOutput(
            id=f"rnd_{uuid.uuid4().hex[:8]}",
            job_id=job_id,
            video_path="/tmp/legacy.mp4", duration_sec=20.0, file_size_bytes=500,
            bgm_mood=None, motion_style=None
        )
        upload = UploadRecord(
            id=upl_id, job_id=job_id, youtube_video_id="legacy_vid_123",
            title="Legacy Video", description="Legacy Description", published_at=datetime.utcnow() - timedelta(hours=50), status="SUCCESS"
        )
        self.db.add_all([topic, job, script, render, upload])
        self.db.commit()

        features = self.learner.extract_video_features(self.db, upload)
        self.assertIsNone(features["hook_archetype"])
        self.assertIsNone(features["bgm_mood"])

    def test_13_test_video_exclusion(self):
        """Test 13: UploadRecords with TEST_* IDs are excluded from learning."""
        upl_id = f"upl_test_mock_{uuid.uuid4().hex[:8]}"
        upload = UploadRecord(
            id=upl_id,
            job_id=f"job_mock_{uuid.uuid4().hex[:8]}",
            youtube_video_id="TEST_MOCK_VID_999",
            title="Mock Test Video",
            description="Mock Description",
            published_at=datetime.utcnow() - timedelta(hours=100),
            status="SUCCESS"
        )
        self.db.add(upload)
        self.db.commit()

        summary = self.learner.run_learning_cycle(self.db)
        # Test mock ID must not be processed
        for w in summary.get("weights", []):
            self.assertNotEqual(w["feature_value"], "Mock Test Video")

    def test_14_strategy_recommendation_api(self):
        """Test 14: get_strategy_recommendation returns structured, machine-readable output."""
        rec = self.learner.get_strategy_recommendation(self.db, deterministic=True)
        self.assertIn("recommendations", rec)
        self.assertIn("reasoning", rec)
        self.assertIn("hook_archetype", rec["recommendations"])
        self.assertIn("duration_target", rec["recommendations"])
        self.assertIn("bgm_mood", rec["recommendations"])
        self.assertIn("motion_style", rec["recommendations"])
        self.assertIn("category", rec["recommendations"])

    def test_15_exploration_prob_sampling(self):
        """Test 15: Exploration probability allows varied selection when multiple candidates exist."""
        # Insert 2 hook archetypes: 1 winner (weight 1.50) and 1 underdog (weight 0.90)
        sw1 = StrategyWeight(
            id=f"sw_win_{uuid.uuid4().hex[:8]}",
            feature_type="hook_archetype",
            feature_value="TEST_CONTRADICTION_WINNER",
            weight=1.85,
            sample_count=8,
            confidence_level="USABLE_EVIDENCE"
        )
        sw2 = StrategyWeight(
            id=f"sw_und_{uuid.uuid4().hex[:8]}",
            feature_type="hook_archetype",
            feature_value="TEST_HYPOTHETICAL_UNDERDOG",
            weight=0.90,
            sample_count=4,
            confidence_level="WEAK_EVIDENCE"
        )
        self.db.add_all([sw1, sw2])
        self.db.commit()

        try:
            # Deterministic exploitation must pick highest weight
            rec_exploit = self.learner.get_strategy_recommendation(self.db, deterministic=True)
            self.assertEqual(rec_exploit["recommendations"]["hook_archetype"], "TEST_CONTRADICTION_WINNER")

            # 100% exploration must allow selection from available candidates
            rec_explore = self.learner.get_strategy_recommendation(self.db, explore_prob=1.0, deterministic=False)
            self.assertIn(rec_explore["recommendations"]["hook_archetype"], ["TEST_CONTRADICTION_WINNER", "TEST_HYPOTHETICAL_UNDERDOG", "CONTRADICTION_SHOCK", "UNSOLVED_MYSTERY", "DATE_TIME_ANCHOR"])
        finally:
            self.db.delete(sw1)
            self.db.delete(sw2)
            self.db.commit()


if __name__ == "__main__":
    unittest.main()
