"""
Topic Discovery Engine.
Generates, filters, and scores intriguing American and European historical stories.
Avoids spam, balances categories, and scores via multi-factor retention model.
"""
import os
import uuid
import random
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Set
import wikipediaapi
from sqlalchemy.orm import Session
from config.constants import HistoricalCategory
from config.settings import GEMINI_API_KEY, AI_PROVIDER_AVAILABLE, TEST_MODE
from core.models import Topic, ArticleRecord, Job, UploadRecord, ClaimRecord, SourceRecord
from intelligence.freshness import FreshnessTier

logger = logging.getLogger(__name__)

# Curated seed database of high-retention factual American & European historical events

# Curated seed database of high-retention current geopolitics & world affairs topics
from config.constants import CurrentAffairsCategory

CURATED_GEOPOLITICAL_SEEDS = [
    {
        "title": "Red Sea Maritime Chokepoint Crisis",
        "category": CurrentAffairsCategory.GEOPOLITICS.value,
        "summary": "Commercial shipping through the Bab-el-Mandeb strait faces missile and drone strikes, forcing international naval escort operations across critical global maritime corridors.",
        "curiosity": 9.8, "visual_potential": 9.9, "historical_interest": 9.2, "storytelling": 9.7, "uniqueness": 9.8
    },
    {
        "title": "Baltic Undersea Infrastructure Security",
        "category": CurrentAffairsCategory.SECURITY.value,
        "summary": "NATO naval patrols and maritime reconnaissance aircraft surge surveillance over undersea telecom cables and energy pipelines following suspected infrastructure sabotage.",
        "curiosity": 9.7, "visual_potential": 9.8, "historical_interest": 9.1, "storytelling": 9.6, "uniqueness": 9.7
    },
    {
        "title": "Strait of Hormuz Naval Interceptions",
        "category": CurrentAffairsCategory.GLOBAL_CONFLICT.value,
        "summary": "Fast-attack patrol craft and naval helicopter units intercept commercial oil tankers in the narrow 21-mile international transit corridor.",
        "curiosity": 9.8, "visual_potential": 9.7, "historical_interest": 9.3, "storytelling": 9.7, "uniqueness": 9.8
    },
    {
        "title": "Taiwan Strait Freedom of Navigation Patrols",
        "category": CurrentAffairsCategory.DIPLOMACY.value,
        "summary": "Allied guided-missile destroyers transit the contested international maritime strait as reconnaissance aircraft track carrier strike group maneuvers.",
        "curiosity": 9.9, "visual_potential": 9.8, "historical_interest": 9.4, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "Suwalki Gap NATO Rapid Deployment",
        "category": CurrentAffairsCategory.SECURITY.value,
        "summary": "Allied mechanized divisions reinforce the 65-mile land corridor connecting Poland and Lithuania amid heightened regional border security.",
        "curiosity": 9.6, "visual_potential": 9.5, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.6
    },
    {
        "title": "Black Sea Maritime Corridor Operations",
        "category": CurrentAffairsCategory.GLOBAL_CONFLICT.value,
        "summary": "Unmanned naval surface vessels and coastal defense batteries patrol the western Black Sea export shipping routes.",
        "curiosity": 9.7, "visual_potential": 9.8, "historical_interest": 9.2, "storytelling": 9.6, "uniqueness": 9.7
    },
    {
        "title": "Arctic Maritime Arctic Defense Posture",
        "category": CurrentAffairsCategory.GEOPOLITICS.value,
        "summary": "Sub-zero icebreakers, strategic deepwater ports, and early warning radar stations expand monitoring across northern polar shipping corridors.",
        "curiosity": 9.6, "visual_potential": 9.8, "historical_interest": 9.2, "storytelling": 9.5, "uniqueness": 9.6
    }
]

