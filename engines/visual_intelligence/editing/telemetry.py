"""
Editing Telemetry & AI Council Foundation Engine.
Collects granular, measurable directorial telemetry from completed EditingPlans.
Exposes clean structural interfaces for future AI Council comparative evaluations.
"""
import logging
from typing import List, Dict, Any, Optional
from collections import Counter

from .editing_models import (
    EditingPlan, EditingTelemetry, EditingStrategy,
    EditingDecision, EditingOutcome, EditingStyleProfile
)

logger = logging.getLogger(__name__)


class EditingTelemetryCollector:
    """Collects and aggregates directorial metrics from an EditingPlan."""

    @staticmethod
    def collect_telemetry(
        plan: EditingPlan,
        voice_id: str = "default_voice",
        bgm_track_id: str = "default_bgm",
        real_footage_pct: float = 65.0,
        generic_stock_pct: float = 20.0,
        static_asset_pct: float = 15.0,
        provenance_completeness: float = 100.0,
        occlusion_avoidances: int = 0
    ) -> EditingTelemetry:
        """
        Computes measurable metrics across the entire EditingPlan.
        """
        shots = plan.shots
        shot_count = len(shots)
        total_dur = sum(s.duration for s in shots)
        avg_dur = round(total_dur / max(1, shot_count), 2)
        variance = round(sum((s.duration - avg_dur)**2 for s in shots) / max(1, shot_count), 3)

        # Subtitle metrics
        styles_used = []
        positions_used = []
        style_seq = []
        for s in shots:
            for cue in s.subtitle_cues:
                st_val = cue.style_type.value if hasattr(cue.style_type, "value") else str(cue.style_type)
                pos_val = cue.position_type.value if hasattr(cue.position_type, "value") else str(cue.position_type)
                styles_used.append(st_val)
                positions_used.append(pos_val)
                style_seq.append(st_val)

        unique_styles = sorted(list(set(styles_used))) if styles_used else ["CLEAN"]
        unique_positions = sorted(list(set(positions_used))) if positions_used else ["BOTTOM_CENTER"]
        style_transitions = sum(1 for i in range(1, len(style_seq)) if style_seq[i] != style_seq[i-1])

        # Transition metrics
        trans_counts: Dict[str, int] = {}
        for s in shots:
            t_val = s.transition_in.transition_type.value if hasattr(s.transition_in.transition_type, "value") else str(s.transition_in.transition_type)
            trans_counts[t_val] = trans_counts.get(t_val, 0) + 1

        # Motion metrics
        motion_counts: Dict[str, int] = {}
        for s in shots:
            m_val = s.camera_motion.motion_type.value if hasattr(s.camera_motion.motion_type, "value") else str(s.camera_motion.motion_type)
            motion_counts[m_val] = motion_counts.get(m_val, 0) + 1

        # SFX metrics
        sfx_total = sum(len(s.sfx_cues) for s in shots)
        sfx_types = []
        for s in shots:
            for c in s.sfx_cues:
                arch_val = c.archetype.value if hasattr(c.archetype, "value") else str(c.archetype)
                sfx_types.append(arch_val)

        # Overlays
        evidence_count = sum(1 for s in shots if s.evidence_overlay_path)

        profile_val = plan.profile.value if hasattr(plan.profile, "value") else str(plan.profile)

        telemetry = EditingTelemetry(
            job_id=plan.job_id,
            editing_profile=profile_val,
            shot_count=shot_count,
            total_duration=round(total_dur, 2),
            avg_shot_duration=avg_dur,
            shot_duration_variance=variance,
            subtitle_styles_used=unique_styles,
            subtitle_style_transitions=style_transitions,
            subtitle_positions_used=unique_positions,
            caption_occlusion_avoidances=occlusion_avoidances,
            transitions_used=trans_counts,
            sfx_count=sfx_total,
            sfx_types_used=sorted(list(set(sfx_types))),
            camera_motions_used=motion_counts,
            bgm_track=bgm_track_id,
            voice_id=voice_id,
            real_footage_pct=real_footage_pct,
            generic_stock_pct=generic_stock_pct,
            static_asset_pct=static_asset_pct,
            evidence_overlays_count=evidence_count,
            provenance_completeness=provenance_completeness
        )
        plan.telemetry = telemetry
        return telemetry
