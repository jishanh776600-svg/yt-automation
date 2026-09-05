"""
Article Text and Metadata Extraction using Trafilatura.
Strips boilerplate, ads, cookie notices, and navigation.
Handles network failures, timeouts, and extraction errors gracefully.
Never fabricates content.
"""
import logging
from dataclasses import dataclass
from typing import Optional
import requests
import trafilatura

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10  # seconds
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


@dataclass
class ExtractionResult:
    text: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    date: Optional[str] = None
    extraction_status: str = "PENDING"  # SUCCESS, FAILED, EMPTY, SKIPPED
    retrieval_status: str = "SUCCESS"    # SUCCESS, FAILED, TIMEOUT, HTTP_ERROR
    error_message: Optional[str] = None


class ArticleExtractor:
    """Extracts clean article text and metadata from URLs using Trafilatura."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def extract_from_html(self, html: str, url: Optional[str] = None) -> ExtractionResult:
        """Extracts content directly from raw HTML string."""
        if not html or not html.strip():
            return ExtractionResult(
                extraction_status="EMPTY",
                retrieval_status="SUCCESS",
                error_message="Empty HTML content"
            )

        try:
            bare = trafilatura.bare_extraction(
                html,
                url=url,
                include_comments=False,
                include_tables=False,
                no_fallback=False
            )

            bare_text = getattr(bare, "text", None) if bare else (bare.get("text") if isinstance(bare, dict) else None)
            bare_title = getattr(bare, "title", None) if bare else (bare.get("title") if isinstance(bare, dict) else None)
            bare_author = getattr(bare, "author", None) if bare else (bare.get("author") if isinstance(bare, dict) else None)
            bare_date = getattr(bare, "date", None) if bare else (bare.get("date") if isinstance(bare, dict) else None)

            if bare_text and len(bare_text.strip()) > 40:
                return ExtractionResult(
                    text=bare_text.strip(),
                    title=bare_title,
                    author=bare_author,
                    date=bare_date,
                    extraction_status="SUCCESS",
                    retrieval_status="SUCCESS"
                )

            # Fallback to standard extract if bare_extraction yielded minimal
            fallback_text = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=False
            )

            if fallback_text and len(fallback_text.strip()) > 40:
                # Try to extract metadata if bare didn't have it
                meta = None
                try:
                    meta = trafilatura.extract_metadata(html, default_url=url)
                except Exception:
                    pass
                return ExtractionResult(
                    text=fallback_text.strip(),
                    title=bare_title or (meta.title if meta else None),
                    author=bare_author or (meta.author if meta else None),
                    date=bare_date or (meta.date if meta else None),
                    extraction_status="SUCCESS",
                    retrieval_status="SUCCESS"
                )

            return ExtractionResult(
                extraction_status="EMPTY",
                retrieval_status="SUCCESS",
                error_message="No substantial article body found"
            )
        except Exception as e:
            logger.warning(f"Trafilatura extraction failed: {e}")
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="SUCCESS",
                error_message=str(e)
            )

    def extract_from_url(self, url: str) -> ExtractionResult:
        """
        Fetches web page at URL and extracts clean article text.
        Guarantees failure isolation: never raises uncaught network exceptions.
        """
        if not url:
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="FAILED",
                error_message="Missing URL"
            )

        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code in (401, 403):
                return ExtractionResult(
                    extraction_status="FAILED",
                    retrieval_status="BLOCKED",
                    error_message=f"Access blocked (HTTP {resp.status_code})"
                )
            elif resp.status_code >= 400:
                return ExtractionResult(
                    extraction_status="FAILED",
                    retrieval_status="HTTP_ERROR",
                    error_message=f"HTTP status {resp.status_code}"
                )

            return self.extract_from_html(resp.text, url=url)

        except requests.exceptions.SSLError as e:
            logger.warning(f"SSL error extracting {url}: {e}")
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="SSL_ERROR",
                error_message=f"SSL verification error: {e}"
            )
        except requests.exceptions.Timeout:
            logger.warning(f"Extraction timeout for {url}")
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="TIMEOUT",
                error_message="Request timed out"
            )
        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error extracting {url}: {e}")
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="FAILED",
                error_message=f"Network error: {type(e).__name__}"
            )
        except Exception as e:
            logger.warning(f"Unexpected error extracting {url}: {e}")
            return ExtractionResult(
                extraction_status="FAILED",
                retrieval_status="FAILED",
                error_message=str(e)
            )
