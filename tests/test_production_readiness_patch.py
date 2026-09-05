"""
Targeted Verification Tests for AL-AMR Production-Readiness Patch.
Covers:
1. Strict Niche Purity Gate (Rejection of politics, approval of mystery/weird science).
2. Hardened Council Quality Gate (Word count 62-70, cliché rejection, hook check).
3. 48-Hour Forward Horizon Scheduler (3/day limit, 48h coverage, past slot filtering).
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from intelligence.clustering import is_niche_compliant
from intelligence.ai_council import AICouncilEngine, CouncilQualityScore
from intelligence.event_card import EventCard, WhereSection, WhenSection, WhoSection, VerificationState
from engines.scheduler_engine import PublicationScheduler, DAILY_SHORTS_LIMIT


def test_niche_purity_rejects_geopolitics_and_war():
    """All politics, diplomacy, elections, and military conflict must be strictly rejected."""
    political_cases = [
        ("Diplomats gather in Geneva for bilateral ceasefire negotiations", "Officials from both governments met to discuss troop withdrawal.", ["Geneva", "Diplomats"]),
        ("Parliament approves sweeping trade tariffs on foreign imports", "Lawmakers debated the new economic legislation.", ["Parliament", "Minister"]),
        ("Military forces launch offensive near disputed border", "Troops and artillery moved into position following drone strikes.", ["Army", "Pentagon"]),
        ("Presidential election results trigger protests outside congress", "Voters turned out in record numbers across the nation.", ["President", "Senate"]),
        ("White house spokesperson comments on national security sanctions", "The administration announced new diplomatic measures.", ["White House", "NATO"]),
    ]
    for title, text, entities in political_cases:
        is_ok, reason = is_niche_compliant(title=title, text=text, entities=entities)
        assert not is_ok, f"Expected rejection for political topic '{title}', but got approval: {reason}"
        assert "REJECTED_POLITICAL_CONTENT" in reason, f"Reason should mention political rejection: {reason}"


def test_niche_purity_approves_mystery_and_weird_science():
    """Mystery, bizarre discoveries, and weird science anomalies must be approved."""
    approved_cases = [
        ("Scientists discover bizarre deep-sea creature near Mariana Trench", "The bioluminescent organism displays an unexplained genetic mutation.", ["Mariana Trench", "Biologists"]),
        ("Ancient pyramid tomb unearthed with mysterious stone anomalies", "Archaeologists discovered baffling subterranean chambers beneath the desert.", ["Egypt", "Archaeologists"]),
        ("Telescope detects strange radio burst from distant galaxy", "Astronomers confirmed an unusual recurring cosmic signal in deep space.", ["Observatory", "Astronomers"]),
        ("Bizarre fossilized skeleton found in Antarctica glacier", "Geologists uncovered an ancient stone age specimen with unusual bone structure.", ["Antarctica", "Geologists"]),
    ]
    for title, text, entities in approved_cases:
        is_ok, reason = is_niche_compliant(title=title, text=text, entities=entities)
        assert is_ok, f"Expected approval for niche topic '{title}', but was rejected: {reason}"
        assert "APPROVED_NICHE" in reason, f"Reason should mention approved niche: {reason}"


def test_niche_purity_rejects_unrelated_content():
    """Content lacking mystery or weird science indicators must be rejected."""
    is_ok, reason = is_niche_compliant(
        title="Stock markets rally after corporate earnings report",
        text="Investors celebrated quarterly profits across retail sectors.",
        entities=["Wall Street"]
    )
    assert not is_ok
    assert "REJECTED_OUT_OF_NICHE" in reason


def test_council_quality_gate_rejects_cliches_and_bad_word_count():
    """Clichés, incorrect word counts (<62 or >70), or generic hooks must trigger REWRITE."""
    council = AICouncilEngine()
    ec = EventCard(
        event_id="ev_test_01",
        canonical_title="Mysterious underwater anomaly discovered by deep-sea submersible",
        what="Unexplained deep ocean sound anomaly recorded near trench",
        why="Natural acoustic resonance",
        how="Hydrophone telemetry array",
        who=WhoSection(organizations=["Oceanographic Institute"], countries=["United States"]),
        first_seen_utc=datetime.now(timezone.utc),
        latest_seen_utc=datetime.now(timezone.utc),
        where=WhereSection(location_name="Mariana Trench", country="Pacific Ocean"),
        when=WhenSection(event_time_utc=datetime.now(timezone.utc)),
        verification_state="CORROBORATED_MULTI_SOURCE",
        confidence=0.95
    )

    # Case A: Too few words (50 words)
    short_script = "Deep below the Pacific, scientists recorded a mysterious sound that defies explanation. " * 5
    short_words = len(short_script.split())
    score_short = council.evaluate_script_quality(
        script_text=short_script,
        hook="Something bizarre is happening under the ocean.",
        event_card=ec,
        word_count=short_words
    )
    assert score_short.verdict == "REWRITE"
    assert "Word count violation" in score_short.critique

    good_length_script = (
        "Something deep beneath the Pacific Ocean is baffling marine biologists. "
        "An autonomous robotic submersible recorded an intense metallic humming sound emerging from six miles below the surface. "
        "The acoustic frequency does not match any known sea creature, seismic fault, or underwater submarine. "
        "When researchers dropped acoustic sensors into the trench, the strange signal suddenly answered back with rhythmic pulses. "
        "No theory currently explains what produced it."
    )
    words = len(good_length_script.split())
    assert 62 <= words <= 70, f"Test script word count {words} should be 62-70"

    score_generic_hook = council.evaluate_script_quality(
        script_text=good_length_script,
        hook="Today, officials announced a discovery.",
        event_card=ec,
        word_count=words
    )
    assert score_generic_hook.verdict == "REWRITE"
    assert "Generic news hook detected" in score_generic_hook.critique

    # Case C: Banned AI cliché
    cliche_script = good_length_script.replace("No theory currently explains what produced it.", "Only time will tell what happens next.")
    score_cliche = council.evaluate_script_quality(
        script_text=cliche_script,
        hook="A bizarre acoustic signal was recorded six miles deep.",
        event_card=ec,
        word_count=len(cliche_script.split())
    )
    assert score_cliche.verdict == "REWRITE"
    assert "Banned AI cliché detected" in score_cliche.critique


def test_council_quality_gate_passes_clean_script():
    """A clean, punchy 65-word mystery script passes the Council Quality Gate."""
    council = AICouncilEngine()
    ec = EventCard(
        event_id="ev_test_02",
        canonical_title="Strange deep-sea acoustic anomaly discovered in oceanic trench",
        what="Unexplained deep ocean sound anomaly recorded near trench",
        who=WhoSection(organizations=["Oceanographic Institute"], countries=["United States"]),
        first_seen_utc=datetime.now(timezone.utc),
        latest_seen_utc=datetime.now(timezone.utc),
        where=WhereSection(location_name="Mariana Trench", country="Pacific Ocean"),
        when=WhenSection(event_time_utc=datetime.now(timezone.utc)),
        verification_state="CORROBORATED_MULTI_SOURCE",
        confidence=0.95
    )

    clean_script = (
        "Something deep beneath the Pacific Ocean is baffling marine biologists. "
        "An autonomous robotic submersible recorded an intense metallic humming sound emerging from six miles below the surface. "
        "The acoustic frequency does not match any known sea creature, seismic fault, or submarine. "
        "When researchers dropped acoustic sensors into the trench, the strange signal suddenly answered back with rhythmic pulses. "
        "No theory currently explains what produced it."
    )
    words = len(clean_script.split())
    assert 62 <= words <= 70

    score = council.evaluate_script_quality(
        script_text=clean_script,
        hook="A metallic pulse from six miles underwater just answered scientists.",
        event_card=ec,
        word_count=words
    )
    assert score.verdict == "PASS"
    assert score.overall_score >= 7.5


def test_scheduler_48_hour_horizon_coverage():
    """Scheduler must inspect slots covering rolling 48-hour window while enforcing 3/day limit."""
    scheduler = PublicationScheduler()
    db_mock = MagicMock()

    # Reference time: 2026-09-05 16:00:00 UTC (All Day 0 slots in past)
    ref_time = datetime(2026, 9, 5, 16, 0, 0)

    # Empty schedule state: no occupied slots
    with patch.object(scheduler, "get_authoritative_schedule_state", return_value=(set(), {}, {})):
        vacant = scheduler.get_vacant_slots_in_horizon(db=db_mock, reference_time=ref_time, horizon_hours=48)
        
        # Day 1 (Sept 6): 06:00, 11:00, 15:00 UTC (3 slots)
        # Day 2 (Sept 7): 06:00, 11:00, 15:00 UTC (3 slots, since 15:00 is 47h ahead <= 48h)
        assert len(vacant) == 6, f"Expected 6 vacant slots across 48h forward horizon, got {len(vacant)}"
        
        for s in vacant:
            assert s > ref_time
            assert s <= ref_time + timedelta(hours=48)

    # Test with 2 occupied slots on Day 1: only 1 vacant slot on Day 1 + 3 on Day 2 = 4 total
    day1_date = datetime(2026, 9, 6).date()
    occupied = {datetime(2026, 9, 6, 6, 0), datetime(2026, 9, 6, 11, 0)}
    day_counts = {day1_date: 2}

    with patch.object(scheduler, "get_authoritative_schedule_state", return_value=(occupied, day_counts, {})):
        vacant = scheduler.get_vacant_slots_in_horizon(db=db_mock, reference_time=ref_time, horizon_hours=48)
        assert len(vacant) == 4
        assert datetime(2026, 9, 6, 15, 0) in vacant
        assert datetime(2026, 9, 6, 6, 0) not in vacant
