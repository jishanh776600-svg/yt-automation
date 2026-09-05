"""
Phase 4 Test Suite: Real-Event Visual Retrieval, Evidence Matching & Cloud-Native Footage Intelligence.
=====================================================================================================
Validates all Phase 4 specifications:
  - SSRF Protection (SafeURLValidator)
  - Data contracts (VisualEvidenceCandidate, BeatVisualPlan, VisualEvidencePlan)
  - Hierarchical sources (Tier 1 Official, Tier 2 Wire, Tier 3 Stock API)
  - Multidimensional matching (Entity, Action, Temporal, Location)
  - Strict Geographic Gating (Theater conflict rejection)
  - Authenticity classification (Event-Specific, Event-Related, Contextual, Generic)
  - Safe fallback & Non-Fabrication (NO_VISUAL, zero hallucination)
  - End-to-end EventCard + ScriptDocument -> VisualEvidencePlan compilation
  - Database persistence via VisualEvidenceRecord
  - Headless cloud autonomy (zero browser dependencies)
"""

import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from core.database import init_db, SessionLocal
from core.models import VisualEvidenceRecord
from intelligence.event_card import (
    EventCard,
    WhoSection,
    WhereSection,
    WhenSection,
)
from intelligence.journalistic_script import (
    ScriptDocument,
    ScriptBeat,
    ScriptBeatType,
    VerificationState,
)
from intelligence.visual_models import (
    VisualAuthenticity,
    VisualLicensingStatus,
    VisualCoverageType,
    VisualEvidenceCandidate,
    BeatVisualPlan,
    VisualEvidencePlan,
)
from intelligence.visual_sources import (
    SafeURLValidator,
    BaseVisualAdapter,
    OfficialDefenseAdapter,
    NewsWireAdapter,
    PexelsFallbackAdapter,
    VisualSourceManager,
)
from intelligence.visual_matching import VisualRelevanceScorer, KNOWN_THEATERS
from intelligence.visual_evidence import VisualEvidenceRetrievalEngine


class TestSafeURLValidator(unittest.TestCase):
    """Unit tests for SafeURLValidator enforcing SSRF protection."""

    def test_valid_https_url(self):
        safe, reason = SafeURLValidator.is_safe_url("https://images.defense.gov/photos/tanker.jpg")
        self.assertTrue(safe)
        self.assertEqual(reason, "Safe URL")

    def test_valid_http_url(self):
        safe, reason = SafeURLValidator.is_safe_url("http://reuters.com/media/clip.mp4")
        self.assertTrue(safe)

    def test_blocked_file_scheme(self):
        safe, reason = SafeURLValidator.is_safe_url("file:///etc/passwd")
        self.assertFalse(safe)
        self.assertIn("Prohibited URL scheme", reason)

    def test_blocked_ftp_scheme(self):
        safe, reason = SafeURLValidator.is_safe_url("ftp://internal.repo/asset.mp4")
        self.assertFalse(safe)
        self.assertIn("Prohibited URL scheme", reason)

    def test_blocked_gopher_scheme(self):
        safe, reason = SafeURLValidator.is_safe_url("gopher://internal.lan/1")
        self.assertFalse(safe)
        self.assertIn("Prohibited URL scheme", reason)

    def test_blocked_localhost(self):
        safe, reason = SafeURLValidator.is_safe_url("http://localhost:8080/secret.json")
        self.assertFalse(safe)
        self.assertIn("Prohibited destination host", reason)

    def test_blocked_loopback_ip(self):
        safe, reason = SafeURLValidator.is_safe_url("http://127.0.0.1/api")
        self.assertFalse(safe)

    def test_blocked_private_ip_10(self):
        safe, reason = SafeURLValidator.is_safe_url("http://10.0.0.5/stream")
        self.assertFalse(safe)
        self.assertIn("private/restricted range", reason)

    def test_blocked_private_ip_172(self):
        safe, reason = SafeURLValidator.is_safe_url("http://172.16.50.1/auth")
        self.assertFalse(safe)
        self.assertIn("private/restricted range", reason)

    def test_blocked_private_ip_192(self):
        safe, reason = SafeURLValidator.is_safe_url("https://192.168.1.100:8443/video.mp4")
        self.assertFalse(safe)
        self.assertIn("private/restricted range", reason)

    def test_blocked_cloud_metadata_ip(self):
        safe, reason = SafeURLValidator.is_safe_url("http://169.254.169.254/latest/meta-data/")
        self.assertFalse(safe)

    def test_blocked_google_metadata_host(self):
        safe, reason = SafeURLValidator.is_safe_url("http://metadata.google.internal/computeMetadata/v1/")
        self.assertFalse(safe)
        self.assertIn("Prohibited destination host", reason)

    def test_empty_or_malformed_url(self):
        safe, _ = SafeURLValidator.is_safe_url("")
        self.assertFalse(safe)
        safe, _ = SafeURLValidator.is_safe_url(None)
        self.assertFalse(safe)


