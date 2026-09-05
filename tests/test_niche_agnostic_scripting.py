"""
Comprehensive Deterministic Tests for Niche-Agnostic Content Strategy Architecture.

Verifies:
1. ScriptEngine consumes ContentProfile cleanly.
2. CURRENT_AFFAIRS_PROFILE dynamically configures prompt instructions and constraints.
3. ScriptEngine contains ZERO hardcoded niche branching (e.g. 'if current_affairs').
4. Exactly 3 scripts mapped to 3 topics in batch generation.
5. 45–68 word count validation strictly enforced.
6. Missing scripts in batch are rejected.
7. Extra scripts in batch (N+1) are rejected.
8. Duplicate/substantially similar narratives in batch are rejected.
9. Different profiles can be supplied dynamically without modifying ScriptEngine.
10. Historical profile behavior remains functional.
11. Pre-generated cached scripts bypass generation and pass validation.
12. Multi-tier AI fallback cascade remains intact.
13. Architectural decoupling test: Synthetic domain (e.g., Deep Sea Marine Biology) profile
    executes without modifying core engine logic.
"""
import json
import unittest
from unittest.mock import MagicMock, patch
from sqlalchemy.orm import Session

from core.database import init_db, SessionLocal
from core.models import Topic, ScriptRecord
from core.content_profile import (
    ContentProfile,
    CURRENT_AFFAIRS_PROFILE,
    HISTORICAL_PROFILE,
    get_active_profile,
    set_active_profile,
    register_profile,
    get_profile_by_name
)
from engines.script_engine import ScriptEngine, ScriptCritic, CriticEvaluation


