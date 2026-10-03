"""
Editorial Visual Composition + Narration-Synchronized Pacing Engine (Step 6/8).
==============================================================================
Orchestrates individually retrieved and framed moving video clips into a coherent,
fast-paced vertical YouTube Short synchronized with narration.

Key Capabilities:
  1. Narration Timeline Construction (sentence boundaries, word timing, deterministic punctuation pauses).
  2. Dynamic Shot Durations (hook: 1.5-2.5s, setup: 2.0-3.5s, climax: 1.2-2.2s, ending/loop: 2.0-3.5s).
  3. Action-Anchor Alignment: Synchronizes clip action peaks (cannon firing, iceberg collision,
     water rushing in) to align with narration action words.
  4. Shot Density Control: Enforces 6-10 meaningful visual beats for 25-30s Shorts (preferring
     fewer strong shots over many weak cuts).
  5. Visual Continuity & Story Flow (thematic subject coherence across adjacent cuts).
  6. Visual Variety & Memory Integration (consecutive-scene protection via Step 5 VisualMemoryManager).
  7. Special Hook Engine (first 1-3s prioritizes instant narrative mystery and high visual interest).
  8. Seamless Ending & Loop Integration (callback to hook without dead time).
  9. Absolute VIDEO ONLY Invariant (zero still images, zero canvases, zero slides).
"""
import re
import uuid
import math
import logging
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set, Union

from core.media_validator import PhysicalVideoValidator, VIDEO_ONLY
from .models import (
    SourceType, VisualCandidate, VisualIntent, VisualContentType,
    NormalizedVideoCandidate, TemporalWindow
)
from .temporal_extractor import TemporalMomentRetriever
from .framing import IntelligentFramingEngine, FramingSpec, EditorialCropStrategy
from .memory import VisualMemoryManager, VisualMemoryEvaluation

logger = logging.getLogger(__name__)

ACTION_ANCHOR_CUES = {
    "fired": ["fired", "fire", "firing", "blast", "blasting", "cannon", "gunshot", "shoot", "shot", "bombardment", "artillery", "launched"],
    "collision": ["slammed", "collision", "collided", "hit", "striking", "struck", "impact", "crashed", "crash", "rammed"],
    "explosion": ["exploded", "explosion", "erupted", "eruption", "burst", "detonation", "blew up", "detonated"],
    "sinking": ["sank", "sinking", "submerged", "drowning", "plunge", "plunged", "swallowed", "flooded", "flooding", "capsized", "water", "draining"],
    "escape": ["fled", "fleeing", "running", "escaped", "evacuated", "evacuating", "scrambling", "rescue", "rescued"],
    "discovered": ["discovered", "uncover", "uncovered", "found", "reveal", "revealed", "unearth", "unearthed", "identified"],
    "vanished": ["vanished", "disappeared", "disappearance", "missing", "lost", "gone", "abandoned", "empty"],
    "collapse": ["collapsed", "collapse", "falling", "fell", "crumbled", "crashing down", "toppled", "crushed", "destroyed"]
}


# ==============================================================================
# 1. Narration Timeline Models & Parser
# ==============================================================================
@dataclass
class NarrationWord:
    """Word-level timing within the narration timeline."""
    word: str
    clean_word: str
    start_time: float
    end_time: float
    duration: float
    is_action_cue: bool = False
    action_type: Optional[str] = None
    is_emphasis: bool = False
    is_noun: bool = False
    is_verb: bool = False
    is_number_date: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NarrationSegment:
    """Clause- or sentence-level segment corresponding to a narrative beat."""
    segment_id: str
    segment_index: int
    text: str
    stage: str                          # hook, context, escalation, reveal, loop_twist
    start_time: float
    end_time: float
    duration: float
    words: List[NarrationWord] = field(default_factory=list)
    has_action: bool = False
    action_type: Optional[str] = None
    action_anchor_time: Optional[float] = None  # Exact timestamp of action word
    sentence_boundaries: List[float] = field(default_factory=list)
    phrases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["words"] = [w.to_dict() for w in self.words]
        return d


@dataclass
class NarrationTimeline:
    """Master narration timeline for a Short."""
    total_duration: float
    segments: List[NarrationSegment] = field(default_factory=list)
    words: List[NarrationWord] = field(default_factory=list)
    hook_duration: float = 2.5
    ending_duration: float = 2.5

    def get_action_anchors(self) -> List[Tuple[float, str, str]]:
        """Returns list of (timestamp, action_type, word) for action events."""
        anchors = []
        for w in self.words:
            if w.is_action_cue and w.action_type:
                anchors.append((w.start_time, w.action_type, w.clean_word))
        return anchors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_duration": self.total_duration,
            "segment_count": len(self.segments),
            "word_count": len(self.words),
            "hook_duration": self.hook_duration,
            "ending_duration": self.ending_duration,
            "segments": [s.to_dict() for s in self.segments]
        }


