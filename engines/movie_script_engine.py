"""
Movie Recap Script Engine: Cinematic Thriller & Survival Storyteller.
=====================================================================
Generates high-retention, present-tense movie recaps for YouTube Shorts (~55s, 130-145 words)
and Long-Form videos (8-12 minutes).

Every beat produces:
  - Spoken narrative text (Kokoro delivery)
  - Visual description tag for exact movie scene retrieval
  - Dynamic tension score & sound cue markers
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple

from core.gemini_client import GeminiClient
from core.movie_catalog import MovieEntry, MovieCatalogManager

logger = logging.getLogger("alamr.movie_script")


@dataclass
class MovieBeat:
    beat_id: str
    sequence: int
    text: str
    visual_description: str
    search_keywords: List[str]
    duration_estimate_sec: float
    tension_level: str  # HIGH, EXTREME, DREAD, SHOCK


@dataclass
class MovieShortsScript:
    movie_title: str
    movie_year: int
    director: str
    subgenre: str
    beats: List[MovieBeat]
    total_words: int
    estimated_duration_sec: float
    headline: str
    hook: str
    cliffhanger_or_twist: str

    @property
    def full_script_text(self) -> str:
        return " ".join(b.text for b in self.beats)


@dataclass
class MovieChapter:
    chapter_index: int
    title: str
    beats: List[MovieBeat]
    total_words: int
    duration_estimate_sec: float


@dataclass
class MovieLongformScript:
    movie_title: str
    movie_year: int
    director: str
    subgenre: str
    chapters: List[MovieChapter]
    total_words: int
    estimated_duration_sec: float
    headline: str
    intro_hook: str
    ending_analysis: str

    @property
    def full_script_text(self) -> str:
        parts = []
        for ch in self.chapters:
            parts.append(" ".join(b.text for b in ch.beats))
        return "\n\n".join(parts)


class MovieScriptEngine:
    """Generates broadcast-grade thriller and survival movie recap scripts."""

    def __init__(self, gemini_client: Optional[GeminiClient] = None):
        self.gemini = gemini_client or GeminiClient()

    def generate_shorts_script(
        self,
        movie: MovieEntry,
        max_attempts: int = 3
    ) -> MovieShortsScript:
        """
        Generates a 52-58 second (~130-145 words) breathless movie recap short
        composed of 14-16 rapid-cut visual beats.
        """
        logger.info(f"[MOVIE_SCRIPT] Generating 55s Thriller Short for: {movie.title} ({movie.year})")

        prompt = f"""
You are a master cinematic thriller storyteller creating an intense 55-second YouTube Short recap for the movie:
Title: {movie.title} ({movie.year})
Director: {movie.director}
Subgenre: {movie.subgenre}
Premise: {movie.premise_summary}
Main Threat: {movie.threat_or_antagonist}
Key Scenes: {json.dumps(movie.key_setpieces)}

STRICT EDITORIAL REQUIREMENTS:
1. WORD COUNT: Exactly 130 to 142 words total. (Crucial: 125 words minimum, 145 words maximum).
2. TONE: Dark, breathless, present-tense narrative. Do NOT sound like an AI review ("In this movie...").
   Sound like a narrator recounting a terrifying real nightmare:
   "Three friends take a wrong turn down a deserted mountain road. Bad mistake."
3. BEAT STRUCTURE: Output exactly 14 to 16 short beats.
   - Beats 1-2 (0-8s): The Hook / The fatal premise.
   - Beats 3-6 (8-22s): The trap sprung / Stranded / entering forbidden territory.
   - Beats 7-11 (22-42s): The hunt / Realization of the monsters / rising horror.
   - Beats 12-15 (42-55s): Desperate fight / shocking discovery / cliffhanger twist.
4. FOR EACH BEAT provide:
   - "text": Spoken voiceover line (7-11 words).
   - "visual_description": Exact physical scene from {movie.title} to show on screen.
   - "search_keywords": 3-4 specific search keywords to find this exact movie clip.
   - "tension_level": "DREAD", "HIGH", "EXTREME", or "SHOCK".

