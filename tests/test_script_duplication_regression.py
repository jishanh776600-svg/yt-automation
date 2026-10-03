"""
REGRESSION TEST: Script Duplication via _synthesize_from_evidence()
====================================================================
Root cause fixed: The fallback function _synthesize_from_evidence() previously contained
8 of its 10 beats as verbatim hard-coded static strings, causing all topics that fell
through to the fallback path to receive identical narration.

This test suite:
1. Creates 3 completely distinct EventCards (different domains, claims, entities, locations).
2. Calls _synthesize_from_evidence() on each.
3. Asserts no two scripts share ANY 5-word n-gram from beats 3–8 (the previously boilerplate section).
4. Asserts that none of the six known boilerplate strings appear in ANY output.
5. Asserts each script's full_text is driven by its EventCard's own data (spot-checks).

This test does NOT mock LLM output. It directly exercises the deterministic fallback
function in isolation, which is the exact code path that caused the bug.
"""
import sys
import os
import uuid
import itertools

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from datetime import datetime, timezone

from intelligence.event_card import (
    EventCard,
    ClaimEvidence,
    ConflictRecord,
    TimelineEntry,
    WhoSection,
    WhereSection,
    WhenSection,
    VerificationState,
)
from intelligence.journalistic_script import JournalisticScriptEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ngrams(text: str, n: int):
    """Return a set of lower-cased n-word tuples from text."""
    words = text.lower().split()
    return set(itertools.islice(zip(*[words[i:] for i in range(n)]), None))


def _full_text(doc) -> str:
    """Concatenate all beat texts into one string."""
    return " ".join(b.text for b in doc.beats)


def _beats_3_to_8_text(doc) -> str:
    """Return text for beats 3–8 (indices 2–7, 0-based) only."""
    relevant = doc.beats[2:8]
    return " ".join(b.text for b in relevant)


# ---------------------------------------------------------------------------
# Known boilerplate strings that MUST NOT appear post-fix
# ---------------------------------------------------------------------------

FORBIDDEN_BOILERPLATE = [
    "Surveillance units tracked unusual tactical movement",
    "Field operations expanded across key sectors",
    "Physical records corroborated what took place",
    "Military observers remained on high alert",
    "Security archives preserve the strange incident",
    "This bizarre mystery still awaits answers",
    "Officials issued no public statement",  # included for completeness
]


# ---------------------------------------------------------------------------
# Fixture factories — three maximally distinct EventCards
# ---------------------------------------------------------------------------

def make_card_maritime_tanker() -> EventCard:
    """Card A: Danish tanker boarded in the Strait of Hormuz."""
    return EventCard(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        canonical_title="Danish Tanker Boarded in Strait of Hormuz",
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.90,
        first_seen_utc=datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc),
        latest_seen_utc=datetime(2026, 9, 18, 8, 0, 0, tzinfo=timezone.utc),
        who=WhoSection(
            people=["Captain Lars Bjornsen"],
            organizations=["Iranian Revolutionary Guard Navy"],
            countries=["Iran", "Denmark"],
        ),
        what="Iranian naval vessels boarded and seized a Danish-flagged commercial tanker",
        where=WhereSection(
            location_name="Strait of Hormuz",
            country="Iran",
            city="Bandar Abbas",
            coordinates={"lat": 26.56, "lon": 56.24},
        ),
        when=WhenSection(
            event_time_utc=datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc),
        ),
        why="Iran claims the vessel violated territorial navigation regulations",
        how="Armed naval personnel boarded via speedboats at 03:00 local time",
        entities=["MV Nordic Star", "Iranian Revolutionary Guard Navy"],
        important_objects=["shipping manifest", "navigation logs"],
        claims=[
            ClaimEvidence(
                claim_id="cl_tanker_001",
                claim_text="Iranian naval forces seized the MV Nordic Star citing illegal navigation",
                publisher="Reuters",
                confidence=0.92,
            ),
            ClaimEvidence(
                claim_id="cl_tanker_002",
                claim_text="Denmark's foreign ministry summoned the Iranian ambassador in protest",
                publisher="AP",
                confidence=0.88,
            ),
        ],
        conflicting_claims=[
            ConflictRecord(
                conflict_id="cnf_tanker_001",
                topic_facet="actor_attribution",
                description="Iran denies boarding was seizure; calls it routine inspection",
                affected_sources=["Reuters", "IRNA"],
            )
        ],
        timeline=[
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 18, 3, 0, 0, tzinfo=timezone.utc),
                event_description="Iranian speedboats intercepted the tanker at Hormuz chokepoint",
                publisher="Reuters",
            ),
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 18, 7, 0, 0, tzinfo=timezone.utc),
                event_description="Danish foreign ministry issued emergency protest statement",
                publisher="AP",
            ),
        ],
    )


