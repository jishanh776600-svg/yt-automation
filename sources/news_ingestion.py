"""
Real-Time News Ingestion & Article Normalization Service.
Orchestrates RSS/Atom feeds and GDELT 2.0 discovery, normalizes timestamps and URLs,
performs deduplication, extracts clean body text with Trafilatura, and persists to SQLite.
Provides complete failure isolation: one bad feed or article never crashes production.
"""
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Set
import feedparser
from sqlalchemy.orm import Session

from core.models import ArticleRecord
from intelligence.freshness import (
    FreshnessTier,
    normalize_timestamp,
    classify_freshness,
    calculate_freshness_score,
)
from intelligence.scoring import (
    SourceType,
    classify_source,
    calculate_composite_score,
)
from intelligence.deduplication import (
    normalize_url,
    URLDeduplicator,
)
from sources.rss_sources import DEFAULT_PRODUCTION_FEEDS, DEFAULT_GEOPOLITICAL_FEEDS, RSSFeedSource
from sources.gdelt_adapter import GDELTAdapter
from sources.extractor import ArticleExtractor, ExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class NormalizedArticle:
    """Normalized article contract fulfilling Phase 1 specifications."""
    article_id: str
    title: str
    source_name: str
    url: str
    normalized_url: str
    published_utc: Optional[datetime]
    discovered_utc: datetime
    freshness_tier: str
    freshness_score: float
    source_type: str
    source_tier: str
    source_confidence: float
    composite_score: float
    category: str = "Geopolitics"
    description: Optional[str] = None
    raw_feed_text: Optional[str] = None
    article_text: Optional[str] = None
    author: Optional[str] = None
    language: Optional[str] = None
    extraction_status: str = "PENDING"  # PENDING, SUCCESS, FAILED, EMPTY, SKIPPED
    retrieval_status: str = "SUCCESS"    # SUCCESS, FAILED, TIMEOUT, HTTP_ERROR
    topic_id: Optional[str] = None
    embedding: Optional[Any] = None

    @property
    def publisher(self) -> str:
        return self.source_name

    @property
    def summary(self) -> Optional[str]:
        return self.description

    def to_record(self) -> ArticleRecord:
        """Converts normalized article to SQLAlchemy ArticleRecord."""
        return ArticleRecord(
            id=self.article_id,
            title=self.title,
            source_name=self.source_name,
            source_type=self.source_type,
            source_tier=self.source_tier,
            url=self.url,
            normalized_url=self.normalized_url,
            author=self.author,
            language=self.language,
            category=self.category,
            published_utc=self.published_utc,
            discovered_utc=self.discovered_utc,
            freshness_tier=self.freshness_tier,
            freshness_score=self.freshness_score,
            source_confidence=self.source_confidence,
            composite_score=self.composite_score,
            summary=self.description,
            raw_feed_text=self.raw_feed_text,
            article_text=self.article_text,
            extraction_status=self.extraction_status,
            retrieval_status=self.retrieval_status,
            topic_id=self.topic_id,
            created_at=self.discovered_utc
        )


