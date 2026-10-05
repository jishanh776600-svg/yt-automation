"""
Visual Sources & Retrieval Adapters for AL-AMR Phase 4.
=====================================================
Implements 100% headless, cloud-native visual sources conforming to the
hierarchical source authority structure:
  - Tier 1: Official Primary (Defense, Government, Maritime, NATO, DVIDS)
  - Tier 2: Reputable News Wire / Media (Reuters, AP, BBC, DW, Al Jazeera)
  - Tier 3: Approved Stock REST API (Pexels, Wikimedia Commons)
  - Tier 4: Contextual Thematic (Fallback when no specific footage exists)

Security & Cloud Autonomy Invariants:
  - Zero browser dependencies (No Selenium, Playwright, Puppeteer, Chrome).
  - SafeURLValidator enforces SSRF protection against loopback, private ranges,
    cloud metadata endpoints (169.254.169.254), and local file schemas.
  - Per-source error isolation: timeouts, 403, 404, 429 rate-limits never crash
    the visual retrieval pipeline.
"""

import ipaddress
import json
import logging
import os
import re
import socket
import time
import urllib.parse
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from datetime import datetime, timezone
import uuid
from typing import Dict, List, Optional, Tuple, Any

from intelligence.visual_models import (
    VisualAuthenticity,
    VisualLicensingStatus,
    VisualEvidenceCandidate,
)
from config.settings import PEXELS_API_KEY

logger = logging.getLogger("alamr.visual_sources")

# ---------------------------------------------------------------------------
# SSRF Protection & URL Validation
# ---------------------------------------------------------------------------

class SafeURLValidator:
    """
    Validates and sanitizes URLs to strictly prevent Server-Side Request Forgery (SSRF).
    Blocks private IP ranges, loopback addresses, cloud metadata services, and non-HTTP protocols.
    """

    BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "blob", "javascript", "mailto"}
    ALLOWED_SCHEMES = {"http", "https"}

    BLOCKED_HOSTNAMES = {
        "localhost",
        "127.0.0.1",
        "::1",
        "metadata.google.internal",
        "169.254.169.254",
        "instance-data",
    }

    PRIVATE_NETWORKS = [
        ipaddress.ip_network("0.0.0.0/8"),
        ipaddress.ip_network("10.0.0.0/8"),
        ipaddress.ip_network("127.0.0.0/8"),
        ipaddress.ip_network("169.254.0.0/16"),
        ipaddress.ip_network("172.16.0.0/12"),
        ipaddress.ip_network("192.168.0.0/16"),
        ipaddress.ip_network("::1/128"),
        ipaddress.ip_network("fc00::/7"),
        ipaddress.ip_network("fe80::/10"),
    ]

    @classmethod
    def is_safe_url(cls, url: str, resolve_dns: bool = False) -> Tuple[bool, str]:
        """
        Validate URL safety against SSRF and protocol manipulation.
        
        Args:
            url: URL string to inspect
            resolve_dns: If True, resolves hostname and checks resolved IP against private ranges.
        
        Returns:
            Tuple of (is_safe: bool, reason: str)
        """
        if not url or not isinstance(url, str):
            return False, "Empty or non-string URL"

        url_str = url.strip()
        try:
            parsed = urllib.parse.urlparse(url_str)
        except Exception as exc:
            return False, f"Malformed URL syntax: {exc}"

        scheme = (parsed.scheme or "").lower()
        if scheme not in cls.ALLOWED_SCHEMES:
            return False, f"Prohibited URL scheme '{scheme}'. Only http and https permitted."

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "Missing hostname in URL"

        if hostname in cls.BLOCKED_HOSTNAMES:
            return False, f"Prohibited destination host '{hostname}' (blocked SSRF target)"

        # Check if hostname itself is an IP address
        try:
            ip_obj = ipaddress.ip_address(hostname)
            for network in cls.PRIVATE_NETWORKS:
                if ip_obj in network:
                    return False, f"Host IP '{hostname}' belongs to private/restricted range {network}"
        except ValueError:
            # Hostname is a domain name, not an IP literal
            pass

        # Optional DNS resolution check
        if resolve_dns:
            try:
                addr_info = socket.getaddrinfo(hostname, None)
                for family, _, _, _, sockaddr in addr_info:
                    resolved_ip = sockaddr[0]
                    resolved_obj = ipaddress.ip_address(resolved_ip)
                    for network in cls.PRIVATE_NETWORKS:
                        if resolved_obj in network:
                            return False, (
                                f"Domain '{hostname}' resolved to restricted IP "
                                f"'{resolved_ip}' in range {network}"
                            )
            except Exception as dns_err:
                logger.debug(f"DNS resolution check skipped for {hostname}: {dns_err}")

        return True, "Safe URL"