class TestVisualDataContracts(unittest.TestCase):
    """Unit tests for VisualCandidate, BeatVisualPlan, and VisualEvidencePlan models."""

    def test_candidate_serialization_roundtrip(self):
        cand = VisualEvidenceCandidate(
            visual_id="vis_test_001",
            event_id="evt_123",
            beat_id="beat_1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="DVIDS",
            source_url="https://dvidshub.net/image/123",
            media_url="https://dvidshub.net/media/123.jpg",
            title="Red Sea Interception",
            description="US Navy destroyer intercepts drone over Red Sea",
            published_at=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
            authenticity=VisualAuthenticity.EVENT_SPECIFIC.value,
            licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
            match_score=0.92,
        )
        cand_dict = cand.to_dict()
        self.assertEqual(cand_dict["visual_id"], "vis_test_001")
        self.assertEqual(cand_dict["authenticity"], "EVENT_SPECIFIC")
        self.assertEqual(cand_dict["licensing_status"], "PUBLIC_DOMAIN")

        restored = VisualEvidenceCandidate.from_dict(cand_dict)
        self.assertEqual(restored.visual_id, cand.visual_id)
        self.assertEqual(restored.match_score, 0.92)
        self.assertEqual(restored.authenticity, VisualAuthenticity.EVENT_SPECIFIC.value)

    def test_beat_visual_plan_roundtrip(self):
        beat_plan = BeatVisualPlan(
            beat_id="b_01",
            sequence=1,
            beat_text="Missiles intercepted over the Red Sea.",
            coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value,
            target_query="US Navy destroyer missile interception Red Sea",
        )
        data = beat_plan.to_dict()
        self.assertEqual(data["beat_id"], "b_01")
        self.assertEqual(data["coverage_type"], "DIRECT_EVIDENCE")

        restored = BeatVisualPlan.from_dict(data)
        self.assertEqual(restored.beat_id, "b_01")
        self.assertEqual(restored.coverage_type, VisualCoverageType.DIRECT_EVIDENCE.value)

    def test_visual_evidence_plan_metrics(self):
        b1 = BeatVisualPlan(beat_id="b1", sequence=1, beat_text="Beat 1", coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value)
        b2 = BeatVisualPlan(beat_id="b2", sequence=2, beat_text="Beat 2", coverage_type=VisualCoverageType.RELATED_EVIDENCE.value)
        b3 = BeatVisualPlan(beat_id="b3", sequence=3, beat_text="Beat 3", coverage_type=VisualCoverageType.CONTEXTUAL.value)
        b4 = BeatVisualPlan(beat_id="b4", sequence=4, beat_text="Beat 4", coverage_type=VisualCoverageType.NO_VISUAL.value)

        plan = VisualEvidencePlan(
            event_id="evt_test",
            script_id="scr_test",
            beat_plans=[b1, b2, b3, b4],
        )
        plan.compute_metrics()

        self.assertEqual(plan.direct_evidence_count, 1)
        self.assertEqual(plan.related_evidence_count, 1)
        self.assertEqual(plan.contextual_count, 1)
        self.assertEqual(plan.no_visual_count, 1)
        self.assertEqual(plan.overall_evidence_ratio, 0.50)

    def test_visual_evidence_plan_json_roundtrip(self):
        b1 = BeatVisualPlan(beat_id="b1", sequence=1, beat_text="Beat 1", coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value)
        plan = VisualEvidencePlan(
            event_id="evt_test",
            script_id="scr_test",
            beat_plans=[b1],
        )
        json_str = plan.to_json()
        restored = VisualEvidencePlan.from_json(json_str)
        self.assertEqual(restored.event_id, "evt_test")
        self.assertEqual(len(restored.beat_plans), 1)

    def test_enums_completeness(self):
        self.assertIn("EVENT_SPECIFIC", [e.value for e in VisualAuthenticity])
        self.assertIn("EVENT_RELATED", [e.value for e in VisualAuthenticity])
        self.assertIn("CONTEXTUAL", [e.value for e in VisualAuthenticity])
        self.assertIn("GENERIC", [e.value for e in VisualAuthenticity])

        self.assertIn("PUBLIC_DOMAIN", [e.value for e in VisualLicensingStatus])
        self.assertIn("STOCK_API_LICENSE", [e.value for e in VisualLicensingStatus])
        self.assertIn("RESTRICTED", [e.value for e in VisualLicensingStatus])

        self.assertIn("DIRECT_EVIDENCE", [e.value for e in VisualCoverageType])
        self.assertIn("NO_VISUAL", [e.value for e in VisualCoverageType])


