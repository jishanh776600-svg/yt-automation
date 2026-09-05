"""
Advanced Motion & Keyframe Engine.
Produces mathematical, cinematic camera movements and non-linear easing curves:
- Easing functions: Linear, Ease-In, Ease-Out, Ease-In-Out, and Spring Physics
- Camera motions: Subtle zooms, Punch-ins, Slow pans, Dynamic reframing, Freeze frames
- Keyframe generator: frame-accurate time, scale, position, rotation, and opacity
- FFmpeg filtergraph expression generator
"""
import math
import logging
from typing import List, Dict, Any, Optional, Union
from .editing_models import MotionType, EasingType, Keyframe, CameraMotionSpec
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, VIDEO_FPS

logger = logging.getLogger(__name__)


def linear_ease(t: float) -> float:
    """Linear progression (t: 0.0 to 1.0)."""
    return max(0.0, min(1.0, t))


def ease_in_quad(t: float) -> float:
    """Quadratic ease in."""
    t = max(0.0, min(1.0, t))
    return t * t


def ease_out_quad(t: float) -> float:
    """Quadratic ease out."""
    t = max(0.0, min(1.0, t))
    return t * (2.0 - t)


def ease_in_out_cubic(t: float) -> float:
    """Cubic smooth ease in and out."""
    t = max(0.0, min(1.0, t))
    if t < 0.5:
        return 4.0 * t * t * t
    else:
        p = 2.0 * t - 2.0
        return 0.5 * p * p * p + 1.0


def spring_physics(t: float, tension: float = 170.0, friction: float = 26.0) -> float:
    """
    Spring physics simulation curve adapted from Remotion / Framer Motion.
    Returns normalized displacement (overshoots slightly then settles at 1.0).
    """
    t = max(0.0, min(1.0, t))
    if t >= 1.0:
        return 1.0
    omega = math.sqrt(tension)
    zeta = friction / (2.0 * omega)
    if zeta < 1.0:
        omega_d = omega * math.sqrt(1.0 - zeta * zeta)
        decay = math.exp(-zeta * omega * t * 3.0)
        osc = math.cos(omega_d * t * 3.0) + (zeta / math.sqrt(1.0 - zeta * zeta)) * math.sin(omega_d * t * 3.0)
        return 1.0 - decay * osc
    else:
        return 1.0 - math.exp(-omega * t * 3.0)


