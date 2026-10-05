"""
Cinematic Reference Engine for AL-AMR.
======================================
Associates story topics, themes, environments, and tense narrative actions
with iconic, broadcast-grade cinematic film references, docudramas, and archival footage.

Examples of Instinctive Association:
  - Jungle disappearance / uncharted Amazon / tribal mystery / cannibalism:
    -> "The Green Inferno", "The Lost City of Z", "Apocalypto", "Jungle (2017)", "Predator"
  - Deep space distress / phantom cosmonauts / Soviet space race:
    -> "First Man", "Apollo 13", "Interstellar", "Gravity", "The Right Stuff", "Ad Astra"
  - Medieval aerial phenomenon / celestial battle / Nuremberg 1561:
    -> "Kingdom of Heaven", "The Seventh Seal", "Agora", "medieval town looking at sky 4k", "sun dog atmospheric phenomenon"
  - Submarine mystery / deep ocean / underwater anomaly:
    -> "Das Boot", "The Hunt for Red October", "K-19 The Widowmaker", "The Abyss", "Crimson Tide"
  - Ancient ruins / forbidden cave / buried artifact:
    -> "Indiana Jones", "The Mummy", "As Above So Below", "archaeological excavation 4k"
  - Arctic isolation / polar blizzard / doomed expedition:
    -> "The Terror", "The Thing", "Arctic", "Against the Ice"
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("alamr.cinematic_reference")

CINEMATIC_KNOWLEDGE_BASE = [
    # 1. JUNGLE / AMAZON / CANNIBALISM / LOST EXPEDITIONS
    {
        "keywords": [
            "jungle", "amazon", "rainforest", "fawcett", "mato grosso", "lost city",
            "cannibal", "cannibalism", "tribe", "tribal", "riverboat", "machete",
            "uncharted", "dense forest", "indigenous", "green inferno"
        ],
        "cinematic_films": [
            "The Lost City of Z",
            "Apocalypto",
            "Jungle 2017",
            "Aguirre the Wrath of God",
            "Embrace of the Serpent"
        ],
        "action_queries": {
            "entry": "entering dense Amazon rainforest cinematic 4k",
            "expedition": "The Lost City of Z jungle expedition movie scene 4k",
            "cannibal": "Apocalypto jungle pursuit film clip 1080p",
            "tribal": "Apocalypto jungle pursuit film clip 1080p",
            "lost": "Jungle 2017 lost in wilderness movie scene 4k",
            "river": "Amazon river boat dense rainforest cinematic 4k",
            "camp": "overgrown abandoned jungle camp 4k cinematic",
            "canopy": "Amazon rainforest aerial canopy drone 4k 60fps",
            "disappearance": "The Lost City of Z deep jungle movie scene 4k",
            "journal": "vintage explorer handwritten expedition journal 4k",
            "search": "Amazon search party rescue expedition documentary 4k",
            "face": "The Lost City of Z Percy Fawcett movie scene 4k",
            "ruin": "ancient overgrown stone ruins jungle 4k cinematic"
        }
    },

    # 2. SPACE ANOMALY / LOST COSMONAUT / RADIO DISTRESS / SOVIET SPACE
    {
        "keywords": [
            "cosmonaut", "astronaut", "space", "vostok", "gagarin", "capsule", "orbit",
            "radio transmission", "morse", "torre bert", "turin", "interception",
            "deep space", "spacecraft", "drifting in space", "reentry", "lost cosmonauts"
        ],
        "cinematic_films": [
            "First Man",
            "Apollo 13",
            "Interstellar",
            "Gravity 2013",
            "The Right Stuff",
            "Ad Astra"
        ],
        "action_queries": {
            "entry": "Soviet Vostok rocket launch archival 1080p",
            "cockpit": "First Man cockpit intense vibration movie scene 4k",
            "radio": "radio operator listening to distress static movie scene 4k",
            "transmission": "military audio tape recorder spinning cinematic 4k",
            "drifting": "astronaut drifting in space Gravity movie scene 4k",
            "capsule": "Apollo 13 spacecraft tumbling in black space 4k",
            "reentry": "space capsule fiery reentry atmosphere movie scene 4k",
            "antenna": "giant radio telescope listening to cosmos 4k drone",
            "unsolved": "deep space darkness stars cinematic 4k"
        }
    },

    # 3. CELESTIAL PHENOMENON / SKY BATTLE / MEDIEVAL MYSTERY / NUREMBERG
    {
        "keywords": [
            "celestial", "nuremberg", "1561", "woodcut", "broadsheet", "hans glaser",
            "spheres", "cylinders", "crosses", "sky battle", "aerial battle", "bizarre sky",
            "ufo", "sun dog", "phenomenon", "medieval", "holy roman empire"
        ],
        "cinematic_films": [
            "Kingdom of Heaven",
            "The Seventh Seal",
            "Agora",
            "The Name of the Rose",
            "Close Encounters"
        ],
        "action_queries": {
            "entry": "medieval city sunrise Kingdom of Heaven cinematic 4k",
            "witnesses": "crowd in medieval town looking up at sky movie scene 4k",
            "sky_objects": "bizarre glowing spheres in sunrise sky cinematic 4k",
            "battle": "mysterious aerial dogfight glowing objects film clip 4k",
            "crash": "smoking object crash impact in countryside movie scene 4k",
            "woodcut": "Hans Glaser 1561 Nuremberg broadsheet high resolution scan",
            "smoke": "pillars of smoke rising on horizon cinematic 4k",
            "investigation": "medieval astronomer observing sky telescope cinematic 4k",
            "unsolved": "dramatic golden hour clouds glowing phenomenon 4k"
        }
    },

    # 4. SUBMARINE / MARITIME / GHOST SHIP / OCEAN DEPTHS
    {
        "keywords": [
            "submarine", "u-boat", "torpedo", "sonar", "depth charge", "ghost ship",
            "ocean", "atlantic", "pacific", "bermuda", "shipwreck", "hull", "sonar ping",
            "periscope", "k-19", "das boot"
        ],
        "cinematic_films": [
            "Das Boot",
            "The Hunt for Red October",
            "K-19 The Widowmaker",
            "The Abyss",
            "Crimson Tide"
        ],
        "action_queries": {
            "entry": "submarine surfacing rough stormy ocean movie scene 4k",
            "sonar": "submarine sonar operator ping red emergency light 4k",
            "interior": "Das Boot claustrophobic submarine interior movie scene 4k",
            "torpedo": "underwater torpedo launch cinematic film clip 4k",
            "ghost_ship": "abandoned empty ship drifting in heavy fog 4k",
            "deep": "deep ocean dark abyss underwater submarine 4k drone"
        }
    },

    # 5. ARCTIC / BLIZZARD / POLAR / COLD ISOLATION
    {
        "keywords": [
            "arctic", "antarctic", "ice", "blizzard", "glacier", "polar", "frozen",
            "snow", "dyatlov", "shackleton", "greenland", "subzero"
        ],
        "cinematic_films": [
            "The Terror",
            "The Thing 1982",
            "Arctic 2018",
            "Against the Ice",
            "Wind River"
        ],
        "action_queries": {
            "entry": "wooden ship trapped in polar ice pack The Terror 4k",
            "blizzard": "blinding arctic blizzard whiteout movie scene 4k",
            "footsteps": "explorers trudging through deep snow polar expedition 4k",
            "isolation": "vast frozen ice sheet drone 4k aerial",
            "tent": "shredded tent in arctic wind blizzard cinematic 4k"
        }
    },

    # 6. ANCIENT TOMB / ARCHAEOLOGY / UNDERGROUND CAVERNS
    {
        "keywords": [
            "tomb", "pyramid", "pharaoh", "excavation", "archaeologist", "cave",
            "cavern", "underground", "catacombs", "curse", "ruins", "temple"
        ],
        "cinematic_films": [
            "Indiana Jones and the Raiders of the Lost Ark",
            "The Mummy 1999",
            "As Above So Below",
            "National Treasure"
        ],
        "action_queries": {
            "torch": "lighting torch inside dark ancient tomb movie scene 4k",
            "excavation": "dusty archaeological dig site desert cinematic 4k",
            "hieroglyphs": "carved ancient symbols stone wall torchlight 4k",
            "catacombs": "walking through narrow underground catacombs 4k"
        }
    }
]


class CinematicBrain:
    """
    Analyzes event context and beat narration to provide vivid,
    genre-defining cinematic footage queries.
    """

    @classmethod
    def match_cinematic_profile(cls, text_corpus: str) -> Optional[Dict]:
        """Finds best matching cinematic reference profile for a topic."""
        t_lower = text_corpus.lower()
        best_profile = None
        max_matches = 0

        for profile in CINEMATIC_KNOWLEDGE_BASE:
            matches = sum(1 for kw in profile["keywords"] if re.search(rf"\b{re.escape(kw)}\b", t_lower))
            if matches > max_matches:
                max_matches = matches
                best_profile = profile

        if max_matches >= 1:
            return best_profile
        return None

    @classmethod
    def get_cinematic_queries_for_beat(
        cls,
        beat_text: str,
        topic_title: str,
        summary: str,
        entities: List[str],
        beat_sequence: int = 1
    ) -> List[str]:
        """
        Synthesizes high-impact cinematic video queries matching the exact beat action.
        """
        corpus = f"{topic_title} {summary} {' '.join(entities)}"
        profile = cls.match_cinematic_profile(corpus)

        queries: List[str] = []
        b_lower = beat_text.lower()

        if profile:
            films = profile["cinematic_films"]
            chosen_film = films[(beat_sequence - 1) % len(films)]

            # Check action mappings
            actions = profile["action_queries"]
            matched_action = None
            for act_key, query_val in actions.items():
                if act_key in b_lower or any(w in b_lower for w in act_key.split("_")):
                    matched_action = query_val
                    break

            if matched_action:
                queries.append(matched_action)
            else:
                # Pair beat words with chosen iconic film
                clean_beat_words = [
                    w for w in re.sub(r"[^\w\s]", "", b_lower).split()
                    if len(w) > 3 and w not in ["this", "that", "there", "where", "what", "with", "from", "after", "before"]
                ]
                key_action = " ".join(clean_beat_words[:2]) if clean_beat_words else "scene"
                queries.append(f"{chosen_film} {key_action} movie scene 4k")

            # Add alternate film clip query
            alt_film = films[beat_sequence % len(films)]
            queries.append(f"{alt_film} film clip 1080p")

        # General high-octane cinematic search based on beat keywords
        clean_words = [
            w for w in re.sub(r"[^\w\s]", "", b_lower).split()
            if len(w) > 3 and w not in ["this", "that", "there", "where", "what", "with", "from", "after", "before", "remains", "unsolved", "trace", "never", "found", "their", "about"]
        ]
        context_anchor = entities[0] if entities else topic_title
        if clean_words:
            lead = " ".join(clean_words[:2])
            queries.append(f"{lead} {context_anchor} movie scene 4k")
            queries.append(f"{context_anchor} {lead} documentary 4k")
        else:
            queries.append(f"{context_anchor} expedition cinematic 4k")

        # Ensure queries have high precision
        final_queries = []
        for q in queries:
            q_clean = re.sub(r"\s+", " ", q).strip()
            if q_clean and q_clean not in final_queries:
                final_queries.append(q_clean)

        return final_queries[:4]
