"""
Current-Affairs Relevance & Category Taxonomy Engine.
Scores geopolitical, economic, diplomatic, and international conflict relevance
for English-speaking Western audiences and categorizes stories into CurrentAffairsCategory.
"""
import re
import logging
from typing import Tuple, Set, Dict, Any, Optional
from config.constants import CurrentAffairsCategory
from intelligence.models import EventCluster
from core.discovery_profile import (
    DEFAULT_CATEGORY_THEME_RULES,
    DEFAULT_HIGH_IMPACT_ENTITIES,
    DEFAULT_LOW_RELEVANCE_NOISE,
    DiscoveryProfile,
    get_active_discovery_profile
)

logger = logging.getLogger(__name__)

# Primary domain keyword mappings to category taxonomies (backwards compatible defaults)
CATEGORY_THEME_RULES = DEFAULT_CATEGORY_THEME_RULES
HIGH_IMPACT_ENTITIES = DEFAULT_HIGH_IMPACT_ENTITIES
LOW_RELEVANCE_NOISE = DEFAULT_LOW_RELEVANCE_NOISE


class RelevanceScorer:
    """Evaluates niche relevance and maps stories to appropriate category taxonomy."""

    def __init__(self, profile: Optional[DiscoveryProfile] = None):
        self.profile = profile or get_active_discovery_profile()

    def evaluate_relevance(self, cluster: EventCluster) -> Tuple[float, str]:
        """
        Calculates a deterministic relevance score (0.0 to 100.0) and determines
        the best-matching category using the active DiscoveryProfile.
        """
        combined_text = f"{cluster.canonical_title} {cluster.canonical_summary}".lower()
        all_tokens = cluster.entities.union(cluster.action_tokens).union(cluster.countries)

        theme_rules = self.profile.category_theme_rules if self.profile else CATEGORY_THEME_RULES
        high_impact = self.profile.high_impact_entities if self.profile else HIGH_IMPACT_ENTITIES
        low_noise = self.profile.low_relevance_noise if self.profile else LOW_RELEVANCE_NOISE
        default_cat = self.profile.default_category if self.profile else CurrentAffairsCategory.GEOPOLITICS.value
        fallback_cat = self.profile.fallback_category if self.profile else CurrentAffairsCategory.MAJOR_WORLD_EVENT.value

        # 1. Check for immediate low-relevance exclusion
        for noise in low_noise:
            if re.search(r"\b" + re.escape(noise) + r"\b", combined_text):
                cluster.relevance_score = 15.0
                cluster.primary_category = fallback_cat
                return 15.0, cluster.primary_category

        base_relevance = 50.0

        # 2. Entity Significance Boost (up to +25 pts)
        shared_high_impact = cluster.entities.intersection(high_impact)
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
        matched_category = default_cat
        highest_match_count = 0

        for cat_name, theme_words in theme_rules:
            matches = len(all_tokens.intersection(theme_words))
            # Also check text containment
            for tw in theme_words:
                if f" {tw} " in f" {combined_text} ":
                    matches += 1

            if matches > highest_match_count:
                highest_match_count = matches
                matched_category = cat_name

        # Default to default_cat if global/key actors present, otherwise fallback_cat
        if highest_match_count == 0:
            if cluster.countries or cluster.entities.intersection(high_impact):
                matched_category = default_cat
            else:
                matched_category = fallback_cat

        final_score = round(min(100.0, max(0.0, base_relevance)), 2)
        cluster.relevance_score = final_score
        cluster.primary_category = matched_category
        return final_score, matched_category
