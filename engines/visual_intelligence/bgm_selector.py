"""
Intelligent BGM Selection & Rotation Engine.
Replaces monolithic soundtrack repetition with multi-attribute story matching
and cross-job usage decay penalties.
Tracks:
- mood, energy, tempo, genre, intensity, editorial suitability
- cross-short rotation ensuring the same track is not repeated consecutively.
"""
import logging
from typing import Dict, Any, List, Optional
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)


class BGMTrack:
    """Rich editorial metadata for a background music asset."""
    def __init__(
        self,
        key: str,
        display_name: str,
        primary_files: List[str],
        mood: str,
        genre: str,
        energy: str,             # LOW, MEDIUM, HIGH, DRIVING
        intensity: str,
        editorial_fit: List[str],
        description: str,
        tempo_bpm: Optional[int] = None,
        license_type: str = "CC0_PUBLIC_DOMAIN"
    ):
        self.key = key
        self.display_name = display_name
        self.primary_files = primary_files
        self.mood = mood
        self.genre = genre
        self.energy = energy
        self.intensity = intensity
        self.editorial_fit = editorial_fit
        self.description = description
        self.tempo_bpm = tempo_bpm
        self.license_type = license_type


class BGMSelector:
    """Selects and rotates background music based on narrative profile and recent history."""

    CATALOG = {
        "best_historical": BGMTrack(
            key="best_historical",
            display_name="No copyright Best Historical",
            primary_files=["No copyright Best Historical.wav", "No copyright Best Historical.mp3"],
            mood="Historical / Serious Documentary / Royal / Politics",
            genre="Cinematic Orchestral",
            energy="MEDIUM",
            intensity="Medium-High",
            editorial_fit=["politics", "history", "war", "monarchy", "treaty", "elections", "court"],
            description="Epic orchestral music for serious politics, historical conflicts, and state events.",
            tempo_bpm=90
        ),
        "suspense_climax": BGMTrack(
            key="suspense_climax",
            display_name="No Copyright Background Music",
            primary_files=["No Copyright Background Music.wav", "No Copyright Background Music.mp3"],
            mood="High Tension / Suspense / Breaking Crisis",
            genre="Driving Hybrid Percussion",
            energy="HIGH",
            intensity="High-Driving",
            editorial_fit=["breaking", "crisis", "scandal", "race", "urgency", "heist", "manhunt"],
            description="Tense driving percussion for high-stakes political intrigue and breaking stories.",
            tempo_bpm=132
        ),
        "flux_ambient": BGMTrack(
            key="flux_ambient",
            display_name="The Flux Beneath It All",
            primary_files=["The Flux Beneath It All.wav", "The Flux Beneath It All.mp3"],
            mood="Analytical / Dark Mystery / Investigation",
            genre="Dark Electronic Pulse",
            energy="MEDIUM",
            intensity="Atmospheric-Tense",
            editorial_fit=["investigation", "mystery", "economy", "technology", "puzzle", "oddity"],
            description="Dark electronic pulse for investigative reports, deep dives, and complex dynamics.",
            tempo_bpm=110
        ),
        "emotional_sad": BGMTrack(
            key="emotional_sad",
            display_name="Empty - Emotional Sad Background",
            primary_files=["Empty - Emotional Sad Background.wav", "Empty - Emotional Sad Background.mp3"],
            mood="Emotional / Somber / Human Tragedy",
            genre="Somber Piano & Strings",
            energy="LOW",
            intensity="Subdued-Poignant",
            editorial_fit=["tragedy", "loss", "grief", "poignant", "sacrifice", "memorial", "disaster"],
            description="Somber melody for tragic events, personal loss, and heartfelt human aftermath.",
            tempo_bpm=74
        )
    }

    def __init__(self):
        # Tracks last 5 used track keys
        self._recent_usage: deque = deque(maxlen=5)
        self._catalog: Dict[str, BGMTrack] = dict(self.CATALOG)

    def register_track(self, track: BGMTrack) -> None:
        """Dynamically registers a verified, properly licensed background music track."""
        self._catalog[track.key] = track
        logger.info(f"[BGM_SELECTOR] Registered verified track '{track.key}' ({track.display_name})")

    def get_recent_usage(self) -> List[str]:
        return list(self._recent_usage)

    def select_track(
        self,
        category: str,
        title: str,
        script_text: str,
        allow_repeat: bool = False,
        target_tempo_bpm: Optional[int] = None
    ) -> str:
        """
        Deterministically evaluates narrative context and selects the best matching track
        while penalizing recently used tracks to prevent auditory monotony.
        """
        full_text = f"{category} {title} {script_text}".lower()
        scored: Dict[str, float] = {}

        for key, track in self._catalog.items():
            base_score = 1.0
            # Fit matches
            for fit_keyword in track.editorial_fit:
                if fit_keyword in full_text:
                    base_score += 2.0

            # Tempo alignment if target tempo requested
            if target_tempo_bpm and track.tempo_bpm:
                tempo_diff = abs(track.tempo_bpm - target_tempo_bpm)
                if tempo_diff <= 15:
                    base_score += 1.5
                elif tempo_diff > 35:
                    base_score -= 1.0

            # Rotation penalty: penalize tracks used recently
            recent_list = list(self._recent_usage)
            if key in recent_list:
                recency_index = recent_list[::-1].index(key)  # 0 = most recent
                if recency_index == 0 and not allow_repeat:
                    base_score -= 5.0  # Immediate consecutive repeat penalty
                elif recency_index == 1:
                    base_score -= 2.5
                else:
                    base_score -= 1.0

            scored[key] = base_score

        # Select highest scored track
        best_track = max(scored.items(), key=lambda x: x[1])[0]
        self._recent_usage.append(best_track)
        logger.info(f"[BGM_SELECTOR] Selected '{best_track}' (Score: {scored[best_track]:.2f}, Recent History: {list(self._recent_usage)})")
        return best_track
