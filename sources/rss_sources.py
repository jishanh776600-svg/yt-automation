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
        name="Historic Mysteries",
        url="https://www.historicmysteries.com/feed/",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Archaeology Magazine News",
        url="https://www.archaeology.org/feed",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Google News Ancient Discoveries",
        url="https://news.google.com/rss/search?q=when:48h+\"ancient+discovery\"+OR+\"archaeological+enigma\"+OR+\"lost+civilization\"&hl=en-US&gl=US&ceid=US:en",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    ),
    RSSFeedSource(
        name="Live Science Strange News",
        url="https://www.livescience.com/feeds/tag/strange-news",
        source_type=SourceType.ESTABLISHED_NEWS,
        default_category="Historical Mysteries"
    )
]

DEFAULT_MYSTERY_SCIENCE_FEEDS: List[RSSFeedSource] = DEFAULT_HISTORICAL_MYSTERY_FEEDS
DEFAULT_PRODUCTION_FEEDS: List[RSSFeedSource] = DEFAULT_HISTORICAL_MYSTERY_FEEDS
DEFAULT_GEOPOLITICAL_FEEDS: List[RSSFeedSource] = DEFAULT_PRODUCTION_FEEDS

