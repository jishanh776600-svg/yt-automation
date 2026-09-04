"""
GDELT 2.0 Document API Source Adapter.
Connects to the GDELT Project's public DOC 2.0 API to harvest real-time global
events, themes, and tone signals without requiring authentication or API keys.
"""
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from intelligence.models import RawArticle
from intelligence.normalization import normalize_article
from core.retry import retry_call

logger = logging.getLogger(__name__)

DEFAULT_GDELT_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"


class GDELTSourceAdapter:
    """Ingests global news articles from the GDELT 2.0 DOC API."""

    def __init__(
        self,
        endpoint: str = DEFAULT_GDELT_ENDPOINT,
        timeout: float = 10.0,
        max_records: int = 30,
        user_agent: str = "AlAmrIntelligence/1.0 (+https://github.com/jishanh776600-svg/yt-automation)"
    ):
        self.endpoint = endpoint
        self.timeout = timeout
        self.max_records = max_records
        self.user_agent = user_agent

    def build_query_url(self, query: str) -> str:
        """Constructs GDELT DOC API request URL."""
        params = {
            "query": query,
            "mode": "artlist",
            "maxrecords": str(self.max_records),
            "format": "json",
            "sort": "DateDesc"
        }
        return f"{self.endpoint}?{urllib.parse.urlencode(params)}"

    def _execute_http_get(self, url: str) -> str:
        """Raw HTTP GET execution wrapped for retry_call."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status != 200:
                raise IOError(f"GDELT returned HTTP {resp.status}")
            raw_bytes = resp.read()
            return raw_bytes.decode("utf-8", errors="replace")

    def fetch_articles(self, query: str = "sourcelang:eng (geopolitics OR military OR sanctions OR NATO OR diplomacy)") -> List[RawArticle]:
        """
        Queries GDELT DOC API, parses JSON, and returns normalized RawArticles.
        Employs exponential backoff and error isolation.
        """
        request_url = self.build_query_url(query)
        logger.info(f"[GDELT_SOURCE] Querying GDELT DOC API: '{query[:60]}...'")

        raw_response: Optional[str] = None
        try:
            raw_response = retry_call(
                lambda: self._execute_http_get(request_url),
                max_retries=2,
                base_delay=1.0,
                max_delay=4.0
            )
        except Exception as e:
            logger.warning(f"[GDELT_SOURCE] API query failed after retries: {e}")
            return []

        if not raw_response or not raw_response.strip():
            return []

        # Parse JSON
        try:
            payload = json.loads(raw_response.strip())
        except Exception as parse_err:
            logger.warning(f"[GDELT_SOURCE] Failed to parse JSON response: {parse_err}")
            return []

        raw_items = payload.get("articles", [])
        if not isinstance(raw_items, list):
            return []

        articles: List[RawArticle] = []
        for item in raw_items:
            try:
                title = item.get("title", "").strip()
                url = item.get("url", "").strip()
                if not title or not url:
                    continue

                domain = item.get("domain", "")
                if not domain:
                    domain = urlparse(url).netloc.replace("www.", "").lower()

                # GDELT seendate format: YYYYMMDDTHHMMSSZ
                seendate_raw = item.get("seendate", "")
                pub_date: Optional[datetime] = None
                if seendate_raw:
                    try:
                        clean_ts = seendate_raw.replace("Z", "")
                        pub_date = datetime.strptime(clean_ts, "%Y%m%dT%H%M%S")
                    except Exception:
                        pass

                source_name = domain.capitalize() if domain else "GDELT Wire"

                art = RawArticle(
                    title=title,
                    summary=f"Reported via {source_name}: {title}",
                    url=url,
                    source_domain=domain.lower(),
                    source_name=source_name,
                    published_at=pub_date,
                    raw_metadata={
                        "sourcecountry": item.get("sourcecountry"),
                        "language": item.get("language")
                    }
                )
                articles.append(normalize_article(art))
            except Exception as item_err:
                logger.debug(f"[GDELT_SOURCE] Skipping article item: {item_err}")
                continue

        logger.info(f"[GDELT_SOURCE] Successfully harvested and normalized {len(articles)} articles.")
        return articles
