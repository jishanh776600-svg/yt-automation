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
        part_number: int = 1,
        total_parts: int = 10,
        max_attempts: int = 3
    ) -> MovieShortsScript:
        """
        Generates a 52-58 second (~130-145 words) breathless movie recap short
        composed of 14-16 rapid-cut visual beats for Part X of the movie series.
        """
        logger.info(f"[MOVIE_SCRIPT] Generating 55s Thriller Short for: {movie.title} ({movie.year}) - Part {part_number}/{total_parts}")

        prompt = f"""
You are a master cinematic thriller storyteller creating an intense 55-second YouTube Short recap for the movie:
Title: {movie.title} ({movie.year})
Episodic Segment: Part {part_number} of {total_parts}
Director: {movie.director}
Subgenre: {movie.subgenre}
Premise: {movie.premise_summary}
Main Threat: {movie.threat_or_antagonist}
Key Scenes: {json.dumps(movie.key_setpieces)}

STRICT EDITORIAL REQUIREMENTS:
1. LANGUAGE LEVEL: SIMPLE, CLEAR, EVERYDAY ENGLISH (Easily understandable worldwide).
   - Use simple words that anyone with basic English can understand.
   - Absolutely NO difficult vocabulary, poetic words, or complex grammar.
   - Use short, direct, punchy sentences (Subject -> Verb -> Object).
   - Example tone:
     "Six friends take a wrong turn on a mountain road. A hidden wire cuts their tires. Stranded with no phone signal, they walk into the deep forest. They find an old wooden cabin. Inside, they make a horrifying discovery. Suddenly, a rusty truck stops outside. The owners are back."
2. FOCUS: This is Part {part_number} of a {total_parts}-part series covering {movie.title}.
   Cover the intense developments of segment {part_number}/{total_parts}.
   End with a simple, high-curiosity cliffhanger compelling the viewer to watch Part {part_number + 1 if part_number < total_parts else 'the conclusion'}!
3. WORD COUNT: Exactly 130 to 142 words total. (Crucial: 125 words minimum, 145 words maximum).
4. TONE: Dark, breathless, present-tense suspense. Do NOT sound like an AI review ("In this movie...").
5. BEAT STRUCTURE: Output exactly 14 to 16 short beats.
   - Beats 1-2 (0-8s): The Hook / The urgent situation.
   - Beats 3-6 (8-22s): Rising tension / trap springing / entering forbidden territory.
   - Beats 7-11 (22-42s): The hunt / realization of danger / gruesome discovery.
   - Beats 12-15 (42-55s): Desperate fight / shocking discovery / cliffhanger twist.
6. FOR EACH BEAT provide:
   - "text": Spoken voiceover line (7-11 simple words).
   - "visual_description": Exact physical scene from {movie.title} to show on screen.
   - "search_keywords": 3-4 specific search keywords to find this exact movie clip.
   - "tension_level": "DREAD", "HIGH", "EXTREME", or "SHOCK".

Return valid JSON strictly adhering to this schema:
{{
  "headline": "{movie.title} - Part {part_number} | Ending Explained #shorts",
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
        return self._build_deterministic_recap(movie, part_number=part_number, total_parts=total_parts)

    def _build_deterministic_recap(
        self,
        movie: MovieEntry,
        part_number: int = 1,
        total_parts: int = 10
    ) -> MovieShortsScript:
        """High-craft deterministic fallback for Wrong Turn or catalog movies."""
        logger.info(f"[MOVIE_SCRIPT] Deploying curated deterministic recap for {movie.title} - Part {part_number}/{total_parts}")
        
        m_lower = movie.title.lower()
        if "wrong turn" in m_lower:
            if part_number == 1:
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
                raw_beats = [
                    (f"In Part {part_number} of Wrong Turn, the mountain nightmare intensifies.", "Dark misty woods establishing shot", ["Wrong Turn forest night", "woods mist"]),
                    ("The survivors break out through the bedroom window into midnight woods.", "Characters dropping quietly from cabin window", ["Wrong Turn window escape scene", "cabin exterior"]),
                    ("Behind them, Three-Finger discovers the empty bed and screams with fury.", "Three Finger roaring inside cabin doorway", ["Wrong Turn Three Finger screaming", "cannibal rage"]),
                    ("The deformed brothers grab hunting bows and barbed wire traps.", "Cannibals grabbing crude weapons and arrows", ["Wrong Turn cannibals weapons", "hunting bow"]),
                    ("Running blindly in darkness, the survivors search for any safe road.", "Characters sprinting through pitch black trees", ["Wrong Turn night forest chase", "running trees"]),
                    ("Suddenly, a tripwire snaps, releasing a vicious spiked branch.", "Tripwire triggering spiked log trap in brush", ["Wrong Turn forest trap scene", "spiked branch"]),
                    ("With cannibals closing the distance, Chris directs everyone up into high pines.", "Characters climbing tall pine tree branches", ["Wrong Turn climbing tree scene", "tree branches"]),
                    ("Torches flicker below as the brothers search the dead forest floor.", "Torches moving through dark misty forest below", ["Wrong Turn search torches night", "cannibal search"]),
                    ("Above in the canopy, they crawl across massive wooden branches.", "Survivors leaping between tree limbs in moonlight", ["Wrong Turn canopy jump scene", "pine canopy"]),
                    ("An arrow whistling through the dark grazes the tree bark inches away.", "Arrow embedding into pine trunk close-up", ["Wrong Turn arrow hit wood", "arrow tree"]),
                    ("Ahead through the leaves, an abandoned forest fire watchtower emerges.", "Tall wooden watchtower above treeline under stars", ["Wrong Turn watchtower reveal", "fire tower"]),
                    ("They scramble up the narrow wooden steps, locking the trapdoor.", "Characters racing up wooden tower staircase", ["Wrong Turn tower stairs", "tower trapdoor"]),
                    ("Below, the cannibals smile and raise glass bottles filled with gasoline.", "Cannibals lighting Molotov cocktail below tower", ["Wrong Turn Molotov cocktail", "fire bottle"]),
                    ("Flames engulf the stairs, trapping everyone in a raging wooden inferno.", "Flames engulfing base of wooden tower", ["Wrong Turn burning tower scene", "tower fire"])
                ]
        elif "hills have eyes" in m_lower:
            if part_number == 1:
                raw_beats = [
                    ("In the scorching desert, an innocent traveling family takes a fatal shortcut.", "Station wagon and trailer driving through barren desert", ["The Hills Have Eyes desert driving", "desert road"]),
                    ("Concealed spike strips tear through their tires, leaving them completely stranded.", "Spike strip shredding car tires on dirt road", ["The Hills Have Eyes spike trap scene", "blown tires"]),
                    ("With no phone signal in the heat, the father hikes miles to find help.", "Man walking alone down desolate canyon highway", ["The Hills Have Eyes walking highway", "desert sun"]),
                    ("Hidden high in the red cliffs, mutated scavengers watch their every move.", "Shadowy deformed figures watching through binoculars", ["The Hills Have Eyes cliff watchers", "mutant binoculars"]),
                    ("As darkness falls over the canyon, eerie clicking noises surround the trailer.", "Trailer illuminated by cold moonlight in canyon", ["The Hills Have Eyes trailer night", "desert darkness"]),
                    ("A sudden explosion draws the family outside into the freezing night air.", "Gasoline explosion in distance diverting family", ["The Hills Have Eyes explosion diversion", "desert explosion"]),
                    ("Inside the defenseless trailer, mutated predators strike with ruthless speed.", "Mutant intruder forcing door of trailer open", ["The Hills Have Eyes trailer raid scene", "mutant attack"]),
                    ("They take emergency supplies and kidnap the family's newborn infant.", "Mutants fleeing into darkness with stolen baby", ["The Hills Have Eyes baby kidnapping", "mutants night run"]),
                    ("Traumatized and bleeding, the survivors realize they are being hunted for sport.", "Grieving family staring into dark rocky canyon", ["The Hills Have Eyes shocked survivors", "desert dawn"]),
                    ("Doug vows to rescue his child and climbs into the mutant canyon territory.", "Determined man gripping shotgun with guard dog", ["The Hills Have Eyes Doug shotgun", "dog canyon"]),
                    ("He uncovers a horrifying ghost town built for 1950s nuclear testing.", "Abandoned nuclear testing town with plastic mannequins", ["The Hills Have Eyes nuclear village", "mannequin town"]),
                    ("Deformed mutants lurk behind ruined suburban houses and rusted cars.", "Mutant hiding behind decayed house corner", ["The Hills Have Eyes mutant village", "nuclear town mutant"]),
                    ("Armed with makeshift weapons, Doug enters the heart of the mutant lair.", "Man sneaking through abandoned house hallway", ["The Hills Have Eyes house hallway", "inside mutant home"]),
                    ("To save his daughter, this ordinary salesman must become an unstoppable force.", "Doug looking intensely ready for brutal confrontation", ["The Hills Have Eyes Doug fight climax", "shotgun ready"])
                ]
            else:
                raw_beats = [
                    (f"In Part {part_number} of The Hills Have Eyes, the battle for survival turns brutal.", "Dust storm blowing across nuclear testing town", ["The Hills Have Eyes dust storm", "nuclear ghost town"]),
                    ("Doug sneaks through the decaying nuclear village with his loyal German Shepherd.", "Doug and guard dog moving stealthily between houses", ["The Hills Have Eyes Doug Beast dog", "nuclear village search"]),
                    ("Inside a dark living room, a mutant attacker ambushes him from behind.", "Mutant swinging weapon at Doug in narrow room", ["The Hills Have Eyes mutant ambush fight", "indoor struggle"]),
                    ("His guard dog Beast lunges forward, tearing the attacker to the floor.", "German Shepherd tackling mutant defender", ["The Hills Have Eyes dog attack scene", "Beast dog fight"]),
                    ("Deep in a back room, Doug hears his baby crying from an iron crib.", "Baby crying in metal crib in dark mutant bedroom", ["The Hills Have Eyes baby in crib", "rescue room"]),
                    ("The monstrous leader Pluto suddenly steps into the doorway with a sledgehammer.", "Massive mutant Pluto holding heavy sledgehammer", ["The Hills Have Eyes Pluto mutant", "sledgehammer door"]),
                    ("A violent life-or-death brawl erupts across the dilapidated wooden floor.", "Brutal physical fight against heavy mutant", ["The Hills Have Eyes Pluto fight scene", "wooden floor brawl"]),
                    ("Using pure desperation, Doug disarms the monster and grabs his daughter.", "Doug retrieving infant and rushing out broken window", ["The Hills Have Eyes baby rescue run", "canyon escape"]),
                    ("Across the canyon, the remaining family members prepare a gasoline defense.", "Survivors pouring fuel around damaged trailer", ["The Hills Have Eyes gasoline trap", "trailer defense"]),
                    ("When Papa Jupiter charges through the rocks, they ignite the fuel line.", "Giant mutant charging toward trailer ambush", ["The Hills Have Eyes Papa Jupiter charge", "fuel trap ignites"]),
                    ("A massive desert fireball erupts into the night sky, wiping out the clan.", "Giant fireball engulfing rocks and canyon", ["The Hills Have Eyes fireball explosion", "desert blast"]),
                    ("Doug stumbles out of the rocky cliffs, carrying his baby toward the dawn light.", "Battered man carrying child emerging from canyon", ["The Hills Have Eyes Doug ending walk", "sunrise canyon"]),
                    ("Battered, bloodied, but alive, the survivors reunite under the morning sun.", "Survivors hugging beside burnt trailer remains", ["The Hills Have Eyes survivors embrace", "desert sunrise"]),
                    ("Yet in the distant peaks, a lone mutant eye watches them walk away.", "Single eye watching through cracked binoculars on cliff", ["The Hills Have Eyes final cliff shot", "ending cliffhanger"])
                ]
        else:
            # Dynamic generic survival recap that changes by part_number
            raw_beats = [
                (f"In Part {part_number} of {movie.title}, the danger escalates to a breaking point.", "Dramatic atmospheric establishing scene", [f"{movie.title} scene"]),
                (f"The survivors push forward into unexplored territory of {movie.title}.", "Characters moving cautiously through hostile environment", [f"{movie.title} exploration"]),
                ("Every exit route is severed as the relentless threat closes in around them.", "Blocked passage or destroyed bridge", [f"{movie.title} trap"]),
                ("They discover evidence of past victims who failed to escape this place.", "Disturbing clues found in shadows", [f"{movie.title} clues"]),
                ("A sudden shock shatters the silence, forcing everyone into a sprint.", "Sudden ambush triggering frantic run", [f"{movie.title} ambush"]),
                ("Separated in the chaos, each person must fight for their own survival.", "Characters split in dangerous corridors", [f"{movie.title} chase"]),
                ("Armed only with basic tools, they prepare an unexpected ambush.", "Character rigging makeshift weapon", [f"{movie.title} defense"]),
                ("When the predator strikes, a violent clash shakes the entire area.", "High intensity fight sequence", [f"{movie.title} fight"]),
                ("They break through the defensive line, racing toward the final exit.", "Sprinting toward daylight or doorway", [f"{movie.title} escape"]),
                ("Just when freedom seems certain, a devastating twist changes the game.", "Shocking climax visual reveal", [f"{movie.title} twist"]),
                ("They trigger a massive counterattack, turning the tables on their hunter.", "Explosion or trap springing on threat", [f"{movie.title} counterattack"]),
                ("In a breathless climax, only the strongest will make it out alive.", "Dramatic final standoff visual", [f"{movie.title} standoff"]),
                (f"The dust settles over {movie.title}, leaving a chilling question behind.", "Ominous closing frame", [f"{movie.title} ending"]),
                ("Watch the next chapter to see if anyone truly escapes this nightmare.", "High tension final cliffhanger", [f"{movie.title} cliffhanger"])
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
            headline=f"{movie.title} - Part {part_number} | Ending Explained #shorts",
            hook=beats[0].text,
            cliffhanger_or_twist=beats[-1].text
        )

    def _extract_json(self, raw_input: Any) -> str:
        if hasattr(raw_input, "text"):
            text = str(raw_input.text)
        else:
            text = str(raw_input)
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
1. SIMPLE & CLEAR ENGLISH: Use plain, conversational, and direct English that anyone globally can easily follow. Avoid difficult vocabulary or complex sentences. Talk like an intense storyteller explaining the story to a friend.
2. Present-tense cinematic storytelling ("They step inside...", "The door slams shut...").
3. High tension, dark atmospheric tone. Zero generic AI clichés.
4. Every scene beat must be visually concrete.

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
