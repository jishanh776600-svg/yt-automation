"""
Source adapters for external news/intelligence ingestion.
"""
from intelligence.sources.rss_source import RSSSourceAdapter
from intelligence.sources.gdelt_source import GDELTSourceAdapter

__all__ = ["RSSSourceAdapter", "GDELTSourceAdapter"]
