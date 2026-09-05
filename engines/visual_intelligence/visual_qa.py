"""
Extended Editorial Visual QA Gate.
Enforces measurable visual quality thresholds beyond elementary MP4 validation:
- Excessive static frames rejection (> 50% static)
- Intra-video duplicate clip rejection
- Near-duplicate clip rejection
- Generic stock footage ceiling rejection (> 35% generic)
- Insufficient motion rejection (avg motion < 0.60)
- BGM consecutive repetition rejection (> 2 consecutive)
- Voice consecutive repetition rejection (> 2 consecutive)
- Rights risk count rejection (unverified / rights uncertain assets)
- Missing mandatory evidence attribution verification
- Provenance completeness verification
"""
import logging
from typing import List, Dict, Any, Tuple, Optional
from .models import VisualCandidate, VisualContentType, RightsStatus, VisualQAResult

logger = logging.getLogger(__name__)


class VisualQAGate:
    """Editorial and visual quality inspection gate."""

    MAX_STATIC_RATIO = 0.50
    MAX_GENERIC_STOCK_RATIO = 0.35
    MIN_AVG_MOTION_SCORE = 0.60
    MAX_CONSECUTIVE_BGM = 2
    MAX_CONSECUTIVE_VOICE = 2
    MAX_RIGHTS_RISK = 0

    def audit_visual_composition(
        self,
        selected_candidates: List[VisualCandidate],
        bgm_history: Optional[List[str]] = None,
        voice_history: Optional[List[str]] = None,
        claims_present: bool = False,
        near_duplicate_pairs: Optional[List[Tuple[str, str]]] = None,
        frozen_frame_pct: float = 0.0
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """
        Performs thorough audit of the visual edit.
        Returns: (passed, failure_reasons, telemetry_metrics)
        """
        reasons: List[str] = []
        total = len(selected_candidates)
        if total == 0:
            return False, ["Visual plan contains zero assets."], {}

        # 1. Intra-video duplicate check
        urls = [c.source_url for c in selected_candidates if c.source_url]
        unique_urls = set(urls)
        dup_count = len(urls) - len(unique_urls)
        if dup_count > 0:
            reasons.append(f"Duplicate asset reuse detected within single Short ({dup_count} duplicate clips).")

        # 2. Near-duplicate check
        near_dups = near_duplicate_pairs or []
        near_dup_count = len(near_dups)
        if near_dup_count > 0:
            reasons.append(f"Near-duplicate asset collision detected ({near_dup_count} near-identical visual pairs).")

        # 3. Static ratio check
        static_count = sum(1 for c in selected_candidates if not c.is_video)
        static_ratio = static_count / total
        if static_ratio > self.MAX_STATIC_RATIO and total > 2:
            reasons.append(f"Excessive static frames: {static_ratio*100:.1f}% static exceeds {self.MAX_STATIC_RATIO*100:.1f}% ceiling.")

        # 4. Generic stock ratio check
        generic_count = sum(1 for c in selected_candidates if c.content_type in (
            VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE
        ))
        generic_ratio = generic_count / total
        if generic_ratio > self.MAX_GENERIC_STOCK_RATIO and total > 3:
            reasons.append(f"Excessive generic stock: {generic_ratio*100:.1f}% exceeds {self.MAX_GENERIC_STOCK_RATIO*100:.1f}% ceiling.")

        # 5. Motion score check
        motion_scores = [c.motion_score for c in selected_candidates]
        avg_motion = sum(motion_scores) / total
        if avg_motion < self.MIN_AVG_MOTION_SCORE and total > 2:
            reasons.append(f"Insufficient visual motion: Average motion {avg_motion:.2f} is below {self.MIN_AVG_MOTION_SCORE} threshold.")

        # 6. BGM repetition check
        bgm_rep = False
        if bgm_history and len(bgm_history) >= (self.MAX_CONSECUTIVE_BGM + 1):
            recent_bgm = bgm_history[-(self.MAX_CONSECUTIVE_BGM + 1):]
            if len(set(recent_bgm)) == 1:
                bgm_rep = True
                reasons.append(f"BGM repetition policy violation: Track '{recent_bgm[0]}' repeated {len(recent_bgm)} times consecutively.")

        # 7. Voice repetition check
        voice_rep = False
        if voice_history and len(voice_history) >= (self.MAX_CONSECUTIVE_VOICE + 1):
            recent_v = voice_history[-(self.MAX_CONSECUTIVE_VOICE + 1):]
            if len(set(recent_v)) == 1:
                voice_rep = True
                reasons.append(f"Voice repetition policy violation: Voice '{recent_v[0]}' repeated {len(recent_v)} times consecutively.")

        # 8. Rights risk check
        rights_risks = [c for c in selected_candidates if c.rights_status == RightsStatus.RIGHTS_UNCERTAIN]
        rights_risk_count = len(rights_risks)
        if rights_risk_count > self.MAX_RIGHTS_RISK:
            reasons.append(f"Rights risk violation: {rights_risk_count} assets possess unverified or uncertain legal rights.")

        # 9. Evidence attribution check
        evidence_attrib_failures = 0
        if claims_present:
            has_evidence = any(
                c.content_type in (
                    VisualContentType.SCREENSHOT_DOCUMENT,
                    VisualContentType.LIVE_EVENT_FOOTAGE,
                    VisualContentType.OFFICIAL_PUBLIC_RECORD
                )
                or (c.provenance and c.provenance.attribution_required)
                for c in selected_candidates
            )
            if not has_evidence and total > 3:
                evidence_attrib_failures = 1
                reasons.append("Missing evidence attribution: Video discusses factual claims but contains zero documented evidence assets.")

        # 10. Provenance completeness check
        complete_prov_count = sum(
            1 for c in selected_candidates
            if c.provenance and (c.provenance.publisher or c.provenance.source or c.provenance.creator) and c.provenance.license_name != "Unknown"
        )
        prov_completeness = round((complete_prov_count / total) * 100, 1) if total else 0.0

        # Frozen frames check
        if frozen_frame_pct > 15.0:
            reasons.append(f"Excessive frozen frames detected: {frozen_frame_pct:.1f}% exceeds 15% threshold.")

        passed = len(reasons) == 0
        real_count = sum(1 for c in selected_candidates if c.content_type in (
            VisualContentType.REAL_VIDEO,
            VisualContentType.LIVE_EVENT_FOOTAGE,
            VisualContentType.ARCHIVAL_VIDEO,
            VisualContentType.OFFICIAL_PUBLIC_RECORD,
            VisualContentType.SCREENSHOT_DOCUMENT,
            VisualContentType.ANIMATED_DATA_MAP,
            VisualContentType.MEME_REACTION
        ))
        real_pct = round((real_count / total) * 100, 1)

        metrics = {
            "total_shots": total,
            "static_pct": round(static_ratio * 100, 1),
            "generic_stock_pct": round(generic_ratio * 100, 1),
            "real_footage_pct": real_pct,
            "avg_motion_score": round(avg_motion, 3),
            "duplicate_clip_count": dup_count,
            "near_duplicate_count": near_dup_count,
            "rights_risk_count": rights_risk_count,
            "evidence_attribution_failures": evidence_attrib_failures,
            "frozen_frame_pct": round(frozen_frame_pct, 1),
            "bgm_repetition": bgm_rep,
            "voice_repetition": voice_rep,
            "provenance_completeness": prov_completeness,
            "passed": passed
        }

        return passed, reasons, metrics


    def audit_composition_full(
        self,
        candidates: List[VisualCandidate],
        bgm_history: Optional[List[str]] = None,
        voice_history: Optional[List[str]] = None,
        claims_present: bool = False,
        near_duplicate_pairs: Optional[List[Tuple[str, str]]] = None,
        frozen_frame_pct: float = 0.0,
        evidence_overlays_count: int = 0,
        selected_bgm: Optional[str] = None,
        selected_voice: Optional[str] = None,
    ) -> VisualQAResult:
        """Audits composition and returns a typed VisualQAResult dataclass."""
        bgm_h = list(bgm_history or [])
        if selected_bgm:
            bgm_h.append(selected_bgm)
        voice_h = list(voice_history or [])
        if selected_voice:
            voice_h.append(selected_voice)
        return self.evaluate_to_result(
            selected_candidates=candidates,
            bgm_history=bgm_h,
            voice_history=voice_h,
            claims_present=claims_present,
            near_duplicate_pairs=near_duplicate_pairs,
            frozen_frame_pct=frozen_frame_pct
        )

    def evaluate_to_result(
        self,
        selected_candidates: List[VisualCandidate],
        bgm_history: Optional[List[str]] = None,
        voice_history: Optional[List[str]] = None,
        claims_present: bool = False,
        near_duplicate_pairs: Optional[List[Tuple[str, str]]] = None,
        frozen_frame_pct: float = 0.0
    ) -> VisualQAResult:
        """Convenience method returning a structured VisualQAResult dataclass."""
        passed, reasons, metrics = self.audit_visual_composition(
            selected_candidates=selected_candidates,
            bgm_history=bgm_history,
            voice_history=voice_history,
            claims_present=claims_present,
            near_duplicate_pairs=near_duplicate_pairs,
            frozen_frame_pct=frozen_frame_pct
        )
        return VisualQAResult(
            passed=passed,
            score=metrics.get("avg_motion_score", 0.0),
            real_footage_pct=metrics.get("real_footage_pct", 0.0),
            generic_stock_pct=metrics.get("generic_stock_pct", 0.0),
            static_asset_pct=metrics.get("static_pct", 0.0),
            avg_motion_score=metrics.get("avg_motion_score", 0.0),
            duplicate_clip_count=metrics.get("duplicate_clip_count", 0),
            near_duplicate_count=metrics.get("near_duplicate_count", 0),
            rights_risk_count=metrics.get("rights_risk_count", 0),
            evidence_attribution_failures=metrics.get("evidence_attribution_failures", 0),
            frozen_frame_pct=metrics.get("frozen_frame_pct", 0.0),
            bgm_repetition=metrics.get("bgm_repetition", False),
            voice_repetition=metrics.get("voice_repetition", False),
            provenance_completeness=metrics.get("provenance_completeness", 0.0),
            failure_reasons=reasons,
            telemetry=metrics
        )