# ==============================================================================
# 2. Narration Timeline Builder
# ==============================================================================
class NarrationTimelineBuilder:
    """
    Constructs accurate narration timeline using exact Whisper/TTS timestamps where available,
    or deterministic acoustic duration weighting with punctuation pauses.
    """

    NUMBER_DATE_PATTERN = re.compile(
        r"^(?:\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"hundred|thousand|million|billion|january|february|march|april|may|june|july|august|september|october|november|december|"
        r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|seconds?|minutes?|hours?|days?|weeks?|months?|years?)$",
        re.IGNORECASE
    )
    COMMON_VERB_SUFFIXES = ("ing", "ed", "ize", "ise", "ate", "en")

    @classmethod
    def parse_action_cue(cls, word_clean: str) -> Optional[str]:
        """Detects if a word is an action-anchor cue."""
        w_lower = word_clean.lower()
        for action_type, keywords in ACTION_ANCHOR_CUES.items():
            if any(k in w_lower for k in keywords):
                return action_type
        return None

    @classmethod
    def build_timeline(
        cls,
        script_parts: List[Tuple[str, str]], # [(stage, text), ...]
        total_duration: float,
        word_timestamps: Optional[List[Dict[str, Any]]] = None
    ) -> NarrationTimeline:
        """
        Builds master timeline.
        If word_timestamps provided: binds exact timestamps.
        If unavailable: applies deterministic acoustic weighting:
          - Commas (,) add +0.15s pause
          - Em-dashes (—) and semicolons (;) add +0.22s pause
          - Periods (.), question marks (?), exclamation marks (!) add +0.32s pause
          - Remaining duration is distributed proportionally by word syllable count
        """
        assert total_duration > 0, "total_duration must be positive"

        # 1. If exact word timestamps are provided
        if word_timestamps and len(word_timestamps) > 0:
            return cls._build_from_exact_word_timestamps(script_parts, total_duration, word_timestamps)

        # 2. Deterministic acoustic pause weighting
        return cls._build_from_deterministic_acoustics(script_parts, total_duration)

    @classmethod
    def _build_from_exact_word_timestamps(
        cls,
        script_parts: List[Tuple[str, str]],
        total_duration: float,
        word_timestamps: List[Dict[str, Any]]
    ) -> NarrationTimeline:
        words = []
        for wt in word_timestamps:
            raw_w = str(wt.get("word", "")).strip()
            clean_w = re.sub(r"[^\w\s]", "", raw_w)
            st = float(wt.get("start", 0.0))
            et = float(wt.get("end", st + 0.3))
            act_type = cls.parse_action_cue(clean_w)
            is_emph = bool(wt.get("is_emphasis", False)) or (len(clean_w) > 4 and clean_w.isupper())
            is_num_date = bool(cls.NUMBER_DATE_PATTERN.match(clean_w.lower())) or any(ch.isdigit() for ch in clean_w)
            is_verb = act_type is not None or any(clean_w.lower().endswith(sfx) for sfx in cls.COMMON_VERB_SUFFIXES)
            is_noun = bool(clean_w and clean_w[0].isupper() and not is_num_date) or (not is_verb and not is_num_date and len(clean_w) > 3)

            words.append(NarrationWord(
                word=raw_w,
                clean_word=clean_w,
                start_time=round(st, 3),
                end_time=round(et, 3),
                duration=round(et - st, 3),
                is_action_cue=act_type is not None,
                action_type=act_type,
                is_emphasis=is_emph,
                is_noun=is_noun,
                is_verb=is_verb,
                is_number_date=is_num_date
            ))

        # Map words to segments
        segments = []
        word_idx = 0
        seg_idx = 0

        for stage, text_content in script_parts:
            text_clean = text_content.strip()
            seg_words = text_clean.split()
            seg_len = len(seg_words)

            assigned = words[word_idx: word_idx + seg_len]
            word_idx += seg_len

            if assigned:
                s_start = assigned[0].start_time
                s_end = assigned[-1].end_time
            else:
                s_start = segments[-1].end_time if segments else 0.0
                s_end = s_start + 2.5

            action_type = None
            action_time = None
            for w in assigned:
                if w.is_action_cue:
                    action_type = w.action_type
                    action_time = w.start_time
                    break

            # Extract clauses/phrases and sentence boundaries
            phrases = [c.strip() for c in re.split(r'[,;—\.]+', text_clean) if len(c.strip()) > 2]
            sentence_bounds = []
            for w in assigned:
                if any(w.word.endswith(p) for p in [".", "!", "?", ",", ";", "—"]):
                    sentence_bounds.append(w.end_time)

            segments.append(NarrationSegment(
                segment_id=f"seg_{seg_idx+1}_{stage}",
                segment_index=seg_idx,
                text=text_clean,
                stage=stage,
                start_time=round(s_start, 3),
                end_time=round(s_end, 3),
                duration=round(max(0.5, s_end - s_start), 3),
                words=assigned,
                has_action=action_type is not None,
                action_type=action_type,
                action_anchor_time=action_time,
                sentence_boundaries=sentence_bounds,
                phrases=phrases
            ))
            seg_idx += 1

        hook_dur = segments[0].duration if segments else 2.5
        end_dur = segments[-1].duration if segments else 2.5

        return NarrationTimeline(
            total_duration=round(total_duration, 2),
            segments=segments,
            words=words,
            hook_duration=hook_dur,
            ending_duration=end_dur
        )

    @classmethod
    def _build_from_deterministic_acoustics(
        cls,
        script_parts: List[Tuple[str, str]],
        total_duration: float
    ) -> NarrationTimeline:
        raw_weights = []
        all_words_by_seg = []

        for stage, text_content in script_parts:
            text_clean = text_content.strip()
            words_in_text = text_clean.split()
            all_words_by_seg.append((stage, text_clean, words_in_text))

            # Base duration weight proportional to word lengths + punctuation pauses
            char_count = sum(max(2, len(w)) for w in words_in_text)
            comma_pause = len(re.findall(r"[,]", text_clean)) * 2.0
            dash_pause = len(re.findall(r"[—;]", text_clean)) * 3.0
            period_pause = len(re.findall(r"[\.!?]", text_clean)) * 4.0

            seg_weight = max(10.0, float(char_count) + comma_pause + dash_pause + period_pause)
            raw_weights.append(seg_weight)

        total_weight = sum(raw_weights)
        scale = total_duration / max(1.0, total_weight)

        segments = []
        all_words = []
        current_time = 0.0

        for i, (stage, text_clean, words_in_text) in enumerate(all_words_by_seg):
            seg_dur = round(raw_weights[i] * scale, 3)
            # Guarantee last segment matches total_duration exactly
            if i == len(all_words_by_seg) - 1:
                seg_dur = max(0.5, round(total_duration - current_time, 3))

            seg_start = round(current_time, 3)
            seg_end = round(current_time + seg_dur, 3)

            # Distribute words inside segment
            seg_words_timed = []
            sentence_bounds = []
            if words_in_text:
                w_dur = seg_dur / float(len(words_in_text))
                w_cur = seg_start
                for raw_w in words_in_text:
                    clean_w = re.sub(r"[^\w\s]", "", raw_w)
                    act_type = cls.parse_action_cue(clean_w)
                    is_emph = (clean_w.isupper() and len(clean_w) > 3) or raw_w.endswith("!")
                    is_num_date = bool(cls.NUMBER_DATE_PATTERN.match(clean_w.lower())) or any(ch.isdigit() for ch in clean_w)
                    is_verb = act_type is not None or any(clean_w.lower().endswith(sfx) for sfx in cls.COMMON_VERB_SUFFIXES)
                    is_noun = bool(clean_w and clean_w[0].isupper() and not is_num_date) or (not is_verb and not is_num_date and len(clean_w) > 3)

                    w_end = round(w_cur + w_dur, 3)
                    word_obj = NarrationWord(
                        word=raw_w,
                        clean_word=clean_w,
                        start_time=round(w_cur, 3),
                        end_time=w_end,
                        duration=round(w_dur, 3),
                        is_action_cue=act_type is not None,
                        action_type=act_type,
                        is_emphasis=is_emph,
                        is_noun=is_noun,
                        is_verb=is_verb,
                        is_number_date=is_num_date
                    )
                    seg_words_timed.append(word_obj)
                    all_words.append(word_obj)
                    if any(raw_w.endswith(p) for p in [".", "!", "?", ",", ";", "—"]):
                        sentence_bounds.append(w_end)
                    w_cur += w_dur

            action_type = None
            action_time = None
            for w in seg_words_timed:
                if w.is_action_cue:
                    action_type = w.action_type
                    action_time = w.start_time
                    break

            phrases = [c.strip() for c in re.split(r'[,;—\.]+', text_clean) if len(c.strip()) > 2]

            segments.append(NarrationSegment(
                segment_id=f"seg_{i+1}_{stage}",
                segment_index=i,
                text=text_clean,
                stage=stage,
                start_time=seg_start,
                end_time=seg_end,
                duration=seg_dur,
                words=seg_words_timed,
                has_action=action_type is not None,
                action_type=action_type,
                action_anchor_time=action_time,
                sentence_boundaries=sentence_bounds,
                phrases=phrases
            ))
            current_time = seg_end

        hook_dur = segments[0].duration if segments else 2.5
        end_dur = segments[-1].duration if segments else 2.5

        return NarrationTimeline(
            total_duration=round(total_duration, 2),
            segments=segments,
            words=all_words,
            hook_duration=hook_dur,
            ending_duration=end_dur
        )