CURATED_HISTORICAL_SEEDS = [
    {
        "title": "The Great Stink of London (1858)",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In the blazing summer of 1858, the Thames River in London smelled so overpoweringly toxic that Parliament had to soak their curtains in lime chloride and hastily rebuild the entire modern sewage network.",
        "curiosity": 9.5, "visual_potential": 8.5, "historical_interest": 9.0, "storytelling": 9.5, "uniqueness": 9.0
    },
    {
        "title": "The 38-Minute Anglo-Zanzibar War (1896)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "On August 27, 1896, the British Empire engaged in the shortest war in recorded world history, defeating the Sultan's palace in exactly 38 minutes flat.",
        "curiosity": 9.8, "visual_potential": 9.0, "historical_interest": 9.2, "storytelling": 9.7, "uniqueness": 9.8
    },
    {
        "title": "The Strange Town of Baarle-Hertog",
        "category": HistoricalCategory.UNUSUAL_BORDERS.value,
        "summary": "A single town in Europe split between Belgium and the Netherlands has 24 separate exclaves, meaning borders literally cut through living rooms, restaurants, and front doors.",
        "curiosity": 9.4, "visual_potential": 8.8, "historical_interest": 8.5, "storytelling": 9.0, "uniqueness": 9.6
    },
    {
        "title": "The Boston Molasses Flood of 1919",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "A massive 50-foot storage tank burst in Boston, releasing a 35-mile-per-hour tsunami of two million gallons of boiling molasses through city streets.",
        "curiosity": 9.6, "visual_potential": 9.2, "historical_interest": 8.9, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The Pig War of San Juan Island (1859)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In 1859, the United States and Great Britain almost sparked a full-scale armed war in the Pacific Northwest over a single trespassing pig eating potatoes.",
        "curiosity": 9.5, "visual_potential": 8.7, "historical_interest": 9.0, "storytelling": 9.3, "uniqueness": 9.5
    },
    {
        "title": "The Lost Roanoke Colony Mystery",
        "category": HistoricalCategory.LOST_PLACES.value,
        "summary": "In 1590, John White returned to Roanoke Island to discover 115 English settlers had vanished without a trace, leaving only the cryptic word CROATOAN carved on a post.",
        "curiosity": 9.7, "visual_potential": 9.0, "historical_interest": 9.5, "storytelling": 9.6, "uniqueness": 9.4
    },
    {
        "title": "The Dancing Plague of Strasbourg (1518)",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "In July 1518, hundreds of citizens in Strasbourg suddenly began dancing uncontrollably in the public square for weeks on end without rest until collapsing.",
        "curiosity": 9.6, "visual_potential": 8.9, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.8
    },
    {
        "title": "The Erfurt Latrine Disaster of 1184",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In July 1184, King Henry VI held a royal diet at the Church of St. Peter in Erfurt, where the wooden floor collapsed under the weight of dozens of nobles who fell into the latrine cesspool below.",
        "curiosity": 9.8, "visual_potential": 8.5, "historical_interest": 9.2, "storytelling": 9.6, "uniqueness": 9.9
    },
    {
        "title": "The London Beer Flood of 1814",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In October 1814, a massive wooden vat at Meux and Company Brewery ruptured, unleashing a 15-foot wave of 320,000 gallons of fermenting porter beer through the streets of St Giles.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 8.8, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The Defenestration of Prague (1618)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In May 1618, Protestant nobles threw two Catholic imperial regents out of a 70-foot third-story window of Prague Castle, sparking the Thirty Years War.",
        "curiosity": 9.6, "visual_potential": 9.3, "historical_interest": 9.4, "storytelling": 9.5, "uniqueness": 9.6
    },
    {
        "title": "The Halifax Explosion of 1917",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In December 1917, the French cargo ship SS Mont-Blanc, fully loaded with wartime munitions, collided with the Norwegian vessel SS Imo in Halifax Harbour, creating the largest man-made blast before the atomic bomb.",
        "curiosity": 9.7, "visual_potential": 9.5, "historical_interest": 9.3, "storytelling": 9.6, "uniqueness": 9.5
    },
    {
        "title": "The Unsinkable Violet Jessop",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "An ocean liner nurse who survived three separate maritime disasters: the collision of the Olympic, the sinking of the Titanic, and the disaster of the Britannic.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 9.4, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The Liechtensteiner Army of 1866",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In 1866, Liechtenstein sent 80 soldiers to guard an alpine border, suffered zero casualties, and returned with 81 men after making an Italian friend along the way.",
        "curiosity": 9.9, "visual_potential": 8.8, "historical_interest": 9.2, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The Kentucky Meat Shower of 1876",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "On March 3, 1876, chunks of fresh red meat fell from a clear sky over a farm in Bath County, Kentucky, puzzling scientists and locals alike.",
        "curiosity": 9.8, "visual_potential": 9.0, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.8
    },
    {
        "title": "The Balloon Duel of Paris (1808)",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "In May 1808, two French gentlemen fought a duel over Paris half a mile in the sky using blunderbusses from hot air balloons.",
        "curiosity": 9.9, "visual_potential": 9.5, "historical_interest": 9.3, "storytelling": 9.7, "uniqueness": 9.9
    },
    {
        "title": "The Cadaver Synod of 897",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "In 897, Pope Stephen VI exhumed the rotting corpse of his predecessor Pope Formosus, dressed it in papal robes, and put it on trial before a Roman court.",
        "curiosity": 9.9, "visual_potential": 9.2, "historical_interest": 9.6, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The Battle of Karansebes (1788)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In September 1788, the Austrian army mistakenly opened fire on itself in the darkness over barrels of schnapps, suffering thousands of casualties without the enemy present.",
        "curiosity": 9.8, "visual_potential": 9.1, "historical_interest": 9.4, "storytelling": 9.6, "uniqueness": 9.8
    },
    {
        "title": "The Lake Peigneur Sinkhole (1980)",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In November 1980, an oil rig accidentally drilled into a salt mine under Lake Peigneur, draining a 1,300-acre lake into an enormous underwater whirlpool.",
        "curiosity": 9.7, "visual_potential": 9.6, "historical_interest": 9.2, "storytelling": 9.7, "uniqueness": 9.7
    },
    {
        "title": "The War of the Stray Dog (1925)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In October 1925, an armed border clash erupted between Greece and Bulgaria after a Greek soldier chased his runaway dog across the frontier.",
        "curiosity": 9.8, "visual_potential": 8.9, "historical_interest": 9.0, "storytelling": 9.6, "uniqueness": 9.8
    }
]


