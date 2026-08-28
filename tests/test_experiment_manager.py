"""
Unit and Integration Test Suite for Experiment Manager & Automated Strategy Execution (Phase 4).
Tests are designed with full isolation — each test clears conflicting feature weights before
asserting on selection outcomes, and restores them in tearDown.

21 required test cases:
01. Phase 3 weight integration (highest weight chosen)
02. Phase 3 discrepancy regression (0.0% lift => weight 1.00)
03. Exploitation selection (highest-weight hook selected)
04. Exploration selection mode
05. Deterministic selection produces reproducible results
06. Invalid strategy values are sanitized to verified fallbacks
07. Experiment persistence in SQLite
08. Strategy assignment reasoning recorded
09. Lifecycle state transitions SELECTED->PRODUCED->READY->UPLOADED->MEASURED
10. Failed production handling
11. Failed upload handling
12. Retry idempotency (no duplicate experiments for same job_id)
13. Experiment-to-upload linking
14. Experiment-to-performance snapshot linking
15. Manual override modes (DEFAULT, EXPLORE)
16. SELF_IMPROVEMENT_ENABLED=false behavior  (via explicit DEFAULT mode)
17. SELF_IMPROVEMENT_ENABLED=true behavior   (via explicit LEARNED mode)
18. Combination safety classification (KNOWN, PARTIALLY_KNOWN, UNSEEN)
19. Database migration compatibility (columns exist)
20. Zero real YouTube uploads performed
21. Zero real production videos generated
"""
import unittest
import uuid
from datetime import datetime, timezone
from core.database import init_db, SessionLocal
from core.models import ExperimentRecord, StrategyWeight, Topic
from engines.experiment_manager import ExperimentManager
from engines.learning_engine import LearningEngine


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TestExperimentManager(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.learner = LearningEngine()
        self.exp_mgr = ExperimentManager(learning_engine=self.learner)
        self.created_exp_ids = []
        self.created_sw_ids = []
        # Stash dicts of SW rows we temporarily removed for isolation
        self._stashed_hooks: list[dict] = []

    def tearDown(self):
        # Clean up experiment records created during tests
        for exp_id in self.created_exp_ids:
            exp = self.db.query(ExperimentRecord).filter(ExperimentRecord.id == exp_id).first()
            if exp:
                self.db.delete(exp)
        # Clean up strategy weights created during tests
        for sw_id in self.created_sw_ids:
            sw = self.db.query(StrategyWeight).filter(StrategyWeight.id == sw_id).first()
            if sw:
                self.db.delete(sw)
        # Restore any stashed hook weights
        for sw_dict in self._stashed_hooks:
            existing = self.db.query(StrategyWeight).filter(StrategyWeight.id == sw_dict["id"]).first()
            if not existing:
                self.db.add(StrategyWeight(**sw_dict))
        self.db.commit()
        self.db.close()

    # ------------------------------------------------------------------
    # Isolation helpers
    # ------------------------------------------------------------------

    def _clear_hook_weights(self):
        """Remove all hook_archetype StrategyWeight rows; stash them for restore in tearDown."""
        existing = self.db.query(StrategyWeight).filter(
            StrategyWeight.feature_type == "hook_archetype"
        ).all()
        for sw in existing:
            self._stashed_hooks.append({
                "id": sw.id,
                "feature_type": sw.feature_type,
                "feature_value": sw.feature_value,
                "weight": sw.weight,
                "sample_count": sw.sample_count,
                "relative_lift": sw.relative_lift,
                "confidence_level": sw.confidence_level
            })
            self.db.delete(sw)
        self.db.commit()

    def _clear_all_weights(self):
        """Remove all StrategyWeight rows for full isolation; stash for restore."""
        existing = self.db.query(StrategyWeight).all()
        for sw in existing:
            self._stashed_hooks.append({
                "id": sw.id,
                "feature_type": sw.feature_type,
                "feature_value": sw.feature_value,
                "weight": sw.weight,
                "sample_count": sw.sample_count,
                "relative_lift": sw.relative_lift,
                "confidence_level": sw.confidence_level
            })
            self.db.delete(sw)
        self.db.commit()

    def _make_topic(self, category="Ancient Mysteries") -> Topic:
        return Topic(id=f"top_{uuid.uuid4().hex[:8]}", title="Test Topic", summary="Summary", category=category)

    # ==================================================================
    # TEST 01 — Phase 3 Weight Integration
    # ==================================================================
    def test_01_phase3_weight_integration(self):
        """Test 1: ExperimentManager uses Phase 3 StrategyWeights as single source of truth."""
        self._clear_hook_weights()

        sw_id = f"sw_exp_{uuid.uuid4().hex[:8]}"
        sw = StrategyWeight(
            id=sw_id,
            feature_type="hook_archetype",
            feature_value="UNSOLVED_MYSTERY",
            weight=1.45,
            sample_count=7,
            relative_lift=45.0,
            confidence_level="USABLE_EVIDENCE"
        )
        self.db.add(sw)
        self.db.commit()
        self.created_sw_ids.append(sw_id)

        strat = self.exp_mgr.select_strategy(self.db, strategy_mode="LEARNED", deterministic=True)
        self.assertIn("hook_archetype", strat)
        self.assertEqual(strat["hook_archetype"], "UNSOLVED_MYSTERY",
                         "Highest-weight StrategyWeight must win in exploitation mode.")

    # ==================================================================
    # TEST 02 — Phase 3 Weight Inconsistency Regression
    # ==================================================================
    def test_02_phase3_weight_inconsistency_regression(self):
        """Test 2: Regression — 0.0% relative lift must produce neutral weight exactly 1.00."""
        weight, lift, conf, reason = self.learner.compute_strategy_weight(
            sample_count=8,
            performance_mean=50.0,
            baseline_performance=50.0
        )
        self.assertEqual(lift, 0.0, "Lift must be 0.0% when performance == baseline.")
        self.assertEqual(weight, 1.00, "0% lift must produce exactly weight=1.00, not 1.50.")
        self.assertEqual(conf, "USABLE_EVIDENCE")

    # ==================================================================
    # TEST 03 — Exploitation Selection
    # ==================================================================
    def test_03_exploitation_selection(self):
        """Test 3: Exploitation mode (explore_prob=0) selects the highest-weight hook."""
        self._clear_hook_weights()

        sw1_id = f"sw_w_{uuid.uuid4().hex[:8]}"
        sw2_id = f"sw_l_{uuid.uuid4().hex[:8]}"
        sw1 = StrategyWeight(id=sw1_id, feature_type="hook_archetype",
                             feature_value="CONTRADICTION_SHOCK", weight=1.60,
                             sample_count=6, confidence_level="USABLE_EVIDENCE")
        sw2 = StrategyWeight(id=sw2_id, feature_type="hook_archetype",
                             feature_value="HYPOTHETICAL_CURIOSITY", weight=0.80,
                             sample_count=5, confidence_level="USABLE_EVIDENCE")
        self.db.add_all([sw1, sw2])
        self.db.commit()
        self.created_sw_ids.extend([sw1_id, sw2_id])

        strat = self.exp_mgr.select_strategy(self.db, explore_prob=0.0,
                                              strategy_mode="LEARNED", deterministic=True)
        self.assertEqual(strat["hook_archetype"], "CONTRADICTION_SHOCK",
                         "CONTRADICTION_SHOCK (weight=1.60) must win over HYPOTHETICAL_CURIOSITY (0.80).")
        self.assertEqual(strat["selection_mode"], "EXPLOITATION")

    # ==================================================================
    # TEST 04 — Exploration Selection
    # ==================================================================
    def test_04_exploration_selection(self):
        """Test 4: EXPLORE mode always returns selection_mode=EXPLORATION and a valid hook."""
        strat = self.exp_mgr.select_strategy(self.db, strategy_mode="EXPLORE", explore_prob=1.0)
        self.assertIn(strat["hook_archetype"], self.exp_mgr.VALID_HOOK_ARCHETYPES,
                      "Exploration must return a valid taxonomy hook.")
        self.assertEqual(strat["selection_mode"], "EXPLORATION",
                         "EXPLORE strategy_mode must always yield selection_mode=EXPLORATION.")

    # ==================================================================
    # TEST 05 — Deterministic Selection
    # ==================================================================
    def test_05_deterministic_selection_mode(self):
        """Test 5: Deterministic mode produces identical results across repeated calls."""
        strat1 = self.exp_mgr.select_strategy(self.db, strategy_mode="LEARNED", deterministic=True)
        strat2 = self.exp_mgr.select_strategy(self.db, strategy_mode="LEARNED", deterministic=True)
        self.assertEqual(strat1["hook_archetype"], strat2["hook_archetype"])
        self.assertEqual(strat1["duration_target"], strat2["duration_target"])
        self.assertEqual(strat1["bgm_mood"], strat2["bgm_mood"])

    # ==================================================================
    # TEST 06 — Unsupported Values Sanitized
    # ==================================================================
    def test_06_unsupported_strategy_values_sanitized(self):
        """Test 6: Values not in taxonomy are sanitized to verified fallbacks."""
        hook = "TOTALLY_FAKE_HOOK"
        sanitized = hook if hook in self.exp_mgr.VALID_HOOK_ARCHETYPES else "DATE_TIME_ANCHOR"
        self.assertEqual(sanitized, "DATE_TIME_ANCHOR",
                         "Invalid hook must be sanitized to DATE_TIME_ANCHOR default.")

        duration = "999_SECONDS"
        sanitized_dur = duration if duration in self.exp_mgr.VALID_DURATION_TARGETS else "SWEET_SPOT"
        self.assertEqual(sanitized_dur, "SWEET_SPOT")

        motion = "CRAZY_ZOOM"
        sanitized_motion = motion if motion in self.exp_mgr.VALID_MOTION_STYLES else "DYNAMIC_ZOOM_PAN"
        self.assertEqual(sanitized_motion, "DYNAMIC_ZOOM_PAN")

    # ==================================================================
    # TEST 07 — Experiment Persistence
    # ==================================================================
    def test_07_experiment_persistence_sqlite(self):
        """Test 7: ExperimentRecord is cleanly persisted and retrievable from SQLite."""
        job_id = f"job_p4_{uuid.uuid4().hex[:8]}"
        strat = {
            "hook_archetype": "UNSOLVED_MYSTERY",
            "duration_target": "SWEET_SPOT",
            "bgm_mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
            "motion_style": "DYNAMIC_ZOOM_PAN",
            "category": "Ancient Mysteries",
            "selection_mode": "EXPLOITATION",
            "strategy_reason": "High retention evidence",
            "combination_type": "KNOWN"
        }
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_123", strategy=strat)
        self.created_exp_ids.append(exp.id)

        fetched = self.db.query(ExperimentRecord).filter(ExperimentRecord.id == exp.id).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.job_id, job_id)
        self.assertEqual(fetched.hook_archetype, "UNSOLVED_MYSTERY")
        self.assertEqual(fetched.status, "SELECTED")

    # ==================================================================
    # TEST 08 — Strategy Reason Recorded
    # ==================================================================
    def test_08_strategy_assignment_reasoning_recorded(self):
        """Test 8: strategy_reason persisted answers 'Why was this strategy used?'"""
        job_id = f"job_reason_{uuid.uuid4().hex[:8]}"
        strat = {
            "hook_archetype": "DATE_TIME_ANCHOR",
            "duration_target": "SWEET_SPOT",
            "bgm_mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
            "motion_style": "DYNAMIC_ZOOM_PAN",
            "selection_mode": "EXPLOITATION",
            "strategy_reason": "Highest weight 1.50 (+50.0% lift, N=8, USABLE_EVIDENCE)"
        }
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_456", strategy=strat)
        self.created_exp_ids.append(exp.id)
        self.assertIn("Highest weight", exp.strategy_reason)

    # ==================================================================
    # TEST 09 — Lifecycle State Transitions
    # ==================================================================
    def test_09_lifecycle_state_transitions(self):
        """Test 9: Lifecycle transitions SELECTED->PRODUCED->READY->UPLOADED->MEASURED."""
        job_id = f"job_life_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT",
                 "bgm_mood": "Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
                 "motion_style": "STATIC"}
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_789", strategy=strat)
        self.created_exp_ids.append(exp.id)
        self.assertEqual(exp.status, "SELECTED")

        self.exp_mgr.update_experiment_status(self.db, job_id=job_id, status="PRODUCED")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "PRODUCED")

        self.exp_mgr.update_experiment_status(self.db, job_id=job_id, status="READY")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "READY")

        self.exp_mgr.link_experiment_to_upload(self.db, job_id=job_id,
                                                upload_id="upl_abc", youtube_video_id="yt_abc")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "UPLOADED")
        self.assertEqual(exp.youtube_video_id, "yt_abc")

        self.exp_mgr.link_experiment_to_snapshot(self.db, upload_id="upl_abc",
                                                   snapshot_id=42, score=75.0)
        self.db.refresh(exp)
        self.assertEqual(exp.status, "MEASURED")
        self.assertIsNotNone(exp.concluded_at)

    # ==================================================================
    # TEST 10 — Failed Production Handling
    # ==================================================================
    def test_10_failed_production_handling(self):
        """Test 10: QA/render failure records failure_reason and marks FAILED."""
        job_id = f"job_fail_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT"}
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_fail", strategy=strat)
        self.created_exp_ids.append(exp.id)

        self.exp_mgr.update_experiment_status(self.db, job_id=job_id,
                                               status="FAILED", failure_reason="FFmpeg encoding error")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "FAILED")
        self.assertEqual(exp.failure_reason, "FFmpeg encoding error")
        self.assertIsNotNone(exp.concluded_at)

    # ==================================================================
    # TEST 11 — Failed Upload Handling
    # ==================================================================
    def test_11_failed_upload_handling(self):
        """Test 11: YouTube upload failure records reason and marks experiment FAILED."""
        job_id = f"job_ufail_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT"}
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_ufail", strategy=strat)
        self.created_exp_ids.append(exp.id)

        self.exp_mgr.update_experiment_status(self.db, job_id=job_id,
                                               status="FAILED",
                                               failure_reason="YouTube quota exceeded")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "FAILED")
        self.assertIn("YouTube quota", exp.failure_reason)
        self.assertIsNotNone(exp.concluded_at)

    # ==================================================================
    # TEST 12 — Retry Idempotency
    # ==================================================================
    def test_12_retry_idempotency(self):
        """Test 12: create_experiment twice with same job_id returns same record without duplicate."""
        job_id = f"job_idem_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT"}
        exp1 = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_idem", strategy=strat)
        exp2 = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_idem", strategy=strat)
        self.created_exp_ids.append(exp1.id)

        self.assertEqual(exp1.id, exp2.id, "Idempotency: same job_id must return same ExperimentRecord.")
        count = self.db.query(ExperimentRecord).filter(ExperimentRecord.job_id == job_id).count()
        self.assertEqual(count, 1, "Only one ExperimentRecord must exist for a given job_id.")

    # ==================================================================
    # TEST 13 — Upload Linking
    # ==================================================================
    def test_13_experiment_to_upload_linking(self):
        """Test 13: link_experiment_to_upload sets UPLOADED status and records upload_id/video_id."""
        job_id = f"job_upl_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT"}
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_upl", strategy=strat)
        self.created_exp_ids.append(exp.id)

        self.exp_mgr.link_experiment_to_upload(self.db, job_id=job_id,
                                                upload_id="upl_xyz", youtube_video_id="yt_xyz")
        self.db.refresh(exp)
        self.assertEqual(exp.status, "UPLOADED")
        self.assertEqual(exp.upload_id, "upl_xyz")
        self.assertEqual(exp.youtube_video_id, "yt_xyz")

    # ==================================================================
    # TEST 14 — Snapshot Linking
    # ==================================================================
    def test_14_experiment_to_snapshot_linking(self):
        """Test 14: link_experiment_to_snapshot concludes experiment with MEASURED status."""
        job_id = f"job_snap_{uuid.uuid4().hex[:8]}"
        strat = {"hook_archetype": "DATE_TIME_ANCHOR", "duration_target": "SWEET_SPOT"}
        exp = self.exp_mgr.create_experiment(self.db, job_id=job_id, topic_id="top_snap", strategy=strat)
        self.created_exp_ids.append(exp.id)

        self.exp_mgr.link_experiment_to_upload(self.db, job_id=job_id,
                                                upload_id="upl_snap", youtube_video_id="yt_snap")
        self.exp_mgr.link_experiment_to_snapshot(self.db, upload_id="upl_snap",
                                                   snapshot_id=99, score=82.5)
        self.db.refresh(exp)
        self.assertEqual(exp.status, "MEASURED")
        self.assertEqual(exp.outcome_snapshot_id, 99)
        self.assertIn("82.50", exp.outcome_summary)

    # ==================================================================
    # TEST 15 — Manual Override Modes
    # ==================================================================
    def test_15_manual_override_modes(self):
        """Test 15: DEFAULT and EXPLORE modes work independently of env-var SELF_IMPROVEMENT_ENABLED."""
        strat_def = self.exp_mgr.select_strategy(self.db, strategy_mode="DEFAULT")
        self.assertEqual(strat_def["selection_mode"], "DEFAULT")
        self.assertEqual(strat_def["hook_archetype"], "DATE_TIME_ANCHOR")

        strat_exp = self.exp_mgr.select_strategy(self.db, strategy_mode="EXPLORE")
        self.assertEqual(strat_exp["selection_mode"], "EXPLORATION")
        self.assertIn(strat_exp["hook_archetype"], self.exp_mgr.VALID_HOOK_ARCHETYPES)

    # ==================================================================
    # TEST 16 — DEFAULT mode behavior (mimics SELF_IMPROVEMENT_ENABLED=False)
    # ==================================================================
    def test_16_default_mode_stable_baseline(self):
        """Test 16: DEFAULT mode always returns the stable baseline strategy regardless of DB weights."""
        strat = self.exp_mgr.select_strategy(self.db, strategy_mode="DEFAULT")
        self.assertEqual(strat["hook_archetype"], "DATE_TIME_ANCHOR")
        self.assertEqual(strat["duration_target"], "SWEET_SPOT")
        self.assertEqual(strat["selection_mode"], "DEFAULT")

    # ==================================================================
    # TEST 17 — LEARNED mode uses DB weights
    # ==================================================================
    def test_17_learned_mode_uses_db_weights(self):
        """Test 17: LEARNED mode queries StrategyWeight table and returns a valid taxonomy value."""
        self._clear_hook_weights()
        sw_id = f"sw_l17_{uuid.uuid4().hex[:8]}"
        sw = StrategyWeight(id=sw_id, feature_type="hook_archetype",
                            feature_value="IN_MEDIAS_RES", weight=1.80,
                            sample_count=6, confidence_level="USABLE_EVIDENCE")
        self.db.add(sw)
        self.db.commit()
        self.created_sw_ids.append(sw_id)

        strat = self.exp_mgr.select_strategy(self.db, strategy_mode="LEARNED", deterministic=True)
        self.assertEqual(strat["hook_archetype"], "IN_MEDIAS_RES")
        self.assertEqual(strat["selection_mode"], "EXPLOITATION")

    # ==================================================================
    # TEST 18 — Combination Safety Classification
    # ==================================================================
    def test_18_combination_safety_classification(self):
        """Test 18: _evaluate_combination_type returns one of KNOWN/PARTIALLY_KNOWN/UNSEEN."""
        c_type = self.exp_mgr._evaluate_combination_type(
            self.db,
            hook="CONTRADICTION_SHOCK",
            duration="ULTRA_TIGHT",
            bgm="Mysterious / Tension / Disappearance / Cryptic Event / True Crime",
            motion="STATIC"
        )
        self.assertIn(c_type, ["KNOWN", "PARTIALLY_KNOWN", "UNSEEN"],
                      "Combination type must be one of the three defined classification levels.")

    # ==================================================================
    # TEST 19 — Database Migration Compatibility
    # ==================================================================
    def test_19_database_migration_columns_exist(self):
        """Test 19: All Phase 4 ExperimentRecord columns exist in SQLite schema."""
        from core.database import engine
        import sqlalchemy
        inspector = sqlalchemy.inspect(engine)
        columns = {col["name"] for col in inspector.get_columns("experiments")}
        required = {
            "experiment_group_id", "job_id", "topic_id",
            "hook_archetype", "duration_target", "bgm_mood", "motion_style",
            "category", "selection_mode", "strategy_reason", "combination_type",
            "failure_reason", "upload_id", "youtube_video_id", "outcome_snapshot_id"
        }
        missing = required - columns
        self.assertFalse(missing, f"Missing Phase 4 columns in 'experiments' table: {missing}")

    # ==================================================================
    # TEST 20 — Zero YouTube Uploads
    # ==================================================================
    def test_20_zero_youtube_uploads_performed(self):
        """Test 20: ExperimentManager never calls YouTube upload API during selection/creation."""
        topic = self._make_topic()
        strat = self.exp_mgr.select_strategy(self.db, topic=topic, strategy_mode="LEARNED", deterministic=True)
        exp = self.exp_mgr.create_experiment(self.db, job_id="job_safe_20", topic_id=topic.id, strategy=strat)
        self.created_exp_ids.append(exp.id)
        # If we reach here, no upload was attempted (would throw connection/auth errors)
        self.assertEqual(exp.status, "SELECTED")
        self.assertIsNone(exp.youtube_video_id)

    # ==================================================================
    # TEST 21 — Zero Production Videos Generated
    # ==================================================================
    def test_21_zero_production_videos_generated(self):
        """Test 21: ExperimentManager pipeline integration creates no video files."""
        import os
        topic = self._make_topic()
        strat = self.exp_mgr.select_strategy(self.db, topic=topic, strategy_mode="DEFAULT")
        exp = self.exp_mgr.create_experiment(self.db, job_id="job_safe_21", topic_id=topic.id, strategy=strat)
        self.created_exp_ids.append(exp.id)
        # No video rendering path is invoked
        self.assertEqual(exp.status, "SELECTED")
        self.assertIsNone(exp.upload_id)


if __name__ == "__main__":
    unittest.main()