# ==============================================================================
# 3. Synchronized Shot & Editorial Composition Data Models
# ==============================================================================
@dataclass
class SynchronizedShot:
    """Editorial specification for a single synchronized shot in the Short."""
    shot_id: str
    shot_index: int
    timeline_start: float
    timeline_end: float
    duration: float
    narration_text: str
    narrative_role: str                 # HOOK, SETUP, ESCALATION, REVEAL, CLIMAX, OUTRO_LOOP
    candidate: NormalizedVideoCandidate
    video_path: Path
    source_clip_in: float               # Sub-clip in-point inside raw candidate
    source_clip_out: float              # Sub-clip out-point inside raw candidate
    action_peak_timeline: Optional[float] = None  # Exact timestamp of action peak in Short
    action_peak_clip_offset: Optional[float] = None
    framing_spec: Optional[FramingSpec] = None
    is_hook: bool = False
    is_ending: bool = False
    editorial_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "shot_index": self.shot_index,
            "timeline_start": self.timeline_start,
            "timeline_end": self.timeline_end,
            "duration": self.duration,
            "narration_text": self.narration_text,
            "narrative_role": self.narrative_role,
            "source_title": self.candidate.title,
            "source_type": self.candidate.source_type.value if hasattr(self.candidate.source_type, "value") else str(self.candidate.source_type),
            "video_path": str(self.video_path),
            "source_clip_in": self.source_clip_in,
            "source_clip_out": self.source_clip_out,
            "action_peak_timeline": self.action_peak_timeline,
            "action_peak_clip_offset": self.action_peak_clip_offset,
            "is_hook": self.is_hook,
            "is_ending": self.is_ending,
            "framing_strategy": self.framing_spec.strategy.value if self.framing_spec else None,
            "editorial_reason": self.editorial_reason
        }


