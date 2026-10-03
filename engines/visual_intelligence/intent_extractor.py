"""
Visual Intent Extractor.
Deconstructs script and narration into structured visual intents per beat:
primary/secondary entities, event, location, action, claim, tone,
visual type, preferred source, and evidence requirements.
Strictly niche agnostic: works universally across politics, history, science, economics, culture.
"""
import re
import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from .provenance import VisualContentType

logger = logging.getLogger(__name__)


@dataclass
class VisualIntent:
    """Explicit visual requirements for a single narrative beat."""
    beat_id: str
    beat_index: int
    narration_text: str
    start_time: float = 0.0
    end_time: float = 3.0
    duration: float = 3.0
    primary_entity: Optional[str] = None
    secondary_entities: List[str] = field(default_factory=list)
    event: Optional[str] = None
    location: Optional[str] = None
    date_context: Optional[str] = None
    action: Optional[str] = None
    claim_discussed: Optional[str] = None
    emotional_tone: str = "SERIOUS"              # SERIOUS, DRAMATIC, TENSE, REVEAL, URGENT, LIGHT
    required_visual_type: VisualContentType = VisualContentType.REAL_VIDEO
    preferred_source_tier: str = "SOURCE_A"       # SOURCE_A (Licensed), SOURCE_B (Editorial), SOURCE_C (Official), SOURCE_D (Graphic/Web)
    minimum_visual_duration: float = 2.0
    transition_requirements: str = "cut"
    evidence_overlay_requirements: Optional[Dict[str, Any]] = None
    search_queries: List[str] = field(default_factory=list)
    era: Optional[str] = None
    environment: Optional[str] = None
    weather: Optional[str] = None
    time_of_day: Optional[str] = None
    mood: Optional[str] = None
    subject: Optional[str] = None
    historical_classification: str = "HISTORICAL"
    architectural_requirements: Optional[str] = None
    clothing_requirements: Optional[str] = None
    forbidden_content: List[str] = field(default_factory=list)
    visual_action: Optional[str] = None
    target_object: Optional[str] = None
    people_actors: List[str] = field(default_factory=list)
    historical_context: Optional[str] = None
    important_nouns: List[str] = field(default_factory=list)
    important_verbs: List[str] = field(default_factory=list)
    disambiguating_terms: List[str] = field(default_factory=list)
    is_person_entity: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["required_visual_type"] = self.required_visual_type.value if isinstance(self.required_visual_type, VisualContentType) else self.required_visual_type
        return d


