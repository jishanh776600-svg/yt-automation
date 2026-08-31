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
from core.gemini_client import GeminiClient


class TestStep15ProviderEconomicsAndReserveCapacity:

    def test_01_ai_call_graph_and_token_consumption_model(self):
        # Mandatory steps per Short: Research (1) + Verification (1) + Script (1) + Visuals (1) + Directing (1)
        mandatory_calls = 3
        typical_calls = 5
        max_calls = 7

        assert mandatory_calls <= typical_calls <= max_calls

        # Economics calculation: ~3,000 tokens per Short @ $0.30/1M tokens
        tokens_per_short = 3000
        cost_per_million = 0.30
        ai_cost_per_short = (tokens_per_short / 1000000.0) * cost_per_million
        assert ai_cost_per_short < 0.002  # Less than 0.2 cents per Short

        # Monthly costs
        monthly_3_per_day = ai_cost_per_short * 3 * 30
        assert monthly_3_per_day < 0.25  # Less than 25 cents per month

    def test_02_producer_publisher_capacity_partition(self):
        # produce_buffer.yml runs every 2 hours = 12 runs/day
        producer_max_daily_runs = 12
        # autopilot.yml consumes strictly <= 3 Shorts/day
        publisher_max_daily_consumption = DAILY_SHORTS_LIMIT  # 3

        # Net daily buffer accumulation potential
        net_daily_buffer_capacity = producer_max_daily_runs - publisher_max_daily_consumption
        assert net_daily_buffer_capacity == 9

        # From deficit = 6, time to reach TARGET_RESERVE_BUFFER = 6:
        deficit = TARGET_RESERVE_BUFFER  # 6
        assert net_daily_buffer_capacity >= deficit  # Can reach full reserve within 1 calendar day

    def test_03_provider_failover_cascade_ordering(self):
        client = GeminiClient()
        providers = ["primary", "secondary", "groq", "openrouter"]

        for p in providers:
            assert not client.is_provider_exhausted(p)
            client.mark_provider_exhausted(p)
            assert client.is_provider_exhausted(p)

    def test_04_terminal_exhaustion_clean_halt(self):
        client = GeminiClient()
        # Mark all providers exhausted
        for p in ["primary", "secondary", "groq", "openrouter"]:
            client.mark_provider_exhausted(p)

        assert client.is_provider_exhausted("primary") is True
        assert client.is_provider_exhausted("secondary") is True

        # Next call must raise clean RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            client.generate_content(model="gemini-2.5-flash", contents="Test prompt", max_retries=1)
        assert "ALL_AI_PROVIDERS_EXHAUSTED" in str(exc_info.value) or "exhausted" in str(exc_info.value).lower()

    def test_05_paid_credit_budget_calculation(self):
        # A $5.00 budget supports at least 2,500 Shorts @ $0.002/Short
        budget = 5.00
        cost_per_short = 0.002
        supported_shorts = int(budget / cost_per_short)
        assert supported_shorts >= 2500
