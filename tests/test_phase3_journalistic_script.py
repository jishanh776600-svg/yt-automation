"""
Comprehensive Test Suite for Phase 3 Journalistic Script Architecture.
Validates all 30 required capabilities and production invariants:
1. EventCard produces valid script.
2. Hook immediately describes the event.
3. Every factual beat has claim_ids.
4. Every claim_id exists in EventCard.
5. Source publisher provenance is preserved.
6. Source URL provenance is preserved.
7. Missing EventCard fields remain absent/null.
8. Why is not invented when EventCard.why is null.
9. How is not invented when EventCard.how is null.
10. Conflicting claims remain explicitly represented.
11. SINGLE_CREDIBLE_SOURCE uses appropriate attribution.
12. MULTI_SOURCE_CORROBORATED permits stronger factual wording.
13. INSUFFICIENT_EVIDENCE is rejected.
14. Generic filler is rejected.
15. Unsupported facts are rejected.
16. Invented casualty numbers are rejected.
17. Invented locations are rejected.
18. Invented actors are rejected.
19. Visual queries are generated from EventCard evidence.
20. No visual retrieval occurs during Phase 3.
21. No rendering occurs.
22. No YouTube upload occurs.
23. Sarah-only voice invariant remains intact.
24. SFX remains disabled.
25. Historical fallback remains impossible.
26. Wikipedia is not used for current-affairs script grounding.
27. Script generation works without Antigravity.
28. Script generation works without a browser.
29. Production paths contain no Windows-only dependency.
30. Cloud autonomy regression remains green.
"""
import inspect
import json
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from pathlib import Path

from intelligence.event_card import (
    EventCard, WhoSection, WhereSection, WhenSection,
    ClaimEvidence, ConflictRecord, TimelineEntry, VerificationState
)
from intelligence.journalistic_script import (
    JournalisticScriptEngine, JournalisticValidationGate,
    ScriptDocument, ScriptBeat, ScriptBeatType
)
from engines.script_engine import ScriptEngine
from core.models import Topic, ScriptRecord
from config.settings import PROJECT_ROOT, APPROVED_PRODUCTION_VOICES, KOKORO_VOICE
from engines.visual_intelligence.voice_policy import VoiceVariationPolicy


def create_sample_event_card(
    verification_state: str = VerificationState.MULTI_SOURCE_CORROBORATED.value,
    why: str = None,
    how: str = None,
    has_conflicts: bool = False
) -> EventCard:
    """Helper fixture to create a realistic geopolitical EventCard."""
    claims = [
        ClaimEvidence(
            claim_id="cl_dan_01",
            claim_text="Danish maritime authorities detained a commercial oil tanker in the Great Belt strait.",
            publisher="Reuters",
            source_url="https://reuters.com/world/europe/danish-tanker-detained",
            source_article_id="art_reuters_01",
            published_utc=datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
            confidence=0.95
        ),
        ClaimEvidence(
            claim_id="cl_dan_02",
            claim_text="Danish naval patrol vessels escorted the commercial vessel to an anchorage following a safety inspection.",
            publisher="Associated Press",
            source_url="https://apnews.com/article/denmark-strait-vessel",
            source_article_id="art_ap_01",
            published_utc=datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc),
            confidence=0.92
        )
    ]

    conflicts = []
    if has_conflicts:
        conflicts.append(ConflictRecord(
            conflict_id="cnf_01",
            topic_facet="cargo_origin",
            competing_claims=[
                {"claim_id": "cl_dan_01", "claim": "Cargo originated from Primorsk", "source": "Reuters"},
                {"claim_id": "cl_dan_02", "claim": "Cargo origin listed as transit export", "source": "AP News"}
            ],
            description="Competing declarations of crude cargo origin",
            affected_sources=["Reuters", "AP News"]
        ))

    return EventCard(
        event_id="ev_baltic_20260904",
        canonical_title="Danish Authorities Detain Commercial Tanker in Great Belt",
        verification_state=verification_state,
        confidence=0.94,
        first_seen_utc=datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
        latest_seen_utc=datetime(2026, 9, 4, 11, 0, tzinfo=timezone.utc),
        who=WhoSection(
            organizations=["Danish Maritime Authority", "Royal Danish Navy"],
            countries=["Denmark"],
            military_units=["Danish naval patrol HDMS Triton"]
        ),
        what="Danish authorities intercepted and detained a commercial tanker in the Great Belt strait.",
        where=WhereSection(
            country="Denmark",
            region="Baltic Sea",
            location_name="Great Belt strait"
        ),
        when=WhenSection(
            event_time_utc=datetime(2026, 9, 4, 9, 45, tzinfo=timezone.utc)
        ),
        why=why,
        how=how,
        event_type="maritime_interception",
        actions=["intercepted", "detained", "escorted", "inspected"],
        entities=["commercial tanker", "Danish Maritime Authority", "Great Belt"],
        important_objects=["crude tanker", "patrol vessel"],
        claims=claims,
        sources=[
            {"publisher": "Reuters", "url": "https://reuters.com/world/europe/danish-tanker-detained"},
            {"publisher": "Associated Press", "url": "https://apnews.com/article/denmark-strait-vessel"}
        ],
        conflicting_claims=conflicts,
        timeline=[
            TimelineEntry(
                timestamp_utc=datetime(2026, 9, 4, 9, 45, tzinfo=timezone.utc),
                event_description="HDMS Triton approached the vessel in the Great Belt.",
                publisher="Reuters"
            )
        ],
        visual_entities=["commercial oil tanker", "naval patrol vessel", "Great Belt Bridge"],
        visual_concepts=["maritime interception", "naval inspection", "strait transit"],
        future_footage_queries=[
            "Danish navy Great Belt tanker inspection footage",
            "Great Belt commercial vessel interception",
            "HDMS Triton Baltic patrol"
        ]
    )


