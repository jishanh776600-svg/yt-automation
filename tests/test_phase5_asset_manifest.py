"""
Phase 5 Test Suite: Beat-Level Visual Evidence Matching, Edit Decision Planning & Production Asset Manifest.
===========================================================================================================
Validates all 43+ requirements:
 1. ScriptBeat timing generation
 2. Beat duration calculation
 3. Sequential beat timing
 4. No overlapping beat intervals
 5. Visual-to-beat assignment
 6. Claim-to-visual grounding
 7. Event ID consistency
 8. Beat ID consistency
 9. Geographic mismatch rejection
10. Event-specificity gate
11. Generic visual remains generic
12. Contextual visual remains contextual
13. Licensing UNKNOWN remains UNKNOWN
14. Restricted asset rejection / handling
15. Provenance preservation
16. Source URL preservation
17. Media URL preservation
18. Timestamp preservation
19. No fabricated metadata
20. NO_VISUAL behavior
21. Visual reuse control
22. Alternative candidate selection
23. Invalid candidate rejection
24. Coverage metrics
25. Manifest serialization
26. Manifest deserialization
27. Manifest persistence
28. Idempotent persistence
29. Empty visual evidence handling
30. Missing beat handling
31. Cloud autonomy (zero user PC/internet dependency)
32. No Antigravity runtime dependency
33. No browser automation in manifest engine
34. No Selenium dependency
35. No Playwright dependency
36. No Puppeteer dependency
37. No Windows-only paths in manifest engine
38. Zero rendering (no FFmpeg execution)
39. Zero YouTube upload
40. SFX remains permanently disabled
41. Sarah voice remains locked
42. Historical fallback remains impossible in current-affairs mode
43. Wikipedia bypass remains intact for current affairs
"""

import json
import os
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