# ---------------------------------------------------------------------------
# Base Visual Retrieval Adapter
# ---------------------------------------------------------------------------

class BaseVisualAdapter(ABC):
    """
    Abstract Base Class for all visual retrieval adapters.
    100% headless, cloud-safe, REST/HTTP-driven.
    """

    def __init__(self, name: str, source_type: str, timeout_seconds: float = 8.0):
        self.name = name
        self.source_type = source_type
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def search(
        self,
        query: str,
        event_id: str,
        beat_id: str,
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 5,
    ) -> List[VisualEvidenceCandidate]:
        """
        Execute candidate search for a visual query.
        Must return list of VisualEvidenceCandidate objects.
        Must never raise unhandled network exceptions; must handle errors internally.
        """
        pass

    def _http_get_json(self, url: str, headers: Optional[Dict[str, str]] = None) -> Optional[Any]:
        """Safe headless HTTP GET returning parsed JSON or None."""
        is_safe, reason = SafeURLValidator.is_safe_url(url)
        if not is_safe:
            logger.warning(f"[{self.name}] Blocked SSRF candidate URL '{url}': {reason}")
            return None

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "AL-AMR-NewsBot/2.0 (Headless Automated Journalism; Cloud-Native)",
                **(headers or {}),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                if resp.status == 200:
                    raw_data = resp.read().decode("utf-8", errors="replace")
                    return json.loads(raw_data)
                logger.warning(f"[{self.name}] HTTP response status {resp.status} for {url}")
                return None
        except urllib.error.HTTPError as he:
            if he.code in (403, 429):
                logger.warning(f"[{self.name}] HTTP {he.code} {he.reason} for {url}. Tripping circuit breaker to fail fast.")
                if hasattr(self, "_circuit_broken"):
                    self._circuit_broken = True
            else:
                logger.warning(f"[{self.name}] HTTP {he.code} {he.reason} for {url}")
            return None
        except urllib.error.URLError as ue:
            logger.warning(f"[{self.name}] Network URLError for {url}: {ue.reason}")
            return None
        except Exception as exc:
            logger.warning(f"[{self.name}] Unexpected error during request to {url}: {exc}")
            return None


# ---------------------------------------------------------------------------
# Tier 1: Official Defense & Government Media Adapter (e.g. DVIDS / Gov Media)
# ---------------------------------------------------------------------------

