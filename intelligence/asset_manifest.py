"""
Phase 5: Beat-Level Visual Evidence Matching, Edit Decision Planning & Production Asset Manifest.
================================================================================================
Bridges verified factual intelligence (EventCard), journalistic script beats (ScriptDocument),
and retrieved visual candidates (VisualEvidencePlan) into a deterministic, machine-readable
ProductionAssetManifest.

Core Invariants:
  - 100% Cloud Autonomous & Headless: Zero browser or GUI dependencies.
  - Zero Shorts Rendered / Zero FFmpeg execution: Planning & manifest generation ONLY.
  - Zero YouTube Uploads.
  - SFX Remains Permanently Disabled.
  - Strict Claim-to-Visual Grounding & Provenance Tracking.
  - Anti-Repetition Visual Reuse Control.
  - Hard Geographic Gating & Authenticity Preservation (Stock is NEVER event-specific).
  - Explicit Licensing Eligibility Classification.
"""

import json
import logging
import math
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any

from intelligence.event_card import EventCard
from intelligence.journalistic_script import ScriptDocument, ScriptBeat
from intelligence.visual_models import (
    BeatVisualPlan,
    VisualAuthenticity,
    VisualCoverageType,
    VisualEvidenceCandidate,
    VisualEvidencePlan,
    VisualLicensingStatus,
)
from intelligence.visual_sources import SafeURLValidator
from intelligence.visual_matching import VisualRelevanceScorer, KNOWN_THEATERS

logger = logging.getLogger("alamr.asset_manifest")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ManifestLicensingEligibility(str, Enum):
    """Licensing eligibility status for automated production use."""
    ELIGIBLE = "ELIGIBLE"              # Verified safe for broadcast (Public Domain, CC, Stock API)
    CONDITIONAL = "CONDITIONAL"        # Requires attribution overlay or editorial credit
    UNKNOWN = "UNKNOWN"                # Unverified; cannot be assumed safe
    RESTRICTED = "RESTRICTED"          # All rights reserved / commercial broadcast clearance required
    REJECTED = "REJECTED"              # Prohibited or unsafe for publication


class EditTransitionType(str, Enum):
    """Edit decision transition types between visual beats."""
    CUT = "CUT"                        # Direct hard cut (standard for fast current affairs)
    CROSSFADE = "CROSSFADE"            # Smooth dissolve between related footage
    HOLD = "HOLD"                      # Sustained visual continuation across contiguous beats
    REPLACE = "REPLACE"                # Alternate visual candidate replacement
    NO_VISUAL = "NO_VISUAL"            # Explicit blank / graphic placeholder (no footage)


class ManifestValidationStatus(str, Enum):
    """Quality gate validation status of a production manifest."""
    VALID = "VALID"
    INVALID = "INVALID"
    NEEDS_REVIEW = "NEEDS_REVIEW"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ManifestValidationError(ValueError):
    """Raised when an asset manifest fails quality gate validation."""
    pass


# ---------------------------------------------------------------------------
# Data Contracts
# ---------------------------------------------------------------------------

@dataclass
class ProvenanceOverlayData:
    """Standardized metadata for broadcast visual credit and provenance overlay."""
    publisher: str
    source_url: str
    media_url: str
    authenticity: str
    licensing_status: str
    eligibility: str
    event_id: str
    beat_id: str
    claim_ids: List[str] = field(default_factory=list)
    published_at: Optional[datetime] = None
    captured_at: Optional[datetime] = None
    confidence: float = 1.0
    credit_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "publisher": self.publisher,
            "source_url": self.source_url,
            "media_url": self.media_url,
            "authenticity": self.authenticity,
            "licensing_status": self.licensing_status,
            "eligibility": self.eligibility,
            "event_id": self.event_id,
            "beat_id": self.beat_id,
            "claim_ids": self.claim_ids,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "confidence": round(self.confidence, 3),
            "credit_text": self.credit_text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProvenanceOverlayData":
        def parse_dt(v):
            if not v:
                return None
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(v)
            except Exception:
                return None

        return cls(
            publisher=data.get("publisher", "Unknown Publisher"),
            source_url=data.get("source_url", ""),
            media_url=data.get("media_url", ""),
            authenticity=data.get("authenticity", VisualAuthenticity.CONTEXTUAL.value),
            licensing_status=data.get("licensing_status", VisualLicensingStatus.LICENSE_UNKNOWN.value),
            eligibility=data.get("eligibility", ManifestLicensingEligibility.UNKNOWN.value),
            event_id=data.get("event_id", ""),
            beat_id=data.get("beat_id", ""),
            claim_ids=data.get("claim_ids", []),
            published_at=parse_dt(data.get("published_at")),
            captured_at=parse_dt(data.get("captured_at")),
            confidence=float(data.get("confidence", 1.0)),
            credit_text=data.get("credit_text", ""),
        )


