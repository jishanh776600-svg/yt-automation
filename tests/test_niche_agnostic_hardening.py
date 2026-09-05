"""
Tests for AL-AMR Step 2E: Final Niche-Agnosticity Hardening and Production-Bridge Audit.

Verifies:
1. Intra-batch deduplication via DeduplicationRouter.filter_intra_batch_duplicates():
   - Historical candidates: duplicate year/location (e.g., 1858 Great Stink) deduplicated.
   - Current affairs candidates: distinct events in same year/city (London airport strike vs stock exchange cyberattack) both preserved.
   - Current affairs candidates: duplicate reports on same event deduplicated.
2. Dynamic environment variable niche switching (CONTENT_PROFILE / ACTIVE_NICHE):
   - Switch between HISTORICAL and CURRENT_AFFAIRS.
   - Automatic synchronization of ContentProfile, DiscoveryProfile, and Deduplication policy.
3. Profile-driven source strategy in discover_candidates():
   - Custom RSS feeds and GDELT toggle configured via DiscoveryProfile.
4. Profile-driven research archive fallback in ResearchEngine:
   - Uses pre-attached sources when present.
   - Falls back to profile-driven archive defaults (e.g., NASA NTRS vs Historical Record) when absent.
5. Synthetic 4-niche end-to-end execution proof:
   - CURRENT_AFFAIRS, HISTORICAL, SPACE_TECHNOLOGY, and FINANCIAL_MARKETS run through
     normalization, clustering, relevance, scoring, dedup, research, and scripting
     without modifying any universal engine code.
"""

import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, SourceRecord, ClaimRecord
from core.content_profile import (
    ContentProfile,
    CURRENT_AFFAIRS_PROFILE,
    HISTORICAL_PROFILE,
    get_active_profile,
    set_active_profile,
    register_profile,
    get_profile_by_name,
)
from core.discovery_profile import (
    DiscoveryProfile,
    CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    HISTORICAL_DISCOVERY_PROFILE,
    get_active_discovery_profile,
    set_active_discovery_profile,
    register_discovery_profile,
    resolve_policy_for_category,
)
from engines.deduplication_engine import DeduplicationRouter
from engines.research_engine import ResearchEngine
from engines.script_engine import ScriptEngine
from engines.fact_verifier import FactVerificationResult
from intelligence import discover_candidates
from intelligence.models import RawArticle, EventCluster
from intelligence.normalization import normalize_article
from intelligence.clustering import EventClusterEngine
from intelligence.relevance import RelevanceScorer
from intelligence.scoring import OpportunityScorer


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_intra_batch_deduplication_historical():
    router = DeduplicationRouter()

    candidates = [
        {"title": "The Great Stink of 1858", "summary": "London Thames smell crisis in 1858 parliament"},
        {"title": "1858 London River Sewage Crisis", "summary": "The Thames river odor crisis shuts parliament down in 1858"},
        {"title": "The 1906 San Francisco Earthquake", "summary": "Massive earthquake strikes California in 1906"},
    ]

    filtered = router.filter_intra_batch_duplicates(
        candidates,
        title_fn=lambda c: c["title"],
        summary_fn=lambda c: c["summary"],
        policy="historical_year_location"
    )

    assert len(filtered) == 2
    titles = [c["title"] for c in filtered]
    assert "The Great Stink of 1858" in titles
    assert "The 1906 San Francisco Earthquake" in titles


def test_intra_batch_deduplication_current_affairs():
    router = DeduplicationRouter()

    # Part A: Distinct events in same year and city must BOTH be kept
    distinct_candidates = [
        {
            "title": "London Heathrow Airport Workers Announce 48-Hour Strike Over Wages",
            "summary": "Heathrow baggage handlers and security staff walk out causing travel chaos across Europe.",
            "category": "SECURITY",
        },
        {
            "title": "London Stock Exchange Targeted by Severe Cyberattack Disrupting Trades",
            "summary": "Financial regulators in London halt morning trading following a major state-sponsored network intrusion.",
            "category": "SECURITY",
        },
    ]
    kept_distinct = router.filter_intra_batch_duplicates(
        distinct_candidates,
        title_fn=lambda c: c["title"],
        summary_fn=lambda c: c["summary"],
        category="SECURITY",
        policy="event_action_domain"
    )
    assert len(kept_distinct) == 2

    # Part B: Duplicate reporting of the same event must be filtered
    candidates_with_dup = [
        {
            "title": "US Imposes Sweeping 25 Percent Tariffs on Global Steel Imports",
            "summary": "The White House announced sweeping 25 percent tariffs on foreign steel exports sparking trade retaliation fears.",
            "category": "GLOBAL_ECONOMY",
        },
        {
            "title": "Federal Reserve Slashes Benchmark Interest Rate by 50 Basis Points",
            "summary": "Central bank policymakers cut interest rates amid cooling inflation and labor market softening.",
            "category": "GLOBAL_ECONOMY",
        },
        {
            "title": "White House Imposes 25 Percent Tariffs on Foreign Steel",
            "summary": "Sweeping US tariffs on foreign steel announced, raising fears of global trade retaliation.",
            "category": "GLOBAL_ECONOMY",
        },
    ]

    filtered = router.filter_intra_batch_duplicates(
        candidates_with_dup,
        title_fn=lambda c: c["title"],
        summary_fn=lambda c: c["summary"],
        category="GLOBAL_ECONOMY",
        policy="event_action_domain"
    )

    assert len(filtered) == 2
    titles = [c["title"] for c in filtered]
    assert "US Imposes Sweeping 25 Percent Tariffs on Global Steel Imports" in titles
    assert "Federal Reserve Slashes Benchmark Interest Rate by 50 Basis Points" in titles