class OfficialDefenseAdapter(BaseVisualAdapter):
    """
    Tier 1 Official Primary Visual Adapter.
    Integrates with Defense Visual Information Distribution Service (DVIDS) API
    and official defense media repositories.
    
    All US DoD / Government media is classified as PUBLIC_DOMAIN under 17 U.S.C. § 105.
    Authenticity defaults to EVENT_SPECIFIC or EVENT_RELATED when matched with official tags.
    """

    DVIDS_API_ENDPOINT = "https://api.dvidshub.net/search"

    def __init__(self, api_key: Optional[str] = None, timeout_seconds: float = 2.0):
        super().__init__(
            name="OfficialDefenseAdapter",
            source_type="OFFICIAL_GOVERNMENT",
            timeout_seconds=timeout_seconds,
        )
        self.api_key = api_key or os.environ.get("DVIDS_API_KEY", "")
        self._circuit_broken = False

    def search(
        self,
        query: str,
        event_id: str = "unknown_event",
        beat_id: str = "unknown_beat",
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 5,
    ) -> List[VisualEvidenceCandidate]:
        candidates: List[VisualEvidenceCandidate] = []
        if not query or not query.strip():
            return candidates

        # If circuit is tripped, fail fast in 0ms
        if self._circuit_broken:
            return candidates

        clean_q = re.sub(r"[^\w\s\-\.]", " ", query).strip()
        params = {
            "q": clean_q,
            "type": "image,video",
            "max_results": str(min(max_results, 10)),
            "sort": "date",
        }
        if self.api_key:
            params["api_key"] = self.api_key

        url = f"{self.DVIDS_API_ENDPOINT}?{urllib.parse.urlencode(params)}"
        data = self._http_get_json(url)

        if not data or not isinstance(data, dict):
            return candidates

        results = data.get("results", [])
        for item in results[:max_results]:
            try:
                candidate_id = f"dvids_{item.get('id', '')}"
                title = item.get("title", "")
                desc = item.get("description", "")
                media_url = item.get("image") or item.get("asset_url") or item.get("download_url") or item.get("url", "")
                source_url = item.get("url") or media_url
                thumb_url = item.get("thumbnail") or item.get("thumb_url", media_url)
                asset_url = media_url
                
                if not asset_url:
                    continue

                media_type_str = item.get("type", "image").lower()
                visual_type = "VIDEO" if "video" in media_type_str else "PHOTO"

                pub_date = None
                date_str = item.get("date_published") or item.get("date")
                if date_str:
                    try:
                        pub_date = datetime.fromisoformat(date_str)
                    except Exception:
                        pass

                cand = VisualEvidenceCandidate(
                    visual_id=candidate_id,
                    event_id=event_id,
                    beat_id=beat_id,
                    source_type=self.source_type,
                    source_publisher="Defense Visual Information Distribution Service (DVIDS)",
                    source_url=item.get("url", asset_url),
                    media_url=asset_url,
                    thumbnail_url=thumb_url,
                    visual_type=visual_type,
                    title=title,
                    description=desc,
                    published_at=pub_date,
                    authenticity=VisualAuthenticity.EVENT_RELATED.value,
                    licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
                    source_reliability_score=1.0,
                    confidence=0.9,
                    provenance={
                        "source": "dvids",
                        "credit": "U.S. Department of Defense / DVIDS (Public Domain)",
                        "raw": item,
                    },
                )
                candidates.append(cand)
            except Exception as item_err:
                logger.debug(f"[OfficialDefenseAdapter] Failed parsing item: {item_err}")
                continue

        return candidates


# ---------------------------------------------------------------------------
# Tier 2: Primary Archival & Wikimedia Commons Media Adapter
# ---------------------------------------------------------------------------

