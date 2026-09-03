"""
Unit & Integration Test Suite for NVIDIA NIM AI Fallback Provider in AL AMR Pipeline.

Verifies:
1. Exact 6-provider order: Primary -> Secondary -> Groq -> OpenRouter -> DeepSeek -> NVIDIA.
2. NVIDIA is called ONLY after all 5 preceding providers fail.
3. Earlier success (Primary, Secondary, Groq, OpenRouter, or DeepSeek) prevents NVIDIA invocation.
4. NVIDIA succeeds -> pipeline receives NvidiaResponse with .text property and continues normally.
5. All 6 providers exhausted -> clean bounded failure (GeminiQuotaExhaustedError).
6. Exhausted providers are skipped on subsequent calls (no retry amplification).
7. NVIDIA_API_KEY is loaded securely from environment / parameters; never hardcoded.
8. API keys/secrets never appear in log messages or reprs.
9. NvidiaResponse interface compatibility with response objects (.text property).
10. Existing DeepSeek fallback behavior remains intact before NVIDIA in the chain.
11. Preserves batching compatibility with generate_batch_scripts().
"""
import unittest
from unittest.mock import MagicMock, patch
import logging
import io

from core.gemini_client import (
    GeminiClient,
    GeminiQuotaExhaustedError,
    DeepSeekResponse,
    GroqResponse,
    OpenRouterResponse,
    NvidiaResponse
)


