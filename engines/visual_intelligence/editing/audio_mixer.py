"""
Audio Directorial Mixer for AL-AMR Advanced Editorial Engine.
Implements studio-grade audio priority mixing:
- Tier 1: Narration Voice (Highest Priority, 0 dB reference)
- Tier 2: Sound Design / SFX Cues (-18 dB to -24 dB, narrative impact)
- Tier 3: Background Music (-28 dB to -32 dB, dynamically ducked during active narration)
- Automatic ducking envelope calculations (smooth fade-down during speech, gentle rise during pauses)
- Target loudness calibration (-14 LUFS master)
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from .editing_models import AudioTrackSpec, AudioMixPlan, SFXCueSpec

logger = logging.getLogger(__name__)


class AudioDirector:
    """
    Directorial audio planner. Formulates the AudioMixPlan with exact
    ducking keyframes and loudness targets.
    """

    DEFAULT_MASTER_LUFS = -14.0
    DEFAULT_BGM_LUFS = -28.0
    DEFAULT_DUCKING_ATTENUATION_DB = -22.0
    DUCKING_FADE_SEC = 0.20

    def formulate_mix_plan(
        self,
        duration: float,
        voice_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        sfx_cues: Optional[List[SFXCueSpec]] = None,
        voice_active_ranges: Optional[List[Tuple[float, float]]] = None
    ) -> AudioMixPlan:
        """
        Builds a comprehensive AudioMixPlan with dynamic ducking intervals.
        """
        dur = round(duration, 2)
        sfx_list = sfx_cues or []

        # Voice track spec
        voice_track = AudioTrackSpec(
            track_id="voice_master",
            track_type="voice",
            file_path=voice_path,
            start_time=0.0,
            duration=dur,
            volume_db=0.0,
            priority=1
        ) if voice_path else None

        # BGM track spec
        bgm_track = AudioTrackSpec(
            track_id="bgm_master",
            track_type="bgm",
            file_path=bgm_path,
            start_time=0.0,
            duration=dur,
            volume_db=-24.0,
            ducking_attenuation_db=self.DEFAULT_DUCKING_ATTENUATION_DB,
            priority=3
        ) if bgm_path else None

        # Calculate ducking intervals: whenever speech is active
        ducking_points: List[Tuple[float, float, float]] = []
        if voice_active_ranges:
            for s, e in voice_active_ranges:
                # Add slight padding around speech for smooth ducking
                duck_s = max(0.0, s - 0.10)
                duck_e = min(dur, e + 0.15)
                ducking_points.append((round(duck_s, 2), round(duck_e, 2), self.DEFAULT_DUCKING_ATTENUATION_DB))
        elif voice_track:
            # Entire voice track active by default with slight intro/outro margin
            ducking_points.append((0.2, max(0.2, dur - 0.4), self.DEFAULT_DUCKING_ATTENUATION_DB))

        # Also duck BGM during heavy SFX impacts (Priority 1 SFX)
        for sfx in sfx_list:
            if sfx.priority == 1:
                sfx_s = max(0.0, sfx.start_time - 0.05)
                sfx_e = min(dur, sfx.start_time + sfx.duration)
                ducking_points.append((round(sfx_s, 2), round(sfx_e, 2), -26.0))

        # Merge overlapping ducking intervals
        merged_ducking = self._merge_intervals(ducking_points)

        logger.debug(f"Formulated AudioMixPlan: {len(merged_ducking)} ducking points, {len(sfx_list)} SFX cues")

        return AudioMixPlan(
            master_duration=dur,
            voice_track=voice_track,
            bgm_track=bgm_track,
            sfx_tracks=sfx_list,
            master_lufs_target=self.DEFAULT_MASTER_LUFS,
            bgm_lufs_target=self.DEFAULT_BGM_LUFS,
            ducking_points=merged_ducking
        )

    def _merge_intervals(
        self,
        intervals: List[Tuple[float, float, float]]
    ) -> List[Tuple[float, float, float]]:
        """Merges overlapping temporal ducking windows."""
        if not intervals:
            return []
        sorted_iv = sorted(intervals, key=lambda x: x[0])
        merged = [sorted_iv[0]]
        for curr in sorted_iv[1:]:
            prev_s, prev_e, prev_vol = merged[-1]
            c_s, c_e, c_vol = curr
            if c_s <= prev_e:
                # Overlapping
                new_e = max(prev_e, c_e)
                min_vol = min(prev_vol, c_vol) # Greater attenuation
                merged[-1] = (prev_s, new_e, min_vol)
            else:
                merged.append(curr)
        return merged
