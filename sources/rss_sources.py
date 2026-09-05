"""
Geopolitical and Defense RSS Feed Registry.
Maintains curated, high-credibility global news and defense feeds.
"""
from dataclasses import dataclass
from typing import List
from intelligence.scoring import SourceType


@dataclass
class RSSFeedSource:
    name: str
    url: str
    source_type: SourceType
    default_category: str
    language: str = "en"


DEFAULT_MYSTERY_SCIENCE_FEEDS: List[RSSFeedSource] = [
    RSSFeedSource(
        name="ScienceDaily Strange & Offbeat",
        url="https://www.sciencedaily.com/rss/strange_offbeat.xml",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Weird Science"
    ),
    RSSFeedSource(
        name="Live Science Strange News",
        url="https://www.livescience.com/feeds/tag/strange-news",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Mystery & Bizarre"
    ),
    RSSFeedSource(
        name="Live Science Discoveries",
        url="https://www.livescience.com/feeds/all",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Weird Science"
    ),
    RSSFeedSource(
        name="ScienceDaily Discoveries",
        url="https://www.sciencedaily.com/rss/all.xml",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Weird Science"
    ),
    RSSFeedSource(
        name="Phys.org Science",
        url="https://phys.org/rss-feed/",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Weird Science"
    ),
    RSSFeedSource(
        name="ScienceAlert Nature & Space",
        url="https://www.sciencealert.com/feed",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Weird Science"
    ),
    RSSFeedSource(
        name="Google News Mystery & Discoveries",
        url="https://news.google.com/rss/search?q=when:48h+scientists+discover+OR+unexplained+OR+mysterious&hl=en-US&gl=US&ceid=US:en",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Mystery & Bizarre"
    ),
    RSSFeedSource(
        name="Google News Ancient Discoveries",
        url="https://news.google.com/rss/search?q=when:48h+\"bizarre\"+OR+\"ancient+discovery\"+OR+\"archaeologists\"&hl=en-US&gl=US&ceid=US:en",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Mystery & Bizarre"
    )
]

DEFAULT_PRODUCTION_FEEDS: List[RSSFeedSource] = DEFAULT_MYSTERY_SCIENCE_FEEDS
DEFAULT_GEOPOLITICAL_FEEDS: List[RSSFeedSource] = DEFAULT_PRODUCTION_FEEDS

