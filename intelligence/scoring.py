"""
Opportunity Scoring Engine.
Computes deterministic opportunity scores for EventClusters
by synthesizing Freshness, Geopolitical Relevance, Multi-Source Breadth,
Narrative Tension, and Coverage Velocity.
"""
import logging
from typing import Dict, Any
from intelligence.models import EventCluster

logger = logging.getLogger(__name__)

# Narrative tension markers (conflict, surprise, high stakes, escalation)
NARRATIVE_TENSION_KEYWORDS = {
    "warns", "crisis", "threat", "escalates", "showdown", "ultimatum", "collapse",
    "deadlock", "emergency", "historic", "unprecedented", "retaliates", "clashes",
    "critical", "fallout", "standoff", "breaking point", "tensions rise"
}


class OpportunityScorer:
    """Calculates composite opportunity scores to prioritize high-impact stories."""

    def __init__(
        self,
        weight_freshness: float = 0.30,
        weight_relevance: float = 0.25,
        weight_breadth: float = 0.20,
        weight_tension: float = 0.15,
        weight_velocity: float = 0.10
    ):
        self.w_fresh = weight_freshness
        self.w_rel = weight_relevance
        self.w_breadth = weight_breadth
        self.w_tension = weight_tension
        self.w_velocity = weight_velocity

    def compute_source_breadth_score(self, domain_count: int) -> float:
        """
        Calibrated score based on independent publisher domain breadth:
          1 domain:  30.0 (Uncorroborated single source)
          2 domains: 70.0 (Corroborated consensus baseline)
          3 domains: 85.0 (Strong consensus)
          4+ domains: 100.0 (Major global event consensus)
        """
        if domain_count <= 1:
            return 30.0
        elif domain_count == 2:
            return 70.0
        elif domain_count == 3:
            return 85.0
        else:
            return 100.0

    def compute_narrative_tension_score(self, cluster: EventCluster) -> float:
        """Evaluates high-stakes narrative tension and dramatic potential."""
        combined_text = f"{cluster.canonical_title} {cluster.canonical_summary}".lower()
        tension_matches = sum(1 for kw in NARRATIVE_TENSION_KEYWORDS if kw in combined_text)
        action_count = len(cluster.action_tokens)

        score = 40.0 + (tension_matches * 15.0) + (action_count * 5.0)
        return min(100.0, max(20.0, score))

    def compute_velocity_score(self, cluster: EventCluster) -> float:
        """Computes coverage velocity based on article volume relative to event age."""
        article_count = len(cluster.articles)
        domain_count = len(cluster.source_domains)

        if domain_count >= 3 and article_count >= 4:
            return 95.0
        elif domain_count >= 2 and article_count >= 2:
            return 75.0
        elif article_count >= 2:
            return 60.0
        return 40.0

    def calculate_opportunity_score(self, cluster: EventCluster) -> float:
        """
        Computes composite opportunity score:
          Score = (w_fresh * Freshness) + (w_rel * Relevance) +
                  (w_breadth * Breadth) + (w_tension * Tension) +
                  (w_velocity * Velocity)
        """
        fresh_score = cluster.freshness_score or 50.0
        rel_score = cluster.relevance_score or 50.0
        breadth_score = self.compute_source_breadth_score(len(cluster.source_domains))
        tension_score = self.compute_narrative_tension_score(cluster)
        velocity_score = self.compute_velocity_score(cluster)

        composite = (
            (self.w_fresh * fresh_score) +
            (self.w_rel * rel_score) +
            (self.w_breadth * breadth_score) +
            (self.w_tension * tension_score) +
            (self.w_velocity * velocity_score)
        )

        final_score = round(min(100.0, max(0.0, composite)), 2)
        cluster.opportunity_score = final_score
        return final_score