class TestVisualSourcesAndAdapters(unittest.TestCase):
    """Unit tests for visual source adapters, tier hierarchy, and error resilience."""

    @patch.object(OfficialDefenseAdapter, "_http_get_json")
    def test_official_defense_adapter_search_success(self, mock_get):
        mock_get.return_value = {
            "results": [
                {
                    "id": "12345",
                    "title": "Guided-missile destroyer USS Mason conducts operations",
                    "description": "USS Mason launches interceptor in Red Sea",
                    "url": "https://www.dvidshub.net/image/12345",
                    "image": "https://cdn.dvidshub.net/media/photos/12345.jpg",
                    "thumbnail": "https://cdn.dvidshub.net/media/thumbs/12345.jpg",
                    "type": "image",
                    "date_published": "2026-03-01T12:00:00Z",
                }
            ]
        }
        adapter = OfficialDefenseAdapter()
        results = adapter.search(query="USS Mason Red Sea", event_id="e1", beat_id="b1")
        self.assertEqual(len(results), 1)
        cand = results[0]
        self.assertEqual(cand.source_type, "OFFICIAL_GOVERNMENT")
        self.assertEqual(cand.licensing_status, VisualLicensingStatus.PUBLIC_DOMAIN.value)
        self.assertEqual(cand.media_url, "https://cdn.dvidshub.net/media/photos/12345.jpg")

    @patch.object(OfficialDefenseAdapter, "_http_get_json")
    def test_official_defense_adapter_http_failure_graceful(self, mock_get):
        mock_get.return_value = None
        adapter = OfficialDefenseAdapter()
        results = adapter.search(query="Destroyer operation", event_id="e1", beat_id="b1")
        self.assertEqual(results, [])

    @patch.object(PexelsFallbackAdapter, "_http_get_json")
    def test_pexels_adapter_enforces_generic_authenticity(self, mock_get):
        mock_get.return_value = {
            "videos": [
                {
                    "id": 99911,
                    "duration": 15,
                    "image": "https://images.pexels.com/videos/99911/thumb.jpg",
                    "video_files": [
                        {
                            "width": 1080,
                            "height": 1920,
                            "link": "https://videos.pexels.com/video-files/99911/1080x1920.mp4",
                        }
                    ],
                    "user": {"name": "Aerial Drone Videography"},
                }
            ]
        }
        adapter = PexelsFallbackAdapter(api_key="mock_key")
        results = adapter.search(query="ocean waves military ship", event_id="e1", beat_id="b1")
        self.assertEqual(len(results), 1)
        cand = results[0]
        self.assertEqual(cand.source_type, "STOCK_API")
        self.assertEqual(cand.authenticity, VisualAuthenticity.GENERIC.value)
        self.assertEqual(cand.licensing_status, VisualLicensingStatus.STOCK_API_LICENSE.value)

    def test_pexels_adapter_without_key_returns_empty(self):
        adapter = PexelsFallbackAdapter(api_key="")
        results = adapter.search(query="ocean waves", event_id="e1", beat_id="b1")
        self.assertEqual(results, [])

    def test_newswire_adapter_returns_empty_when_no_query(self):
        adapter = NewsWireAdapter()
        results = adapter.search(query="")
        self.assertEqual(results, [])

    def test_source_manager_deduplication_and_ssrf_filtering(self):
        mock_adapter = MagicMock()
        cand_safe = VisualEvidenceCandidate(
            visual_id="v_safe",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="US Navy",
            source_url="https://navy.mil/photo1",
            media_url="https://navy.mil/photo1.jpg",
            title="Safe Photo",
            description="Safe Description",
        )
        cand_unsafe = VisualEvidenceCandidate(
            visual_id="v_unsafe",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="US Navy",
            source_url="http://169.254.169.254/secret",
            media_url="http://169.254.169.254/secret.jpg",
            title="Unsafe Metadata Photo",
            description="SSRF target",
        )
        mock_adapter.search.return_value = [cand_safe, cand_unsafe]

        manager = VisualSourceManager(adapters=[mock_adapter])
        retrieved = manager.retrieve_candidates(query="navy operation")
        self.assertEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].visual_id, "v_safe")


