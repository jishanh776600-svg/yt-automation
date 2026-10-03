"""
Deterministic Multi-Factor Visual Candidate Scoring Engine.
Ranks visual candidates by:
  - semantic_relevance
  - entity_match
  - event_match
  - location_match
  - date_match
  - motion_score (video-first)
  - visual_quality / resolution
  - freshness
  - source_quality
  - editorial_fit
  - rights_confidence
  - provenance_completeness

Penalties:
  - duplicate
  - near_duplicate
  - recent_use
  - generic_stock
  - rights_risk
  - misleading_context

Strictly prefers accurate/contextually relevant footage over beautiful but generic footage.
"""
import re
import logging
from typing import List, Dict, Any, Optional, Set, Tuple
from .models import VisualCandidate, VisualIntent, RightsStatus, VisualContentType, SourceTier, SourceContentClass

logger = logging.getLogger(__name__)


class VisualCandidateScorer:
    """
    Deterministic scoring and ranking model for visual assets.
    Prioritizes real entity footage, authentic events, and verified provenance.
    """

    # Multi-factor weights summing to 1.00
    WEIGHT_RELEVANCE = 0.14
    WEIGHT_ENTITY = 0.18
    WEIGHT_EVENT = 0.10
    WEIGHT_ACTION = 0.12
    WEIGHT_LOCATION = 0.06
    WEIGHT_DATE = 0.04
    WEIGHT_MOTION = 0.12
    WEIGHT_QUALITY = 0.07
    WEIGHT_INTEREST = 0.05
    WEIGHT_SOURCE_QUALITY = 0.04
    WEIGHT_EDITORIAL_FIT = 0.03
    WEIGHT_RIGHTS_CONFIDENCE = 0.02
    WEIGHT_PROVENANCE = 0.03

    # Step 2: Minimum Semantic Relevance Threshold for Qualification
    MIN_SEMANTIC_RELEVANCE_THRESHOLD = 0.40

    # Controlled Action Synonym Clusters for High-Precision Event Matching
    ACTION_SYNONYM_CLUSTERS = {
        "exploding": ["exploding", "explosion", "firing", "blast", "smoke blast", "bursting", "detonating", "erupting", "blew up"],
        "fled": ["fled", "fleeing", "running", "evacuating", "evacuation", "rushing", "tunnel escape", "escaping", "scrambling"],
        "whirlpool": ["whirlpool", "vortex", "swirling", "draining", "rushing water", "sinkhole", "crater flooding", "swallowed"],
        "sinking": ["sinking", "submerged", "taking on water", "listing", "capsizing", "going down", "underwater"],
        "crashing": ["crashing", "crash", "collision", "colliding", "impact", "spiraling", "wreckage", "falling"],
        "erupting": ["erupting", "eruption", "lava", "ash cloud", "pyroclastic", "explosion", "spewing"],
        "protesting": ["protesting", "protest", "demonstration", "marching", "rally", "chanting", "riot", "clashing"],
        "arresting": ["arresting", "arrest", "handcuffing", "detaining", "police escort", "custody"],
        "striking": ["striking", "missile strike", "airstrike", "bombing", "drone strike", "shelling", "impact"],
        "battle": ["battle", "combat", "soldiers", "infantry", "troops", "fighting", "war", "charge", "assault", "frontline", "action", "fell", "fighters"],
        "cannon": ["cannon", "artillery", "bombardment", "shelling", "firing", "broadside", "gunfire", "explosion", "cannons"],
        "sailing": ["sailing", "warship", "battleship", "fleet", "steaming", "naval", "cruiser", "destroyer", "vessel", "ship", "ships"],
        "marching": ["marching", "march", "parade", "formation", "advancing", "soldiers", "troops", "patrol", "rushing"],
        "flag": ["flag", "flagpole", "lowered", "surrender", "hauled down", "banner", "colors"]
    }

    CONTRADICTORY_STATIC_MARKERS = [
        "museum", "museum display", "exhibit", "parked", "stationary", "calm", "docked",
        "peaceful", "dormant", "static display", "model", "replica", "monument", "quiet shore",
        "mining equipment", "stationary drill", "coal cart"
    ]

    GENERIC_ENTITY_TOKENS = {
        "lake", "mountain", "river", "ship", "plane", "car", "building", "politician",
        "man", "woman", "soldier", "drill", "water", "forest", "city", "ocean", "sea",
        "mine", "tunnel", "island", "bridge", "road", "vehicle", "aircraft", "train"
    }

    GENERIC_FOOTAGE_MARKERS = [
        "generic", "stock footage", "scenery", "scenic", "peaceful", "calm", "landscape",
        "nature background", "ambient", "b-roll", "establishing shot of nature",
        "calm water", "relaxing", "drone view of mountains", "generic politician",
        "generic business", "calm lake", "scenic mountain"
    ]

    PROHIBITED_GRAPHIC_MARKERS = [
        "map", "maps", "animated map", "map animation", "diagram", "diagrams",
        "infographic", "infographics", "engraving", "engravings", "illustration",
        "illustrations", "drawing", "drawings", "sketch", "slideshow", "slide show",
        "still image", "still photo", "photo slideshow", "image montage",
        "title card", "text card", "timeline graphic"
    ]

    # Motion scores by content type (Video-First Rule)
    MOTION_TIERS = {
        VisualContentType.REAL_VIDEO: 1.0,
        VisualContentType.LIVE_EVENT_FOOTAGE: 0.95,
        VisualContentType.ARCHIVAL_VIDEO: 0.88,
        VisualContentType.OFFICIAL_PUBLIC_RECORD: 0.85,
        VisualContentType.ANIMATED_DATA_MAP: 0.0,
        VisualContentType.MEME_REACTION: 0.80,
        VisualContentType.SCREENSHOT_DOCUMENT: 0.0,
        VisualContentType.STATIC_PHOTO: 0.0,
        VisualContentType.GENERIC_STOCK_VIDEO: 0.40,
        VisualContentType.GENERIC_STOCK_IMAGE: 0.0
    }

    HIGH_MOTION_KEYWORDS = [
        "marching", "running", "sailing", "walking", "moving", "flying", "flowing",
        "crashing", "exploding", "driving", "drifting", "chasing", "storm", "waves",
        "traffic", "crowd", "smoke", "fire", "combat", "battle", "riding", "spinning",
        "pouring", "surging", "action", "charging", "hurrying", "galloping"
    ]
    LOW_MOTION_KEYWORDS = [
        "still", "static", "stationary", "posed", "portrait", "freeze", "locked off",
        "tripod still", "no movement", "motionless", "sleeping", "statue", "monument",
        "standing still", "slideshow"
    ]
    VISUAL_INTEREST_KEYWORDS = [
        "crowd", "battlefield", "soldiers", "ship", "ocean", "storm", "street",
        "smoke", "action", "interaction", "vehicle", "locomotive", "train",
        "confrontation", "explosion", "waves", "protest", "speech", "ceremony",
        "handwritten", "document", "artifact", "fire", "horses", "castle", "bridge"
    ]

    def compute_motion_score(self, candidate: VisualCandidate) -> float:
        """Calculates motion score adhering strictly to the Video-First Rule with action detection."""
        base_motion = self.MOTION_TIERS.get(candidate.content_type, 0.50)
        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.entity_tags)}".lower()

        # Check explicit high motion action verbs
        if any(re.search(rf"\b{re.escape(k)}\b", cand_text) for k in self.HIGH_MOTION_KEYWORDS):
            base_motion = min(1.0, base_motion + 0.15)

        # Check low motion / effectively static footage
        if any(re.search(rf"\b{re.escape(k)}\b", cand_text) for k in self.LOW_MOTION_KEYWORDS):
            base_motion = max(0.10, base_motion - 0.35)

        # Attribute-based motion if available
        if hasattr(candidate, "motion_intensity") and candidate.motion_intensity is not None:
            base_motion = round(0.4 * base_motion + 0.6 * float(candidate.motion_intensity), 3)

        if candidate.is_video:
            if candidate.width >= 1080 and candidate.height >= 1080:
                base_motion = min(1.0, base_motion + 0.05)
        return round(base_motion, 3)

    def evaluate_visual_interest(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates visual dynamism: human interaction, vehicles, crowds, environmental movement."""
        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.entity_tags)}".lower()
        score = 0.50
        matched = sum(1 for kw in self.VISUAL_INTEREST_KEYWORDS if re.search(rf"\b{re.escape(kw)}\b", cand_text))
        if matched >= 3:
            score = 1.0
        elif matched >= 1:
            score = 0.80

        # Reward candidates matching the intent's action or environment
        if intent.action and intent.action.lower() in cand_text:
            score = min(1.0, score + 0.15)
        if intent.environment and intent.environment.lower() in cand_text:
            score = min(1.0, score + 0.10)
        return round(score, 2)

    def evaluate_entity_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """
        Evaluates whether candidate specifically depicts the requested primary or secondary entities.
        Includes entity disambiguation against false generic token matches:
        E.g. for 'Lake Peigneur', matching 'lake' alone without 'peigneur' receives a heavy penalty.
        """
        if not intent.primary_entity:
            return 0.50  # Neutral baseline when no specific entity is requested

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.entity_tags)}".lower()
        entity_lower = intent.primary_entity.lower().strip()

        # Exact match of full entity
        if entity_lower in cand_text:
            return 1.0

        # Check disambiguating / compound terms
        entity_tokens = [t for t in re.split(r'\s+', entity_lower) if len(t) > 2]
        specific_tokens = [t for t in entity_tokens if t not in self.GENERIC_ENTITY_TOKENS]

        if specific_tokens:
            # Specific identifying tokens exist (e.g. 'peigneur', 'dyatlov', 'kennedy', 'titanic')
            specific_matches = sum(1 for t in specific_tokens if re.search(rf"\b{re.escape(t)}\b", cand_text))
            if specific_matches > 0:
                ratio = specific_matches / len(specific_tokens)
                return round(0.70 + (0.30 * ratio), 2)
            else:
                # Matched generic words (like 'lake' or 'mountain') but NOT the specific entity!
                # False generic token match defense
                return 0.15

        # Fallback for entities with no generic tokens: standard token overlap
        if entity_tokens:
            matches = sum(1 for t in entity_tokens if re.search(rf"\b{re.escape(t)}\b", cand_text))
            match_ratio = matches / len(entity_tokens)
            if match_ratio >= 0.5:
                return round(0.50 + (0.50 * match_ratio), 2)

        # Check secondary entities
        for sec in intent.secondary_entities:
            if sec.lower() in cand_text:
                return 0.65

        # Check people/actors if available
        if hasattr(intent, "people_actors") and intent.people_actors:
            for actor in intent.people_actors:
                if actor.lower() in cand_text:
                    return 0.75

        # Check if candidate matches visual query context for action/setting depiction
        query_words = set()
        for q in getattr(intent, "search_queries", []) or []:
            query_words.update(re.findall(r'\b\w{3,}\b', q.lower()))
        cand_tokens = set(re.findall(r'\b\w{3,}\b', cand_text))
        if len(cand_tokens.intersection(query_words)) >= 2:
            return 0.65  # Relevant setting / action depiction

        # No entity match: penalty when a specific person/entity was requested
        return 0.20

    def evaluate_action_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """
        Evaluates dynamic action match against candidate footage.
        Rewards action verb / synonym cluster matches.
        Penalizes contradictory static footage (e.g. stationary cannon when explosion is needed,
        peaceful lake when whirlpool is needed, equipment when evacuation is needed).
        """
        target_action = getattr(intent, "visual_action", None) or intent.action or ""
        if not target_action and hasattr(intent, "important_verbs") and intent.important_verbs:
            target_action = " ".join(intent.important_verbs)

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.event_tags)} {' '.join(candidate.entity_tags)}".lower()

        if not target_action:
            return 0.50  # Neutral baseline when no specific action requested

        target_lower = target_action.lower()

        # Find matching synonym clusters
        relevant_synonyms = set()
        for action_key, syns in self.ACTION_SYNONYM_CLUSTERS.items():
            if action_key in target_lower or any(s in target_lower for s in syns):
                relevant_synonyms.update(syns)

        if not relevant_synonyms:
            words = [w for w in re.findall(r'\b\w{3,}\b', target_lower) if w not in ("the", "and", "with", "into", "from")]
            relevant_synonyms = set(words)

        # Check action match
        action_matched = False
        if target_lower in cand_text:
            action_matched = True
        elif relevant_synonyms and any(re.search(rf"\b{re.escape(syn)}\b", cand_text) for syn in relevant_synonyms):
            action_matched = True
        else:
            for q in getattr(intent, "search_queries", []) or []:
                for qw in re.findall(r'\b\w{3,}\b', q.lower()):
                    for syns in self.ACTION_SYNONYM_CLUSTERS.values():
                        if qw in syns and any(re.search(rf"\b{re.escape(s)}\b", cand_text) for s in syns):
                            action_matched = True
                            break

        # Check contradictory static markers
        has_static_contradiction = any(re.search(rf"\b{re.escape(sm)}\b", cand_text) for sm in self.CONTRADICTORY_STATIC_MARKERS)

        if action_matched:
            if has_static_contradiction:
                return 0.35  # Conflicted: mentions action term but also museum/parked/calm
            return 1.00
        elif has_static_contradiction:
            return 0.10  # Contradictory static footage when dynamic action required
        else:
            return 0.25  # Missing action

    def evaluate_generic_footage_penalty(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """
        Applies a penalty if generic footage (scenery, calm b-roll, generic stock) is offered
        for a scene requiring a specific historical or dramatic event/entity.
        """
        if candidate.content_type in (VisualContentType.ARCHIVAL_VIDEO, VisualContentType.REAL_VIDEO, VisualContentType.LIVE_EVENT_FOOTAGE):
            return 0.0  # Real archival and live documentary footage is not generic stock

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.event_tags)} {' '.join(candidate.entity_tags)}".lower()
        penalty = 0.0

        # Check if intent requires a specific entity or event
        has_specific_intent = bool(intent.primary_entity or intent.event or getattr(intent, "disambiguating_terms", None))
        if not has_specific_intent:
            return 0.0

        # Check for generic markers in candidate text
        has_generic_marker = any(re.search(rf"\b{re.escape(gm)}\b", cand_text) for gm in self.GENERIC_FOOTAGE_MARKERS)

        # Check if candidate lacks specific identifying tokens
        lacks_specific = True
        if intent.primary_entity:
            entity_tokens = [t for t in re.split(r'\s+', intent.primary_entity.lower()) if len(t) > 2 and t not in self.GENERIC_ENTITY_TOKENS]
            if entity_tokens and any(t in cand_text for t in entity_tokens):
                lacks_specific = False
        if intent.event:
            event_tokens = [t for t in re.split(r'\s+', intent.event.lower()) if len(t) > 3 and t not in self.GENERIC_ENTITY_TOKENS]
            if event_tokens and any(t in cand_text for t in event_tokens):
                lacks_specific = False

        if has_generic_marker and lacks_specific:
            penalty += 0.35
        elif lacks_specific and candidate.content_type in (VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE):
            penalty += 0.25

        return penalty

    def evaluate_event_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates match to the news or historical event being discussed."""
        if not intent.event and not intent.action:
            return 0.50

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.event_tags)}".lower()
        target_event = (intent.event or "").lower()
        target_action = (intent.action or "").lower()

        score = 0.30
        if target_action and target_action in cand_text:
            score += 0.35
        if target_event:
            tokens = [
                t.lower() for t in re.findall(r'[a-zA-Z0-9]{3,}', target_event)
                if t.lower() not in self.GENERIC_ENTITY_TOKENS and t.lower() not in ("the", "and", "for", "with", "from")
            ]
            if not tokens:
                tokens = [t.lower() for t in re.findall(r'[a-zA-Z0-9]{3,}', target_event)]
            if tokens:
                matches = sum(1 for t in tokens if re.search(rf"\b{re.escape(t)}\b", cand_text))
                score += min(0.35, 0.35 * (matches / max(1, len(tokens))))

        query_words = set()
        for q in getattr(intent, "search_queries", []) or []:
            query_words.update(re.findall(r'\b\w{3,}\b', q.lower()))
        cand_tokens = set(re.findall(r'\b\w{3,}\b', cand_text))
        if len(cand_tokens.intersection(query_words)) >= 2:
            score = max(score, 0.65)

        return min(1.0, round(score, 2))

    def evaluate_location_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates geographic / location relevance."""
        if not intent.location:
            return 0.50  # Neutral if no location required

        cand_text = f"{candidate.title} {candidate.description} {' '.join(candidate.event_tags)} {' '.join(candidate.entity_tags)}".lower()
        loc_lower = intent.location.lower()

        if loc_lower in cand_text:
            return 1.0

        loc_tokens = [t for t in re.split(r'\s+', loc_lower) if len(t) > 2]
        if loc_tokens:
            matches = sum(1 for t in loc_tokens if re.search(rf"\b{re.escape(t)}\b", cand_text))
            if matches > 0:
                return round(0.50 + 0.50 * (matches / len(loc_tokens)), 2)

        return 0.20

    def evaluate_date_match(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates chronological era or date alignment."""
        if not intent.date_context:
            return 0.50

        target_date = str(intent.date_context).lower()
        cand_text = f"{candidate.title} {candidate.description} {getattr(candidate.provenance, 'publication_date', '')}".lower()

        if target_date in cand_text:
            return 1.0

        # Check year extraction match
        target_years = re.findall(r'\b(1[89]\d{2}|20\d{2})\b', target_date)
        if target_years:
            if any(y in cand_text for y in target_years):
                return 0.90

        return 0.40

    def evaluate_semantic_relevance(self, candidate: VisualCandidate, intent: VisualIntent) -> float:
        """Evaluates lexical and thematic overlap with the narration beat and visual query."""
        cand_words = set(re.findall(r'\b\w{3,}\b', f"{candidate.title} {candidate.description}".lower()))
        beat_words = set(re.findall(r'\b\w{3,}\b', intent.narration_text.lower()))

        # Include visual query and action intent words
        query_words = set()
        for q in getattr(intent, "search_queries", []) or []:
            query_words.update(re.findall(r'\b\w{3,}\b', q.lower()))
        if intent.action:
            query_words.update(re.findall(r'\b\w{3,}\b', intent.action.lower()))
        if intent.environment:
            query_words.update(re.findall(r'\b\w{3,}\b', intent.environment.lower()))

        target_words = beat_words.union(query_words)
        if not target_words:
            return 0.50

        overlap = cand_words.intersection(target_words)
        query_overlap = cand_words.intersection(query_words) if query_words else set()

        if len(query_overlap) >= 2:
            return min(1.0, 0.70 + 0.05 * len(query_overlap))

        ratio = len(overlap) / max(3, min(8, len(target_words)))
        return min(1.0, round(ratio * 1.5, 2))

    def evaluate_provenance_completeness(self, candidate: VisualCandidate) -> float:
        """Evaluates whether all required rights and origin fields are verified."""
        prov = candidate.provenance
        if not prov:
            return 0.20

        score = 0.20
        if prov.creator:
            score += 0.20
        if prov.publisher:
            score += 0.20
        if prov.source_url:
            score += 0.20
        if prov.license_name and prov.license_name != "Unknown":
            score += 0.20
        return round(score, 2)

    def evaluate_era_and_context_compatibility(
        self,
        candidate: Any,
        intent: Any
    ) -> Tuple[float, str]:
        """
        Hard defense against anachronisms and contradictory visuals:
          - 1837 London -> rejects modern London streets, modern cars, traffic, skyscrapers.
          - Ancient/Medieval/WWII -> rejects modern office, modern apartment, modern electronics.
          - Modern geopolitics/current events -> rejects antique engravings, 19th-century paintings.
        """
        # Handle swapped arguments gracefully
        if hasattr(candidate, "visual_query") or hasattr(candidate, "forbidden_content") or hasattr(candidate, "era"):
            candidate, intent = intent, candidate

        if isinstance(candidate, dict):
            cand_title = candidate.get("title", "")
            cand_tags = candidate.get("tags", [])
            cand_text = f"{cand_title} {' '.join(cand_tags)}".lower()
        else:
            cand_title = getattr(candidate, 'title', '')
            cand_ev = getattr(candidate, 'event_tags', []) or []
            cand_en = getattr(candidate, 'entity_tags', []) or []
            cand_text = f"{cand_title} {' '.join(cand_ev)} {' '.join(cand_en)}".lower()

        # Check explicit forbidden items from intent
        forbidden = getattr(intent, "forbidden_content", []) or []
        for item in forbidden:
            if re.search(rf"\b{re.escape(item.lower())}\b", cand_text):
                return 0.0, f"Anachronistic content '{item}' forbidden for {getattr(intent, 'era', 'this era')}"

        hist_class = getattr(intent, "historical_classification", "HISTORICAL")

        # 1. Historical Scene Defense against Modern Visuals
        is_pre_modern = (hist_class == "HISTORICAL") or any(k in (getattr(intent, "era", "") or "").lower() for k in ["victorian", "ancient", "medieval", "1800", "1700", "1830s"])
        if getattr(intent, "date_context", None):
            year_matches = re.findall(r'\b(1[0-9]{3}|20[0-2][0-9])\b', str(intent.date_context))
            if year_matches and any(int(y) < 1960 for y in year_matches):
                is_pre_modern = True

        if is_pre_modern:
            modern_markers = [
                "modern car", "modern cars", "modern traffic", "traffic jam", "highway", "skyscraper", "skyscrapers",
                "smartphone", "smartphones", "laptop", "modern office", "asphalt", "neon lights",
                "modern city", "contemporary downtown", "modern london", "modern street"
            ]
            for m in modern_markers:
                if re.search(rf"\b{re.escape(m)}\b", cand_text):
                    return 0.0, f"Modern anachronism '{m}' rejected for historical pre-modern scene ({getattr(intent, 'date_context', None) or getattr(intent, 'era', '')})"

        # 2. Modern Scene Defense against Antique/Archival Artifacts
        if hist_class == "MODERN" or any(k in (getattr(intent, "era", "") or "").lower() for k in ["current", "breaking", "today", "modern", "2024", "2025", "2026"]):
            antique_markers = [
                "19th century painting", "woodcut engraving", "ancient fresco", "antique lithograph", "medieval manuscript", "18th century etching", "antique renaissance", "ancient parchment"
            ]
            for a in antique_markers:
                if re.search(rf"\b{re.escape(a)}\b", cand_text):
                    return 0.0, f"Antique archival artwork '{a}' rejected for modern current-events scene"

        return 1.0, ""

    @classmethod
    def classify_source_content(
        cls,
        candidate: VisualCandidate,
        intent: Optional[VisualIntent] = None
    ) -> Tuple[SourceTier, SourceContentClass]:
        """
        Deterministically classifies candidate footage into the 6-Tier Retrieval Hierarchy
        and 18-category SourceContentClass based on provenance, title, channel, and visual metadata.
        """
        title = (candidate.title or "").lower()
        desc = (candidate.description or "").lower()
        creator = (candidate.creator or "").lower()
        publisher = (candidate.publisher or "").lower()
        src_name = (candidate.source_name or "").lower()
        src_url = (candidate.source_url or "").lower()
        all_text = f"{title} {desc} {creator} {publisher} {src_name} {src_url}"

        # 1. Prohibited explainer / talking head / podcast / reaction / flat graphics
        if any(m in title or m in creator for m in [
            "casually explained", "oversimplified", "ted-ed", "crash course",
            "simple history", "top 10 facts", "top 5 facts", "infographics show"
        ]):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.EXPLAINER

        if any(m in title or m in desc for m in ["podcast", "interview with", "exclusive interview", "q&a"]):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.PODCAST

        if any(m in title for m in ["reaction", "reacts to", "blind reaction"]):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.REACTION

        if candidate.metadata.get("has_presenter") or "talking head" in all_text:
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.TALKING_HEAD

        if candidate.metadata.get("is_graphic") or any(m in title for m in ["animated map", "infographic animation", "cartoon animation", "slideshow"]):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.FLAT_GRAPHIC

        if candidate.metadata.get("has_watermark") and "title" in str(candidate.metadata.get("watermark_error", "")):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.TITLE_CARD

        # 2. Tier 1: Cinematic Docudrama / Feature Film
        docudrama_markers = ["docudrama", "dramatization", "reenactment", "movie scene", "film clip", "feature film", "cinema", "theatrical"]
        if any(m in all_text for m in docudrama_markers) or src_name == "movie" or candidate.source_class == "SOURCE_A_CINEMATIC":
            return SourceTier.TIER_1_CINEMATIC_DOCUDRAMA, SourceContentClass.DOCUMENTARY_REENACTMENT

        # 3. Tier 2: Institutional / Official / Archival
        institutional_markers = ["nasa", "goddard", "eso", "usgs", "esa", "cern", "national archives", "noaa", "defense visual information", "dvidshub"]
        if any(m in all_text for m in institutional_markers) or src_name in ("official", "nasa"):
            return SourceTier.TIER_2_INSTITUTIONAL_ARCHIVE, SourceContentClass.INSTITUTIONAL_VISUALIZATION

        # 4. Tier 3: Museum / University / Academic
        museum_markers = ["smithsonian", "beinecke", "yale", "oxford", "harvard", "museum", "loc.gov", "british museum", "archives.gov", "national gallery"]
        if any(m in all_text for m in museum_markers) or src_name in ("archive", "internet_archive", "wikimedia", "wikimedia_commons"):
            return SourceTier.TIER_3_MUSEUM_ACADEMIC, SourceContentClass.ARTIFACT_DOCUMENTATION

        # 5. Tier 4: Original / On-Location Verified
        if "on location" in all_text or "original camera" in all_text or "field recording" in all_text:
            return SourceTier.TIER_4_ORIGINAL_VERIFIED, SourceContentClass.ORIGINAL_ON_LOCATION

        # 6. Tier 6: Stock Fallback
        if src_name in ("pexels", "pixabay") or candidate.content_type in (VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE):
            return SourceTier.TIER_6_STOCK_FALLBACK, SourceContentClass.STOCK_CONTEXT

        # 7. Tier 5: Clean Web Video (YouTube documentary, news broadcast, authentic report)
        if any(m in all_text for m in ["documentary", "archive", "archival", "news report", "broadcast", "itn", "associated press", "bbc", "reuters", "cnn", "nbc"]):
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.ARCHIVAL

        if intent and intent.primary_entity and intent.primary_entity.lower() in all_text:
            return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.REAL_SUBJECT

        return SourceTier.TIER_5_CLEAN_WEB_ARCHIVE, SourceContentClass.REAL_EVENT

    def score_candidate(
        self,
        candidate: VisualCandidate,
        intent: VisualIntent,
        recent_usage_counts: Optional[Dict[str, int]] = None,
        job_used_urls: Optional[Set[str]] = None,
        near_duplicate_urls: Optional[Set[str]] = None,
        recent_scene_subjects: Optional[List[str]] = None,
        visual_memory: Optional[Any] = None,
        temporal_start: float = 0.0,
        temporal_end: float = 0.0,
        job_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None,
        recent_scene_source_ids: Optional[List[str]] = None,
        current_time: Optional[Any] = None
    ) -> float:
        """
        Computes final deterministic score for candidate under given intent.
        Enforces:
          - Accurate/contextual relevance dominates over generic beauty
          - High-motion action detection and static footage penalties
          - Visual interest / dynamism preference
          - Anti-repetition penalties across consecutive scenes and past jobs
          - Video > Photo motion preference
          - Strict penalties for duplicate, rights risk, and generic stock overuse
          - Step 5: Visual memory evaluation and cross-job duplicate prevention
          - Step 8D: 6-Tier Retrieval Hierarchy and Source Content Classification
        """
        # Hard era and context compatibility check
        is_compat, reason = self.evaluate_era_and_context_compatibility(candidate, intent)
        if not is_compat:
            candidate.raw_score = 0.0
            candidate.final_score = 0.0
            candidate.rejection_reason = reason
            return 0.0

        # Classify candidate source tier & content class if not already populated
        if not candidate.source_tier or not candidate.source_content_class:
            tier, s_class = self.classify_source_content(candidate, intent)
            candidate.source_tier = candidate.source_tier or tier
            candidate.source_content_class = candidate.source_content_class or s_class
            if candidate.provenance:
                candidate.provenance.source_tier = candidate.provenance.source_tier or tier
                candidate.provenance.source_content_class = candidate.provenance.source_content_class or s_class

        # HARD REJECTION FOR PROHIBITED SOURCE CONTENT CLASSES
        prohibited_classes = {
            SourceContentClass.EXPLAINER,
            SourceContentClass.TALKING_HEAD,
            SourceContentClass.PODCAST,
            SourceContentClass.LECTURE,
            SourceContentClass.REACTION,
            SourceContentClass.FLAT_GRAPHIC,
            SourceContentClass.STATIC_IMAGE,
            SourceContentClass.TITLE_CARD,
            SourceContentClass.SOURCE_BRANDING
        }
        if candidate.source_content_class in prohibited_classes:
            candidate.raw_score = 0.0
            candidate.final_score = 0.0
            candidate.rejection_reason = f"Prohibited source content class: {candidate.source_content_class.value}"
            return 0.0

        # Hard Prohibited Graphic / Diagram / Static Rejection
        cand_text_all = f"{candidate.title} {candidate.description} {' '.join(getattr(candidate, 'event_tags', []) or [])} {' '.join(getattr(candidate, 'entity_tags', []) or [])}".lower()
        for gm in self.PROHIBITED_GRAPHIC_MARKERS:
            if re.search(rf"\b{re.escape(gm)}\b", cand_text_all):
                candidate.raw_score = 0.0
                candidate.final_score = 0.0
                candidate.rejection_reason = f"Prohibited static/graphic/diagrammatic marker detected: '{gm}'"
                return 0.0

        job_used = job_used_urls or set()
        near_dups = near_duplicate_urls or set()
        recent_counts = recent_usage_counts or {}

        # 1. Base Multi-Factor Scores
        rel_score = self.evaluate_semantic_relevance(candidate, intent)
        entity_score = self.evaluate_entity_match(candidate, intent)
        event_score = self.evaluate_event_match(candidate, intent)
        action_score = self.evaluate_action_match(candidate, intent)
        loc_score = self.evaluate_location_match(candidate, intent)
        date_score = self.evaluate_date_match(candidate, intent)
        motion_score = self.compute_motion_score(candidate)
        interest_score = self.evaluate_visual_interest(candidate, intent)

        # Resolution / Visual Quality
        quality_score = 0.50
        if candidate.width >= 1080 and candidate.height >= 1920:
            quality_score = 1.0  # 1080p vertical
        elif candidate.width >= 1920 and candidate.height >= 1080:
            quality_score = 0.90  # 1080p landscape (crops cleanly)
        elif candidate.width >= 720 and candidate.height >= 1280:
            quality_score = 0.85  # 720p vertical
        elif candidate.width >= 1280 and candidate.height >= 720:
            quality_score = 0.75  # 720p landscape
        elif candidate.width < 720 or candidate.height < 720:
            quality_score = 0.20  # Sub-720p

        # Physical sharpness modulation from cleanliness filter
        cand_sharpness = float(
            candidate.metadata.get("sharpness_score", 0.0) or
            getattr(candidate.provenance, "provenance_metadata", {}).get("sharpness_score", 0.0) or
            0.0
        )
        if cand_sharpness > 0:
            if cand_sharpness >= 180.0:
                quality_score = min(1.0, quality_score + 0.10)
            elif 120.0 <= cand_sharpness < 180.0:
                quality_score = max(0.40, quality_score - 0.15)

        source_quality = 1.0 if candidate.source_class in ("SOURCE_A", "SOURCE_C", "SOURCE_A_CINEMATIC", "SOURCE_B_YOUTUBE") else 0.80
        editorial_fit = 0.95 if (candidate.content_type == intent.required_visual_type) else 0.65
        rights_confidence = getattr(candidate.provenance, "confidence_score", 0.90) if candidate.provenance else 0.50
        prov_completeness = self.evaluate_provenance_completeness(candidate)

        # 1. Semantic Hierarchy Gating (Problem 2 & Problem 9)
        # Level 1: EXACT SUBJECT / EVENT (1.00)
        # Level 2: DIRECT PHYSICAL CONSEQUENCE (0.85)
        # Level 3: AUTHENTIC ARCHIVAL CONTEXT (0.70)
        # Level 4: CLOSE CONTEXTUAL FOOTAGE (0.45)
        # Level 5: GENERIC FOOTAGE (0.15)
        has_specific_entity = bool(intent.primary_entity and intent.primary_entity.lower() not in self.GENERIC_ENTITY_TOKENS)
        has_specific_event = bool(intent.event and intent.event.lower() not in self.GENERIC_ENTITY_TOKENS)

        consequence_markers = [
            "aftermath", "wreckage", "ruin", "crater", "damage", "rescue", "casualties",
            "dead", "bodies", "remains", "debris", "collapsed", "destruction", "survivors", "fatal"
        ]
        cand_text_all = f"{candidate.title} {candidate.description} {' '.join(getattr(candidate, 'entity_tags', []) or [])}".lower()
        is_direct_consequence = any(re.search(rf"\b{re.escape(cm)}\b", cand_text_all) for cm in consequence_markers)

        if (has_specific_entity and entity_score >= 0.70) or (has_specific_event and event_score >= 0.65):
            semantic_hierarchy_level = 1.00  # Level 1: EXACT SUBJECT / EVENT
        elif candidate.source_tier in (SourceTier.TIER_1_DIRECT_INSTITUTIONAL, SourceTier.TIER_4_ORIGINAL_PROCEDURAL_3D) or candidate.source_name in ("nasa_svs", "procedural_3d"):
            semantic_hierarchy_level = 0.85  # Level 2: DIRECT INSTITUTIONAL / PROCEDURAL 3D EVIDENCE
        elif is_direct_consequence and (entity_score >= 0.35 or event_score >= 0.35):
            semantic_hierarchy_level = 0.85  # Level 2: DIRECT PHYSICAL CONSEQUENCE
        elif candidate.source_tier in (SourceTier.TIER_2_ARCHIVAL_VIDEO, SourceTier.TIER_3_WHITELISTED_DOCUDRAMA) or candidate.source_name in ("wikimedia_commons", "internet_archive", "official", "youtube") or candidate.content_type == VisualContentType.ARCHIVAL_VIDEO:
            semantic_hierarchy_level = 0.70  # Level 3: AUTHENTIC ARCHIVAL / DOCUDRAMA CONTEXT
        elif action_score >= 0.65 or loc_score >= 0.70 or rel_score >= 0.30:
            semantic_hierarchy_level = 0.45  # Level 4: CLOSE CONTEXTUAL FOOTAGE
        elif candidate.source_tier == SourceTier.TIER_5_SUPPORTING_STOCK or candidate.source_name in ("pexels", "pixabay"):
            semantic_hierarchy_level = 0.40  # Level 5: SUPPORTING MACRO STOCK
        else:
            semantic_hierarchy_level = 0.15  # Level 6: GENERIC UNMATCHED FOOTAGE

        # Usable Quality Evaluation (Problem 3)
        sharp_factor = 0.50
        if cand_sharpness >= 180.0:
            sharp_factor = 1.00
        elif 120.0 <= cand_sharpness < 180.0:
            sharp_factor = 0.75
        elif 80.0 <= cand_sharpness < 120.0:
            sharp_factor = 0.40
        else:
            sharp_factor = 0.15

        usable_quality = round(
            0.35 * quality_score +
            0.35 * sharp_factor +
            0.30 * motion_score,
            3
        )

        # ARCHIVAL AUTHENTICITY EXCEPTION:
        # Authentic historical/archival footage from public records, NASA SVS, or Internet Archive
        # inherently exhibits vintage grain, sepia/BW tones, or pre-digital resolution.
        # Ensure authentic assets are not falsely rejected for sharpness or vintage artifacting.
        is_archival_exempt = (
            getattr(candidate, "archival_authenticity_exception", False) or
            (candidate.provenance and getattr(candidate.provenance, "archival_authenticity_exception", False)) or
            candidate.source_tier in (SourceTier.TIER_2_ARCHIVAL_VIDEO, SourceTier.TIER_1_DIRECT_INSTITUTIONAL) or
            candidate.source_name in ("internet_archive", "archive", "nasa_svs")
        )
        if is_archival_exempt:
            usable_quality = max(usable_quality, 0.85)
            candidate.metadata["archival_authenticity_exception"] = True

        # Creator / Explainer / Talking Head Penalties (Problem 1 & 9)
        cand_title_lower = str(getattr(candidate, "title", "") or "").lower()
        explainer_markers = [
            "explained", "explaining", "explainer", "reaction", "reacts", "top 10", "top 5",
            "podcast", "interview", "commentary", "review", "vlog", "crash course",
            "simple history", "oversimplified", "ted-ed", "infographics show"
        ]
        explainer_penalty = 0.0
        if any(re.search(rf"\b{re.escape(em)}\b", cand_title_lower) for em in explainer_markers):
            explainer_penalty = 0.35
            candidate.metadata["explainer_video_penalty"] = 0.35

        # Base Relevance Calculation
        base_relevance = max(semantic_hierarchy_level, round(0.40 * rel_score + 0.35 * entity_score + 0.25 * event_score, 3))
        base_relevance = max(0.05, base_relevance - explainer_penalty)

        # Multiplicative Gating: FINAL SCORE = RELEVANCE × USABLE QUALITY
        composite = round(base_relevance * usable_quality, 4)

        # Generic footage hard ceiling: generic filler can never score above 0.18
        if semantic_hierarchy_level <= 0.20:
            composite = min(composite, 0.18)

        # 2. Penalties
        # Single-short duplicate: absolute disqualify
        if candidate.source_url in job_used:
            composite -= 1.00

        # Perceptual / Near-duplicate penalty
        if candidate.source_url in near_dups:
            composite -= 0.40

        # Cross-job recent repetition penalty (recent-use decay)
        prior_uses = recent_counts.get(candidate.source_url, 0)
        if prior_uses > 0:
            composite -= min(0.50, prior_uses * 0.20)

        # Anti-Repetition: Bounded consecutive-scene subject repetition penalty
        if recent_scene_subjects:
            last_subj = str(recent_scene_subjects[-1]).lower().strip()
            cand_text_lower = f"{candidate.title} {candidate.description} {' '.join(candidate.entity_tags)}".lower()
            if len(last_subj) > 3 and re.search(rf"\b{re.escape(last_subj)}\b", cand_text_lower):
                composite -= 0.20

        # Rights risk penalty
        if candidate.rights_status == RightsStatus.RIGHTS_UNCERTAIN:
            composite -= 0.40

        # Step 8G: Tier 5 supporting stock exception for literal physical macro nouns
        is_tier_5_macro_noun = (
            candidate.source_tier == SourceTier.TIER_5_SUPPORTING_STOCK and
            any(noun in f"{candidate.title} {intent.narration_text} {intent.primary_entity}".lower() for noun in [
                "clock", "clocks", "hourglass", "microscope", "centrifuge", "flask", "scale", "pendulum", "compass"
            ])
        )

        # Generic stock overuse penalty when specific entity/event is requested
        if (intent.primary_entity or intent.event) and candidate.content_type in (
            VisualContentType.GENERIC_STOCK_VIDEO, VisualContentType.GENERIC_STOCK_IMAGE
        ) and not is_tier_5_macro_noun:
            composite -= 0.25

        # Generic footage penalty
        if not is_tier_5_macro_noun:
            composite -= self.evaluate_generic_footage_penalty(candidate, intent)

        # Zero semantic match penalty: if candidate has zero semantic matches to the scene,
        # technical beauty/cinematic origin must not artificially qualify it.
        has_entity_match = (entity_score >= 0.70 and bool(intent.primary_entity)) or is_tier_5_macro_noun
        has_event_match = (event_score > 0.40 and bool(intent.event))
        has_action_match = (action_score >= 0.75 and bool(intent.action or getattr(intent, "visual_action", None)))
        has_rel_match = (rel_score >= 0.15)
        has_loc_match = (loc_score >= 0.75 and bool(intent.location))
        num_semantic_matches = sum([has_entity_match, has_event_match, has_action_match, has_rel_match, has_loc_match])
        if num_semantic_matches == 0:
            composite -= 0.30

        # Specific Historical/Event Entity Hard Gate:
        # If the narrative beat explicitly targets a specific entity or historical event,
        # footage that does NOT depict the entity/event cannot qualify on motion/quality alone.
        # EXCEPTION: Action/setting beats or Tier 5 macro noun supporting objects.
        has_specific_entity = bool(intent.primary_entity and intent.primary_entity.lower() not in self.GENERIC_ENTITY_TOKENS)
        has_specific_event = bool(intent.event and intent.event.lower() not in self.GENERIC_ENTITY_TOKENS)
        is_action_depiction = bool(intent.action or getattr(intent, "visual_action", None) or action_score >= 0.25)
        if (has_specific_entity or has_specific_event) and not is_action_depiction and not is_tier_5_macro_noun:
            if entity_score < 0.50 and event_score < 0.50:
                composite -= 0.35
                # Cap the score below the threshold so it cannot qualify as primary
                composite = min(composite, 0.35)
                candidate.metadata["entity_disqualification"] = "Candidate lacks verified match to requested entity/event"
        elif candidate.source_name in ("youtube", "wikimedia_commons", "internet_archive", "official"):
            composite += 0.10  # Authentic evidence bonus
            candidate.metadata["evidence_specific"] = True

        # Step 8G: 5-Tier Retrieval Hierarchy weighting derived from reference forensics
        tier_bonuses = {
            SourceTier.TIER_1_DIRECT_INSTITUTIONAL: 0.20,
            SourceTier.TIER_2_ARCHIVAL_VIDEO: 0.15,
            SourceTier.TIER_3_WHITELISTED_DOCUDRAMA: 0.15,
            SourceTier.TIER_4_ORIGINAL_PROCEDURAL_3D: 0.10,
            SourceTier.TIER_5_SUPPORTING_STOCK: -0.20,
            # Backward compatibility aliases
            SourceTier.TIER_1_CINEMATIC_DOCUDRAMA: 0.15,
            SourceTier.TIER_2_INSTITUTIONAL_ARCHIVE: 0.20,
            SourceTier.TIER_3_MUSEUM_ACADEMIC: 0.10,
            SourceTier.TIER_4_ORIGINAL_VERIFIED: 0.20,
            SourceTier.TIER_5_CLEAN_WEB_ARCHIVE: 0.15,
            SourceTier.TIER_6_STOCK_FALLBACK: -0.20,
        }
        tier_bonus = tier_bonuses.get(candidate.source_tier, 0.0)
        if is_tier_5_macro_noun:
            tier_bonus = 0.0  # Macro noun is allowed as valid supporting physical visual without negative penalty
        composite += tier_bonus
        candidate.metadata["source_tier"] = candidate.source_tier.value if candidate.source_tier else "UNKNOWN"
        candidate.metadata["source_content_class"] = candidate.source_content_class.value if candidate.source_content_class else "UNKNOWN"
        candidate.metadata["tier_bonus"] = tier_bonus

        # Watermark and Timecode Penalties
        if candidate.metadata.get("has_watermark"):
            composite -= 0.30
            candidate.metadata["watermark_penalty"] = 0.30
        if candidate.metadata.get("has_timecode"):
            composite -= 0.25
            candidate.metadata["timecode_penalty"] = 0.25

        # Misleading context penalty (e.g. meme used during serious factual claim)
        if intent.emotional_tone in ("SERIOUS", "TRAGIC") and candidate.content_type == VisualContentType.MEME_REACTION:
            composite -= 0.50

        # Anachronism Hard Gate for Historical Topics:
        # Strictly reject modern civic construction, local TV news, home videos, webcams, and podcasts
        is_historical_intent = (
            getattr(intent, "historical_classification", "") == "HISTORICAL" or
            any(k in str(getattr(intent, "date_context", "")).lower() for k in ["18", "19", "century", "ancient", "victorian"])
        )
        if is_historical_intent:
            cand_title_lower = str(getattr(candidate, "title", "") or "").lower()
            cand_uploader_lower = str(getattr(candidate, "creator", "") or "").lower()
            anachronistic_markers = [
                "construction", "demolition", "excavator", "bulldozer", "preservationists",
                "building permit", "police", "highway", "traffic", "home video", "vhs", "camcorder",
                "webcam", "zoom", "interview", "podcast", "vlog", "haul", "reaction", "unboxing",
                "timelapse city", "modern day"
            ]
            modern_affiliates = [
                "cbs", "nbc", "abc news", "fox news", "local news", "action news",
                "eyewitness news", "wtae", "kdka", "kron", "news 12"
            ]
            if any(re.search(rf"\b{re.escape(m)}\b", cand_title_lower) for m in anachronistic_markers):
                composite -= 0.50
                composite = min(composite, 0.20)
                candidate.metadata["anachronism_disqualification"] = "Candidate contains modern civic/commercial/anachronistic content"
            elif any(re.search(rf"\b{re.escape(aff)}\b", cand_uploader_lower) for aff in modern_affiliates):
                composite -= 0.50
                composite = min(composite, 0.20)
                candidate.metadata["anachronism_disqualification"] = "Candidate is from modern local news affiliate"

        # Physical Cleanliness: Monochrome Saturation Whiplash Penalty
        # If candidate is black-and-white / monochrome (HSV saturation < 18.0):
        # Allow without penalty ONLY if intent is an authentic historical/archival document/treaty.
        # Otherwise apply -0.25 penalty so clean color footage wins whenever available.
        is_monochrome = bool(
            candidate.metadata.get("is_monochrome", False) or
            getattr(candidate.provenance, "provenance_metadata", {}).get("is_monochrome", False)
        )
        if is_monochrome:
            beat_text = (str(getattr(intent, "narration_text", "")) + " " + str(getattr(intent, "claim_discussed", "") or "")).lower()
            is_explicit_archival_beat = (
                getattr(intent, "preferred_source", "") in ("archival", "document") or
                getattr(intent, "preferred_visual_type", None) == VisualContentType.ARCHIVAL_VIDEO or
                any(k in beat_text for k in ["document", "treaty", "treaties", "signature", "manuscript", "telegram", "archive", "newspaper clipping"])
            )
            is_modern_beat = (getattr(intent, "historical_classification", "") == "MODERN")
            if is_modern_beat or not is_explicit_archival_beat:
                composite -= 0.25
                candidate.metadata["monochrome_penalty"] = 0.25

        # Step 5: Visual Memory & Cross-Job Duplicate Prevention
        if visual_memory is not None:
            mem_eval = visual_memory.evaluate_candidate(
                candidate=candidate,
                temporal_start=temporal_start,
                temporal_end=temporal_end,
                job_id=job_id,
                recent_scene_urls=recent_scene_urls or list(job_used),
                recent_scene_source_ids=recent_scene_source_ids,
                current_time=current_time
            )
            candidate.metadata["memory_evaluation"] = mem_eval.to_dict()
            if mem_eval.is_hard_duplicate:
                composite -= 1.00
                candidate.metadata["is_hard_duplicate"] = True
                candidate.metadata["duplicate_reason"] = mem_eval.duplicate_reason
            else:
                composite -= mem_eval.penalty
                # Mild source diversity bonus if qualified and unused
                div_bonus = visual_memory.calculate_source_diversity_bonus(candidate)
                composite += div_bonus
                candidate.metadata["diversity_bonus"] = div_bonus

        candidate.raw_score = round(composite, 4)
        candidate.final_score = candidate.raw_score
        candidate.metadata["subscores"] = {
            "relevance": rel_score,
            "entity": entity_score,
            "event": event_score,
            "action": action_score,
            "location": loc_score,
            "motion": motion_score
        }
        return candidate.final_score

    def rank_candidates(
        self,
        candidates: List[VisualCandidate],
        intent: VisualIntent,
        recent_usage_counts: Optional[Dict[str, int]] = None,
        job_used_urls: Optional[Set[str]] = None,
        near_duplicate_urls: Optional[Set[str]] = None,
        recent_scene_subjects: Optional[List[str]] = None,
        visual_memory: Optional[Any] = None,
        temporal_start: float = 0.0,
        temporal_end: float = 0.0,
        job_id: Optional[str] = None,
        recent_scene_urls: Optional[List[str]] = None,
        recent_scene_source_ids: Optional[List[str]] = None,
        current_time: Optional[Any] = None
    ) -> List[VisualCandidate]:
        """
        Ranks candidates according to the Step-2 Two-Stage Qualification Policy:
          - Stage 1: Candidate must pass MIN_SEMANTIC_RELEVANCE_THRESHOLD (0.40).
          - Qualified non-stock (Tier 1) beats qualified stock (Tier 2).
          - Irrelevant non-stock (Tier 3) does NOT beat qualified stock (Tier 2).
          - Multiple qualified non-stock candidates are sorted by highest semantic relevance score.
          - Step 5: Incorporates visual memory penalties and source diversity while preserving
            RELEVANCE > VARIETY invariant.
        """
        for c in candidates:
            self.score_candidate(
                c,
                intent,
                recent_usage_counts=recent_usage_counts,
                job_used_urls=job_used_urls,
                near_duplicate_urls=near_duplicate_urls,
                recent_scene_subjects=recent_scene_subjects,
                visual_memory=visual_memory,
                temporal_start=temporal_start,
                temporal_end=temporal_end,
                job_id=job_id,
                recent_scene_urls=recent_scene_urls,
                recent_scene_source_ids=recent_scene_source_ids,
                current_time=current_time
            )

        def _sort_key(c: VisualCandidate):
            from .models import SourceType
            # Two-Stage Qualification Policy
            is_qualified = (c.final_score >= self.MIN_SEMANTIC_RELEVANCE_THRESHOLD and c.raw_score > 0.0)

            if is_qualified:
                if getattr(c, "source_type", None) == SourceType.STOCK or c.source_name in ("pexels", "pixabay"):
                    tier = 2  # Qualified stock video fallback
                else:
                    tier = 1  # Qualified non-stock (MOVIE, INTERNET_REAL, ARCHIVAL)
            else:
                tier = 3      # Unqualified (below semantic relevance threshold)

            return (tier, -c.final_score)

        ranked = sorted(candidates, key=_sort_key)
        return ranked