Return valid JSON strictly adhering to this schema:
{{
  "headline": "Short punchy title (under 60 chars)",
  "hook": "Opening sentence",
  "cliffhanger_or_twist": "Closing punchline",
  "beats": [
    {{
      "sequence": 1,
      "text": "...",
      "visual_description": "...",
      "search_keywords": ["...", "..."],
      "tension_level": "..."
    }}
  ]
}}
"""

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.gemini.generate_content(
                    prompt=prompt,
                    system_instruction="You are a professional cinema thriller recap director. Output raw JSON only."
                )

                clean_text = self._extract_json(response)
                data = json.loads(clean_text)

                beats_data = data.get("beats", [])
                raw_words = " ".join(b.get("text", "") for b in beats_data)
                words = re.sub(r"[^\w\s]", "", raw_words).split()
                total_words = len(words)

                logger.info(f"[MOVIE_SCRIPT] Attempt {attempt}: Generated {total_words} words across {len(beats_data)} beats.")

                if 125 <= total_words <= 148 and len(beats_data) >= 12:
                    beats = []
                    for idx, b in enumerate(beats_data):
                        beats.append(MovieBeat(
                            beat_id=f"beat_{idx+1:02d}",
                            sequence=idx + 1,
                            text=b.get("text", "").strip(),
                            visual_description=b.get("visual_description", "").strip(),
                            search_keywords=b.get("search_keywords", [movie.title]),
                            duration_estimate_sec=round(len(b.get("text", "").split()) * 0.38, 2),
                            tension_level=b.get("tension_level", "HIGH")
                        ))

                    est_duration = sum(b.duration_estimate_sec for b in beats)

                    return MovieShortsScript(
                        movie_title=movie.title,
                        movie_year=movie.year,
                        director=movie.director,
                        subgenre=movie.subgenre,
                        beats=beats,
                        total_words=total_words,
                        estimated_duration_sec=est_duration,
                        headline=data.get("headline", f"{movie.title} ({movie.year}) Recap"),
                        hook=data.get("hook", beats[0].text if beats else ""),
                        cliffhanger_or_twist=data.get("cliffhanger_or_twist", beats[-1].text if beats else "")
                    )
                else:
                    logger.warning(f"[MOVIE_SCRIPT] Word count {total_words} outside 125-148 window. Retrying...")

            except Exception as e:
                logger.error(f"[MOVIE_SCRIPT] Attempt {attempt} failed: {e}")

        # Deterministic curated fallback if AI rate limit or word count variance
        return self._build_deterministic_recap(movie)

    def _build_deterministic_recap(self, movie: MovieEntry) -> MovieShortsScript:
        """High-craft deterministic fallback for Wrong Turn or catalog movies."""
        logger.info(f"[MOVIE_SCRIPT] Deploying curated deterministic recap for {movie.title}")
        
        if "wrong turn" in movie.title.lower():
            raw_beats = [
                ("Deep in West Virginia, six travelers take an abandoned dirt road.", "Car driving down isolated forested dirt road under grey skies", ["Wrong Turn 2003 driving dirt road", "car woods"]),
                ("Barbed wire hidden in the brush violently punctures their tires.", "Close-up barbed wire puncturing car tire on muddy path", ["Wrong Turn 2003 tire trap scene", "barbed wire"]),
                ("Stranded without service, they hike miles into dense mountain woods.", "Group walking through dense Appalachian forest looking lost", ["Wrong Turn 2003 hiking woods", "stranded travelers"]),
                ("Deep in the forest, they find a secluded, rotting wooden cabin.", "Creepy wooden cabin surrounded by rusty car wreckage", ["Wrong Turn 2003 cabin reveal", "creepy cabin"]),
                ("Inside, shelves are packed with jars filled with human body parts.", "Jars and severed teeth on wooden kitchen table", ["Wrong Turn 2003 cabin inside jars", "cabin kitchen"]),
                ("A rusty truck rumbles outside. The occupants have returned.", "Rusty tow truck headlights pulling into cabin driveway", ["Wrong Turn 2003 tow truck arrival", "truck night"]),
                ("The survivors desperately dive under a wooden bed frame.", "Characters trembling hiding under wooden bed holding breath", ["Wrong Turn 2003 hiding under bed scene", "bed hiding"]),
                ("Three deformed cannibal brothers drag a fresh corpse inside.", "Three-Finger dragging a dead body into the kitchen", ["Wrong Turn 2003 cannibals body scene", "Three Finger"]),
                ("They butcher the body inches away from the hiding survivors.", "Axe chopping wood and meat while characters watch terrified", ["Wrong Turn 2003 axe chopping cabin", "cabin terror"]),
                ("Escaping through a back window, they flee into the trees.", "Characters jumping out cabin window into dark woods", ["Wrong Turn 2003 window escape", "forest night"]),
                ("Armed with hunting bows, the cannibals track them through the dark.", "Cannibals running through forest shooting arrows", ["Wrong Turn 2003 bow arrow chase", "tree pursuit"]),
                ("The survivors climb into the canopy, leaping across branches.", "Characters crawling high on pine branches in moonlight", ["Wrong Turn 2003 tree canopy jump scene", "treetop chase"]),
                ("Trapped inside a wooden watchtower, the cannibals set it on fire.", "Cannibals throwing Molotov cocktail setting tower stairs in flames", ["Wrong Turn 2003 watchtower fire scene", "flaming tower"]),
                ("With flames rising, they must leap into the dark or burn.", "Characters standing on burning balcony preparing to leap", ["Wrong Turn 2003 balcony jump ending", "flames jump"])
            ]
        else:
            # Generic structured survival recap (14 beats, ~134 words)
            raw_beats = [
                (f"In {movie.title}, an innocent road journey turns into an inescapable nightmare.", "Ominous landscape establishing shot", [f"{movie.title} opening scene"]),
                ("A group of travelers takes a fatal shortcut away from civilization.", "Characters entering isolated zone", [f"{movie.title} travel scene"]),
                ("Their vehicle breaks down, leaving them completely stranded without any communication.", "Stranded vehicle in desolate wilderness", [f"{movie.title} stranded scene"]),
                ("Seeking immediate help, they stumble upon an isolated structure in the dark.", "Eerie building discovered in distance", [f"{movie.title} building discovery"]),
                ("Inside, they uncover gruesome evidence that they are not alone.", "Characters discovering disturbing clues", [f"{movie.title} clues scene"]),
                ("Before they can flee, the heavy door slams shut. The predator returns.", "Shadowy figure appearing in doorway", [f"{movie.title} killer arrival"]),
                ("Hiding in the shadows, they watch in horror as the trap is set.", "Characters holding breath hiding", [f"{movie.title} hiding scene"]),
                ("One by one, the survivors realize every single exit is locked.", "Characters desperately checking locked doors", [f"{movie.title} locked doors"]),
                ("A relentless pursuit begins through corridors of pure terrifying darkness.", "High tension pursuit through darkness", [f"{movie.title} chase scene"]),
                ("Armed with makeshift weapons, they prepare for a brutal confrontation.", "Character gripping weapon with shaking hands", [f"{movie.title} weapon confrontation"]),
                ("In a chaotic clash, the predator closes in with relentless force.", "Violent struggle between survivors and threat", [f"{movie.title} fight scene"]),
                ("They break through the perimeter, running for their lives into the night.", "Characters sprinting through exterior zone", [f"{movie.title} escape run"]),
                ("Just when safety seems within reach, a shocking revelation changes everything.", "Shocking climax visual reveal", [f"{movie.title} twist scene"]),
                (f"Only the most ruthless will survive the final trial of {movie.title}.", "Final dramatic cliffhanger frame", [f"{movie.title} ending scene"])
            ]

        beats = []
        for idx, (txt, v_desc, kws) in enumerate(raw_beats):
            beats.append(MovieBeat(
                beat_id=f"beat_{idx+1:02d}",
                sequence=idx + 1,
                text=txt,
                visual_description=v_desc,
                search_keywords=kws,
                duration_estimate_sec=round(len(txt.split()) * 0.38, 2),
                tension_level="HIGH" if idx < 10 else "SHOCK"
            ))

        total_words = sum(len(b.text.split()) for b in beats)
        return MovieShortsScript(
            movie_title=movie.title,
            movie_year=movie.year,
            director=movie.director,
            subgenre=movie.subgenre,
            beats=beats,
            total_words=total_words,
            estimated_duration_sec=sum(b.duration_estimate_sec for b in beats),
            headline=f"{movie.title} ({movie.year}) - The Ultimate Survival Nightmare",
            hook=beats[0].text,
            cliffhanger_or_twist=beats[-1].text
        )

    def _extract_json(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return text.strip()

    def generate_longform_script(
        self,
        movie: MovieEntry,
    ) -> MovieLongformScript:
        """
        Generates an 8-12 minute (~1,300 words) deep-dive scene-by-scene movie explainer
        divided into 4 acts/chapters with tension analysis and thematic resolution.
        """
        logger.info(f"[MOVIE_SCRIPT] Generating 10-minute long-form explainer for: {movie.title} ({movie.year})")
        
        # Structure 4 chapters
        chapters = []
        chapter_specs = [
            ("Act 1: The Fatal Detour & Isolation", 300, "The journey begins, characters take the forbidden path, and isolation sets in."),
            ("Act 2: The Trap Springs & The Threat Revealed", 350, "The confrontation begins, the grotesque truth is uncovered, and the first death occurs."),
            ("Act 3: Relentless Pursuit & Survival Counter-Attack", 350, "The survivors fight back, the chase intensifies across wilderness or trap rooms."),
            ("Act 4: The Climax, Twist & Ending Explained", 300, "The ultimate standoff, the shocking revelation, and the thematic aftermath.")
        ]
        
        for idx, (ch_title, target_words, ch_desc) in enumerate(chapter_specs, 1):
            prompt = f"""