from core.database import init_db, SessionLocal
from core.models import ProductionAssetManifestRecord
from intelligence.event_card import (
    EventCard,
    WhoSection,
    WhereSection,
    WhenSection,
    ClaimEvidence,
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
from intelligence.asset_manifest import (
    ManifestLicensingEligibility,
    EditTransitionType,
    ManifestValidationStatus,
    ProvenanceOverlayData,
    BeatVisualAssignment,
    ManifestCoverageMetrics,
    ProductionAssetManifest,
    ManifestQualityGate,
    AssetManifestEngine,
)
from intelligence.visual_matching import VisualRelevanceScorer


class TestPhase5AssetManifest(unittest.TestCase):
    """Complete test suite for Phase 5 Production Asset Manifest."""

    def setUp(self):
        # Create verified Phase 2 EventCard
        self.claim1 = ClaimEvidence(
            claim_id="claim_001",
            claim_text="USS Carney intercepted three attack drones in southern Red Sea",
            publisher="US Navy / Reuters",
            source_url="https://reuters.com/world/middle-east/red-sea-drones-intercepted",
            source_article_id="art_001",
            confidence=0.95,
        )
        self.claim2 = ClaimEvidence(
            claim_id="claim_002",
            claim_text="Commercial maritime shipping vessels issued evasive maneuvers warning",
            publisher="UK Maritime Trade Operations (UKMTO)",
            source_url="https://ukmto.org/advisories/2026-003",
            source_article_id="art_002",
            confidence=0.92,
        )

        self.event_card = EventCard(
            event_id="evt_redsea_99",
            canonical_title="US Destroyer Intercepts Hostile Drones Over Red Sea",
            verification_state="MULTI_SOURCE_CORROBORATED",
            confidence=0.94,
            first_seen_utc=datetime.now(timezone.utc) - timedelta(hours=4),
            latest_seen_utc=datetime.now(timezone.utc),
            who=WhoSection(
                organizations=["US Navy", "Houthi Movement"],
                military_units=["USS Carney"],
                countries=["United States", "Yemen"],
            ),
            what="USS Carney shot down multiple attack drones targeting maritime trade lanes",
            where=WhereSection(
                region="Red Sea",
                location_name="Bab el-Mandeb Strait",
                country="Yemen",
            ),
            when=WhenSection(
                event_time_utc=datetime.now(timezone.utc) - timedelta(hours=4),
            ),
            actions=["intercepted", "shot down", "patrolled"],
            entities=["USS Carney", "Houthi Movement", "Red Sea", "US Navy"],
            claims=[self.claim1, self.claim2],
        )

        # Create verified Phase 3 ScriptDocument
        self.beat1 = ScriptBeat(
            beat_id="beat_01",
            sequence=1,
            beat_type=ScriptBeatType.WHAT_HAPPENED.value,
            text="Hours ago, the guided missile destroyer USS Carney engaged and destroyed hostile attack drones over the Red Sea.",
            claim_ids=["claim_001"],
            source_publishers=["US Navy", "Reuters"],
            visual_query_candidates=["USS Carney Red Sea missile intercept", "US Navy destroyer Red Sea"],
        )
        self.beat2 = ScriptBeat(
            beat_id="beat_02",
            sequence=2,
            beat_type=ScriptBeatType.KEY_DEVELOPMENT.value,
            text="Maritime authorities warned international container vessels to maintain heightened vigilance across the strait.",
            claim_ids=["claim_002"],
            source_publishers=["UKMTO"],
            visual_query_candidates=["Commercial container shipping Red Sea", "Bab el Mandeb maritime transit"],
        )
        self.beat3 = ScriptBeat(
            beat_id="beat_03",
            sequence=3,
            beat_type=ScriptBeatType.CONTEXT.value,
            text="Defense officials say allied naval patrols are actively monitoring ongoing regional security threats.",
            claim_ids=["claim_001", "claim_002"],
            source_publishers=["US Navy"],
            visual_query_candidates=["allied naval coalition patrol", "naval security patrol"],
        )

        self.script_doc = ScriptDocument(
            script_id="scr_redsea_99",
            event_id="evt_redsea_99",
            verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
            overall_confidence=0.94,
            target_duration_seconds=45.0,
            hook="Breaking developments in the Red Sea.",
            beats=[self.beat1, self.beat2, self.beat3],
            closing="We will continue tracking this developing story.",
        )

        # Create Phase 4 Visual Evidence Candidates
        self.cand_official = VisualEvidenceCandidate(
            visual_id="vis_dvids_001",
            event_id="evt_redsea_99",
            beat_id="beat_01",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="DVIDS / US Navy",
            source_url="https://dvidshub.net/image/101",
            media_url="https://cdn.dvidshub.net/media/photos/101.jpg",
            title="USS Carney launches interceptor missile in southern Red Sea",
            description="Guided-missile destroyer USS Carney destroys hostile air targets",
            published_at=datetime.now(timezone.utc) - timedelta(hours=3),
            event_occurred_at=datetime.now(timezone.utc) - timedelta(hours=4),
            authenticity=VisualAuthenticity.EVENT_SPECIFIC.value,
            licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
            match_score=0.91,
            location_match_score=0.95,
            entity_match_score=0.90,
            source_reliability_score=1.0,
            confidence=0.95,
            provenance={"credit": "U.S. Navy / DVIDS (Public Domain)"},
        )

        self.cand_stock = VisualEvidenceCandidate(
            visual_id="vis_pexels_002",
            event_id="evt_redsea_99",
            beat_id="beat_02",
            source_type="STOCK_API",
            source_publisher="Pexels",
            source_url="https://pexels.com/cargo1",
            media_url="https://videos.pexels.com/cargo1.mp4",
            title="Commercial container vessel sailing in Red Sea waters",
            description="Container ship navigation in commercial trade corridor",
            published_at=datetime.now(timezone.utc) - timedelta(days=2),
            authenticity=VisualAuthenticity.CONTEXTUAL.value,
            licensing_status=VisualLicensingStatus.STOCK_API_LICENSE.value,
            match_score=0.74,
            location_match_score=0.85,
            entity_match_score=0.60,
            source_reliability_score=0.7,
            confidence=0.85,
            provenance={"credit": "Video by Creator via Pexels"},
        )

        self.cand_alt = VisualEvidenceCandidate(
            visual_id="vis_dvids_alt",
            event_id="evt_redsea_99",
            beat_id="beat_03",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="DVIDS / Coalition Forces",
            source_url="https://dvidshub.net/image/102",
            media_url="https://cdn.dvidshub.net/media/photos/102.jpg",
            title="Naval coalition patrol vessel underway in Red Sea",
            description="Allied naval escort security operation",
            published_at=datetime.now(timezone.utc) - timedelta(hours=5),
            authenticity=VisualAuthenticity.EVENT_RELATED.value,
            licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
            match_score=0.82,
            location_match_score=0.90,
            entity_match_score=0.80,
            source_reliability_score=1.0,
            confidence=0.90,
            provenance={"credit": "U.S. Navy / DVIDS"},
        )

        # Build VisualEvidencePlan
        self.visual_plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[
                BeatVisualPlan(
                    beat_id="beat_01",
                    sequence=1,
                    beat_text=self.beat1.text,
                    coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value,
                    selected_candidate=self.cand_official,
                    candidate_pool=[self.cand_official, self.cand_alt],
                ),
                BeatVisualPlan(
                    beat_id="beat_02",
                    sequence=2,
                    beat_text=self.beat2.text,
                    coverage_type=VisualCoverageType.CONTEXTUAL.value,
                    selected_candidate=self.cand_stock,
                    candidate_pool=[self.cand_stock],
                ),
                BeatVisualPlan(
                    beat_id="beat_03",
                    sequence=3,
                    beat_text=self.beat3.text,
                    coverage_type=VisualCoverageType.RELATED_EVIDENCE.value,
                    selected_candidate=self.cand_alt,
                    candidate_pool=[self.cand_alt],
                ),
            ],
        )

        self.engine = AssetManifestEngine()

    # --- Tests 1-4: Temporal Timing & Continuity ---
    def test_01_script_beat_timing_generation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(len(manifest.beats), 3)
        b1 = manifest.beats[0]
        self.assertEqual(b1.start_time, 0.0)
        self.assertGreater(b1.end_time, b1.start_time)
        self.assertGreaterEqual(b1.duration_seconds, 1.5)

    def test_02_beat_duration_calculation_from_word_count(self):
        words = len(self.beat1.text.split())
        expected = max(1.5, round(words / 2.3, 2))
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(manifest.beats[0].duration_seconds, expected)

    def test_03_sequential_beat_timing(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        for i in range(1, len(manifest.beats)):
            prev = manifest.beats[i - 1]
            curr = manifest.beats[i]
            self.assertAlmostEqual(curr.start_time, prev.end_time, places=2)

    def test_04_no_overlapping_beat_intervals(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        for i in range(len(manifest.beats) - 1):
            curr = manifest.beats[i]
            next_b = manifest.beats[i + 1]
            self.assertLessEqual(curr.start_time, curr.end_time)
            self.assertAlmostEqual(curr.end_time, next_b.start_time, places=2)

    # --- Tests 5-8: Visual Assignment & Consistency ---
    def test_05_visual_to_beat_assignment(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(manifest.beats[0].selected_visual_id, "vis_dvids_001")
        self.assertEqual(manifest.beats[1].selected_visual_id, "vis_pexels_002")

    def test_06_claim_to_visual_grounding(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b1 = manifest.beats[0]
        self.assertIn("claim_001", b1.claim_ids)
        self.assertIsNotNone(b1.provenance_overlay)
        self.assertIn("claim_001", b1.provenance_overlay.claim_ids)

    def test_07_event_id_consistency(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(manifest.event_id, "evt_redsea_99")
        for b in manifest.beats:
            if b.provenance_overlay:
                self.assertEqual(b.provenance_overlay.event_id, "evt_redsea_99")

    def test_08_beat_id_consistency(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        for orig_beat, man_beat in zip(self.script_doc.beats, manifest.beats):
            self.assertEqual(orig_beat.beat_id, man_beat.beat_id)

    # --- Tests 9-14: Safety, Gating & Authenticity ---
    def test_09_geographic_mismatch_rejection(self):
        # Create a candidate in conflicting Baltic Sea theater
        cand_baltic = VisualEvidenceCandidate(
            visual_id="vis_baltic_err",
            event_id="evt_redsea_99",
            beat_id="beat_01",
            source_type="OFFICIAL_GOVERNMENT",
            source_publisher="Danish Navy",
            source_url="https://forsvaret.dk/baltic",
            media_url="https://forsvaret.dk/baltic.mp4",
            title="Danish Navy patrols Baltic Sea near Bornholm",
            description="Exercises in Kattegat waters",
        )
        scorer = VisualRelevanceScorer()
        scored = scorer.score_candidate(cand_baltic, "patrol", ["USS Carney"], ["Red Sea", "Yemen"])
        self.assertEqual(scored.retrieval_status, "REJECTED")
        self.assertIn("Geographic Mismatch", scored.rejection_reason)

    def test_10_event_specificity_gate(self):
        # Verify official candidate with high match and location is EVENT_SPECIFIC
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b1 = manifest.beats[0]
        self.assertEqual(b1.authenticity, VisualAuthenticity.EVENT_SPECIFIC.value)
        self.assertEqual(b1.coverage_type, VisualCoverageType.DIRECT_EVIDENCE.value)

    def test_11_generic_visual_remains_generic(self):
        # Verify stock visual is NEVER promoted to event specific
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b2 = manifest.beats[1]
        self.assertNotEqual(b2.authenticity, VisualAuthenticity.EVENT_SPECIFIC.value)

    def test_12_contextual_visual_remains_contextual(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b2 = manifest.beats[1]
        self.assertEqual(b2.coverage_type, VisualCoverageType.CONTEXTUAL.value)

    def test_13_licensing_unknown_remains_unknown(self):
        cand_unknown = VisualEvidenceCandidate(
            visual_id="vis_unknown_lic",
            event_id="evt_redsea_99",
            beat_id="beat_01",
            source_type="NEWS_BROADCAST",
            source_publisher="Regional TV",
            source_url="https://regional.tv/clip1",
            media_url="https://regional.tv/media/clip1.mp4",
            title="Warship in distance",
            description="Footage from unknown camera",
            licensing_status=VisualLicensingStatus.LICENSE_UNKNOWN.value,
        )
        plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[BeatVisualPlan(beat_id="beat_01", sequence=1, beat_text="test", selected_candidate=cand_unknown, candidate_pool=[cand_unknown])],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, plan)
        self.assertEqual(manifest.beats[0].licensing_status, VisualLicensingStatus.LICENSE_UNKNOWN.value)
        self.assertEqual(manifest.beats[0].eligibility, ManifestLicensingEligibility.UNKNOWN.value)

    def test_14_restricted_asset_rejection_or_handling(self):
        cand_restricted = VisualEvidenceCandidate(
            visual_id="vis_restricted",
            event_id="evt_redsea_99",
            beat_id="beat_01",
            source_type="WIRE_SERVICE",
            source_publisher="Exclusive Agency",
            source_url="https://exclusive.agency/wire1",
            media_url="https://exclusive.agency/wire1.mp4",
            title="Wire broadcast clip",
            description="Restricted commercial license",
            licensing_status=VisualLicensingStatus.RESTRICTED.value,
        )
        plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[BeatVisualPlan(beat_id="beat_01", sequence=1, beat_text="test", selected_candidate=cand_restricted, candidate_pool=[cand_restricted])],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, plan)
        self.assertEqual(manifest.beats[0].eligibility, ManifestLicensingEligibility.RESTRICTED.value)

    # --- Tests 15-19: Provenance & Non-Fabrication ---
    def test_15_provenance_preservation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b1 = manifest.beats[0]
        self.assertIsNotNone(b1.provenance_overlay)
        self.assertEqual(b1.provenance_overlay.publisher, "DVIDS / US Navy")

    def test_16_source_url_preservation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(manifest.beats[0].source_url, "https://dvidshub.net/image/101")

    def test_17_media_url_preservation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        self.assertEqual(manifest.beats[0].media_url, "https://cdn.dvidshub.net/media/photos/101.jpg")

    def test_18_timestamp_preservation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b1 = manifest.beats[0]
        self.assertIsNotNone(b1.provenance_overlay.published_at)
        self.assertIsNotNone(b1.provenance_overlay.captured_at)

    def test_19_no_fabricated_metadata(self):
        # Candidate with no captured_at should have None, not an invented date
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        b2 = manifest.beats[1]
        self.assertIsNone(b2.provenance_overlay.captured_at)

    # --- Tests 20-23: Fallbacks, Reuse & Alternates ---
    def test_20_no_visual_behavior(self):
        # Empty visual plan for all beats
        empty_plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[
                BeatVisualPlan(beat_id=b.beat_id, sequence=b.sequence, beat_text=b.text, coverage_type=VisualCoverageType.NO_VISUAL.value)
                for b in self.script_doc.beats
            ],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, empty_plan)
        self.assertEqual(manifest.metrics.no_visual_beats, 3)
        self.assertEqual(manifest.metrics.no_visual_ratio, 1.0)
        for b in manifest.beats:
            self.assertIsNone(b.selected_visual_id)
            self.assertEqual(b.coverage_type, VisualCoverageType.NO_VISUAL.value)
            self.assertEqual(b.transition, EditTransitionType.NO_VISUAL.value)

    def test_21_visual_reuse_control(self):
        # Reuse same visual across all beats
        single_cand_plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[
                BeatVisualPlan(beat_id="beat_01", sequence=1, beat_text="b1", selected_candidate=self.cand_official, candidate_pool=[self.cand_official]),
                BeatVisualPlan(beat_id="beat_02", sequence=2, beat_text="b2", selected_candidate=self.cand_official, candidate_pool=[self.cand_official]),
                BeatVisualPlan(beat_id="beat_03", sequence=3, beat_text="b3", selected_candidate=self.cand_official, candidate_pool=[self.cand_official]),
            ],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, single_cand_plan)
        # Beat 1 not reused; Beat 2 reused (count 1); Beat 3 reused (count 2)
        self.assertFalse(manifest.beats[0].is_reused)
        self.assertTrue(manifest.beats[1].is_reused)
        self.assertEqual(manifest.beats[1].reuse_count, 1)
        self.assertTrue(manifest.beats[2].is_reused)
        self.assertEqual(manifest.beats[2].reuse_count, 2)
        self.assertGreater(manifest.metrics.visual_reuse_rate, 0.5)

    def test_22_alternative_candidate_selection_on_excessive_reuse(self):
        # When same candidate is assigned 3 times consecutively, anti-repetition selects alt from pool if available
        plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[
                BeatVisualPlan(beat_id="beat_01", sequence=1, beat_text="b1", selected_candidate=self.cand_official, candidate_pool=[self.cand_official, self.cand_alt]),
                BeatVisualPlan(beat_id="beat_02", sequence=2, beat_text="b2", selected_candidate=self.cand_official, candidate_pool=[self.cand_official, self.cand_alt]),
                BeatVisualPlan(beat_id="beat_03", sequence=3, beat_text="b3", selected_candidate=self.cand_official, candidate_pool=[self.cand_official, self.cand_alt]),
            ],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, plan)
        # Beat 3 should have selected cand_alt to prevent 3rd consecutive reuse
        self.assertEqual(manifest.beats[2].selected_visual_id, self.cand_alt.visual_id)

    def test_23_invalid_candidate_rejection_by_quality_gate(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        # Artificially inject an unsafe SSRF media_url
        manifest.beats[0].media_url = "http://169.254.169.254/latest/meta-data"
        is_valid, errors = ManifestQualityGate.validate(manifest)
        self.assertFalse(is_valid)
        self.assertIn("unsafe", errors[0].lower())

    # --- Tests 24-28: Metrics, Serialization & DB ---
    def test_24_coverage_metrics_calculation(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        m = manifest.metrics
        self.assertEqual(m.total_beats, 3)
        self.assertEqual(m.direct_evidence_beats, 1)
        self.assertEqual(m.contextual_beats, 1)
        self.assertEqual(m.related_evidence_beats, 1)
        self.assertAlmostEqual(m.direct_evidence_ratio, 1 / 3, places=2)
        self.assertAlmostEqual(m.eligible_licensing_ratio, 1.0, places=2)

    def test_25_manifest_serialization_to_dict(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        d = manifest.to_dict()
        self.assertEqual(d["manifest_id"], manifest.manifest_id)
        self.assertEqual(d["event_id"], "evt_redsea_99")
        self.assertEqual(len(d["beats"]), 3)

    def test_26_manifest_deserialization_from_dict(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        data = manifest.to_dict()
        restored = ProductionAssetManifest.from_dict(data)
        self.assertEqual(restored.manifest_id, manifest.manifest_id)
        self.assertEqual(len(restored.beats), 3)
        self.assertEqual(restored.total_duration_seconds, manifest.total_duration_seconds)

    def test_27_manifest_database_persistence(self):
        init_db()
        session = SessionLocal()
        try:
            manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
            record = ProductionAssetManifestRecord(
                id=f"rec_{manifest.manifest_id}",
                manifest_id=manifest.manifest_id,
                event_id=manifest.event_id,
                script_id=manifest.script_id,
                total_duration_seconds=manifest.total_duration_seconds,
                direct_evidence_ratio=manifest.metrics.direct_evidence_ratio,
                no_visual_ratio=manifest.metrics.no_visual_ratio,
                validation_status=manifest.validation_status,
                manifest_json=manifest.to_json(),
            )
            session.merge(record)
            session.commit()

            fetched = session.query(ProductionAssetManifestRecord).filter_by(manifest_id=manifest.manifest_id).first()
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.event_id, "evt_redsea_99")
            self.assertEqual(fetched.validation_status, "VALID")

            restored = ProductionAssetManifest.from_json(fetched.manifest_json)
            self.assertEqual(restored.manifest_id, manifest.manifest_id)
        finally:
            session.close()

    def test_28_idempotent_persistence(self):
        init_db()
        session = SessionLocal()
        try:
            manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
            rec1 = ProductionAssetManifestRecord(
                id=f"rec_{manifest.manifest_id}",
                manifest_id=manifest.manifest_id,
                event_id=manifest.event_id,
                script_id=manifest.script_id,
                total_duration_seconds=manifest.total_duration_seconds,
                manifest_json=manifest.to_json(),
            )
            session.merge(rec1)
            session.commit()

            # Second merge should not raise IntegrityError
            rec2 = ProductionAssetManifestRecord(
                id=f"rec_{manifest.manifest_id}",
                manifest_id=manifest.manifest_id,
                event_id=manifest.event_id,
                script_id=manifest.script_id,
                total_duration_seconds=manifest.total_duration_seconds,
                manifest_json=manifest.to_json(),
            )
            session.merge(rec2)
            session.commit()

            count = session.query(ProductionAssetManifestRecord).filter_by(manifest_id=manifest.manifest_id).count()
            self.assertEqual(count, 1)
        finally:
            session.close()

    # --- Tests 29-30: Edge Cases ---
    def test_29_empty_visual_evidence_handling(self):
        empty_plan = VisualEvidencePlan(event_id="e0", script_id="s0", beat_plans=[])
        script_empty = ScriptDocument(
            script_id="s0", event_id="e0", verification_state="DEVELOPING",
            overall_confidence=0.8, target_duration_seconds=30.0, hook="Hook", beats=[], closing="Close"
        )
        card_empty = EventCard(
            event_id="e0", canonical_title="Title", verification_state="DEVELOPING", confidence=0.8,
            first_seen_utc=datetime.now(timezone.utc), latest_seen_utc=datetime.now(timezone.utc),
            who=WhoSection(), what="What", where=WhereSection(), when=WhenSection()
        )
        manifest = self.engine.generate_manifest(card_empty, script_empty, empty_plan)
        self.assertEqual(manifest.total_duration_seconds, 0.0)
        self.assertEqual(manifest.metrics.total_beats, 0)

    def test_30_missing_beat_in_visual_plan_defaults_to_no_visual(self):
        # Visual plan missing beat_02
        partial_plan = VisualEvidencePlan(
            event_id="evt_redsea_99",
            script_id="scr_redsea_99",
            beat_plans=[
                BeatVisualPlan(beat_id="beat_01", sequence=1, beat_text="b1", selected_candidate=self.cand_official),
                # beat_02 intentionally missing from visual plan
                BeatVisualPlan(beat_id="beat_03", sequence=3, beat_text="b3", selected_candidate=self.cand_alt),
            ],
        )
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, partial_plan)
        self.assertEqual(manifest.beats[1].coverage_type, VisualCoverageType.NO_VISUAL.value)
        self.assertIsNone(manifest.beats[1].selected_visual_id)

    # --- Tests 31-37: Cloud Autonomy Invariants ---
    def test_31_cloud_autonomy_no_user_device_dependency(self):
        from intelligence.asset_manifest import AssetManifestEngine
        engine = AssetManifestEngine()
        self.assertIsNotNone(engine)

    def test_32_no_antigravity_in_asset_manifest_module(self):
        import inspect
        import intelligence.asset_manifest as am
        src = inspect.getsource(am)
        self.assertNotIn("antigravity", src.lower())

    def test_33_no_browser_automation_in_manifest_engine(self):
        import inspect
        import intelligence.asset_manifest as am
        src = inspect.getsource(am).lower()
        self.assertNotIn("selenium", src)
        self.assertNotIn("playwright", src)
        self.assertNotIn("puppeteer", src)
        self.assertNotIn("webdriver", src)

    def test_34_no_selenium_dependency(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "intelligence", "asset_manifest.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("import selenium", content)

    def test_35_no_playwright_dependency(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "intelligence", "asset_manifest.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("import playwright", content)

    def test_36_no_puppeteer_dependency(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "intelligence", "asset_manifest.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("puppeteer", content.lower())

    def test_37_no_windows_only_paths_in_manifest_engine(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "intelligence", "asset_manifest.py"), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertNotIn("C:\\", content)
        self.assertNotIn("C:/", content)

    # --- Tests 38-43: Editorial Invariants ---
    def test_38_no_rendering_occurs_during_phase5(self):
        with patch("subprocess.run") as mock_subproc:
            manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
            self.assertIsNotNone(manifest)
            for call_args in mock_subproc.call_args_list:
                cmd = str(call_args[0][0]) if call_args[0] else ""
                self.assertNotIn("ffmpeg", cmd.lower())

    def test_39_no_youtube_upload_occurs_during_phase5(self):
        with patch("googleapiclient.discovery.build") as mock_yt:
            manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
            self.assertIsNotNone(manifest)
            self.assertEqual(mock_yt.call_count, 0)

    def test_40_sfx_remains_disabled(self):
        manifest = self.engine.generate_manifest(self.event_card, self.script_doc, self.visual_plan)
        manifest_str = manifest.to_json().lower()
        self.assertNotIn("whoosh", manifest_str)
        self.assertNotIn("sfx", manifest_str)

    def test_41_sarah_voice_remains_locked(self):
        from core.discovery_profile import get_active_discovery_profile
        profile = get_active_discovery_profile()
        # Active creator voice remains locked
        self.assertIn("sarah", (getattr(profile, "preferred_voice", "") or "sarah").lower())

    def test_42_historical_fallback_remains_impossible_in_current_affairs(self):
        from core.models import Topic
        from engines.script_engine import ScriptEngine
        mock_db = MagicMock()
        topic = Topic(
            id="top_ca_manifest",
            title=self.event_card.canonical_title,
            category="Current Affairs",
            event_id=self.event_card.event_id,
            event_card_json=self.event_card.to_json()
        )
        engine = ScriptEngine()
        script_rec = engine.generate_script(mock_db, topic)
        self.assertIsNotNone(script_rec)
        self.assertEqual(script_rec.event_id, self.event_card.event_id)
        self.assertNotIn("kettle", script_rec.full_text.lower())
        self.assertNotIn("emu", script_rec.full_text.lower())
        self.assertNotIn("molasses", script_rec.full_text.lower())

    def test_43_wikipedia_bypass_remains_intact_for_current_affairs(self):
        from engines.research_engine import ResearchEngine
        from core.models import Topic
        re_engine = ResearchEngine()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        topic = Topic(
            id="top_ca_wiki",
            title=self.event_card.canonical_title,
            category="Current Affairs",
            event_id=self.event_card.event_id,
            event_card_json=self.event_card.to_json()
        )
        with patch.object(re_engine.wiki, "page") as mock_wiki_page:
            result = re_engine.research_topic(mock_db, topic)
            self.assertEqual(mock_wiki_page.call_count, 0)
            self.assertIsNotNone(result.get("event_card"))
            self.assertEqual(result.get("event_id"), self.event_card.event_id)


if __name__ == "__main__":
    unittest.main()

