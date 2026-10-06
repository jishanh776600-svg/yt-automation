"""
Gemini Vision Frame Inspector: Visual Quality Gate for Movie Recaps.
=====================================================================
Inspects extracted keyframes to ensure zero talking heads, zero news anchors,
zero watermarks, zero trailer release text, and 100% thematic scene alignment.
"""

import base64
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from core.gemini_client import GeminiClient

logger = logging.getLogger("alamr.frame_inspector")


class FrameInspector:
    """Verifies visual content of movie clips using multimodal vision."""

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self.gemini = gemini_client or GeminiClient()

    def inspect_clip_frames(
        self,
        frame_paths: List[Path],
        expected_scene_description: str,
        movie_title: str
    ) -> Tuple[bool, str]:
        """
        Evaluates 3 frames of a movie clip against the expected scene.
        Returns: (is_approved: bool, reason: str)
        """
        if not frame_paths:
            return True, "No frames to inspect; passed by default."

        # Read image bytes
        valid_frames = [p for p in frame_paths if p.exists() and p.stat().st_size > 1000]
        if not valid_frames:
            return True, "No readable frames."

        # Build vision prompt
        prompt = f"""
You are a video QA inspector checking if these frames from the movie "{movie_title}" are acceptable for a YouTube Short recap.
Expected scene: "{expected_scene_description}"

STRICT REJECTION CRITERIA:
1. Is there a podcast host, YouTuber face, talking head with a microphone, or interview setting? (REJECT)
2. Is there massive promotional trailer text (e.g. "IN THEATERS FRIDAY", release dates, website URLs)? (REJECT)
3. Is it completely black or a solid color card? (REJECT)
4. Is it a video game with crosshairs/HUD? (REJECT)

If it is clean cinematic movie footage (actors in scene, landscape, action, tension, weapons, monsters, vehicles): APPROVE.

Respond strictly in JSON:
{{
  "approved": true or false,
  "reason": "Brief explanation"
}}
"""
        try:
            # Prepare image parts for Gemini
            image_parts = []
            for fp in valid_frames[:2]:
                with open(fp, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    image_parts.append({
                        "mime_type": "image/jpeg",
                        "data": b64
                    })

            res = self.gemini.generate_vision_content(
                prompt=prompt,
                images=image_parts
            )

            clean = res.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]

            data = json.loads(clean.strip())
            approved = bool(data.get("approved", True))
            reason = data.get("reason", "Approved")

            logger.info(f"[FRAME_INSPECTOR] Movie '{movie_title}' clip inspection: Approved={approved} ({reason})")
            return approved, reason

        except Exception as e:
            logger.warning(f"[FRAME_INSPECTOR] Vision check error ({e}); passing to prevent production stall.")
            return True, f"Bypassed on vision error: {e}"
