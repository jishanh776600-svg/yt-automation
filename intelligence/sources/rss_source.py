"""
RSS & Atom Feed Ingestion Source.
Parses public wire and news feeds into normalized RawArticle records.
Designed with strict per-feed error isolation and resilient timestamp parsing.
"""
import logging
import urllib.request
from datetime import datetime, timezone
import email.utils
from typing import List, Dict, Optional, Any
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

from intelligence.models import RawArticle
from intelligence.normalization import normalize_article, normalize_url

logger = logging.getLogger(__name__)

# Default reputable international & geopolitical news feeds
DEFAULT_RSS_FEEDS = [
    {
        "name": "BBC World News",
        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
        "domain": "bbc.com",
        "weight": 1.0
    },
    {
        "name": "Reuters World",
        "url": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best",
        "domain": "reuters.com",
        "weight": 1.0
    },
    {
        "name": "Associated Press News",
        "url": "https://apnews.com/rss",
        "domain": "apnews.com",
        "weight": 1.0
    },
    {
        "name": "Al Jazeera English",
        "url": "https://www.aljazeera.com/xml/rss/all.xml",
        "domain": "aljazeera.com",
        "weight": 0.9
    }
]


def parse_pubdate(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parses RFC 822 / RFC 2822, ISO 8601, and common date strings into UTC datetime.
    """
    if not date_str:
        return None
    cleaned = date_str.strip()

    # 1. Try email.utils.parsedate_to_datetime (standard for RSS RFC 822)
    try:
        dt = email.utils.parsedate_to_datetime(cleaned)
        if dt.tzinfo:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        pass

    # 2. Try ISO 8601 (Atom standard)
    iso_candidates = [
        cleaned,
        cleaned.replace("Z", "+00:00")
    ]
    for cand in iso_candidates:
        try:
            dt = datetime.fromisoformat(cand)
            if dt.tzinfo:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            continue

    # 3. Common fallback formats
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except Exception:
            continue

    logger.debug(f"[RSS_PARSER] Could not parse date: '{date_str}'")
    return None


class RSSSourceAdapter:
    """Ingests articles from configurable RSS/Atom feeds with error containment."""

    def __init__(
        self,
        feeds: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 8.0,
        user_agent: str = "AlAmrIntelligence/1.0 (+https://github.com/jishanh776600-svg/yt-automation)"
    ):
        self.feeds = feeds or DEFAULT_RSS_FEEDS
        self.timeout = timeout
        self.user_agent = user_agent

    def fetch_feed_xml(self, url: str) -> Optional[str]:
        """Fetches raw feed XML with custom User-Agent and timeout."""
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": self.user_agent, "Accept": "application/rss+xml, application/xml, text/xml"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    raw_bytes = resp.read()
                    # Try UTF-8 first, fallback to Latin-1
                    try:
                        return raw_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        return raw_bytes.decode("latin-1", errors="ignore")
                else:
                    logger.warning(f"[RSS_SOURCE] HTTP {resp.status} fetching feed {url}")
        except Exception as e:
            logger.warning(f"[RSS_SOURCE] Failed to fetch feed {url}: {e}")
        return None

    def parse_feed_content(self, xml_content: str, default_source_name: str, default_domain: str) -> List[RawArticle]:
        """
        Parses XML string as either RSS 2.0 (<rss><channel><item>) or Atom (<feed><entry>).
        Returns a list of un-normalized RawArticle records.
        """
        articles: List[RawArticle] = []
        if not xml_content or not xml_content.strip():
            return articles

        try:
            root = ET.fromstring(xml_content.strip())
        except Exception as e:
            logger.warning(f"[RSS_PARSER] Malformed XML for {default_source_name}: {e}")
            return articles

        # Detect tag format (handle namespaces)
        tag = root.tag.lower()

        # 1. RSS 2.0 / RDF format
        if "rss" in tag or "rdf" in tag or root.find("channel") is not None:
            channel = root.find("channel") if root.find("channel") is not None else root
            items = channel.findall("item")
            for it in items:
                try:
                    title_elem = it.find("title")
                    link_elem = it.find("link")
                    desc_elem = it.find("description")
                    pubdate_elem = it.find("pubDate")
                    author_elem = it.find("author") or it.find("{http://purl.org/dc/elements/1.1/}creator")

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    raw_link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                    summary = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
                    pub_date = parse_pubdate(pubdate_elem.text) if pubdate_elem is not None and pubdate_elem.text else None
                    author = author_elem.text.strip() if author_elem is not None and author_elem.text else None

                    if not title or not raw_link:
                        continue

                    # Extract netloc domain
                    parsed_domain = urlparse(raw_link).netloc.replace("www.", "").lower() or default_domain

                    article = RawArticle(
                        title=title,
                        summary=summary,
                        url=raw_link,
                        source_domain=parsed_domain,
                        source_name=default_source_name,
                        published_at=pub_date,
                        author=author
                    )
                    articles.append(article)
                except Exception as item_err:
                    logger.debug(f"[RSS_PARSER] Skipping malformed RSS item in {default_source_name}: {item_err}")
                    continue

        # 2. Atom format (<feed><entry>)
        elif "feed" in tag:
            # Atom elements often carry xmlns namespaces
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")
            if not entries:
                entries = root.findall("entry")

            for ent in entries:
                try:
                    title_elem = ent.find("{http://www.w3.org/2005/Atom}title") or ent.find("title")
                    desc_elem = (
                        ent.find("{http://www.w3.org/2005/Atom}summary")
                        or ent.find("summary")
                        or ent.find("{http://www.w3.org/2005/Atom}content")
                        or ent.find("content")
                    )
                    date_elem = (
                        ent.find("{http://www.w3.org/2005/Atom}updated")
                        or ent.find("updated")
                        or ent.find("{http://www.w3.org/2005/Atom}published")
                        or ent.find("published")
                    )

                    # Links in Atom are usually in <link href="...">
                    link_elem = ent.find("{http://www.w3.org/2005/Atom}link") or ent.find("link")
                    raw_link = ""
                    if link_elem is not None:
                        raw_link = link_elem.get("href") or link_elem.text or ""

                    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
                    summary = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ""
                    pub_date = parse_pubdate(date_elem.text) if date_elem is not None and date_elem.text else None

                    if not title or not raw_link:
                        continue

                    parsed_domain = urlparse(raw_link).netloc.replace("www.", "").lower() or default_domain

                    article = RawArticle(
                        title=title,
                        summary=summary,
                        url=raw_link,
                        source_domain=parsed_domain,
                        source_name=default_source_name,
                        published_at=pub_date
                    )
                    articles.append(article)
                except Exception as entry_err:
                    logger.debug(f"[RSS_PARSER] Skipping malformed Atom entry: {entry_err}")
                    continue

        return articles

    def ingest_all(self) -> List[RawArticle]:
        """
        Polls all configured feeds, parses content, normalizes records,
        and eliminates duplicate URLs across the harvest.
        """
        all_articles: List[RawArticle] = []
        seen_urls: set = set()

        for feed_cfg in self.feeds:
            name = feed_cfg.get("name", "Unknown Wire")
            url = feed_cfg.get("url")
            domain = feed_cfg.get("domain", "")
            if not url:
                continue

            xml_data = self.fetch_feed_xml(url)
            if not xml_data:
                continue

            parsed_list = self.parse_feed_content(xml_data, default_source_name=name, default_domain=domain)
            for art in parsed_list:
                norm_art = normalize_article(art)
                canonical_url = norm_art.url
                if canonical_url and canonical_url not in seen_urls:
                    seen_urls.add(canonical_url)
                    all_articles.append(norm_art)

        logger.info(f"[RSS_SOURCE] Ingested {len(all_articles)} unique articles across {len(self.feeds)} feeds.")
        return all_articles