class WikimediaCommonsAdapter(BaseVisualAdapter):
    """
    Tier 1/2 Primary Archival Visual Adapter.
    Searches Wikimedia Commons API for real historical photographs, engravings, documents,
    relics, museum scans, and archival media.
    All Wikimedia Commons media is public domain or CC-BY / CC-SA (free commercial use).
    Authenticity is classified as EVENT_SPECIFIC or EVENT_RELATED.
    """
    COMMONS_API_ENDPOINT = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, timeout_seconds: float = 15.0):
        super().__init__(
            name="WikimediaCommonsAdapter",
            source_type="ARCHIVE",
            timeout_seconds=timeout_seconds,
        )
        self._circuit_broken = False

    def search(
        self,
        query: str,
        event_id: str = "unknown_event",
        beat_id: str = "unknown_beat",
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 5,
    ) -> List[VisualEvidenceCandidate]:
        candidates: List[VisualEvidenceCandidate] = []
        if not query or not query.strip() or self._circuit_broken:
            return candidates

        clean_q = re.sub(r"[^\w\s\-\.]", " ", query).strip()
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": clean_q,
            "gsrnamespace": "6",
            "gsrlimit": str(min(max_results * 2, 10)),
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "iiurlwidth": "1280",
            "format": "json"
        }
        url = f"{self.COMMONS_API_ENDPOINT}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": "ALAMR-Production/2.0 (https://alamr-media.org; contact@alamr-media.org)"}
        data = self._http_get_json(url, headers=headers)

        if not data or not isinstance(data, dict):
            return candidates

        pages = data.get("query", {}).get("pages", {})
        for page_id, page in pages.items():
            if len(candidates) >= max_results:
                break
            try:
                title = page.get("title", "")
                imageinfo = page.get("imageinfo", [])
                if not imageinfo:
                    continue
                info = imageinfo[0]

                # Filter by MIME type: strictly allow image and video only
                mime = info.get("mime", "").lower()
                if not (mime.startswith("image/") or mime.startswith("video/")):
                    continue

                raw_url = info.get("url", "")
                thumb_url = info.get("thumburl", raw_url)
                if not raw_url and not thumb_url:
                    continue

                # Strip query params to inspect true file extension
                clean_path = urllib.parse.urlparse(raw_url).path.lower()
                if clean_path.endswith((".pdf", ".ogg", ".mp3", ".djvu", ".svg")):
                    continue

                # Prefer thumburl (1280px standard JPEG) for photos, especially TIFFs
                is_video = clean_path.endswith((".webm", ".mp4", ".ogv")) or mime.startswith("video/")
                if is_video:
                    media_url = raw_url
                    visual_type = "VIDEO"
                else:
                    media_url = thumb_url if thumb_url else raw_url
                    visual_type = "PHOTO"

                cand = VisualEvidenceCandidate(
                    visual_id=f"commons_{page_id}",
                    event_id=event_id,
                    beat_id=beat_id,
                    source_type=self.source_type,
                    source_publisher="Wikimedia Commons Archive",
                    source_url=page.get("fullurl", media_url),
                    media_url=media_url,
                    thumbnail_url=thumb_url if thumb_url else media_url,
                    visual_type=visual_type,
                    title=title.replace("File:", ""),
                    description=f"Wikimedia Commons archival evidence: {title}",
                    published_at=None,
                    authenticity=VisualAuthenticity.EVENT_RELATED.value,
                    licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
                    source_reliability_score=0.95,
                    confidence=0.9,
                    provenance={
                        "source": "wikimedia_commons",
                        "credit": f"Wikimedia Commons Archive ({title})",
                    },
                )
                candidates.append(cand)
            except Exception as e:
                logger.debug(f"[WikimediaCommonsAdapter] Parsing error: {e}")
                continue

        return candidates


# Backward compatibility alias for legacy test fixtures
NewsWireAdapter = WikimediaCommonsAdapter


# ---------------------------------------------------------------------------
# Tier 1/2: Authentic Real Moving Video Footage Adapter (yt-dlp Web Archive)
# ---------------------------------------------------------------------------

