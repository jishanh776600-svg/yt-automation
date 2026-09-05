"""
Offline unit & integration test suite for the Isolated Current-Affairs Intelligence Layer.
Verifies all 20 specified criteria offline with zero live API calls or network requests.
"""
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, SourceRecord, Job
from config.constants import CurrentAffairsCategory, HistoricalCategory
from intelligence.models import RawArticle, EventCluster
from intelligence.normalization import (
    normalize_article, normalize_url, strip_html, strip_publisher_boilerplate,
    extract_entities_and_tokens
)
from intelligence.sources.rss_source import RSSSourceAdapter, parse_pubdate
from intelligence.sources.gdelt_source import GDELTSourceAdapter
from intelligence.clustering import EventClusterEngine, are_articles_same_event
from intelligence.freshness import FreshnessScorer
from intelligence.relevance import RelevanceScorer
from intelligence.scoring import OpportunityScorer
from intelligence.deduplication import CurrentAffairsDeduplicationEngine
from intelligence.candidate_writer import CandidateWriter
from intelligence import discover_current_affairs_candidates
from engines.topic_discovery import TopicDiscoveryEngine


class TestIntelligenceLayer(unittest.TestCase):

    def setUp(self):
        """Sets up an isolated in-memory SQLite database for test execution."""
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    # 1. RSS article parsing
    def test_01_rss_article_parsing(self):
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>BBC News</title>
                <item>
                    <title>NATO announces new defense pact in Brussels</title>
                    <link>https://www.bbc.com/news/world-12345?utm_source=rss</link>
                    <description>Leaders gathered in Brussels to finalize security agreements.</description>
                    <pubDate>Fri, 04 Sep 2026 10:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>
        """
        adapter = RSSSourceAdapter()
        articles = adapter.parse_feed_content(sample_rss, "BBC News", "bbc.com")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].title, "NATO announces new defense pact in Brussels")
        self.assertEqual(articles[0].source_domain, "bbc.com")
        self.assertIsNotNone(articles[0].published_at)

    # 2. Malformed RSS handling
    def test_02_malformed_rss_handling(self):
        malformed_xml = "<rss><channel><item><title>Incomplete tag"
        adapter = RSSSourceAdapter()
        articles = adapter.parse_feed_content(malformed_xml, "Test Source", "test.com")
        self.assertEqual(articles, [])

    # 3. Duplicate URL removal
    def test_03_duplicate_url_removal(self):
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Wire Service</title>
                <item>
                    <title>Story 1</title>
                    <link>https://reuters.com/world/story1?utm_source=twitter</link>
                    <description>Summary 1</description>
                </item>
                <item>
                    <title>Story 1 Duplicate</title>
                    <link>https://reuters.com/world/story1?utm_medium=email</link>
                    <description>Summary 1</description>
                </item>
            </channel>
        </rss>
        """
        adapter = RSSSourceAdapter(feeds=[{"name": "Wire", "url": "mock://wire", "domain": "reuters.com"}])
        with patch.object(adapter, "fetch_feed_xml", return_value=sample_rss):
            articles = adapter.ingest_all()
            self.assertEqual(len(articles), 1)
            self.assertEqual(articles[0].url, "https://reuters.com/world/story1")

    # 4. Timestamp normalization
    def test_04_timestamp_normalization(self):
        rfc822_date = "Fri, 04 Sep 2026 12:00:00 GMT"
        iso_date = "2026-09-04T12:00:00Z"
        dt1 = parse_pubdate(rfc822_date)
        dt2 = parse_pubdate(iso_date)
        self.assertIsNotNone(dt1)
        self.assertIsNotNone(dt2)
        self.assertEqual(dt1.year, 2026)
        self.assertEqual(dt1.month, 9)
        self.assertEqual(dt1.day, 4)
        self.assertEqual(dt1.hour, 12)
        self.assertEqual(dt2.hour, 12)

    # 5. Article normalization
    def test_05_article_normalization(self):
        raw = RawArticle(
            title="BREAKING: US and Poland sign major military agreement - BBC News",
            summary="<p>Warsaw announced a new deployment of troops.</p>",
            url="https://bbc.com/news/123?utm_campaign=social#ref",
            source_domain="bbc.com",
            source_name="BBC",
            published_at=datetime(2026, 9, 4, 10, 0)
        )
        norm = normalize_article(raw)
        self.assertEqual(norm.normalized_title, "US and Poland sign major military agreement")
        self.assertEqual(norm.normalized_summary, "Warsaw announced a new deployment of troops.")
        self.assertEqual(norm.url, "https://bbc.com/news/123")
        self.assertIn("poland", norm.countries)
        self.assertIn("military", norm.action_tokens)
        self.assertIn("deployment", norm.action_tokens)

    # 6. Same-event clustering
    def test_06_same_event_clustering(self):
        art1 = RawArticle(
            title="Poland and US finalize missile defense deployment in Warsaw",
            summary="Pentagon confirms delivery of interceptors to eastern flank.",
            url="https://bbc.com/poland-missiles",
            source_domain="bbc.com",
            source_name="BBC",
            published_at=datetime(2026, 9, 4, 10, 0)
        )
        art2 = RawArticle(
            title="Warsaw confirms US missile interceptors deployment",
            summary="Polish defense ministry announces new air defense battery with United States.",
            url="https://reuters.com/poland-us-defense",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=datetime(2026, 9, 4, 11, 0)
        )
        engine = EventClusterEngine()
        clusters = engine.cluster_articles([normalize_article(art1), normalize_article(art2)])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0].articles), 2)
        self.assertEqual(clusters[0].source_domains, {"bbc.com", "reuters.com"})

    # 7. Different-event separation
    def test_07_different_event_separation(self):
        art1 = RawArticle(
            title="NATO conducts naval exercises in Baltic Sea",
            summary="Allied warships assemble for scheduled maritime maneuvers.",
            url="https://bbc.com/nato-drills",
            source_domain="bbc.com",
            source_name="BBC",
            published_at=datetime(2026, 9, 4, 10, 0)
        )
        art2 = RawArticle(
            title="Japan central bank raises interest rates in surprise move",
            summary="Tokyo policymakers increase benchmark rates amid currency pressures.",
            url="https://reuters.com/japan-rates",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=datetime(2026, 9, 4, 10, 0)
        )
        engine = EventClusterEngine()
        clusters = engine.cluster_articles([normalize_article(art1), normalize_article(art2)])
        self.assertEqual(len(clusters), 2)

    # 8. Same-year/same-city different-event separation
    def test_08_same_year_same_city_different_event_separation(self):
        """CRITICAL: Two distinct events in London in 2026 must NOT collide."""
        art_military = RawArticle(
            title="UK Ministry of Defence announces new military deployment to Baltic airspace",
            summary="British fighter jets deployed from London defense headquarters.",
            url="https://bbc.com/uk-jets",
            source_domain="bbc.com",
            source_name="BBC",
            published_at=datetime(2026, 9, 4, 9, 0)
        )
        art_trade = RawArticle(
            title="UK Treasury signs major trade and tariff accord with Australia in London",
            summary="Officials in London finalize bilateral commerce pact to reduce tariffs.",
            url="https://reuters.com/uk-aus-trade",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=datetime(2026, 9, 4, 10, 0)
        )
        engine = EventClusterEngine()
        clusters = engine.cluster_articles([normalize_article(art_military), normalize_article(art_trade)])
        # Must produce TWO distinct clusters despite both being in London in 2026
        self.assertEqual(len(clusters), 2)

    # 9. Freshness scoring
    def test_09_freshness_scoring(self):
        ref_time = datetime(2026, 9, 4, 12, 0)
        cl_breaking = EventCluster(
            cluster_id="cl_1",
            canonical_title="Breaking event",
            canonical_summary="Just happened",
            last_published_at=datetime(2026, 9, 4, 10, 30)  # 1.5h old
        )
        cl_older = EventCluster(
            cluster_id="cl_2",
            canonical_title="Older event",
            canonical_summary="Happened days ago",
            last_published_at=datetime(2026, 9, 1, 12, 0)  # 72h old
        )
        scorer = FreshnessScorer()
        score_breaking, class_breaking = scorer.evaluate_freshness(cl_breaking, reference_time=ref_time)
        score_older, class_older = scorer.evaluate_freshness(cl_older, reference_time=ref_time)
        self.assertEqual(class_breaking, "BREAKING")
        self.assertGreaterEqual(score_breaking, 90.0)
        self.assertLess(score_older, score_breaking)

    # 10. Relevance scoring
    def test_10_relevance_scoring(self):
        cl = EventCluster(
            cluster_id="cl_rel",
            canonical_title="US and NATO impose new sanctions on foreign defense firms",
            canonical_summary="Washington and Brussels expand trade embargo."
        )
        cl.entities = {"united states", "nato", "brussels", "washington"}
        cl.action_tokens = {"sanction", "embargo", "defense"}
        cl.countries = {"united states"}

        scorer = RelevanceScorer()
        rel_score, category = scorer.evaluate_relevance(cl)
        self.assertGreaterEqual(rel_score, 75.0)
        self.assertIn(category, [CurrentAffairsCategory.GLOBAL_ECONOMY.value, CurrentAffairsCategory.GEOPOLITICS.value, CurrentAffairsCategory.SECURITY.value])

    # 11. Multi-source requirement
    def test_11_multi_source_requirement(self):
        cl = EventCluster(cluster_id="cl_m", canonical_title="Event", canonical_summary="Summ")
        cl.source_domains = {"bbc.com", "reuters.com"}
        writer = CandidateWriter(min_independent_domains=2)
        passed, reason = writer.evaluate_multi_source_evidence(cl)
        self.assertTrue(passed)
        self.assertTrue(cl.has_multi_source_consensus)

    # 12. Single-source candidate rejection
    def test_12_single_source_candidate_rejection(self):
        cl = EventCluster(cluster_id="cl_s", canonical_title="Single source claim", canonical_summary="Summ")
        cl.source_domains = {"unverified-blog.com"}
        writer = CandidateWriter(min_independent_domains=2)
        passed, reason = writer.evaluate_multi_source_evidence(cl)
        self.assertFalse(passed)
        self.assertEqual(cl.status, "INSUFFICIENT_EVIDENCE")

    # 13. Two-source candidate approval
    def test_13_two_source_candidate_approval(self):
        cl = EventCluster(
            cluster_id="cl_2src",
            canonical_title="European Union reaches landmark defense pact",
            canonical_summary="Brussels envoys sign security accord.",
            primary_category=CurrentAffairsCategory.DIPLOMACY.value,
            opportunity_score=85.0
        )
        art1 = RawArticle(title="EU defense pact", summary="Summary", url="https://bbc.com/eu", source_domain="bbc.com", source_name="BBC", published_at=None)
        art2 = RawArticle(title="EU defense pact", summary="Summary", url="https://reuters.com/eu", source_domain="reuters.com", source_name="Reuters", published_at=None)
        cl.add_article(art1)
        cl.add_article(art2)

        writer = CandidateWriter(min_independent_domains=2, min_opportunity_score=50.0)
        approved = writer.process_and_persist_candidates([cl], self.db)
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0].status, "APPROVED")
        self.assertEqual(approved[0].category, CurrentAffairsCategory.DIPLOMACY.value)

    # 14. Duplicate current-affairs event rejection
    def test_14_duplicate_current_affairs_event_rejection(self):
        existing_topic = Topic(
            id="top_exist_1",
            title="US and Poland finalize missile defense deployment in Warsaw",
            summary="Pentagon confirms delivery of interceptors to eastern flank.",
            category=CurrentAffairsCategory.SECURITY.value,
            status="APPROVED"
        )
        self.db.add(existing_topic)
        self.db.commit()

        dup_cluster = EventCluster(
            cluster_id="cl_dup",
            canonical_title="US and Poland finalize missile defense deployment in Warsaw",
            canonical_summary="Pentagon confirms delivery of interceptors to eastern flank.",
            primary_category=CurrentAffairsCategory.SECURITY.value,
            opportunity_score=80.0
        )
        dup_cluster.source_domains = {"bbc.com", "apnews.com"}
        dup_cluster.entities = {"poland", "united states", "pentagon", "warsaw"}
        dup_cluster.action_tokens = {"military", "missile", "deployment"}

        writer = CandidateWriter(min_independent_domains=2)
        approved = writer.process_and_persist_candidates([dup_cluster], self.db)
        self.assertEqual(len(approved), 0)
        self.assertEqual(dup_cluster.status, "REJECTED")

    # 15. Distinct current-affairs events accepted
    def test_15_distinct_current_affairs_events_accepted(self):
        existing_topic = Topic(
            id="top_exist_2",
            title="UK Ministry of Defence announces new military deployment to Baltic airspace",
            summary="British fighter jets deployed from London defense headquarters.",
            category=CurrentAffairsCategory.SECURITY.value,
            status="APPROVED"
        )
        self.db.add(existing_topic)
        self.db.commit()

        distinct_cluster = EventCluster(
            cluster_id="cl_dist",
            canonical_title="UK Treasury signs major trade and tariff accord with Australia in London",
            canonical_summary="London trade summit eliminates agricultural export tariffs.",
            primary_category=CurrentAffairsCategory.GLOBAL_ECONOMY.value,
            opportunity_score=75.0
        )
        distinct_cluster.source_domains = {"ft.com", "reuters.com"}
        distinct_cluster.entities = {"united kingdom", "australia", "london"}
        distinct_cluster.action_tokens = {"trade", "tariff"}
        art1 = RawArticle(title="Trade", summary="Summ", url="https://ft.com/trade", source_domain="ft.com", source_name="FT", published_at=None)
        art2 = RawArticle(title="Trade", summary="Summ", url="https://reuters.com/trade", source_domain="reuters.com", source_name="Reuters", published_at=None)
        distinct_cluster.add_article(art1)
        distinct_cluster.add_article(art2)

        writer = CandidateWriter(min_independent_domains=2)
        approved = writer.process_and_persist_candidates([distinct_cluster], self.db)
        # Must be approved and not collide with the existing London military story
        self.assertEqual(len(approved), 1)

    # 16. Topic creation
    def test_16_topic_creation(self):
        cl = EventCluster(
            cluster_id="cl_t",
            canonical_title="NATO Leaders Convene in Brussels for Strategic Summit",
            canonical_summary="Allied leaders debate defense spending and eastern flank readiness.",
            primary_category=CurrentAffairsCategory.GEOPOLITICS.value,
            opportunity_score=88.5
        )
        cl.source_domains = {"bbc.com", "reuters.com"}
        art1 = RawArticle(title="NATO", summary="Summ", url="https://bbc.com/nato", source_domain="bbc.com", source_name="BBC", published_at=None)
        art2 = RawArticle(title="NATO", summary="Summ", url="https://reuters.com/nato", source_domain="reuters.com", source_name="Reuters", published_at=None)
        cl.add_article(art1)
        cl.add_article(art2)

        writer = CandidateWriter(min_independent_domains=2)
        topics = writer.process_and_persist_candidates([cl], self.db)
        self.assertEqual(len(topics), 1)
        t = topics[0]
        self.assertEqual(t.status, "APPROVED")
        self.assertEqual(t.score, 88.5)
        self.assertEqual(t.category, CurrentAffairsCategory.GEOPOLITICS.value)

    # 17. SourceRecord creation
    def test_17_source_record_creation(self):
        cl = EventCluster(
            cluster_id="cl_src",
            canonical_title="G7 Envoys Sign Climate and Energy Transition Accord",
            canonical_summary="Finance ministers commit to multilateral infrastructure funding.",
            primary_category=CurrentAffairsCategory.GLOBAL_ECONOMY.value,
            opportunity_score=80.0
        )
        art1 = RawArticle(title="G7", summary="Summ", url="https://bbc.com/g7", source_domain="bbc.com", source_name="BBC", published_at=None)
        art2 = RawArticle(title="G7", summary="Summ", url="https://apnews.com/g7", source_domain="apnews.com", source_name="AP", published_at=None)
        cl.add_article(art1)
        cl.add_article(art2)

        writer = CandidateWriter(min_independent_domains=2)
        topics = writer.process_and_persist_candidates([cl], self.db)
        self.assertEqual(len(topics), 1)
        t = topics[0]

        sources = self.db.query(SourceRecord).filter(SourceRecord.topic_id == t.id).all()
        self.assertEqual(len(sources), 2)
        urls = {s.source_url for s in sources}
        self.assertIn("https://bbc.com/g7", urls)
        self.assertIn("https://apnews.com/g7", urls)

    # 18. Historical topics unaffected
    def test_18_historical_topics_unaffected(self):
        from core.discovery_profile import HISTORICAL_DISCOVERY_PROFILE
        hist_topic = Topic(
            id="top_hist_1",
            title="The Great Stink of London (1858)",
            summary="A hot summer overwhelmed London with the stench of sewage.",
            category=HistoricalCategory.DOCUMENTED_DISASTERS.value,
            score=55.0,
            status="APPROVED"
        )
        self.db.add(hist_topic)
        self.db.commit()

        # Run historical discovery and verify it remains unaffected
        engine = TopicDiscoveryEngine()
        results = engine.discover_topics(self.db, limit=1, profile=HISTORICAL_DISCOVERY_PROFILE)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "The Great Stink of London (1858)")
        self.assertEqual(results[0].category, HistoricalCategory.DOCUMENTED_DISASTERS.value)

    # 19. Source failure does not crash intelligence layer
    def test_19_source_failure_does_not_crash_intelligence_layer(self):
        mock_failing_rss = MagicMock()
        mock_failing_rss.ingest_all.side_effect = RuntimeError("Network timeout connecting to RSS")

        # Must not raise an exception; must return empty list safely
        topics = discover_current_affairs_candidates(
            db=self.db,
            limit=3,
            rss_adapter=mock_failing_rss
        )
        self.assertEqual(topics, [])

    # 20. Intelligence failure does not break historical discovery
    def test_20_intelligence_failure_does_not_break_historical_discovery(self):
        from core.discovery_profile import HISTORICAL_DISCOVERY_PROFILE
        engine = TopicDiscoveryEngine()

        # Even if current affairs discovery fails with an error
        with patch("intelligence.discover_current_affairs_candidates", side_effect=Exception("Catastrophic wire failure")):
            ca_results = engine.discover_current_affairs_candidates(self.db, limit=3)
            self.assertEqual(ca_results, [])

        # Historical discovery continues running normally
        with patch.object(engine, "is_duplicate", return_value=False), \
             patch("engines.topic_discovery.AI_PROVIDER_AVAILABLE", False):
            hist_results = engine.discover_topics(self.db, limit=1, profile=HISTORICAL_DISCOVERY_PROFILE)
            self.assertGreaterEqual(len(hist_results), 1)
            self.assertIn(hist_results[0].category, [c.value for c in HistoricalCategory])


if __name__ == "__main__":
    unittest.main()
