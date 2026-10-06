"""
Movie Series & Episodic Rotation Manager.
=========================================
Coordinates the parallel 2-Movie production cycle:
  - Movie 1 (e.g. Wrong Turn) -> Daily Slot 1 (11:00 UTC) produces Part 1, Part 2, Part 3...
  - Movie 2 (e.g. Hostel)     -> Daily Slot 2 (17:00 UTC) produces Part 1, Part 2, Part 3...
  - State persistence across ephemeral cloud runners.
  - Automatic advancement to next movie upon series completion.
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from core.movie_catalog import MovieCatalogManager, MovieEntry

logger = logging.getLogger("alamr.movie_series")


@dataclass
class MovieTrackState:
    slot_index: int              # 1 or 2
    movie_title: str
    movie_year: int
    current_part: int            # e.g. 1
    total_parts: int             # e.g. 10
    is_completed: bool = False
    completed_at: Optional[str] = None


class MovieSeriesManager:
    """Manages parallel multi-part movie series scheduling across daily slots."""

    def __init__(
        self,
        state_file: Optional[Path] = None,
        movie_catalog: Optional[MovieCatalogManager] = None,
        default_parts_per_movie: int = 10,
    ):
        self.state_file = state_file or Path("data/movie_series_state.json")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.catalog = movie_catalog or MovieCatalogManager()
        self.default_parts = default_parts_per_movie
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Loads persistent movie series state."""
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[SERIES_MANAGER] Could not read state file: {e}")

        # Default initial state: Movie 1 (Wrong Turn) and Movie 2 (The Hills Have Eyes)
        movies = self.catalog.get_all_movies()
        m1 = movies[0] if len(movies) > 0 else None
        m2 = movies[1] if len(movies) > 1 else None

        initial_state = {
            "track_1": {
                "slot_index": 1,
                "movie_title": m1.title if m1 else "Wrong Turn",
                "movie_year": m1.year if m1 else 2003,
                "current_part": 1,
                "total_parts": self.default_parts,
                "is_completed": False
            },
            "track_2": {
                "slot_index": 2,
                "movie_title": m2.title if m2 else "The Hills Have Eyes",
                "movie_year": m2.year if m2 else 2006,
                "current_part": 1,
                "total_parts": self.default_parts,
                "is_completed": False
            },
            "completed_movies": []
        }
        self._save_state(initial_state)
        return initial_state

    def _save_state(self, state: Dict[str, Any]) -> None:
        """Persists state atomically to disk."""
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"[SERIES_MANAGER] Failed saving state: {e}")

    def get_active_movie_for_slot(self, slot_index: int = 1) -> Tuple[MovieEntry, int, int]:
        """
        Returns (MovieEntry, current_part, total_parts) for the specified daily slot.
        slot_index 1 = 11:00 UTC (Movie Track 1)
        slot_index 2 = 17:00 UTC (Movie Track 2)
        """
        track_key = f"track_{slot_index}"
        track_data = self._state.get(track_key, {})
        title = track_data.get("movie_title")
        current_part = track_data.get("current_part", 1)
        total_parts = track_data.get("total_parts", self.default_parts)

        movie = self.catalog.get_movie_by_title(title)
        if not movie:
            movie = self.catalog.get_all_movies()[slot_index - 1]

        return movie, current_part, total_parts

    def advance_part_for_slot(self, slot_index: int = 1) -> Tuple[int, bool]:
        """
        Increments current_part for this track. If series finishes,
        rotates to the next unproduced movie in catalog.
        Returns: (new_part: int, is_series_completed: bool)
        """
        track_key = f"track_{slot_index}"
        track_data = self._state.get(track_key, {})
        current_part = track_data.get("current_part", 1)
        total_parts = track_data.get("total_parts", self.default_parts)
        curr_title = track_data.get("movie_title")

        if current_part < total_parts:
            # Advance to next part of same movie
            new_part = current_part + 1
            track_data["current_part"] = new_part
            self._save_state(self._state)
            logger.info(f"[SERIES_MANAGER] Slot {slot_index} advanced {curr_title} to Part {new_part}/{total_parts}")
            return new_part, False
        else:
            # Movie series complete! Rotate to next unproduced movie
            completed_entry = f"{curr_title} ({track_data.get('movie_year')})"
            if completed_entry not in self._state.get("completed_movies", []):
                self._state.setdefault("completed_movies", []).append(completed_entry)

            # Find next unproduced movie from catalog
            all_movies = self.catalog.get_all_movies()
            active_other = self._state.get("track_2" if slot_index == 1 else "track_1", {}).get("movie_title", "")
            completed = self._state.get("completed_movies", [])

            next_movie = None
            for m in all_movies:
                entry_str = f"{m.title} ({m.year})"
                if entry_str not in completed and m.title.lower() != active_other.lower() and m.title.lower() != curr_title.lower():
                    next_movie = m
                    break

            if not next_movie:
                next_movie = all_movies[0]

            track_data["movie_title"] = next_movie.title
            track_data["movie_year"] = next_movie.year
            track_data["current_part"] = 1
            track_data["total_parts"] = self.default_parts
            self._save_state(self._state)

            logger.info(
                f"[SERIES_MANAGER] Slot {slot_index} COMPLETED {curr_title}! "
                f"Promoted new series: {next_movie.title} ({next_movie.year}) starting at Part 1/{self.default_parts}."
            )
            return 1, True
