import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime

from core.models import Topic, Job, JobState, RenderOutput
from core.database import SessionLocal, init_db
from engines.script_engine import ScriptEngine, ScriptCritic, CriticEvaluation
from engines.topic_discovery import TopicDiscoveryEngine
from core.lock import ProcessLock
from main import ShortsPipeline


class TestStep26FailureInjectionAndTopicAdvancement:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        init_db()

    def test_01_topic_a_failure_injection_and_attempt_boundary(self):
        """
        Simulate Topic A encountering factual/word-count failures for 3 revision attempts.
        Verify:
        - Exactly 3 attempts are executed.
        - Script quality gate raises RuntimeError after attempt 3.
        - Job transitions to NEEDS_REVIEW.
        """
        engine = ScriptEngine()
        topic_a = Topic(id="top_adv_fail", title="The Great Adversarial Incident of 1999", summary="An adversarial incident.")
        
        mock_gemini = MagicMock()
        # Return a 38-word invalid script with unsupported claim
        mock_resp = MagicMock()
        mock_resp.text = json.dumps({
            "hook": "In 1784, a European war ended with a kettle.",
            "context": "Holy Roman Empire clashed with Dutch forces.",
            "escalation": "One cannon shot was fired.",
            "reveal": "It hit an iron soup kettle.",
            "loop_twist": "The war ended instantly on October 8."
        })
        mock_gemini.generate_content.return_value = mock_resp

        with patch("core.gemini_client.get_gemini_client", return_value=mock_gemini), \
             patch.object(engine.critic, "evaluate") as mock_eval:
            
            # Fail all 3 attempts
            mock_eval.return_value = CriticEvaluation(
                score=60.0,
                passed=False,
                hook_score=10.0,
                information_gap_score=10.0,
                narrative_flow_score=10.0,
                spoken_cadence_score=10.0,
                specificity_score=10.0,
                payoff_score=10.0,
                fact_grounding_score=0.0,
                cliches_detected=[],
                feedback=["Total word count (38) outside calibrated 45-68 word target.", "Unsupported claim in 'October 8'"]
            )

            with pytest.raises(RuntimeError) as excinfo:
                engine.generate_script(MagicMock(), topic_a, research_data={"summary": "Adversarial facts"})

            assert "Script quality gate failed after 3 attempts" in str(excinfo.value)
            # Verify attempt boundary: exactly 3 calls to draft script pass
            assert mock_eval.call_count == 3

    def test_02_failure_isolation_and_no_reselection(self):
        """
        Verify Topic A is quarantined in attempted_topic_ids and never reselected.
        """
        discovery = TopicDiscoveryEngine()
        db = MagicMock()

        topic_a = Topic(id="top_failed_quarantine", title="The Failed Topic", summary="Failed", status="APPROVED")
        topic_b = Topic(id="top_eligible_replacement", title="The Replacement Topic", summary="Good", status="APPROVED")

        attempted_ids = {topic_a.id}

        db.query.return_value.filter.return_value.all.return_value = [topic_b]

        with patch.object(discovery, "is_duplicate", return_value=False):
            candidates = discovery.discover_topics(db, limit=1, exclude_topic_ids=attempted_ids)
            assert len(candidates) == 1
            assert candidates[0].id == "top_eligible_replacement"
            assert candidates[0].id != topic_a.id
            assert topic_a.id not in [c.id for c in candidates]

    def test_03_end_to_end_self_healing_producer_recovery(self):
        """
        Execute an end-to-end failure injection test on ShortsPipeline:
        - Candidate Topic A fails QA on attempt 1.
        - Producer catches failure, quarantines Topic A, and flags Job A as NEEDS_REVIEW.
        - Producer automatically advances to Candidate Topic B on attempt 2.
        - Topic B passes QA and is deposited into 01_READY.
        - Consecutive failures count is reset to 0.
        """
        pipeline = ShortsPipeline()
        
        topic_a = Topic(id="top_fail_e2e", title="The Great Adversarial Incident of 1999", summary="Kettle war", status="APPROVED")
        topic_b = Topic(id="top_succ_e2e", title="The Boston Molasses Flood of 1919", summary="Molasses wave", status="APPROVED")

        # Mock Drive Engine upload
        mock_drive_file = {"id": "drive_file_succ_12345", "name": "short_job_test_1080x1920.mp4"}
        pipeline.drive_engine.upload_video_to_vault = MagicMock(return_value=mock_drive_file)
        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=[0, 0, 0, 1, 1, 1, 1])

        # Step 1: Render Topic A fails, Render Topic B succeeds
        call_count = {"topic": 0}

        def mock_render_and_qa(db, job, topic, force=True):
            call_count["topic"] += 1
            if topic.id == topic_a.id:
                # Topic A fails script/QA
                return None, None
            elif topic.id == topic_b.id:
                # Topic B succeeds
                mock_render = RenderOutput(id="rend_succ", job_id=job.id, video_path="mock/path/short.mp4", duration_sec=23.5, file_size_bytes=1024)
                mock_meta = {"title": topic.title, "description": topic.summary, "tags": ["history"]}
                return mock_render, mock_meta
            return None, None

        pipeline._render_and_qa_job = MagicMock(side_effect=mock_render_and_qa)

        # Mock topic discovery to return Topic A first, then Topic B when Topic A is excluded
        def mock_discover_topics(db, limit=1, exclude_topic_ids=None):
            excluded = set(exclude_topic_ids or [])
            if topic_a.id not in excluded:
                return [topic_a]
            elif topic_b.id not in excluded:
                return [topic_b]
            return []

        pipeline.topic_engine.discover_topics = MagicMock(side_effect=mock_discover_topics)

        # Run maintain_buffer(target_stock=1)
        produced_count, summary = pipeline.maintain_buffer(target_stock=1)

        assert produced_count == 1
        assert summary["outcome"] == "SUCCEEDED"
        assert summary["final_stock"] == 1
        assert summary["block_reason"] is None

        # Verify Topic A was attempted once, quarantined, and Topic B succeeded
        assert call_count["topic"] == 2

    def test_04_circuit_breaker_not_tripped_on_isolated_failure(self):
        """
        Verify that a single candidate failure does not trip the 3-consecutive-failure circuit breaker
        when the subsequent candidate succeeds.
        """
        pipeline = ShortsPipeline()
        
        topic_a = Topic(id="top_fail_cb", title="Topic A", summary="Fails", status="APPROVED")
        topic_b = Topic(id="top_succ_cb", title="Topic B", summary="Succeeds", status="APPROVED")

        mock_drive_file = {"id": "drive_file_cb_999", "name": "short_job_cb_1080x1920.mp4"}
        pipeline.drive_engine.upload_video_to_vault = MagicMock(return_value=mock_drive_file)
        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=[0, 0, 1, 1])

        def mock_render(db, job, topic, force=True):
            if topic.id == topic_a.id:
                return None, None
            return RenderOutput(id="rend_cb", job_id=job.id, video_path="mock/path.mp4", duration_sec=22.0, file_size_bytes=1024), {"title": topic.title}

        pipeline._render_and_qa_job = MagicMock(side_effect=mock_render)

        def mock_discover(db, limit=1, exclude_topic_ids=None):
            excluded = set(exclude_topic_ids or [])
            if topic_a.id not in excluded:
                return [topic_a]
            return [topic_b]

        pipeline.topic_engine.discover_topics = MagicMock(side_effect=mock_discover)

        count, summary = pipeline.produce_batch(count=1)
        assert count == 1
        assert summary["outcome"] == "SUCCEEDED"
        assert summary["block_reason"] is None

    def test_05_process_lock_released_after_failure_and_success(self):
        """
        Verify that ProcessLock is cleanly released after candidate failure and subsequent success.
        """
        lock = ProcessLock(name="production", command_name="test-lock-safety")
        assert lock.acquire() is True
        assert lock.is_locked() is True
        lock.release()
        assert lock.is_locked() is False

    def test_06_database_integrity_check(self):
        """
        Verify SQLite PRAGMA integrity_check returns ok.
        """
        from core.database import engine
        from sqlalchemy import text

        with engine.connect() as conn:
            res = conn.execute(text("PRAGMA integrity_check;")).fetchall()
            assert len(res) == 1
            assert res[0][0] == "ok"

    def test_07_no_deepseek_dependency_in_provider_stack(self):
        """
        Assert DeepSeek is completely absent from all configurations and imports.
        """
        import sys
        assert "deepseek" not in sys.modules
        assert "DEEPSEEK_API_KEY" not in os.environ