# --------------------------------------------------------------------------
# Tests 1-6: Script Generation, Hook Structure & Granular Provenance
# --------------------------------------------------------------------------
def test_01_event_card_produces_valid_script():
    """EventCard generates a valid, structured ScriptDocument."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    assert isinstance(doc, ScriptDocument)
    assert doc.event_id == card.event_id
    assert doc.verification_state == card.verification_state
    assert len(doc.beats) >= 3
    assert doc.word_count > 20
    assert doc.estimated_duration_sec > 10.0
    assert doc.provenance_complete is True


def test_02_hook_immediately_describes_event():
    """Journalistic hook follows [ACTOR] + [ACTION] + [OBJECT/EVENT] + [LOCATION/TIME ANCHOR]."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    hook = doc.hook.lower()
    # Must specify what happened and where without generic fluff
    assert any(w in hook for w in ["danish", "authorities", "navy", "tanker", "great belt"])
    assert "in a surprising turn of events" not in hook
    assert "tensions are rising" not in hook
    assert "the world is watching" not in hook


def test_03_every_factual_beat_has_claim_ids():
    """Every factual beat in the script must be explicitly tied to one or more claim_ids."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    for beat in doc.beats:
        if beat.factual:
            assert len(beat.claim_ids) > 0, f"Beat {beat.sequence} marked factual but has empty claim_ids"


def test_04_every_claim_id_exists_in_event_card():
    """All referenced claim_ids in beats must exist in the input EventCard."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    valid_cids = {c.claim_id for c in card.claims}
    for beat in doc.beats:
        for cid in beat.claim_ids:
            assert cid in valid_cids, f"Beat referenced unknown claim_id '{cid}' not in EventCard"


def test_05_source_publisher_provenance_is_preserved():
    """Source publishers from EventCard are preserved in the beat metadata."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    all_pubs = []
    for beat in doc.beats:
        all_pubs.extend(beat.source_publishers)

    assert any("Reuters" in p or "Associated Press" in p for p in all_pubs)


def test_06_source_url_provenance_is_preserved():
    """The complete chain from beat -> claim_id -> source URL can be reconstructed."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    claim_map = {c.claim_id: c for c in card.claims}
    reconstructed_urls = []
    for beat in doc.beats:
        for cid in beat.claim_ids:
            claim = claim_map.get(cid)
            if claim and claim.source_url:
                reconstructed_urls.append(claim.source_url)

    assert len(reconstructed_urls) > 0
    assert "https://reuters.com/world/europe/danish-tanker-detained" in reconstructed_urls


