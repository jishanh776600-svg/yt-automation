"""
Historical Mysteries and Bizarre Real-World Event Feed Registry.
Maintains curated, high-credibility discovery feeds for historical curiosities and mysteries.
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


DEFAULT_HISTORICAL_MYSTERY_FEEDS: List[RSSFeedSource] = [
    RSSFeedSource(
        name="ScienceDaily Strange & Offbeat",
        url="https://www.sciencedaily.com/rss/strange_offbeat.xml",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Live Science Strange News",
        url="https://www.livescience.com/feeds/tag/strange-news",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Google News Mystery & Discoveries",
        url="https://news.google.com/rss/search?q=when:48h+unexplained+OR+mysterious+anomaly+OR+bizarre&hl=en-US&gl=US&ceid=US:en",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Google News Ancient Discoveries",
        url="https://news.google.com/rss/search?q=when:48h+\"bizarre\"+OR+\"ancient+discovery\"+OR+\"archaeological+enigma\"&hl=en-US&gl=US&ceid=US:en",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    )
]

DEFAULT_MYSTERY_SCIENCE_FEEDS: List[RSSFeedSource] = DEFAULT_HISTORICAL_MYSTERY_FEEDS
DEFAULT_PRODUCTION_FEEDS: List[RSSFeedSource] = DEFAULT_HISTORICAL_MYSTERY_FEEDS
DEFAULT_GEOPOLITICAL_FEEDS: List[RSSFeedSource] = DEFAULT_PRODUCTION_FEEDS

