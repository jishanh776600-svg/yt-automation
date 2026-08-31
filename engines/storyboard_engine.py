"""
Storyboard Engine.
Deconstructs script into 4-7 synchronized visual shots.
Dynamically generates story-specific, historical visual search queries and AI prompts via Gemini 3.6 Flash.
"""
import uuid
import json
import logging
from typing import List, Dict, Any
from core.models import ScriptRecord
from config.settings import GEMINI_API_KEY, AI_PROVIDER_AVAILABLE

logger = logging.getLogger(__name__)


class StoryboardEngine:
    """Creates a visual breakdown matching script pacing and narration timing."""

    CAMERA_MOTIONS = ["zoom_in", "zoom_out", "pan_left", "pan_right", "tilt_up", "tilt_down"]

    def create_storyboard(self, script: ScriptRecord) -> List[Dict[str, Any]]:
        """
        Splits script into 5 structured visual shots with topic-specific queries and motions.
        """
        raw_segments = [
            {"name": "hook", "text": script.hook},
            {"name": "context", "text": script.context},
            {"name": "escalation", "text": script.escalation},
            {"name": "reveal", "text": script.reveal},
            {"name": "loop_twist", "text": script.loop_twist}
        ]

        # 1. Use configured AI Provider to generate 5 story-specific search queries and AI prompts
        queries = []
        if AI_PROVIDER_AVAILABLE:
            try:
                from core.gemini_client import get_gemini_client
                gemini_client = get_gemini_client()
                prompt = (
                    f"Given this historical story script:\n"
                    f"Hook: {script.hook}\n"
                    f"Context: {script.context}\n"
                    f"Escalation: {script.escalation}\n"
                    f"Reveal: {script.reveal}\n"
                    f"Twist: {script.loop_twist}\n\n"
                    f"Generate 5 distinct, highly specific stock photo search queries (2-4 words each) "
                    f"and 5 cinematic visual prompts tailored exactly to this event.\n"
                    f"Return ONLY valid JSON format with a list of 5 objects, each having 'query' and 'prompt'."
                )
                from config.settings import GEMINI_MODEL
                response = gemini_client.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                clean_json = response.text.strip().replace("```json", "").replace("```", "").strip()
                queries = json.loads(clean_json)
            except Exception as e:
                logger.warning(f"Dynamic storyboard query generation fallback: {e}")

        # Fallback if Gemini unavailable
        if not queries or len(queries) < 5:
            topic_words = script.hook.split()[:4]
            base_kw = " ".join([w for w in topic_words if len(w) > 3])
            queries = [
                {"query": f"{base_kw} dramatic history", "prompt": f"Cinematic historical documentary scene of {base_kw}"},
                {"query": f"{base_kw} vintage architecture", "prompt": f"Historical setting during {base_kw}"},
                {"query": f"{base_kw} tension conflict", "prompt": f"Dramatic historical scene showing {base_kw}"},
                {"query": f"{base_kw} aftermath destruction", "prompt": f"Historical aftermath of {base_kw}"},
                {"query": f"{base_kw} memorial landscape", "prompt": f"Moody historical wide landscape of {base_kw}"}
            ]

        total_duration = script.estimated_duration_sec
        # Allocate duration per shot
        durations = [3.5, 4.5, 6.0, 5.0, total_duration - 19.0]
        if durations[-1] < 3.0:
            durations[-1] = 3.5

        shots = []
        current_time = 0.0

        for i, seg in enumerate(raw_segments):
            dur = durations[i]
            shot_id = f"shot_{i+1}_{uuid.uuid4().hex[:6]}"
            motion = self.CAMERA_MOTIONS[i % len(self.CAMERA_MOTIONS)]
            q_info = queries[i] if i < len(queries) else queries[0]

            shot = {
                "shot_id": shot_id,
                "shot_index": i,
                "start_time": round(current_time, 2),
                "end_time": round(current_time + dur, 2),
                "duration": round(dur, 2),
                "narration_segment": seg["text"],
                "search_query": q_info.get("query", "vintage historical event"),
                "visual_prompt": q_info.get("prompt", "Cinematic historical documentary scene, 8k resolution"),
                "camera_motion": motion,
                "transition": "crossfade" if i > 0 else "cut"
            }
            shots.append(shot)
            current_time += dur

        logger.info(f"Generated dynamic storyboard with {len(shots)} unique visual queries: {[s['search_query'] for s in shots]}")
        return shots
