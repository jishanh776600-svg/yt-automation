"""
Test suite for Step 2D: Niche-Agnostic Discovery Bridge & Safety Fixes.
Verifies all 4 blockers (BLK-01, BLK-02, BLK-03, BLK-04) are fully resolved:
  - BLK-01: Niche-aware deduplication routing (Historical vs Current Affairs).
  - BLK-01: Two distinct 2026/London events are NOT falsely rejected.
  - BLK-01: Genuine duplicate current affairs events ARE rejected.
  - BLK-01: Historical duplicate detection remains strictly intact.
  - BLK-02: ResearchEngine prioritizes pre-attached SourceRecords and bypasses Wikipedia.
  - BLK-02: ResearchEngine falls back to Wikipedia for topics without pre-attached sources.
  - BLK-04: FreshnessScorer future timestamp defense (clock skew clamp vs penalty).
  - BLK-03: Synthetic DiscoveryProfile proves generic discovery extensibility without code modifications.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, SourceRecord, ClaimRecord
from core.content_profile import CURRENT_AFFAIRS_PROFILE, HISTORICAL_PROFILE, set_active_profile
from core.discovery_profile import (
    DiscoveryProfile,
    CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    HISTORICAL_DISCOVERY_PROFILE,
    set_active_discovery_profile,
    get_active_discovery_profile
)
from engines.deduplication_engine import DeduplicationRouter, StoryDeduplicationEngine
from engines.topic_discovery import TopicDiscoveryEngine
from engines.research_engine import ResearchEngine
from intelligence.freshness import FreshnessScorer
from intelligence.normalization import extract_entities_and_tokens, normalize_article
from intelligence.clustering import EventClusterEngine, are_articles_same_event
from intelligence.relevance import RelevanceScorer
from intelligence.scoring import OpportunityScorer
from intelligence.models import RawArticle, EventCluster
from intelligence.deduplication import CurrentAffairsDeduplicationEngine
from config.constants import CurrentAffairsCategory


@pytest.fixture
def db_session():
    """Provides an isolated in-memory SQLite DB session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ==============================================================================
# BLK-01: Niche-Aware Deduplication Routing
# ==============================================================================

def test_deduplication_router_policy_dispatch():
    """Test 1: Router correctly dispatches based on profile and explicit policy."""
    router = DeduplicationRouter()

    # 1. Historical explicit
    assert router.resolve_policy(explicit_policy="historical_year_location") == "historical_year_location"

    # 2. Current Affairs explicit
    assert router.resolve_policy(explicit_policy="event_action_domain") == "event_action_domain"

    # 3. By Category
    assert router.resolve_policy(category=CurrentAffairsCategory.GLOBAL_CONFLICT.value) == "event_action_domain"
    assert router.resolve_policy(category="DIPLOMACY") == "event_action_domain"
    assert router.resolve_policy(category="BIZARRE_HISTORY") == "historical_year_location"


def test_distinct_2026_london_events_not_rejected(db_session):
    """
    Test 2: Two distinct 2026 London events (e.g. Airport Strike vs Stock Exchange Cyberattack)
    must NOT collide or be falsely rejected under Current Affairs deduplication.
    """
    # Pre-populate DB with existing 2026 London event
    existing_topic = Topic(
        id="top_existing_01",
        title="Heathrow Airport Workers Launch Indefinite Strike in London",
        summary="Hundreds of ground crew at Heathrow Airport in London stage an indefinite strike over wage disputes in 2026.",
        category="WORLD_POLITICS",
        status="APPROVED"
    )
    db_session.add(existing_topic)
    db_session.commit()

    # Candidate 2026 London event in a different domain (Cyberattack / Defense / Economy)
    candidate_title = "London Stock Exchange Suffers Major Foreign Cyberattack"
    candidate_summary = "Financial infrastructure in London comes under unprecedented cyberattack halting trading in 2026."

    router = DeduplicationRouter(policy="event_action_domain")
    result = router.evaluate_candidate(
        candidate_title=candidate_title,
        candidate_summary=candidate_summary,
        db=db_session,
        category="SECURITY"
    )

    # Must be allowed!
    assert result.is_allowed is True
    assert result.is_duplicate is False

    # Also verify via TopicDiscoveryEngine.is_duplicate()
    disc_eng = TopicDiscoveryEngine()
    is_dup = disc_eng.is_duplicate(
        db=db_session,
        title=candidate_title,
        summary=candidate_summary,
        category="SECURITY",
        policy="event_action_domain"
    )
    assert is_dup is False