class VisualIntentExtractor:
    """Extracts explicit editorial visual intent from narration segments."""

    # Common entity patterns without hardcoding specific people or niches
    PROPER_NOUN_PATTERN = re.compile(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b')
    YEAR_PATTERN = re.compile(r'\b(1[89]\d{2}|20\d{2})\b')
    DATE_PATTERN = re.compile(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2}(?:,\s+\d{4})?\b', re.IGNORECASE)
    CLAIM_INDICATORS = ["announced", "declared", "passed", "revealed", "discovered", "signed", "warned", "voted", "claimed", "ruled", "banned"]

    # Common stop words that should never be identified as standalone entities
    STOP_WORDS = {
        "the", "a", "an", "this", "that", "these", "those", "in", "on", "at", "to",
        "for", "of", "with", "by", "from", "up", "about", "into", "over", "after",
        "before", "between", "under", "during", "without", "through", "and", "or",
        "but", "so", "as", "if", "when", "while", "where", "how", "all", "any",
        "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
        "not", "only", "own", "same", "than", "too", "very", "can", "will", "just",
        "should", "now", "it", "its", "their", "there", "then", "minute", "minutes",
        "hour", "hours", "day", "days", "year", "years"
    }

    def __init__(self):
        pass

    def extract_intent_from_beat(
        self,
        narration: str,
        beat_index: int,
        start_time: float,
        duration: float,
        topic_title: str = "",
        category: str = ""
    ) -> VisualIntent:
        """
        Niche-agnostic extraction of entity, event, context, and evidence requirements.
        Uses grammatical and syntactic entity extraction with fallback heuristics.
        """
        clean_text = (narration or "").strip()
        end_time = round(start_time + duration, 2)
        beat_id = f"intent_beat_{beat_index+1}"

        # 1. Extract potential entities (multi-word capitalized phrases or significant terms)
        words = clean_text.split()
        capitalized_phrases = self.PROPER_NOUN_PATTERN.findall(clean_text)
        
        # Filter out stop words and sentence-start capitalization unless genuine entity
        filtered_entities = []
        for phrase in capitalized_phrases:
            p_clean = phrase.strip()
            if p_clean.lower() in self.STOP_WORDS:
                continue
            p_words = p_clean.split()
            if clean_text.startswith(p_clean) and len(p_words) == 1:
                if p_clean.lower() in (topic_title + " " + category).lower() and len(p_clean) > 3:
                    filtered_entities.append(p_clean)
            else:
                filtered_entities.append(p_clean)

        # Also pull from topic title if no entities found in beat
        if not filtered_entities and topic_title:
            title_entities = [
                p.strip() for p in self.PROPER_NOUN_PATTERN.findall(topic_title)
                if p.strip().lower() not in self.STOP_WORDS and len(p.strip()) > 3
            ]
            if title_entities:
                filtered_entities.extend(title_entities)

        primary_entity = filtered_entities[0] if filtered_entities else (topic_title.split(":")[0] if ":" in topic_title else None)
        if primary_entity and primary_entity.lower() in self.STOP_WORDS:
            primary_entity = None
        secondary_entities = [e for e in filtered_entities[1:4] if e.lower() not in self.STOP_WORDS] if len(filtered_entities) > 1 else []

        # Check if primary_entity is a Person / Historical Figure
        is_person_entity = False
        if primary_entity:
            p_words = primary_entity.split()
            person_cues = [
                "he", "his", "him", "she", "her", "physicist", "scientist", "professor",
                "doctor", "dr", "president", "king", "queen", "minister", "general",
                "inventor", "author", "theorist", "philosopher", "mathematician",
                "astronomer", "cosmologist", "predicted", "said", "wrote", "proved"
            ]
            has_person_cues = any(re.search(rf"\b{cue}\b", clean_text, re.IGNORECASE) for cue in person_cues)
            non_person_keywords = [
                "space", "telescope", "hole", "star", "planet", "galaxy", "ocean", "river",
                "mountain", "city", "country", "empire", "treaty", "project", "mission",
                "operation", "void", "accretion", "plasma", "beaming", "radiation", "trap"
            ]
            if len(p_words) >= 2 and (has_person_cues or not any(k in primary_entity.lower() for k in non_person_keywords)):
                is_person_entity = True
            elif len(p_words) == 1 and has_person_cues and len(primary_entity) > 3 and not any(k in primary_entity.lower() for k in non_person_keywords):
                is_person_entity = True

        # 2. Extract Date / Time Context
        year_match = self.YEAR_PATTERN.search(clean_text) or self.YEAR_PATTERN.search(topic_title)
        date_match = self.DATE_PATTERN.search(clean_text)
        date_context = date_match.group(0) if date_match else (year_match.group(0) if year_match else None)

        # 3. Detect Action / Claim & Semantic Verbs
        action = None
        claim = None
        important_verbs = []
        COMMON_VERBS = [
            "struck", "collided", "exploded", "fled", "collapsed", "sank", "erupted",
            "fired", "escaped", "drained", "flooded", "disappeared", "attacked", "crashed",
            "invaded", "signed", "destroyed", "evacuated", "marching", "sailing", "running"
        ]
        for v in COMMON_VERBS:
            if re.search(r'\b' + v + r'\b', clean_text, re.IGNORECASE):
                important_verbs.append(v.lower())
                if not action:
                    action = v.lower()

        for ind in self.CLAIM_INDICATORS:
            if re.search(r'\b' + ind + r'\b', clean_text, re.IGNORECASE):
                if not action:
                    action = ind.lower()
                claim = clean_text
                if ind.lower() not in important_verbs:
                    important_verbs.append(ind.lower())
                break

        # Extract target object
        target_object = None
        COMMON_OBJECTS = [
            "iceberg", "cannon", "tunnel", "whirlpool", "vortex", "ship", "battleship",
            "mine", "plane", "bomber", "tank", "bridge", "volcano", "pipeline", "oil rig",
            "drilling rig", "crater"
        ]
        for obj in COMMON_OBJECTS:
            if re.search(r'\b' + obj + r'\b', clean_text, re.IGNORECASE):
                target_object = obj.lower()
                break

        # Extract people / actors
        people_actors = []
        ACTOR_TERMS = [
            "miners", "soldiers", "sailors", "officials", "scientists", "protesters",
            "politicians", "hikers", "passengers", "survivors", "infantry", "pilots"
        ]
        for act in ACTOR_TERMS:
            if re.search(r'\b' + act + r'\b', clean_text, re.IGNORECASE):
                people_actors.append(act.lower())

        # Extract disambiguating compound terms
        disambiguating_terms = []
        if primary_entity:
            disambiguating_terms.append(primary_entity)
        for phr in capitalized_phrases:
            if phr not in disambiguating_terms and len(phr.split()) > 1:
                disambiguating_terms.append(phr)
        if topic_title and topic_title not in disambiguating_terms:
            disambiguating_terms.append(topic_title)

        # 4. Determine Tone
        tone = "SERIOUS"
        lower_text = clean_text.lower()
        if any(w in lower_text for w in ["shocking", "stunning", "unbelievable", "secret", "suddenly", "twist"]):
            tone = "REVEAL"
        elif any(w in lower_text for w in ["war", "crisis", "threat", "danger", "collapse", "urgent", "breaking"]):
            tone = "URGENT"
        elif any(w in lower_text for w in ["bizarre", "ironic", "ridiculous", "laughable", "absurd"]):
            tone = "LIGHT"
        elif any(w in lower_text for w in ["tension", "escalat", "standoff", "conflict", "clash"]):
            tone = "TENSE"

        # 5. Required Visual Type & Preferred Source Tier (Problem 6: Real Moving Video Only)
        # Invariant: VIDEO ONLY. Reject animated maps, slideshows, screenshots, and diagrams.
        req_visual = VisualContentType.REAL_VIDEO
        pref_source = "SOURCE_B" if (primary_entity or "news" in category.lower()) else "SOURCE_A"

        if action and any(w in lower_text for w in ["document", "signed", "treaty", "law", "record", "headline", "reported"]):
            # Authentic archival moving footage of the signing/recording or original archive
            req_visual = VisualContentType.ARCHIVAL_VIDEO
            pref_source = "SOURCE_A"
        elif any(w in lower_text for w in ["historical", "archive", "war", "century", "disaster"]):
            req_visual = VisualContentType.ARCHIVAL_VIDEO

        # 6. Evidence Overlay Requirements
        overlay_req = None
        if claim or date_context or primary_entity:
            overlay_req = {
                "show_overlay": True,
                "headline": f"{primary_entity}: {action.title() if action else 'Development'}" if primary_entity else clean_text[:45],
                "attribution": "Official Public Record" if pref_source == "SOURCE_C" else "Documented Report",
                "date_label": date_context or "Verified Context",
                "badge_type": "FACT_CHECKED" if action else "CONTEXT"
            }

        # 7. Scene-level Semantic Requirements (Era, Location, Weather, Environment)
        location = None
        known_locations = [
            "London", "Paris", "Rome", "Siberia", "Kentucky", "Brazil", "Baltic",
            "Red Sea", "Hormuz", "Taiwan", "Washington", "Tokyo", "Berlin", "Vienna",
            "Strasbourg", "Louisiana", "Danube", "Crimea", "Egypt", "Pacific", "Atlantic"
        ]
        for loc in known_locations:
            if re.search(r'\b' + loc + r'\b', clean_text, re.IGNORECASE) or re.search(r'\b' + loc + r'\b', topic_title, re.IGNORECASE):
                location = loc
                break

        # Era derivation
        era = None
        historical_class = "HISTORICAL"
        forbidden = []
        year_val = int(year_match.group(0)) if year_match else None

        if "1837" in clean_text or "1837" in topic_title or "victorian" in lower_text or "victorian" in topic_title.lower():
            era = "Victorian / 1837"
            historical_class = "HISTORICAL"
        elif year_val:
            if year_val < 1900:
                era = f"{year_val} / 19th Century or earlier"
                historical_class = "HISTORICAL"
            elif year_val < 1960:
                era = f"{year_val} / Early-to-Mid 20th Century"
                historical_class = "HISTORICAL"
            elif year_val >= 2020:
                era = f"{year_val} / Contemporary"
                historical_class = "MODERN"
            else:
                era = f"{year_val}"
                historical_class = "HISTORICAL"
        elif any(w in lower_text for w in ["ancient", "rome", "roman", "medieval", "knight", "castle", "pharaoh"]):
            era = "Ancient / Medieval"
            historical_class = "HISTORICAL"
        elif any(w in lower_text for w in ["current", "breaking", "today", "drone", "cyber", "satellite", "guided-missile"]):
            era = "Modern / Contemporary"
            historical_class = "MODERN"

        # Forbidden modern / antique content filters
        if historical_class == "HISTORICAL":
            forbidden = [
                "modern car", "modern cars", "modern traffic", "traffic jam", "skyscraper", "skyscrapers",
                "smartphone", "smartphones", "laptop", "modern office", "neon", "asphalt highway"
            ]
        else:
            forbidden = [
                "19th century painting", "woodcut engraving", "ancient fresco", "antique lithograph", "medieval manuscript"
            ]

        # Weather & Time of Day
        weather = None
        for w_candidate in ["fog", "rain", "storm", "snow", "smoke", "haze", "sunny", "mist"]:
            if re.search(r'\b' + w_candidate + r'\b', lower_text):
                weather = w_candidate
                break

        time_of_day = None
        for t_candidate in ["night", "midnight", "dawn", "dusk", "evening", "morning", "afternoon"]:
            if re.search(r'\b' + t_candidate + r'\b', lower_text):
                time_of_day = t_candidate
                break

        # Environment
        environment = None
        for env_cand in ["narrow streets", "cobblestone", "street", "forest", "ocean", "sea", "desert", "castle", "palace", "battlefield", "harbor", "trench"]:
            if re.search(r'\b' + env_cand + r'\b', lower_text):
                environment = env_cand
                break

        # Construct visual action
        visual_action = None
        if primary_entity and action and target_object:
            visual_action = f"{primary_entity} {action} {target_object}"
        elif primary_entity and action:
            visual_action = f"{primary_entity} {action}"
        elif action and target_object:
            visual_action = f"{action} {target_object}"
        elif clean_text:
            visual_action = clean_text[:40]

        # Extract important nouns
        important_nouns = []
        if primary_entity:
            important_nouns.append(primary_entity)
        if target_object and target_object not in important_nouns:
            important_nouns.append(target_object)
        if location and location not in important_nouns:
            important_nouns.append(location)
        for phr in capitalized_phrases:
            if phr not in important_nouns:
                important_nouns.append(phr)

        # 8. Formulate targeted search queries (Anti-Generic: ENTITY + ACTION + EVENT + CONTEXT)
        queries = []
        clean_topic = re.sub(r'[^\w\s]', '', topic_title).strip() if topic_title else ""
        topic_words = [w for w in clean_topic.split() if w.lower() not in self.STOP_WORDS and len(w) > 2]
        core_topic = " ".join(topic_words[:4]) or clean_topic[:30]

        # For historical topics, prefix with the era (e.g. 19th century) to find authentic period footage,
        # avoiding topic-title poisoning that leads to amateur slideshow video essays.
        if historical_class == "HISTORICAL":
            era_str = era or ""
            prefix = "19th century" if ("19th" in era_str or "18" in era_str or "victorian" in era_str.lower()) else (era_str or "historical")
        else:
            prefix = core_topic

        if primary_entity and action and (target_object or location):
            queries.append(f"{prefix} {primary_entity} {action} {target_object or location}")
        if primary_entity and action:
            queries.append(f"{prefix} {primary_entity} {action}")
        elif action and (target_object or location):
            queries.append(f"{prefix} {action} {target_object or location}")
        elif action:
            queries.append(f"{prefix} {action}")

        if primary_entity and primary_entity.lower() not in prefix.lower():
            queries.append(f"{prefix} {primary_entity} archival footage")

        if prefix:
            queries.append(f"{prefix} archival documentary footage")
        if not queries:
            queries.append(f"{clean_text[:25]}")

        if is_person_entity and primary_entity:
            req_visual = VisualContentType.ARCHIVAL_VIDEO
            pref_source = "SOURCE_B"
            forbidden.extend(["graph", "curve", "diagram", "canvas", "abstract", "still card", "infographic", "map"])
            queries.insert(0, f"{primary_entity} archival film footage")
            queries.insert(1, f"{primary_entity} historical newsreel")
            queries.insert(2, f"{primary_entity} speech lecture video")

        # Ensure queries are descriptive moving video queries (at least 2 words, no generic single words, no image words)
        GENERIC_SINGLE_WORDS = {"history", "soldier", "city", "war", "businessman", "people"}
        IMAGE_WORDS = ["photo", "still", "image", "painting", "portrait", "illustration", "screenshot", "slideshow"]
        clean_queries = []
        for q in queries:
            q_clean = q.strip()
            for iw in IMAGE_WORDS:
                q_clean = re.sub(rf"\b{re.escape(iw)}\b", "", q_clean, flags=re.IGNORECASE).strip()
            q_clean = re.sub(r"\s+", " ", q_clean).strip()
            q_words = q_clean.split()
            if len(q_words) == 1:
                if q_clean.lower() in GENERIC_SINGLE_WORDS:
                    q_clean = f"{q_clean} archival documentary motion footage"
                else:
                    q_clean = f"{q_clean} documentary footage"
            if len(q_clean.split()) >= 2:
                clean_queries.append(q_clean)
        if not clean_queries:
            clean_queries = [f"{topic_title or clean_text[:25]} archival documentary video".strip()]

        hist_context = f"{date_context or era or ''} {topic_title or ''}".strip() or None

        return VisualIntent(
            beat_id=beat_id,
            beat_index=beat_index,
            narration_text=clean_text,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            primary_entity=primary_entity,
            secondary_entities=secondary_entities,
            event=topic_title[:60] if topic_title else None,
            location=location,
            date_context=date_context,
            action=action,
            claim_discussed=claim,
            emotional_tone=tone,
            required_visual_type=req_visual,
            preferred_source_tier=pref_source,
            minimum_visual_duration=min(2.0, duration),
            transition_requirements="cut" if tone in ("URGENT", "REVEAL") else "crossfade",
            evidence_overlay_requirements=overlay_req,
            search_queries=clean_queries,
            era=era,
            environment=environment,
            weather=weather,
            time_of_day=time_of_day,
            mood=tone,
            subject=primary_entity,
            historical_classification=historical_class,
            forbidden_content=forbidden,
            visual_action=visual_action,
            target_object=target_object,
            people_actors=people_actors,
            historical_context=hist_context,
            important_nouns=important_nouns,
            important_verbs=important_verbs,
            disambiguating_terms=disambiguating_terms,
            is_person_entity=is_person_entity
        )
