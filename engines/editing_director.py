"""
Editing Director Engine.
Autonomous AI directing layer that formulates a per-scene EditingPlan:
semantic scene role classification, restrained transition selection,
camera motion design, and contextual SFX cue placement.
"""
import uuid
import json
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from sqlalchemy.orm import Session
from config.settings import GEMINI_API_KEY, GEMINI_MODEL
from core.models import Topic, ScriptRecord, AssetRecord
from engines.sfx_manager import SFX_CATALOG

logger = logging.getLogger(__name__)

# Valid Semantic Roles
VALID_ROLES = [
    "HOOK", "SETUP", "ESCALATION", "REVEAL", "IMPACT",
    "EMOTION", "EXPLANATION", "CLIMAX", "OUTRO"
]

# Valid Motion Profiles
VALID_MOTIONS = [
    "none", "subtle_zoom_in", "subtle_zoom_out",
    "slow_pan_left", "slow_pan_right", "dynamic_reframe"
]

# Valid Transitions
VALID_TRANSITIONS = ["cut", "crossfade", "dip_to_black", "wipe_left"]


@dataclass
class SFXCue:
    sfx_id: str
    start_time: float
    duration: float = 1.5
    volume_db: float = -20.0
    fade_in_sec: float = 0.05
    fade_out_sec: float = 0.3
    reason: str = ""
    priority: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SceneEditingDirective:
    shot_id: str
    shot_index: int
    start_time: float
    duration: float
    narrative_role: str
    intensity: str  # LOW, MEDIUM, HIGH, CLIMAX
    transition_in: str  # cut, crossfade, dip_to_black, wipe_left
    transition_duration: float
    camera_motion: str  # none, subtle_zoom_in, subtle_zoom_out, slow_pan_left, slow_pan_right, dynamic_reframe
    caption_style: str  # standard, punchy_hook, highlight_reveal, climax_burst
    sfx_cues: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EditingPlan:
    job_id: str
    topic_title: str
    overall_profile: str
    scenes: List[SceneEditingDirective] = field(default_factory=list)
    sfx_anti_repetition_applied: bool = True
    total_sfx_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "topic_title": self.topic_title,
            "overall_profile": self.overall_profile,
            "scenes": [s.to_dict() for s in self.scenes],
            "sfx_anti_repetition_applied": self.sfx_anti_repetition_applied,
            "total_sfx_count": self.total_sfx_count
        }