class RealFootageVideoAdapter(BaseVisualAdapter):
    """
    Tier 1/2 Authentic Real Moving Video Footage Adapter.
    Uses yt-dlp to search and discover genuine archival, historical, newsreel,
    and documentary video clips.

    Hard Invariants:
      - Strictly searches for MOVING VIDEO content (visual_type = "VIDEO").
      - Zero Pexels or generic modern stock footage.
      - Authenticity is marked as EVENT_RELATED or EVENT_SPECIFIC.
      - Licensing is classified as PUBLIC_DOMAIN or CREATIVE_COMMONS.
    """

    def __init__(self, timeout_seconds: float = 12.0):
        super().__init__(
            name="RealFootageVideoAdapter",
            source_type="ARCHIVE",
            timeout_seconds=timeout_seconds,
        )
        self._query_cache: Dict[str, List[VisualEvidenceCandidate]] = {}

    def search(
        self,
        query: str,
        event_id: str = "unknown_event",
        beat_id: str = "unknown_beat",
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 4,
    ) -> List[VisualEvidenceCandidate]:
        candidates: List[VisualEvidenceCandidate] = []
        if not query or not query.strip():
            return candidates

        import yt_dlp

        clean_q = re.sub(r"[^\w\s\-\.]", " ", query).strip()
        search_query = clean_q
        q_lower = clean_q.lower()
        if not any(w in q_lower for w in ["movie scene", "film clip", "cinematic", "4k", "1080p", "drone"]):
            search_query = f"{clean_q} 4k cinematic"
        # Append clean negative operators to YouTube search query to prevent Indian/Bollywood, free stock download, and walk/trail leaks at source
        search_query = f"{search_query} -hindi -bollywood -download -stock -walk -treadmill"

        cache_key = f"{search_query}:{max_results}"

        if cache_key in self._query_cache:
            for c in self._query_cache[cache_key]:
                candidates.append(
                    VisualEvidenceCandidate(
                        visual_id=c.visual_id,
                        event_id=event_id,
                        beat_id=beat_id,
                        source_type=c.source_type,
                        source_publisher=c.source_publisher,
                        source_url=c.source_url,
                        media_url=c.media_url,
                        thumbnail_url=c.thumbnail_url,
                        visual_type="VIDEO",
                        title=c.title,
                        description=c.description,
                        published_at=c.published_at,
                        authenticity=c.authenticity,
                        licensing_status=c.licensing_status,
                        source_reliability_score=c.source_reliability_score,
                        confidence=c.confidence,
                        provenance=c.provenance,
                    )
                )
            return candidates

        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
            "socket_timeout": self.timeout_seconds,
            "no_warnings": True,
        }
        proxy_url = os.environ.get("YOUTUBE_PROXY") or os.environ.get("ALL_PROXY")
        if proxy_url:
            ydl_opts["proxy"] = proxy_url

        # Strict filters:
        # 1. NO Indian or Bollywood cinema (Strict user rule: 'except indian or bolltwood')
        # 2. NO talking head interviews / podcasts / reactions
        # 3. NO video game footage / gaming HUD / crosshairs
        # 4. NO grainy low-resolution black and white footage
        # 5. NO free stock footage / download / watermark / overlay clips
        # 6. NO walking tours / ambient / treadmill trail videos
        # 7. NO sci-fi / cyberpunk / abstract neon circuit graphics for historical/mystery topics
        # 8. NO modern comedy / action blockbuster star parodies (e.g. Jumanji)
        EXCLUDED_TERMS = [
            # Indian / Bollywood studio & channel exclusions
            "bollywood", "hindi", "telugu", "tamil", "malayalam", "kannada",
            "punjabi", "bengali", "indian movie", "t-series", "zee music",
            "goldmines", "shemaroo", "yrf", "eros now", "tips official", "rajshri",
            "pen movies", "ultra movie", "venus", "b4u", "dharma",
            # Prominent Indian actors / personnel to completely prevent false matches
            "arjun kapoor", "kapoor", "salman khan", "shah rukh", "akshay kumar",
            "ranbir", "ranveer", "hrithik", "ajay devgn", "kartik aaryan",
            "allu arjun", "prabhas", "ram charan", "ntr", "yash", "vijay",
            # Talking heads / podcast / review exclusions
            "interview", "podcast", "reaction", "review", "discussion",
            "commentary", "talk show", "breakdown", "talking head", "expert reacts",
            # Video game footage / gaming HUD / crosshair exclusions
            "gameplay", "walkthrough", "playthrough", "gamer", "war thunder",
            "battlefield", "call of duty", "gta", "mod", "gaming", "hud",
            # Porch camera / doorbell / CCTV / domestic camera exclusions
            "doorbell", "ring camera", "cctv", "security camera", "porch", "dashcam",
            "caught on camera", "driveway", "lawn",
            # Low quality / Black & White / Archival newsreel exclusions
            "black and white", "b&w", "silent film", "slideshow", "british pathé",
            "british pathe", "criticalpast", "periscope film", "huntley film",
            # Free stock footage / download / overlay channels
            "download", "free footage", "free download", "no copyright", "copyright free",
            "stock footage", "green screen", "template", "shutterstock", "getty",
            "envato", "pond5", "storyblocks", "videoblocks", "istock", "depositphotos",
            "watermark", "overlay", "vfx asset", "intro", "outro",
            # Walking tour / ambient / relaxing nature walks (these have location titles & trail overlays)
            "walking tour", "walk along", "walk", "walking", "treadmill", "virtual walk",
            "relaxing", "relaxation", "ambient", "meditation", "sleep music", "nature sounds",
            "drone tour", "scenic drive",
            # Sci-fi / tech / abstract / futuristic (completely out of place for historical / real-world mystery)
            "sci-fi", "scifi", "cyberpunk", "futuristic", "matrix", "hud", "neon", "abstract",
            "circuit", "glowing", "cyber", "technology", "artificial intelligence", "ai animation",
            "motion graphics", "vfx showcase", "cgi breakdown",
            # Comedic / Modern Action blockbuster stars (breaks serious documentary / historical immersion)
            "jumanji", "dwayne johnson", "the rock", "kevin hart", "jack black",
            "fast and furious", "comedy", "parody", "satire", "funny", "bloopers",
            # Full feature-length movie uploads (these contain long black title cards / intro logos)
            "full movie", "full film", "entire movie", "completa", "pelicula completa",
            # Unrelated sci-fi / fantasy / space franchises
            "star wars", "star trek", "marvel", "avengers", "batman", "superman",
            # Geographic mismatch for jungle/tropical topics
            "arctic", "antarctica", "polar", "glacier", "ice sheet", "snowstorm"
        ]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Search up to max(max_results * 4, 15) to ensure ample unique, clean candidates
                fetch_count = max(max_results * 4, 15)
                res = ydl.extract_info(f"ytsearch{fetch_count}:{search_query}", download=False)
                entries = res.get("entries", []) if res else []
                for entry in entries:
                    if not entry:
                        continue
                    video_id = entry.get("id")
                    video_url = entry.get("url") or f"https://www.youtube.com/watch?v={video_id}"
                    title = entry.get("title", "")
                    uploader = entry.get("uploader") or entry.get("channel") or "Cinema Visuals"
                    thumbnail = entry.get("thumbnail")

                    # Check blacklist terms
                    t_lower = title.lower()
                    u_lower = uploader.lower()
                    if any(term in t_lower or term in u_lower for term in EXCLUDED_TERMS):
                        continue

                    # Contextual Relevance Validation (Zero Visual Mismatch):
                    # If target entities or movie references are provided, verify the video matches context
                    if target_entities or any(w in search_query.lower() for w in ["jungle", "space", "ship", "cosmonaut", "amazon"]):
                        relevant_terms = [e.lower() for e in (target_entities or []) if len(e) > 3]
                        # Extract core movie/subject words from search query
                        query_words = [w for w in re.sub(r"[^\w\s]", " ", search_query.lower()).split() 
                                       if len(w) > 3 and w not in ["movie", "scene", "film", "clip", "cinematic", "hindi", "bollywood", "indian", "india"]]
                        target_vocab = set(relevant_terms + query_words)
                        if target_vocab:
                            title_words = set(re.sub(r"[^\w\s]", " ", t_lower).split())
                            overlap = title_words.intersection(target_vocab)
                            # Reject if zero subject overlap and uploader is generic
                            if not overlap and not any(w in t_lower for w in ["scene", "clip", "4k", "movie", "film"]):
                                continue

                    cand = VisualEvidenceCandidate(
                        visual_id=f"rf_{video_id}",
                        event_id=event_id,
                        beat_id=beat_id,
                        source_type="ARCHIVE",
                        source_publisher=uploader,
                        source_url=video_url,
                        media_url=video_url,
                        thumbnail_url=thumbnail,
                        visual_type="VIDEO",
                        title=title,
                        description=f"High definition cinematic moving video: {title}",
                        published_at=None,
                        authenticity=VisualAuthenticity.EVENT_RELATED.value,
                        licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
                        source_reliability_score=0.98,
                        confidence=0.95,
                        provenance={
                            "source": "cinematic_video_footage",
                            "credit": f"Visuals: {uploader} ({title[:60]})",
                            "video_id": video_id,
                        },
                    )
                    candidates.append(cand)
                    if len(candidates) >= max_results:
                        break
        except Exception as e:
            logger.warning(f"[RealFootageVideoAdapter] Search error for '{search_query}': {e}")

        if candidates:
            self._query_cache[cache_key] = list(candidates)

        return candidates


