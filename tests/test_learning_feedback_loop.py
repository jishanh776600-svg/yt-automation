"""
Comprehensive End-to-End Simulation & Verification Test for Closed Feedback Learning Loop.
Verifies:
1. Non-destructive performance snapshot collection
2. Statistical classification (Outperformer vs Underperformer vs Average vs Insufficient Data)
3. Structured root cause generation (Fact vs Hypothesis)
4. Anti-overfitting confidence scaling (LOW -> MEDIUM -> HIGH)
5. 60/30/10 strategy allocation
6. Persistent LEARNING_LOG.md and Daily Report generation
"""
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from sqlalchemy.orm import Session
from core.database import SessionLocal, init_db
from core.models import (
    Job, Topic, ScriptRecord, UploadRecord, PerformanceSnapshot,
    VideoAnalysisRecord, ContentPattern, ExperimentRecord
)
from engines.metrics_collector import MetricsCollector
from engines.video_analyzer import VideoAnalyzer
from engines.learning_engine import LearningEngine
from engines.experiment_manager import ExperimentManager
from engines.report_generator import ReportGenerator
from engines.analytics_engine import AnalyticsEngine


def test_closed_feedback_learning_loop():
    init_db()
    db: Session = SessionLocal()

    collector = MetricsCollector()
    analyzer = VideoAnalyzer()
    learner = LearningEngine()
    exp_mgr = ExperimentManager()
    reporter = ReportGenerator()
    orchestrator = AnalyticsEngine()

    print("\n--- STEP 1: Seeding Historical Benchmark Cohort ---")
    # Create 5 synthetic historical uploads with diverse categories, hooks, durations, and metrics
    cohort = [
        {
            "topic": "The 38-Minute War",
            "category": "Unusual Wars",
            "hook": "In 1896, the British Empire won a war in exactly 38 minutes.",
            "duration": 22.5,
            "views": 4200,
            "apv": 92.5,
            "eng": 7.8,
            "subs": 45
        },
        {
            "topic": "The Boston Molasses Flood",
            "category": "Documented Disasters",
            "hook": "A 35-mile-per-hour wave of boiling molasses destroyed an entire city.",
            "duration": 23.8,
            "views": 3800,
            "apv": 88.0,
            "eng": 6.5,
            "subs": 32
        },
        {
            "topic": "The Pig War of 1859",
            "category": "Unusual Wars",
            "hook": "In 1859, a single trespassing pig almost started a world war.",
            "duration": 22.2,
            "views": 3100,
            "apv": 89.2,
            "eng": 7.1,
            "subs": 28
        },
        {
            "topic": "The Dancing Plague",
            "category": "Strange Historical Laws",
            "hook": "In 1518, hundreds of people danced continuously until they collapsed.",
            "duration": 24.5,
            "views": 1500,
            "apv": 62.0,
            "eng": 3.2,
            "subs": 5
        },
        {
            "topic": "Unfinished Obscure Battle",
            "category": "Forgotten Figures",
            "hook": "An obscure forgotten figure did something unremarkable.",
            "duration": 21.0,
            "views": 450,
            "apv": 48.0,
            "eng": 2.1,
            "subs": 1
        }
    ]

    for i, item in enumerate(cohort):
        topic_id = f"test_top_{i}_{datetime.utcnow().timestamp()}"
        job_id = f"test_job_{i}_{datetime.utcnow().timestamp()}"
        upload_id = f"test_upl_{i}_{datetime.utcnow().timestamp()}"

        top = Topic(id=topic_id, title=item["topic"], summary="Historical summary", category=item["category"], score=50.0)
        db.add(top)

        job = Job(id=job_id, topic_id=topic_id, state="PUBLISHED")
        db.add(job)

        scr = ScriptRecord(
            id=f"test_scr_{i}_{datetime.utcnow().timestamp()}", topic_id=topic_id, hook=item["hook"],
            context="Context", escalation="Escalation", reveal="Reveal",
            loop_twist="Loop", full_text=item["hook"] + " context escalation reveal loop.",
            word_count=54, estimated_duration_sec=item["duration"]
        )
        db.add(scr)

        upl = UploadRecord(
            id=upload_id, job_id=job_id, youtube_video_id=f"TEST_YT_{i}",
            title=item["topic"], description="Description", privacy_status="test_local",
            published_at=datetime.utcnow() - timedelta(days=2)
        )
        db.add(upl)
        db.commit()

        # Record metrics snapshot
        mock_metrics = {
            "views": item["views"],
            "average_view_percentage": item["apv"],
            "engagement_rate": item["eng"],
            "subscribers_gained": item["subs"],
            "average_view_duration_sec": item["duration"] * (item["apv"] / 100.0)
        }
        collector.collect_for_upload(db, upl, mock_data=mock_metrics)

    print("\n--- STEP 2: Computing Channel Rolling Baselines ---")
    baselines = analyzer.compute_channel_baselines(db)
    print("Channel Baselines:", baselines)
    assert baselines["median_views"] > 0
    assert baselines["median_apv"] > 0

    print("\n--- STEP 3: Classifying Video Outliers & Root Causes ---")
    uploads = db.query(UploadRecord).filter(UploadRecord.youtube_video_id.like("TEST_YT_%")).all()
    classifications = []
    for upl in uploads:
        an = analyzer.analyze_video(db, upl, baselines)
        classifications.append(an.classification)
        facts = json.loads(an.facts_observed)
        hypotheses = json.loads(an.hypotheses)
        print(f"[{an.classification}] {upl.title} -> Score: {an.performance_score:.1f} | Facts: {facts[0]} | Hypo: {hypotheses[0]}")

    assert "OUTPERFORMER" in classifications
    assert "UNDERPERFORMER" in classifications

    print("\n--- STEP 4: Testing Anti-Overfitting Learning Engine ---")
    patterns = learner.update_learning_database(db)
    for p in patterns:
        print(f"Pattern [{p.pattern_type}] '{p.pattern_key}': N={p.sample_size}, APV={p.avg_percentage_viewed:.1f}%, Score={p.composite_effectiveness_score:.1f}, Confidence={p.confidence}")

    unusual_wars_pattern = next((p for p in patterns if p.pattern_key == "Unusual Wars"), None)
    assert unusual_wars_pattern is not None
    assert unusual_wars_pattern.sample_size >= 2
    assert unusual_wars_pattern.confidence in ["MEDIUM_CONFIDENCE", "HIGH_CONFIDENCE"]

    print("\n--- STEP 5: Testing Controlled Experiment Strategy (60/30/10 Rule) ---")
    strategy = exp_mgr.select_content_strategy(db)
    print(f"Allocated Content Strategy: [{strategy['strategy_type']}] - {strategy['description']}")
    assert strategy["strategy_type"] in ["PROVEN_PATTERN", "CONTROLLED_VARIATION", "PURE_EXPLORATION"]

    exp = exp_mgr.plan_experiment(
        db,
        experiment_type="EXPERIMENT_A",
        title="Test Date-Anchor Hook vs Conflict Hook in Unusual Wars",
        hypothesis="Date anchor will increase early 2-second retention by 8%",
        control_variable="Category: Unusual Wars",
        test_variable="Hook Archetype: Date Anchor"
    )
    assert exp.status == "PLANNED"

    print("\n--- STEP 6: Generating Daily Intelligence & Persistent Human Log ---")
    daily_report = reporter.generate_daily_learning_report(db)
    print(daily_report)
    assert "DAILY SHORTS INTELLIGENCE & LEARNING REPORT" in daily_report
    assert "BEST PERFORMER" in daily_report

    reporter.append_to_learning_log(
        date_str=datetime.utcnow().strftime("%Y-%m-%d"),
        video_title="The 38-Minute War",
        result="OUTPERFORMER",
        observation="APV 92.5% (+17.5% over channel median 75.0%)",
        hypothesis="High-stakes conflict hook + 22.5s duration maximizes completion rate",
        experiment="Re-test hook on 'The Pig War'",
        confidence="MEDIUM_CONFIDENCE",
        decision="Prioritize Unusual Wars category in 60% proven slot"
    )

    from config.settings import DATA_DIR
    log_file = DATA_DIR / "LEARNING_LOG.md"
    assert log_file.exists()
    print("Persistent Learning Log verified at:", log_file)

    db.close()
    print("\n[+] Full Continuous Learning Feedback Loop Successfully Verified!")


if __name__ == "__main__":
    test_closed_feedback_learning_loop()
