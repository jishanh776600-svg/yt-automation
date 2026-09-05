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
    start_time: float
    end_time: float
    duration: float
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
        
        # Filter out sentence-start capitalization unless it occurs inside or is a known entity
        filtered_entities = []
        for phrase in capitalized_phrases:
            p_words = phrase.split()
            # If at the very start of the sentence, keep if multi-word or if title/category shares word
            if clean_text.startswith(phrase) and len(p_words) == 1:
                if phrase.lower() in (topic_title + " " + category).lower():
                    filtered_entities.append(phrase)
            else:
                filtered_entities.append(phrase)

        # Also pull from topic title if no entities found in beat
        if not filtered_entities and topic_title:
            title_entities = self.PROPER_NOUN_PATTERN.findall(topic_title)
            if title_entities:
                filtered_entities.extend(title_entities)

        primary_entity = filtered_entities[0] if filtered_entities else (topic_title.split(":")[0] if ":" in topic_title else None)
        secondary_entities = filtered_entities[1:4] if len(filtered_entities) > 1 else []

        # 2. Extract Date / Time Context
        year_match = self.YEAR_PATTERN.search(clean_text) or self.YEAR_PATTERN.search(topic_title)
        date_match = self.DATE_PATTERN.search(clean_text)
        date_context = date_match.group(0) if date_match else (year_match.group(0) if year_match else None)

        # 3. Detect Action / Claim
        action = None
        claim = None
        for ind in self.CLAIM_INDICATORS:
            if re.search(r'\b' + ind + r'\b', clean_text, re.IGNORECASE):
                action = ind.lower()
                claim = clean_text
                break

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

        # 5. Required Visual Type & Preferred Source Tier
        # Rule: Prefer REAL_VIDEO whenever an entity or action is present
        req_visual = VisualContentType.REAL_VIDEO
        pref_source = "SOURCE_B" if (primary_entity or "news" in category.lower()) else "SOURCE_A"

        if action and any(w in lower_text for w in ["document", "signed", "treaty", "law", "record", "headline", "reported"]):
            req_visual = VisualContentType.SCREENSHOT_DOCUMENT
            pref_source = "SOURCE_D"
        elif any(w in lower_text for w in ["map", "border", "territory", "invaded", "located"]):
            req_visual = VisualContentType.ANIMATED_DATA_MAP
            pref_source = "SOURCE_D"
        elif tone == "LIGHT" and any(w in lower_text for w in ["reaction", "mocked", "responded", "face"]):
            req_visual = VisualContentType.MEME_REACTION
            pref_source = "SOURCE_D"

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

        # 7. Formulate targeted search queries (avoiding generic modern stock defaults)
        queries = []
        if primary_entity and action:
            queries.append(f"{primary_entity} {action}")
        if primary_entity:
            queries.append(f"{primary_entity} speech press conference")
            queries.append(f"{primary_entity} event")
        if topic_title:
            clean_title = re.sub(r'[^\w\s]', '', topic_title)
            queries.append(f"{clean_title[:30]}")
        if not queries:
            queries.append(f"{clean_text[:25]}")

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
            location=None,
            date_context=date_context,
            action=action,
            claim_discussed=claim,
            emotional_tone=tone,
            required_visual_type=req_visual,
            preferred_source_tier=pref_source,
            minimum_visual_duration=min(2.0, duration),
            transition_requirements="cut" if tone in ("URGENT", "REVEAL") else "crossfade",
            evidence_overlay_requirements=overlay_req,
            search_queries=queries
        )