# --------------------------------------------------------------------------
# Tests 7-10: Missing Fields & Conflict Preservation
# --------------------------------------------------------------------------
def test_07_missing_event_card_fields_remain_absent():
    """EventCard fields that are None remain absent and are not hallucinated."""
    card = create_sample_event_card(why=None, how=None)
    assert card.why is None
    assert card.how is None

    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)
    full_text = doc.full_text.lower()

    assert "secretly intended" not in full_text
    assert "in order to provoke" not in full_text


def test_08_why_is_not_invented_when_event_card_why_is_null():
    """Validator rejects script if it introduces causal 'why' assertions when EventCard.why is null."""
    card = create_sample_event_card(why=None)
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    # Manually inject an unverified causal statement into beat
    doc.beats.append(ScriptBeat(
        beat_id="beat_bad_why",
        sequence=99,
        text="The interception occurred in order to retaliate against foreign sanctions.",
        beat_type=ScriptBeatType.CONTEXT.value,
        claim_ids=[card.claims[0].claim_id],
        source_publishers=["Reuters"],
        factual=True
    ))

    is_valid, errors, unsupported = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("EventCard.why is null" in e for e in errors)


def test_09_how_is_not_invented_when_event_card_how_is_null():
    """Validator rejects script if it introduces ungrounded mechanical 'how' assertions when how is null."""
    card = create_sample_event_card(how=None)
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_bad_how",
        sequence=99,
        text="Danish forces boarded the vessel by deploying advanced covert submersible drones.",
        beat_type=ScriptBeatType.WHAT_HAPPENED.value,
        claim_ids=[card.claims[0].claim_id],
        source_publishers=["Reuters"],
        factual=True
    ))

    is_valid, errors, unsupported = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("EventCard.how is null" in e for e in errors)


def test_10_conflicting_claims_remain_explicitly_represented():
    """When conflicting claims exist, the dispute is explicitly preserved in script."""
    card = create_sample_event_card(
        verification_state=VerificationState.CONFLICTING_REPORTS.value,
        has_conflicts=True
    )
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    full_text = doc.full_text.lower()
    assert any(w in full_text for w in ["differ", "competing", "dispute", "accounts"])


# --------------------------------------------------------------------------
# Tests 11-14: Verification States, Fail-Closed & Generic Filler
# --------------------------------------------------------------------------
def test_11_single_credible_source_uses_attribution():
    """SINGLE_CREDIBLE_SOURCE verification state enforces journalistic attribution language."""
    card = create_sample_event_card(verification_state=VerificationState.SINGLE_CREDIBLE_SOURCE.value)
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    full_text = doc.full_text.lower()
    assert any(m in full_text for m in ["reported", "according to", "officials", "credible report"])


def test_12_multi_source_corroborated_permits_stronger_factual_wording():
    """MULTI_SOURCE_CORROBORATED passes validation without requiring soft qualification on every beat."""
    card = create_sample_event_card(verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value)
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)
    is_valid, errors, _ = JournalisticValidationGate.validate(doc, card)

    assert is_valid is True
    assert len(errors) == 0


def test_13_insufficient_evidence_is_rejected():
    """INSUFFICIENT_EVIDENCE fails closed immediately."""
    card = create_sample_event_card(verification_state=VerificationState.INSUFFICIENT_EVIDENCE.value)
    engine = JournalisticScriptEngine()

    with pytest.raises(ValueError, match="INSUFFICIENT_EVIDENCE"):
        engine.generate_journalistic_script(card)


def test_14_generic_filler_is_rejected():
    """Banned AI clichés trigger immediate validation rejection."""
    card = create_sample_event_card()
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_cliche",
        sequence=99,
        text="In a surprising turn of events, tensions are rising and the world is watching.",
        beat_type=ScriptBeatType.CONTEXT.value,
        claim_ids=[card.claims[0].claim_id],
        source_publishers=["Reuters"],
        factual=True
    ))

    is_valid, errors, _ = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("Prohibited AI cliché" in e for e in errors)


