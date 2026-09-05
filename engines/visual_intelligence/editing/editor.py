"""
Advanced Editorial Engine for AL-AMR.
Orchestrates high-level directorial decisions across all editorial dimensions:
- Pacing & Rhythm (EditingRhythmEngine)
- Multi-Style Typography (SubtitleStyleSelector & MultiStyleSubtitleEngine)
- Dynamic Collision-Free Positioning (SubtitlePositionEngine)
- Camera Motions & Keyframes (MotionEngine)
- Pacing-Aware Transitions (TransitionEngine)
- Restrained Sound Design (SFXEngine)
- Prioritized Audio Mixing & Ducking (AudioDirector)
- Subject-Aware 9:16 Reframing (ReframingEngine)
- Full Provenance Retention & AI Council Telemetry (EditingTelemetryCollector)
"""
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from .editing_models import (
    EditingPlan, ShotEdit, SubtitleCue, SubtitleWord,
    EditingStyleProfile, MotionType, TransitionType
)
from .style_selector import SubtitleStyleSelector, EditingStyleSelector
from .position_engine import SubtitlePositionEngine
from .subtitle_engine import MultiStyleSubtitleEngine
from .motion_engine import MotionEngine
from .transition_engine import TransitionEngine
from .sfx_engine import SFXEngine
from .audio_mixer import AudioDirector
from .reframing_engine import ReframingEngine
from .editing_rhythm import EditingRhythmEngine
from .timeline import MultitrackTimeline
from .telemetry import EditingTelemetryCollector

from ..models import VisualCandidate, VisualProvenance, RightsStatus

logger = logging.getLogger(__name__)