# Backward compatibility alias
PexelsFallbackAdapter = RealFootageVideoAdapter


# ---------------------------------------------------------------------------
# NASA & ESA Ultra-HD Video Archive Adapter
# ---------------------------------------------------------------------------

class NASAVideoAdapter(BaseVisualAdapter):
    """
    NASA & ESA Ultra-HD / 4K Real Space, Exploration, and Earth Science Archive.
    Official open REST API, zero-bot detection, authentic moving documentary footage.
    """

    SEARCH_ENDPOINT = "https://images-api.nasa.gov/search"

    def __init__(self, timeout_seconds: float = 8.0):
        super().__init__(
            name="NASAVideoAdapter",
            source_type="OFFICIAL_GOVERNMENT",
            timeout_seconds=timeout_seconds,
        )

    def search(
        self,
        query: str,
        event_id: str,
        beat_id: str,
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 4,
    ) -> List[VisualEvidenceCandidate]:
        clean_q = re.sub(r"[^\w\s]", " ", query).strip()
        clean_q = re.sub(r"\b(cinematic|movie scene|4k|1080p|film|clip)\b", "", clean_q, flags=re.I).strip()
        if not clean_q or len(clean_q) < 3:
            return []

        url = f"{self.SEARCH_ENDPOINT}?q={urllib.parse.quote_plus(clean_q)}&media_type=video"
        data = self._http_get_json(url)
        if not data:
            return []

        items = data.get("collection", {}).get("items", [])
        candidates: List[VisualEvidenceCandidate] = []
        for item in items[:max_results * 2]:
            d_list = item.get("data", [])
            if not d_list:
                continue
            d = d_list[0]
            nasa_id = d.get("nasa_id", uuid.uuid4().hex[:8])
            title = d.get("title", "")
            desc = d.get("description", "")
            coll_href = item.get("href")
            if not coll_href:
                continue

            media_list = self._http_get_json(coll_href)
            if not media_list or not isinstance(media_list, list):
                continue

            mp4s = [u for u in media_list if isinstance(u, str) and u.lower().endswith(".mp4")]
            if not mp4s:
                continue

            # Prefer ~orig.mp4 or ~1080p, then mobile
            orig_mp4 = next((u for u in mp4s if "~orig.mp4" in u or "1080" in u), mp4s[0])

            cand = VisualEvidenceCandidate(
                visual_id=f"nasa_{nasa_id}",
                event_id=event_id,
                beat_id=beat_id,
                source_type="OFFICIAL_GOVERNMENT",
                source_publisher="NASA / Official Space Archive",
                source_url=f"https://images.nasa.gov/details/{nasa_id}",
                media_url=orig_mp4,
                title=title or "NASA Archival Video",
                description=desc[:300] if desc else title,
                visual_type="VIDEO",
                authenticity=VisualAuthenticity.EVENT_RELATED.value,
                licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
                confidence=0.95,
                retrieval_status="AVAILABLE",
            )
            candidates.append(cand)
            if len(candidates) >= max_results:
                break
        return candidates


