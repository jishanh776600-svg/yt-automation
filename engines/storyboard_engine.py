"""
Storyboard Engine.
Deconstructs script into 4-7 synchronized visual shots with camera motion and visual queries.
"""
import uuid
import logging
from typing import List, Dict, Any
from core.models import ScriptRecord

logger = logging.getLogger(__name__)


class StoryboardEngine:
    """Creates a visual breakdown matching script pacing and narration timing."""

    CAMERA_MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down"]

    def create_storyboard(self, script: ScriptRecord) -> List[Dict[str, Any]]:
        """
        Splits script into 5 structured visual shots with timing, motion, and visual queries.
        """
        segments = [
            {"name": "hook", "text": script.hook, "query": "dramatic historical monument landscape", "prompt": "Cinematic historical documentary scene, dramatic lighting, 8k resolution, authentic 19th century atmosphere"},
            {"name": "context", "text": script.context, "query": "old vintage architecture building europe", "prompt": "Authentic period accurate historical setting, vintage architectural detail, atmospheric cinematic tone"},
            {"name": "escalation", "text": script.escalation, "query": "historical army battleship storm tension", "prompt": "Intense cinematic historical conflict, dramatic smoke and dynamic lighting, realistic period costumes"},
            {"name": "reveal", "text": script.reveal, "query": "historical palace explosion victory", "prompt": "Cinematic climactic historical revelation, dramatic visual composition, detailed period accuracy"},
            {"name": "loop_twist", "text": script.loop_twist, "query": "cinematic sunset vintage landscape", "prompt": "Moody atmospheric ending shot, historical cinematic lighting, reflective wide shot"}
        ]

        total_duration = script.estimated_duration_sec
        # Allocate duration per shot
        durations = [3.5, 4.5, 6.0, 5.0, total_duration - 19.0]
        if durations[-1] < 3.0:
            durations[-1] = 3.5

        shots = []
        current_time = 0.0

        for i, seg in enumerate(segments):
            dur = durations[i]
            shot_id = f"shot_{i+1}_{uuid.uuid4().hex[:6]}"
            motion = self.CAMERA_MOTIONS[i % len(self.CAMERA_MOTIONS)]

            shot = {
                "shot_id": shot_id,
                "shot_index": i,
                "start_time": round(current_time, 2),
                "end_time": round(current_time + dur, 2),
                "duration": round(dur, 2),
                "narration_segment": seg["text"],
                "search_query": seg["query"],
                "visual_prompt": seg["prompt"],
                "camera_motion": motion,
                "transition": "crossfade" if i > 0 else "cut"
            }
            shots.append(shot)
            current_time += dur

        logger.info(f"Generated storyboard with {len(shots)} shots for script {script.id}")
        return shots
