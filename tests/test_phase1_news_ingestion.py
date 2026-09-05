"""
Phase 1 News Ingestion and Article Normalization Test Suite.
Verifies all 18 required contracts:
1. Valid RSS article ingestion
2. Multiple RSS sources
3. Duplicate URL prevention
4. UTC timestamp normalization
5. Timestamp with timezone offset
6. Missing timestamp handling
7. Malformed timestamp handling
8. Future timestamp handling
9. 24-hour freshness classification
10. Older article classification
11. Article extraction success
12. Article extraction failure
13. One failed source does not kill the entire ingestion run
14. GDELT adapter failure handling
15. Historical trivia fallback is NOT used by current-affairs production mode
16. Curated historical seeds are not selected when live current-affairs discovery is active
17. No fabricated article content
18. Database persistence idempotency
"""
import sys
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.database import init_db, SessionLocal
from core.models import ArticleRecord, Topic
from core.discovery_profile import DiscoveryProfile, ProfileType
from intelligence.freshness import (
    FreshnessTier,
    normalize_timestamp,
    classify_freshness,
    calculate_freshness_score,
)
from intelligence.scoring import SourceType, classify_source, calculate_composite_score
from intelligence.deduplication import normalize_url, URLDeduplicator
from sources.rss_sources import RSSFeedSource
from sources.extractor import ArticleExtractor
from sources.gdelt_adapter import GDELTAdapter
from sources.news_ingestion import NewsIngestionService, NormalizedArticle
from engines.topic_discovery import TopicDiscoveryEngine


from core.models import Base, ArticleRecord, Topic