class TopicDiscoveryEngine:
    """Discovers, evaluates, and scores high-performing historical topics."""

    def __init__(self, ingestion_service: Optional[Any] = None):
        self.wiki = wikipediaapi.Wikipedia(
            user_agent="HistoryShortsPipeline/1.0 (historical_research@shorts.ai)",
            language="en"
        )
        if ingestion_service is not None:
            self.ingestion_service = ingestion_service
        else:
            try:
                from sources.news_ingestion import NewsIngestionService
                self.ingestion_service = NewsIngestionService()
            except Exception:
                self.ingestion_service = None

    def calculate_topic_score(self, item: Dict[str, Any]) -> float:
        """
        Calculates multi-factor score:
        TOPIC_SCORE = curiosity + visual_potential + historical_interest + storytelling + uniqueness
        """
        curiosity = float(item.get("curiosity", 8.0))
        visual_potential = float(item.get("visual_potential", 8.0))
        historical_interest = float(item.get("historical_interest", 8.0))
        storytelling = float(item.get("storytelling", 8.0))
        uniqueness = float(item.get("uniqueness", 8.0))

        score = (curiosity * 1.3) + (visual_potential * 1.1) + (historical_interest * 1.0) + (storytelling * 1.4) + (uniqueness * 1.2)
        return round(score, 2)

    def is_duplicate(
        self,
        db: Session,
        title: str,
        summary: str = "",
        script_text: str = "",
        exclude_topic_id: Optional[str] = None,
        category: Optional[str] = None,
        policy: Optional[str] = None
    ) -> bool:
        """
        Evaluates candidate story against the complete published, ready, and database historical corpus
        using the policy-aware DeduplicationRouter.
        """
        from engines.deduplication_engine import DeduplicationRouter, is_current_affairs_category
        effective_policy = policy
        if not effective_policy and not (category and is_current_affairs_category(category)):
            effective_policy = "historical_year_location"

        router = DeduplicationRouter(policy=effective_policy)
        result = router.evaluate_candidate(
            candidate_title=title,
            candidate_summary=summary,
            candidate_script=script_text,
            db=db,
            exclude_topic_id=exclude_topic_id,
            category=category,
            policy=effective_policy
        )
        if not result.is_allowed:
            logger.info(f"Topic '{title}' rejected by Deduplication Gate ({result.classification}): {result.reason}")
            return True
        return False

    def evaluate_competitor_outlier(
        self,
        competitor_views: Optional[int],
        channel_median_views: Optional[float],
        outlier_threshold: float = 3.0
    ) -> Dict[str, Any]:
        """
        Calculates Outlier Velocity Ratio for competitor topics:
            OutlierRatio = CompetitorShortViews / CompetitorChannelMedianViews
        Data Truth Safeguards:
          - If channel median or views are missing/None/<=0, returns UNAVAILABLE (never substitutes 0 or 1).
          - Identifies candidate breakout hypotheses without modifying production strategy weights.
        """
        if competitor_views is None or channel_median_views is None or channel_median_views <= 0:
            return {
                "status": "UNAVAILABLE",
                "outlier_ratio": None,
                "is_outlier": False,
                "classification": "UNAVAILABLE_DATA",
                "reason": "Competitor views or channel median views unavailable. Zero/1.0 not substituted."
            }

        ratio = float(competitor_views) / float(channel_median_views)
        is_outlier = ratio >= outlier_threshold
        classification = "COMPETITOR_OUTLIER_HYPOTHESIS" if is_outlier else "STANDARD_PERFORMANCE"

        return {
            "status": "VALID",
            "outlier_ratio": round(ratio, 2),
            "is_outlier": is_outlier,
            "classification": classification,
            "reason": f"Outlier velocity ratio {ratio:.2f}x vs competitor channel median ({channel_median_views:.0f} views)"
        }

    def inject_competitor_hypothesis(
        self,
        db: Session,
        title: str,
        summary: str,
        category: str,
        competitor_views: Optional[int] = None,
        channel_median_views: Optional[float] = None,
        outlier_threshold: float = 3.0
    ) -> Optional[Topic]:
        """
        Converts verified competitor breakout topics into internal candidate hypotheses.
        MANDATORY INVARIANT: Competitor hypotheses NEVER directly modify AL AMR strategy weights.
        All hypotheses must pass through AL AMR research, fact-checking, production, and internal telemetry.
        """
        analysis = self.evaluate_competitor_outlier(
            competitor_views=competitor_views,
            channel_median_views=channel_median_views,
            outlier_threshold=outlier_threshold
        )

        if not analysis.get("is_outlier"):
            logger.info(f"Competitor topic '{title}' not qualified as outlier hypothesis: {analysis.get('reason')}")
            return None

        # Check exact title match in Topic table first
        existing_topic = db.query(Topic).filter(Topic.title.ilike(title.strip())).first()
        if existing_topic:
            logger.info(f"Competitor outlier '{title}' skipped: exact title already exists in Topic database.")
            return None

        # Enforce semantic deduplication against existing library
        if self.is_duplicate(db, title, summary):
            logger.info(f"Competitor outlier '{title}' skipped: duplicate of existing AL AMR topic.")
            return None

        topic_id = f"top_{uuid.uuid4().hex[:12]}"
        topic = Topic(
            id=topic_id,
            title=title.strip(),
            summary=summary.strip(),
            category=category.strip(),
            score=56.0,
            status="COMPETITOR_HYPOTHESIS"
        )
        db.add(topic)
        db.commit()
        logger.info(
            f"[COMPETITOR_PRIOR] Ingested candidate hypothesis '{title}' "
            f"(Outlier Ratio: {analysis['outlier_ratio']}x). Ready for internal research."
        )
        return topic

    def discover_current_affairs_candidates(
        self,
        db: Session,
        limit: int = 3,
        include_gdelt: bool = False,
        **kwargs
    ) -> List[Topic]:
        """
        Discovers verified, multi-source current-affairs opportunities via the isolated
        intelligence layer and persists qualifying items as approved Topic records.
        Fails safely and returns an empty list if any external error occurs.
        """
        try:
            from intelligence import discover_current_affairs_candidates as run_discovery
            return run_discovery(db=db, limit=limit, include_gdelt=include_gdelt, **kwargs)
        except Exception as e:
            logger.warning(f"[CURRENT_AFFAIRS_DISCOVERY] Discovery cycle noticed exception: {e}")
            return []

    def discover_topics(
        self,
        db: Session,
        limit: int = 5,
        profile: Optional[Any] = None,
        exclude_topic_ids: Optional[Any] = None,
        allow_ai: bool = True
    ) -> List[Topic]:
        """
        Primary topic discovery entry point.
        Dispatches according to DiscoveryProfile:
          - CURRENT_AFFAIRS: Live news ingestion (RSS + GDELT), recency filtering, zero historical fallback.
          - HISTORICAL: Legacy mode for historicalShorts.
        """
        from core.discovery_profile import DiscoveryProfile, ProfileType
        if profile is None:
            profile = DiscoveryProfile(profile_type=ProfileType.CURRENT_AFFAIRS)

        if getattr(profile, "profile_type", None) == ProfileType.CURRENT_AFFAIRS:
            return self._discover_current_affairs_topics(db, limit, profile)
        else:
            return self._discover_historical_topics(db, limit=limit, exclude_topic_ids=exclude_topic_ids, allow_ai=allow_ai)

    def _discover_current_affairs_topics(
        self,
        db: Session,
        limit: int = 5,
        profile: Optional[Any] = None
    ) -> List[Topic]:
        """
        Discovers real-time geopolitical topics exclusively from live news feeds.
        STRICT GUARANTEE:
          1. Prioritizes real incoming events from live feeds (RSS + GDELT).
          2. Strongly enforces 24-hour recency (TIER 1 & TIER 2).
          3. Stale unproduced topics (>24h old) are strictly excluded.
          4. Zero fallback to historical trivia prompt or curated historical seeds.
        """
        historical_cat_values = {c.value for c in HistoricalCategory}
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Prioritize real incoming live events via NewsIngestionService
        if self.ingestion_service:
            logger.info("Executing live news ingestion for current-affairs discovery...")
            freshness_tiers = [FreshnessTier.TIER_1, FreshnessTier.TIER_2]
            articles = self.ingestion_service.ingest_live_news(
                db=db,
                extract_body=False,
                freshness_tiers=freshness_tiers,
                limit_per_source=10
            )

            discovered = []
            if articles:
                from intelligence.clustering import EventClusterEngine
                cluster_engine = EventClusterEngine(profile=profile)
                clusters = cluster_engine.cluster_articles(articles)

                # Sort clusters by confidence, independent publisher count, and recency
                clusters.sort(
                    key=lambda c: (
                        c.confidence,
                        c.independent_publisher_count,
                        c.first_published_at or datetime.min
                    ),
                    reverse=True
                )

                for cluster in clusters:
                    if self.is_duplicate(db, cluster.canonical_title):
                        continue

                    # Check cluster duplicate via CurrentAffairsDeduplicationEngine
                    try:
                        from intelligence.deduplication import CurrentAffairsDeduplicationEngine
                        dedup = CurrentAffairsDeduplicationEngine(profile=profile)
                        is_dup, _, _ = dedup.is_cluster_duplicate(cluster, db)
                        if is_dup:
                            continue
                    except Exception as dedup_err:
                        logger.debug(f"Dedup check notice: {dedup_err}")

                    event_card = cluster.to_event_card()
                    topic_id = f"top_{uuid.uuid4().hex[:12]}"
                    topic = Topic(
                        id=topic_id,
                        title=cluster.canonical_title,
                        summary=cluster.canonical_summary or cluster.canonical_title,
                        category=cluster.primary_category or "Geopolitics",
                        score=round(cluster.confidence * 100.0, 1),
                        status="APPROVED",
                        event_id=cluster.cluster_id,
                        verification_state=cluster.verification_state,
                        independent_sources_count=cluster.independent_publisher_count,
                        event_card_json=event_card.to_json()
                    )
                    db.add(topic)

                    # Link all articles in cluster and extract text for primary article
                    for art in cluster.articles:
                        norm_url = getattr(art, "normalized_url", None)
                        if norm_url:
                            db_art = db.query(ArticleRecord).filter(
                                ArticleRecord.normalized_url == norm_url
                            ).first()
                            if db_art:
                                db_art.topic_id = topic_id
                                if not db_art.article_text or db_art.extraction_status == "PENDING":
                                    try:
                                        ext_res = self.ingestion_service.extractor.extract_from_url(db_art.url)
                                        if ext_res.text:
                                            db_art.article_text = ext_res.text
                                            db_art.extraction_status = ext_res.extraction_status
                                            db_art.retrieval_status = ext_res.retrieval_status
                                            if ext_res.author and not db_art.author:
                                                db_art.author = ext_res.author
                                            if len(ext_res.text) > len(topic.summary):
                                                topic.summary = ext_res.text[:350].rsplit(" ", 1)[0] + "..."
                                    except Exception as ext_err:
                                        logger.warning(f"On-demand extraction for topic {topic_id} failed: {ext_err}")

                    # Persist claims with provenance into ClaimRecord
                    for cl in cluster.claims:
                        db_claim = ClaimRecord(
                            topic_id=topic_id,
                            claim_text=cl.claim_text,
                            verification_status=cl.verification_state,
                            supporting_sources=cl.publisher,
                            confidence=cl.confidence,
                            source_article_id=cl.source_article_id,
                            publisher=cl.publisher,
                            source_url=cl.source_url,
                            evidence_excerpt=cl.evidence_excerpt
                        )
                        db.add(db_claim)

                    # Persist sources into SourceRecord
                    for src in event_card.sources:
                        db_src = SourceRecord(
                            topic_id=topic_id,
                            source_name=src["publisher"],
                            source_url=src.get("url"),
                            source_type="news_report",
                            confidence=0.90
                        )
                        db.add(db_src)

                    discovered.append(topic)
                    if len(discovered) >= limit:
                        break

                if discovered:
                    db.commit()
                    logger.info(f"Discovered {len(discovered)} verified current-affairs event clusters from live feeds.")
                    return discovered

        # 2. If live ingestion returned no candidates, check for fresh unproduced topics in DB (<24h old)
        published_topic_ids = {
            j.topic_id for j in db.query(Job).filter(Job.state == "PUBLISHED").all() if j.topic_id
        }
        cutoff_24h = now_utc - timedelta(hours=24)

        unproduced_fresh = db.query(Topic).filter(
            Topic.id.notin_(published_topic_ids),
            Topic.category.notin_(historical_cat_values),
            Topic.created_at >= cutoff_24h
        ).all()

        if unproduced_fresh:
            random.shuffle(unproduced_fresh)
            logger.info(f"Retrieved {len(unproduced_fresh[:limit])} fresh (<24h) unproduced current-affairs topics from DB.")
            return unproduced_fresh[:limit]

        # 3. Halt cleanly with empty list: ZERO historical fallback
        logger.warning(
            "No current event candidates available from live news feeds. "
            "Data integrity preserved: halting topic discovery without historical fallback."
        )
        return []

    def _discover_historical_topics(
        self,
        db: Session,
        limit: int = 5,
        exclude_topic_ids: Optional[Any] = None,
        allow_ai: bool = True
    ) -> List[Topic]:
        """Discovers new candidate topics or returns unproduced approved topics."""
        # 1. First check if we have approved topics in DB that have not been published or produced yet
        from core.models import Job, UploadRecord
        excluded_ids = set(exclude_topic_ids or [])

        # Exclude topics that have already reached terminal, scheduled, or active production states
        try:
            active_jobs = db.query(Job).filter(
                Job.state.in_([
                    "PUBLISHED", "SCHEDULED", "READY_TO_UPLOAD", "UPLOADING",
                    "EDITING", "QA", "RENDERED_QA_PASSED", "VOICE_READY",
                    "VOICE_GENERATING", "AUDIO_READY", "SCRIPT_READY", "SCRIPTING",
                    "RESEARCHED", "RESEARCHING", "FACT_CHECKED", "FACT_CHECKING",
                    "VISUALS_READY", "VISUALS_SEARCHING", "VISUAL_PLANNING"
                ])
            ).all()
            for j in active_jobs:
                if j.topic_id:
                    excluded_ids.add(j.topic_id)

            # Exclude topics referenced by active or historical UploadRecords
            active_uploads = db.query(UploadRecord).filter(
                UploadRecord.status.in_(["PUBLISHED", "SCHEDULED", "SUCCESS", "TEST_VERIFIED"])
            ).all()
            for u in active_uploads:
                if u.job_id:
                    u_job = db.query(Job).filter(Job.id == u.job_id).first()
                    if u_job and u_job.topic_id:
                        excluded_ids.add(u_job.topic_id)
        except Exception as e:
            logger.warning(f"Error gathering active/published topic exclusions: {e}")

        def is_test_topic(t: Topic) -> bool:
            t_id = (t.id or "").lower()
            t_title = (t.title or "").strip()
            t_summary = (t.summary or "").strip().lower()
            t_cat = (t.category or "").strip().lower()
            if t_id.startswith(("top_test_", "test_top_", "test_topic_", "test_", "top_thr_")) or t_id == "test_topic":
                return True
            if t_title in ("The Test Historical Incident", "Test Incident", "Test Topic", "Test Title", "Sample Topic"):
                return True
            if "thread topic" in t_title.lower():
                return True
            if t_cat == "test" or t_summary in ("test summary", "test", "sample summary"):
                return True
            return False

        # Query eligible unproduced topics (exclude REJECTED, COMPLETED, PUBLISHED, SCHEDULED)
        unproduced = db.query(Topic).filter(
            Topic.id.notin_(excluded_ids),
            ~Topic.status.in_(["REJECTED", "COMPLETED", "PUBLISHED", "SCHEDULED"])
        ).all()

        # Filter unproduced topics through deduplication against published/scheduled stories
        valid_unproduced = []
        for t in unproduced:
            if t.id in excluded_ids:
                continue
            if is_test_topic(t):
                continue
            # Pass exclude_topic_id=t.id so the topic is not compared against itself in the corpus
            if not self.is_duplicate(db, t.title, t.summary, exclude_topic_id=t.id):
                valid_unproduced.append(t)
                if len(valid_unproduced) >= limit:
                    break

        if valid_unproduced:
            from engines.script_engine import CURATED_SCRIPTS
            # Prioritize verified curated documentary scripts
            valid_unproduced.sort(key=lambda t: (0 if t.title in CURATED_SCRIPTS else 1, t.created_at))
            return valid_unproduced[:limit]

        # 1. Check content strategy from ExperimentManager
        strategy_info = {"strategy_type": "PROVEN_PATTERN", "description": "Default strategy"}
        try:
            from engines.experiment_manager import ExperimentManager
            from engines.learning_engine import LearningEngine
            exp_mgr = ExperimentManager()
            learn_eng = LearningEngine()
            strategy_info = exp_mgr.select_content_strategy(db)
            guidance = learn_eng.get_strategy_guidance(db)
            logger.info(f"Topic Discovery running under strategy: [{strategy_info['strategy_type']}] - {strategy_info['description']}")
        except Exception as e:
            logger.warning(f"Could not load learning guidance: {e}")
            guidance = {}

        discovered = []

        # 2. If AI Provider is available and permitted, generate fresh stories online
        is_test = TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")
        if allow_ai and AI_PROVIDER_AVAILABLE and not is_test:
            try:
                from core.gemini_client import get_gemini_client
                gemini_client = get_gemini_client()
                
                favored_cats = guidance.get("top_categories", ["Unusual Wars", "Documented Disasters"])
                cat_prompt_part = f"Focus especially on high-performing categories: {', '.join(favored_cats)}." if strategy_info["strategy_type"] == "PROVEN_PATTERN" else "Explore unusual, less-known historical categories."

                prompt = (
                    f"Suggest 3 obscure, true, bizarre historical events from American or European history "
                    f"that make great 23-second YouTube Shorts. {cat_prompt_part} "
                    f"Format each as: Title | Category | 1-sentence factual summary. "
                    f"Do NOT use generic facts. Prioritize strange laws, unusual wars, or documented mysteries."
                )
                from config.settings import GEMINI_MODEL
                response = gemini_client.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt
                )
                lines = response.text.strip().split("\n")
                for line in lines:
                    if "|" in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3:
                            title, category, summary = parts[0].lstrip("1234567890. -*"), parts[1], parts[2]
                            if not self.is_duplicate(db, title, summary):
                                topic_id = f"top_{uuid.uuid4().hex[:12]}"
                                topic = Topic(
                                    id=topic_id,
                                    title=title,
                                    summary=summary,
                                    category=category,
                                    score=52.0,
                                    status="APPROVED"
                                )
                                db.add(topic)
                                discovered.append(topic)
                                if len(discovered) >= limit:
                                    break
                if discovered:
                    db.commit()
                    logger.info(f"Discovered {len(discovered)} fresh topics via Gemini 3.6 Flash AI under strategy {strategy_info['strategy_type']}!")
                    return discovered
            except Exception as e:
                logger.warning(f"Gemini live topic discovery fallback: {e}")

        # 3. Evaluate curated seed topics (prioritize current geopolitics)
        candidates = list(CURATED_GEOPOLITICAL_SEEDS) + list(CURATED_HISTORICAL_SEEDS)
        random.shuffle(candidates)

        for item in candidates:
            if self.is_duplicate(db, item["title"], item["summary"]):
                continue

            score = self.calculate_topic_score(item)
            if score < 45.0:
                continue

            topic_id = f"top_{uuid.uuid4().hex[:12]}"
            topic = Topic(
                id=topic_id,
                title=item["title"],
                summary=item["summary"],
                category=item["category"],
                score=score,
                status="APPROVED"
            )
            db.add(topic)
            discovered.append(topic)
            if len(discovered) >= limit:
                break

        db.commit()
        logger.info(f"Discovered {len(discovered)} qualified historical topics.")
        return discovered
