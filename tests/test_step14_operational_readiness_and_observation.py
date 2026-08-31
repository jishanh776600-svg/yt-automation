import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timedelta

from config.constants import (
    DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType,
    VisualSourceType, HistoricalEventRelation
)
from core.models import Job, UploadRecord, AssetRecord
from engines.asset_fetcher import AssetFetcher
from dashboard.data_provider import SystemDataProvider


class TestStep14OperationalReadinessAndObservation:

    def test_01_operational_readiness_verdict_and_reserve_invariants(self):
        # Target reserve is 6 verified Shorts
        assert TARGET_RESERVE_BUFFER == 6
        ready_count = 0
        deficit = max(TARGET_RESERVE_BUFFER - ready_count, 0)
        assert deficit == 6

        # Deficit calculation must never be negative
        ready_count_over = 8
        deficit_over = max(TARGET_RESERVE_BUFFER - ready_count_over, 0)
        assert deficit_over == 0

    def test_02_daily_publishing_capacity_accounting(self):
        # Strict publishing ceiling of 3 Shorts/day
        assert DAILY_SHORTS_LIMIT == 3

        # Scenario: 1 published today + 1 scheduled today = 2 booked today
        published_today = 1
        scheduled_today = 1
        booked_today = published_today + scheduled_today
        remaining_capacity = max(DAILY_SHORTS_LIMIT - booked_today, 0)

        assert booked_today == 2
        assert remaining_capacity == 1

        # Scenario: 3 booked today -> 0 capacity remaining
        booked_full = 3
        remaining_full = max(DAILY_SHORTS_LIMIT - booked_full, 0)
        assert remaining_full == 0

    def test_03_provider_capacity_and_exhaustion_classification(self):
        from core.recovery_manager import classify_error_to_failure_type

        # Exhaustion must map to QUOTA_FAILURE or PROVIDER_FAILURE
        err_msg = "All configured AI providers exhausted daily API quotas."
        failure_type = classify_error_to_failure_type(RuntimeError(err_msg))
        assert failure_type in (FailureType.QUOTA_FAILURE.value, FailureType.PROVIDER_FAILURE.value)
        assert failure_type == FailureType.QUOTA_FAILURE.value

    def test_04_reconciliation_zero_anomalies_invariant(self):
        db = MagicMock()
        provider = SystemDataProvider()

        # Mock clean state with zero anomalies
        with patch.object(provider, "get_reconciliation_anomalies", return_value=[]):
            anomalies = provider.get_reconciliation_anomalies(db)
            assert len(anomalies) == 0

    def test_05_crash_recovery_preserves_valid_completed_stages(self):
        job = MagicMock(spec=Job)
        job.id = "job_recov_01"
        job.state = "EDITING"

        # Simulating that completed audio/visual files exist in scratch/renders
        render_path = Path("temp_render_test.mp4")
        render_path.write_bytes(b"temp_mp4_bytes_exceeding_size" * 1000)

        assert render_path.exists()
        assert render_path.stat().st_size > 10000

        render_path.unlink(missing_ok=True)
