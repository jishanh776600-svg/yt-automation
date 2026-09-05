"""
Candidate Writer & Multi-Source Evidence Gate.
Enforces the strict multi-source consensus invariant (>= 2 independent domains),
evaluates deduplication, and promotes approved EventClusters into SQLite Topic
and SourceRecord records.
"""
import uuid
import logging
from typing import List, Tuple, Optional
from sqlalchemy.orm import Session

from intelligence.models import EventCluster
from intelligence.deduplication import CurrentAffairsDeduplicationEngine
from core.models import Topic, SourceRecord, ClaimRecord
from core.discovery_profile import DiscoveryProfile, get_active_discovery_profile

logger = logging.getLogger(__name__)


class CandidateWriter:
    """Manages evidence gate evaluation and database persistence for current-affairs topics."""

    def __init__(
        self,
        min_independent_domains: int = 2,
        min_opportunity_score: float = 40.0,
        dedup_engine: Optional[CurrentAffairsDeduplicationEngine] = None,
        profile: Optional[DiscoveryProfile] = None
    ):
        self.profile = profile or get_active_discovery_profile()
        self.min_domains = min_independent_domains
        self.min_score = min_opportunity_score
        self.dedup_engine = dedup_engine or CurrentAffairsDeduplicationEngine(profile=self.profile)

    def evaluate_multi_source_evidence(self, cluster: EventCluster) -> Tuple[bool, str]:
        """
        Enforces the multi-source evidence gate:
        Requires >= 2 independent publisher domains before promotion.
        """
        domain_count = len(cluster.source_domains)
        if domain_count >= self.min_domains:
            cluster.has_multi_source_consensus = True
            return True, f"CONSENSUS_VERIFIED_{domain_count}_DOMAINS"

        cluster.has_multi_source_consensus = False
        cluster.status = "INSUFFICIENT_EVIDENCE"
        cluster.rejection_reason = f"Only {domain_count} independent domain (minimum {self.min_domains} required)"
        return False, cluster.rejection_reason

    def process_and_persist_candidates(
        self,
        clusters: List[EventCluster],
        db: Session,
        limit: int = 5
    ) -> List[Topic]:
        """
        Filters clusters through:
          1. Multi-source evidence gate (>= 2 independent domains)
          2. Opportunity score threshold (>= min_score)
          3. Current-affairs deduplication gate against SQLite
        Promotes qualifying clusters to Topic(status="APPROVED") + SourceRecords.
        """
        approved_topics: List[Topic] = []

        # Sort clusters by opportunity score descending
        sorted_clusters = sorted(clusters, key=lambda c: c.opportunity_score, reverse=True)

        for cluster in sorted_clusters:
            if len(approved_topics) >= limit:
                break

            # 1. Multi-Source Evidence Gate
            has_evidence, evidence_reason = self.evaluate_multi_source_evidence(cluster)
            if not has_evidence:
                logger.info(
                    f"[EVIDENCE_GATE] Candidate '{cluster.canonical_title[:45]}' rejected: {evidence_reason}"
                )
                continue

            # 2. Opportunity Score Threshold
            if cluster.opportunity_score < self.min_score:
                cluster.status = "REJECTED"
                cluster.rejection_reason = f"Opportunity score {cluster.opportunity_score:.1f} below threshold {self.min_score}"
                logger.info(
                    f"[SCORE_GATE] Candidate '{cluster.canonical_title[:45]}' rejected: {cluster.rejection_reason}"
                )
                continue

            # 3. Deduplication Gate
            is_dup, matched_title, dedup_reason = self.dedup_engine.is_cluster_duplicate(cluster, db)
            if is_dup:
                cluster.status = "REJECTED"
                cluster.rejection_reason = f"Duplicate of '{matched_title}' ({dedup_reason})"
                continue

            # 4. Promote to APPROVED Topic
            topic_id = f"top_{uuid.uuid4().hex[:12]}"
            topic = Topic(
                id=topic_id,
                title=cluster.canonical_title,
                summary=cluster.canonical_summary,
                category=cluster.primary_category,
                score=cluster.opportunity_score,
                status="APPROVED"
            )
            db.add(topic)

            # 5. Persist SourceRecords for all unique sources in the cluster
            seen_source_urls = set()
            for art in cluster.articles:
                if art.url and art.url not in seen_source_urls:
                    seen_source_urls.add(art.url)
                    source_rec = SourceRecord(
                        topic_id=topic_id,
                        source_name=art.source_name,
                        source_url=art.url,
                        source_type="wire_report",
                        confidence=0.95
                    )
                    db.add(source_rec)

            cluster.status = "APPROVED"
            approved_topics.append(topic)
            logger.info(
                f"[CANDIDATE_WRITER] Approved and persisted Topic '{topic.title}' "
                f"(Category: {topic.category}, Score: {topic.score:.1f}, Sources: {len(seen_source_urls)})"
            )

        if approved_topics:
            db.commit()
            logger.info(f"[CANDIDATE_WRITER] Successfully committed {len(approved_topics)} approved current-affairs topics.")

        return approved_topics