def test_env_var_niche_switching(monkeypatch):
    router = DeduplicationRouter()

    monkeypatch.setenv("CONTENT_PROFILE", "HISTORICAL")
    assert get_active_profile().name == "HISTORICAL"
    assert get_active_discovery_profile().name == "HISTORICAL"
    assert router.resolve_policy() == "historical_year_location"

    monkeypatch.setenv("CONTENT_PROFILE", "CURRENT_AFFAIRS")
    assert get_active_profile().name == "CURRENT_AFFAIRS"
    assert get_active_discovery_profile().name == "CURRENT_AFFAIRS"
    assert router.resolve_policy() == "event_action_domain"

    monkeypatch.delenv("CONTENT_PROFILE")
    monkeypatch.setenv("ACTIVE_NICHE", "HISTORICAL")
    assert get_active_profile().name == "HISTORICAL"
    assert router.resolve_policy() == "historical_year_location"


def test_profile_driven_source_strategy(db_session):
    custom_discovery = DiscoveryProfile(
        name="TECH_DISCOVERY",
        description="Emerging consumer and enterprise technology developments.",
        rss_feeds=[
            {"url": "https://techcrunch.com/feed/", "name": "TechCrunch"},
            {"url": "https://arstechnica.com/feed/", "name": "Ars Technica"}
        ],
        enable_gdelt=False,
    )

    with patch("intelligence.RSSSourceAdapter") as mock_rss, \
         patch("intelligence.GDELTSourceAdapter") as mock_gdelt, \
         patch("intelligence.EventClusterEngine") as mock_cluster, \
         patch("intelligence.CandidateWriter") as mock_writer:

        mock_rss_instance = MagicMock()
        mock_rss_instance.ingest_all.return_value = []
        mock_rss.return_value = mock_rss_instance

        mock_cluster_instance = MagicMock()
        mock_cluster_instance.cluster_articles.return_value = []
        mock_cluster.return_value = mock_cluster_instance

        mock_writer_instance = MagicMock()
        mock_writer_instance.write_candidates.return_value = []
        mock_writer.return_value = mock_writer_instance

        discover_candidates(db_session, profile=custom_discovery)

        mock_rss.assert_called_once_with(
            feeds=[
                {"url": "https://techcrunch.com/feed/", "name": "TechCrunch"},
                {"url": "https://arstechnica.com/feed/", "name": "Ars Technica"}
            ]
        )
        mock_gdelt.assert_not_called()


def test_profile_driven_research_archive_fallback(db_session):
    engine = ResearchEngine()

    # Case A: Topic with pre-attached source records
    topic_with_sources = Topic(
        id="top_res_01",
        title="Ceasefire Signed in Geneva Peace Summit",
        summary="Envoys reached peace accord in Geneva.",
        category="CURRENT_AFFAIRS",
    )
    db_session.add(topic_with_sources)
    db_session.commit()

    source = SourceRecord(
        topic_id=topic_with_sources.id,
        source_name="Reuters Wire",
        source_url="https://reuters.com/world/geneva-summit",
        confidence=0.95,
    )
    claim = ClaimRecord(
        topic_id=topic_with_sources.id,
        claim_text="Envoys signed a 90-day armistice agreement.",
        supporting_sources="Reuters Wire",
        verification_status="VERIFIED",
        confidence=0.95
    )
    db_session.add_all([source, claim])
    db_session.commit()

    ctx = engine.research_topic(db_session, topic_with_sources, profile=CURRENT_AFFAIRS_PROFILE)
    assert ctx["verified"] is True
    assert ctx["sources_count"] == 1
    assert "Reuters Wire" in [c["source"] for c in ctx["verified_claims"]]

    # Case B: Topic without pre-attached sources under a custom profile
    custom_space_profile = ContentProfile(
        name="SPACE_EXPLORATION",
        description="Deep space exploration and aerospace engineering.",
        target_audience="Space technology enthusiasts",
        tone="Scientific and awe-inspiring",
        script_objective="Discovery, technical hurdle, breakthrough",
        system_role_instruction="Explain the aerospace breakthrough.",
        default_archive_name="NASA Technical Reports Server",
        default_archive_url="https://ntrs.nasa.gov/",
    )

    topic_empty = Topic(
        id="top_res_02",
        title="Artemis III Crew Module Thermal Shield Validation",
        summary="Engineers complete thermal stress testing on lunar module.",
        category="SCIENCE",
    )
    db_session.add(topic_empty)
    db_session.commit()

    with patch.object(engine, "search_wikipedia_page", return_value=None):
        ctx_space = engine.research_topic(db_session, topic_empty, profile=custom_space_profile)
        assert ctx_space["verified"] is True
        created_source = db_session.query(SourceRecord).filter(SourceRecord.topic_id == topic_empty.id).first()
        assert created_source is not None
        assert created_source.source_name == "NASA Technical Reports Server"
        assert created_source.source_url == "https://ntrs.nasa.gov/"