class EditingDirector:
    """Directs editing decisions for pacing, camera motion, transitions, and audio-visual emphasis."""

    def __init__(self):
        pass

    def classify_story_profile(self, category: str, title: str, script_text: str) -> str:
        """Determines overarching editing style profile."""
        text = f"{category} {title} {script_text}".lower()
        if any(k in text for k in ["myster", "secret", "strange", "baffling", "unexplained", "phenomenon", "enigma", "riddle", "cipher"]):
            return "MYSTERY"
        elif any(k in text for k in ["war", "battle", "crusade", "empire", "king", "army", "monarch", "rebellion", "siege"]):
            return "WAR_POLITICS"
        elif any(k in text for k in ["disaster", "flood", "explosion", "tsunami", "molasses", "erupt", "volcano", "cataclysm"]):
            return "DISASTER"
        elif any(k in text for k in ["tragedy", "grief", "poignant", "mourn", "sacrifice", "famine", "plague", "sorrow"]):
            return "TRAGEDY"
        return "GENERAL_DOCUMENTARY"

    def plan_editing(
        self,
        db: Session,
        job_id: str,
        topic: Topic,
        script: ScriptRecord,
        shots: List[Dict[str, Any]],
        asset_map: Optional[Dict[str, AssetRecord]] = None
    ) -> EditingPlan:
        """
        Formulates an authoritative per-scene editing plan.
        Prioritizes story-driven restraint: no over-editing, clean cuts where appropriate,
        subtle motion, and max 1-2 intentional SFX cues.
        """
        profile = self.classify_story_profile(
            topic.category or "",
            topic.title or "",
            script.full_text or ""
        )

        # 1. Attempt AI-driven director planning if Gemini is available
        plan = None
        if GEMINI_API_KEY:
            plan = self._generate_ai_editing_plan(job_id, topic, script, shots, profile, asset_map)

        # 2. Fall back cleanly to deterministic rules if AI is unavailable or fails validation
        if not plan or len(plan.scenes) != len(shots):
            plan = self._generate_deterministic_editing_plan(job_id, topic, script, shots, profile, asset_map)

        # 3. Enforce strict anti-repetition on SFX cues
        self._enforce_sfx_anti_repetition(plan)

        logger.info(
            f"[EDITING_DIRECTOR] Formulated Editing Plan for Job {job_id[:8]}: "
            f"Profile={plan.overall_profile}, Scenes={len(plan.scenes)}, SFX Cues={plan.total_sfx_count}"
        )
        return plan

    def _generate_deterministic_editing_plan(
        self,
        job_id: str,
        topic: Topic,
        script: ScriptRecord,
        shots: List[Dict[str, Any]],
        profile: str,
        asset_map: Optional[Dict[str, AssetRecord]] = None
    ) -> EditingPlan:
        """
        Generates calibrated, deterministic editing directives using classical documentary grammar.
        """
        directives = []
        current_time = 0.0
        num_shots = len(shots)

        for i, s in enumerate(shots):
            dur = float(s.get("duration", 4.5))
            shot_id = s.get("shot_id", f"shot_{i+1}")
            asset = asset_map.get(shot_id) if asset_map else None
            is_video = bool(asset and getattr(asset, "asset_type", "") == "video")

            # Determine Narrative Role & Intensity by narrative progression
            if i == 0:
                role = "HOOK"
                intensity = "HIGH"
                trans = "cut"
                trans_dur = 0.0
                motion = "none" if is_video else "subtle_zoom_in"
                caption = "punchy_hook"
                sfx = []
                if profile in ["MYSTERY", "DISASTER"]:
                    sfx.append(SFXCue(
                        sfx_id="tension_riser" if profile == "MYSTERY" else "distant_thunder_rumble",
                        start_time=0.0,
                        duration=1.8,
                        volume_db=-22.0,
                        reason="Hook atmosphere builder"
                    ).to_dict())
            elif i == 1:
                role = "SETUP"
                intensity = "MEDIUM"
                trans = "cut"
                trans_dur = 0.0
                motion = "slow_pan_left" if not is_video else "none"
                caption = "standard"
                sfx = []
                if "law" in topic.title.lower() or "decree" in topic.title.lower():
                    sfx.append(SFXCue(
                        sfx_id="subtle_paper_turn",
                        start_time=round(current_time + 0.5, 2),
                        duration=1.0,
                        volume_db=-24.0,
                        reason="Historical document texture"
                    ).to_dict())
            elif i == 2:
                role = "ESCALATION"
                intensity = "MEDIUM"
                trans = "cut" if i % 2 == 0 else "crossfade"
                trans_dur = 0.25 if trans == "crossfade" else 0.0
                motion = "subtle_zoom_in" if not is_video else "none"
                caption = "standard"
                sfx = []
            elif i == 3 or (i == num_shots - 2 and num_shots > 3):
                role = "REVEAL"
                intensity = "CLIMAX"
                trans = "crossfade" if profile in ["MYSTERY", "TRAGEDY"] else "cut"
                trans_dur = 0.25 if trans == "crossfade" else 0.0
                motion = "subtle_zoom_out" if not is_video else "none"
                caption = "highlight_reveal"
                sfx = []
                # Add singular impactful reveal SFX
                sfx.append(SFXCue(
                    sfx_id="impact_boom" if profile in ["DISASTER", "WAR_POLITICS"] else "tension_riser",
                    start_time=round(current_time + 0.2, 2),
                    duration=1.8,
                    volume_db=-19.0,
                    reason="Major narrative reveal emphasis"
                ).to_dict())
            else:
                role = "CLIMAX" if i == num_shots - 1 else "EXPLANATION"
                intensity = "HIGH" if i == num_shots - 1 else "LOW"
                trans = "cut"
                trans_dur = 0.0
                motion = "none"
                caption = "climax_burst" if i == num_shots - 1 else "standard"
                sfx = []

            directive = SceneEditingDirective(
                shot_id=shot_id,
                shot_index=i,
                start_time=round(current_time, 2),
                duration=round(dur, 2),
                narrative_role=role,
                intensity=intensity,
                transition_in=trans,
                transition_duration=trans_dur,
                camera_motion=motion,
                caption_style=caption,
                sfx_cues=sfx,
                reason=f"Classical {role} pacing for {profile} genre"
            )
            directives.append(directive)
            current_time += dur

        return EditingPlan(
            job_id=job_id,
            topic_title=topic.title,
            overall_profile=profile,
            scenes=directives
        )

    def _generate_ai_editing_plan(
        self,
        job_id: str,
        topic: Topic,
        script: ScriptRecord,
        shots: List[Dict[str, Any]],
        profile: str,
        asset_map: Optional[Dict[str, AssetRecord]] = None
    ) -> Optional[EditingPlan]:
        """Queries Gemini for refined contextual directorial plan with strict JSON validation."""
        try:
            from core.gemini_client import get_gemini_client
            gemini_client = get_gemini_client()

            shots_desc = []
            for idx, s in enumerate(shots):
                shots_desc.append({
                    "index": idx,
                    "shot_id": s.get("shot_id"),
                    "duration": s.get("duration"),
                    "narration": s.get("narration_segment", ""),
                    "query": s.get("search_query", "")
                })

            prompt = (
                f"You are a master documentary film editor directing a short 20-25s historical Short.\n"
                f"Topic: {topic.title} ({topic.category})\n"
                f"Profile: {profile}\n"
                f"Script: {script.full_text}\n"
                f"Shots: {json.dumps(shots_desc, indent=2)}\n\n"
                f"For EACH shot, assign:\n"
                f"1. narrative_role: HOOK | SETUP | ESCALATION | REVEAL | IMPACT | EMOTION | EXPLANATION | CLIMAX | OUTRO\n"
                f"2. intensity: LOW | MEDIUM | HIGH | CLIMAX\n"
                f"3. transition_in: cut | crossfade | dip_to_black | wipe_left (Rule: Default to 'cut'. Use crossfade only for temporal shifts)\n"
                f"4. camera_motion: none | subtle_zoom_in | subtle_zoom_out | slow_pan_left | slow_pan_right\n"
                f"5. caption_style: standard | punchy_hook | highlight_reveal | climax_burst\n"
                f"6. sfx_cues: list of 0 or 1 SFX (from: impact_boom, tension_riser, cinematic_whoosh, subtle_paper_turn, distant_thunder_rumble, clock_tick_suspense, bell_toll_somber). IMPORTANT: Maximum 2 SFX cues in total for the whole Short!\n"
                f"7. reason: 1 short sentence justification.\n\n"
                f"Respond ONLY in valid JSON matching:\n"
                f'{{\n'
                f'  "overall_profile": "{profile}",\n'
                f'  "scenes": [\n'
                f'    {{\n'
                f'      "shot_id": "string",\n'
                f'      "narrative_role": "HOOK",\n'
                f'      "intensity": "HIGH",\n'
                f'      "transition_in": "cut",\n'
                f'      "camera_motion": "none",\n'
                f'      "caption_style": "punchy_hook",\n'
                f'      "sfx_id": "tension_riser" | null,\n'
                f'      "reason": "string"\n'
                f'    }}\n'
                f'  ]\n'
                f'}}'
            )

            response = gemini_client.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            clean_json = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)

            ai_scenes = data.get("scenes", [])
            if len(ai_scenes) != len(shots):
                return None

            directives = []
            curr_time = 0.0
            for idx, s in enumerate(shots):
                ai_s = ai_scenes[idx]
                dur = float(s.get("duration", 4.5))
                shot_id = s.get("shot_id", f"shot_{idx+1}")
                role = ai_s.get("narrative_role", "SETUP")
                if role not in VALID_ROLES:
                    role = "SETUP"

                trans = ai_s.get("transition_in", "cut")
                if trans not in VALID_TRANSITIONS:
                    trans = "cut"
                trans_dur = 0.25 if trans in ["crossfade", "dip_to_black", "wipe_left"] else 0.0

                motion = ai_s.get("camera_motion", "none")
                if motion not in VALID_MOTIONS:
                    motion = "none"

                caption = ai_s.get("caption_style", "standard")
                sfx_list = []
                sfx_name = ai_s.get("sfx_id")
                if sfx_name and sfx_name in SFX_CATALOG:
                    sfx_list.append(SFXCue(
                        sfx_id=sfx_name,
                        start_time=round(curr_time + 0.2, 2),
                        duration=1.8,
                        volume_db=SFX_CATALOG[sfx_name]["default_volume_db"],
                        reason=ai_s.get("reason", "AI selected context sound")
                    ).to_dict())

                directives.append(SceneEditingDirective(
                    shot_id=shot_id,
                    shot_index=idx,
                    start_time=round(curr_time, 2),
                    duration=round(dur, 2),
                    narrative_role=role,
                    intensity=ai_s.get("intensity", "MEDIUM"),
                    transition_in=trans,
                    transition_duration=trans_dur,
                    camera_motion=motion,
                    caption_style=caption,
                    sfx_cues=sfx_list,
                    reason=f"[AI Directed] {ai_s.get('reason', '')}"
                ))
                curr_time += dur

            return EditingPlan(
                job_id=job_id,
                topic_title=topic.title,
                overall_profile=data.get("overall_profile", profile),
                scenes=directives
            )
        except Exception as e:
            logger.warning(f"AI Editing Plan generation notice: {e}. Utilizing deterministic director.")
            return None

    def _enforce_sfx_anti_repetition(self, plan: EditingPlan) -> None:
        """
        Enforces sound design restraint:
        1. Max 2-3 SFX cues per entire Short.
        2. No identical SFX back-to-back.
        3. Cleans up redundant or duplicate cues.
        """
        seen_sfx = set()
        total_sfx = 0
        max_allowed_sfx = 3

        for sc in plan.scenes:
            filtered_cues = []
            for cue in sc.sfx_cues:
                sid = cue.get("sfx_id")
                if sid not in seen_sfx and total_sfx < max_allowed_sfx:
                    filtered_cues.append(cue)
                    seen_sfx.add(sid)
                    total_sfx += 1
                else:
                    logger.debug(f"[ANTI-REPETITION] Dropping redundant SFX '{sid}' in shot {sc.shot_id}")
            sc.sfx_cues = filtered_cues

        plan.total_sfx_count = total_sfx
        plan.sfx_anti_repetition_applied = True