Write Chapter {idx} of a 10-minute YouTube movie explainer/recap for the cult thriller:
Title: {movie.title} ({movie.year})
Director: {movie.director}
Subgenre: {movie.subgenre}
Premise: {movie.premise_summary}
Chapter Title: {ch_title}
Focus: {ch_desc}
Target Word Count: Exactly {target_words} words.

CRITICAL RULES:
1. Present-tense cinematic storytelling ("They step inside...", "The door slams shut...").
2. High tension, dark atmospheric tone. Zero generic AI clichés.
3. Every scene beat must be visually concrete.

Respond strictly in JSON format:
{{
  "beats": [
    {{
      "text": "Spoken narration for this beat",
      "visual_description": "Exact visual from the movie to show",
      "search_keywords": ["keyword1", "keyword2"],
      "tension_level": "HIGH"
    }}
  ]
}}
"""
            try:
                resp = self.gemini.generate_content(prompt, temperature=0.3)
                clean_json = self._extract_json(resp.text)
                data = json.loads(clean_json)
                beats_data = data.get("beats", [])
                beats = []
                for b_idx, b in enumerate(beats_data):
                    beats.append(MovieBeat(
                        beat_id=f"ch{idx}_beat_{b_idx+1:02d}",
                        sequence=b_idx + 1,
                        text=b.get("text", "").strip(),
                        visual_description=b.get("visual_description", "").strip(),
                        search_keywords=b.get("search_keywords", [movie.title]),
                        duration_estimate_sec=round(len(b.get("text", "").split()) * 0.38, 2),
                        tension_level=b.get("tension_level", "HIGH")
                    ))
                ch_words = sum(len(b.text.split()) for b in beats)
                ch_dur = sum(b.duration_estimate_sec for b in beats)
                chapters.append(MovieChapter(
                    chapter_index=idx,
                    title=ch_title,
                    beats=beats,
                    total_words=ch_words,
                    duration_estimate_sec=ch_dur
                ))
            except Exception as e:
                logger.warning(f"[MOVIE_SCRIPT] AI longform generation failed for Chapter {idx}: {e}. Using structured fallback.")
                fb_beat = MovieBeat(
                    beat_id=f"ch{idx}_beat_01",
                    sequence=1,
                    text=f"In {movie.title}, {ch_desc}",
                    visual_description=f"Cinematic scenes depicting {ch_title}",
                    search_keywords=[f"{movie.title} {movie.year} scene"],
                    duration_estimate_sec=60.0,
                    tension_level="HIGH"
                )
                chapters.append(MovieChapter(
                    chapter_index=idx,
                    title=ch_title,
                    beats=[fb_beat],
                    total_words=len(fb_beat.text.split()),
                    duration_estimate_sec=60.0
                ))

        total_words = sum(ch.total_words for ch in chapters)
        total_dur = sum(ch.duration_estimate_sec for ch in chapters)

        return MovieLongformScript(
            movie_title=movie.title,
            movie_year=movie.year,
            director=movie.director,
            subgenre=movie.subgenre,
            chapters=chapters,
            total_words=total_words,
            estimated_duration_sec=total_dur,
            headline=f"{movie.title} ({movie.year}) - Complete Story & Ending Explained",
            intro_hook=f"In {movie.year}, {movie.title} traumatized audiences with its brutal depiction of {movie.subgenre}.",
            ending_analysis=f"{movie.title} remains a cult masterwork because of its unrelenting dread and psychological tension."
        )