def test_genuine_current_affairs_duplicate_rejected(db_session):
    """
    Test 3: Genuine current affairs duplicates (same actors, actions, keywords)
    must be flagged and rejected.
    """
    existing_topic = Topic(
        id="top_existing_02",
        title="US Imposes Sweeping 25 Percent Tariffs on Global Steel Imports",
        summary="The White House announced sweeping 25 percent tariffs on foreign steel exports sparking trade retaliation fears.",
        category="GLOBAL_ECONOMY",
        status="APPROVED"
    )
    db_session.add(existing_topic)
    db_session.commit()

    # Highly similar duplicate story
    dup_candidate_title = "White House Imposes 25 Percent Tariffs on Foreign Steel"
    dup_candidate_summary = "Sweeping US tariffs on foreign steel announced, raising fears of global trade retaliation."

    router = DeduplicationRouter(policy="event_action_domain")
    result = router.evaluate_candidate(
        candidate_title=dup_candidate_title,
        candidate_summary=dup_candidate_summary,
        db=db_session,
        category="GLOBAL_ECONOMY"
    )

    assert result.is_duplicate is True
    assert result.is_allowed is False
    assert result.matched_event_title == existing_topic.title


def test_historical_duplicate_detection_intact(db_session):
    """
    Test 4: Historical duplicate detection remains strictly intact under historical policy
    (e.g. 1858 Great Stink vs London Thames stench).
    """
    existing_topic = Topic(
        id="top_hist_01",
        title="The Great Stink of 1858",
        summary="In 1858, a severe heatwave in London caused untreated human sewage in the River Thames to produce an unbearable stench that overwhelmed Parliament.",
        category="BIZARRE_HISTORY",
        status="APPROVED"
    )
    db_session.add(existing_topic)
    db_session.commit()

    # Paraphrased historical topic
    candidate_title = "When London River Thames Overwhelmed Parliament in 1858"
    candidate_summary = "During 1858, extreme stench from sewage in the River Thames forced politicians to flee Parliament curtains soaked in chloride."

    router = DeduplicationRouter(policy="historical_year_location")
    result = router.evaluate_candidate(
        candidate_title=candidate_title,
        candidate_summary=candidate_summary,
        db=db_session,
        category="BIZARRE_HISTORY"
    )

    assert result.is_duplicate is True
    assert result.is_allowed is False
    assert "1858" in result.reason or "Location" in result.reason or "Anchor" in result.reason


# ==============================================================================
# BLK-02: ResearchEngine Bridge (Pre-Verified Source Prioritization)
# ==============================================================================

def test_research_engine_uses_attached_sources_and_skips_wikipedia(db_session):
    """
    Test 5: When a topic has pre-attached SourceRecord entries (wire reports),
    ResearchEngine must use them and NEVER query Wikipedia or add historical fallback.
    """
    topic = Topic(
        id="top_wire_01",
        title="Diplomatic Summit in Geneva Reaches Ceasefire Agreement",
        summary="Delegates at the Geneva summit reached a historic ceasefire agreement after three days of closed-door negotiations.",
        category="DIPLOMACY",
        status="APPROVED"
    )
    db_session.add(topic)

    # Pre-attach wire sources (as CandidateWriter does)
    source1 = SourceRecord(
        topic_id=topic.id,
        source_name="Reuters",
        source_url="https://reuters.com/world/geneva-ceasefire-2026",
        source_type="wire_report",
        confidence=0.95
    )
    source2 = SourceRecord(
        topic_id=topic.id,
        source_name="Associated Press",
        source_url="https://apnews.com/article/geneva-peace-accord",
        source_type="wire_report",
        confidence=0.95
    )
    db_session.add_all([source1, source2])
    db_session.commit()

    researcher = ResearchEngine()

    # Mock search_wikipedia_page to verify it is NEVER called
    with patch.object(researcher, "search_wikipedia_page") as mock_wiki:
        result = researcher.research_topic(db_session, topic)

        mock_wiki.assert_not_called()
        assert result["verified"] is True
        assert result["sources_count"] == 2
        assert result["claims_count"] >= 1
        assert "Geneva" in result["summary"]

        # Verify no "Documented Historical Record" fallback was added
        all_sources = db_session.query(SourceRecord).filter(SourceRecord.topic_id == topic.id).all()
        assert len(all_sources) == 2
        assert not any("History" in s.source_url for s in all_sources)