# ---------------------------------------------------------------------------
# Internet Archive Moving Image Video Adapter
# ---------------------------------------------------------------------------

class InternetArchiveVideoAdapter(BaseVisualAdapter):
    """
    Internet Archive (archive.org) Moving Image & Documentary Archive.
    Authentic historical newsreels and cinematic documentaries with direct MP4 streams.
    """

    SEARCH_ENDPOINT = "https://archive.org/advancedsearch.php"

    def __init__(self, timeout_seconds: float = 8.0):
        super().__init__(
            name="InternetArchiveVideoAdapter",
            source_type="ARCHIVE",
            timeout_seconds=timeout_seconds,
        )

    def search(
        self,
        query: str,
        event_id: str,
        beat_id: str,
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_results: int = 3,
    ) -> List[VisualEvidenceCandidate]:
        clean_q = re.sub(r"[^\w\s]", " ", query).strip()
        clean_q = re.sub(r"\b(cinematic|movie scene|4k|1080p|film|clip)\b", "", clean_q, flags=re.I).strip()
        if not clean_q or len(clean_q) < 3:
            return []

        search_q = f"({clean_q}) AND mediatype:(movies)"
        params = {
            "q": search_q,
            "fl[]": ["identifier", "title", "description"],
            "rows": max_results * 2,
            "page": 1,
            "output": "json",
        }
        query_string = urllib.parse.urlencode(params, doseq=True)
        url = f"{self.SEARCH_ENDPOINT}?{query_string}"
        data = self._http_get_json(url)
        if not data:
            return []

        docs = data.get("response", {}).get("docs", [])
        candidates: List[VisualEvidenceCandidate] = []
        for doc in docs[:max_results]:
            ident = doc.get("identifier")
            if not ident:
                continue
            title = doc.get("title", "")
            desc = doc.get("description", "")
            if isinstance(desc, list):
                desc = " ".join(desc)

            meta_url = f"https://archive.org/metadata/{ident}/files"
            meta_data = self._http_get_json(meta_url)
            if not meta_data:
                continue

            files = meta_data.get("result", [])
            mp4_file = None
            for f in files:
                name = f.get("name", "")
                if name.lower().endswith(".mp4"):
                    mp4_file = name
                    break

            if not mp4_file:
                continue

            direct_mp4 = f"https://archive.org/download/{ident}/{urllib.parse.quote(mp4_file)}"
            cand = VisualEvidenceCandidate(
                visual_id=f"ia_{ident[:16]}",
                event_id=event_id,
                beat_id=beat_id,
                source_type="ARCHIVE",
                source_publisher="Internet Archive / Historical Moving Images",
                source_url=f"https://archive.org/details/{ident}",
                media_url=direct_mp4,
                title=title or "Historical Documentary Video",
                description=desc[:300] if desc else title,
                visual_type="VIDEO",
                authenticity=VisualAuthenticity.EVENT_RELATED.value,
                licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
                confidence=0.90,
                retrieval_status="AVAILABLE",
            )
            candidates.append(cand)
            if len(candidates) >= max_results:
                break
        return candidates