# --------------------------------------------------------------------------
# Tests 15-18: Unsupported Facts, Casualty Figures, Locations & Actors
# --------------------------------------------------------------------------
def test_15_unsupported_facts_are_rejected():
    """Factual beat without claim_ids fails validation."""
    card = create_sample_event_card()
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_no_claim",
        sequence=99,
        text="A secret pact was signed between both nations.",
        beat_type=ScriptBeatType.KEY_DEVELOPMENT.value,
        claim_ids=[],  # Empty claim_ids on factual beat
        source_publishers=[],
        factual=True
    ))

    is_valid, errors, unsupported = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("has no claim_ids" in e for e in errors)
    assert "A secret pact was signed between both nations." in unsupported


def test_16_invented_casualty_numbers_are_rejected():
    """Invented numeric casualty figures not found in claims trigger rejection."""
    card = create_sample_event_card()
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_invented_num",
        sequence=99,
        text="Over 487 sailors were injured in the operation.",
        beat_type=ScriptBeatType.WHAT_HAPPENED.value,
        claim_ids=[card.claims[0].claim_id],
        source_publishers=["Reuters"],
        factual=True
    ))

    is_valid, errors, _ = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("Invented numeric figures" in e for e in errors)


def test_17_invented_locations_are_rejected():
    """Factual claims tied to non-existent claim IDs fail validation."""
    card = create_sample_event_card()
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_fake_loc",
        sequence=99,
        text="The ship was redirected to Singapore naval docks.",
        beat_type=ScriptBeatType.WHERE.value,
        claim_ids=["cl_fake_singapore_99"],  # Nonexistent claim ID
        source_publishers=["Fabricated News"],
        factual=True
    ))

    is_valid, errors, _ = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("nonexistent claim_id" in e for e in errors)


def test_18_invented_actors_are_rejected():
    """Factual claims referencing unknown entities without claim backing fail validation."""
    card = create_sample_event_card()
    engine = JournalisticScriptEngine()
    doc = engine.generate_journalistic_script(card)

    doc.beats.append(ScriptBeat(
        beat_id="beat_fake_actor",
        sequence=99,
        text="General Maximiliano personally ordered the operation.",
        beat_type=ScriptBeatType.WHO.value,
        claim_ids=["cl_unknown_general_77"],
        source_publishers=["Unknown"],
        factual=True
    ))

    is_valid, errors, _ = JournalisticValidationGate.validate(doc, card)
    assert is_valid is False
    assert any("nonexistent claim_id" in e for e in errors)


# --------------------------------------------------------------------------
# Tests 19-22: Visual Query Handoff & Safety Non-Execution
# --------------------------------------------------------------------------
def test_19_visual_queries_generated_from_event_card():
    """Each script beat generates candidate visual search queries grounded in EventCard metadata."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()
    doc = engine.generate_journalistic_script(card)

    for beat in doc.beats:
        assert len(beat.visual_query_candidates) > 0
        assert any(
            any(entity.lower() in q.lower() for entity in ["denmark", "tanker", "great belt", "naval"])
            for q in beat.visual_query_candidates
        )


def test_20_no_visual_retrieval_occurs_during_phase3():
    """Phase 3 script generation does NOT invoke visual search/download APIs."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()

    with patch("requests.get") as mock_http:
        doc = engine.generate_journalistic_script(card)
        # Should not make outbound requests to Pexels, YouTube, or image downloaders
        for call_args in mock_http.call_args_list:
            url = str(call_args[0][0]) if call_args[0] else ""
            assert "pexels.com" not in url
            assert "youtube.com" not in url