def test_research_engine_falls_back_to_wikipedia_when_no_sources(db_session):
    """
    Test 6: When a topic has NO pre-attached sources, ResearchEngine
    queries Wikipedia and extracts encyclopedic claims.
    """
    topic = Topic(
        id="top_wiki_01",
        title="Battle of Hastings",
        summary="The Battle of Hastings was fought on 14 October 1066 between William of Normandy and Harold Godwinson.",
        category="HISTORICAL",
        status="APPROVED"
    )
    db_session.add(topic)
    db_session.commit()

    researcher = ResearchEngine()

    mock_page = MagicMock()
    mock_page.exists.return_value = True
    mock_page.title = "Battle of Hastings"
    mock_page.fullurl = "https://en.wikipedia.org/wiki/Battle_of_Hastings"
    mock_page.summary = "The Battle of Hastings was fought on 14 October 1066 between the Norman-French army of William, the Duke of Normandy, and an English army under the Anglo-Saxon King Harold Godwinson. This battle marked the beginning of the Norman conquest of England."

    with patch.object(researcher, "search_wikipedia_page", return_value=mock_page) as mock_wiki_search:
        result = researcher.research_topic(db_session, topic)

        mock_wiki_search.assert_called_once_with(topic.title)
        assert result["verified"] is True
        assert result["sources_count"] == 1
        assert "Battle of Hastings" in result["summary"]

        stored_sources = db_session.query(SourceRecord).filter(SourceRecord.topic_id == topic.id).all()
        assert len(stored_sources) == 1
        assert stored_sources[0].source_name == "Wikipedia: Battle of Hastings"


# ==============================================================================
# BLK-04: FreshnessScorer Future Timestamp Defense
# ==============================================================================

def test_freshness_scorer_future_timestamp_handling():
    """
    Test 7:
    - Future skew <= 1 hour (e.g., 15m into future) is clamped to 0.5h -> High freshness.
    - Large future timestamp (> 1 hour into future, e.g., 48h) is penalized to 72.0h -> Zero freshness.
    """
    scorer = FreshnessScorer()
    now_utc = datetime.now(timezone.utc)

    # 1. Minor clock skew: 15 minutes in the future
    future_skew_dt = now_utc + timedelta(minutes=15)
    age_skew = scorer.calculate_age_hours(future_skew_dt)
    assert age_skew == 0.5

    cluster_skew = EventCluster(
        cluster_id="c_skew",
        canonical_title="Breaking News with Minor Clock Skew",
        canonical_summary="Wire published with minor future timestamp skew.",
        last_published_at=future_skew_dt
    )
    score_skew, cls_skew = scorer.evaluate_freshness(cluster_skew)
    assert score_skew >= 95.0
    assert cls_skew in ["BREAKING", "DEVELOPING"]

    # 2. Large future timestamp: 48 hours in the future
    egregious_future_dt = now_utc + timedelta(hours=48)
    age_egregious = scorer.calculate_age_hours(egregious_future_dt)
    assert age_egregious == 72.0

    cluster_egregious = EventCluster(
        cluster_id="c_egregious",
        canonical_title="Erroneous Future Article",
        canonical_summary="Article timestamped two days into future.",
        last_published_at=egregious_future_dt
    )
    score_egregious, cls_egregious = scorer.evaluate_freshness(cluster_egregious)
    assert score_egregious <= 40.0
    assert cls_egregious in ["MATURING", "BACKGROUND"]


# ==============================================================================
# BLK-03: Synthetic DiscoveryProfile Extensibility Test
# ==============================================================================