class TestVisualMatchingAndGeographicGating(unittest.TestCase):
    """Unit tests for VisualRelevanceScorer including hard geographic gating."""

    def setUp(self):
        self.scorer = VisualRelevanceScorer()

    def test_geographic_gating_rejects_conflicting_theaters(self):
        event_locations = ["Red Sea", "Yemen"]
        event_entities = ["Houthi", "USS Carney"]

        cand = VisualEvidenceCandidate(
            visual_id="v_baltic",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="Danish Navy",
            source_url="https://forsvaret.dk/baltic",
            media_url="https://forsvaret.dk/media/baltic.mp4",
            title="Danish Navy patrols Baltic Sea near Bornholm",
            description="Naval exercises in Kattegat and Baltic Sea waters",
        )

        scored = self.scorer.score_candidate(
            candidate=cand,
            target_query="naval interception",
            event_entities=event_entities,
            event_locations=event_locations,
        )

        self.assertEqual(scored.retrieval_status, "REJECTED")
        self.assertEqual(scored.location_match_score, 0.0)
        self.assertIn("Geographic Mismatch", scored.rejection_reason)
        self.assertIn("baltic", scored.rejection_reason)

    def test_geographic_gating_rejects_taiwan_vs_syria(self):
        event_locations = ["Taiwan Strait"]
        event_entities = ["Taiwan Navy", "PLA"]

        cand = VisualEvidenceCandidate(
            visual_id="v_syria",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="SANA",
            source_url="https://sana.sy/strike",
            media_url="https://sana.sy/video.mp4",
            title="Airstrikes in Damascus Syria",
            description="Middle east conflict developments in Syria and Beirut",
        )

        scored = self.scorer.score_candidate(
            candidate=cand,
            target_query="naval patrol",
            event_entities=event_entities,
            event_locations=event_locations,
        )

        self.assertEqual(scored.retrieval_status, "REJECTED")
        self.assertEqual(scored.location_match_score, 0.0)

    def test_geographic_matching_accepts_correct_theater(self):
        event_locations = ["Red Sea", "Yemen"]
        event_entities = ["Houthi", "USS Carney"]

        cand = VisualEvidenceCandidate(
            visual_id="v_redsea",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="DVIDS",
            source_url="https://dvidshub.net/image/99",
            media_url="https://dvidshub.net/photos/99.jpg",
            title="USS Carney intercepts Houthi missile over southern Red Sea",
            description="Operations in Bab el-Mandeb strait off Yemen coast",
            published_at=datetime.now(timezone.utc),
        )

        scored = self.scorer.score_candidate(
            candidate=cand,
            target_query="USS Carney missile interception Red Sea",
            event_entities=event_entities,
            event_locations=event_locations,
            event_actions=["intercepted", "fired"],
            event_time=datetime.now(timezone.utc),
        )

        self.assertEqual(scored.retrieval_status, "AVAILABLE")
        self.assertGreaterEqual(scored.location_match_score, 0.7)
        self.assertGreaterEqual(scored.entity_match_score, 0.8)
        self.assertGreaterEqual(scored.match_score, 0.72)
        self.assertEqual(scored.authenticity, VisualAuthenticity.EVENT_SPECIFIC.value)

    def test_stock_footage_never_promoted_to_event_specific(self):
        cand = VisualEvidenceCandidate(
            visual_id="v_stock",
            event_id="e1",
            beat_id="b1",
            source_type="STOCK_API",
            source_publisher="Pexels",
            source_url="https://pexels.com/123",
            media_url="https://videos.pexels.com/123.mp4",
            title="USS Carney Red Sea Destroyer Intercepts Houthi Missiles",
            description="Stock representation of warship",
            published_at=datetime.now(timezone.utc),
        )

        scored = self.scorer.score_candidate(
            candidate=cand,
            target_query="USS Carney Red Sea",
            event_entities=["USS Carney", "Houthi"],
            event_locations=["Red Sea"],
        )

        self.assertNotEqual(scored.authenticity, VisualAuthenticity.EVENT_SPECIFIC.value)
        self.assertEqual(scored.authenticity, VisualAuthenticity.GENERIC.value)

    def test_score_below_minimum_threshold_is_rejected(self):
        cand = VisualEvidenceCandidate(
            visual_id="v_irrelevant",
            event_id="e1",
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="NASA",
            source_url="https://nasa.gov/mars",
            media_url="https://nasa.gov/mars.jpg",
            title="Mars Rover Explores Crater",
            description="Scientific mission on surface of Mars",
            published_at=datetime.now(timezone.utc) - timedelta(days=500),
        )

        scored = self.scorer.score_candidate(
            candidate=cand,
            target_query="USS Carney Red Sea",
            event_entities=["USS Carney"],
            event_locations=["Red Sea"],
        )

        self.assertEqual(scored.retrieval_status, "REJECTED")
        self.assertIn("below threshold", scored.rejection_reason)

    def test_temporal_scoring_decay(self):
        now = datetime.now(timezone.utc)
        score_fresh = self.scorer._compute_temporal_score(now - timedelta(hours=12), now)
        self.assertEqual(score_fresh, 1.0)

        score_3d = self.scorer._compute_temporal_score(now - timedelta(days=3), now)
        self.assertEqual(score_3d, 0.60)

        score_20d = self.scorer._compute_temporal_score(now - timedelta(days=20), now)
        self.assertEqual(score_20d, 0.35)

        score_old = self.scorer._compute_temporal_score(now - timedelta(days=60), now)
        self.assertEqual(score_old, 0.15)


