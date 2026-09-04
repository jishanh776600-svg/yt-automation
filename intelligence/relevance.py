"""
Current-Affairs Relevance & Category Taxonomy Engine.
Scores geopolitical, economic, diplomatic, and international conflict relevance
for English-speaking Western audiences and categorizes stories into CurrentAffairsCategory.
"""
import re
import logging
from typing import Tuple, Set, Dict, Any
from config.constants import CurrentAffairsCategory
from intelligence.models import EventCluster

logger = logging.getLogger(__name__)

# Primary domain keyword mappings to category taxonomies
CATEGORY_THEME_RULES = [
    (
        CurrentAffairsCategory.GLOBAL_CONFLICT.value,
        {"strike", "attack", "bombing", "missile", "drone", "invasion", "troops", "casualty", "combat", "offensive", "warfare", "ceasefire", "airspace", "retaliation"}
    ),
    (
        CurrentAffairsCategory.DIPLOMACY.value,
        {"summit", "treaty", "envoy", "ambassador", "negotiation", "bilateral", "pact", "accord", "dialogue", "peace talks", "normalization"}
    ),
    (
        CurrentAffairsCategory.GLOBAL_ECONOMY.value,
        {"tariff", "trade", "embargo", "inflation", "debt", "interest rate", "currency", "export", "import", "supply chain", "energy", "pipeline", "oil", "gas", "sanctions", "deficit"}
    ),
    (
        CurrentAffairsCategory.SECURITY.value,
        {"hostage", "cyberattack", "espionage", "intelligence", "border", "refugee", "blockade", "evacuation", "emergency", "defense", "military"}
    ),
    (
        CurrentAffairsCategory.US_POLITICS.value,
        {"congress", "white house", "senate", "supreme court", "democrat", "republican", "biden", "trump", "pentagon", "state department"}
    ),
    (
        CurrentAffairsCategory.EUROPE_POLITICS.value,
        {"european union", "eu", "brussels", "bundestag", "downing street", "elysee", "parliament", "chancellor", "macron", "starmer", "scholz"}
    ),
    (
        CurrentAffairsCategory.WORLD_POLITICS.value,
        {"election", "vote", "resign", "impeach", "cabinet", "protest", "dissolve", "coup", "prime minister", "president"}
    )
]

# High-priority entities that elevate relevance for Western geopolitical analysis
HIGH_IMPACT_ENTITIES = {
    "united states", "us", "usa", "america", "united kingdom", "uk", "britain",
    "nato", "european union", "eu", "russia", "china", "ukraine", "taiwan",
    "israel", "iran", "pentagon", "white house", "kremlin", "united nations",
    "g7", "brics", "opec", "federal reserve", "imf"
}

# Low-relevance noise terms that indicate domestic municipal news, lifestyle, sports, or gossip
LOW_RELEVANCE_NOISE = {
    "celebrity", "hollywood", "actor", "actress", "box office", "nfl", "nba",
    "premier league", "football", "soccer", "tennis", "recipe", "horoscope",
    "lottery", "weather forecast", "traffic jam", "zoo", "festival"
}


class RelevanceScorer:
    """Evaluates geopolitical relevance and maps stories to CurrentAffairsCategory."""

    def evaluate_relevance(self, cluster: EventCluster) -> Tuple[float, str]:
        """
        Calculates a deterministic relevance score (0.0 to 100.0) and determines
        the best-matching CurrentAffairsCategory.
        """
        combined_text = f"{cluster.canonical_title} {cluster.canonical_summary}".lower()
        all_tokens = cluster.entities.union(cluster.action_tokens).union(cluster.countries)

        # 1. Check for immediate low-relevance exclusion
        for noise in LOW_RELEVANCE_NOISE:
            if re.search(r"\b" + re.escape(noise) + r"\b", combined_text):
                cluster.relevance_score = 15.0
                cluster.primary_category = CurrentAffairsCategory.MAJOR_WORLD_EVENT.value
                return 15.0, cluster.primary_category

        base_relevance = 50.0

        # 2. Entity Significance Boost (up to +25 pts)
        shared_high_impact = cluster.entities.intersection(HIGH_IMPACT_ENTITIES)
        if len(shared_high_impact) >= 3:
            base_relevance += 25.0
        elif len(shared_high_impact) >= 2:
            base_relevance += 18.0
        elif len(shared_high_impact) >= 1:
            base_relevance += 10.0

        # 3. Action Significance Boost (up to +25 pts)
        if len(cluster.action_tokens) >= 3:
            base_relevance += 20.0
        elif len(cluster.action_tokens) >= 1:
            base_relevance += 12.0

        # 4. Determine Category by Matching Themes
        matched_category = CurrentAffairsCategory.GEOPOLITICS.value
        highest_match_count = 0

        for cat_name, theme_words in CATEGORY_THEME_RULES:
            matches = len(all_tokens.intersection(theme_words))
            # Also check text containment
            for tw in theme_words:
                if f" {tw} " in f" {combined_text} ":
                    matches += 1

            if matches > highest_match_count:
                highest_match_count = matches
                matched_category = cat_name

        # Default to GEOPOLITICS if global actors present, otherwise MAJOR_WORLD_EVENT
        if highest_match_count == 0:
            if cluster.countries or cluster.entities.intersection(HIGH_IMPACT_ENTITIES):
                matched_category = CurrentAffairsCategory.GEOPOLITICS.value
            else:
                matched_category = CurrentAffairsCategory.MAJOR_WORLD_EVENT.value

        final_score = round(min(100.0, max(0.0, base_relevance)), 2)
        cluster.relevance_score = final_score
        cluster.primary_category = matched_category
        return final_score, matched_category
