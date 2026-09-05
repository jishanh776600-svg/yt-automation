"""
GDELT 2.0 Global Event Discovery Adapter.
Queries GDELT 2.0 DOC API for real-time global geopolitical events.
Acts as a discovery firehose with complete failure isolation.
"""
import logging
from typing import List, Dict, Any, Optional
import requests
from intelligence.scoring import SourceType

logger = logging.getLogger(__name__)

GDELT_DOC_API_ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
DEFAULT_GDELT_QUERY = "(geopolitics OR military OR conflict OR sanctions OR diplomacy OR defense)"


class GDELTAdapter:
    """Adapter for GDELT 2.0 DOC API with resilient network error handling."""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "AL-AMR-NewsIngestion/1.0 (geopolitical_research@pipeline.ai)"
        })

    def fetch_articles(
        self,
        query: str = DEFAULT_GDELT_QUERY,
        timespan: str = "24h",
        limit: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Queries GDELT DOC API for articles in the last 24 hours.
        Fails gracefully: if GDELT is down or network fails, returns empty list without raising.
        """
        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(min(limit, 100)),
            "format": "json",
            "timespan": timespan
        }

        try:
            resp = self.session.get(GDELT_DOC_API_ENDPOINT, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logger.warning(f"GDELT API returned status code {resp.status_code}")
                return []

            data = resp.json()
            raw_articles = data.get("articles", [])
            results = []

            for item in raw_articles:
                url = item.get("url")
                title = item.get("title")
                if not url or not title:
                    continue

                domain_val = item.get("domain")
                if not domain_val:
                    try:
                        from urllib.parse import urlparse
                        domain_val = urlparse(url).netloc.lower()
                        if domain_val.startswith("www."):
                            domain_val = domain_val[4:]
                    except Exception:
                        domain_val = "GDELT Global News"

                results.append({
                    "title": title.strip(),
                    "url": url.strip(),
                    "source_name": domain_val or "GDELT Global News",
                    "source_type": SourceType.AGGREGATOR.value,
                    "published_raw": item.get("seendate"),
                    "language": item.get("language") or None,
                    "raw_feed_text": None,
                    "summary": None
                })

            logger.info(f"GDELT 2.0 discovery yielded {len(results)} candidate articles.")
            return results

        except requests.exceptions.Timeout:
            logger.warning("GDELT API request timed out. Continuing without GDELT.")
            return []
        except requests.exceptions.RequestException as e:
            logger.warning(f"GDELT API network error ({e}). Continuing without GDELT.")
            return []
        except ValueError as e:
            logger.warning(f"GDELT API invalid JSON response ({e}). Continuing without GDELT.")
            return []
        except Exception as e:
            logger.warning(f"Unexpected error in GDELT adapter ({e}). Continuing without GDELT.")
            return []