class MotionEngine:
    """Generates directorial motion directives, keyframe sequences, and FFmpeg filter expressions."""

    def generate_camera_motion_spec(
        self,
        motion_type: Union[MotionType, str],
        duration: float,
        intensity: float = 1.0
    ) -> CameraMotionSpec:
        """Creates a fully specified CameraMotionSpec with generated keyframes."""
        if isinstance(motion_type, str):
            try:
                m_type = MotionType(motion_type)
            except ValueError:
                m_type = MotionType.NONE
        else:
            m_type = motion_type

        start_scale = 1.0
        end_scale = 1.0
        easing = EasingType.EASE_IN_OUT

        if m_type == MotionType.SUBTLE_ZOOM_IN:
            start_scale = 1.0
            end_scale = 1.0 + (0.06 * intensity)
            easing = EasingType.EASE_IN_OUT
        elif m_type == MotionType.SUBTLE_ZOOM_OUT:
            start_scale = 1.0 + (0.06 * intensity)
            end_scale = 1.0
            easing = EasingType.EASE_IN_OUT
        elif m_type == MotionType.PUNCH_IN:
            start_scale = 1.0
            end_scale = 1.0 + (0.15 * intensity)
            easing = EasingType.SPRING
        elif m_type == MotionType.PUNCH_OUT:
            start_scale = 1.0 + (0.15 * intensity)
            end_scale = 1.0
            easing = EasingType.SPRING
        elif m_type in (MotionType.SLOW_PAN_LEFT, MotionType.SLOW_PAN_RIGHT):
            start_scale = 1.08 # Scale up slightly to allow horizontal pan margin
            end_scale = 1.08
            easing = EasingType.LINEAR

        keyframes = self._generate_keyframes(m_type, duration, start_scale, end_scale, easing)

        return CameraMotionSpec(
            motion_type=m_type,
            start_scale=round(start_scale, 3),
            end_scale=round(end_scale, 3),
            pan_direction="left" if m_type == MotionType.SLOW_PAN_LEFT else ("right" if m_type == MotionType.SLOW_PAN_RIGHT else None),
            easing=easing,
            intensity=intensity,
            keyframes=keyframes
        )

    def _generate_keyframes(
        self,
        motion_type: MotionType,
        duration: float,
        start_scale: float,
        end_scale: float,
        easing: EasingType
    ) -> List[Keyframe]:
        """Interpolates discrete keyframes across the shot duration."""
        steps = max(2, int(duration * 2)) # ~2 keyframes per second
        kfs = []
        for i in range(steps):
            frac = i / float(steps - 1)
            t_offset = round(frac * duration, 2)
            
            # Compute ease progression
            if easing == EasingType.LINEAR:
                progress = linear_ease(frac)
            elif easing == EasingType.SPRING:
                progress = spring_physics(frac)
            else:
                progress = ease_in_out_cubic(frac)

            scale = round(start_scale + progress * (end_scale - start_scale), 3)
            
            # Pan shifts
            x_shift = 0.0
            if motion_type == MotionType.SLOW_PAN_LEFT:
                x_shift = round(0.04 * (1.0 - progress * 2.0), 3)
            elif motion_type == MotionType.SLOW_PAN_RIGHT:
                x_shift = round(0.04 * (-1.0 + progress * 2.0), 3)

            kfs.append(Keyframe(
                time_offset=t_offset,
                scale=scale,
                x_offset=x_shift,
                easing=easing
            ))
        return kfs

    def build_ffmpeg_filter(
        self,
        motion_type: MotionType,
        duration: float,
        fps: int = VIDEO_FPS
    ) -> str:
        """
        Builds production-grade FFmpeg filter expression (zoompan and crop)
        matching the desired motion profile.
        """
        frames = max(1, int(duration * fps))

        if motion_type == MotionType.SUBTLE_ZOOM_IN:
            return (
                f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
                f"zoompan=z='min(zoom+0.0006,1.06)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={fps},"
                f"setsar=1,format=yuv420p"
            )
        elif motion_type == MotionType.SUBTLE_ZOOM_OUT:
            return (
                f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
                f"zoompan=z='if(lte(zoom,1.0),1.06,max(1.001,zoom-0.0006))':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={fps},"
                f"setsar=1,format=yuv420p"
            )
        elif motion_type == MotionType.PUNCH_IN:
            return (
                f"scale={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH*2}:{VIDEO_HEIGHT*2},"
                f"zoompan=z='min(zoom+0.0018,1.15)':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={fps},"
                f"setsar=1,format=yuv420p"
            )
        elif motion_type == MotionType.SLOW_PAN_LEFT:
            return (
                f"scale={int(VIDEO_WIDTH*1.15)}:{int(VIDEO_HEIGHT*1.15)}:force_original_aspect_ratio=increase,"
                f"zoompan=z=1.08:x='if(lte(on,1),(iw-iw/zoom)/2,max(0,x-0.5))':y='(ih-ih/zoom)/2':d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={fps},"
                f"setsar=1,format=yuv420p"
            )
        elif motion_type == MotionType.SLOW_PAN_RIGHT:
            return (
                f"scale={int(VIDEO_WIDTH*1.15)}:{int(VIDEO_HEIGHT*1.15)}:force_original_aspect_ratio=increase,"
                f"zoompan=z=1.08:x='if(lte(on,1),0,min(iw-iw/zoom,x+0.5))':y='(ih-ih/zoom)/2':d={frames}:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:fps={fps},"
                f"setsar=1,format=yuv420p"
            )
        else: # NONE / Standard center crop
            return (
                f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(iw-{VIDEO_WIDTH})/2:(ih-{VIDEO_HEIGHT})/2,"
                f"setsar=1,format=yuv420p"
            )
