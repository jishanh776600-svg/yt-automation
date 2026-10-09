"""
Semantic Blueprint Matcher for Autonomous Video Pipelines.
===========================================================
Eliminates random B-roll mismatch by matching script narration beats against
the rich Vision + SDH Scene Blueprint ledger for each movie.

Matches based on:
1. Visible Characters (identities, mutant/predator, counts)
2. Environment / Setting (cabin, under bed, gas station, desert, slaughterhouse)
3. Physical Action & Movement (hiding, running, screaming, tire slashing)
4. Exact SDH Subtitle cues (dialogue, sound effects [FOOTSTEPS], speaker names)
5. Chronological windowing per episode (Ep 1 = beginning, Ep 16 = climax)
6. Duplicate suppression (no repeated shots within the same episode)
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

logger = logging.getLogger("alamr.blueprint_matcher")

VAULT_BASE = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\vault")


class SemanticBlueprintMatcher:
    """
    Finds the exact cinematic shot from the movie's Rich Scene Blueprint
    that matches the narrative beat's characters, environment, action, and sound cues.
    """

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_base = vault_dir or VAULT_BASE
        self._blueprints: Dict[str, Dict[str, Any]] = {}
        self._used_shots: Dict[str, Set[str]] = {}

    def load_blueprint(self, movie_slug: str) -> Optional[Dict[str, Any]]:
        """Loads rich_scene_blueprint.json for the specified movie."""
        if movie_slug in self._blueprints:
            return self._blueprints[movie_slug]

        asset_folder = self.vault_base / f"assets_{movie_slug}"
        if not asset_folder.exists():
            # Try alternate naming
            candidates = list(self.vault_base.glob(f"*{movie_slug}*"))
            if candidates:
                asset_folder = candidates[0]

        blueprint_path = asset_folder / f"{movie_slug}_rich_scene_blueprint.json"
        if not blueprint_path.exists():
            # Look for any rich_scene_blueprint in the directory
            matches = list(asset_folder.glob("*rich_scene_blueprint*.json"))
            if matches:
                blueprint_path = matches[0]

        if not blueprint_path.exists():
            logger.warning(f"[BLUEPRINT_MATCHER] Blueprint not found at {blueprint_path}")
            return None

        try:
            with open(blueprint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._blueprints[movie_slug] = data
                logger.info(f"[BLUEPRINT_MATCHER] Loaded {len(data.get('shots', []))} rich shots for {movie_slug}")
                return data
        except Exception as e:
            logger.error(f"[BLUEPRINT_MATCHER] Error reading {blueprint_path}: {e}")
            return None

    def reset_used_shots(self, episode_key: str):
        """Clears used shots tracker for a new episode."""
        self._used_shots[episode_key] = set()

    def find_best_shot(
        self,
        movie_slug: str,
        narration_text: str,
        episode_index: int = 1,
        total_episodes: int = 8,
        action_hint: Optional[str] = None,
        environment_hint: Optional[str] = None,
        character_hint: Optional[str] = None,
        episode_key: Optional[str] = None,
        chronological_bias: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Queries the movie blueprint to find the single best matching shot for a narration beat.
        """
        blueprint = self.load_blueprint(movie_slug)
        if not blueprint or not blueprint.get("shots"):
            return None

        all_shots = blueprint["shots"]
        used = self._used_shots.get(episode_key, set()) if episode_key else set()

        # Chronological target window
        progress_ratio = max(0.0, min(1.0, (episode_index - 1) / max(1, total_episodes - 1)))
        window_size = 0.35  # Look within 35% of movie timeline around episode target
        center_idx = int(progress_ratio * len(all_shots))
        min_idx = max(0, int(center_idx - (window_size * len(all_shots) * 0.5)))
        max_idx = min(len(all_shots), int(center_idx + (window_size * len(all_shots) * 0.5)))

        # Clean search keywords from narration text
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "with", "by", "from", "up", "about", "into", "over", "after", "is",
            "are", "was", "were", "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "as", "if", "each", "how", "which", "their", "they"
        }
        words = re.findall(r"[a-z0-9]+", narration_text.lower())
        keywords = {w for w in words if w not in stop_words and len(w) > 2}

        if action_hint:
            keywords.update(re.findall(r"[a-z0-9]+", action_hint.lower()))
        if environment_hint:
            keywords.update(re.findall(r"[a-z0-9]+", environment_hint.lower()))
        if character_hint:
            keywords.update(re.findall(r"[a-z0-9]+", character_hint.lower()))

        scored_candidates = []

        for idx, shot in enumerate(all_shots):
            s_id = shot.get("shot_id", "")
            if s_id in used:
                continue

            env = str(shot.get("environment", "")).lower()
            act = str(shot.get("action", "")).lower()
            mov = str(shot.get("movement", "")).lower()
            sdh = str(shot.get("sdh_context", "")).lower()
            chars = [str(c).lower() for c in shot.get("characters", [])]
            chars_str = " ".join(chars)

            # Hard exclude: credits and black screen
            if "credit" in env or "black screen" in env or "credit" in act:
                continue

            score = 0.0

            # 1. Match Keywords against Environment
            env_hits = sum(1 for kw in keywords if kw in env)
            score += env_hits * 3.5

            # 2. Match Keywords against Physical Action
            act_hits = sum(1 for kw in keywords if kw in act)
            score += act_hits * 4.0

            # 3. Match Keywords against Characters
            char_hits = sum(1 for kw in keywords if kw in chars_str)
            score += char_hits * 5.0

            # 4. Match Keywords against SDH Subtitles (Dialogue & Sound cues)
            sdh_hits = sum(1 for kw in keywords if kw in sdh)
            score += sdh_hits * 3.0

            # 5. Chronological Proximity Bonus
            # Higher score if closer to the current episode's timeline position
            dist_from_center = abs(idx - center_idx)
            max_dist = max(1, len(all_shots))
            proximity_factor = 1.0 - (dist_from_center / max_dist)
            score += (proximity_factor * 2.5 * chronological_bias)

            # Bonus if shot is within chronological window
            if min_idx <= idx <= max_idx:
                score += 3.0

            # Quality bonus: shot has verified clip file on disk
            if shot.get("has_clip", False):
                score += 1.0

            scored_candidates.append((score, shot))

        if not scored_candidates:
            # Fallback to closest unused shot in window
            for idx in range(min_idx, max_idx):
                if idx < len(all_shots) and all_shots[idx].get("shot_id") not in used:
                    chosen = all_shots[idx]
                    if episode_key:
                        self._used_shots.setdefault(episode_key, set()).add(chosen["shot_id"])
                    return chosen
            return all_shots[min(len(all_shots) - 1, center_idx)]

        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_shot = scored_candidates[0]

        if episode_key:
            self._used_shots.setdefault(episode_key, set()).add(best_shot["shot_id"])

        logger.info(
            f"[BLUEPRINT_MATCH] Matched '{best_shot['shot_id']}' (Score: {best_score:.1f}) | "
            f"Env: {best_shot.get('environment')} | Act: {best_shot.get('action')} | "
            f"SDH: {best_shot.get('sdh_context')[:60]}..."
        )

        return best_shot
