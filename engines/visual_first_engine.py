"""
Visual-First / Footage-Driven Script & Assembly Engine.
======================================================
NEW PARADIGM: First Clips, Scenes, and Visuals -> THEN Script!

How it works:
1. Selects the chronological sequence of 12-15 cinematic shots from the movie's
   Rich Scene Blueprint (with exact characters, action, environment, and SDH subtitles).
2. The LLM is fed the exact visual sequence: it writes the voiceover narration
   to describe and synchronize with what the audience is PHYSICALLY seeing on screen.
3. Every beat is pre-locked to its exact clip file (1080x1080) and timestamp.
4. Zero mismatch. Zero random B-roll. 100% synchronized storytelling.
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv

from google import genai

logger = logging.getLogger("alamr.visual_first")

PROJECT_ROOT = Path("C:/Users/jisha/OneDrive/Desktop/yt automation")
load_dotenv(PROJECT_ROOT / ".env")

VAULT_BASE = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\vault")


class VisualFirstEngine:
    """
    Selects the visual footage sequence first, then crafts the voiceover script
    specifically tailored to those shots.
    """

    def __init__(self, client: Optional[genai.Client] = None):
        api_key = os.environ.get("GEMINI_API_KEY")
        self.client = client or genai.Client(api_key=api_key)

    def load_blueprint(self, movie_slug: str) -> Dict[str, Any]:
        """Loads the rich scene blueprint for a movie."""
        asset_dir = VAULT_BASE / f"assets_{movie_slug}"
        bp_path = asset_dir / f"{movie_slug}_rich_scene_blueprint.json"
        if not bp_path.exists():
            matches = list(asset_dir.glob("*rich_scene_blueprint*.json"))
            if matches:
                bp_path = matches[0]
            else:
                raise FileNotFoundError(f"No blueprint found for {movie_slug} at {asset_dir}")

        with open(bp_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def select_visual_sequence(
        self,
        movie_slug: str,
        part_number: int,
        total_parts: int = 10,
        target_shots: int = 14
    ) -> List[Dict[str, Any]]:
        """
        Selects a sequential, chronological arc of high-narrative shots for this episode.
        Filters out credits, black screens, and static filler.
        """
        blueprint = self.load_blueprint(movie_slug)
        all_shots = blueprint.get("shots", [])
        if not all_shots:
            raise ValueError(f"Blueprint for {movie_slug} contains no shots!")

        # Chronological window for this Part
        total_count = len(all_shots)
        span = total_count / max(1, total_parts)
        window_start = int((part_number - 1) * span)
        window_end = min(total_count, int(window_start + span * 1.25))

        candidates = all_shots[window_start:window_end]

        # Filter out credits, black screens, and static filler
        valid_shots = []
        for s in candidates:
            env = str(s.get("environment", "")).lower()
            act = str(s.get("action", "")).lower()
            if "credit" in env or "black screen" in env or "credit" in act:
                continue
            if not s.get("has_clip", True):
                continue
            valid_shots.append(s)

        if len(valid_shots) < target_shots:
            # Expand window slightly if needed
            valid_shots = [
                s for s in all_shots[max(0, window_start - 10):min(total_count, window_end + 15)]
                if "credit" not in str(s.get("environment", "")).lower() and s.get("has_clip", True)
            ]

        # Chronological Binning: divide window into target_shots sequential segments
        # In each bin, pick the most dramatic, character-rich shot!
        def shot_richness(s):
            score = 0.0
            chars = s.get("characters", [])
            act = str(s.get("action", "")).lower()
            env = str(s.get("environment", "")).lower()
            sdh = str(s.get("sdh_context", "")).lower()

            if chars and len(chars) > 0:
                score += 4.0
            if act and act not in ["none", "scene action", "scene_action", "unknown"]:
                score += 3.0
            if "[" in sdh or "(" in sdh or "screaming" in sdh or "gun" in sdh or len(sdh) > 20:
                score += 2.5
            if env and env not in ["unknown", "exterior scene", "exterior"]:
                score += 1.5
            return score

        if len(valid_shots) <= target_shots:
            selected = valid_shots
        else:
            selected = []
            bin_size = len(valid_shots) / float(target_shots)
            for b in range(target_shots):
                start_i = int(b * bin_size)
                end_i = max(start_i + 1, int((b + 1) * bin_size))
                bin_candidates = valid_shots[start_i:end_i]
                best_in_bin = max(bin_candidates, key=shot_richness)
                selected.append(best_in_bin)

        logger.info(f"[VISUAL_FIRST] Selected {len(selected)} rich visual shots for {movie_slug} Part {part_number}/{total_parts}")
        return selected

    def write_script_for_visuals(
        self,
        movie_title: str,
        movie_slug: str,
        part_number: int,
        total_parts: int,
        selected_shots: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Feeds the exact visual shots into Gemini and generates a voiceover narration
        where EACH BEAT directly describes the visuals on screen.
        """
        # Build the exact shot prompt ledger
        shots_summary = []
        for idx, s in enumerate(selected_shots, 1):
            shots_summary.append(
                f"SHOT {idx} ({s['shot_id']}, ts: {s['timestamp_sec']}s):\n"
                f"  - Setting/Environment: {s.get('environment', 'unknown')}\n"
                f"  - Characters: {', '.join(s.get('characters', [])) or 'Nobody visible'}\n"
                f"  - Physical Action: {s.get('action', 'none')}\n"
                f"  - Camera Framing: {s.get('movement', 'medium shot')}\n"
                f"  - Dialogue/Audio cue: {s.get('sdh_context', 'none')}"
            )
        shots_text = "\n\n".join(shots_summary)

        prompt = f"""You are a master horror/thriller movie recap director creating an intense 55-second YouTube Short recap.

IMPORTANT NEW RULE: THE VISUAL FOOTAGE HAS ALREADY BEEN EDITED AND LOCKED IN THIS EXACT ORDER.
You must write the voiceover narration SO THAT EACH LINE MATCHES EXACTLY WHAT IS PHYSICALLY ON SCREEN!

MOVIE: {movie_title} (Part {part_number} of {total_parts})

HERE ARE THE {len(selected_shots)} SHOTS IN EXACT CHRONOLOGICAL ORDER:
{shots_text}

INSTRUCTIONS:
1. Write EXACTLY {len(selected_shots)} voiceover sentences (one sentence per shot, sequence 1 to {len(selected_shots)}).
2. For each shot: describe what the characters are doing, the danger, and the environment shown in THAT specific shot.
3. Language: Simple, breathless, everyday English (Subject -> Verb -> Object). No fancy poetry.
4. Word count per sentence: 7 to 10 simple words (~3 to 3.5 seconds spoken).
5. Total word count for all sentences combined: 125 to 140 words total.
6. The final sentence must be a high-stakes cliffhanger urging viewers to subscribe for Part {part_number + 1 if part_number < total_parts else 'the finale'}.
7. Determine if each shot is an "impact" moment (physical strike, sudden crash, weapon swing) -> set "is_impact": true (for stylized noir desaturation).

Return raw valid JSON strictly adhering to this format:
{{
  "yt_title": "{movie_title} Part {part_number} | Intense Horror Recap #Shorts",
  "yt_description": "Part {part_number} recap of {movie_title}. What happens next will shock you! #Shorts #MovieRecap #{movie_slug.replace('_', '')}",
  "beats": [
    {{
      "sequence": 1,
      "shot_id": "{selected_shots[0]['shot_id']}",
      "sentence": "Spoken voiceover line matching Shot 1 exactly.",
      "is_impact": false
    }}
  ]
}}
"""

        # Generate using Groq Qwen (instantaneous, high-token limit) with Gemini fallback
        raw_text = ""
        groq_key = os.environ.get("GROQ_API_KEY")
        if groq_key:
            try:
                import openai
                g_client = openai.OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_key)
                g_resp = g_client.chat.completions.create(
                    model="qwen/qwen3.8-27b",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1200
                )
                raw_text = g_resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"[VISUAL_FIRST] Groq generation failed ({e}), falling back...")

        if not raw_text:
            try:
                resp = self.client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=[prompt]
                )
                raw_text = resp.text.strip()
            except Exception as e:
                logger.warning(f"[VISUAL_FIRST] Gemini generation failed ({e}), trying OpenRouter...")
                import openai
                o_client = openai.OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ.get("OPENROUTER_API_KEY"))
                o_resp = o_client.chat.completions.create(
                    model="nvidia/nemotron-3.5-lightning:free",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=1200
                )
                raw_text = o_resp.choices[0].message.content.strip()

        raw_text = re.sub(r"^```json\s*", "", raw_text, flags=re.IGNORECASE)
        raw_text = re.sub(r"^```\s*", "", raw_text)
        raw_text = re.sub(r"\s*```$", "", raw_text)

        # Extract JSON object substring if model wrapped it in chat commentary
        json_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if json_match:
            raw_text = json_match.group(1)

        data = json.loads(raw_text)

        # Merge with shot metadata for full assembly packet
        beats_out = []
        for idx, (b, s) in enumerate(zip(data.get("beats", []), selected_shots), 1):
            beats_out.append({
                "sequence": idx,
                "shot_id": s["shot_id"],
                "clip_file": s["clip_file"],
                "frame_file": s["frame_file"],
                "timestamp_sec": s["timestamp_sec"],
                "duration_sec": s.get("duration_sec", 3.5),
                "sentence": b.get("sentence", "").strip(),
                "is_impact": b.get("is_impact", False),
                "visual_environment": s.get("environment"),
                "visual_action": s.get("action"),
                "visual_characters": s.get("characters"),
                "sdh_cues": s.get("sdh_context")
            })

        total_words = sum(len(b["sentence"].split()) for b in beats_out)
        logger.info(f"[VISUAL_FIRST] Generated script: {len(beats_out)} beats, {total_words} words total.")

        return {
            "movie_slug": movie_slug,
            "movie_title": movie_title,
            "part_number": part_number,
            "total_parts": total_parts,
            "yt_title": data.get("yt_title", f"{movie_title} Part {part_number} #Shorts"),
            "yt_description": data.get("yt_description", f"Part {part_number} recap of {movie_title}."),
            "total_words": total_words,
            "beats": beats_out
        }

    def generate_episode_packet(
        self,
        movie_slug: str,
        movie_title: str,
        part_number: int,
        total_parts: int = 10,
        target_shots: int = 14
    ) -> Dict[str, Any]:
        """
        Complete one-stop Visual-First generator:
        1. Selects footage first.
        2. Writes matching script.
        3. Returns full production-ready packet.
        """
        shots = self.select_visual_sequence(movie_slug, part_number, total_parts, target_shots)
        packet = self.write_script_for_visuals(movie_title, movie_slug, part_number, total_parts, shots)
        return packet