@dataclass
class EditorialComposition:
    """Complete multitrack editorial composition for a Short."""
    composition_id: str
    total_duration: float
    shots: List[SynchronizedShot] = field(default_factory=list)
    timeline: Optional[NarrationTimeline] = None
    shot_density: int = 0
    avg_shot_duration: float = 0.0
    action_sync_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "composition_id": self.composition_id,
            "total_duration": self.total_duration,
            "shot_density": self.shot_density,
            "avg_shot_duration": self.avg_shot_duration,
            "action_sync_count": self.action_sync_count,
            "shots": [s.to_dict() for s in self.shots],
            "timeline": self.timeline.to_dict() if self.timeline else None,
            "metadata": self.metadata
        }


# ==============================================================================
# 4. Action-Anchor Alignment Engine
# ==============================================================================
class ActionAnchorAligner:
    """
    Synchronizes physical action peaks (e.g. cannon fire, ship collision, water rush)
    with the exact spoken word timestamp in narration.
    """

    @staticmethod
    def align_shot_action(
        shot_start_timeline: float,
        shot_duration: float,
        action_word_timeline: Optional[float],
        source_candidate: Any,
        temporal_window: Optional[TemporalWindow] = None
    ) -> Tuple[float, float, Optional[float], Optional[float]]:
        """
        Determines the optimal source clip in-point and out-point such that the
        clip's action peak coincides with the spoken action word.
        Uses small 0.25s lead-in before major action so motion initiates naturally.

        Returns:
          (clip_in, clip_out, action_peak_timeline, action_peak_clip_offset)
        """
        total_source_dur = getattr(source_candidate, "duration", 0.0) or 4.0
        # Determine internal action peak offset inside candidate
        peak_offset = 1.0  # Default assumption: action reaches apex around 1.0s
        if temporal_window and temporal_window.metadata:
            peak_offset = float(temporal_window.metadata.get("peak_action_offset", 1.0))
        elif temporal_window:
            peak_offset = min(shot_duration * 0.5, max(0.5, (temporal_window.end_time - temporal_window.start_time) * 0.5))

        if action_word_timeline is not None:
            # Word offset relative to shot start
            word_offset_in_shot = max(0.1, min(shot_duration - 0.2, action_word_timeline - shot_start_timeline))
            # Optimal in-point aligns clip's peak_offset with word_offset_in_shot with 0.25s lead-in
            lead_in = 0.25
            target_in = max(0.0, (peak_offset - lead_in) - word_offset_in_shot)
            # Clamp in-point so clip_out does not exceed source video duration
            if total_source_dur > shot_duration:
                target_in = min(target_in, total_source_dur - shot_duration)
            clip_in = round(target_in, 2)
            clip_out = round(clip_in + shot_duration, 2)
            action_peak_tl = round(shot_start_timeline + word_offset_in_shot, 2)
            return (clip_in, clip_out, action_peak_tl, peak_offset)

        # Fallback when no action word exists in segment
        base_start = temporal_window.start_time if temporal_window else 0.0
        if total_source_dur > shot_duration:
            base_start = min(base_start, total_source_dur - shot_duration)
        clip_in = round(max(0.0, base_start), 2)
        clip_out = round(clip_in + shot_duration, 2)
        return (clip_in, clip_out, None, None)


