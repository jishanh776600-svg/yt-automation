"""
Multitrack Timeline Engine for AL-AMR.
Implements non-destructive, declarative multitrack timeline composition:
- Layer 0: Visual Media Track (Video / Still Photos with In/Out points)
- Layer 1: Contextual Evidence Overlay Track
- Layer 2: Multi-Style Subtitle Dialogue Track
- Layer 3: Narration Voice Audio Track
- Layer 4: SFX Audio Cue Track
- Layer 5: Dynamic BGM Track (with ducking envelope)

Enforces strict temporal continuity: zero black-frame gaps, zero overlap collisions,
and bounded duration clamping.
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from .editing_models import ShotEdit, SubtitleCue, SFXCueSpec, AudioTrackSpec

logger = logging.getLogger(__name__)


class TimelineValidationError(Exception):
    """Raised when timeline integrity checks fail."""
    pass


class MultitrackTimeline:
    """
    Directorial timeline representation. Organizes and validates all video, audio,
    and subtitle streams for a single Short.
    """

    def __init__(self, target_duration: float = 24.0):
        self.target_duration = round(target_duration, 2)
        self.video_track: List[ShotEdit] = []
        self.overlay_track: List[Dict[str, Any]] = []
        self.subtitle_cues: List[SubtitleCue] = []
        self.sfx_cues: List[SFXCueSpec] = []
        self.voice_track: Optional[AudioTrackSpec] = None
        self.bgm_track: Optional[AudioTrackSpec] = None

    def add_shot(self, shot: ShotEdit):
        """Appends a shot edit to the video track."""
        self.video_track.append(shot)

    def add_overlay(self, overlay_spec: Dict[str, Any]):
        """Adds a graphic overlay to the overlay track."""
        self.overlay_track.append(overlay_spec)

    def add_subtitle_cue(self, cue: SubtitleCue):
        """Adds a subtitle cue to the dialogue track."""
        self.subtitle_cues.append(cue)

    def add_sfx_cue(self, cue: SFXCueSpec):
        """Adds an SFX cue to the sound design track."""
        self.sfx_cues.append(cue)

    def set_audio_tracks(
        self,
        voice: Optional[AudioTrackSpec] = None,
        bgm: Optional[AudioTrackSpec] = None
    ):
        """Registers master narration and BGM streams."""
        self.voice_track = voice
        self.bgm_track = bgm

    def validate_timeline(self) -> Tuple[bool, List[str]]:
        """
        Validates timeline continuity and bounds.
        Guarantees:
        1. Video track has at least 1 shot.
        2. No negative or zero duration shots.
        3. Zero temporal gaps between consecutive video shots (continuous coverage).
        4. Total shot duration equals target duration (within +/- 0.15s).
        5. In-point < out-point for every clip.
        """
        errors: List[str] = []

        if not self.video_track:
            return False, ["Timeline contains zero video shots."]

        expected_time = 0.0
        total_time = 0.0

        for i, shot in enumerate(self.video_track):
            if shot.duration <= 0.0:
                errors.append(f"Shot {i} has invalid duration: {shot.duration:.2f}s.")

            if abs(shot.timeline_start - expected_time) > 0.05:
                errors.append(
                    f"Temporal gap/overlap detected at shot {i}: expected {expected_time:.2f}s, "
                    f"got {shot.timeline_start:.2f}s (delta: {shot.timeline_start - expected_time:.3f}s)."
                )

            if shot.clip_in_point >= shot.clip_out_point:
                errors.append(
                    f"Shot {i} has invalid clip in/out points: in={shot.clip_in_point}, out={shot.clip_out_point}."
                )

            expected_time = shot.timeline_end
            total_time += shot.duration

        total_time = round(total_time, 2)
        if abs(total_time - self.target_duration) > 0.15:
            errors.append(
                f"Total timeline duration ({total_time:.2f}s) does not match target ({self.target_duration:.2f}s)."
            )

        passed = len(errors) == 0
        if not passed:
            logger.warning(f"Timeline validation failed with {len(errors)} issues: {errors}")
        return passed, errors

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured timeline summary."""
        return {
            "shot_count": len(self.video_track),
            "target_duration": self.target_duration,
            "actual_duration": round(sum(s.duration for s in self.video_track), 2),
            "overlay_count": len(self.overlay_track),
            "subtitle_cue_count": len(self.subtitle_cues),
            "sfx_cue_count": len(self.sfx_cues),
            "has_voice": self.voice_track is not None,
            "has_bgm": self.bgm_track is not None
        }