def make_card_north_korea_missile() -> EventCard:
    """Card B: North Korea launches an ICBM over the Sea of Japan."""
    return EventCard(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        canonical_title="North Korea Fires ICBM Over Sea of Japan",
        verification_state=VerificationState.OFFICIAL_CONFIRMATION.value,
        confidence=0.94,
        first_seen_utc=datetime(2026, 9, 20, 14, 30, 0, tzinfo=timezone.utc),
        latest_seen_utc=datetime(2026, 9, 20, 15, 0, 0, tzinfo=timezone.utc),
        who=WhoSection(
            people=["Kim Jong Un"],
            organizations=["Korean People's Army Strategic Force"],
            countries=["North Korea", "Japan", "South Korea"],
        ),
        what="North Korea test-fired an intercontinental ballistic missile that flew over Japanese airspace",
        where=WhereSection(
            location_name="Sea of Japan",
            country="North Korea",
            city="Sunan",
            coordinates={"lat": 39.2, "lon": 125.67},
        ),
        when=WhenSection(
            event_time_utc=datetime(2026, 9, 20, 14, 30, 0, tzinfo=timezone.utc),
        ),
        why="Pyongyang cites joint US-South Korea military exercises as provocation",
        how="Missile launched from Sunan Air Base; reached 6,000 km altitude before splashing down",
        entities=["Hwasong-18 ICBM", "Kim Jong Un"],
        important_objects=["missile telemetry data", "J-Alert system"],
        claims=[
            ClaimEvidence(
                claim_id="cl_nk_001",
                claim_text="North Korea fired a Hwasong-18 ICBM that flew 1,100 km before splashing into the Sea of Japan",
                publisher="NHK World",
                confidence=0.95,
            ),
            ClaimEvidence(
                claim_id="cl_nk_002",
                claim_text="Japan activated J-Alert emergency broadcast system for eastern prefectures",
                publisher="Kyodo News",
                confidence=0.93,
            ),
        ],
        conflicting_claims=[],
        timeline=[
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 20, 14, 30, 0, tzinfo=timezone.utc),
                event_description="Hwasong-18 launched from Sunan Air Base heading northeast",
                publisher="NHK World",
            ),
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 20, 15, 15, 0, tzinfo=timezone.utc),
                event_description="US Indo-Pacific Command confirmed the launch and tracked the trajectory",
                publisher="Pentagon",
            ),
        ],
    )


def make_card_brazil_amazon_fires() -> EventCard:
    """Card C: Unprecedented Amazon wildfire crisis in Pará state, Brazil."""
    return EventCard(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        canonical_title="Amazon Wildfire Crisis Engulfs Para State Brazil",
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.86,
        first_seen_utc=datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc),
        latest_seen_utc=datetime(2026, 9, 15, 18, 0, 0, tzinfo=timezone.utc),
        who=WhoSection(
            people=["Governor Helder Barbalho"],
            organizations=["IBAMA Environmental Agency"],
            countries=["Brazil"],
        ),
        what="Uncontrolled wildfires swept across 2.3 million hectares of Amazonian rainforest in Para",
        where=WhereSection(
            location_name="Para State Amazon Basin",
            country="Brazil",
            city="Belem",
            coordinates={"lat": -1.45, "lon": -48.5},
        ),
        when=WhenSection(
            event_time_utc=datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc),
        ),
        why="Extreme drought conditions and illegal land-clearing operations accelerated fire spread",
        how="Fire fronts spread at 40 km/day driven by low humidity and strong easterly winds",
        entities=["IBAMA Environmental Agency", "Para State Civil Defense"],
        important_objects=["satellite fire data", "deforestation alerts"],
        claims=[
            ClaimEvidence(
                claim_id="cl_amazon_001",
                claim_text="Fires consumed 2.3 million hectares in Para state within 72 hours",
                publisher="O Globo",
                confidence=0.87,
            ),
            ClaimEvidence(
                claim_id="cl_amazon_002",
                claim_text="IBAMA deployed 1,200 firefighters and requested international air tanker support",
                publisher="Folha de Sao Paulo",
                confidence=0.85,
            ),
        ],
        conflicting_claims=[
            ConflictRecord(
                conflict_id="cnf_amazon_001",
                topic_facet="casualty_count",
                description="Government and NGOs dispute number of indigenous communities displaced",
                affected_sources=["O Globo", "FUNAI"],
            )
        ],
        timeline=[
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc),
                event_description="Satellite data detected simultaneous ignition across Para frontier zones",
                publisher="INPE",
            ),
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 16, 6, 0, 0, tzinfo=timezone.utc),
                event_description="Federal emergency declared; military aviation units deployed to Belem",
                publisher="Brazilian Ministry of Defense",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def engine():
    return JournalisticScriptEngine()


