"""
Dedicated Test Suite: 3-Hour Autonomous Buffer Refill Logic.
=============================================================
Covers all 10 canonical requirements:
1. READY = 6 -> produce 0
2. READY = 5 -> produce exactly 1
3. READY = 3 -> produce exactly 3
4. READY = 0 -> produce exactly 6 (or safety ceiling)
5. READY > 6 -> produce 0
6. Re-running after successful refill does not create duplicates
7. Manual refill uses same CloudProductionOrchestrator
8. Dashboard displays same target (6) and interval (Every 3 hours)
9. Workflow YAML contains 0 */3 * * * and target 6
10. Last/next audit telemetry is correctly calculated
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from config.constants import (
    TARGET_RESERVE_BUFFER,
    BUFFER_AUDIT_INTERVAL_HOURS,
    BUFFER_AUDIT_CRON,
    BUFFER_AUDIT_HOURS_UTC,
    get_next_buffer_audit_time,
)
from config.settings import PROJECT_ROOT
from core.pipeline_state import ProductionRunTelemetry
from intelligence.cloud_orchestrator import CloudProductionOrchestrator
from dashboard.data_provider import SystemDataProvider
from dashboard.mission_control_service import mission_control_service


def _get_mock_cloud_lock():
    lock = MagicMock()
    lock.acquire.return_value = True
    lock.release.return_value = True
    return lock


class TestBufferRefill3HourLogic:
    """Comprehensive test suite for the 3-hour autonomous buffer refill system."""

    # --------------------------------------------------------------------------
    # 1. READY = 6 -> produce 0
    # --------------------------------------------------------------------------
    def test_01_ready_stock_6_produces_zero(self):
        """When READY stock is 6, deficit is 0 and 0 Shorts are produced."""
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 6

        orchestrator = CloudProductionOrchestrator(
            drive_engine=mock_drive,
            is_dry_run=True,
        )

        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])):
            telemetry = orchestrator.run_production_cycle(target_buffer=6)

        assert telemetry.initial_ready_stock == 6
        assert telemetry.videos_deposited == 0
        assert telemetry.status in ("BUFFER_HEALTHY", "SUCCEEDED")

    # --------------------------------------------------------------------------
    # 2. READY = 5 -> produce exactly 1
    # --------------------------------------------------------------------------
    def test_02_ready_stock_5_produces_one(self):
        """When READY stock is 5, deficit is 1 and exactly 1 Short is produced."""
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 5

        orchestrator = CloudProductionOrchestrator(
            drive_engine=mock_drive,
            is_dry_run=True,
        )

        initial_stock = 5
        target = 6
        deficit = max(0, target - initial_stock)
        assert deficit == 1

        def mock_produce(ec, telemetry, db):
            telemetry.videos_deposited += 1
            return MagicMock()

        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])), \
             patch("engines.topic_discovery.TopicDiscoveryEngine.is_duplicate", return_value=False), \
             patch.object(orchestrator, "is_event_already_produced", return_value=False), \
             patch.object(orchestrator, "produce_single_event", side_effect=mock_produce):
            telemetry = orchestrator.run_production_cycle(target_buffer=6)

        assert telemetry.videos_deposited == 1

    # --------------------------------------------------------------------------
    # 3. READY = 3 -> produce exactly 3
    # --------------------------------------------------------------------------
    def test_03_ready_stock_3_produces_three(self):
        """When READY stock is 3, deficit is 3 and exactly 3 Shorts are produced."""
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 3

        orchestrator = CloudProductionOrchestrator(
            drive_engine=mock_drive,
            is_dry_run=True,
        )

        initial_stock = 3
        target = 6
        deficit = max(0, target - initial_stock)
        assert deficit == 3

        def mock_produce(ec, telemetry, db):
            telemetry.videos_deposited += 1
            return MagicMock()

        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])), \
             patch("engines.topic_discovery.TopicDiscoveryEngine.is_duplicate", return_value=False), \
             patch.object(orchestrator, "is_event_already_produced", return_value=False), \
             patch.object(orchestrator, "produce_single_event", side_effect=mock_produce):
            telemetry = orchestrator.run_production_cycle(target_buffer=6)

        assert telemetry.videos_deposited == 3

    # --------------------------------------------------------------------------
    # 4. READY = 0 -> produce exactly 6 (or safety ceiling)
    # --------------------------------------------------------------------------
    def test_04_ready_stock_0_produces_full_target(self):
        """When READY stock is 0, deficit is 6 and up to target (6) Shorts are produced."""
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 0

        orchestrator = CloudProductionOrchestrator(
            drive_engine=mock_drive,
            is_dry_run=True,
        )

        initial_stock = 0
        target = 6
        deficit = max(0, target - initial_stock)
        assert deficit == 6

        def mock_produce(ec, telemetry, db):
            telemetry.videos_deposited += 1
            return MagicMock()

        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])), \
             patch("engines.topic_discovery.TopicDiscoveryEngine.is_duplicate", return_value=False), \
             patch.object(orchestrator, "is_event_already_produced", return_value=False), \
             patch.object(orchestrator, "produce_single_event", side_effect=mock_produce):
            telemetry = orchestrator.run_production_cycle(target_buffer=6)

        assert telemetry.videos_deposited == 6

    # --------------------------------------------------------------------------
    # 5. READY > 6 -> produce 0
    # --------------------------------------------------------------------------
    def test_05_ready_stock_greater_than_6_produces_zero(self):
        """When READY stock exceeds target (e.g. 7, 8, 10), deficit is 0 and 0 are produced."""
        mock_drive = MagicMock()

        for stock in [7, 8, 10, 15]:
            mock_drive.get_ready_stock_count.return_value = stock
            orchestrator = CloudProductionOrchestrator(
                drive_engine=mock_drive,
                is_dry_run=True,
            )

            with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
                 patch("intelligence.cloud_orchestrator.download_canonical_database"), \
                 patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
                 patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])):
                telemetry = orchestrator.run_production_cycle(target_buffer=6)

            assert telemetry.videos_deposited == 0
            assert telemetry.status in ("BUFFER_HEALTHY", "SUCCEEDED")

    # --------------------------------------------------------------------------
    # 6. Re-running after successful refill does not create duplicates
    # --------------------------------------------------------------------------
    def test_06_rerunning_after_successful_refill_is_idempotent(self):
        """After replenishing stock to 6, a second run immediately sees stock=6 and produces 0."""
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 5

        orchestrator = CloudProductionOrchestrator(
            drive_engine=mock_drive,
            is_dry_run=True,
        )

        def mock_produce(ec, telemetry, db):
            telemetry.videos_deposited += 1
            return MagicMock()

        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])), \
             patch("engines.topic_discovery.TopicDiscoveryEngine.is_duplicate", return_value=False), \
             patch.object(orchestrator, "is_event_already_produced", return_value=False), \
             patch.object(orchestrator, "produce_single_event", side_effect=mock_produce):
            tel1 = orchestrator.run_production_cycle(target_buffer=6)
            assert tel1.videos_deposited == 1

        # Cycle 2: Stock is now 6
        mock_drive.get_ready_stock_count.return_value = 6
        with patch("intelligence.cloud_orchestrator.CloudLockManager", return_value=_get_mock_cloud_lock()), \
             patch("intelligence.cloud_orchestrator.download_canonical_database"), \
             patch("intelligence.cloud_orchestrator.upload_canonical_database"), \
             patch.object(orchestrator, "check_environment_secrets", return_value=(True, [])):
            tel2 = orchestrator.run_production_cycle(target_buffer=6)
            assert tel2.videos_deposited == 0
            assert tel2.status in ("BUFFER_HEALTHY", "SUCCEEDED")

    # --------------------------------------------------------------------------
    # 7. Manual refill uses same CloudProductionOrchestrator
    # --------------------------------------------------------------------------
    def test_07_manual_refill_uses_same_orchestrator_and_logic(self):
        """ActionManager and main.py maintain_buffer invoke CloudProductionOrchestrator."""
        from main import ShortsPipeline

        pipeline = ShortsPipeline(voice="af_bella")
        mock_drive = MagicMock()
        mock_drive.get_ready_stock_count.return_value = 4
        pipeline.drive_engine = mock_drive

        with patch("intelligence.cloud_orchestrator.CloudProductionOrchestrator.run_production_cycle") as mock_run:
            fake_telemetry = ProductionRunTelemetry(is_dry_run=True)
            fake_telemetry.initial_ready_stock = 4
            fake_telemetry.final_ready_stock = 6
            fake_telemetry.videos_deposited = 2
            fake_telemetry.status = "SUCCEEDED"
            mock_run.return_value = fake_telemetry

            deposited, summary = pipeline.maintain_buffer(target_stock=6)

            assert deposited == 2
            assert summary["requested_deficit"] == 2
            assert summary["target_stock"] == 6
            assert summary["voice"] == "af_bella"
            mock_run.assert_called_once_with(target_buffer=6)

    # --------------------------------------------------------------------------
    # 8. Dashboard displays same target (6) and interval (Every 3 hours)
    # --------------------------------------------------------------------------
    def test_08_dashboard_displays_same_target_and_interval(self):
        """SystemDataProvider and MissionControlService report 6-reserve and 3-hour interval."""
        provider = SystemDataProvider()
        mock_db = MagicMock()

        # Telemetry check
        with patch("engines.drive_engine.DriveVaultEngine.get_ready_stock_count", return_value=4):
            refill_telem = provider.get_refill_telemetry(mock_db)
            assert refill_telem["target_reserve"] == 6
            assert refill_telem["audit_interval_hours"] == 3
            assert refill_telem["audit_cron"] == "0 */3 * * *"
            assert "Every 3 hours" in refill_telem["trigger_schedule"]
            assert refill_telem["automation_status"] == "ACTIVE"

            # Cloud workflows check
            cloud_wf = provider.get_cloud_workflows_status()
            workflows = cloud_wf.get("workflows", [])
            buffer_wf = next((w for w in workflows if w["id"] == "produce_buffer"), None)
            assert buffer_wf is not None
            assert "0 */3 * * *" in buffer_wf["cron"]
            assert "Every 3 hours" in buffer_wf["cron"]
            assert "6 Shorts" in buffer_wf["target"]

            # Mission control command center telemetry check
            mc_telem = mission_control_service.get_command_center_telemetry(db=mock_db)
            assert mc_telem["target_reserve"] == 6
            assert mc_telem["audit_interval_hours"] == 3
            assert mc_telem["audit_cron"] == "0 */3 * * *"
            assert mc_telem["refill_deficit"] == 2  # 6 - 4
            assert mc_telem["automation_status"] == "ACTIVE"

    # --------------------------------------------------------------------------
    # 9. Workflow YAML contains 0 */3 * * * and target 6
    # --------------------------------------------------------------------------
    def test_09_workflow_yaml_contains_3hour_cron_and_target_6(self):
        """produce_buffer.yml matches 3-hour cron and target_buffer default of 6."""
        wf_path = PROJECT_ROOT / ".github" / "workflows" / "produce_buffer.yml"
        assert wf_path.exists(), "produce_buffer.yml must exist"

        content = wf_path.read_text(encoding="utf-8")
        assert "0 */3 * * *" in content, "Cron must be 0 */3 * * *"

        parsed = yaml.safe_load(content)
        triggers = parsed.get("on") or parsed.get(True) or {}
        schedule = triggers.get("schedule", [])
        crons = [s.get("cron") for s in schedule if isinstance(s, dict)]
        assert "0 */3 * * *" in crons, f"Expected '0 */3 * * *' in crons: {crons}"

        dispatch = triggers.get("workflow_dispatch", {})
        inputs = dispatch.get("inputs", {})
        target_input = inputs.get("target_buffer", {})
        assert str(target_input.get("default")) == "6"

    # --------------------------------------------------------------------------
    # 10. Last/next audit telemetry is correctly calculated
    # --------------------------------------------------------------------------
    def test_10_next_audit_telemetry_dynamic_calculation(self):
        """get_next_buffer_audit_time aligns to 00, 03, 06, 09, 12, 15, 18, 21 UTC."""
        assert BUFFER_AUDIT_INTERVAL_HOURS == 3
        assert BUFFER_AUDIT_CRON == "0 */3 * * *"
        assert BUFFER_AUDIT_HOURS_UTC == [0, 3, 6, 9, 12, 15, 18, 21]

        # Case A: 01:15 UTC -> Next is 03:00 UTC
        dt_a = datetime(2026, 9, 6, 1, 15, 0, tzinfo=timezone.utc)
        next_a = get_next_buffer_audit_time(dt_a)
        assert next_a == datetime(2026, 9, 6, 3, 0, 0)

        # Case B: Exactly on slot 03:00 UTC -> Next is 06:00 UTC
        dt_b = datetime(2026, 9, 6, 3, 0, 0, tzinfo=timezone.utc)
        next_b = get_next_buffer_audit_time(dt_b)
        assert next_b == datetime(2026, 9, 6, 6, 0, 0)

        # Case C: 22:30 UTC -> Next is 00:00 UTC tomorrow
        dt_c = datetime(2026, 9, 6, 22, 30, 0, tzinfo=timezone.utc)
        next_c = get_next_buffer_audit_time(dt_c)
        assert next_c == datetime(2026, 9, 7, 0, 0, 0)