class TestPhase1NewsIngestion(unittest.TestCase):

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        self.engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    # 1. Valid RSS article ingestion
    def test_01_valid_rss_article_ingestion(self):
        service = NewsIngestionService(enable_gdelt=False)
        feed_source = RSSFeedSource(
            name="Mock Global News",
            url="http://mock.test/rss.xml",
            source_type=SourceType.ESTABLISHED_NEWS,
            default_category="Geopolitics"
        )

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_entry = MagicMock()
        mock_entry.link = "https://reuters.com/world/treaty-signed-2026"
        mock_entry.title = "Nations Sign Comprehensive Security Accord"
        mock_entry.summary = "Diplomats from 12 countries signed the agreement."
        mock_entry.author = "Jane Reporter"
        mock_entry.published_parsed = (2026, 9, 5, 6, 0, 0, 5, 248, 0)
        mock_feed.entries = [mock_entry]

        with patch("feedparser.parse", return_value=mock_feed):
            raw_items = service.parse_rss_feed(feed_source, limit=10)

        self.assertEqual(len(raw_items), 1)
        self.assertEqual(raw_items[0]["title"], "Nations Sign Comprehensive Security Accord")
        self.assertEqual(raw_items[0]["source_name"], "Mock Global News")
        self.assertEqual(raw_items[0]["author"], "Jane Reporter")

        normalized = service.normalize_article_data(raw_items[0])
        self.assertIsNotNone(normalized)
        self.assertIn("reuters.com/world/treaty-signed-2026", normalized.normalized_url)
        self.assertEqual(normalized.source_type, SourceType.ESTABLISHED_NEWS.value)

    # 2. Multiple RSS sources
    def test_02_multiple_rss_sources(self):
        src1 = RSSFeedSource(name="Reuters", url="http://reuters.mock/rss", source_type=SourceType.ESTABLISHED_NEWS, default_category="Geopolitics")
        src2 = RSSFeedSource(name="AP News", url="http://ap.mock/rss", source_type=SourceType.ESTABLISHED_NEWS, default_category="Geopolitics")
        src3 = RSSFeedSource(name="Defense News", url="http://defense.mock/rss", source_type=SourceType.SPECIALIST_DEFENSE, default_category="Defense")

        service = NewsIngestionService(rss_sources=[src1, src2, src3], enable_gdelt=False)

        def mock_parse(url):
            m = MagicMock()
            m.bozo = False
            entry = MagicMock()
            entry.link = f"{url}/article-1"
            entry.title = f"Headline from {url}"
            entry.summary = "Summary text"
            entry.published_parsed = (2026, 9, 5, 7, 0, 0, 5, 248, 0)
            m.entries = [entry]
            return m

        with patch("feedparser.parse", side_effect=mock_parse):
            articles = service.ingest_live_news(db=None)

        self.assertEqual(len(articles), 3)
        sources_found = {a.source_name for a in articles}
        self.assertEqual(sources_found, {"Reuters", "AP News", "Defense News"})

    # 3. Duplicate URL prevention
    def test_03_duplicate_url_prevention(self):
        dedup = URLDeduplicator()
        base_url = "https://www.reuters.com/world/peace-talks-begin/"
        url_with_tracking = "https://reuters.com/world/peace-talks-begin?utm_source=twitter&utm_medium=social&ref=123"

        # Normalized URLs must be identical
        norm1 = normalize_url(base_url)
        norm2 = normalize_url(url_with_tracking)
        self.assertEqual(norm1, norm2)

        # Root trailing slash vs without trailing slash must be identical
        self.assertEqual(normalize_url("https://reuters.com/"), normalize_url("https://reuters.com"))
        # Default port stripping
        self.assertEqual(normalize_url("http://reuters.com:80/world"), normalize_url("http://reuters.com/world"))

        # First visit should not be duplicate
        self.assertFalse(dedup.is_duplicate(base_url))
        dedup.mark_seen(base_url)

        # Second visit with tracking parameters must be detected as duplicate
        self.assertTrue(dedup.is_duplicate(url_with_tracking))

    # 4. UTC timestamp normalization (ISO, string, numeric epoch, millisecond)
    def test_04_utc_timestamp_normalization(self):
        ref_now = datetime(2026, 9, 5, 12, 0, 0)
        raw_utc = "2026-09-05T08:30:00Z"
        normalized = normalize_timestamp(raw_utc, now_utc=ref_now)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized.year, 2026)
        self.assertEqual(normalized.month, 9)
        self.assertEqual(normalized.day, 5)
        self.assertEqual(normalized.hour, 8)
        self.assertEqual(normalized.minute, 30)

        # Numeric Unix seconds
        norm_epoch_sec = normalize_timestamp(1725528000, now_utc=ref_now)
        self.assertIsNotNone(norm_epoch_sec)

        # Numeric Unix milliseconds (13 digits)
        norm_epoch_ms = normalize_timestamp(1725528000000, now_utc=ref_now)
        self.assertIsNotNone(norm_epoch_ms)
        self.assertEqual(norm_epoch_sec, norm_epoch_ms)

        # String-formatted Unix epoch
        norm_str_epoch = normalize_timestamp("1725528000", now_utc=ref_now)
        self.assertIsNotNone(norm_str_epoch)
        self.assertEqual(norm_str_epoch, norm_epoch_sec)

        # GDELT 14-digit integer
        norm_gdelt = normalize_timestamp(20260905083000, now_utc=ref_now)
        self.assertIsNotNone(norm_gdelt)
        self.assertEqual(norm_gdelt.hour, 8)

    # 5. Timestamp with timezone offset
    def test_05_timestamp_with_timezone_offset(self):
        ref_now = datetime(2026, 9, 5, 12, 0, 0)
        # +04:00 offset: 12:00:00+04:00 corresponds to 08:00:00 UTC
        raw_offset_plus = "2026-09-05T12:00:00+04:00"
        norm_plus = normalize_timestamp(raw_offset_plus, now_utc=ref_now)
        self.assertIsNotNone(norm_plus)
        self.assertEqual(norm_plus.hour, 8)

        # -05:00 offset: 03:00:00-05:00 corresponds to 08:00:00 UTC
        raw_offset_minus = "2026-09-05T03:00:00-05:00"
        norm_minus = normalize_timestamp(raw_offset_minus, now_utc=ref_now)
        self.assertIsNotNone(norm_minus)
        self.assertEqual(norm_minus.hour, 8)

    # 6. Missing timestamp handling
    def test_06_missing_timestamp_handling(self):
        self.assertIsNone(normalize_timestamp(None))
        self.assertIsNone(normalize_timestamp(""))
        self.assertIsNone(normalize_timestamp("   "))

        # In freshness classifier, None is classified as TIER_4 background context
        tier, age_hours, is_fresh = classify_freshness(None)
        self.assertEqual(tier, FreshnessTier.TIER_4)
        self.assertFalse(is_fresh)

    # 7. Malformed timestamp handling
    def test_07_malformed_timestamp_handling(self):
        malformed_inputs = [
            "completely-invalid-date-string",
            "2026-99-99T99:99:99",
            "not a date at all",
            1e20,  # Overflow
            "2026/invalid/format"
        ]
        for bad_input in malformed_inputs:
            result = normalize_timestamp(bad_input)
            self.assertIsNone(result, f"Failed for input: {bad_input}")

    # 8. Future timestamp handling
    def test_08_future_timestamp_handling(self):
        now_fixed = datetime(2026, 9, 5, 12, 0, 0)
        future_timestamp = now_fixed + timedelta(days=5)

        # Future timestamp should be clamped to now_fixed
        normalized = normalize_timestamp(future_timestamp, now_utc=now_fixed)
        self.assertIsNotNone(normalized)
        self.assertEqual(normalized, now_fixed)

    # 9. 24-hour freshness classification
    def test_09_24_hour_freshness_classification(self):
        ref_time = datetime(2026, 9, 5, 12, 0, 0)

        # 2 hours old -> TIER 1 (Breaking/Immediate, 0-6h)
        t_2h = ref_time - timedelta(hours=2)
        tier1, age1, is_fresh1 = classify_freshness(t_2h, reference_time=ref_time)
        self.assertEqual(tier1, FreshnessTier.TIER_1)
        self.assertTrue(is_fresh1)
        self.assertAlmostEqual(age1, 2.0, places=1)

        # 14 hours old -> TIER 2 (Daily Cycle, 6-24h)
        t_14h = ref_time - timedelta(hours=14)
        tier2, age2, is_fresh2 = classify_freshness(t_14h, reference_time=ref_time)
        self.assertEqual(tier2, FreshnessTier.TIER_2)
        self.assertTrue(is_fresh2)
        self.assertAlmostEqual(age2, 14.0, places=1)

    # 10. Older article classification
    def test_10_older_article_classification(self):
        ref_time = datetime(2026, 9, 5, 12, 0, 0)

        # 36 hours old -> TIER 3 (24-72h)
        t_36h = ref_time - timedelta(hours=36)
        tier3, _, is_fresh3 = classify_freshness(t_36h, reference_time=ref_time)
        self.assertEqual(tier3, FreshnessTier.TIER_3)
        self.assertFalse(is_fresh3)

        # 5 days old -> TIER 4 (>72h)
        t_5d = ref_time - timedelta(days=5)
        tier4, _, is_fresh4 = classify_freshness(t_5d, reference_time=ref_time)
        self.assertEqual(tier4, FreshnessTier.TIER_4)
        self.assertFalse(is_fresh4)

    # 11. Article extraction success
    def test_11_article_extraction_success(self):
        extractor = ArticleExtractor()
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>International Summit Concludes with Historic Accord</title>
            <meta name="author" content="Alex Vance">
        </head>
        <body>
            <nav><a href="/">Home</a><a href="/news">News</a></nav>
            <div class="ad-banner">Buy widgets today! 50% discount!</div>
            <article>
                <h1>International Summit Concludes with Historic Accord</h1>
                <p>Representatives from fifteen allied nations concluded an emergency summit in Geneva today, formalizing an unprecedented defensive agreement covering cyber infrastructure and maritime patrol zones.</p>
                <p>The joint declaration followed three weeks of continuous closed-door deliberations between top security advisers and foreign ministers.</p>
                <p>Implementation of the joint intelligence task force will commence on the first of next month across all participating member states.</p>
            </article>
            <footer>Copyright 2026 News Corp. Cookie policy. All rights reserved.</footer>
        </body>
        </html>
        """
        result = extractor.extract_from_html(html)
        self.assertEqual(result.extraction_status, "SUCCESS")
        self.assertEqual(result.retrieval_status, "SUCCESS")
        self.assertIsNotNone(result.text)
        self.assertIn("Geneva today", result.text)
        self.assertNotIn("Buy widgets", result.text)  # Ad stripped
        self.assertNotIn("Cookie policy", result.text)  # Boilerplate stripped

    # 12. Article extraction failure
    def test_12_article_extraction_failure(self):
        extractor = ArticleExtractor()

        # Empty HTML
        res_empty = extractor.extract_from_html("")
        self.assertEqual(res_empty.extraction_status, "EMPTY")

        # HTML with no meaningful article body
        res_boilerplate = extractor.extract_from_html("<html><body><nav>Menu</nav><div></div></body></html>")
        self.assertIn(res_boilerplate.extraction_status, ["EMPTY", "FAILED"])

        # URL network failure isolation: 404 HTTP Error
        with patch.object(extractor.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_get.return_value = mock_resp
            res_404 = extractor.extract_from_url("https://broken.news/not-found")
            self.assertEqual(res_404.extraction_status, "FAILED")
            self.assertEqual(res_404.retrieval_status, "HTTP_ERROR")

        # URL timeout
        with patch.object(extractor.session, "get", side_effect=requests.exceptions.Timeout("Connection timed out")):
            res_timeout = extractor.extract_from_url("https://slow.news/timeout")
            self.assertEqual(res_timeout.extraction_status, "FAILED")
            self.assertEqual(res_timeout.retrieval_status, "TIMEOUT")

        # URL SSL error
        with patch.object(extractor.session, "get", side_effect=requests.exceptions.SSLError("Certificate invalid")):
            res_ssl = extractor.extract_from_url("https://bad-ssl.news/article")
            self.assertEqual(res_ssl.extraction_status, "FAILED")
            self.assertEqual(res_ssl.retrieval_status, "SSL_ERROR")

        # URL blocked / forbidden (403)
        with patch.object(extractor.session, "get") as mock_get_blocked:
            mock_resp = MagicMock()
            mock_resp.status_code = 403
            mock_get_blocked.return_value = mock_resp
            res_blocked = extractor.extract_from_url("https://paywalled.news/article")
            self.assertEqual(res_blocked.extraction_status, "FAILED")
            self.assertEqual(res_blocked.retrieval_status, "BLOCKED")

    # 13. One failed source does not kill the entire ingestion run
    def test_13_one_failed_source_does_not_kill_entire_ingestion_run(self):
        broken_src = RSSFeedSource(name="Crashing Feed", url="http://crash.test", source_type=SourceType.ESTABLISHED_NEWS, default_category="Geopolitics")
        working_src = RSSFeedSource(name="Reliable Feed", url="http://ok.test", source_type=SourceType.ESTABLISHED_NEWS, default_category="Geopolitics")

        service = NewsIngestionService(rss_sources=[broken_src, working_src], enable_gdelt=False)

        def mock_parse(url):
            if "crash" in url:
                raise ConnectionResetError("Connection abruptly terminated by host")
            m = MagicMock()
            m.bozo = False
            entry = MagicMock()
            entry.link = "http://ok.test/live-event-1"
            entry.title = "Verified Geopolitical Event in Central Asia"
            entry.summary = "Borders reaffirmed peacefully."
            entry.published_parsed = (2026, 9, 5, 8, 0, 0, 5, 248, 0)
            m.entries = [entry]
            return m

        with patch("feedparser.parse", side_effect=mock_parse):
            articles = service.ingest_live_news(db=None)

        # Ingestion run should not crash and should succeed with working feed
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0].source_name, "Reliable Feed")

    # 14. GDELT adapter failure handling
    def test_14_gdelt_adapter_failure_handling(self):
        adapter = GDELTAdapter()

        # Test timeout handling
        with patch.object(adapter.session, "get", side_effect=requests.exceptions.Timeout("GDELT Down")):
            res_timeout = adapter.fetch_articles()
            self.assertEqual(res_timeout, [])

        # Test invalid JSON handling
        with patch.object(adapter.session, "get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = ValueError("Corrupt JSON payload")
            mock_get.return_value = mock_resp
            res_json_err = adapter.fetch_articles()
            self.assertEqual(res_json_err, [])

    # 15. Historical trivia fallback is NOT used by current-affairs production mode
    def test_15_historical_trivia_fallback_not_used_in_current_affairs_mode(self):
        topic_engine = TopicDiscoveryEngine()
        profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        # Mock ingestion service to simulate zero live articles returned (e.g. outage)
        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[])

        with patch("google.genai.Client") as mock_gemini:
            topics = topic_engine.discover_topics(self.db, limit=2, profile=profile)

            # Gemini historical prompt must NEVER be invoked in current-affairs mode
            mock_gemini.assert_not_called()

            # Must return empty list rather than falling back to historical trivia
            self.assertEqual(topics, [])

    # 16. Curated historical seeds are not selected when live current-affairs discovery is active/available
    def test_16_curated_historical_seeds_not_selected_in_current_affairs(self):
        topic_engine = TopicDiscoveryEngine()
        profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        # Case A: Live current-affairs discovery IS available
        mock_art = NormalizedArticle(
            article_id="art_live_test_01",
            title="Active Geopolitical Treaty Accord Signed",
            source_name="Reuters",
            url="https://reuters.com/world/active-treaty-signed",
            normalized_url="https://reuters.com/world/active-treaty-signed",
            published_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            discovered_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            freshness_tier="TIER_1",
            freshness_score=98.0,
            source_type=SourceType.ESTABLISHED_NEWS.value,
            source_tier="TIER_2_ESTABLISHED",
            source_confidence=0.85,
            composite_score=92.8,
            category="Geopolitics",
            description="Live breaking treaty."
        )
        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[mock_art])

        live_topics = topic_engine.discover_topics(self.db, limit=1, profile=profile)
        self.assertEqual(len(live_topics), 1)
        self.assertEqual(live_topics[0].title, "Active Geopolitical Treaty Accord Signed")
        self.assertEqual(live_topics[0].category, "Geopolitics")

        # Case B: When live news is unavailable and no unproduced topics exist, zero historical seeds are selected
        self.db.query(Topic).delete()
        self.db.commit()
        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[])
        empty_topics = topic_engine.discover_topics(self.db, limit=5, profile=profile)
        self.assertEqual(len(empty_topics), 0)

        # Verify no historical curated seeds were added to DB
        db_historical = self.db.query(Topic).filter(
            Topic.title.in_([
                "The Great Stink of London (1858)",
                "The 38-Minute Anglo-Zanzibar War (1896)",
                "The Boston Molasses Flood of 1919",
                "The Pig War of San Juan Island (1859)"
            ])
        ).all()
        self.assertEqual(len(db_historical), 0)

    # 17. No fabricated article content
    def test_17_no_fabricated_article_content(self):
        service = NewsIngestionService(enable_gdelt=False)
        raw_item = {
            "title": "Diplomatic Summit in Vienna",
            "url": "https://dw.com/vienna-summit",
            "source_name": "Deutsche Welle",
            "published_raw": "2026-09-05T08:00:00Z",
            "summary": "Officials gathered in Vienna."
        }
        # Ingestion without body extraction
        normalized = service.normalize_article_data(raw_item)
        self.assertIsNotNone(normalized)
        # article_text must remain None without fabricating text
        self.assertIsNone(normalized.article_text)
        self.assertEqual(normalized.extraction_status, "PENDING")

        # When extraction fails, article_text must remain None
        extractor = ArticleExtractor()
        res_fail = extractor.extract_from_html("")
        self.assertIsNone(res_fail.text)
        self.assertEqual(res_fail.extraction_status, "EMPTY")

    # 18. Database persistence idempotency
    def test_18_database_persistence_and_idempotency(self):
        service = NewsIngestionService(enable_gdelt=False)
        art = NormalizedArticle(
            article_id="art_test_idempotent_01",
            title="Idempotency Test Article Title",
            source_name="Reuters",
            url="https://reuters.com/world/idempotency-test-unique",
            normalized_url="https://reuters.com/world/idempotency-test-unique",
            published_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            discovered_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            freshness_tier="TIER_1",
            freshness_score=95.0,
            source_type=SourceType.ESTABLISHED_NEWS.value,
            source_tier="TIER_2_ESTABLISHED",
            source_confidence=0.85,
            composite_score=91.0,
            description="Test summary."
        )

        # Initial write
        first_count = service.persist_articles(self.db, [art])
        self.assertEqual(first_count, 1)

        # Repeated write with exact same article
        second_count = service.persist_articles(self.db, [art])
        self.assertEqual(second_count, 0)

        # Verify only 1 record exists in DB
        records = self.db.query(ArticleRecord).filter(
            ArticleRecord.normalized_url == art.normalized_url
        ).all()
        self.assertEqual(len(records), 1)

    # 19. Stale unproduced topics (>24h old) are NOT selected by current-affairs mode
    def test_19_stale_unproduced_topics_not_selected_in_current_affairs(self):
        topic_engine = TopicDiscoveryEngine()
        profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        # Add an unproduced topic created 48 hours ago
        stale_topic = Topic(
            id="top_stale_48h",
            title="Stale Geopolitical Event From Two Days Ago",
            summary="This event happened 48 hours ago and is no longer fresh.",
            category="Geopolitics",
            score=50.0,
            status="APPROVED",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
        )
        self.db.add(stale_topic)
        self.db.commit()

        # Ingestion returns no live articles (simulating live source outage)
        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[])

        # Current affairs discovery must NOT return the 48-hour old stale topic
        topics = topic_engine.discover_topics(self.db, limit=5, profile=profile)
        self.assertEqual(len(topics), 0)

    # 20. Existing article enrichment on update
    def test_20_existing_article_enrichment_on_update(self):
        service = NewsIngestionService(enable_gdelt=False)
        base_art = NormalizedArticle(
            article_id="art_enrich_01",
            title="Initial Feed Article",
            source_name="AP News",
            url="https://apnews.com/article/enrich-test",
            normalized_url="https://apnews.com/article/enrich-test",
            published_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            discovered_utc=datetime.now(timezone.utc).replace(tzinfo=None),
            freshness_tier="TIER_1",
            freshness_score=90.0,
            source_type=SourceType.ESTABLISHED_NEWS.value,
            source_tier="TIER_2_ESTABLISHED",
            source_confidence=0.85,
            composite_score=88.0,
            article_text=None,
            extraction_status="PENDING",
            author=None
        )
        service.persist_articles(self.db, [base_art])

        # Re-persist with extracted body text and author
        enriched_art = NormalizedArticle(
            article_id="art_enrich_01_updated",
            title="Initial Feed Article",
            source_name="AP News",
            url="https://apnews.com/article/enrich-test",
            normalized_url="https://apnews.com/article/enrich-test",
            published_utc=base_art.published_utc,
            discovered_utc=base_art.discovered_utc,
            freshness_tier="TIER_1",
            freshness_score=90.0,
            source_type=SourceType.ESTABLISHED_NEWS.value,
            source_tier="TIER_2_ESTABLISHED",
            source_confidence=0.85,
            composite_score=88.0,
            article_text="Full article text successfully extracted via Trafilatura from web page.",
            extraction_status="SUCCESS",
            author="Veteran Foreign Correspondent"
        )
        service.persist_articles(self.db, [enriched_art])

        # Verify DB record was enriched
        record = self.db.query(ArticleRecord).filter(
            ArticleRecord.normalized_url == base_art.normalized_url
        ).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.extraction_status, "SUCCESS")
        self.assertIn("Trafilatura", record.article_text)
        self.assertEqual(record.author, "Veteran Foreign Correspondent")

    # 21. ResearchEngine uses linked ArticleRecord for current-affairs topics
    def test_21_research_engine_uses_linked_article_records(self):
        from engines.research_engine import ResearchEngine
        research_engine = ResearchEngine()

        topic = Topic(
            id="top_ca_news_01",
            title="Strategic Maritime Security Pact Ratified",
            summary="Allied ministers signed the defense cooperation agreement.",
            category="Geopolitics",
            score=92.0
        )
        self.db.add(topic)

        article = ArticleRecord(
            id="art_record_01",
            topic_id="top_ca_news_01",
            title="Strategic Maritime Security Pact Ratified",
            source_name="Reuters",
            source_type="established_news",
            source_tier="TIER_2_ESTABLISHED",
            url="https://reuters.com/world/maritime-pact",
            normalized_url="https://reuters.com/world/maritime-pact",
            article_text="Ministers from seven nations formalized the naval security agreement in Brussels today. The treaty expands joint surveillance patrols across the northern maritime corridor.",
            extraction_status="SUCCESS",
            retrieval_status="SUCCESS",
            published_utc=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        self.db.add(article)
        self.db.commit()

        # Execute research
        res = research_engine.research_topic(self.db, topic)
        self.assertTrue(res["verified"])
        self.assertGreater(res["claims_count"], 0)

        # Verify sources added correspond to Reuters (the real news source), NOT Wikipedia
        from core.models import SourceRecord, ClaimRecord
        sources = self.db.query(SourceRecord).filter(SourceRecord.topic_id == topic.id).all()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_name, "Reuters")
        self.assertEqual(sources[0].source_type, "news_report")

        # Verify claims are from the article
        claims = self.db.query(ClaimRecord).filter(ClaimRecord.topic_id == topic.id).all()
        self.assertGreater(len(claims), 0)
        self.assertIn("Brussels", claims[0].claim_text)


if __name__ == "__main__":
    unittest.main()
