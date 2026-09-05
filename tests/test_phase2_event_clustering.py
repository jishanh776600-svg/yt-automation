"""
Comprehensive Unit & Integration Test Suite for Phase 2:
Semantic Event Clustering + Multi-Source Verification + Structured Event Cards.
Validates all 14+ Phase 2 specifications offline with deterministic fixtures.
"""
import unittest
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, ArticleRecord, SourceRecord, ClaimRecord
from core.discovery_profile import DiscoveryProfile, ProfileType
from sources.news_ingestion import NormalizedArticle
from intelligence.models import RawArticle, EventCluster
from intelligence.event_card import (
    EventCard, VerificationState, ClaimEvidence, ConflictRecord,
    WhoSection, WhereSection, WhenSection, TimelineEntry
)
from intelligence.verification import EventVerificationEngine, canonicalize_publisher
from intelligence.clustering import EventClusterEngine, are_articles_same_event, SemanticEmbeddingService
from intelligence.deduplication import CurrentAffairsDeduplicationEngine
from engines.topic_discovery import TopicDiscoveryEngine
from engines.research_engine import ResearchEngine


class TestPhase2EventClustering(unittest.TestCase):

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)
        self.now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    def tearDown(self):
        self.db.close()

    # 1. Paraphrased articles cluster together
    def test_01_paraphrased_articles_cluster_together(self):
        engine = EventClusterEngine(profile=self.profile)
        art1 = RawArticle(
            title="Missile strike hits commercial port in Odesa, igniting fuel storage tanks",
            summary="Emergency responders battle large blaze at the Black Sea container terminal after rocket attack.",
            url="https://reuters.com/world/odesa-port-strike",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=2)
        )
        art2 = RawArticle(
            title="Rockets were launched against the Black Sea harbor, triggering massive depot blazes",
            summary="Firefighters extinguish fires at dockside fuel tanks following coastal bombardment in Ukraine.",
            url="https://apnews.com/world/black-sea-harbor-strike",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=self.now_utc - timedelta(hours=1)
        )

        clusters = engine.cluster_articles([art1, art2])
        self.assertEqual(len(clusters), 1, "Paraphrased reports on the same harbor strike must cluster together")
        self.assertEqual(len(clusters[0].articles), 2)

    # 2. Unrelated events remain separate (e.g. Syria vs Yemen)
    def test_02_unrelated_events_remain_separate(self):
        engine = EventClusterEngine(profile=self.profile)
        art_yemen = RawArticle(
            title="Missile strike hits port facility in Yemen's Hodeidah",
            summary="Airstrikes target coastal installations controlled by Houthi forces along the Red Sea.",
            url="https://reuters.com/world/yemen-port-strike",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=2),
            countries={"yemen"}
        )
        art_syria = RawArticle(
            title="Missile strike hits military depot in Syria's Latakia",
            summary="Airstrikes target weapons storage facility near the Mediterranean coast in northwestern Syria.",
            url="https://apnews.com/world/syria-depot-strike",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=self.now_utc - timedelta(hours=2),
            countries={"syria"}
        )

        clusters = engine.cluster_articles([art_yemen, art_syria])
        self.assertEqual(len(clusters), 2, "Strikes in distinct countries (Yemen vs Syria) must remain separate events")

    # 3. Same event across Reuters/AP/BBC-style sources clusters correctly
    def test_03_same_event_across_major_wires_clusters_correctly(self):
        engine = EventClusterEngine(profile=self.profile)
        art_reuters = RawArticle(
            title="Russian warship intercepts commercial tanker in Baltic Sea",
            summary="Danish straits authorities monitor maritime boarding operation in international waters.",
            url="https://reuters.com/world/baltic-tanker-intercept",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=3),
            countries={"denmark", "russia"}
        )
        art_ap = RawArticle(
            title="Danish authorities confirm Russian shadow-fleet vessel detained in Baltic waters",
            summary="Naval patrol escort commercial vessel to harbor after inspection near Great Belt.",
            url="https://apnews.com/world/danish-shadow-fleet-detained",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=self.now_utc - timedelta(hours=2),
            countries={"denmark", "russia"}
        )
        art_bbc = RawArticle(
            title="Denmark investigates Russian-linked shadow tanker in Baltic straits",
            summary="Coast guard and maritime officials examine documentation of intercepted merchant ship.",
            url="https://bbc.com/news/world-europe-baltic-ship",
            source_domain="bbc.com",
            source_name="BBC World",
            published_at=self.now_utc - timedelta(hours=1),
            countries={"denmark", "russia"}
        )

        clusters = engine.cluster_articles([art_reuters, art_ap, art_bbc])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(len(clusters[0].articles), 3)
        self.assertEqual(clusters[0].independent_publisher_count, 3)

    # 4. Duplicate/syndicated articles do not inflate independent source count
    def test_04_syndicated_articles_do_not_inflate_independent_count(self):
        v_engine = EventVerificationEngine()
        art_original = RawArticle(
            title="Navy Intercepts Submersible in Gulf of Oman",
            summary="Guided missile destroyer seizes illicit cargo vessel carrying advanced components.",
            url="https://reuters.com/world/navy-intercepts-gulf",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=2)
        )
        art_syndicated1 = RawArticle(
            title="Navy Intercepts Submersible in Gulf of Oman",
            summary="(Reuters) — Guided missile destroyer seizes illicit cargo vessel carrying advanced components.",
            url="https://news.yahoo.com/reuters/navy-intercepts-gulf",
            source_domain="news.yahoo.com",
            source_name="Yahoo News (Reuters)",
            published_at=self.now_utc - timedelta(hours=1)
        )
        art_syndicated2 = RawArticle(
            title="Navy Intercepts Submersible in Gulf of Oman",
            summary="Reporting by Reuters: Guided missile destroyer seizes illicit cargo vessel in Gulf waters.",
            url="https://msn.com/news/navy-intercepts-gulf",
            source_domain="msn.com",
            source_name="MSN News via Reuters",
            published_at=self.now_utc - timedelta(hours=1)
        )

        analysis = v_engine.analyze_publishers([art_original, art_syndicated1, art_syndicated2])
        self.assertEqual(analysis["total_articles"], 3)
        self.assertEqual(analysis["independent_publisher_count"], 1, "Syndicated copies of Reuters must count as 1 independent publisher")

    # 5. Single credible source becomes DEVELOPING rather than automatically rejected
    def test_05_single_credible_source_becomes_developing(self):
        v_engine = EventVerificationEngine()
        art_defense = RawArticle(
            title="New Hypersonic Glide Vehicle Tested at Pacific Range",
            summary="Defense contractors successfully launched experimental test glider reaching Mach 7.",
            url="https://defensenews.com/air/hypersonic-test-pacific",
            source_domain="defensenews.com",
            source_name="Defense News",
            published_at=self.now_utc - timedelta(hours=3)
        )

        v_state, conf, conflicts, info = v_engine.evaluate_verification([art_defense])
        self.assertIn(v_state, [VerificationState.DEVELOPING, VerificationState.SINGLE_CREDIBLE_SOURCE])
        self.assertNotEqual(v_state, VerificationState.INSUFFICIENT_EVIDENCE)
        self.assertGreaterEqual(conf, 0.75)

    # 6. Multiple independent reputable sources become MULTI_SOURCE_CORROBORATED
    def test_06_multiple_independent_sources_become_corroborated(self):
        v_engine = EventVerificationEngine()
        art1 = RawArticle(
            title="Security Accord Signed at Geneva Summit",
            summary="Allied leaders finalize cooperative naval defense agreement.",
            url="https://reuters.com/world/geneva-accord",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=3)
        )
        art2 = RawArticle(
            title="Ministers Ratify Maritime Defense Framework in Geneva",
            summary="Naval pact agreed between regional powers to secure transit channels.",
            url="https://apnews.com/world/geneva-treaty-signed",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=self.now_utc - timedelta(hours=2)
        )

        v_state, conf, conflicts, info = v_engine.evaluate_verification([art1, art2])
        self.assertEqual(v_state, VerificationState.MULTI_SOURCE_CORROBORATED)
        self.assertGreaterEqual(conf, 0.85)
        self.assertEqual(info["independent_publisher_count"], 2)

    # 7. Conflicting claims are preserved
    def test_07_conflicting_claims_are_preserved(self):
        v_engine = EventVerificationEngine()
        art1 = RawArticle(
            title="Border Shootout Leaves 5 Dead Near Northern Outpost",
            summary="Authorities confirm 5 casualties occurred during morning perimeter clash.",
            url="https://reuters.com/world/border-shootout",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=3)
        )
        art2 = RawArticle(
            title="Ministry Reports 14 Casualties in Northern Frontier Clash",
            summary="Regional commanders report 14 killed after heavy border exchange.",
            url="https://aljazeera.com/news/border-clash-casualties",
            source_domain="aljazeera.com",
            source_name="Al Jazeera",
            published_at=self.now_utc - timedelta(hours=2)
        )

        v_state, conf, conflicts, info = v_engine.evaluate_verification([art1, art2])
        self.assertEqual(v_state, VerificationState.CONFLICTING_REPORTS)
        self.assertGreaterEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].topic_facet, "casualty_count")

    # 8. Missing facts remain unknown (zero hallucination)
    def test_08_missing_facts_remain_unknown(self):
        engine = EventClusterEngine(profile=self.profile)
        art = RawArticle(
            title="Unidentified Radar Contact Logged Over Northern Airspace",
            summary="Civil aviation controllers logged brief anomalous radar signal before contact faded.",
            url="https://dw.com/en/radar-contact-airspace",
            source_domain="dw.com",
            source_name="Deutsche Welle",
            published_at=self.now_utc - timedelta(hours=1)
        )
        clusters = engine.cluster_articles([art])
        card = clusters[0].to_event_card()

        # Unknown fields must remain None rather than fabricated
        self.assertIsNone(card.why)
        self.assertIsNone(card.how)
        self.assertIsNone(card.where.coordinates)

    # 9. Event timestamps are distinct from article publication timestamps
    def test_09_event_timestamps_distinct_from_publication_time(self):
        engine = EventClusterEngine(profile=self.profile)
        event_time = self.now_utc - timedelta(hours=10)
        pub_time = self.now_utc - timedelta(hours=1)

        art = RawArticle(
            title="Patrol Boat Intercept Occurred at 04:00 UTC",
            summary="Naval vessel conducted boarding at dawn.",
            url="https://apnews.com/world/patrol-boat-dawn",
            source_domain="apnews.com",
            source_name="Associated Press",
            published_at=pub_time
        )
        cluster = engine.cluster_articles([art])[0]
        cluster.event_occurred_at = event_time
        card = cluster.to_event_card()

        self.assertEqual(card.when.event_time_utc, event_time)
        self.assertEqual(card.first_seen_utc, pub_time)
        self.assertNotEqual(card.when.event_time_utc, card.first_seen_utc)

    # 10. Old events are not treated as breaking merely because a new article was published
    def test_10_old_events_not_treated_as_breaking(self):
        from intelligence.freshness import FreshnessScorer
        scorer = FreshnessScorer(breaking_hours=6.0, developing_hours=24.0, profile=self.profile)

        old_cluster = EventCluster(
            cluster_id="ev_old_01",
            canonical_title="Historical Border skirmish analysis",
            canonical_summary="A review of border skirmishes that ended two weeks ago.",
            first_published_at=self.now_utc - timedelta(days=14),
            last_published_at=self.now_utc - timedelta(hours=1)
        )
        # Event age is governed by event inception / earliest report
        score, classification = scorer.evaluate_freshness(old_cluster, reference_time=self.now_utc)
        self.assertNotEqual(classification, "BREAKING")

    # 11. Same event across multiple ingestion cycles remains deduplicated
    def test_11_same_event_across_multiple_ingestion_cycles_deduplicated(self):
        dedup = CurrentAffairsDeduplicationEngine(profile=self.profile)

        # Existing topic from previous cycle
        existing_topic = Topic(
            id="top_existing_01",
            title="Commercial Tanker Detained by Danish Authorities in Baltic",
            summary="Naval authorities escorted a foreign flagged vessel to dock for inspection.",
            category="Geopolitics",
            event_id="ev_baltic_tanker_001",
            score=90.0,
            status="APPROVED"
        )
        self.db.add(existing_topic)
        self.db.commit()

        # Incoming candidate cluster in current cycle
        new_cluster = EventCluster(
            cluster_id="ev_baltic_tanker_001",  # Same event identity
            canonical_title="Danish Navy Inspects Intercepted Baltic Tanker",
            canonical_summary="Danish authorities boarded and inspected foreign commercial vessel.",
            action_tokens={"intercept", "inspect", "military"}
        )

        is_dup, matched_title, reason = dedup.is_cluster_duplicate(new_cluster, self.db)
        self.assertTrue(is_dup)
        self.assertEqual(reason, "EXACT_EVENT_ID_MATCH")

    # 12. EventCard schema is valid and complete
    def test_12_event_card_schema_is_valid(self):
        engine = EventClusterEngine(profile=self.profile)
        art = RawArticle(
            title="Allied Destroyers Intercept Inbound Anti-Ship Missiles",
            summary="Air defense systems downed three missiles targeting commercial shipping lanes.",
            url="https://reuters.com/world/destroyers-intercept-missiles",
            source_domain="reuters.com",
            source_name="Reuters",
            published_at=self.now_utc - timedelta(hours=2)
        )
        cluster = engine.cluster_articles([art])[0]
        card = cluster.to_event_card()

        # Round-trip JSON validation
        json_str = card.to_json()
        restored = EventCard.from_json(json_str)

        self.assertEqual(restored.event_id, card.event_id)
        self.assertEqual(restored.canonical_title, card.canonical_title)
        self.assertIsInstance(restored.who, WhoSection)
        self.assertIsInstance(restored.where, WhereSection)
        self.assertIsInstance(restored.when, WhenSection)
        self.assertGreaterEqual(len(restored.claims), 1)
        self.assertGreaterEqual(len(restored.sources), 1)
        self.assertGreaterEqual(len(restored.future_footage_queries), 1)

    # 13. Claim provenance is preserved in database
    def test_13_claim_provenance_is_preserved_in_db(self):
        topic_engine = TopicDiscoveryEngine()
        profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        mock_art = NormalizedArticle(
            article_id="art_reuters_prov_01",
            title="Strategic Strait Air Defense Batteries Activated",
            source_name="Reuters",
            url="https://reuters.com/world/strait-air-defense",
            normalized_url="https://reuters.com/world/strait-air-defense",
            published_utc=self.now_utc - timedelta(hours=2),
            discovered_utc=self.now_utc,
            freshness_tier="TIER_1",
            freshness_score=95.0,
            source_type="established_news",
            source_tier="TIER_2_ESTABLISHED",
            source_confidence=0.85,
            composite_score=90.0,
            category="Geopolitics",
            description="Coastal missile batteries went on high alert following reported aerial incursions.",
            article_text="Coastal missile batteries went on high alert following reported aerial incursions. Air defense commanders verified radar contacts over the strait."
        )

        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[mock_art])
        topics = topic_engine.discover_topics(self.db, limit=1, profile=profile)
        self.assertEqual(len(topics), 1)

        # Inspect persisted ClaimRecords
        claims = self.db.query(ClaimRecord).filter(ClaimRecord.topic_id == topics[0].id).all()
        self.assertGreaterEqual(len(claims), 1)
        self.assertEqual(claims[0].publisher, "Reuters")
        self.assertEqual(claims[0].source_article_id, "art_reuters_prov_01")
        self.assertIn("https://reuters.com", claims[0].source_url)
        self.assertIsNotNone(claims[0].evidence_excerpt)

    # 14. Historical fallback remains impossible in current-affairs mode
    def test_14_historical_fallback_impossible_in_current_affairs_mode(self):
        topic_engine = TopicDiscoveryEngine()
        profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        # Live ingestion returns zero candidates (outage)
        topic_engine.ingestion_service.ingest_live_news = MagicMock(return_value=[])

        with patch("google.genai.Client") as mock_gemini:
            topics = topic_engine.discover_topics(self.db, limit=1, profile=profile)
            mock_gemini.assert_not_called()
            self.assertEqual(topics, [], "Must return empty list rather than falling back to historical trivia")

    # 15. Official confirmation state assignment
    def test_15_official_confirmation_state(self):
        v_engine = EventVerificationEngine()
        art_official = RawArticle(
            title="Ministry of Defense Confirms Maritime Escort Operation",
            summary="Official communique outlines naval escort mission in northern sea routes.",
            url="https://defense.gov/news/maritime-escort",
            source_domain="defense.gov",
            source_name="U.S. Department of Defense",
            published_at=self.now_utc - timedelta(hours=1)
        )

        v_state, conf, conflicts, info = v_engine.evaluate_verification([art_official])
        self.assertEqual(v_state, VerificationState.OFFICIAL_CONFIRMATION)
        self.assertGreaterEqual(conf, 0.90)

    # 16. ResearchEngine returns event card and provenance for Phase 2 topics
    def test_16_research_engine_returns_event_card(self):
        research_engine = ResearchEngine()

        card = EventCard(
            event_id="ev_test_res_01",
            canonical_title="Naval Task Force Deployed to Bab-el-Mandeb",
            verification_state="MULTI_SOURCE_CORROBORATED",
            confidence=0.92,
            first_seen_utc=self.now_utc - timedelta(hours=4),
            latest_seen_utc=self.now_utc - timedelta(hours=1),
            who=WhoSection(countries=["United States", "United Kingdom"]),
            what="Naval task force deployed to secure commercial shipping lanes.",
            where=WhereSection(location_name="Bab-el-Mandeb"),
            when=WhenSection(event_time_utc=self.now_utc - timedelta(hours=4)),
            claims=[
                ClaimEvidence(
                    claim_id="cl_01",
                    claim_text="Guided missile destroyers shot down three drones.",
                    publisher="Reuters",
                    source_url="https://reuters.com/drone-intercept"
                )
            ],
            sources=[{"publisher": "Reuters", "url": "https://reuters.com/drone-intercept"}]
        )

        topic = Topic(
            id="top_ev_card_test",
            title="Naval Task Force Deployed to Bab-el-Mandeb",
            summary="Naval task force deployed to secure commercial shipping lanes.",
            category="Geopolitics",
            score=92.0,
            event_id="ev_test_res_01",
            verification_state="MULTI_SOURCE_CORROBORATED",
            event_card_json=card.to_json()
        )
        self.db.add(topic)

        claim_rec = ClaimRecord(
            topic_id="top_ev_card_test",
            claim_text="Guided missile destroyers shot down three drones.",
            verification_status="VERIFIED",
            confidence=0.95,
            publisher="Reuters",
            source_url="https://reuters.com/drone-intercept",
            source_article_id="art_reuters_01",
            evidence_excerpt="Guided missile destroyers shot down three drones."
        )
        self.db.add(claim_rec)
        self.db.commit()

        result = research_engine.research_topic(self.db, topic)
        self.assertTrue(result["verified"])
        self.assertEqual(result["event_id"], "ev_test_res_01")
        self.assertIn("event_card", result)
        self.assertIn("claims_count", result)
        self.assertGreater(result["claims_count"], 0)
        self.assertEqual(result["verified_claims"][0]["source_article_id"], "art_reuters_01")


if __name__ == "__main__":
    unittest.main()