class TestVisualEvidenceRetrievalEngine(unittest.TestCase):
    """End-to-end integration tests for VisualEvidenceRetrievalEngine."""

    def setUp(self):
        self.event_card = EventCard(
            event_id="card_redsea_01",
            canonical_title="Red Sea Coalition Intercepts Attack Drones",
            verification_state="CORROBORATED",
            confidence=0.92,
            first_seen_utc=datetime.now(timezone.utc) - timedelta(hours=6),
            latest_seen_utc=datetime.now(timezone.utc),
            who=WhoSection(
                organizations=["Houthi", "US Navy"],
                military_units=["USS Carney"],
                countries=["United States", "Yemen"],
            ),
            what="USS Carney intercepted hostile attack drones over the southern Red Sea",
            where=WhereSection(
                region="Red Sea",
                location_name="Bab el-Mandeb",
                country="Yemen",
            ),
            when=WhenSection(
                event_time_utc=datetime.now(timezone.utc) - timedelta(hours=6),
            ),
            actions=["intercepted", "shot down"],
            entities=["USS Carney", "Houthi", "Red Sea", "US Navy"],
        )

        beat1 = ScriptBeat(
            beat_id="b1",
            sequence=1,
            beat_type=ScriptBeatType.WHAT_HAPPENED.value,
            text="Hours ago, guided missile destroyer USS Carney intercepted multiple drones over the Red Sea.",
            visual_query_candidates=["USS Carney drone interception Red Sea", "US Navy destroyer Red Sea operations"],
            claim_ids=["claim_001"],
            source_publishers=["US Navy", "Reuters"],
        )
        beat2 = ScriptBeat(
            beat_id="b2",
            sequence=2,
            beat_type=ScriptBeatType.KEY_DEVELOPMENT.value,
            text="Maritime officials confirm international commercial shipping remains on high alert.",
            visual_query_candidates=["Red Sea commercial shipping convoy", "cargo vessel maritime security"],
            claim_ids=["claim_002"],
            source_publishers=["UKMTO"],
        )

        self.script_doc = ScriptDocument(
            script_id="scr_redsea_01",
            event_id="card_redsea_01",
            verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
            overall_confidence=0.92,
            target_duration_seconds=45.0,
            hook="Breaking developments in the Red Sea.",
            beats=[beat1, beat2],
            closing="We will monitor updates as this develops.",
        )

    def test_engine_produces_valid_evidence_plan(self):
        mock_mgr = MagicMock()
        cand1 = VisualEvidenceCandidate(
            visual_id="v_official_01",
            event_id=self.event_card.event_id,
            beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="DVIDS / US Navy",
            source_url="https://dvidshub.net/image/101",
            media_url="https://cdn.dvidshub.net/media/photos/101.jpg",
            title="USS Carney launches SM-2 interceptor in southern Red Sea",
            description="Guided-missile destroyer USS Carney intercepts hostile targets",
            published_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        cand2 = VisualEvidenceCandidate(
            visual_id="v_stock_02",
            event_id=self.event_card.event_id,
            beat_id="b2",
            source_type="STOCK_API",
            source_publisher="Pexels",
            source_url="https://pexels.com/cargo1",
            media_url="https://videos.pexels.com/cargo1.mp4",
            title="Commercial cargo vessel sailing in Red Sea shipping corridor",
            description="Container ship sailing near Red Sea maritime transit route",
            published_at=datetime.now(timezone.utc) - timedelta(days=2),
        )

        def mock_retrieve(query, **kwargs):
            if "Carney" in query or "interception" in query:
                return [cand1]
            return [cand2]

        mock_mgr.retrieve_candidates.side_effect = mock_retrieve

        engine = VisualEvidenceRetrievalEngine(source_manager=mock_mgr)
        plan = engine.generate_evidence_plan(self.event_card, self.script_doc)

        self.assertEqual(plan.event_id, self.event_card.event_id)
        self.assertEqual(plan.script_id, self.script_doc.script_id)
        self.assertEqual(len(plan.beat_plans), 2)

        # Beat 1 should have DIRECT_EVIDENCE or RELATED_EVIDENCE
        b1_plan = plan.beat_plans[0]
        self.assertIn(b1_plan.coverage_type, [VisualCoverageType.DIRECT_EVIDENCE.value, VisualCoverageType.RELATED_EVIDENCE.value])
        self.assertIsNotNone(b1_plan.selected_candidate)
        self.assertEqual(b1_plan.selected_candidate.visual_id, "v_official_01")

        # Beat 2 with stock should be CONTEXTUAL
        b2_plan = plan.beat_plans[1]
        self.assertEqual(b2_plan.coverage_type, VisualCoverageType.CONTEXTUAL.value)

    def test_engine_zero_fabrication_on_no_visual(self):
        mock_mgr = MagicMock()
        mock_mgr.retrieve_candidates.return_value = []

        engine = VisualEvidenceRetrievalEngine(source_manager=mock_mgr)
        plan = engine.generate_evidence_plan(self.event_card, self.script_doc)

        self.assertEqual(plan.direct_evidence_count, 0)
        self.assertEqual(plan.no_visual_count, 2)
        self.assertEqual(plan.overall_evidence_ratio, 0.0)

        for b in plan.beat_plans:
            self.assertEqual(b.coverage_type, VisualCoverageType.NO_VISUAL.value)
            self.assertIsNone(b.selected_candidate)

    def test_database_persistence_of_visual_evidence_record(self):
        init_db()
        session = SessionLocal()
        try:
            plan = VisualEvidencePlan(
                event_id="evt_db_test",
                script_id="scr_db_test",
                beat_plans=[
                    BeatVisualPlan(
                        beat_id="b1",
                        sequence=1,
                        beat_text="Test Beat",
                        coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value,
                    )
                ],
            )
            plan.compute_metrics()

            record = VisualEvidenceRecord(
                id="vis_rec_001",
                event_id=plan.event_id,
                script_id=plan.script_id,
                overall_evidence_ratio=plan.overall_evidence_ratio,
                direct_evidence_count=plan.direct_evidence_count,
                related_evidence_count=plan.related_evidence_count,
                contextual_count=plan.contextual_count,
                no_visual_count=plan.no_visual_count,
                plan_json=plan.to_json(),
            )
            session.merge(record)
            session.commit()

            fetched = session.query(VisualEvidenceRecord).filter_by(id="vis_rec_001").first()
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.event_id, "evt_db_test")
            self.assertEqual(fetched.direct_evidence_count, 1)

            restored_plan = VisualEvidencePlan.from_json(fetched.plan_json)
            self.assertEqual(restored_plan.script_id, "scr_db_test")
            self.assertEqual(len(restored_plan.beat_plans), 1)
        finally:
            session.close()

    def test_visual_plan_empty_beats_metrics(self):
        plan = VisualEvidencePlan(event_id="e0", script_id="s0", beat_plans=[])
        plan.compute_metrics()
        self.assertEqual(plan.overall_evidence_ratio, 0.0)
        self.assertEqual(plan.direct_evidence_count, 0)
        self.assertEqual(plan.no_visual_count, 0)

    def test_visual_source_manager_empty_adapters(self):
        mgr = VisualSourceManager(adapters=[])
        results = mgr.retrieve_candidates(query="test query")
        self.assertEqual(results, [])

    def test_action_matching_sensitivity(self):
        scorer = VisualRelevanceScorer()
        high_act = scorer._compute_action_score("missile interception launched over sea", ["interception", "launched"], "missile launch")
        low_act = scorer._compute_action_score("peaceful diplomatic signing ceremony", ["interception", "launched"], "missile launch")
        self.assertGreater(high_act, low_act)

    def test_safe_url_validator_dns_resolution_mock(self):
        with patch("socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [(2, 1, 6, "", ("10.1.2.3", 80))]
            safe, reason = SafeURLValidator.is_safe_url("http://internal-corp-service.net/api", resolve_dns=True)
            self.assertFalse(safe)
            self.assertIn("resolved to restricted IP", reason)

    def test_licensing_classification_attributes(self):
        cand_pd = VisualEvidenceCandidate(
            visual_id="v_pd", event_id="e1", beat_id="b1",
            source_type="OFFICIAL_GOVERNMENT", source_publisher="DVIDS",
            source_url="https://dvidshub.net/1", media_url="https://dvidshub.net/1.jpg",
            title="DVIDS Photo", description="DoD work",
            licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
        )
        self.assertEqual(cand_pd.licensing_status, "PUBLIC_DOMAIN")
        self.assertIn(cand_pd.licensing_status, [e.value for e in VisualLicensingStatus])


if __name__ == "__main__":
    unittest.main()

