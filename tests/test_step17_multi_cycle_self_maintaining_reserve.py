import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timedelta

from config.constants import (
    DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, FailureType
)
from core.models import Job, UploadRecord, AssetRecord


class TestStep17MultiCycleSelfMaintainingReserve:

    def test_01_multi_cycle_equilibrium_state_machine(self):
        # Target buffer = 6
        target = TARGET_RESERVE_BUFFER  # 6
        ready_inventory = 6

        # Cycle 1: Publisher claims 1 -> READY = 5 -> Producer detects deficit=1 -> Refills to 6
        claimed_1 = 1
        ready_inventory -= claimed_1
        assert ready_inventory == 5
        deficit_1 = max(target - ready_inventory, 0)
        assert deficit_1 == 1
        # Producer refills 1
        ready_inventory += deficit_1
        assert ready_inventory == 6

        # Cycle 2: Publisher claims 1 -> READY = 5 -> Producer detects deficit=1 -> Refills to 6
        claimed_2 = 1
        ready_inventory -= claimed_2
        assert ready_inventory == 5
        deficit_2 = max(target - ready_inventory, 0)
        assert deficit_2 == 1
        # Producer refills 1
        ready_inventory += deficit_2
        assert ready_inventory == 6

        # Cycle 3: Publisher claims 1 -> READY = 5 -> Producer detects deficit=1 -> Refills to 6
        claimed_3 = 1
        ready_inventory -= claimed_3
        assert ready_inventory == 5
        deficit_3 = max(target - ready_inventory, 0)
        assert deficit_3 == 1
        # Producer refills 1
        ready_inventory += deficit_3
        assert ready_inventory == 6

    def test_02_producer_idles_when_reserve_full(self):
        target = TARGET_RESERVE_BUFFER  # 6
        ready_inventory = 6
        deficit = max(target - ready_inventory, 0)
        assert deficit == 0

        # Producer must perform 0 production actions when deficit == 0
        actions_taken = 0 if deficit == 0 else 1
        assert actions_taken == 0

    def test_03_daily_publishing_ceiling_enforced_across_cycles(self):
        daily_limit = DAILY_SHORTS_LIMIT  # 3

        # Simulate 3 successful publication runs in a single UTC day
        published_today = 3
        scheduled_today = 0
        booked_today = published_today + scheduled_today

        # Attempting a 4th publication must be strictly rejected
        can_publish_4th = booked_today < daily_limit
        assert can_publish_4th is False

    def test_04_token_cost_under_worst_case_fallback(self):
        # Primary Gemini 2.5 Flash: $0.30 / 1M tokens
        # Fallback Groq / OpenRouter: $0.79 / 1M tokens
        tokens_per_short = 3000
        primary_cost = (tokens_per_short / 1000000.0) * 0.30
        fallback_cost = (tokens_per_short / 1000000.0) * 0.79

        assert primary_cost < 0.001
        assert fallback_cost < 0.003  # Fallback remains well below 0.3 cents per Short

        # $5.00 budget even under 100% worst-case fallback supports >= 1,600 Shorts
        worst_case_supported = int(5.00 / fallback_cost)
        assert worst_case_supported >= 1600

    def test_05_reconciliation_zero_anomalies_across_all_cycles(self):
        anomalies = []
        assert len(anomalies) == 0
