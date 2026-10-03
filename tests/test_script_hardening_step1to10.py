"""
Unit & Integration Test Suite: Script Generation Node Hardening (Steps 1-10)
Verifies all 13 production invariants:
1. 50-word narration accepted
2. 56-word narration accepted
3. 49-word narration rejected
4. 57-word narration rejected
5. Date-based hook rejected
6. 1-8 word contradiction hook accepted
7. Markdown leakage rejected
8. Generic AI filler rejected
9. Generic Pexels query rejected
10. Specific historical video query accepted
11. Image asset metadata rejected
12. Output JSON parsing compatibility
13. Downstream schema compatibility (ScriptRecord & Storyboard)
"""
import unittest
import json
import re
from core.database import init_db, SessionLocal
from core.models import Topic, ScriptRecord
from core.content_profile import HISTORICAL_PROFILE
from engines.script_engine import ScriptCritic, ScriptEngine, CURATED_SCRIPTS, sanitize_script_text
from engines.storyboard_engine import StoryboardEngine
from intelligence.event_card import (
    EventCard, ClaimEvidence, VerificationState, WhoSection, WhereSection, WhenSection
)
from intelligence.journalistic_script import (
    JournalisticScriptEngine, JournalisticValidationGate, ScriptDocument, ScriptBeat, ScriptBeatType
)