class AdvancedEditorialEngine:
    """Master editorial director assembling deterministic, broadcast-grade Short edits."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir
        self.style_selector = SubtitleStyleSelector()
        self.profile_selector = EditingStyleSelector()
        self.position_engine = SubtitlePositionEngine()
        self.subtitle_engine = MultiStyleSubtitleEngine(output_dir=self.output_dir)
        self.motion_engine = MotionEngine()
        self.transition_engine = TransitionEngine()
        self.sfx_engine = SFXEngine()
        self.audio_director = AudioDirector()
        self.reframing_engine = ReframingEngine()
        self.rhythm_engine = EditingRhythmEngine()

    def build_editing_plan(
        self,
        job_id: str,
        topic_title: str,
        category: str,
        script_text: str,
        shots_data: List[Dict[str, Any]],
        candidates_map: Dict[str, VisualCandidate],
        total_duration: float,
        evidence_overlays_map: Optional[Dict[str, str]] = None,
        voice_path: Optional[str] = None,
        voice_id: str = "voice_default",
        bgm_path: Optional[str] = None,
        bgm_track_id: str = "bgm_default",
        words_data: Optional[List[Dict[str, Any]]] = None
    ) -> EditingPlan:
        """
        Synthesizes all editorial inputs into a fully deterministic EditingPlan.
        """
        # Reset per-job directorial state
        self.style_selector.reset()
        self.position_engine.reset()
        self.transition_engine.reset()
        self.sfx_engine.reset()

        shot_count = len(shots_data)
        if shot_count == 0:
            raise ValueError("Cannot formulate editing plan for 0 shots.")

        # 1. Determine overarching EditingStyleProfile
        profile = self.profile_selector.select_profile(category, topic_title, script_text)
        logger.info(f"[EDITORIAL_ENGINE] Formulating plan for job {job_id} under profile '{profile.value}' ({shot_count} shots)")

        # 2. Directorial Rhythm & Pacing curve
        narrative_roles = [s.get("narrative_stage", "SETUP") for s in shots_data]
        pacing_urgency = "FAST_PACED" if profile == EditingStyleProfile.FAST_BREAKING else "BALANCED"
        durations = self.rhythm_engine.calculate_pacing_curve(
            total_duration=total_duration,
            shot_count=shot_count,
            narrative_roles=narrative_roles,
            profile_urgency=pacing_urgency
        )

        timeline = MultitrackTimeline(target_duration=total_duration)
        all_subtitle_cues: List[SubtitleCue] = []
        shot_edits: List[ShotEdit] = []
        curr_time = 0.0
        overlays_map = evidence_overlays_map or {}

        # 3. Build each ShotEdit
        for idx, s in enumerate(shots_data):
            shot_id = s.get("shot_id", f"shot_{idx+1}")
            dur = durations[idx]
            role = s.get("narrative_stage", "SETUP")
            narration = s.get("narration_segment", "")
            s_time = round(curr_time, 2)
            e_time = round(curr_time + dur, 2)

            # A. Visual Candidate & Provenance
            cand = candidates_map.get(shot_id)
            if not cand:
                # Deterministic fallback candidate
                cand = VisualCandidate(
                    candidate_id=f"cand_fallback_{idx+1}",
                    source_class="SOURCE_A",
                    source_name="pexels",
                    source_url="https://images.pexels.com/fallback.mp4"
                )

            prov_id = cand.provenance.asset_id if cand.provenance else cand.candidate_id

            # B. 9:16 Vertical Reframing
            reframing = self.reframing_engine.calculate_reframing(
                source_width=cand.width,
                source_height=cand.height,
                subject_center_x=0.5,
                subject_center_y=0.4
            )

            # C. Camera Motion Design
            motion_str = s.get("camera_motion", "subtle_zoom_in")
            intensity_multiplier = 1.2 if profile in (EditingStyleProfile.DRAMATIC, EditingStyleProfile.FAST_BREAKING) else 1.0
            motion_spec = self.motion_engine.generate_camera_motion_spec(
                motion_type=motion_str,
                duration=dur,
                intensity=intensity_multiplier
            )

            # D. Pacing-Aware Transition In
            prev_role = shots_data[idx-1].get("narrative_stage") if idx > 0 else None
            transition_spec = self.transition_engine.select_transition(
                shot_index=idx,
                narrative_role=role,
                previous_role=prev_role,
                pacing_urgency=pacing_urgency
            )

            # E. Evidence Overlay Presence
            overlay_file = overlays_map.get(shot_id)

            # F. Directorial Subtitle Styling
            style_type = self.style_selector.select_style_for_beat(
                beat_index=idx,
                narrative_role=role,
                narration_text=narration,
                evidence_overlay_present=bool(overlay_file),
                intensity="CLIMAX" if role in ("CLIMAX", "REVEAL") else "MEDIUM"
            )

            # G. Dynamic Subtitle Positioning (Avoiding lower-third overlay collision)
            pos_type = self.position_engine.select_optimal_position(
                evidence_overlay_present=bool(overlay_file),
                text_length=len(narration),
                is_dramatic_climax=(role == "CLIMAX")
            )
            screen_x, screen_y, _, _ = self.position_engine.get_position_coordinates(pos_type)

            # H. Generate Subtitle Cue for this shot
            shot_cue = SubtitleCue(
                cue_id=f"cue_{idx+1}",
                start_time=s_time,
                end_time=e_time,
                text=narration,
                style_type=style_type,
                position_type=pos_type,
                screen_x=screen_x,
                screen_y=screen_y
            )
            all_subtitle_cues.append(shot_cue)

            # I. Sound Design Opportunity
            sfx_spec = self.sfx_engine.evaluate_sfx_opportunity(
                start_time=s_time,
                duration=dur,
                narrative_role=role,
                narration_text=narration,
                evidence_overlay_present=bool(overlay_file)
            )
            sfx_list = [sfx_spec] if sfx_spec else []

            # J. Formulate ShotEdit
            shot_edit = ShotEdit(
                shot_id=shot_id,
                shot_index=idx,
                timeline_start=s_time,
                timeline_end=e_time,
                duration=dur,
                source_asset_id=cand.candidate_id,
                source_url=cand.source_url,
                source_provenance_id=prov_id,
                clip_in_point=0.0,
                clip_out_point=dur,
                narrative_role=role,
                intensity="HIGH" if role in ("HOOK", "CLIMAX") else "MEDIUM",
                reframing=reframing,
                camera_motion=motion_spec,
                transition_in=transition_spec,
                subtitle_cues=[shot_cue],
                sfx_cues=sfx_list,
                evidence_overlay_path=overlay_file,
                editorial_reason=f"{role.capitalize()} beat with {style_type.value} typography and {motion_str} motion"
            )
            shot_edits.append(shot_edit)
            timeline.add_shot(shot_edit)
            if overlay_file:
                timeline.add_overlay({"shot_id": shot_id, "path": overlay_file, "start": s_time, "duration": dur})
            if sfx_spec:
                timeline.add_sfx_cue(sfx_spec)

            curr_time = e_time

        # 4. Generate Multi-Style ASS Subtitle Stream
        ass_path = self.subtitle_engine.generate_multistyle_ass(
            cues=all_subtitle_cues,
            job_id=job_id
        )

        # 5. Formulate Master Audio Mix Plan (Voice > SFX > BGM)
        all_sfx = self.sfx_engine.placed_cues
        speech_intervals = [(s.timeline_start, s.timeline_end) for s in shot_edits]
        audio_plan = self.audio_director.formulate_mix_plan(
            duration=total_duration,
            voice_path=voice_path,
            bgm_path=bgm_path,
            sfx_cues=all_sfx,
            voice_active_ranges=speech_intervals
        )
        timeline.set_audio_tracks(voice=audio_plan.voice_track, bgm=audio_plan.bgm_track)

        # 6. Validate Multitrack Timeline Integrity
        valid, errors = timeline.validate_timeline()
        if not valid:
            logger.error(f"[EDITORIAL_ENGINE] Timeline validation failed: {errors}")

        # 7. Package Complete Directorial EditingPlan
        plan = EditingPlan(
            job_id=job_id,
            topic_title=topic_title,
            profile=profile,
            total_duration=round(total_duration, 2),
            shots=shot_edits,
            audio_mix_plan=audio_plan,
            ass_subtitles_path=str(ass_path)
        )

        # 8. Collect Measurable AI Council Telemetry
        EditingTelemetryCollector.collect_telemetry(
            plan=plan,
            voice_id=voice_id,
            bgm_track_id=bgm_track_id,
            occlusion_avoidances=self.position_engine.occlusion_avoidance_count
        )

        logger.info(
            f"[EDITORIAL_ENGINE] Successfully formulated EditingPlan {job_id}: "
            f"{len(shot_edits)} shots, {len(all_sfx)} SFX, "
            f"{len(set(c.style_type for c in all_subtitle_cues))} subtitle styles"
        )
        return plan