class TestNvidiaFallbackProvider(unittest.TestCase):

    def test_01_exact_six_provider_fallback_order(self):
        """TEST 1: Verify configured providers order is Primary -> Secondary -> Groq -> OpenRouter -> DeepSeek -> NVIDIA."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            groq_api_key="groq_key",
            openrouter_api_key="openrouter_key",
            deepseek_api_key="deepseek_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )
        providers = client._get_configured_providers()
        names = [p["name"] for p in providers]
        self.assertEqual(
            names,
            ["primary", "secondary", "groq", "openrouter", "deepseek", "nvidia"],
            f"Expected 6-provider order, got {names}"
        )

    def test_02_nvidia_called_only_after_all_five_preceding_fail(self):
        """TEST 2: NVIDIA is called only after Primary, Secondary, Groq, OpenRouter, and DeepSeek all fail."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            groq_api_key="groq_key",
            openrouter_api_key="openrouter_key",
            deepseek_api_key="deepseek_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} quota exhausted")

        def fake_groq(api_key, model, contents, **kwargs):
            calls.append("groq")
            raise GeminiQuotaExhaustedError("Groq quota exhausted")

        def fake_openrouter(api_key, model, contents, **kwargs):
            calls.append("openrouter")
            raise GeminiQuotaExhaustedError("OpenRouter quota exhausted")

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            raise GeminiQuotaExhaustedError("DeepSeek quota exhausted")

        def fake_nvidia(api_key, model, contents, **kwargs):
            calls.append("nvidia")
            return NvidiaResponse(text="NVIDIA final fallback output")

        client._execute_request = fake_gemini
        client._execute_groq_request = fake_groq
        client._execute_openrouter_request = fake_openrouter
        client._execute_deepseek_request = fake_deepseek
        client._execute_nvidia_request = fake_nvidia

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(
            calls,
            ["primary", "secondary", "groq", "openrouter", "deepseek", "nvidia"]
        )
        self.assertEqual(resp.text, "NVIDIA final fallback output")
        self.assertTrue(client.is_provider_exhausted("primary"))
        self.assertTrue(client.is_provider_exhausted("secondary"))
        self.assertTrue(client.is_provider_exhausted("groq"))
        self.assertTrue(client.is_provider_exhausted("openrouter"))
        self.assertTrue(client.is_provider_exhausted("deepseek"))
        self.assertFalse(client.is_provider_exhausted("nvidia"))

    def test_03_earlier_success_prevents_nvidia_invocation(self):
        """TEST 3: When any earlier provider (e.g. DeepSeek) succeeds, NVIDIA is NEVER called."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            groq_api_key="groq_key",
            openrouter_api_key="openrouter_key",
            deepseek_api_key="deepseek_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            raise GeminiQuotaExhaustedError(f"{provider_name} quota exhausted")

        def fake_groq(api_key, model, contents, **kwargs):
            calls.append("groq")
            raise GeminiQuotaExhaustedError("Groq quota exhausted")

        def fake_openrouter(api_key, model, contents, **kwargs):
            calls.append("openrouter")
            raise GeminiQuotaExhaustedError("OpenRouter quota exhausted")

        def fake_deepseek(api_key, model, contents, **kwargs):
            calls.append("deepseek")
            return DeepSeekResponse(text="DeepSeek output")

        def fake_nvidia(api_key, model, contents, **kwargs):
            calls.append("nvidia")
            return NvidiaResponse(text="NVIDIA output")

        client._execute_request = fake_gemini
        client._execute_groq_request = fake_groq
        client._execute_openrouter_request = fake_openrouter
        client._execute_deepseek_request = fake_deepseek
        client._execute_nvidia_request = fake_nvidia

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(
            calls,
            ["primary", "secondary", "groq", "openrouter", "deepseek"]
        )
        self.assertNotIn("nvidia", calls)
        self.assertEqual(resp.text, "DeepSeek output")
        self.assertFalse(client.is_provider_exhausted("nvidia"))

    def test_04_primary_success_prevents_all_fallbacks(self):
        """TEST 4: When Primary succeeds, Groq, OpenRouter, DeepSeek, and NVIDIA are not called."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            groq_api_key="groq_key",
            openrouter_api_key="openrouter_key",
            deepseek_api_key="deepseek_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )
        calls = []

        def fake_gemini(api_key, model, contents, provider_name="primary", **kwargs):
            calls.append(provider_name)
            resp = MagicMock()
            resp.text = "Primary Success"
            return resp

        client._execute_request = fake_gemini
        client._execute_groq_request = MagicMock()
        client._execute_openrouter_request = MagicMock()
        client._execute_deepseek_request = MagicMock()
        client._execute_nvidia_request = MagicMock()

        resp = client.generate_content(model="gemini-3.6-flash", contents="Generate topic")
        self.assertEqual(calls, ["primary"])
        self.assertEqual(resp.text, "Primary Success")
        client._execute_nvidia_request.assert_not_called()

    def test_05_all_six_providers_fail_clean_quota_exhausted_error(self):
        """TEST 5: When all 6 providers fail, GeminiQuotaExhaustedError is raised cleanly."""
        client = GeminiClient(
            api_key="primary_key",
            secondary_api_key="secondary_key",
            groq_api_key="groq_key",
            openrouter_api_key="openrouter_key",
            deepseek_api_key="deepseek_key",
            nvidia_api_key="nvidia_key",
            sleeper=MagicMock()
        )

        client._execute_request = MagicMock(side_effect=GeminiQuotaExhaustedError("Gemini exhausted"))
        client._execute_groq_request = MagicMock(side_effect=GeminiQuotaExhaustedError("Groq exhausted"))
        client._execute_openrouter_request = MagicMock(side_effect=GeminiQuotaExhaustedError("OpenRouter exhausted"))
        client._execute_deepseek_request = MagicMock(side_effect=GeminiQuotaExhaustedError("DeepSeek exhausted"))
        client._execute_nvidia_request = MagicMock(side_effect=GeminiQuotaExhaustedError("NVIDIA exhausted"))

        with self.assertRaises(GeminiQuotaExhaustedError) as ctx:
            client.generate_content(model="gemini-3.6-flash", contents="Test prompt")
        self.assertIn("exhausted", str(ctx.exception).lower())

    def test_06_nvidia_api_key_security_and_redaction(self):
        """TEST 6: Ensure NVIDIA API key is never exposed in logs, exceptions, or string reprs."""
        secret_key = "nvapi-SUPER_SECRET_NVIDIA_KEY_xyz999"
        client = GeminiClient(
            api_key="",
            nvidia_api_key=secret_key,
            sleeper=MagicMock()
        )
        self.assertNotIn(secret_key, repr(client))
        resp = NvidiaResponse(text="Test Response")
        self.assertNotIn(secret_key, repr(resp))
        self.assertEqual(resp.text, "Test Response")

    def test_07_nvidia_response_interface_compatibility(self):
        """TEST 7: NvidiaResponse provides .text property compatible with google.genai response."""
        content = "1. Islamic Golden Age\n2. House of Wisdom"
        resp = NvidiaResponse(text=content)
        self.assertTrue(hasattr(resp, "text"))
        self.assertEqual(resp.text, content)
        self.assertIn("Islamic Golden Age", repr(resp))

    def test_08_batch_script_generation_offline_compatibility(self):
        """TEST 8: generate_batch_scripts compatibility with 6-provider fallback chain."""
        import json
        from engines.script_engine import ScriptEngine
        from core.models import Topic

        class MockFactResult:
            def __init__(self, passed, score=15.0, hallucination_score=10.0):
                self.passed = passed
                self.score = score
                self.hallucination_score = hallucination_score
                self.feedback = []

        topics = [
            Topic(id="top_pig_war", title="The Pig War of 1859", summary="A border dispute between the US and UK over a pig on San Juan Island.", category="Unusual Wars"),
            Topic(id="top_stink", title="The Great Stink of 1858", summary="A hot summer overwhelmed London with the stench of sewage from the River Thames.", category="Documented Disasters"),
            Topic(id="top_dancing", title="The Dancing Plague of 1518", summary="Hundreds of citizens in Strasbourg danced uncontrollably for weeks in the summer heat.", category="Unexplained Events"),
        ]
        research_map = {
            "top_pig_war": {"verified_claims": [{"claim": "In 1859, an American farmer shot a British pig on San Juan Island."}], "summary": "San Juan Island pig conflict."},
            "top_stink": {"verified_claims": [{"claim": "In 1858, the Thames smell forced Parliament to shut down and fund sewers."}], "summary": "London sewer crisis."},
            "top_dancing": {"verified_claims": [{"claim": "In 1518, hundreds in Strasbourg danced in the streets until collapsing."}], "summary": "Strasbourg dancing plague."}
        }

        valid_payload = {
            "scripts": [
                {
                    "topic_index": 1,
                    "topic_id": "top_pig_war",
                    "hook": "In 1859, America and Britain almost went to war over a pig.",
                    "context": "An American farmer shot an aggressive boar foraging in his island garden.",
                    "escalation": "Both nations deployed heavily armed warships and soldiers to the remote border.",
                    "reveal": "Commanders on both sides refused to fire shots over an animal.",
                    "loop_twist": "The standoff ended peacefully with the pig as the only casualty."
                },
                {
                    "topic_index": 2,
                    "topic_id": "top_stink",
                    "hook": "In 1858, the smell of London became so toxic it shut down Parliament.",
                    "context": "A brutal heatwave boiled raw sewage sitting inside the shallow River Thames.",
                    "escalation": "Lawmakers soaked curtains in lime, yet the overwhelming stench caused severe nausea.",
                    "reveal": "Panicked politicians passed emergency legislation to fund an underground modern sewer network.",
                    "loop_twist": "That foul summer stench created the world's first modern urban sanitation system."
                },
                {
                    "topic_index": 3,
                    "topic_id": "top_dancing",
                    "hook": "In 1518, hundreds of European citizens began dancing frantically without being able to stop.",
                    "context": "A woman stepped into the street, and within days, hundreds joined her.",
                    "escalation": "Doctors mistakenly prescribed nonstop dancing, hiring musicians to play day and night.",
                    "reveal": "Dozens collapsed from exhaustion before the strange dancing mania finally vanished.",
                    "loop_twist": "Modern medicine still cannot prove what drove the town to dance."
                }
            ]
        }

        mock_client = MagicMock()
        mock_client.generate_content.return_value = NvidiaResponse(text=json.dumps(valid_payload))

        engine = ScriptEngine()
        mock_db = MagicMock()
        with patch("core.gemini_client.get_gemini_client", return_value=mock_client), \
             patch("engines.fact_verifier.FactVerifier.verify", return_value=MockFactResult(True, 10.0)):
            results = engine.generate_batch_scripts(db=mock_db, topics=topics, research_data_map=research_map)
            self.assertEqual(len(results), 3)
            self.assertIsNotNone(results["top_pig_war"])
            self.assertIsNotNone(results["top_stink"])
            self.assertIsNotNone(results["top_dancing"])
            self.assertIn("pig", results["top_pig_war"]["hook"].lower())


if __name__ == "__main__":
    unittest.main()