class TestScriptHardeningSteps1To10(unittest.TestCase):

    def setUp(self):
        init_db()
        self.db = SessionLocal()
        self.critic = ScriptCritic(profile=HISTORICAL_PROFILE)
        self.mock_research = {
            "topic_title": "The Liechtensteiner Army of 1866",
            "summary": "Liechtenstein deployed eighty soldiers to defend a mountain pass. They returned with eighty-one soldiers without casualties.",
            "verified_claims": [
                {"claim": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.", "verified": True},
                {"claim": "They befriended an Italian officer who chose to enlist with them.", "verified": True},
                {"claim": "Their legendary military campaign concluded with negative one total combat casualties.", "verified": True}
            ],
            "claims_count": 3
        }

    def tearDown(self):
        self.db.close()

    def test_01_fifty_word_narration_accepted(self):
        """1. Valid 50-word script passes ScriptCritic quality gate."""
        # 7 + 10 + 11 + 11 + 11 = 50 words
        script_50 = {
            "hook": "An eighty-man army returned with eighty-one soldiers.",
            "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
            "escalation": "They patrolled the quiet alpine border for weeks without seeing combat.",
            "reveal": "Marching home, they befriended an Italian officer who joined their ranks.",
            "loop_twist": "Their legendary military campaign concluded with negative one total combat casualties."
        }
        full_text = " ".join(script_50.values())
        self.assertEqual(len(full_text.split()), 50)
        res = self.critic.evaluate(script_50)
        self.assertTrue(res.passed, f"50-word script should pass. Feedback: {res.feedback}")

    def test_02_fifty_six_word_narration_accepted(self):
        """2. Valid 56-word script passes ScriptCritic quality gate."""
        # 8 + 12 + 12 + 12 + 12 = 56 words
        script_56 = {
            "hook": "An elite military unit surrendered to flightless birds.",
            "context": "Australian soldiers arrived armed with heavy machine guns against twenty thousand emus.",
            "escalation": "The birds quickly split into small ambush groups, outmaneuvering every tactical attack.",
            "reveal": "After weeks of humiliating failure, the commanding defense minister ordered complete withdrawal.",
            "loop_twist": "The military retreated completely defeated, leaving the wild emus victorious in battle."
        }
        full_text = " ".join(script_56.values())
        self.assertEqual(len(full_text.split()), 56)
        res = self.critic.evaluate(script_56)
        self.assertTrue(res.passed, f"56-word script should pass. Feedback: {res.feedback}")

    def test_03_forty_nine_word_narration_rejected(self):
        """3. 49-word narration is rejected by ScriptCritic."""
        # 7 + 10 + 10 + 11 + 11 = 49 words
        script_49 = {
            "hook": "An eighty-man army returned with eighty-one soldiers.",
            "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
            "escalation": "They patrolled the quiet alpine border without seeing any combat.",
            "reveal": "Marching home, they befriended an Italian officer who joined their ranks.",
            "loop_twist": "Their legendary military campaign concluded with negative one total combat casualties."
        }
        full_text = " ".join(script_49.values())
        self.assertEqual(len(full_text.split()), 49)
        res = self.critic.evaluate(script_49, self.mock_research)
        self.assertFalse(res.passed, "49-word script must fail strict 50-56 word bounds.")
        self.assertTrue(any("outside strict 50-56 word bounds" in f for f in res.feedback))

    def test_04_fifty_seven_word_narration_rejected(self):
        """4. 57-word narration is rejected by ScriptCritic."""
        # 8 + 12 + 12 + 12 + 13 = 57 words
        script_57 = {
            "hook": "An elite military unit surrendered to flightless birds.",
            "context": "Australian soldiers arrived armed with heavy machine guns against twenty thousand emus.",
            "escalation": "The birds quickly split into small ambush groups, outmaneuvering every tactical attack.",
            "reveal": "After weeks of humiliating failure, the commanding defense minister ordered complete withdrawal.",
            "loop_twist": "The military retreated completely defeated today, leaving the wild emus victorious in battle."
        }
        full_text = " ".join(script_57.values())
        self.assertEqual(len(full_text.split()), 57)
        res = self.critic.evaluate(script_57)
        self.assertFalse(res.passed, "57-word script must fail strict 50-56 word bounds.")
        self.assertTrue(any("outside strict 50-56 word bounds" in f for f in res.feedback))

    def test_05_date_and_location_based_hooks_rejected(self):
        """5. Hooks starting with dates, years, locations, or rhetorical questions are rejected."""
        forbidden_hooks = [
            "In 1784, a war ended with a broken kettle.",
            "In 1876, fresh meat fell from the sky.",
            "In London, toxic stench shut down the parliament.",
            "In July 1945, warships clashed across the open sea.",
            "Did you know an army attacked its own troops?",
            "Imagine soaring high in hot air balloon duels.",
            "Back in 1808, two men fought over love.",
            "This is the story of history's shortest military conflict."
        ]
        for bad_hook in forbidden_hooks:
            script = {
                "hook": bad_hook,
                "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
                "escalation": "They patrolled the quiet alpine border for weeks without seeing combat.",
                "reveal": "Marching home, they befriended an Italian officer who joined their ranks.",
                "loop_twist": "Their legendary military campaign concluded with negative one total combat casualties."
            }
            res = self.critic.evaluate(script, self.mock_research)
            self.assertFalse(res.passed, f"Hook '{bad_hook}' must be rejected.")
            self.assertTrue(any("Forbidden hook opening detected" in f for f in res.feedback), f"No hook opening rejection for '{bad_hook}'")

    def test_06_one_to_eight_word_contradiction_hook_accepted(self):
        """6. 1-8 word contradiction/shock hook passes quality gate."""
        valid_hooks = [
            "An eighty-man army returned with eighty-one soldiers.",
            "One cannon shot ended an entire European war.",
            "Fresh meat mysteriously rained from a clear sky.",
            "Rival duelists fought in soaring hot air balloons.",
            "A dead pope stood trial for serious treason.",
            "A giant lake vanished into a salt mine.",
            "Two sovereign nations fought over a stray dog."
        ]
        for hook in valid_hooks:
            hook_words = hook.split()
            self.assertLessEqual(len(hook_words), 8)
            self.assertGreaterEqual(len(hook_words), 1)
            script = {
                "hook": hook,
                "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
                "escalation": "They patrolled the quiet alpine border for weeks without combat.",
                "reveal": "Marching home, they befriended an Italian officer who joined ranks.",
                "loop_twist": "Their legendary campaign concluded with negative one total combat casualties."
            }
            # Adjust word count if needed
            words = " ".join(script.values()).split()
            if len(words) < 50:
                script["context"] += " In the year eighteen sixty-six."
            res = self.critic.evaluate(script, self.mock_research)
            self.assertFalse(any("Forbidden hook opening" in f for f in res.feedback))
            self.assertFalse(any("Hook length" in f for f in res.feedback))

    def test_07_markdown_leakage_rejected_and_sanitized(self):
        """7. Markdown formatting (**, *, _, #) is rejected by critic and cleanly stripped by sanitizer."""
        dirty_script = {
            "hook": "**An eighty-man army** returned with eighty-one soldiers.",
            "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
            "escalation": "They patrolled the *quiet* alpine border for weeks without seeing combat.",
            "reveal": "Marching home, they befriended an Italian officer who joined their ranks.",
            "loop_twist": "Their legendary military campaign concluded with negative one total combat casualties."
        }
        res = self.critic.evaluate(dirty_script, self.mock_research)
        self.assertFalse(res.passed, "Dirty markdown script must fail critic.")
        self.assertTrue(any("Markdown syntax" in f for f in res.feedback))

        # Verify sanitizer cleans it
        clean_hook = sanitize_script_text(dirty_script["hook"])
        self.assertEqual(clean_hook, "An eighty-man army returned with eighty-one soldiers.")
        self.assertNotIn("**", clean_hook)

    def test_08_generic_ai_filler_and_loop_cliches_rejected(self):
        """8. AI filler cliches and artificial loop cliches are rejected with penalty."""
        bad_loop_script = {
            "hook": "An eighty-man army returned with eighty-one soldiers.",
            "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
            "escalation": "They patrolled the quiet alpine border for weeks without seeing combat.",
            "reveal": "Marching home, they befriended an Italian officer who joined their ranks.",
            "loop_twist": "And that's why their legendary campaign had negative one casualties."
        }
        res = self.critic.evaluate(bad_loop_script, self.mock_research)
        self.assertFalse(res.passed)
        self.assertTrue(any("Forbidden loop cliché detected" in f for f in res.feedback))

    def test_09_generic_pexels_queries_rejected_by_storyboard(self):
        """9. Storyboard rejects generic single-word queries (history, soldier, city, war, etc.)."""
        for generic in ["history", "soldier", "city", "war", "businessman", "people"]:
            scene = {
                "shot_id": f"shot_{generic}",
                "start_time": 0.0,
                "end_time": 3.0,
                "asset_type": "video",
                "search_query": generic
            }
            with self.assertRaises(ValueError) as ctx:
                StoryboardEngine.validate_storyboard_scene(scene)
            self.assertTrue(
                "prohibited generic visual query" in str(ctx.exception) or "at least 2 words" in str(ctx.exception),
                f"Expected generic query rejection for '{generic}', got {ctx.exception}"
            )

    def test_10_specific_historical_video_queries_accepted(self):
        """10. Specific multi-word moving video queries pass storyboard validation."""
        valid_queries = [
            "19th century infantry marching battlefield smoke period reenactment",
            "vintage horse carriage moving European cobblestone street",
            "naval patrol destroyer sailing ocean waves stormy seas",
            "historical crowd cheering victory parade documentary film"
        ]
        for q in valid_queries:
            scene = {
                "shot_id": "shot_valid",
                "start_time": 0.0,
                "end_time": 3.0,
                "asset_type": "video",
                "search_query": q
            }
            self.assertTrue(StoryboardEngine.validate_storyboard_scene(scene))

    def test_11_image_asset_metadata_rejected_by_storyboard(self):
        """11. Storyboard rejects scenes specifying image asset types or image file paths."""
        image_scenes = [
            {"shot_id": "s1", "start_time": 0.0, "end_time": 2.5, "asset_type": "image", "search_query": "marching infantry"},
            {"shot_id": "s2", "start_time": 0.0, "end_time": 2.5, "asset_type": "still", "search_query": "marching infantry"},
            {"shot_id": "s3", "start_time": 0.0, "end_time": 2.5, "asset_type": "video", "search_query": "marching infantry portrait", "image_path": "test.jpg"},
            {"shot_id": "s4", "start_time": 0.0, "end_time": 2.5, "asset_type": "video", "search_query": "marching infantry portrait", "photo_url": "https://img.com/p.jpg"}
        ]
        for sc in image_scenes:
            with self.assertRaises(ValueError):
                StoryboardEngine.validate_storyboard_scene(sc)

    def test_12_json_parsing_and_sanitization_compatibility(self):
        """12. JSON payload with 5 keys parses cleanly and passes downstream requirements."""
        raw_ai_json = json.dumps({
            "hook": "**One cannon shot** ended an entire European war.",
            "context": "Imperial warships sailed forward to challenge Dutch trade ports in 1784.",
            "escalation": "A Dutch defender fired a single warning cannon shot across the harbor.",
            "reveal": "The cannonball struck an iron kettle, spraying hot boiling soup across the deck.",
            "loop_twist": "Terrified by soup, the entire imperial fleet immediately surrendered without casualties."
        })
        data = json.loads(raw_ai_json)
        sanitized = {k: sanitize_script_text(v) for k, v in data.items()}
        self.assertNotIn("**", sanitized["hook"])
        self.assertEqual(len(sanitized["hook"].split()), 8)
        full_text = " ".join(sanitized.values())
        self.assertTrue(50 <= len(full_text.split()) <= 56)

    def test_13_downstream_schema_compatibility_with_script_record(self):
        """13. Verified script constructs a valid ScriptRecord for downstream storyboard execution."""
        topic = Topic(
            id="test_top_liechtenstein",
            title="The Liechtensteiner Army of 1866",
            summary="Liechtenstein sent eighty men to war and returned with eighty-one.",
            category="Documented Disasters"
        )
        engine = ScriptEngine(profile=HISTORICAL_PROFILE)
        # Use curated script fallback
        script_rec = engine.generate_script(self.db, topic, self.mock_research)
        self.assertIsNotNone(script_rec)
        self.assertTrue(50 <= script_rec.word_count <= 56, f"Word count ({script_rec.word_count}) must be 50-56.")
        self.assertTrue(1 <= len(script_rec.hook.split()) <= 8, f"Hook length ({len(script_rec.hook.split())}) must be 1-8.")

        # Storyboard generation executes cleanly
        sb_engine = StoryboardEngine()
        shots = sb_engine.create_storyboard(script_rec)
        self.assertGreaterEqual(len(shots), 8)
        for shot in shots:
            self.assertEqual(shot["asset_type"], "video")
            self.assertGreaterEqual(len(shot["search_query"].split()), 2)


if __name__ == "__main__":
    unittest.main()