def test_synthetic_space_tech_discovery_profile():
    """
    Test 8: Verifies that an entirely novel niche (e.g. SPACE_TECHNOLOGY) can configure
    custom entities, action domains, category taxonomy, tension keywords, and weights
    and run through normalization, clustering, relevance, and scoring WITHOUT modifying intelligence code.
    """
    space_profile = DiscoveryProfile(
        name="space_technology",
        description="Deep tech and space exploration discovery profile",
        recognized_entities={
            "nasa", "spacex", "esa", "isro", "blue origin", "jaxa", "cnsa",
            "starship", "falcon 9", "artemis", "james webb", "mars rover"
        },
        action_stems={
            "launch", "dock", "orbit", "land", "propel", "abort", "explode",
            "transmit", "deploy", "stage", "ignite", "rendezvous"
        },
        action_domain_map={
            "launch": "FLIGHT_OPERATIONS",
            "dock": "FLIGHT_OPERATIONS",
            "orbit": "FLIGHT_OPERATIONS",
            "deploy": "FLIGHT_OPERATIONS",
            "explode": "ANOMALY",
            "abort": "ANOMALY",
            "transmit": "COMMUNICATIONS"
        },
        category_theme_rules=[
            ("ROCKET_LAUNCHES", {"launch", "starship", "falcon 9", "ignite", "stage"}),
            ("PLANETARY_SCIENCE", {"mars rover", "james webb", "transmit", "orbit"}),
            ("LUNAR_MISSIONS", {"artemis", "land", "dock", "rendezvous"})
        ],
        high_impact_entities={"nasa", "spacex", "artemis", "starship"},
        low_relevance_noise={"scifi", "movie", "astrology", "horoscope", "alien costume"},
        tension_keywords={"anomaly", "abort", "explosion", "critical malfunction", "countdown stopped"},
        default_category="SPACE_EXPLORATION",
        fallback_category="GENERAL_AEROSPACE",
        deduplication_policy="event_action_domain",
        weight_freshness=0.35,
        weight_relevance=0.30,
        weight_breadth=0.15,
        weight_tension=0.10,
        weight_velocity=0.10
    )

    # 1. Normalization with space profile
    raw_article_1 = RawArticle(
        source_domain="spacenews.com",
        source_name="SpaceNews",
        title="SpaceX Starship Successfully Ignites All Raptor Engines in Texas",
        summary="NASA and SpaceX confirmed Starship completed a static fire countdown test ahead of its orbital launch attempt in 2026.",
        url="https://spacenews.com/starship-static-fire-texas",
        published_at=datetime.now(timezone.utc)
    )
    norm_1 = normalize_article(raw_article_1, profile=space_profile)
    assert "spacex" in norm_1.entities
    assert "starship" in norm_1.entities
    assert "launch" in norm_1.action_tokens or "ignite" in norm_1.action_tokens

    # Article 2 covering same event
    raw_article_2 = RawArticle(
        source_domain="nasaspaceflight.com",
        source_name="NASASpaceFlight",
        title="Starship Static Fire Success in Texas for SpaceX",
        summary="SpaceX conducts static fire countdown with Starship engines in Texas ahead of orbital launch.",
        url="https://nasaspaceflight.com/starship-static-fire-texas",
        published_at=datetime.now(timezone.utc)
    )
    norm_2 = normalize_article(raw_article_2, profile=space_profile)

    # 2. Clustering with space profile
    cluster_engine = EventClusterEngine(profile=space_profile)
    clusters = cluster_engine.cluster_articles([norm_1, norm_2])
    assert len(clusters) == 1
    cluster = clusters[0]
    assert len(cluster.source_domains) == 2

    # 3. Relevance with space profile
    rel_scorer = RelevanceScorer(profile=space_profile)
    rel_score, category = rel_scorer.evaluate_relevance(cluster)
    assert rel_score >= 70.0
    assert category == "ROCKET_LAUNCHES"

    # 4. Opportunity Scoring with space profile
    opp_scorer = OpportunityScorer(profile=space_profile)
    fresh_scorer = FreshnessScorer(profile=space_profile)
    fresh_scorer.evaluate_freshness(cluster)
    opp_score = opp_scorer.calculate_opportunity_score(cluster)
    assert opp_score >= 60.0
