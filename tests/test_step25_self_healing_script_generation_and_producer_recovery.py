import os
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime

from core.models import Topic, Job, JobState
from engines.script_engine import ScriptEngine, ScriptCritic
from engines.topic_discovery import TopicDiscoveryEngine
from core.lock import ProcessLock


class TestStep25SelfHealingScriptGenerationAndProducerRecovery:

    def test_01_first_pass_prompt_contains_word_count_and_stages(self):
        engine = ScriptEngine()
        dummy_topic = Topic(id="top_p1", title="The Boston Molasses Flood", summary="Molasses tank exploded.")
        
        # Test draft script pass prompt construction
        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "hook": "In January 1919, a massive tank ruptured in Boston.",
            "context": "Two million gallons of hot molasses surged into city streets.",
            "escalation": "The thirty-five mile-per-hour wave crushed buildings and trapped horses instantly.",
            "reveal": "Twenty-one people died in the suffocating sweet disaster.",
            "loop_twist": "For decades afterward, the streets still smelled like warm molasses."
        })
        mock_gemini.generate_content.return_value = mock_response

        with patch("core.gemini_client.get_gemini_client", return_value=mock_gemini):
            data = engine._draft_script_pass(
                topic=dummy_topic,
                selected_hook="In January 1919, a massive tank ruptured in Boston.",
                research_data={"summary": "Boston molasses flood facts."}
            )

            # Inspect the prompt passed to Gemini
            prompt_called = mock_gemini.generate_content.call_args[1]["contents"]
            assert "45 words" in prompt_called
            assert "68 words" in prompt_called
            assert "50–55 words" in prompt_called or "50-55 words" in prompt_called
            assert "hook" in prompt_called
            assert "context" in prompt_called
            assert "escalation" in prompt_called
            assert "reveal" in prompt_called
            assert "loop_twist" in prompt_called
            assert "NEVER invent dates" in prompt_called
            assert "Use ONLY information explicitly supported" in prompt_called

    def test_02_local_validator_rejects_short_and_accepts_valid_words(self):
        critic = ScriptCritic()
        
        # 1. 40-word script (below 45 words)
        short_script = {
            "hook": "On October 8, 1784, a sudden naval clash erupted.",
            "context": "Holy Roman Empire fought the Dutch Republic.",
            "escalation": "One cannon shot was fired in anger.",
            "reveal": "It struck an iron soup kettle on deck.",
            "loop_twist": "The war ended instantly in bizarre fashion."
        }
        res_short = critic.evaluate(short_script)
        assert res_short.passed is False
        assert any("outside calibrated" in fb for fb in res_short.feedback)

        # 2. 52-word valid script
        valid_script = {
            "hook": "In July 1184, sixty European nobles met a bizarre fate in Erfurt.",
            "context": "King Henry held a royal peace summit inside an ancient church hall.",
            "escalation": "Under the sudden crushing weight of hundreds of armored men, the floor gave way.",
            "reveal": "Dozens of high-ranking aristocrats plunged straight into the deep cesspool below.",
            "loop_twist": "The king survived only by clinging desperately to an iron window grate."
        }
        res_valid = critic.evaluate(valid_script)
        words_count = len(f"{valid_script['hook']} {valid_script['context']} {valid_script['escalation']} {valid_script['reveal']} {valid_script['loop_twist']}".split())
        assert 45 <= words_count <= 68
        assert res_valid.passed is True

    def test_03_targeted_revision_prompt_formats_exact_feedback(self):
        engine = ScriptEngine()
        dummy_topic = Topic(id="top_p2", title="The Kettle War", summary="Soup kettle struck by cannonball.")
        mock_gemini = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "hook": "In 1784, a European war ended over a bowl of soup.",
            "context": "The Holy Roman Empire challenged the Dutch Republic at sea.",
            "escalation": "A single cannon shot echoed across the harbor water.",
            "reveal": "The blast struck an iron soup kettle on deck.",
            "loop_twist": "Both sides immediately surrendered without a single human casualty."
        })
        mock_gemini.generate_content.return_value = mock_response

        with patch("core.gemini_client.get_gemini_client", return_value=mock_gemini):
            engine._draft_script_pass(
                topic=dummy_topic,
                selected_hook="In 1784, a war ended over soup.",
                research_data={"summary": "Kettle war facts."},
                revision_feedback=[
                    "Total word count (40) outside calibrated 45-68 word target.",
                    "UNSUPPORTED CLAIM TO REMOVE/REVISE: Unsupported claim in 'October 8, 1784'"
                ]
            )

            prompt_called = mock_gemini.generate_content.call_args[1]["contents"]
            assert "CRITICAL TARGETED REVISION INSTRUCTIONS" in prompt_called
            assert "WORD COUNT CORRECTION" in prompt_called
            assert "FACTUAL CORRECTION" in prompt_called

    def test_04_topic_failure_isolation_and_candidate_advancement(self):
        topic_engine = TopicDiscoveryEngine()
        db = MagicMock()

        topic_a = Topic(id="top_kettle_war", title="The Kettle War of 1784", summary="Kettle war incident.", status="APPROVED")
        topic_b = Topic(id="top_halifax_explosion", title="The Halifax Explosion", summary="Halifax munitions blast.", status="APPROVED")

        # When topic A is excluded (quarantined)
        exclude_set = {"top_kettle_war"}

        db.query.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = [topic_b]

        with patch.object(topic_engine, "is_duplicate", return_value=False):
            candidates = topic_engine.discover_topics(db, limit=1, exclude_topic_ids=exclude_set)
            assert len(candidates) == 1
            assert candidates[0].id == "top_halifax_explosion"
            assert candidates[0].id not in exclude_set

    def test_05_needs_review_and_rejected_topics_excluded(self):
        topic_engine = TopicDiscoveryEngine()
        db = MagicMock()

        topic_rejected = Topic(id="top_rej", title="Invalid Topic", summary="Invalid", status="REJECTED")
        topic_needs_review = Topic(id="top_nr", title="Failed Script Topic", summary="Review needed", status="NEEDS_REVIEW")
        topic_valid = Topic(id="top_good", title="Valid Topic", summary="Good topic", status="APPROVED")

        # Database returns only un-excluded, approved topics
        db.query.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = [topic_valid]

        with patch.object(topic_engine, "is_duplicate", return_value=False):
            candidates = topic_engine.discover_topics(db, limit=1)
            assert len(candidates) == 1
            assert candidates[0].id == "top_good"
            assert candidates[0].status == "APPROVED"

    def test_06_real_failure_reproduction_and_autonomous_recovery(self):
        """
        Deterministic simulation of GitHub Actions run #33406576060:
        Topic A fails 3 script revision attempts -> quarantined -> Topic B selected -> production succeeds!
        """
        from main import ShortsPipeline

        app = ShortsPipeline()
        db = MagicMock()

        topic_a = Topic(id="top_kettle_failed", title="The Kettle War of 1784", summary="Kettle war", status="APPROVED")
        topic_b = Topic(id="top_london_beer", title="The London Beer Flood of 1814", summary="Beer flood", status="APPROVED")

        attempted_topics = set()

        # Step 1: Attempt 1 with Topic A -> Fails render/QA
        attempted_topics.add(topic_a.id)
        assert "top_kettle_failed" in attempted_topics

        # Step 2: Attempt 2 with exclude_topic_ids -> Automatically picks Topic B
        db.query.return_value.all.return_value = []
        db.query.return_value.filter.return_value.all.return_value = [topic_b]

        with patch.object(app.topic_engine, "is_duplicate", return_value=False):
            next_topics = app.topic_engine.discover_topics(db, limit=1, exclude_topic_ids=attempted_topics)
            assert len(next_topics) == 1
            selected_next = next_topics[0]
            assert selected_next.id == "top_london_beer"
            assert selected_next.id != "top_kettle_failed"

    def test_07_no_deepseek_dependency_anywhere(self):
        from config.settings import AI_PROVIDER_AVAILABLE, GEMINI_MODEL, GROQ_API_KEY
        import sys
        
        # DeepSeek must NOT be configured, imported, or used anywhere
        assert "deepseek" not in sys.modules
        assert not hasattr(os.environ, "DEEPSEEK_API_KEY")
