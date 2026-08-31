import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime

from core.models import Topic, Job, JobState, RenderOutput, UploadRecord
from core.database import SessionLocal, init_db, engine
from engines.topic_discovery import TopicDiscoveryEngine
from engines.script_engine import ScriptEngine
from core.lock import ProcessLock, ProcessLockError
from main import ShortsPipeline
from sqlalchemy import text


class TestStep27ProducerCycleAndReserveRefillRootCause:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        init_db()
        with patch("time.sleep", return_value=None):
            yield

    def test_01_ready_0_full_refill_contract(self):
        """
        When READY = 0, maintain_buffer(target_stock=6) must identify deficit=6
        and produce 6 Shorts to reach target stock 6.
        """
        pipeline = ShortsPipeline()
        
        stock_state = {"count": 0}
        
        def mock_get_stock():
            return stock_state["count"]
            
        def mock_upload(local_path, target_folder, description=None, metadata_properties=None):
            stock_state["count"] += 1
            return {"id": f"drive_file_{stock_state['count']}", "name": f"short_{stock_state['count']}.mp4"}

        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=mock_get_stock)
        pipeline.drive_engine.upload_video_to_vault = MagicMock(side_effect=mock_upload)

        topics_pool = [
            Topic(id=f"top_{i}", title=f"Historical Topic {i}", summary=f"Summary {i}", status="APPROVED")
            for i in range(10)
        ]

        def mock_discover(db, limit=1, exclude_topic_ids=None):
            excluded = set(exclude_topic_ids or [])
            eligible = [t for t in topics_pool if t.id not in excluded]
            return eligible[:limit]

        pipeline.topic_engine.discover_topics = MagicMock(side_effect=mock_discover)

        def mock_render(db, job, topic, force=True):
            render = RenderOutput(
                id=f"rend_{job.id}", job_id=job.id, video_path="mock/short.mp4",
                duration_sec=23.0, file_size_bytes=1024
            )
            return render, {"title": topic.title, "description": topic.summary, "tags": ["history"]}

        pipeline._render_and_qa_job = MagicMock(side_effect=mock_render)

        produced, summary = pipeline.maintain_buffer(target_stock=6)

        assert produced == 6
        assert summary["outcome"] == "SUCCEEDED"
        assert summary["initial_stock"] == 0
        assert summary["final_stock"] == 6
        assert summary["requested_deficit"] == 6
        assert stock_state["count"] == 6

    def test_02_ready_1_through_5_deterministic_deficit_calculation(self):
        """
        For each starting READY stock (1 through 5), verify exact deficit is produced.
        """
        for starting_stock in range(1, 6):
            pipeline = ShortsPipeline()
            expected_deficit = 6 - starting_stock
            stock_state = {"count": starting_stock}

            pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=lambda: stock_state["count"])
            pipeline.drive_engine.upload_video_to_vault = MagicMock(
                side_effect=lambda **kw: stock_state.update({"count": stock_state["count"] + 1}) or {"id": "mock_id", "name": "mock.mp4"}
            )

            topics_pool = [
                Topic(id=f"top_st_{starting_stock}_{i}", title=f"Topic {i}", summary="Summary", status="APPROVED")
                for i in range(10)
            ]
            pipeline.topic_engine.discover_topics = MagicMock(
                side_effect=lambda db, limit=1, exclude_topic_ids=None: [t for t in topics_pool if t.id not in set(exclude_topic_ids or [])][:limit]
            )

            pipeline._render_and_qa_job = MagicMock(
                side_effect=lambda db, job, topic, force=True: (
                    RenderOutput(id=f"r_{job.id}", job_id=job.id, video_path="mock.mp4", duration_sec=23.0, file_size_bytes=1024),
                    {"title": topic.title}
                )
            )

            produced, summary = pipeline.maintain_buffer(target_stock=6)

            assert produced == expected_deficit, f"Failed for starting stock {starting_stock}"
            assert summary["outcome"] == "SUCCEEDED"
            assert summary["final_stock"] == 6
            assert summary["requested_deficit"] == expected_deficit

    def test_03_ready_6_idles_with_zero_production(self):
        """
        When READY = 6, maintain_buffer(target_stock=6) must do 0 production and exit immediately.
        """
        pipeline = ShortsPipeline()
        pipeline.drive_engine.get_ready_stock_count = MagicMock(return_value=6)
        pipeline.produce_single_to_vault = MagicMock()

        produced, summary = pipeline.maintain_buffer(target_stock=6)

        assert produced == 0
        assert summary["outcome"] == "SUCCEEDED"
        assert summary["initial_stock"] == 6
        assert summary["final_stock"] == 6
        assert summary["requested_deficit"] == 0
        pipeline.produce_single_to_vault.assert_not_called()

    def test_04_publisher_claim_triggers_producer_refill_cycle(self):
        """
        Simulate publisher claiming 1 Short (READY 6 -> 5), followed by producer
        refilling 1 Short (READY 5 -> 6).
        """
        pipeline = ShortsPipeline()
        vault_ready_files = [
            {"id": f"drive_file_{i}", "name": f"short_{i}.mp4", "properties": {"job_id": f"job_{i}", "topic_id": f"top_{i}"}}
            for i in range(6)
        ]

        # 1. Publisher claims 1 file
        claimed_file = vault_ready_files.pop(0)
        assert len(vault_ready_files) == 5

        # 2. Producer runs maintain_buffer
        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=lambda: len(vault_ready_files))
        
        def mock_upload(local_path, target_folder, description=None, metadata_properties=None):
            new_file = {"id": "drive_file_replenished", "name": "short_replenished.mp4"}
            vault_ready_files.append(new_file)
            return new_file

        pipeline.drive_engine.upload_video_to_vault = MagicMock(side_effect=mock_upload)

        topic_repl = Topic(id="top_repl", title="Replacement Event", summary="Summary", status="APPROVED")
        pipeline.topic_engine.discover_topics = MagicMock(return_value=[topic_repl])
        pipeline._render_and_qa_job = MagicMock(return_value=(
            RenderOutput(id="r_repl", job_id="job_repl", video_path="mock.mp4", duration_sec=22.5, file_size_bytes=1024),
            {"title": topic_repl.title}
        ))

        produced, summary = pipeline.maintain_buffer(target_stock=6)

        assert produced == 1
        assert summary["outcome"] == "SUCCEEDED"
        assert len(vault_ready_files) == 6
        assert summary["final_stock"] == 6

    def test_05_multi_cycle_equilibrium_simulation(self):
        """
        Simulate 5 consecutive publisher/producer operational cycles.
        Verify:
        - Reserve stays at exactly 6 after every cycle.
        - No overfilling occurs.
        - No duplicate claims occur.
        """
        pipeline = ShortsPipeline()
        vault = [f"short_{i}.mp4" for i in range(6)]
        published = []

        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=lambda: len(vault))
        
        cycle_count = 0
        def mock_upload(local_path, target_folder, description=None, metadata_properties=None):
            nonlocal cycle_count
            cycle_count += 1
            new_file = f"short_cycle_{cycle_count}.mp4"
            vault.append(new_file)
            return {"id": f"drive_{new_file}", "name": new_file}

        pipeline.drive_engine.upload_video_to_vault = MagicMock(side_effect=mock_upload)

        for cycle in range(1, 6):
            # Publisher claims 1 Short
            claimed = vault.pop(0)
            published.append(claimed)
            assert len(vault) == 5

            # Producer replenishes 1 Short
            topic_c = Topic(id=f"top_c_{cycle}", title=f"Cycle Topic {cycle}", summary="Summary", status="APPROVED")
            pipeline.topic_engine.discover_topics = MagicMock(return_value=[topic_c])
            pipeline._render_and_qa_job = MagicMock(return_value=(
                RenderOutput(id=f"r_{cycle}", job_id=f"j_{cycle}", video_path="mock.mp4", duration_sec=23.0, file_size_bytes=1024),
                {"title": topic_c.title}
            ))

            produced, summary = pipeline.maintain_buffer(target_stock=6)
            assert produced == 1
            assert len(vault) == 6
            assert summary["final_stock"] == 6

        assert len(published) == 5
        assert len(vault) == 6
        assert len(set(published)) == 5  # No duplicate claims

    def test_06_failure_isolation_and_circuit_breaker_resilience(self):
        """
        Verify that when candidate 1 fails, candidate 2 succeeds, refilling the reserve
        without tripping the circuit breaker.
        """
        pipeline = ShortsPipeline()
        vault = [f"short_{i}.mp4" for i in range(5)]  # starting at 5/6

        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=lambda: len(vault))

        def mock_upload(local_path, target_folder, description=None, metadata_properties=None):
            vault.append("short_fixed.mp4")
            return {"id": "drive_fixed", "name": "short_fixed.mp4"}

        pipeline.drive_engine.upload_video_to_vault = MagicMock(side_effect=mock_upload)

        topic_fail = Topic(id="top_adv_fail", title="Failing Candidate", summary="Fails", status="APPROVED")
        topic_pass = Topic(id="top_adv_pass", title="Passing Candidate", summary="Passes", status="APPROVED")

        def mock_discover(db, limit=1, exclude_topic_ids=None):
            excluded = set(exclude_topic_ids or [])
            if topic_fail.id not in excluded:
                return [topic_fail]
            return [topic_pass]

        pipeline.topic_engine.discover_topics = MagicMock(side_effect=mock_discover)

        def mock_render(db, job, topic, force=True):
            if topic.id == topic_fail.id:
                return None, None
            return (
                RenderOutput(id="r_pass", job_id="j_pass", video_path="mock.mp4", duration_sec=23.0, file_size_bytes=1024),
                {"title": topic_pass.title}
            )

        pipeline._render_and_qa_job = MagicMock(side_effect=mock_render)

        produced, summary = pipeline.maintain_buffer(target_stock=6)

        assert produced == 1
        assert summary["outcome"] == "SUCCEEDED"
        assert len(vault) == 6
        assert summary["block_reason"] is None

    def test_07_process_lock_safety_under_exception(self):
        """
        Verify ProcessLock is always released even when an unhandled exception occurs.
        """
        pipeline = ShortsPipeline()
        pipeline.drive_engine.get_ready_stock_count = MagicMock(side_effect=RuntimeError("Simulated critical failure"))

        with pytest.raises(RuntimeError):
            pipeline.maintain_buffer(target_stock=6)

        lock = ProcessLock(name="production", command_name="test-check")
        assert lock.is_locked() is False

    def test_08_sqlite_database_integrity(self):
        """
        Verify SQLite database integrity check returns ok.
        """
        with engine.connect() as conn:
            res = conn.execute(text("PRAGMA integrity_check;")).fetchall()
            assert len(res) == 1
            assert res[0][0] == "ok"

    def test_09_no_deepseek_dependency(self):
        """
        Verify DeepSeek is completely absent from all modules and environment variables.
        """
        assert "deepseek" not in sys.modules
        assert "DEEPSEEK_API_KEY" not in os.environ