def test_synthetic_four_niche_execution_proof(db_session):
    niches = [
        {
            "name": "CURRENT_AFFAIRS",
            "content_profile": CURRENT_AFFAIRS_PROFILE,
            "discovery_profile": CURRENT_AFFAIRS_DISCOVERY_PROFILE,
            "category": "CURRENT_AFFAIRS",
            "articles": [
                {
                    "title": "US Imposes Fresh Chip Export Restrictions on Semiconductor Tech",
                    "content": "The Commerce Department announced comprehensive export controls on AI hardware in Washington.",
                    "url": "https://reuters.com/tech/chip-controls",
                    "source_domain": "reuters.com",
                    "published_at": datetime.now(timezone.utc) - timedelta(hours=3),
                },
                {
                    "title": "Commerce Department Expands Semiconductor AI Chip Limits",
                    "content": "New semiconductor licensing restrictions announced in Washington affect cutting edge processors.",
                    "url": "https://apnews.com/tech/chip-limits",
                    "source_domain": "apnews.com",
                    "published_at": datetime.now(timezone.utc) - timedelta(hours=2),
                },
            ],
            "dedup_policy": "event_action_domain",
        },
        {
            "name": "HISTORICAL",
            "content_profile": HISTORICAL_PROFILE,
            "discovery_profile": HISTORICAL_DISCOVERY_PROFILE,
            "category": "HISTORY",
            "articles": [
                {
                    "title": "1858 Great Stink Overwhelms London Parliament",
                    "content": "During the hot summer of 1858, the Thames river smell in London forced politicians to evacuate.",
                    "url": "https://history.org/1858-stink",
                    "source_domain": "history.org",
                    "published_at": datetime.now(timezone.utc) - timedelta(days=1),
                },
            ],
            "dedup_policy": "historical_year_location",
        },
        {
            "name": "SPACE_TECHNOLOGY",
            "content_profile": ContentProfile(
                name="SPACE_TECHNOLOGY",
                description="Space technology and aerospace exploration breakthroughs.",
                target_audience="Space enthusiasts",
                tone="Technical and inspiring",
                script_objective="Mission context, mechanical failure, orbital rescue",
                system_role_instruction="Analyze the propulsion breakthrough.",
                default_archive_name="NASA Scientific Archive",
                default_archive_url="https://nasa.gov/archive",
            ),
            "discovery_profile": DiscoveryProfile(
                name="SPACE_DISCOVERY",
                description="Space industry and rocket propulsion news.",
                high_impact_entities={"nasa", "spacex", "artemis"},
                recognized_entities={"mars", "moon", "orbit", "satellite", "rocket"},
                action_stems={"launch", "dock", "propel", "thruster", "orbit", "breakthrough"},
                action_domain_map={"launch": "MISSION_OPERATIONS", "propel": "PROPULSION", "thruster": "PROPULSION"},
                category_theme_rules=[("SCIENCE", {"thruster", "propulsion", "orbit"})],
                deduplication_policy="event_action_domain",
            ),
            "category": "SCIENCE",
            "articles": [
                {
                    "title": "Next-Gen Ion Thruster Sets Orbital Propulsion Efficiency Record",
                    "content": "Engineers achieve breakthrough in ion propulsion for deep space exploration missions.",
                    "url": "https://spacenews.com/ion-thruster-record",
                    "source_domain": "spacenews.com",
                    "published_at": datetime.now(timezone.utc) - timedelta(hours=5),
                },
            ],
            "dedup_policy": "event_action_domain",
        },
        {
            "name": "FINANCIAL_MARKETS",
            "content_profile": ContentProfile(
                name="FINANCIAL_MARKETS",
                description="Global macro finance, central banking, and market liquidity.",
                target_audience="Macro investors and traders",
                tone="Analytical, fast-paced, high stakes",
                script_objective="Market shock, liquidity cascade, institutional reaction",
                system_role_instruction="Explain the monetary shift.",
                default_archive_name="Federal Reserve Economic Data",
                default_archive_url="https://fred.stlouisfed.org",
            ),
            "discovery_profile": DiscoveryProfile(
                name="FINANCIAL_DISCOVERY",
                description="Financial markets and economic news.",
                high_impact_entities={"federal reserve", "central bank", "treasury"},
                recognized_entities={"yield", "bond", "inflation", "debt", "interest rate"},
                action_stems={"rate", "cut", "hike", "liquidity", "inject", "bailout"},
                action_domain_map={"rate": "MONETARY_POLICY", "liquidity": "LIQUIDITY_OPERATIONS"},
                category_theme_rules=[("FINANCE", {"liquidity", "yield", "rate"})],
                deduplication_policy="event_action_domain",
            ),
            "category": "FINANCE",
            "articles": [
                {
                    "title": "Central Bank Announces Surprise Emergency Liquidity Window",
                    "content": "Monetary authorities inject liquidity into sovereign bond markets following yield spike.",
                    "url": "https://bloomberg.com/news/central-bank-window",
                    "source_domain": "bloomberg.com",
                    "published_at": datetime.now(timezone.utc) - timedelta(hours=1),
                },
            ],
            "dedup_policy": "event_action_domain",
        },
    ]

    dedup_router = DeduplicationRouter()
    research_engine = ResearchEngine()

    for niche in niches:
        c_prof = niche["content_profile"]
        d_prof = niche["discovery_profile"]

        register_profile(c_prof)
        register_discovery_profile(d_prof)

        # 1. Normalization
        raw_articles = []
        for a in niche["articles"]:
            raw = RawArticle(
                title=a["title"],
                summary=a["content"],
                url=a["url"],
                source_domain=a["source_domain"],
                source_name=a["source_domain"],
                published_at=a["published_at"]
            )
            norm = normalize_article(raw, profile=d_prof)
            raw_articles.append(norm)

        assert len(raw_articles) == len(niche["articles"])

        # 2. Clustering
        cluster_engine = EventClusterEngine()
        clusters = cluster_engine.cluster_articles(raw_articles)
        assert len(clusters) >= 1
        primary_cluster = clusters[0]

        # 3. Relevance Scoring
        rel_scorer = RelevanceScorer(profile=d_prof)
        rel_score, cat = rel_scorer.evaluate_relevance(primary_cluster)
        assert rel_score >= 0.0

        # 4. Opportunity Scoring
        opp_scorer = OpportunityScorer(profile=d_prof)
        opp_score = opp_scorer.calculate_opportunity_score(primary_cluster)
        assert opp_score >= 0.0

        # 5. Deduplication Policy Resolution
        resolved_policy = dedup_router.resolve_policy(category=niche["category"])
        assert resolved_policy == niche["dedup_policy"]

        # 6. Research Engine Execution
        topic = Topic(
            id=f"top_{niche['name'].lower()}",
            title=primary_cluster.canonical_title,
            summary=primary_cluster.canonical_summary,
            category=niche["category"],
        )
        db_session.add(topic)
        db_session.commit()

        src = SourceRecord(
            topic_id=topic.id,
            source_name=primary_cluster.articles[0].source_domain,
            source_url=primary_cluster.articles[0].url,
            confidence=0.9,
        )
        db_session.add(src)
        db_session.commit()

        research_ctx = research_engine.research_topic(db_session, topic, profile=c_prof)
        assert research_ctx["verified"] is True
        assert research_ctx["sources_count"] >= 1

        # 7. ScriptEngine Profile Execution & Critic Evaluation
        script_engine = ScriptEngine(profile=c_prof)
        assert script_engine.profile.name == c_prof.name

        compliant_script = {
            "hook": "In 2026, an unexpected crisis altered the geopolitical landscape forever.",
            "context": "Allied commanders monitored the unfolding situation across primary military sectors.",
            "escalation": "Rising pressures pushed the entire initiative to the absolute breaking point.",
            "reveal": "A critical strategic maneuver secured the definitive outcome against all odds.",
            "loop_twist": "And that is how the decisive milestone was successfully achieved."
        }
        with patch("engines.fact_verifier.FactVerifier.verify") as mock_verify:
            mock_verify.return_value = FactVerificationResult(passed=True, score=15.0)
            eval_res = script_engine.critic.evaluate(
                script_data=compliant_script,
                research_data=research_ctx
            )
            assert eval_res.passed is True
            assert eval_res.score >= 80.0