@dataclass
class BeatVisualAssignment:
    """Deterministic visual evidence assignment and temporal edit decision for one beat."""
    beat_id: str
    sequence: int
    text: str
    start_time: float
    end_time: float
    duration_seconds: float
    selected_visual_id: Optional[str]
    coverage_type: str
    authenticity: str
    licensing_status: str
    eligibility: str
    transition: str = EditTransitionType.CUT.value
    claim_ids: List[str] = field(default_factory=list)
    source_publisher: Optional[str] = None
    source_url: Optional[str] = None
    media_url: Optional[str] = None
    confidence: float = 1.0
    is_reused: bool = False
    reuse_count: int = 0
    selection_reason: str = ""
    provenance_overlay: Optional[ProvenanceOverlayData] = None
    alternative_visual_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "sequence": self.sequence,
            "text": self.text,
            "start_time": round(self.start_time, 2),
            "end_time": round(self.end_time, 2),
            "duration_seconds": round(self.duration_seconds, 2),
            "selected_visual_id": self.selected_visual_id,
            "coverage_type": self.coverage_type,
            "authenticity": self.authenticity,
            "licensing_status": self.licensing_status,
            "eligibility": self.eligibility,
            "transition": self.transition,
            "claim_ids": self.claim_ids,
            "source_publisher": self.source_publisher,
            "source_url": self.source_url,
            "media_url": self.media_url,
            "confidence": round(self.confidence, 3),
            "is_reused": self.is_reused,
            "reuse_count": self.reuse_count,
            "selection_reason": self.selection_reason,
            "provenance_overlay": self.provenance_overlay.to_dict() if self.provenance_overlay else None,
            "alternative_visual_ids": self.alternative_visual_ids,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BeatVisualAssignment":
        prov = None
        if data.get("provenance_overlay"):
            prov = ProvenanceOverlayData.from_dict(data["provenance_overlay"])

        return cls(
            beat_id=data.get("beat_id", ""),
            sequence=int(data.get("sequence", 0)),
            text=data.get("text", ""),
            start_time=float(data.get("start_time", 0.0)),
            end_time=float(data.get("end_time", 0.0)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            selected_visual_id=data.get("selected_visual_id"),
            coverage_type=data.get("coverage_type", VisualCoverageType.NO_VISUAL.value),
            authenticity=data.get("authenticity", VisualAuthenticity.CONTEXTUAL.value),
            licensing_status=data.get("licensing_status", VisualLicensingStatus.LICENSE_UNKNOWN.value),
            eligibility=data.get("eligibility", ManifestLicensingEligibility.UNKNOWN.value),
            transition=data.get("transition", EditTransitionType.CUT.value),
            claim_ids=data.get("claim_ids", []),
            source_publisher=data.get("source_publisher"),
            source_url=data.get("source_url"),
            media_url=data.get("media_url"),
            confidence=float(data.get("confidence", 1.0)),
            is_reused=bool(data.get("is_reused", False)),
            reuse_count=int(data.get("reuse_count", 0)),
            selection_reason=data.get("selection_reason", ""),
            provenance_overlay=prov,
            alternative_visual_ids=data.get("alternative_visual_ids", []),
        )


@dataclass
class ManifestCoverageMetrics:
    """Comprehensive editorial and licensing metrics for a production asset manifest."""
    total_beats: int = 0
    direct_evidence_beats: int = 0
    related_evidence_beats: int = 0
    contextual_beats: int = 0
    no_visual_beats: int = 0
    direct_evidence_ratio: float = 0.0
    related_evidence_ratio: float = 0.0
    contextual_ratio: float = 0.0
    no_visual_ratio: float = 0.0
    eligible_licensing_ratio: float = 0.0
    unknown_licensing_ratio: float = 0.0
    average_visual_confidence: float = 0.0
    unique_visual_sources_count: int = 0
    visual_reuse_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_beats": self.total_beats,
            "direct_evidence_beats": self.direct_evidence_beats,
            "related_evidence_beats": self.related_evidence_beats,
            "contextual_beats": self.contextual_beats,
            "no_visual_beats": self.no_visual_beats,
            "direct_evidence_ratio": round(self.direct_evidence_ratio, 3),
            "related_evidence_ratio": round(self.related_evidence_ratio, 3),
            "contextual_ratio": round(self.contextual_ratio, 3),
            "no_visual_ratio": round(self.no_visual_ratio, 3),
            "eligible_licensing_ratio": round(self.eligible_licensing_ratio, 3),
            "unknown_licensing_ratio": round(self.unknown_licensing_ratio, 3),
            "average_visual_confidence": round(self.average_visual_confidence, 3),
            "unique_visual_sources_count": self.unique_visual_sources_count,
            "visual_reuse_rate": round(self.visual_reuse_rate, 3),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ManifestCoverageMetrics":
        return cls(
            total_beats=int(data.get("total_beats", 0)),
            direct_evidence_beats=int(data.get("direct_evidence_beats", 0)),
            related_evidence_beats=int(data.get("related_evidence_beats", 0)),
            contextual_beats=int(data.get("contextual_beats", 0)),
            no_visual_beats=int(data.get("no_visual_beats", 0)),
            direct_evidence_ratio=float(data.get("direct_evidence_ratio", 0.0)),
            related_evidence_ratio=float(data.get("related_evidence_ratio", 0.0)),
            contextual_ratio=float(data.get("contextual_ratio", 0.0)),
            no_visual_ratio=float(data.get("no_visual_ratio", 0.0)),
            eligible_licensing_ratio=float(data.get("eligible_licensing_ratio", 0.0)),
            unknown_licensing_ratio=float(data.get("unknown_licensing_ratio", 0.0)),
            average_visual_confidence=float(data.get("average_visual_confidence", 0.0)),
            unique_visual_sources_count=int(data.get("unique_visual_sources_count", 0)),
            visual_reuse_rate=float(data.get("visual_reuse_rate", 0.0)),
        )


@dataclass
class ProductionAssetManifest:
    """Final, machine-readable production contract consumed by future renderers."""
    manifest_id: str
    event_id: str
    script_id: str
    total_duration_seconds: float
    beats: List[BeatVisualAssignment] = field(default_factory=list)
    metrics: ManifestCoverageMetrics = field(default_factory=ManifestCoverageMetrics)
    licensing_summary: Dict[str, int] = field(default_factory=dict)
    provenance_summary: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    rejected_candidates: List[Dict[str, Any]] = field(default_factory=list)
    validation_status: str = ManifestValidationStatus.VALID.value
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def compute_metrics(self) -> None:
        """Calculates granular coverage metrics and summaries across all beat assignments."""
        total = len(self.beats)
        self.metrics.total_beats = total

        if total == 0:
            self.total_duration_seconds = 0.0
            return

        self.total_duration_seconds = round(sum(b.duration_seconds for b in self.beats), 2)

        direct = sum(1 for b in self.beats if b.coverage_type == VisualCoverageType.DIRECT_EVIDENCE.value)
        related = sum(1 for b in self.beats if b.coverage_type == VisualCoverageType.RELATED_EVIDENCE.value)
        contextual = sum(1 for b in self.beats if b.coverage_type == VisualCoverageType.CONTEXTUAL.value)
        no_vis = sum(1 for b in self.beats if b.coverage_type == VisualCoverageType.NO_VISUAL.value)

        self.metrics.direct_evidence_beats = direct
        self.metrics.related_evidence_beats = related
        self.metrics.contextual_beats = contextual
        self.metrics.no_visual_beats = no_vis

        self.metrics.direct_evidence_ratio = round(direct / total, 3)
        self.metrics.related_evidence_ratio = round(related / total, 3)
        self.metrics.contextual_ratio = round(contextual / total, 3)
        self.metrics.no_visual_ratio = round(no_vis / total, 3)

        eligible = sum(1 for b in self.beats if b.eligibility in [
            ManifestLicensingEligibility.ELIGIBLE.value,
            ManifestLicensingEligibility.CONDITIONAL.value,
        ])
        unknown = sum(1 for b in self.beats if b.eligibility == ManifestLicensingEligibility.UNKNOWN.value)

        self.metrics.eligible_licensing_ratio = round(eligible / total, 3)
        self.metrics.unknown_licensing_ratio = round(unknown / total, 3)

        confidences = [b.confidence for b in self.beats if b.selected_visual_id]
        self.metrics.average_visual_confidence = round(
            sum(confidences) / len(confidences), 3
        ) if confidences else 0.0

        publishers = {b.source_publisher for b in self.beats if b.source_publisher}
        self.metrics.unique_visual_sources_count = len(publishers)

        reused = sum(1 for b in self.beats if b.is_reused)
        self.metrics.visual_reuse_rate = round(reused / total, 3)

        # Licensing summary
        lic_counts: Dict[str, int] = {}
        for b in self.beats:
            lic_counts[b.licensing_status] = lic_counts.get(b.licensing_status, 0) + 1
        self.licensing_summary = lic_counts

        # Provenance summary
        self.provenance_summary = {
            "publishers": list(publishers),
            "total_assigned_visuals": sum(1 for b in self.beats if b.selected_visual_id),
            "total_reused_visuals": reused,
            "unassigned_beats": no_vis,
        }

    def to_dict(self) -> Dict[str, Any]:
        self.compute_metrics()
        return {
            "manifest_id": self.manifest_id,
            "event_id": self.event_id,
            "script_id": self.script_id,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "total_duration_seconds": self.total_duration_seconds,
            "beats": [b.to_dict() for b in self.beats],
            "metrics": self.metrics.to_dict(),
            "licensing_summary": self.licensing_summary,
            "provenance_summary": self.provenance_summary,
            "warnings": self.warnings,
            "rejected_candidates": self.rejected_candidates,
            "validation_status": self.validation_status,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProductionAssetManifest":
        dt = None
        if data.get("generated_at"):
            try:
                dt = datetime.fromisoformat(data["generated_at"])
            except Exception:
                dt = datetime.now(timezone.utc)

        beats = [BeatVisualAssignment.from_dict(b) for b in data.get("beats", [])]
        metrics = ManifestCoverageMetrics.from_dict(data.get("metrics", {}))

        manifest = cls(
            manifest_id=data.get("manifest_id", f"man_{uuid.uuid4().hex[:12]}"),
            event_id=data.get("event_id", "unknown_event"),
            script_id=data.get("script_id", "unknown_script"),
            total_duration_seconds=float(data.get("total_duration_seconds", 0.0)),
            beats=beats,
            metrics=metrics,
            licensing_summary=data.get("licensing_summary", {}),
            provenance_summary=data.get("provenance_summary", {}),
            warnings=data.get("warnings", []),
            rejected_candidates=data.get("rejected_candidates", []),
            validation_status=data.get("validation_status", ManifestValidationStatus.VALID.value),
            generated_at=dt or datetime.now(timezone.utc),
        )
        manifest.compute_metrics()
        return manifest

    @classmethod
    def from_json(cls, json_str: str) -> "ProductionAssetManifest":
        return cls.from_dict(json.loads(json_str))


# ---------------------------------------------------------------------------
# Quality Gate Validator
# ---------------------------------------------------------------------------

class ManifestQualityGate:
    """
    Fails closed on any invalid timing, geographic violation, SSRF risk,
    fabricated metadata, or missing provenance.
    """

    @classmethod
    def validate(
        cls,
        manifest: ProductionAssetManifest,
        event_card: Optional[EventCard] = None,
        script_doc: Optional[ScriptDocument] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validates the entire ProductionAssetManifest against hard constraints.

        Returns:
            Tuple of (is_valid: bool, error_messages: List[str])
        """
        errors: List[str] = []

        if not manifest.manifest_id:
            errors.append("Manifest lacks manifest_id")

        if not manifest.event_id or manifest.event_id == "unknown_event":
            errors.append("Manifest lacks valid event_id")

        if not manifest.script_id or manifest.script_id == "unknown_script":
            errors.append("Manifest lacks valid script_id")

        # Check script document alignment
        if script_doc:
            if manifest.script_id != script_doc.script_id:
                errors.append(f"Manifest script_id '{manifest.script_id}' does not match ScriptDocument '{script_doc.script_id}'")
            if len(manifest.beats) != len(script_doc.beats):
                errors.append(f"Manifest beat count ({len(manifest.beats)}) does not match ScriptDocument beat count ({len(script_doc.beats)})")

        # Check event card alignment
        if event_card:
            card_id = getattr(event_card, "event_id", getattr(event_card, "card_id", None))
            if card_id and manifest.event_id != card_id:
                errors.append(f"Manifest event_id '{manifest.event_id}' does not match EventCard '{card_id}'")

        # Timing validation
        current_time = 0.0
        for idx, beat in enumerate(manifest.beats):
            if beat.duration_seconds <= 0:
                errors.append(f"Beat {beat.beat_id} has invalid non-positive duration: {beat.duration_seconds}")

            if beat.start_time < 0:
                errors.append(f"Beat {beat.beat_id} has negative start_time: {beat.start_time}")

            if beat.end_time <= beat.start_time:
                errors.append(f"Beat {beat.beat_id} end_time ({beat.end_time}) <= start_time ({beat.start_time})")

            # Contiguity check (allow tiny 0.05s floating point rounding)
            if abs(beat.start_time - current_time) > 0.06:
                errors.append(
                    f"Timing gap or overlap at beat {beat.beat_id} sequence {beat.sequence}: "
                    f"expected start {current_time:.2f}, got {beat.start_time:.2f}"
                )

            current_time = beat.end_time

            # Selected visual safety checks
            if beat.selected_visual_id:
                # SSRF and URL validation
                if beat.media_url:
                    safe, reason = SafeURLValidator.is_safe_url(beat.media_url)
                    if not safe:
                        errors.append(f"Beat {beat.beat_id} selected visual media_url unsafe: {reason}")
                else:
                    errors.append(f"Beat {beat.beat_id} has selected_visual_id but media_url is empty")

                # Hard Invariant: Stock footage is NEVER event-specific
                if beat.licensing_status == VisualLicensingStatus.STOCK_API_LICENSE.value or (
                    beat.source_publisher and "pexels" in beat.source_publisher.lower()
                ):
                    if beat.authenticity == VisualAuthenticity.EVENT_SPECIFIC.value:
                        errors.append(f"Beat {beat.beat_id} falsely marks stock visual as EVENT_SPECIFIC")

                # Licensing eligibility constraint
                if beat.eligibility == ManifestLicensingEligibility.REJECTED.value:
                    errors.append(f"Beat {beat.beat_id} assigns a REJECTED visual")

        is_valid = len(errors) == 0
        manifest.validation_status = ManifestValidationStatus.VALID.value if is_valid else ManifestValidationStatus.INVALID.value
        return is_valid, errors


# ---------------------------------------------------------------------------
# Asset Manifest Engine / Edit Decision Planner
# ---------------------------------------------------------------------------

class AssetManifestEngine:
    """
    Coordinates beat-level visual assignment, temporal planning, anti-repetition,
    provenance overlay preparation, and quality gate execution.
    """

    DEFAULT_WORDS_PER_SECOND = 2.3     # Standard broadcast narration rate (~138 WPM)
    MIN_BEAT_DURATION = 1.5            # Minimum duration for visual cut stability
    MAX_CONSECUTIVE_REUSE = 2          # Maximum times the exact same visual can repeat consecutively

    def __init__(
        self,
        words_per_second: float = DEFAULT_WORDS_PER_SECOND,
        min_beat_duration: float = MIN_BEAT_DURATION,
    ):
        self.words_per_second = words_per_second
        self.min_beat_duration = min_beat_duration

    def generate_manifest(
        self,
        event_card: EventCard,
        script_doc: ScriptDocument,
        visual_plan: VisualEvidencePlan,
    ) -> ProductionAssetManifest:
        """
        Compiles a verified ProductionAssetManifest connecting ScriptBeats and VisualEvidencePlan.

        Args:
            event_card: Phase 2 verified EventCard
            script_doc: Phase 3 claim-grounded ScriptDocument
            visual_plan: Phase 4 VisualEvidencePlan

        Returns:
            Validated ProductionAssetManifest
        """
        manifest_id = f"man_{uuid.uuid4().hex[:12]}"
        event_id = getattr(event_card, "event_id", getattr(event_card, "card_id", "unknown_event"))
        logger.info(f"Generating ProductionAssetManifest {manifest_id} for Event {event_id}")

        assignments: List[BeatVisualAssignment] = []
        warnings: List[str] = []
        rejected_candidates: List[Dict[str, Any]] = []

        # Index visual plans by beat_id
        plan_by_beat: Dict[str, BeatVisualPlan] = {b.beat_id: b for b in visual_plan.beat_plans}

        # Index event card claims by claim_id for grounding
        event_claims: Dict[str, Any] = {}
        if hasattr(event_card, "claims") and event_card.claims:
            for cl in event_card.claims:
                cid = getattr(cl, "claim_id", None) or (cl.get("claim_id") if isinstance(cl, dict) else None)
                if cid:
                    event_claims[cid] = cl

        current_time = 0.0
        used_visual_counts: Dict[str, int] = {}
        manifest_used_visual_ids: Set[str] = set()
        last_selected_visual_id: Optional[str] = None
        consecutive_reuse_count = 0

        for idx, beat in enumerate(script_doc.beats):
            # 1. Temporal Planning: Calculate deterministic duration from word count
            word_count = len(beat.text.strip().split())
            calculated_duration = max(self.min_beat_duration, round(word_count / self.words_per_second, 2))
            start_time = round(current_time, 2)
            end_time = round(start_time + calculated_duration, 2)
            current_time = end_time

            # 2. Visual Candidate Selection
            beat_plan = plan_by_beat.get(beat.beat_id)
            selected_cand: Optional[VisualEvidenceCandidate] = None
            selection_reason = ""
            alternative_ids: List[str] = []

            if beat_plan and beat_plan.candidate_pool:
                pool = beat_plan.candidate_pool
                alternative_ids = [c.visual_id for c in pool if c.visual_id != getattr(beat_plan.selected_candidate, "visual_id", "")]
                # Check primary candidate
                primary = beat_plan.selected_candidate
                if primary and primary.retrieval_status == "AVAILABLE":
                    # Condition A: Consecutive reuse exceeds limit -> force alternative
                    if (
                        primary.visual_id == last_selected_visual_id
                        and consecutive_reuse_count >= self.MAX_CONSECUTIVE_REUSE
                    ):
                        alt_found = None
                        for alt in pool:
                            if alt.visual_id != primary.visual_id and alt.retrieval_status == "AVAILABLE" and alt.match_score >= 0.40:
                                alt_found = alt
                                break

                        if alt_found:
                            selected_cand = alt_found
                            selection_reason = (
                                f"Selected alternative visual {alt_found.visual_id} to prevent "
                                f"excessive consecutive repetition of {primary.visual_id}"
                            )
                        else:
                            selected_cand = primary
                            selection_reason = f"Primary visual {primary.visual_id} reused (no valid alternative in pool)"
                    # Condition B: Consecutive reuse within limit allowed
                    elif primary.visual_id == last_selected_visual_id:
                        selected_cand = primary
                        selection_reason = f"Primary visual {primary.visual_id} consecutive reuse allowed"
                    # Condition C: Non-consecutive reuse (already used earlier in Short) -> prefer unused alternative
                    elif primary.visual_id in used_visual_counts:
                        unused_alt = None
                        for alt in pool:
                            if alt.visual_id not in used_visual_counts and alt.retrieval_status == "AVAILABLE" and alt.match_score >= 0.35:
                                unused_alt = alt
                                break
                        if unused_alt:
                            selected_cand = unused_alt
                            selection_reason = f"Selected fresh alternative visual {unused_alt.visual_id} to prevent intra-short duplicate"
                        else:
                            selected_cand = primary
                            selection_reason = f"Primary visual {primary.visual_id} reused (no unused alternative in pool)"
                    else:
                        selected_cand = primary
                        selection_reason = f"Top-ranked candidate {primary.visual_id} from source {primary.source_publisher}"
                else:
                    available = [c for c in pool if c.retrieval_status == "AVAILABLE"]
                    if available:
                        selected_cand = available[0]
                        selection_reason = f"Pool candidate {selected_cand.visual_id} selected"


            # 3. Licensing & Eligibility Classification
            eligibility = ManifestLicensingEligibility.UNKNOWN.value
            lic_status = VisualLicensingStatus.LICENSE_UNKNOWN.value
            authenticity = VisualAuthenticity.CONTEXTUAL.value
            coverage_type = VisualCoverageType.NO_VISUAL.value
            prov_overlay: Optional[ProvenanceOverlayData] = None

            if selected_cand:
                # Classify licensing eligibility
                lic_status = selected_cand.licensing_status
                authenticity = selected_cand.authenticity

                if lic_status in [
                    VisualLicensingStatus.PUBLIC_DOMAIN.value,
                    VisualLicensingStatus.CREATIVE_COMMONS.value,
                    VisualLicensingStatus.STOCK_API_LICENSE.value,
                    VisualLicensingStatus.LICENSE_CONFIRMED.value,
                ]:
                    eligibility = ManifestLicensingEligibility.ELIGIBLE.value
                elif lic_status == VisualLicensingStatus.RESTRICTED.value:
                    eligibility = ManifestLicensingEligibility.RESTRICTED.value
                else:
                    eligibility = ManifestLicensingEligibility.UNKNOWN.value

                # Classify coverage
                if authenticity == VisualAuthenticity.EVENT_SPECIFIC.value:
                    coverage_type = VisualCoverageType.DIRECT_EVIDENCE.value
                elif authenticity == VisualAuthenticity.EVENT_RELATED.value:
                    coverage_type = VisualCoverageType.RELATED_EVIDENCE.value
                else:
                    coverage_type = VisualCoverageType.CONTEXTUAL.value

                # Build credit text
                credit = selected_cand.provenance.get("credit") or f"Source: {selected_cand.source_publisher}"

                # Provenance overlay data for future renderers
                prov_overlay = ProvenanceOverlayData(
                    publisher=selected_cand.source_publisher,
                    source_url=selected_cand.source_url,
                    media_url=selected_cand.media_url,
                    authenticity=authenticity,
                    licensing_status=lic_status,
                    eligibility=eligibility,
                    event_id=event_id,
                    beat_id=beat.beat_id,
                    claim_ids=list(beat.claim_ids),
                    published_at=selected_cand.published_at,
                    captured_at=selected_cand.event_occurred_at,
                    confidence=selected_cand.confidence,
                    credit_text=credit,
                )

            # 4. Anti-Repetition Tracking & Reuse Metrics
            is_reused = False
            reuse_cnt = 0
            selected_vid = selected_cand.visual_id if selected_cand else None

            if selected_vid:
                prior_count = used_visual_counts.get(selected_vid, 0)
                if prior_count > 0:
                    is_reused = True
                    reuse_cnt = prior_count

                used_visual_counts[selected_vid] = prior_count + 1

                if selected_vid == last_selected_visual_id:
                    consecutive_reuse_count += 1
                else:
                    consecutive_reuse_count = 1
                last_selected_visual_id = selected_vid
            else:
                last_selected_visual_id = None
                consecutive_reuse_count = 0
                selection_reason = "No suitable visual evidence found; explicit NO_VISUAL"

            # 5. Transition Determination
            transition = EditTransitionType.CUT.value
            if not selected_vid:
                transition = EditTransitionType.NO_VISUAL.value
            elif idx > 0 and assignments and assignments[-1].selected_visual_id == selected_vid:
                transition = EditTransitionType.HOLD.value

            # 6. Assemble Beat Assignment
            assignment = BeatVisualAssignment(
                beat_id=beat.beat_id,
                sequence=idx + 1,
                text=beat.text,
                start_time=start_time,
                end_time=end_time,
                duration_seconds=calculated_duration,
                selected_visual_id=selected_vid,
                coverage_type=coverage_type,
                authenticity=authenticity,
                licensing_status=lic_status,
                eligibility=eligibility,
                transition=transition,
                claim_ids=list(beat.claim_ids),
                source_publisher=selected_cand.source_publisher if selected_cand else None,
                source_url=selected_cand.source_url if selected_cand else None,
                media_url=selected_cand.media_url if selected_cand else None,
                confidence=selected_cand.confidence if selected_cand else 1.0,
                is_reused=is_reused,
                reuse_count=reuse_cnt,
                selection_reason=selection_reason,
                provenance_overlay=prov_overlay,
                alternative_visual_ids=alternative_ids,
            )
            assignments.append(assignment)

        manifest = ProductionAssetManifest(
            manifest_id=manifest_id,
            event_id=event_id,
            script_id=script_doc.script_id,
            total_duration_seconds=round(current_time, 2),
            beats=assignments,
            warnings=warnings,
            rejected_candidates=rejected_candidates,
        )
        manifest.compute_metrics()

        # Validate with Quality Gate
        is_valid, errors = ManifestQualityGate.validate(manifest, event_card, script_doc)
        if not is_valid:
            logger.warning(f"Manifest {manifest_id} failed quality gate: {errors}")
            manifest.warnings.extend(errors)

        return manifest