class NewsIngestionService:
    """
    Ingests, normalizes, deduplicates, and extracts live geopolitical news articles.
    """

    def __init__(
        self,
        rss_sources: Optional[List[RSSFeedSource]] = None,
        enable_gdelt: bool = True,
        extractor_timeout: int = 10
    ):
        self.rss_sources = rss_sources or list(DEFAULT_PRODUCTION_FEEDS)
        self.enable_gdelt = enable_gdelt
        self.gdelt_adapter = GDELTAdapter(timeout=extractor_timeout)
        self.extractor = ArticleExtractor(timeout=extractor_timeout)
        self.deduplicator = URLDeduplicator()

    def parse_rss_feed(
        self,
        feed_source: RSSFeedSource,
        limit: int = 25
    ) -> List[Dict[str, Any]]:
        """
        Parses a single RSS/Atom feed with error isolation.
        Returns list of raw item dicts.
        """
        raw_items = []
        try:
            feed = feedparser.parse(feed_source.url)
            if feed.bozo and not feed.entries:
                logger.warning(f"RSS feed parsing bozo for {feed_source.name}: {feed.bozo_exception}")
                return []

            for entry in feed.entries[:limit]:
                url = getattr(entry, "link", None)
                title = getattr(entry, "title", None)
                if not url or not title:
                    continue

                # Published date representation from feedparser
                published_raw = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    published_raw = entry.published_parsed
                elif hasattr(entry, "published"):
                    published_raw = entry.published
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    published_raw = entry.updated_parsed
                elif hasattr(entry, "updated"):
                    published_raw = entry.updated

                # Summary / Description
                summary = None
                if hasattr(entry, "summary"):
                    summary = entry.summary
                elif hasattr(entry, "description"):
                    summary = entry.description

                author = getattr(entry, "author", None)

                raw_items.append({
                    "title": title.strip(),
                    "url": url.strip(),
                    "source_name": feed_source.name,
                    "source_type": feed_source.source_type.value,
                    "published_raw": published_raw,
                    "author": author,
                    "language": feed_source.language or None,
                    "category": getattr(feed_source, "default_category", "Geopolitics"),
                    "summary": summary,
                    "raw_feed_text": summary
                })

            logger.info(f"Parsed {len(raw_items)} items from RSS feed '{feed_source.name}'.")
        except Exception as e:
            logger.warning(f"Failed parsing feed '{feed_source.name}' ({feed_source.url}): {e}")

        return raw_items

    def normalize_article_data(
        self,
        raw_item: Dict[str, Any],
        now_utc: Optional[datetime] = None
    ) -> Optional[NormalizedArticle]:
        """
        Applies strict normalization contract to a single raw candidate article.
        Returns NormalizedArticle or None if invalid.
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

        url = raw_item.get("url", "").strip()
        title = raw_item.get("title", "").strip()
        if not url or not title:
            return None

        norm_url = normalize_url(url)
        if not norm_url:
            return None

        # 1. Normalize publication timestamp to UTC
        published_utc = normalize_timestamp(raw_item.get("published_raw"), now_utc=now_utc)

        # 2. Freshness evaluation
        freshness_tier, age_hours, _ = classify_freshness(published_utc, reference_time=now_utc)
        freshness_score = calculate_freshness_score(published_utc, reference_time=now_utc)

        # 3. Source classification & confidence
        src_type_enum, src_confidence, src_tier_label = classify_source(
            url=norm_url,
            publisher=raw_item.get("source_name")
        )
        composite_score = calculate_composite_score(freshness_score, src_confidence)

        article_id = f"art_{uuid.uuid4().hex[:12]}"

        return NormalizedArticle(
            article_id=article_id,
            title=title,
            source_name=raw_item.get("source_name") or "Unknown Publisher",
            url=url,
            normalized_url=norm_url,
            published_utc=published_utc,
            discovered_utc=now_utc,
            freshness_tier=freshness_tier.value,
            freshness_score=freshness_score,
            source_type=src_type_enum.value,
            source_tier=src_tier_label,
            source_confidence=src_confidence,
            composite_score=composite_score,
            category=raw_item.get("category", "Geopolitics"),
            description=raw_item.get("summary"),
            raw_feed_text=raw_item.get("raw_feed_text"),
            article_text=raw_item.get("article_text"),
            author=raw_item.get("author"),
            language=raw_item.get("language") or None,
            extraction_status=raw_item.get("extraction_status", "PENDING"),
            retrieval_status=raw_item.get("retrieval_status", "SUCCESS"),
            topic_id=raw_item.get("topic_id")
        )

    def ingest_live_news(
        self,
        db: Optional[Session] = None,
        extract_body: bool = False,
        freshness_tiers: Optional[List[FreshnessTier]] = None,
        limit_per_source: int = 20
    ) -> List[NormalizedArticle]:
        """
        Executes complete ingestion pipeline:
          1. Reads RSS feeds
          2. Queries GDELT 2.0
          3. Deduplicates URLs
          4. Normalizes timestamps to UTC
          5. Optionally runs Trafilatura extraction
          6. Persists to SQLite if db session is provided
        Returns list of normalized articles.
        """
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        raw_items: List[Dict[str, Any]] = []

        # 1. Ingest all RSS feeds with per-source isolation
        for feed_source in self.rss_sources:
            try:
                items = self.parse_rss_feed(feed_source, limit=limit_per_source)
                raw_items.extend(items)
            except Exception as e:
                logger.warning(f"Isolation caught failure on RSS source {feed_source.name}: {e}")

        # 2. Ingest GDELT if enabled
        if self.enable_gdelt:
            try:
                gdelt_items = self.gdelt_adapter.fetch_articles(limit=limit_per_source * 2)
                raw_items.extend(gdelt_items)
            except Exception as e:
                logger.warning(f"Isolation caught failure on GDELT adapter: {e}")

        # Allowed freshness tiers (default: TIER 1 and TIER 2: last 24h)
        allowed_tier_values = {
            t.value for t in (freshness_tiers or [FreshnessTier.TIER_1, FreshnessTier.TIER_2])
        }

        normalized_articles: List[NormalizedArticle] = []

        # 3. Deduplicate and normalize
        for item in raw_items:
            url = item.get("url")
            if not url or self.deduplicator.is_duplicate(url, db=db):
                continue

            article = self.normalize_article_data(item, now_utc=now_utc)
            if not article:
                continue

            # 4. Optional Trafilatura extraction
            if extract_body:
                try:
                    ext_res = self.extractor.extract_from_url(article.url)
                    article.article_text = ext_res.text
                    article.extraction_status = ext_res.extraction_status
                    article.retrieval_status = ext_res.retrieval_status
                    if ext_res.author and not article.author:
                        article.author = ext_res.author
                    if ext_res.title and (not article.title or len(article.title) < 15):
                        article.title = ext_res.title
                    # Recover missing publication date from page metadata if available
                    if article.published_utc is None and ext_res.date:
                        recovered_dt = normalize_timestamp(ext_res.date, now_utc=now_utc)
                        if recovered_dt:
                            article.published_utc = recovered_dt
                            f_tier, _, _ = classify_freshness(recovered_dt, reference_time=now_utc)
                            article.freshness_tier = f_tier.value
                            article.freshness_score = calculate_freshness_score(recovered_dt, reference_time=now_utc)
                            article.composite_score = calculate_composite_score(article.freshness_score, article.source_confidence)
                except Exception as ext_err:
                    logger.warning(f"Extraction error on {article.url}: {ext_err}")
                    article.extraction_status = "FAILED"
                    article.retrieval_status = "FAILED"

            # Check freshness tier constraint
            if freshness_tiers is not None and article.freshness_tier not in allowed_tier_values:
                continue

            # Mark seen
            self.deduplicator.mark_seen(article.normalized_url)
            normalized_articles.append(article)

        # 5. Persist to DB idempotently
        if db is not None and normalized_articles:
            self.persist_articles(db, normalized_articles)

        logger.info(f"Ingestion completed: {len(normalized_articles)} fresh normalized articles produced.")
        return normalized_articles

    def persist_articles(self, db: Session, articles: List[NormalizedArticle]) -> int:
        """
        Idempotently inserts articles into database.
        Tolerant of duplicate input via normalized_url conflict checking.
        Enriches existing articles if new extraction text or metadata is available.
        """
        inserted_count = 0
        try:
            for art in articles:
                # Check DB directly to guarantee transaction safety
                exists = db.query(ArticleRecord).filter(
                    ArticleRecord.normalized_url == art.normalized_url
                ).first()

                if exists is None:
                    record = art.to_record()
                    db.add(record)
                    inserted_count += 1
                else:
                    # Enrich existing record if newly extracted
                    updated = False
                    if art.article_text and not exists.article_text:
                        exists.article_text = art.article_text
                        exists.extraction_status = art.extraction_status
                        exists.retrieval_status = art.retrieval_status
                        updated = True
                    if art.author and not exists.author:
                        exists.author = art.author
                        updated = True
                    if art.description and not exists.summary:
                        exists.summary = art.description
                        updated = True
                    if art.freshness_score > exists.freshness_score:
                        exists.freshness_score = art.freshness_score
                        exists.composite_score = art.composite_score
                        exists.freshness_tier = art.freshness_tier
                        updated = True

            db.commit()
            logger.info(f"Persisted {inserted_count} new articles to database.")
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to persist articles: {e}")
            raise

        return inserted_count
