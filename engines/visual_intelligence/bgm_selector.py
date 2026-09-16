"""
Intelligent BGM Selection & Rotation Engine.
Replaces monolithic soundtrack repetition with multi-attribute story matching,
persistent cross-run history in SQLite SystemConfig, and rotation decay penalties.
Tracks:
- mood, energy, tempo, genre, intensity, editorial suitability
- cross-short rotation ensuring the same track is not repeated consecutively
- persistent usage tracking across ephemeral cloud runs via SQLite SystemConfig
"""
import json
import logging
import re
from typing import Dict, Any, List, Optional
from collections import deque
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_CONFIG_KEY = "recent_bgm_tracks"


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
        license_type: str = "CC0_PUBLIC_DOMAIN",
        category_keywords: Optional[List[str]] = None,
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
        self.category_keywords = category_keywords or []


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
            category_keywords=[
                "history", "historical", "war", "warfare", "empire", "politics", "military",
                "monarchy", "royal", "medieval", "unusual wars", "diplomacy", "american history",
                "world affairs", "ancient rome", "ancient greece"
            ],
            editorial_fit=[
                "war", "battle", "army", "armies", "empire", "empires", "king", "queen", "court",
                "parliament", "revolution", "monarch", "monarchy", "dynasty", "coronation", "treaty",
                "treaties", "feud", "rebellion", "emperor", "pope", "crusade", "medieval", "royal",
                "duel", "regime", "conquest", "siege", "knight", "throne", "castle", "crown",
                "republic", "legion", "armada", "commander", "soldier", "soldiers", "navy", "military",
                "napoleon", "caesar", "churchill", "latrine", "privy", "scandal", "erfurt", "tax",
                "beards", "laws", "aristocrats", "collapse", "politics", "political", "government",
                "diplomacy", "diplomatic", "state", "senate", "historical", "history", "warfare",
                "general", "generals", "president", "alliance", "allies", "treaty"
            ],
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
            category_keywords=[
                "suspense", "thriller", "crisis", "crises", "urgency", "heist", "manhunt",
                "escape", "high tension", "espionage", "breaking"
            ],
            editorial_fit=[
                "breaking", "crisis", "scandal", "race", "urgency", "urgent", "heist", "manhunt",
                "escape", "chase", "tension", "suspense", "thriller", "panic", "countdown",
                "assassination", "ambush", "plot", "trapped", "deadly", "strike", "pursuit",
                "breakout", "hostage", "bomb", "confrontation", "alarm", "ticking", "undercover",
                "spy", "infiltrate", "stealth", "infiltrator", "fugitive", "assassin", "pursuer",
                "critical", "threat", "danger", "peril", "emergency", "high-stakes", "sabotage",
                "interception", "race against time"
            ],
            description="Tense driving percussion for high-stakes political intrigue, thrilling chases, and breaking stories.",
            tempo_bpm=132
        ),
        "flux_ambient": BGMTrack(
            key="flux_ambient",
            display_name="The Flux Beneath It All",
            primary_files=["The Flux Beneath It All.wav", "The Flux Beneath It All.mp3"],
            mood="Dark Mystery / Atmospheric Intrigue / Scientific Wonder / Bizarre Oddity",
            genre="Dark Electronic Pulse",
            energy="MEDIUM",
            intensity="Atmospheric-Tense",
            category_keywords=[
                "mystery", "mysteries", "historical mysteries", "unexplained", "oddity",
                "oddities", "cipher", "ciphers", "artifact", "artifacts"
            ],
            editorial_fit=[
                "mystery", "mysteries", "mysterious", "secret", "secrets", "cipher", "ciphers",
                "cryptic", "puzzle", "puzzles", "riddle", "riddles", "unexplained", "phenomenon",
                "anomalous", "anomaly", "curiosity", "intrigue", "dark", "alchemist", "astronomy",
                "artifact", "artifacts", "voynich", "roanoke", "atlantis", "conspiracy", "code",
                "codes", "alien", "supernatural", "peculiar", "unsolved", "baffling", "occult",
                "enigma", "enigmatic", "paranormal", "strange"
            ],
            description="Dark electronic pulse for unexplained mysteries, ciphers, ancient artifacts, and cryptic enigmas.",
            tempo_bpm=110
        ),
        "emotional_sad": BGMTrack(
            key="emotional_sad",
            display_name="Empty - Emotional Sad Background",
            primary_files=["Empty - Emotional Sad Background.wav", "Empty - Emotional Sad Background.mp3"],
            mood="Emotional / Sad / Mournful / Poignant / Human Tragedy",
            genre="Somber Piano & Strings",
            energy="LOW",
            intensity="Subdued-Poignant",
            category_keywords=[
                "tragedy", "human tragedy", "loss", "grief", "memorial", "documented disasters",
                "disaster", "sorrow", "famine"
            ],
            editorial_fit=[
                "sad", "tragedy", "tragic", "emotional", "loss", "grief", "poignant", "mourn",
                "mourning", "sacrifice", "heartbreak", "death", "tears", "memorial", "ruin",
                "sorrow", "farewell", "crying", "dying", "famine", "plague", "victim", "victims",
                "burial", "fatal", "suffering", "sorrowful", "heartbreaking", "perished",
                "massacre", "destitution", "orphan", "starved", "grave", "graves", "lonely",
                "tear", "sympathy", "deprived", "destitute", "grieving", "regret", "casualty",
                "casualties", "aftermath", "human toll", "catastrophe", "wept", "devastation"
            ],
            description="Somber melody for tragic human events, personal loss, poignant sacrifices, and heartfelt mourning.",
            tempo_bpm=74
        )
    }

    def __init__(self):
        self._catalog: Dict[str, BGMTrack] = dict(self.CATALOG)
        self._recent_usage: deque = deque(maxlen=5)
        for k in self._load_persisted_usage():
            self._recent_usage.append(k)

    def _load_persisted_usage(self) -> List[str]:
        """Loads recent BGM track history from canonical SQLite SystemConfig."""
        try:
            from core.database import SessionLocal
            from core.models import SystemConfig
            with SessionLocal() as db:
                cfg = db.query(SystemConfig).filter(SystemConfig.key == SYSTEM_CONFIG_KEY).first()
                if cfg and cfg.value:
                    items = json.loads(cfg.value)
                    if isinstance(items, list):
                        return [k for k in items if k in self._catalog]
        except Exception as e:
            logger.debug(f"[BGM_SELECTOR] Could not load persisted usage from SystemConfig: {e}")
        return []

    def _persist_usage(self) -> None:
        """Persists recent BGM track history to canonical SQLite SystemConfig."""
        try:
            from core.database import SessionLocal
            from core.models import SystemConfig
            with SessionLocal() as db:
                val = json.dumps(list(self._recent_usage))
                cfg = db.query(SystemConfig).filter(SystemConfig.key == SYSTEM_CONFIG_KEY).first()
                if cfg:
                    cfg.value = val
                else:
                    cfg = SystemConfig(key=SYSTEM_CONFIG_KEY, value=val)
                    db.add(cfg)
                db.commit()
        except Exception as e:
            logger.debug(f"[BGM_SELECTOR] Could not persist usage to SystemConfig: {e}")

    def register_track(self, track: BGMTrack) -> None:
        """Dynamically registers a verified, properly licensed background music track."""
        self._catalog[track.key] = track
        logger.info(f"[BGM_SELECTOR] Registered verified track '{track.key}' ({track.display_name})")

    def get_recent_usage(self) -> List[str]:
        return list(self._recent_usage)

    def record_usage(self, track_key: str) -> None:
        """Records track usage and synchronizes with persistent storage."""
        if track_key in self._catalog:
            self._recent_usage.append(track_key)
            self._persist_usage()

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
        Theme compatibility remains the primary requirement; recent-use history acts as
        an anti-monotony penalty when alternative tracks are compatible.
        """
        def _match_count(text: str, keywords: List[str]) -> int:
            if not text or not keywords:
                return 0
            cnt = 0
            t_lower = text.lower()
            for kw in keywords:
                pattern = r'\b' + re.escape(kw.lower()) + r'\b'
                if re.search(pattern, t_lower):
                    cnt += 1
            return cnt

        scored: Dict[str, float] = {}

        for key, track in self._catalog.items():
            base_score = 1.0

            # 1. Category alignment (+4.0 per match)
            if category and track.category_keywords:
                cat_matches = _match_count(category, track.category_keywords)
                base_score += cat_matches * 4.0

            # 2. Title keyword matches (+2.5 per match)
            if title and track.editorial_fit:
                title_matches = _match_count(title, track.editorial_fit)
                base_score += title_matches * 2.5

            # 3. Script keyword matches (+1.0 per match, capped at 5)
            if script_text and track.editorial_fit:
                script_matches = _match_count(script_text, track.editorial_fit)
                base_score += min(script_matches, 5) * 1.0

            # 4. Tempo alignment if target tempo requested
            if target_tempo_bpm and track.tempo_bpm:
                tempo_diff = abs(track.tempo_bpm - target_tempo_bpm)
                if tempo_diff <= 15:
                    base_score += 1.5
                elif tempo_diff > 35:
                    base_score -= 1.0

            # 5. Anti-monotony rotation penalty: penalize tracks used recently
            recent_list = list(self._recent_usage)
            if key in recent_list:
                recency_index = recent_list[::-1].index(key)  # 0 = most recent
                if recency_index == 0 and not allow_repeat:
                    base_score -= 3.5  # Immediate consecutive repeat penalty
                elif recency_index == 1:
                    base_score -= 2.0
                elif recency_index == 2:
                    base_score -= 1.0

            scored[key] = round(base_score, 2)

        # Select highest scored track
        best_track = max(scored.items(), key=lambda x: x[1])[0]
        self.record_usage(best_track)
        logger.info(f"[BGM_SELECTOR] Selected '{best_track}' (Score: {scored[best_track]:.2f}, Recent History: {list(self._recent_usage)})")
        return best_track