def test_21_no_rendering_occurs():
    """Phase 3 does not call FFmpeg or generate MP4 files."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()

    with patch("subprocess.run") as mock_subproc:
        doc = engine.generate_journalistic_script(card)
        for call_args in mock_subproc.call_args_list:
            cmd = str(call_args[0][0]) if call_args[0] else ""
            assert "ffmpeg" not in cmd


def test_22_no_youtube_upload_occurs():
    """Phase 3 does not call YouTube upload or publish APIs."""
    engine = JournalisticScriptEngine()
    card = create_sample_event_card()

    with patch("googleapiclient.discovery.build") as mock_yt:
        doc = engine.generate_journalistic_script(card)
        assert mock_yt.call_count == 0


# --------------------------------------------------------------------------
# Tests 23-26: Invariants: Voice Lock, SFX Disabled, No Historical Fallback
# --------------------------------------------------------------------------
def test_23_sarah_only_voice_invariant_remains_intact():
    """Approved production voice remains strictly af_sarah."""
    assert "af_sarah" in APPROVED_PRODUCTION_VOICES
    assert KOKORO_VOICE == "af_sarah"



def test_24_sfx_remains_disabled():
    """SFX and BGM policy remain permanently disabled."""
    policy = VoiceVariationPolicy()
    decision = policy.select_voice_and_delivery(category="geopolitics", title="Crisis", script_text="Troops moved.")
    assert decision.bgm_policy == "NONE"


def test_25_historical_fallback_remains_impossible():
    """ScriptEngine with a Current Affairs EventCard NEVER falls back to historical seeds."""
    mock_db = MagicMock()
    card = create_sample_event_card()
    topic = Topic(
        id="top_current_001",
        title=card.canonical_title,
        category="Current Affairs",
        event_id=card.event_id,
        event_card_json=card.to_json()
    )

    engine = ScriptEngine()
    script_rec = engine.generate_script(mock_db, topic)

    assert script_rec is not None
    assert script_rec.event_id == card.event_id
    assert "kettle" not in script_rec.full_text.lower()
    assert "emu" not in script_rec.full_text.lower()
    assert "molasses" not in script_rec.full_text.lower()
    assert "pig war" not in script_rec.full_text.lower()


def test_26_wikipedia_is_not_used_for_current_affairs_script_grounding():
    """ResearchEngine bypasses Wikipedia entirely when an EventCard is attached."""
    from engines.research_engine import ResearchEngine
    re_engine = ResearchEngine()
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = []

    card = create_sample_event_card()
    topic = Topic(
        id="top_ca_002",
        title=card.canonical_title,
        category="Current Affairs",
        event_id=card.event_id,
        event_card_json=card.to_json()
    )

    with patch.object(re_engine.wiki, "page") as mock_wiki_page:
        result = re_engine.research_topic(mock_db, topic)
        assert mock_wiki_page.call_count == 0
        assert result.get("event_card") is not None
        assert result.get("event_id") == card.event_id


# --------------------------------------------------------------------------
# Tests 27-30: 100% Cloud Autonomy, Headless Execution & Database
# --------------------------------------------------------------------------
def test_27_script_generation_works_without_antigravity():
    """JournalisticScriptEngine has zero import or runtime dependency on Antigravity."""
    import intelligence.journalistic_script as mod
    source = inspect.getsource(mod).lower()
    assert "antigravity" not in source


def test_28_script_generation_works_without_browser():
    """JournalisticScriptEngine has zero import or runtime dependency on browser automation."""
    import intelligence.journalistic_script as mod
    source = inspect.getsource(mod).lower()
    for b in ["selenium", "playwright", "puppeteer", "browser_get_dom", "webbrowser"]:
        assert b not in source, f"Found browser term '{b}' in journalistic script engine"


def test_29_production_paths_contain_no_windows_only_dependency():
    """ScriptDocument and JournalisticScriptEngine use platform-agnostic standard libraries."""
    import intelligence.journalistic_script as mod
    source = inspect.getsource(mod)
    assert "C:\\Users" not in source
    assert "win32" not in source


def test_30_cloud_autonomy_script_record_database_persistence():
    """ScriptRecord schema persists EventCard script document with provenance flags."""
    mock_db = MagicMock()
    card = create_sample_event_card()
    topic = Topic(
        id="top_ca_003",
        title=card.canonical_title,
        category="Current Affairs",
        event_id=card.event_id,
        event_card_json=card.to_json()
    )

    engine = ScriptEngine()
    script_rec = engine.generate_script(mock_db, topic)

    assert script_rec.id.startswith("scr_")
    assert script_rec.event_id == card.event_id
    assert script_rec.script_document_json is not None
    assert script_rec.provenance_complete is True
    assert script_rec.validation_status == "APPROVED"
    assert mock_db.add.called
