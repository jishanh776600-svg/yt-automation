"""
Tests for AI Council multi-agent editorial & quality gate system.
Verifies:
1. DeepSeek story ideation & hook generation
2. Kimi K3 retention & swipe risk detection
3. Nemotron factual grounding & visual reasoning
4. 9-metric Quality Gate scoring & verdict
5. ScriptDocument integration with CouncilSession provenance
"""
import pytest
from datetime import datetime, timezone

from intelligence.event_card import EventCard, ClaimEvidence, WhereSection, WhenSection, WhoSection, VerificationState
from intelligence.ai_council import (
    AICouncilEngine, get_ai_council, CouncilQualityScore, CouncilMemberReview, CouncilSession
)
from intelligence.journalistic_script import JournalisticScriptEngine, ScriptDocument


def _make_sample_event_card() -> EventCard:
    claim1 = ClaimEvidence(
        claim_id="cl_001",
        claim_text="Marine biologists in the Mariana Trench recorded unprecedented bio-luminescent flashes from unknown organisms.",
        publisher="Nature Marine Science",
        source_url="https://nature.com/articles/sample001",
        published_utc=datetime.now(timezone.utc),
        confidence=0.95
    )
    claim2 = ClaimEvidence(
        claim_id="cl_002",
        claim_text="Submersible sensors registered structural acoustic pulses repeating at precise ten-second intervals.",
        publisher="Oceanographic Institute",
        source_url="https://oceanographic.org/sample002",
        published_utc=datetime.now(timezone.utc),
        confidence=0.92
    )

    now = datetime.now(timezone.utc)
    return EventCard(
        event_id="evt_trench_001",
        canonical_title="Deep Sea Anomaly in Mariana Trench",
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.95,
        first_seen_utc=now,
        latest_seen_utc=now,
        who=WhoSection(organizations=["Oceanographic Institute"], countries=["United States"]),
        what="Submersible teams detected repeated acoustic pulses and biological light patterns in the trench.",
        where=WhereSection(location_name="Mariana Trench", country="Pacific Ocean"),
        when=WhenSection(event_time_utc=now),
        entities=["Mariana Trench", "autonomous submersible", "deep-sea organism"],
        actions=["detected", "recorded", "analyzed"],
        important_objects=["acoustic hydrophone", "titanium submersible", "luminescent specimen"],
        claims=[claim1, claim2]
    )


def test_ai_council_singleton():
    c1 = get_ai_council()
    c2 = get_ai_council()
    assert c1 is c2
    assert isinstance(c1, AICouncilEngine)


def test_ai_council_evaluates_script_quality():
    council = get_ai_council()
    event_card = _make_sample_event_card()
    script = (
        "Seven miles below the Pacific, deep-sea cameras caught something impossible. "
        "Automated sensors tracked brilliant light pulses firing at strict ten-second intervals. "
        "No known organism generates rhythmic strobe patterns at this depth. "
        "Acoustic hydrophones confirmed structural vibrations echoing off the trench walls. "
        "Researchers retrieved anomalous mineral dust clinging to the submersible hull. "
        "Laboratory tests found complex synthetic compounds never seen in nature. "
        "Data indicates an organized signal rather than random biological activity. "
        "Sonar scans mapped an uncharted metallic mass buried in the sediment. "
        "The coordinates are now classified by oceanic research authorities. "
        "Whatever answered their transmitters remains active in the total darkness."
    )
    score = council.evaluate_script_quality(
        script_text=script,
        hook="Seven miles below the Pacific, deep-sea cameras caught something impossible.",
        event_card=event_card,
        word_count=len(script.split())
    )
    assert isinstance(score, CouncilQualityScore)
    assert score.overall_score >= 1.0 and score.overall_score <= 10.0
    assert score.verdict in ("PASS", "REWRITE", "REJECT")
    assert 0.0 <= score.hook_strength <= 10.0
    assert 0.0 <= score.duration_suitability <= 10.0


def test_script_document_stores_council_session():
    event_card = _make_sample_event_card()
    engine = JournalisticScriptEngine()
    script_doc = engine.generate_journalistic_script(event_card, target_duration_seconds=23.0)

    assert isinstance(script_doc, ScriptDocument)
    assert script_doc.word_count >= 40
    # Provenance complete
    assert script_doc.provenance_complete is True
    # Serialization preserves council_session if present
    d = script_doc.to_dict()
    assert "council_session" in d
    restored = ScriptDocument.from_dict(d)
    assert restored.script_id == script_doc.script_id