# ==============================================================================
# 5. Editorial Composition & Pacing Engine
# ==============================================================================
class EditorialCompositionEngine:
    """
    Directorial visual composition engine.
    Transforms storyboard beats and retrieved video candidates into a coherent,
    paced, narration-synchronized Short.
    """

    # Dynamic Pacing Targets (seconds)
    HOOK_PACING_RANGE = (1.5, 2.5)       # Fast, intriguing visual cut
    SETUP_PACING_RANGE = (2.0, 3.5)      # Normal informative rhythm
    CLIMAX_PACING_RANGE = (1.2, 2.2)     # Fast high-tension cutting
    REVEAL_PACING_RANGE = (2.5, 3.5)     # Visual hold for emotional punch
    ENDING_PACING_RANGE = (2.0, 3.5)     # Concluding hold & loop preparation

    # Target Shot Density Bounds (Target: ~9-12 shots for 22-25s Shorts, avg 1.8-2.2s)
    MIN_SHOT_DENSITY = 7
    TARGET_SHOT_DENSITY = 11
    MAX_SHOT_DENSITY = 14

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        visual_memory: Optional[VisualMemoryManager] = None
    ):
        self.cache_dir = cache_dir or Path(tempfile.gettempdir())
        self.visual_memory = visual_memory
        self.framing_engine = IntelligentFramingEngine(cache_dir=self.cache_dir)
        self.temporal_extractor = TemporalMomentRetriever(cache_dir=self.cache_dir)

    def plan_shot_density_and_durations(
        self,
        timeline: NarrationTimeline,
        available_candidates_count: Optional[int] = None
    ) -> List[Tuple[NarrationSegment, float, str]]:
        """
        Calculates dynamic shot boundaries and durations based on narrative stage:
          - Target 9 to 12 shots for ~22-25s content (average 1.8-2.2s per shot)
          - Hook gets punchy 1.5-2.5s
          - Climax gets rapid 1.2-2.2s
          - Reveal gets breathing room 2.5-3.5s
          - Invariant: RELEVANCE ALWAYS BEATS SHOT COUNT.
            Never manufacture additional shots by duplicating footage, repeating temporal moments,
            or inserting images. If only 7 genuinely relevant clips exist, use 7.
        Returns list of (segment, shot_duration, narrative_role).
        """
        planned_shots = []

        # Target density scaled to duration
        ideal_target = max(self.MIN_SHOT_DENSITY, min(self.MAX_SHOT_DENSITY, round(timeline.total_duration / 2.0)))
        if available_candidates_count is not None and available_candidates_count > 0:
            max_allowed = min(ideal_target, available_candidates_count)
        else:
            max_allowed = ideal_target

        for seg in timeline.segments:
            stage_upper = seg.stage.upper()
            if "HOOK" in stage_upper:
                role = "HOOK"
                if seg.duration > 3.0 and len(planned_shots) + 1 <= max_allowed:
                    half = round(seg.duration / 2.0, 2)
                    planned_shots.append((seg, half, "HOOK_TEASE"))
                    planned_shots.append((seg, round(seg.duration - half, 2), "HOOK_ESTABLISH"))
                else:
                    planned_shots.append((seg, seg.duration, "HOOK"))

            elif "ESCALATION" in stage_upper or "CLIMAX" in stage_upper:
                role = "CLIMAX" if "CLIMAX" in stage_upper else "ESCALATION"
                if seg.duration > 3.5 and len(planned_shots) + 1 <= max_allowed:
                    half = round(seg.duration / 2.0, 2)
                    planned_shots.append((seg, half, role))
                    planned_shots.append((seg, round(seg.duration - half, 2), role))
                else:
                    planned_shots.append((seg, seg.duration, role))

            elif "REVEAL" in stage_upper:
                if seg.duration > 3.8 and len(planned_shots) + 1 <= max_allowed:
                    half = round(seg.duration / 2.0, 2)
                    planned_shots.append((seg, half, "REVEAL_BUILD"))
                    planned_shots.append((seg, round(seg.duration - half, 2), "REVEAL"))
                else:
                    planned_shots.append((seg, seg.duration, "REVEAL"))

            elif "LOOP" in stage_upper or "TWIST" in stage_upper:
                if seg.duration > 3.8 and len(planned_shots) + 1 <= max_allowed:
                    half = round(seg.duration / 2.0, 2)
                    planned_shots.append((seg, half, "OUTRO_TWIST"))
                    planned_shots.append((seg, round(seg.duration - half, 2), "OUTRO_LOOP"))
                else:
                    planned_shots.append((seg, seg.duration, "OUTRO_LOOP"))

            else:
                role = "SETUP"
                if seg.duration > 4.0 and len(planned_shots) + 1 <= max_allowed:
                    half = round(seg.duration / 2.0, 2)
                    planned_shots.append((seg, half, "SETUP_PART1"))
                    planned_shots.append((seg, round(seg.duration - half, 2), "SETUP_PART2"))
                else:
                    planned_shots.append((seg, seg.duration, role))

        # Clamp shot count so it never exceeds max_allowed (relevance beats shot count)
        while len(planned_shots) > max_allowed and len(planned_shots) > 1:
            shortest_idx = min(range(len(planned_shots) - 1), key=lambda i: planned_shots[i][1] + planned_shots[i+1][1])
            s1, d1, r1 = planned_shots[shortest_idx]
            s2, d2, r2 = planned_shots[shortest_idx + 1]
            planned_shots[shortest_idx] = (s1, round(d1 + d2, 2), r1)
            planned_shots.pop(shortest_idx + 1)

        # Expand shots if candidate count allows and longest shots can breathe faster
        if available_candidates_count is not None and len(planned_shots) < max_allowed:
            while len(planned_shots) < max_allowed:
                longest_idx = max(range(len(planned_shots)), key=lambda i: planned_shots[i][1])
                seg, dur, r = planned_shots[longest_idx]
                if dur <= 2.4:
                    break
                half = round(dur / 2.0, 2)
                planned_shots[longest_idx] = (seg, half, f"{r}_A")
                planned_shots.insert(longest_idx + 1, (seg, round(dur - half, 2), f"{r}_B"))

        # Exact duration calibration: ensure sum matches timeline.total_duration
        current_sum = sum(d for _, d, _ in planned_shots)
        dur_diff = round(timeline.total_duration - current_sum, 2)
        if abs(dur_diff) > 0.001 and planned_shots:
            last_seg, last_dur, last_r = planned_shots[-1]
            planned_shots[-1] = (last_seg, round(max(0.8, last_dur + dur_diff), 2), last_r)

        return planned_shots

    def compose_short(
        self,
        script_parts: List[Tuple[str, str]], # [(stage, text), ...]
        total_duration: float,
        candidates_by_beat: List[List[NormalizedVideoCandidate]],
        word_timestamps: Optional[List[Dict[str, Any]]] = None,
        job_id: Optional[str] = None
    ) -> EditorialComposition:
        """
        Assembles complete, narration-synchronized editorial composition.
        Integrates:
          - Narration timeline
          - Action-anchor timing alignment
          - Step 3 temporal moment extraction
          - Step 4 intelligent 9:16 vertical framing
          - Step 5 cross-job visual memory & consecutive-scene duplicate protection
        """
        assert VIDEO_ONLY is True, "VIDEO_ONLY invariant violation"

        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=script_parts,
            total_duration=total_duration,
            word_timestamps=word_timestamps
        )

        # Count distinct candidates across all pools to scale shot count dynamically (Problem 5)
        distinct_cand_urls = set()
        for pool in candidates_by_beat:
            for c in pool:
                if c.is_video:
                    u = c.page_url or c.media_url
                    if u:
                        distinct_cand_urls.add(u)

        num_available = max(1, len(distinct_cand_urls))
        planned_specs = self.plan_shot_density_and_durations(
            timeline=timeline,
            available_candidates_count=num_available
        )
        shot_count = len(planned_specs)

        used_urls: Set[str] = set()
        recent_scene_urls: List[str] = []
        recent_crops: List[Tuple[float, float]] = []

        shots: List[SynchronizedShot] = []
        current_timeline = 0.0
        action_sync_count = 0

        for i, (seg, shot_dur, role) in enumerate(planned_specs):
            shot_id = f"shot_{i+1}_{uuid.uuid4().hex[:6]}"
            shot_start = round(current_timeline, 2)
            shot_end = round(current_timeline + shot_dur, 2)

            # Available candidate pool for this shot
            cand_pool = candidates_by_beat[i % len(candidates_by_beat)]
            valid_videos = [c for c in cand_pool if c.is_video]
            if not valid_videos:
                # Check all pools for any valid video
                valid_videos = [c for pool in candidates_by_beat for c in pool if c.is_video]

            if not valid_videos:
                raise RuntimeError(
                    f"No video candidates available for shot {i+1} ('{seg.text[:30]}...'). "
                    f"Under the VIDEO_ONLY policy, image assets and canvases are strictly prohibited."
                )

            # Candidate Selection: Strictly prioritize UNUSED candidates (Problem 5: Zero Repeated Clips)
            chosen_candidate = None
            chosen_eval = None

            # 1. Search in current beat pool for unused candidate
            for cand in valid_videos:
                raw_url = cand.page_url or cand.media_url
                if raw_url in used_urls:
                    continue

                if self.visual_memory:
                    mem_eval = self.visual_memory.evaluate_candidate(
                        candidate=cand,
                        temporal_start=0.0,
                        temporal_end=shot_dur,
                        job_id=job_id,
                        recent_scene_urls=recent_scene_urls
                    )
                    if mem_eval.is_hard_duplicate:
                        continue
                    chosen_candidate = cand
                    chosen_eval = mem_eval
                    break
                else:
                    chosen_candidate = cand
                    break

            # 2. If not found in current pool, search across ALL pools for any unused candidate
            if not chosen_candidate:
                all_candidates = [c for pool in candidates_by_beat for c in pool if c.is_video]
                for cand in all_candidates:
                    raw_url = cand.page_url or cand.media_url
                    if raw_url not in used_urls:
                        chosen_candidate = cand
                        break

            # 3. If STILL no unused candidate: USE FEWER SHOTS. Merge with preceding shot rather than repeating!
            if not chosen_candidate and shots:
                logger.info(f"[COMPOSITION] No unique candidate available for shot {i+1}. Merging {shot_dur:.2f}s into shot {shots[-1].shot_id} (Fewer shots > repeated clips)")
                shots[-1].duration = round(shots[-1].duration + shot_dur, 2)
                shots[-1].end_time = round(shots[-1].end_time + shot_dur, 2)
                current_timeline = shot_end
                continue

            if not chosen_candidate:
                chosen_candidate = valid_videos[0]

            # Verify physical video validity
            if chosen_candidate.local_path:
                val = PhysicalVideoValidator.validate_file(Path(chosen_candidate.local_path))
                if not val.is_valid:
                    raise ValueError(f"Prohibited non-video asset in shot {shot_id}: {val.error_message}")

            # Action-Anchor Synchronization
            action_time = seg.action_anchor_time
            clip_in, clip_out, action_tl, action_offset = ActionAnchorAligner.align_shot_action(
                shot_start_timeline=shot_start,
                shot_duration=shot_dur,
                action_word_timeline=action_time,
                source_candidate=chosen_candidate
            )
            if action_tl is not None:
                action_sync_count += 1

            # Step 4 Framing & Crop Specification
            framing_spec = None
            if chosen_candidate.local_path and Path(chosen_candidate.local_path).exists():
                try:
                    framing_spec = self.framing_engine.calculate_framing_spec(
                        video_path=Path(chosen_candidate.local_path),
                        used_crops=recent_crops
                    )
                    recent_crops.append((framing_spec.start_cx, framing_spec.end_cx))
                except Exception as e:
                    logger.debug(f"[COMPOSITION] Framing calculation fallback for shot {i+1}: {e}")

            raw_url = chosen_candidate.page_url or chosen_candidate.media_url
            used_urls.add(raw_url)
            recent_scene_urls.append(raw_url)

            is_hook = (i == 0 or "HOOK" in role)
            is_ending = (i == shot_count - 1 or "LOOP" in role or "OUTRO" in role)

            shot = SynchronizedShot(
                shot_id=shot_id,
                shot_index=i,
                timeline_start=shot_start,
                timeline_end=shot_end,
                duration=round(shot_dur, 2),
                narration_text=seg.text,
                narrative_role=role,
                candidate=chosen_candidate,
                video_path=Path(chosen_candidate.local_path) if chosen_candidate.local_path else Path(""),
                source_clip_in=clip_in,
                source_clip_out=clip_out,
                action_peak_timeline=action_tl,
                action_peak_clip_offset=action_offset,
                framing_spec=framing_spec,
                is_hook=is_hook,
                is_ending=is_ending,
                editorial_reason=f"Stage: {seg.stage}, Action: {seg.action_type or 'None'}"
            )
            shots.append(shot)
            current_timeline = shot_end

        avg_dur = round(total_duration / float(len(shots)), 2)
        comp_id = f"comp_{uuid.uuid4().hex[:8]}"

        composition = EditorialComposition(
            composition_id=comp_id,
            total_duration=round(total_duration, 2),
            shots=shots,
            timeline=timeline,
            shot_density=len(shots),
            avg_shot_duration=avg_dur,
            action_sync_count=action_sync_count,
            metadata={
                "job_id": job_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "action_anchors_detected": len(timeline.get_action_anchors())
            }
        )

        logger.info(
            f"[EDITORIAL_COMPOSITION] Successfully composed {len(shots)} shots "
            f"(Total: {total_duration:.1f}s, Avg Shot: {avg_dur:.2f}s, Action Syncs: {action_sync_count})"
        )
        return composition

    def compose_editorial_timeline(
        self,
        script_parts: List[Tuple[str, str]], # [(stage, text), ...]
        total_duration: float,
        shots_data: List[Dict[str, Any]],
        asset_map: Dict[str, Any],
        word_timestamps: Optional[List[Dict[str, Any]]] = None,
        job_id: Optional[str] = None
    ) -> Tuple[EditorialComposition, List[Dict[str, Any]]]:
        """
        Orchestrates acquired real 9:16 assets from Steps 1-5 into an action-synchronized
        editorial timeline ready for direct FFmpeg rendering (Step 6/8).

        Enforces:
          1. VIDEO_ONLY invariant (strict rejection of static images, canvases, title cards).
          2. Narration timeline construction (sentence boundaries, word timing, punctuation pauses).
          3. Role-aware pacing (Hook 1.5-2.5s, Setup 2.0-3.5s, Climax 1.2-2.2s, Reveal 2.5-3.5s, Outro 2.0-3.5s).
          4. Action-anchor alignment (audio action verb -> video peak action with 0.25s lead-in).
          5. Visual memory & consecutive-scene protection (no adjacent duplicate URLs/canonical IDs).
          6. Relevance beats shot count (targets 9-12 shots for 22-25s Shorts, never synthesizes duplicate shots).
          7. Seamless ending & loop strategy (conceptual callback to hook without repeating frames).
        """
        assert VIDEO_ONLY is True, "VIDEO_ONLY invariant violation"
        if not shots_data:
            raise ValueError("Cannot compose editorial timeline with empty shots_data.")

        # 1. Physical Video & Cleanliness Gate: Strict VIDEO_ONLY verification
        for s in shots_data:
            sid = s.get("shot_id")
            asset = asset_map.get(sid)
            if not asset:
                continue
            local_p = getattr(asset, "local_path", None)
            if local_p:
                p = Path(local_p)
                if not p.exists() or not PhysicalVideoValidator.is_valid_video(p):
                    raise ValueError(
                        f"Prohibited non-video or corrupted visual asset in shot {sid}: '{local_p}'. "
                        f"Under the VIDEO_ONLY policy, static images, slideshows, and canvases are strictly prohibited."
                    )

        # 2. Build Master Narration Timeline
        timeline = NarrationTimelineBuilder.build_timeline(
            script_parts=script_parts,
            total_duration=total_duration,
            word_timestamps=word_timestamps
        )

        # 3. Plan Shot Density & Durations based on narrative roles & candidate count
        num_candidates = len(shots_data)
        planned_specs = self.plan_shot_density_and_durations(
            timeline=timeline,
            available_candidates_count=num_candidates
        )

        # Ensure planned specs count matches shots_data count
        if len(planned_specs) < num_candidates:
            while len(planned_specs) < num_candidates:
                longest_idx = max(range(len(planned_specs)), key=lambda i: planned_specs[i][1])
                seg, dur, r = planned_specs[longest_idx]
                half = round(dur / 2.0, 2)
                planned_specs[longest_idx] = (seg, half, f"{r}_A")
                planned_specs.insert(longest_idx + 1, (seg, round(dur - half, 2), f"{r}_B"))
        elif len(planned_specs) > num_candidates:
            while len(planned_specs) > num_candidates:
                shortest_idx = min(range(len(planned_specs) - 1), key=lambda i: planned_specs[i][1] + planned_specs[i+1][1])
                s1, d1, r1 = planned_specs[shortest_idx]
                s2, d2, r2 = planned_specs[shortest_idx + 1]
                planned_specs[shortest_idx] = (s1, round(d1 + d2, 2), r1)
                planned_specs.pop(shortest_idx + 1)

        # Final duration calibration
        cur_sum = sum(d for _, d, _ in planned_specs)
        diff = round(total_duration - cur_sum, 2)
        if abs(diff) > 0.001 and planned_specs:
            s_last, d_last, r_last = planned_specs[-1]
            planned_specs[-1] = (s_last, round(max(0.5, d_last + diff), 2), r_last)

        # 4. Synchronize Shots & Align Action Peaks
        synchronized_shots: List[SynchronizedShot] = []
        updated_shots_data: List[Dict[str, Any]] = []
        current_time = 0.0
        action_sync_count = 0
        recent_scene_urls: List[str] = []

        total_shots = len(shots_data)
        for i in range(total_shots):
            shot = dict(shots_data[i])
            sid = shot.get("shot_id", f"shot_{i+1}")
            seg, shot_dur, role = planned_specs[i]
            asset = asset_map.get(sid)

            shot_start = round(current_time, 2)
            shot_end = round(current_time + shot_dur, 2)

            # Check consecutive-scene protection
            asset_url = getattr(asset, "source_url", "") or getattr(asset, "local_path", "")
            if recent_scene_urls and asset_url and asset_url == recent_scene_urls[-1]:
                logger.warning(f"[COMPOSITION] Consecutive-scene duplicate detected for shot {sid}: {asset_url}. Preserving diversity.")

            # Memory evaluation if available
            if self.visual_memory and asset:
                from .memory import extract_canonical_source_id
                canon_id = extract_canonical_source_id(asset_url)
                if canon_id and canon_id in [extract_canonical_source_id(u) for u in recent_scene_urls[-1:]]:
                    logger.warning(f"[COMPOSITION] Consecutive canonical ID reuse detected: {canon_id}")

            recent_scene_urls.append(asset_url)

            # Candidate mock/wrapper for alignment
            local_p = Path(getattr(asset, "local_path", "")) if asset and getattr(asset, "local_path", None) else None
            cand_wrapper = NormalizedVideoCandidate(
                source_name=getattr(asset, "source", "real_video"),
                source_type=SourceType.INTERNET_REAL,
                title=shot.get("search_query", "Historical Scene"),
                duration=max(shot_dur, float(shot.get("duration", shot_dur))),
                local_path=str(local_p) if local_p else None
            )

            # Action Anchor Alignment
            action_time = seg.action_anchor_time
            clip_in, clip_out, action_tl, action_offset = ActionAnchorAligner.align_shot_action(
                shot_start_timeline=shot_start,
                shot_duration=shot_dur,
                action_word_timeline=action_time,
                source_candidate=cand_wrapper
            )
            if action_tl is not None:
                action_sync_count += 1

            is_hook = (i == 0 or "HOOK" in role)
            is_ending = (i == total_shots - 1 or "LOOP" in role or "OUTRO" in role)

            # Ending / Loop Strategy: verify that outro visual feels intentional
            if is_ending and len(script_parts) > 0:
                loop_text = script_parts[-1][1].lower()
                has_loop_intent = any(k in loop_text for k in ["again", "today", "still", "cycle", "loop", "returns", "repeat", "never"])
                if has_loop_intent:
                    shot["loop_callback"] = True

            # Update shot dictionary for render engine
            shot["start_time"] = shot_start
            shot["end_time"] = shot_end
            shot["duration"] = round(shot_dur, 2)
            shot["source_clip_in"] = clip_in
            shot["narrative_role"] = role
            shot["action_peak_timeline"] = action_tl
            shot["action_peak_clip_offset"] = action_offset
            shot["is_hook"] = is_hook
            shot["is_ending"] = is_ending

            synced_shot = SynchronizedShot(
                shot_id=sid,
                shot_index=i,
                timeline_start=shot_start,
                timeline_end=shot_end,
                duration=round(shot_dur, 2),
                narration_text=seg.text,
                narrative_role=role,
                candidate=cand_wrapper,
                video_path=local_p or Path(""),
                source_clip_in=clip_in,
                source_clip_out=clip_out,
                action_peak_timeline=action_tl,
                action_peak_clip_offset=action_offset,
                is_hook=is_hook,
                is_ending=is_ending,
                editorial_reason=f"Role: {role}, Action: {seg.action_type or 'None'}"
            )
            synchronized_shots.append(synced_shot)
            updated_shots_data.append(shot)
            current_time = shot_end

        avg_dur = round(total_duration / float(len(synchronized_shots)), 2)
        composition = EditorialComposition(
            composition_id=f"comp_{uuid.uuid4().hex[:8]}",
            total_duration=round(total_duration, 2),
            shots=synchronized_shots,
            timeline=timeline,
            shot_density=len(synchronized_shots),
            avg_shot_duration=avg_dur,
            action_sync_count=action_sync_count,
            metadata={
                "job_id": job_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "action_anchors_detected": len(timeline.get_action_anchors())
            }
        )

        logger.info(
            f"[EDITORIAL_COMPOSITION] Timeline composed: {len(synchronized_shots)} shots "
            f"across {total_duration:.2f}s (Avg Shot: {avg_dur:.2f}s, Action Syncs: {action_sync_count})"
        )
        return composition, updated_shots_data
