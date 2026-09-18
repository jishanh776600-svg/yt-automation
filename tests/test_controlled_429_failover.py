import unittest
from unittest.mock import MagicMock
from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    NvidiaResponse
)
from core.database import SessionLocal, init_db
from core.models import Topic
from engines.topic_discovery import TopicDiscoveryEngine


class TestControlled429Failover(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()

    def tearDown(self):
        self.db.close()

    def test_01_gemini_429_cascades_to_nvidia_and_produces_valid_topics(self):
        client = GeminiClient(
            api_key="primary_key_429",
            secondary_api_key="secondary_key_429",
            groq_api_key="groq_key_invalid",
            openrouter_api_key="openrouter_key_unpaid",
            deepseek_api_key="deepseek_key_503",
            nvidia_api_key="nvidia_key_valid",
            sleeper=MagicMock()
        )

        cascade_trace = []

        def mock_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            cascade_trace.append("gemini_" + provider_name)
            raise GeminiQuotaExhaustedError("429 RESOURCE_EXHAUSTED on " + provider_name)

        def mock_groq(api_key, model, contents, **kwargs):
            cascade_trace.append("groq")
            raise GeminiQuotaExhaustedError("Groq HTTP 403 Forbidden")

        def mock_openrouter(api_key, model, contents, **kwargs):
            cascade_trace.append("openrouter")
            raise GeminiQuotaExhaustedError("OpenRouter HTTP 402 Payment Required")

        def mock_deepseek(api_key, model, contents, **kwargs):
            cascade_trace.append("deepseek")
            raise GeminiQuotaExhaustedError("DeepSeek HTTP 503 Service Unavailable")

        def mock_nvidia(api_key, model, contents, **kwargs):
            cascade_trace.append("nvidia")
            return NvidiaResponse(
                text="The Great Emu War | Bizarre Military Encounters | In 1932 Australian soldiers fought birds with machine guns.\nDancing Plague of 1518 | Historical Mysteries | Hundreds danced uncontrollably for days in Strasbourg."
            )

        client._execute_request = mock_gemini
        client._execute_groq_request = mock_groq
        client._execute_openrouter_request = mock_openrouter
        client._execute_deepseek_request = mock_deepseek
        client._execute_nvidia_request = mock_nvidia

        resp = client.generate_content(
            model="gemini-3.6-flash",
            contents="Suggest 2 obscure historical events"
        )

        self.assertEqual(
            cascade_trace,
            ["gemini_primary", "gemini_secondary", "groq", "openrouter", "deepseek", "nvidia"]
        )
        self.assertIn("The Great Emu War", resp.text)
        self.assertEqual(client.active_provider, "nvidia")

        lines = resp.text.strip().split("\n")
        candidates = []
        for line in lines:
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    candidates.append({
                        "title": parts[0],
                        "category": parts[1],
                        "summary": parts[2]
                    })
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["title"], "The Great Emu War")

    def test_02_topic_discovery_failover_with_deduplication_gate_active(self):
        engine = TopicDiscoveryEngine()
        is_dup = engine.is_duplicate(
            db=self.db,
            title="A Brand New Unique Incident Never Seen Before In Human History 99999",
            summary="A unique incident that occurred in 1845 in a remote location."
        )
        self.assertFalse(is_dup)

        existing_topic = self.db.query(Topic).first()
        if existing_topic:
            is_dup_existing = engine.is_duplicate(
                db=self.db,
                title=existing_topic.title,
                summary=existing_topic.summary
            )
            self.assertTrue(is_dup_existing)

    def test_03_openrouter_402_permanent_failure_advances_immediately(self):
        """Verify OpenRouter HTTP 402 fails fast and advances immediately to the next provider."""
        client = GeminiClient(
            api_key="primary_key",
            openrouter_api_key="openrouter_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )

        trace = []

        def mock_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            trace.append("primary_gemini")
            raise GeminiQuotaExhaustedError("429 RESOURCE_EXHAUSTED")

        def mock_openrouter(api_key, model, contents, **kwargs):
            trace.append("openrouter")
            raise GeminiQuotaExhaustedError("OpenRouter authentication/payment error (HTTP 402)")

        def mock_nvidia(api_key, model, contents, **kwargs):
            trace.append("nvidia")
            return NvidiaResponse(text="Test Title | Category | Test Summary")

        client._execute_request = mock_gemini
        client._execute_openrouter_request = mock_openrouter
        client._execute_nvidia_request = mock_nvidia

        resp = client.generate_content(model="gemini-3.6-flash", contents="Test")
        self.assertEqual(trace, ["primary_gemini", "openrouter", "nvidia"])
        self.assertTrue(client.is_provider_exhausted("openrouter"))
        self.assertEqual(client.active_provider, "nvidia")

    def test_04_provider_health_state_tracking_and_recovery(self):
        """Verify provider exhaustion state is properly tracked, and recovery/reset restores eligibility."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )

        # Initially, all configured providers are available
        available = [p["name"] for p in client.get_available_providers()]
        self.assertEqual(available, ["primary", "secondary", "nvidia"])

        # Mark primary exhausted
        client.mark_provider_exhausted("primary")
        self.assertTrue(client.is_provider_exhausted("primary"))
        available_after = [p["name"] for p in client.get_available_providers()]
        self.assertEqual(available_after, ["secondary", "nvidia"])

        # Reset exhaustion (simulating new session or health recovery)
        client.reset_provider_exhaustion()
        self.assertFalse(client.is_provider_exhausted("primary"))
        available_reset = [p["name"] for p in client.get_available_providers()]
        self.assertEqual(available_reset, ["primary", "secondary", "nvidia"])


if __name__ == "__main__":
    unittest.main()
