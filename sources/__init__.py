"""Forwarding bridge for root sources import."""
from engines.visual_intelligence.sources import *
from sources.rss_sources import DEFAULT_GEOPOLITICAL_FEEDS, RSSFeedSource
from sources.extractor import ArticleExtractor, ExtractionResult
from sources.gdelt_adapter import GDELTAdapter
from sources.news_ingestion import NewsIngestionService, NormalizedArticle