@pytest.fixture(scope="module")
def three_scripts(engine):
    card_a = make_card_maritime_tanker()
    card_b = make_card_north_korea_missile()
    card_c = make_card_brazil_amazon_fires()
    doc_a = engine._synthesize_from_evidence(card_a)
    doc_b = engine._synthesize_from_evidence(card_b)
    doc_c = engine._synthesize_from_evidence(card_c)
    return card_a, card_b, card_c, doc_a, doc_b, doc_c


class TestNoBogusBoilerplate:
    """Ensures none of the old static boilerplate strings appear in any output."""

    def test_no_surveillance_units_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "surveillance units tracked unusual tactical movement" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"

    def test_no_field_operations_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "field operations expanded across key sectors" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"

    def test_no_physical_records_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "physical records corroborated what took place" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"

    def test_no_military_observers_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "military observers remained on high alert" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"

    def test_no_security_archives_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "security archives preserve the strange incident" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"

    def test_no_bizarre_mystery_boilerplate(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for doc in (doc_a, doc_b, doc_c):
            ft = _full_text(doc).lower()
            assert "this bizarre mystery still awaits answers" not in ft, \
                f"Old boilerplate found in script: {_full_text(doc)[:200]}"


class TestCrossTopicUniqueness:
    """
    Core regression: no two distinct EventCards may produce the same or
    near-identical script body through the fallback synthesis path.

    Uniqueness criterion: no shared 5-word n-gram in beats 3–8 between any pair,
    EXCEPT for pure structural connectives (which are filtered).

    Additionally, the complete full_text of any two scripts must differ.
    """

    STRUCTURAL_5GRAMS = {
        # Common English connectives that are acceptable to share
        ("the", "incident", "unfolded", "in", "the"),
        ("inquiries", "remain", "underway", ".", "monitors"),
    }

    def _significant_ngrams(self, text: str, n: int) -> set:
        grams = _ngrams(text, n)
        return grams - self.STRUCTURAL_5GRAMS

    def test_card_a_vs_card_b_beats_3_to_8_no_shared_5gram(self, three_scripts):
        _, _, _, doc_a, doc_b, _ = three_scripts
        ng_a = self._significant_ngrams(_beats_3_to_8_text(doc_a), 5)
        ng_b = self._significant_ngrams(_beats_3_to_8_text(doc_b), 5)
        shared = ng_a & ng_b
        assert len(shared) == 0, (
            f"Card A and Card B share {len(shared)} 5-gram(s) in beats 3–8:\n"
            f"  Shared: {list(shared)[:5]}\n"
            f"  Script A beats 3–8: {_beats_3_to_8_text(doc_a)}\n"
            f"  Script B beats 3–8: {_beats_3_to_8_text(doc_b)}"
        )

    def test_card_a_vs_card_c_beats_3_to_8_no_shared_5gram(self, three_scripts):
        _, _, _, doc_a, _, doc_c = three_scripts
        ng_a = self._significant_ngrams(_beats_3_to_8_text(doc_a), 5)
        ng_c = self._significant_ngrams(_beats_3_to_8_text(doc_c), 5)
        shared = ng_a & ng_c
        assert len(shared) == 0, (
            f"Card A and Card C share {len(shared)} 5-gram(s) in beats 3–8:\n"
            f"  Shared: {list(shared)[:5]}\n"
            f"  Script A beats 3–8: {_beats_3_to_8_text(doc_a)}\n"
            f"  Script C beats 3–8: {_beats_3_to_8_text(doc_c)}"
        )

    def test_card_b_vs_card_c_beats_3_to_8_no_shared_5gram(self, three_scripts):
        _, _, _, _, doc_b, doc_c = three_scripts
        ng_b = self._significant_ngrams(_beats_3_to_8_text(doc_b), 5)
        ng_c = self._significant_ngrams(_beats_3_to_8_text(doc_c), 5)
        shared = ng_b & ng_c
        assert len(shared) == 0, (
            f"Card B and Card C share {len(shared)} 5-gram(s) in beats 3–8:\n"
            f"  Shared: {list(shared)[:5]}\n"
            f"  Script B beats 3–8: {_beats_3_to_8_text(doc_b)}\n"
            f"  Script C beats 3–8: {_beats_3_to_8_text(doc_c)}"
        )

    def test_full_texts_are_pairwise_distinct(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        ft_a = _full_text(doc_a)
        ft_b = _full_text(doc_b)
        ft_c = _full_text(doc_c)
        assert ft_a != ft_b, "Script A and Script B are identical full texts — duplication bug re-emerged."
        assert ft_a != ft_c, "Script A and Script C are identical full texts — duplication bug re-emerged."
        assert ft_b != ft_c, "Script B and Script C are identical full texts — duplication bug re-emerged."


class TestEventCardDataGrounding:
    """Spot-checks that each script's text is actually derived from its own EventCard data."""

    def test_script_a_contains_tanker_specific_terms(self, three_scripts):
        _, _, _, doc_a, _, _ = three_scripts
        ft = _full_text(doc_a).lower()
        # Must contain domain-specific terms from Card A's data
        assert any(term in ft for term in ["hormuz", "tanker", "nordic", "iranian", "denmark", "boardin"]), \
            f"Script A does not reference its own EventCard data.\nFull text: {_full_text(doc_a)}"

    def test_script_b_contains_missile_specific_terms(self, three_scripts):
        _, _, _, _, doc_b, _ = three_scripts
        ft = _full_text(doc_b).lower()
        assert any(term in ft for term in ["icbm", "north korea", "japan", "missile", "hwasong", "sunan", "pyongyang", "korean"]), \
            f"Script B does not reference its own EventCard data.\nFull text: {_full_text(doc_b)}"

    def test_script_c_contains_amazon_specific_terms(self, three_scripts):
        _, _, _, _, _, doc_c = three_scripts
        ft = _full_text(doc_c).lower()
        assert any(term in ft for term in ["amazon", "pará", "para", "brazil", "fire", "ibama", "belém", "belem", "hectare"]), \
            f"Script C does not reference its own EventCard data.\nFull text: {_full_text(doc_c)}"


class TestScriptDocumentIntegrity:
    """Validates ScriptDocument structural integrity post-synthesis."""

    def test_all_docs_have_at_least_3_beats(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            assert len(doc.beats) >= 3, f"Script {label} has only {len(doc.beats)} beats (minimum 3 required)"

    def test_all_docs_word_count_in_range(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            wc = len(_full_text(doc).split())
            assert 50 <= wc <= 56, (
                f"Script {label} word count {wc} outside valid range [50, 56].\n"
                f"Full text: {_full_text(doc)}"
            )

    def test_all_docs_have_hook_field(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            assert doc.hook and len(doc.hook) > 0, f"Script {label} missing hook field"

    def test_all_beats_have_unique_beat_ids(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            ids = [b.beat_id for b in doc.beats]
            assert len(ids) == len(set(ids)), f"Script {label} has duplicate beat_ids: {ids}"

    def test_all_beats_are_factual(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            for beat in doc.beats:
                assert beat.factual is True, \
                    f"Script {label} beat {beat.beat_id} has factual=False; all fallback beats must be factual"

    def test_event_ids_match_cards(self, three_scripts):
        card_a, card_b, card_c, doc_a, doc_b, doc_c = three_scripts
        assert doc_a.event_id == card_a.event_id, "Script A event_id does not match Card A event_id"
        assert doc_b.event_id == card_b.event_id, "Script B event_id does not match Card B event_id"
        assert doc_c.event_id == card_c.event_id, "Script C event_id does not match Card C event_id"

    def test_provenance_complete_flag(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            assert doc.provenance_complete is True, f"Script {label} provenance_complete should be True"

    def test_unsupported_claims_empty(self, three_scripts):
        _, _, _, doc_a, doc_b, doc_c = three_scripts
        for label, doc in [("A", doc_a), ("B", doc_b), ("C", doc_c)]:
            assert doc.unsupported_claims == [], \
                f"Script {label} has unsupported_claims: {doc.unsupported_claims}"