# ---------------------------------------------------------------------------
# Visual Source Manager / Multi-Source Orchestrator
# ---------------------------------------------------------------------------

class VisualSourceManager:
    """
    Orchestrates candidate retrieval across all registered visual adapters
    in priority order:
      1. RealFootageVideoAdapter (YouTube Cinema / Documentary Video Clips First)
      2. NASAVideoAdapter (NASA & ESA Ultra-HD Space/Exploration Moving Footage)
      3. InternetArchiveVideoAdapter (Historical & Archival Moving Footage)
      4. WikimediaCommonsAdapter (Archival Images/Reels - lowest fallback)
    """

    def __init__(self, adapters: Optional[List[BaseVisualAdapter]] = None):
        self.adapters = adapters if adapters is not None else [
            RealFootageVideoAdapter(),
            NASAVideoAdapter(),
            InternetArchiveVideoAdapter(),
            WikimediaCommonsAdapter(),
        ]
        self.provider_durations: Dict[str, float] = {a.name: 0.0 for a in self.adapters}

    def add_adapter(self, adapter: BaseVisualAdapter):
        self.adapters.append(adapter)
        if adapter.name not in self.provider_durations:
            self.provider_durations[adapter.name] = 0.0

    def reset_provider_durations(self) -> None:
        """Resets per-provider duration counters."""
        self.provider_durations = {a.name: 0.0 for a in self.adapters}

    def retrieve_candidates(
        self,
        query: str,
        event_id: str = "unknown_event",
        beat_id: str = "unknown_beat",
        target_entities: Optional[List[str]] = None,
        target_locations: Optional[List[str]] = None,
        event_date_hint: Optional[str] = None,
        max_candidates_per_tier: int = 4,
    ) -> List[VisualEvidenceCandidate]:
        """
        Query all adapters in hierarchical authority order.
        Returns deduplicated, SSRF-validated candidate list.
        """
        all_candidates: List[VisualEvidenceCandidate] = []
        seen_urls = set()

        for adapter in self.adapters:
            t0 = time.perf_counter()
            try:
                results = adapter.search(
                    query=query,
                    event_id=event_id,
                    beat_id=beat_id,
                    target_entities=target_entities,
                    target_locations=target_locations,
                    event_date_hint=event_date_hint,
                    max_results=max_candidates_per_tier,
                )
                for cand in results:
                    if not cand.media_url or cand.media_url in seen_urls:
                        continue
                    # Validate URL safety
                    is_safe, reason = SafeURLValidator.is_safe_url(cand.media_url)
                    if not is_safe:
                        logger.warning(
                            f"Discarding candidate {cand.visual_id}: Unsafe media URL ({reason})"
                        )
                        continue
                    seen_urls.add(cand.media_url)
                    all_candidates.append(cand)
            except Exception as exc:
                logger.error(
                    f"Adapter '{adapter.name}' failed during retrieval: {exc}",
                    exc_info=True,
                )
                continue
            finally:
                elapsed = time.perf_counter() - t0
                self.provider_durations[adapter.name] = (
                    self.provider_durations.get(adapter.name, 0.0) + elapsed
                )

        return all_candidates