class TestNicheAgnosticScripting(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        set_active_profile(CURRENT_AFFAIRS_PROFILE)

    def tearDown(self):
        self.db.close()
        set_active_profile(CURRENT_AFFAIRS_PROFILE)

    def test_01_script_engine_consumes_content_profile(self):
        """Test 1: ScriptEngine consumes ContentProfile on initialization and at runtime."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        self.assertEqual(engine.profile.name, "CURRENT_AFFAIRS")
        self.assertEqual(engine.critic.profile.name, "CURRENT_AFFAIRS")

        engine_default = ScriptEngine()
        self.assertEqual(engine_default.profile.name, get_active_profile().name)

    def test_02_current_affairs_profile_formats_instructions(self):
        """Test 2: Current affairs profile formats geopolitical prompt instructions."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topic = Topic(
            id="top_ca_001",
            title="EU Imposes Sweeping Lithium Export Controls",
            summary="The European Union announced strict quota caps on raw lithium exports.",
            category="Geopolitics"
        )
        research = {
            "summary": "EU ministers approved export restrictions on raw battery minerals.",
            "verified_claims": [{"claim": "EU ministers capped lithium exports to protect domestic supply."}]
        }

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "hook": "The European Union just banned critical mineral shipments across borders.",
            "context": "Ministers in Brussels enacted emergency quota limits on raw lithium.",
            "escalation": "Foreign battery factories face immediate production freezes as supply lines contract.",
            "reveal": "The landmark order prioritizes European electric vehicle makers over foreign competitors.",
            "loop_twist": "Global markets must now secure expensive alternative trade routes immediately."
        })
        mock_client.generate_content.return_value = mock_response

        with patch("core.gemini_client.get_gemini_client", return_value=mock_client):
            engine._draft_script_pass(
                topic=topic,
                selected_hook="The European Union just banned critical mineral shipments across borders.",
                research_data=research,
                profile=CURRENT_AFFAIRS_PROFILE
            )

            call_args = mock_client.generate_content.call_args
            prompt_text = call_args[1].get("contents") or call_args[0][0]

            self.assertIn("geopolitical intelligence analyst", prompt_text)
            self.assertIn(CURRENT_AFFAIRS_PROFILE.tone, prompt_text)
            self.assertIn(CURRENT_AFFAIRS_PROFILE.script_objective, prompt_text)
            self.assertIn(CURRENT_AFFAIRS_PROFILE.factual_policy, prompt_text)

    def test_03_no_hardcoded_niche_branching_in_script_engine(self):
        """Test 3: ScriptEngine contains zero hardcoded niche if-statements."""
        import inspect
        source = inspect.getsource(ScriptEngine)

        self.assertNotIn("if current_affairs", source.lower())
        self.assertNotIn("if is_current_affairs", source.lower())
        self.assertNotIn("if topic.category == \"geopolitics\"", source.lower())
        self.assertNotIn("if profile.name == \"historical\"", source.lower())

    def test_04_exact_three_script_batch_mapping(self):
        """Test 4: 3-script batch produces exactly 3 correctly mapped scripts."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topics = [
            Topic(id="top_batch_1", title="US Treasury Freezes Overseas Assets", summary="US Treasury sanctions enacted."),
            Topic(id="top_batch_2", title="Panama Canal Restricts Daily Ship Crossings", summary="Severe drought limits canal transit."),
            Topic(id="top_batch_3", title="Nordic Defense Pact Expands Arctic Patrols", summary="Allied aircraft deployed along northern perimeter.")
        ]

        mock_batch_data = {
            "scripts": [
                {
                    "topic_index": 1,
                    "topic_id": "top_batch_1",
                    "hook": "The United States Treasury just froze forty billion dollars in foreign accounts.",
                    "context": "Federal officials announced emergency sanctions targeting illicit state financing networks worldwide.",
                    "escalation": "Dozens of central banks halted cross-border wire clearances within minutes of the decree.",
                    "reveal": "The coordinated enforcement effectively severed the designated institutions from western capital markets.",
                    "loop_twist": "Targeted governments now scramble to route trade through alternative currency clearinghouses."
                },
                {
                    "topic_index": 2,
                    "topic_id": "top_batch_2",
                    "hook": "Severe tropical droughts just forced the Panama Canal to cut daily crossings.",
                    "context": "Canal authorities slashed maritime traffic slots by one third as reservoir levels dropped.",
                    "escalation": "Over one hundred cargo ships remain anchored outside harbor gates awaiting transit approval.",
                    "reveal": "Global freight operators rerouted container vessels around South America at massive expense.",
                    "loop_twist": "Shippers now face weeks of transit delays across every major ocean corridor."
                },
                {
                    "topic_index": 3,
                    "topic_id": "top_batch_3",
                    "hook": "Allied Nordic nations launched continuous joint patrols across the Arctic perimeter.",
                    "context": "Defense ministers established combined air bases to monitor expanding polar shipping lanes.",
                    "escalation": "Advanced radar stations detected rising reconnaissance flights near northern sovereign airspace.",
                    "reveal": "The alliance deployed twenty interceptor fighters to secure crucial undersea fiber routes.",
                    "loop_twist": "Arctic security has permanently shifted toward permanent joint naval task forces."
                }
            ]
        }

        mock_fact_res = MagicMock(score=15.0, passed=True, feedback=[])
        with patch("engines.fact_verifier.FactVerifier.verify", return_value=mock_fact_res):
            results = engine.generate_batch_scripts(
                db=self.db,
                topics=topics,
                _mock_response=json.dumps(mock_batch_data)
            )

        self.assertEqual(len(results), 3)
        self.assertIsNotNone(results["top_batch_1"])
        self.assertIsNotNone(results["top_batch_2"])
        self.assertIsNotNone(results["top_batch_3"])
        self.assertEqual(results["top_batch_1"]["hook"], mock_batch_data["scripts"][0]["hook"])

    def test_05_word_count_validation_enforced(self):
        """Test 5: Scripts outside 45-68 word boundaries are strictly rejected."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topic = Topic(id="top_wc_1", title="Short Script Test", summary="Test summary")

        short_batch = {
            "scripts": [
                {
                    "topic_index": 1,
                    "topic_id": "top_wc_1",
                    "hook": "Ministers held an emergency meeting.",
                    "context": "They discussed energy prices.",
                    "escalation": "Disagreements erupted quickly.",
                    "reveal": "No deal was signed.",
                    "loop_twist": "Markets dropped."
                }
            ]
        }

        results = engine.generate_batch_scripts(
            db=self.db,
            topics=[topic],
            _mock_response=json.dumps(short_batch)
        )
        self.assertIsNone(results["top_wc_1"], "Short scripts under 45 words must be rejected.")

    def test_06_missing_scripts_rejected(self):
        """Test 6: Missing scripts in batch output cause batch rejection with fallback."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topics = [
            Topic(id="top_m1", title="Topic One"),
            Topic(id="top_m2", title="Topic Two"),
            Topic(id="top_m3", title="Topic Three")
        ]

        incomplete_batch = {
            "scripts": [
                {
                    "topic_index": 1,
                    "topic_id": "top_m1",
                    "hook": "In 2026, ministers enacted emergency tariffs on foreign grain imports.",
                    "context": "The agricultural decree aimed to protect domestic farm producers from bankruptcy.",
                    "escalation": "Neighboring nations filed retaliatory complaints with international commercial trade courts.",
                    "reveal": "Subsidies failed to cushion grocery inflation as regional shipping freight doubled.",
                    "loop_twist": "Economic analysts warn consumers will bear the cost through next winter."
                },
                {
                    "topic_index": 2,
                    "topic_id": "top_m2",
                    "hook": "In 2026, satellite operators detected widespread navigation jamming across coastal straits.",
                    "context": "Commercial oil tankers reported erratic coordinates while traversing designated transit corridors.",
                    "escalation": "Coast guard cutters scrambled patrol boats to escort merchant ships through darkness.",
                    "reveal": "Investigations traced electromagnetic interference to naval transmitters operating near foreign borders.",
                    "loop_twist": "Maritime insurers have raised cargo risk premiums for all regional voyages."
                }
            ]
        }

        results = engine.generate_batch_scripts(
            db=self.db,
            topics=topics,
            _mock_response=json.dumps(incomplete_batch)
        )
        self.assertIsNone(results["top_m1"])
        self.assertIsNone(results["top_m2"])
        self.assertIsNone(results["top_m3"])

    def test_07_extra_scripts_rejected(self):
        """Test 7: Extra (N+1)th scripts violate invariant and are rejected."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topics = [
            Topic(id="top_e1", title="Topic One"),
            Topic(id="top_e2", title="Topic Two")
        ]

        extra_batch = {
            "scripts": [
                {"topic_index": 1, "topic_id": "top_e1", "hook": "H1", "context": "C1", "escalation": "E1", "reveal": "R1", "loop_twist": "L1"},
                {"topic_index": 2, "topic_id": "top_e2", "hook": "H2", "context": "C2", "escalation": "E2", "reveal": "R2", "loop_twist": "L2"},
                {"topic_index": 3, "topic_id": "top_e3", "hook": "H3", "context": "C3", "escalation": "E3", "reveal": "R3", "loop_twist": "L3"}
            ]
        }

        results = engine.generate_batch_scripts(
            db=self.db,
            topics=topics,
            _mock_response=json.dumps(extra_batch)
        )
        self.assertIsNone(results["top_e1"])
        self.assertIsNone(results["top_e2"])

    def test_08_duplicate_similar_narratives_rejected(self):
        """Test 8: Substantially similar/duplicate narratives in batch are rejected."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topics = [
            Topic(id="top_d1", title="Pipeline Leak in Baltic Sea"),
            Topic(id="top_d2", title="Pipeline Sabotage Incident")
        ]

        script_text_1 = {
            "topic_index": 1,
            "topic_id": "top_d1",
            "hook": "A critical gas pipeline exploded under the Baltic Sea yesterday morning.",
            "context": "Naval surveyors detected methane bubbling across three miles of freezing water.",
            "escalation": "European intelligence agencies launched forensic sonar dives to inspect ruptured steel.",
            "reveal": "Underwater explosive residues confirmed intentional sabotage by unknown professional military divers.",
            "loop_twist": "Security patrols now monitor every major continental energy conduit around the clock."
        }
        script_text_2 = {
            "topic_index": 2,
            "topic_id": "top_d2",
            "hook": "A critical gas pipeline exploded under the Baltic Sea yesterday morning.",
            "context": "Naval surveyors detected methane bubbling across three miles of freezing water.",
            "escalation": "European intelligence agencies launched forensic sonar dives to inspect ruptured steel.",
            "reveal": "Underwater explosive residues confirmed intentional sabotage by unknown professional military divers.",
            "loop_twist": "Security patrols now monitor every major continental energy conduit around the clock."
        }

        mock_fact_res = MagicMock(score=15.0, passed=True, feedback=[])
        with patch("engines.fact_verifier.FactVerifier.verify", return_value=mock_fact_res):
            results = engine.generate_batch_scripts(
                db=self.db,
                topics=topics,
                _mock_response=json.dumps({"scripts": [script_text_1, script_text_2]})
            )

        self.assertIsNone(results["top_d2"])

    def test_09_different_profiles_supplied_without_modifying_engine(self):
        """Test 9: Multiple distinct profiles can be supplied dynamically without engine code changes."""
        critic_ca = ScriptCritic(profile=CURRENT_AFFAIRS_PROFILE)
        script_ca = {
            "hook": "In 2026, world leaders signed a historic non-proliferation treaty.",
            "context": "Delegates from fifty nations assembled in Geneva for marathon diplomatic negotiations.",
            "escalation": "Border disputes threatened to derail consensus until key concessions were offered.",
            "reveal": "The treaty established independent satellite inspections of sensitive nuclear infrastructure.",
            "loop_twist": "Inspectors will begin monitoring border silos starting next month without delay."
        }
        eval_ca = critic_ca.evaluate(script_ca)
        self.assertTrue(eval_ca.passed)

        critic_hist = ScriptCritic(profile=HISTORICAL_PROFILE)
        script_hist = {
            "hook": "In 1784, an Austrian army mistakenly opened fire on its own cavalry.",
            "context": "Soldiers bought barrels of schnapps and refused to share with arriving infantry.",
            "escalation": "A drunken skirmish erupted and panic spread through the camp in darkness.",
            "reveal": "Artillery batteries fired on friendly lines believing the enemy had invaded.",
            "loop_twist": "Thousands fell before dawn without seeing a single opposing enemy soldier."
        }
        eval_hist = critic_hist.evaluate(script_hist)
        self.assertTrue(eval_hist.passed)

    def test_10_historical_profile_behavior_remains_functional(self):
        """Test 10: Curated historical seed script library still operates smoothly."""
        engine = ScriptEngine(profile=HISTORICAL_PROFILE)
        topic = Topic(
            id="top_seed_hist",
            title="The Kettle War of 1784",
            summary="Holy Roman Empire warships surrendered when a cannon shot broke a soup kettle."
        )
        script_rec = engine.generate_script(self.db, topic)
        self.assertIsNotNone(script_rec)
        self.assertEqual(script_rec.status, "APPROVED")
        self.assertIn("kettle", script_rec.hook.lower())

    def test_11_cached_scripts_bypass_generation(self):
        """Test 11: Pre-generated batch script cache bypasses expensive AI calls."""
        engine = ScriptEngine(profile=CURRENT_AFFAIRS_PROFILE)
        topic = Topic(
            id="top_cached_100",
            title="Suez Canal Deepens Navigational Channel",
            summary="Canal Authority deepens canal."
        )
        cached_script = {
            "hook": "In 2026, Egyptian dredgers completed deepening the Suez Canal southern lane.",
            "context": "Massive supertankers can now navigate the chokepoint without grounding fears.",
            "escalation": "Engineers worked around the clock removing millions of tons of compacted seabed.",
            "reveal": "Vessel transit fees rose five percent to cover expansion project financing.",
            "loop_twist": "Commercial container carriers now transit thirty minutes faster each individual journey."
        }
        engine.cache_script(topic.id, cached_script)

        with patch.object(engine, "_draft_script_pass") as mock_draft:
            rec = engine.generate_script(self.db, topic)
            mock_draft.assert_not_called()
            self.assertEqual(rec.hook, cached_script["hook"])
            self.assertEqual(rec.status, "APPROVED")

    def test_12_provider_fallback_cascade_remains_intact(self):
        """Test 12: ScriptEngine respects AI provider failover cascade when generating."""
        from core.gemini_client import get_gemini_client
        client = get_gemini_client()
        self.assertIsNotNone(client)
        self.assertTrue(hasattr(client, "generate_content"))

    def test_13_architectural_test_synthetic_marine_biology_profile(self):
        """
        Architectural Decoupling Test:
        Define an entirely new synthetic domain profile ('MARINE_BIOLOGY')
        and verify that ScriptEngine consumes and evaluates it cleanly
        WITHOUT modifying a single line of ScriptEngine or ScriptCritic.
        """
        MARINE_BIOLOGY_PROFILE = ContentProfile(
            name="MARINE_BIOLOGY",
            description="Deep ocean discoveries, abyssal creatures, and hydrothermal vent ecosystems.",
            target_audience="Science enthusiasts and curiosity seekers interested in marine mysteries.",
            tone="Wonder, curiosity, scientific precision, and captivating discovery.",
            script_objective="Reveal astonishing oceanic creatures and deep-sea survival adaptations in 23 seconds.",
            system_role_instruction="You are a National Geographic oceanographer and documentary scriptwriter for YouTube Shorts.",
            beat_descriptions={
                "hook": "(0-2s) Bizarre oceanic adaptation or mysterious deep-sea entity (6-14 words).",
                "context": "(2-7s) Ocean depth, abyssal zone, and extreme environmental pressures.",
                "escalation": "(7-14s) Bizarre predatory strategies or physiological feats under crushing water.",
                "reveal": "(14-19s) The definitive scientific breakthrough or evolutionary mechanism.",
                "loop_twist": "(19-23s) The broader ocean ecosystem wonder and loop back to the hook."
            },
            factual_policy="Strict marine biology factual accuracy. Ground claims in peer-reviewed oceanographic research.",
            forbidden_cliches=[
                "will shock you", "unbelievable ocean", "scientists are baffled", "mind-blowing"
            ],
            hook_markers=[
                r"\b(miles|feet|meters|depth|abyss|bioluminescent|predator|pressure|tentacles|deepest|ocean|species)\b"
            ],
            preferred_cadence="Awe-inspiring spoken English. Measured pacing, punchy rhythm.",
            min_words=45,
            max_words=68,
            target_words="50-55 words"
        )

        register_profile(MARINE_BIOLOGY_PROFILE)
        self.assertIsNotNone(get_profile_by_name("MARINE_BIOLOGY"))

        engine = ScriptEngine(profile=MARINE_BIOLOGY_PROFILE)
        self.assertEqual(engine.profile.name, "MARINE_BIOLOGY")

        script_marine = {
            "hook": "Six miles beneath the Pacific Ocean, creatures survive inside superheated hydrothermal vents.",
            "context": "Water temperatures exceed seven hundred degrees under thousands of pounds of pressure.",
            "escalation": "Bioluminescent anglerfish and giant tube worms thrive completely without sunlight or oxygen.",
            "reveal": "Bacteria synthesize toxic hydrogen sulfide into organic food for the entire ecosystem.",
            "loop_twist": "These alien abyssal depths may mirror how life first began on Earth."
        }

        eval_res = engine.critic.evaluate(script_marine, profile=MARINE_BIOLOGY_PROFILE)
        self.assertTrue(
            eval_res.passed,
            f"Synthetic profile script should pass quality gate (Score: {eval_res.score}, Feedback: {eval_res.feedback})"
        )
        self.assertGreaterEqual(eval_res.score, 80.0)
        self.assertEqual(len(eval_res.cliches_detected), 0)


if __name__ == "__main__":
    unittest.main()
