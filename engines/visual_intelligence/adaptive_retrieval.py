"""
Adaptive Real-Time Retrieval + Streaming Ingestion Engine (Step 7/8).
====================================================================
Orchestrates:
  1. RetrievalBudget: Configurable timeouts, retry caps, byte limits, candidate bounds.
  2. AdaptiveQueryExpander: Context-aware, scene-specific query generation leveraging VisualIntent.
  3. StagedStreamIngester: Progressive chunk streaming, header inspection, early magic-byte & HTML rejection.
  4. ParallelVideoRetriever: Safe multi-threaded provider retrieval with failure isolation & early success.
  5. RetrievalTelemetryCollector: Internal structured diagnostics for auditing retrieval performance.

Invariants:
  - VIDEO ONLY: Zero tolerance for images, static canvases, slides, or disguised assets.
  - Fail-Closed: Safe failure if no authentic video passes physical validation.
  - Non-Stock Priority: MOVIE / INTERNET_REAL / ARCHIVAL > STOCK fallback.
  - Relevance > Speed/Variety: Semantic accuracy is never sacrificed.
"""
import os
import re
import time
import shutil
import logging
import requests
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

from config.settings import (
    ASSETS_CACHE_DIR,
    RETRIEVAL_PROVIDER_TIMEOUT,
    RETRIEVAL_TOTAL_TIMEOUT,
    RETRIEVAL_DOWNLOAD_TIMEOUT,
    RETRIEVAL_MAX_DOWNLOAD_BYTES,
    RETRIEVAL_MAX_RETRIES,
    RETRIEVAL_MAX_EXPANSIONS,
)
from core.media_validator import (
    PhysicalVideoValidator,
    PROHIBITED_MIME_TYPES,
    IMAGE_MAGIC_SIGNATURES,
    VIDEO_ONLY
)
from .models import (
    SourceType,
    NormalizedVideoCandidate,
    VisualCandidate,
    VisualIntent,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Retrieval Budget Configuration
# ==============================================================================
@dataclass
class RetrievalBudget:
    """Configurable budget parameters for visual retrieval and ingestion."""
    provider_timeout: float = field(default_factory=lambda: RETRIEVAL_PROVIDER_TIMEOUT)
    total_scene_timeout: float = field(default_factory=lambda: RETRIEVAL_TOTAL_TIMEOUT)
    download_timeout: float = field(default_factory=lambda: RETRIEVAL_DOWNLOAD_TIMEOUT)
    max_retries: int = field(default_factory=lambda: RETRIEVAL_MAX_RETRIES)
    max_candidates_per_provider: int = 4
    max_download_bytes: int = field(default_factory=lambda: RETRIEVAL_MAX_DOWNLOAD_BYTES)
    max_query_expansions: int = field(default_factory=lambda: RETRIEVAL_MAX_EXPANSIONS)
    early_success_threshold: float = 0.60
    enable_early_magic_check: bool = True
    enable_parallel: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ==============================================================================
# 2. Adaptive Query Expander
# ==============================================================================
class AdaptiveQueryExpander:
    """
    Deterministically generates context-aware, scene-specific search query variants
    leveraging structured VisualIntent attributes without random keyword spam.
    Expands dynamically along multiple concrete dimensions:
      - Entity synonyms / alternate phrasing
      - Action synonyms (e.g., sinking, bombardment, evacuation, collapse, advancing)
      - Environment / setting terminology (e.g., naval harbor, high seas, bunker, urban)
      - Event terminology (e.g., disaster, crisis, operation, treaty, incident)
      - Archival / authentic documentary phrasing
    Ensures ENTITY + ACTION + EVENT + CONTEXT structure and rejects generic terms alone.
    """

    GENERIC_TERMS: Set[str] = {
        "ship", "water", "war", "history", "ocean", "people",
        "movie", "video", "footage", "clip", "event", "scene", "historical",
        "shot", "background", "man", "woman", "guy", "stuff", "thing"
    }

    ACTION_SYNONYMS: Dict[str, List[str]] = {
        "sink": ["sinking", "going down", "capsizing", "submerging"],
        "bombard": ["naval bombardment", "artillery shelling", "naval gunfire"],
        "bomb": ["bombardment", "aerial bombing", "air strike", "explosion"],
        "fire": ["firing artillery", "gunfire", "firing broadside", "shooting"],
        "march": ["marching troops", "soldiers advancing", "infantry column", "military parade"],
        "retreat": ["retreating", "evacuating troops", "tactical withdrawal"],
        "flee": ["evacuation", "refugees fleeing", "mass departure"],
        "rescue": ["rescue operation", "emergency evacuation", "saving survivors"],
        "collapse": ["structural collapse", "building crumbling", "destruction aftermath"],
        "protest": ["mass protest", "demonstration", "crowd rally", "civil unrest"],
        "strike": ["airstrike", "missile strike", "precision attack"],
        "attack": ["military offensive", "assault operation", "ambush"],
        "crash": ["crash wreckage", "collision aftermath", "wreckage site"],
        "sign": ["treaty signing ceremony", "official signing", "diplomatic accord"],
        "speech": ["public address", "press conference", "announcing statement"],
        "celebrate": ["victory celebration", "crowds cheering", "liberation parade"],
        "patrol": ["naval patrol", "security patrol", "reconnaissance mission"],
        "sail": ["warship underway", "naval fleet sailing", "at sea navigation"],
        "fly": ["flight take off", "aerial combat flight", "in flight cockpit"],
    }

    ENVIRONMENT_MAPPINGS: Dict[str, List[str]] = {
        "sea": ["high seas", "open ocean", "naval waters"],
        "harbor": ["port harbor", "dockside", "anchorage"],
        "ocean": ["open ocean", "deep sea", "naval waters"],
        "palace": ["sultan palace", "royal residence", "seat of government"],
        "city": ["city center", "urban streets", "capital city"],
        "bunker": ["underground bunker", "command fortification", "bomb shelter"],
        "trench": ["frontline trench", "dugout position", "fortified line"],
        "air": ["aerial view", "in flight", "cockpit perspective"],
        "desert": ["desert dunes", "arid frontline", "desert terrain"],
        "coastal": ["coastline", "coastal shore", "coastal battery"],
    }

    def _get_action_expansions(self, action_text: str) -> List[str]:
        """Finds synonymous action phrasings for the given action text."""
        expansions = []
        action_lower = action_text.lower()
        for root, syns in self.ACTION_SYNONYMS.items():
            if root in action_lower:
                expansions.extend(syns)
        return expansions[:3]

    def _get_env_expansions(self, env_text: str) -> List[str]:
        """Finds setting/environment phrases for the given environment text."""
        expansions = []
        env_lower = env_text.lower()
        for root, syns in self.ENVIRONMENT_MAPPINGS.items():
            if root in env_lower:
                expansions.extend(syns)
        return expansions[:2]

    def expand_queries(
        self,
        base_query: str,
        intent: Optional[VisualIntent] = None,
        max_variants: int = 3
    ) -> List[str]:
        """
        Generates 1 to max_variants focused query variants.
        Original query is preserved as the first element.
        """
        base = base_query.strip()
        variants: List[str] = [base] if base else []
        seen = {base.lower()} if base else set()

        if not intent:
            return variants

        target_obj = getattr(intent, "target_object", None) or getattr(intent, "subject", None)
        v_action = getattr(intent, "visual_action", None) or getattr(intent, "action", None)
        p_entity = getattr(intent, "primary_entity", None)
        hist_ctx = getattr(intent, "historical_context", None) or getattr(intent, "date_context", None) or getattr(intent, "era", None)
        nouns = getattr(intent, "important_nouns", []) or []
        actors = getattr(intent, "people_actors", []) or []
        disambig = getattr(intent, "disambiguating_terms", []) or []
        env = getattr(intent, "environment", None)
        loc = getattr(intent, "location", None)
        event = getattr(intent, "event", None)

        # Determine clean event/topic anchor
        clean_event = ""
        if event:
            ev_main = str(event).split(":")[0].split(" - ")[0].strip()
            ev_clean = re.sub(r'[^\w\s]', '', ev_main).strip()
            ev_words = [w for w in ev_clean.split() if w.lower() not in {"the", "a", "an", "this", "that", "disaster", "event", "story", "secret", "covert", "classified", "recovery"} and not w.isdigit()]
            clean_event = " ".join(ev_words[:3])
        if not clean_event and p_entity:
            clean_event = str(p_entity).strip()
        if not clean_event and base:
            clean_base = re.sub(r'[^\w\s]', '', base).strip()
            b_words = [w for w in clean_base.split() if w.lower() not in {"the", "a", "an", "footage"} and not w.isdigit()]
            clean_event = " ".join(b_words[:2]) or clean_base

        # Anchor base query with topic/event if missing to prevent generic drift
        if clean_event and base and clean_event.lower() not in base.lower():
            anchored_base = f"{clean_event} {base}"
            variants = [anchored_base, base]
            seen = {anchored_base.lower(), base.lower()}
        else:
            variants = [base] if base else []
            seen = {base.lower()} if base else set()

        era_str = str(getattr(intent, "era", "") or getattr(intent, "date_context", "") or "").lower()
        is_historical = any(k in era_str for k in ["18th", "19th", "victorian", "medieval", "ancient", "century", "historical", "cold war"]) or (
            bool(re.search(r'\b(1[6-9]\d{2})\b', era_str))
        )

        def _clean_action_str(raw_act: str) -> str:
            if not raw_act:
                return ""
            act_words = [
                w for w in re.sub(r'[^\w\s]', '', str(raw_act)).split()
                if w.lower() not in {"the", "a", "an", "this", "that", "from", "down", "with", "into", "onto", "of", "and", "is", "was", "were"}
            ]
            return " ".join(act_words[:4])

        def _combine_anchor(anchor_str: str, main_str: str) -> str:
            if not anchor_str:
                return main_str
            if not main_str:
                return anchor_str
            anchor_words = anchor_str.split()
            main_words = main_str.split()
            main_lower = {w.lower() for w in main_words}
            unique_anchor = [w for w in anchor_words if w.lower() not in main_lower]
            if unique_anchor:
                return f"{' '.join(unique_anchor)} {main_str}"
            return main_str

        generated_candidates: List[str] = []

        # 1. Target Object + Action Synonyms (+ Topic Anchor)
        if target_obj and v_action:
            obj_str = str(target_obj).strip()
            act_clean = _clean_action_str(str(v_action))
            combined_obj = _combine_anchor(clean_event, obj_str)
            if act_clean.lower() in combined_obj.lower():
                parts = [combined_obj]
            else:
                parts = [combined_obj, act_clean]
            generated_candidates.append(" ".join([p for p in parts if p]))
            for act_syn in self._get_action_expansions(str(v_action)):
                if act_syn.lower() in combined_obj.lower():
                    parts_syn = [combined_obj]
                else:
                    parts_syn = [combined_obj, act_syn]
                generated_candidates.append(" ".join([p for p in parts_syn if p]))

        # 2. Primary Entity + Action / Setting (+ Topic Anchor)
        if p_entity:
            ent_str = str(p_entity).strip()
            combined_ent = _combine_anchor(clean_event, ent_str)
            entity_parts = [combined_ent]
            if v_action:
                act_clean = _clean_action_str(str(v_action))
                entity_parts.append(act_clean)
            generated_candidates.append(" ".join([p for p in entity_parts if p]))
            if env:
                for env_syn in self._get_env_expansions(str(env)):
                    generated_candidates.append(" ".join([p for p in [combined_ent, env_syn] if p]))

        # 3. Environment / Setting + Location + Visual Action
        if env and (loc or clean_event):
            loc_str = str(loc).strip() if loc else clean_event
            act_clean = _clean_action_str(str(v_action)) if v_action else ""
            for env_syn in self._get_env_expansions(str(env)):
                if act_clean:
                    generated_candidates.append(f"{loc_str} {env_syn} {act_clean}")
                else:
                    generated_candidates.append(f"{loc_str} {env_syn} footage")

        # 4. People / Actors + Action / Topic Anchor
        if actors:
            actor = str(actors[0]).strip()
            act_clean = _clean_action_str(str(v_action)) if v_action else ""
            if act_clean:
                generated_candidates.append(f"{clean_event} {actor} {act_clean}")
            else:
                generated_candidates.append(f"{clean_event} {actor} footage")

        # 5. Disambiguating Terms + Core Nouns
        if disambig:
            d_term = str(disambig[0]).strip()
            target_str = str(target_obj or p_entity or "").strip()
            if target_str and d_term.lower() not in target_str.lower() and target_str.lower() not in d_term.lower():
                combined = _combine_anchor(clean_event, f"{d_term} {target_str}")
                generated_candidates.append(combined)
            elif target_str:
                combined = _combine_anchor(clean_event, target_str)
                generated_candidates.append(combined)

        # 6. Reference-Derived Tier 1 & Tier 2 Queries (Docudrama / Archival / Documentary)
        if clean_event:
            generated_candidates.append(f"{clean_event} docudrama film reenactment")
            generated_candidates.append(f"{clean_event} documentary footage")
            generated_candidates.append(f"{clean_event} archival footage")
            if is_historical:
                generated_candidates.append(f"{clean_event} declassified footage")
                generated_candidates.append(f"{clean_event} historical broadcast")
            else:
                generated_candidates.append(f"{clean_event} news report footage")
            generated_candidates.append(f"{clean_event} footage")

        # Filter, normalize, deduplicate
        for cand in generated_candidates:
            raw_tokens = cand.split()
            # Deduplicate repeated words across entire query
            deduped_tokens = []
            seen_cand_tokens = set()
            for t in raw_tokens:
                t_lower = t.lower()
                if t_lower in seen_cand_tokens and len(t) > 3:
                    continue
                seen_cand_tokens.add(t_lower)
                deduped_tokens.append(t)
            cand_clean = " ".join(deduped_tokens).strip()
            if not cand_clean:
                continue
            cand_lower = cand_clean.lower()
            tokens = cand_lower.split()

            # Reject single generic token alone
            if len(tokens) == 1 and tokens[0] in self.GENERIC_TERMS:
                continue
            # Reject if all tokens are generic
            if all(t in self.GENERIC_TERMS for t in tokens):
                continue

            if cand_lower not in seen:
                seen.add(cand_lower)
                variants.append(cand_clean)
                if len(variants) >= max_variants + 1:
                    break

        return variants[:max_variants + 1]


# ==============================================================================
# 3. Staged / Streaming Download Ingester
# ==============================================================================
class StagedStreamIngester:
    """
    Staged streaming downloader with early header inspection and
    first-chunk magic-byte rejection.
    Rejects images, HTML error pages, and oversize downloads early before
    consuming network bandwidth or disk space.
    """

    HTML_SIGNATURES = [
        b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<head", b"<body",
        b"502 Bad Gateway", b"404 Not Found", b"403 Forbidden", b"500 Internal",
        b'{"error":', b'{"message":'
    ]

    def is_early_rejected_payload(self, first_chunk: bytes) -> Tuple[bool, Optional[str]]:
        """Inspects first chunk (up to 8KB) for static image or HTML error signatures."""
        if not first_chunk or len(first_chunk) < 8:
            return True, "Payload too small or empty"

        # Check known image magic byte signatures
        for sig, mime in IMAGE_MAGIC_SIGNATURES:
            if first_chunk.startswith(sig):
                return True, f"Prohibited image magic bytes detected ({mime})"

        # Check WebP RIFF
        if first_chunk.startswith(b"RIFF") and len(first_chunk) >= 12 and first_chunk[8:12] == b"WEBP":
            return True, "Prohibited image magic bytes detected (image/webp)"

        # Check HTML / error page text
        chunk_stripped = first_chunk.lstrip()
        for html_sig in self.HTML_SIGNATURES:
            if html_sig in chunk_stripped[:1024]:
                sig_repr = html_sig.decode("ascii", errors="ignore")
                return True, f"HTML/text error page signature detected ({sig_repr})"

        return False, None

    def stream_and_validate(
        self,
        url: str,
        dest_path: Path,
        budget: Optional[RetrievalBudget] = None
    ) -> Tuple[bool, Optional[str], int]:
        """
        Progressively streams and validates video download.
        Returns:
            (success: bool, error_message: Optional[str], bytes_downloaded: int)
        """
        b = budget or RetrievalBudget()

        # 1. Pre-validation of URL extension / patterns
        if PhysicalVideoValidator.is_image_url(url):
            return False, f"Static image URL rejected prior to network request: {url}", 0

        # Handle local file:// URIs directly
        if url.startswith("file:///"):
            local_src = Path(url[8:])
            if local_src.exists():
                try:
                    shutil.copyfile(local_src, dest_path)
                    return True, None, dest_path.stat().st_size
                except Exception as cp_err:
                    return False, f"Local copy failed: {cp_err}", 0

        headers = {
            "User-Agent": "AL-AMR-VisualRetrieval/1.0 (Public Research Video Ingestion; Headless)",
            "Accept": "video/*,*/*;q=0.8"
        }

        bytes_written = 0
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(1, b.max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=b.download_timeout)

                # Fast-fail on permanent client errors (404, 403, 410)
                if 400 <= resp.status_code < 500:
                    return False, f"HTTP {resp.status_code} client error (permanent, non-retryable)", 0

                # Transient server error: retry if attempts remain
                if resp.status_code != 200:
                    if attempt == b.max_retries:
                        return False, f"HTTP {resp.status_code} server error after {b.max_retries} attempts", 0
                    continue

                # Header inspection: reject image or HTML MIME types
                c_type = (resp.headers.get("Content-Type") or "").lower().split(";")[0].strip()
                if c_type in PROHIBITED_MIME_TYPES or c_type.startswith("image/") or c_type.startswith("text/html"):
                    return False, f"Prohibited MIME type rejected via header: {c_type}", 0

                # Content-Length guard
                c_len = resp.headers.get("Content-Length")
                if c_len:
                    try:
                        content_len = int(c_len)
                        if content_len > b.max_download_bytes:
                            return False, f"Content-Length ({content_len} bytes) exceeds limit ({b.max_download_bytes} bytes)", 0
                        if content_len == 0:
                            return False, "Content-Length is 0 bytes", 0
                    except ValueError:
                        pass

                # Streaming download with first-chunk inspection
                first_chunk_checked = False
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        if not first_chunk_checked and b.enable_early_magic_check:
                            is_rejected, reject_reason = self.is_early_rejected_payload(chunk)
                            if is_rejected:
                                dest_path.unlink(missing_ok=True)
                                return False, f"Early stream rejection: {reject_reason}", bytes_written
                            first_chunk_checked = True

                        bytes_written += len(chunk)
                        if bytes_written > b.max_download_bytes:
                            dest_path.unlink(missing_ok=True)
                            return False, f"Download exceeded max bytes ({b.max_download_bytes}) during streaming", bytes_written
                        f.write(chunk)

                if bytes_written == 0 or not dest_path.exists():
                    dest_path.unlink(missing_ok=True)
                    return False, "Zero bytes written to target destination", 0

                return True, None, bytes_written

            except (requests.Timeout, requests.ConnectionError) as net_err:
                dest_path.unlink(missing_ok=True)
                if attempt == b.max_retries:
                    return False, f"Transient network failure after {attempt} retries: {net_err}", 0
            except Exception as dl_err:
                dest_path.unlink(missing_ok=True)
                return False, f"Download error: {dl_err}", 0

        dest_path.unlink(missing_ok=True)
        return False, "Exhausted download attempts without success", 0


# ==============================================================================
# 4. Parallel Provider Video Retriever
# ==============================================================================
class ParallelVideoRetriever:
    """
    Executes safe parallel retrieval across independent video providers
    with timeout guardrails, provider failure isolation, and early-success support.
    """

    def search_providers_parallel(
        self,
        providers: List[Any],
        query: str,
        intent: Optional[VisualIntent] = None,
        count: int = 4,
        exclude_urls: Optional[Set[str]] = None,
        budget: Optional[RetrievalBudget] = None
    ) -> Tuple[List[NormalizedVideoCandidate], List[Dict[str, Any]]]:
        """
        Concurrently queries registered providers.
        A single provider failure or timeout does NOT terminate the batch.
        """
        b = budget or RetrievalBudget()
        exclude = set(exclude_urls or [])
        candidates: List[NormalizedVideoCandidate] = []
        provider_reports: List[Dict[str, Any]] = []

        if not providers:
            return candidates, provider_reports

        from .cache import get_circuit_breaker
        circuit_breaker = get_circuit_breaker()
        active_providers = [p for p in providers if circuit_breaker.is_available(getattr(p, "name", "unknown"))]
        if not active_providers:
            logger.warning("[PARALLEL_RETRIEVER] All providers tripped circuit breaker. Returning empty.")
            return candidates, provider_reports

        # Sequential fallback if parallel is disabled or only 1 active provider exists
        if not b.enable_parallel or len(active_providers) == 1:
            for prov in active_providers:
                prov_name = getattr(prov, "name", "unknown")
                start_t = time.perf_counter()
                try:
                    cands = prov.search(query=query, intent=intent, count=count, exclude_urls=exclude)
                    latency = time.perf_counter() - start_t
                    valid_cands = self._filter_and_normalize(cands, exclude)
                    candidates.extend(valid_cands)
                    circuit_breaker.record_success(prov_name)
                    provider_reports.append({
                        "provider": prov_name,
                        "status": "SUCCESS",
                        "count": len(valid_cands),
                        "latency": latency
                    })
                except Exception as e:
                    latency = time.perf_counter() - start_t
                    circuit_breaker.record_failure(prov_name, str(e))
                    logger.warning(f"[PARALLEL_RETRIEVER] Provider '{prov_name}' search notice: {e}")
                    provider_reports.append({
                        "provider": prov_name,
                        "status": "FAILED",
                        "error": str(e),
                        "latency": latency
                    })
            return candidates, provider_reports

        # Concurrent execution across active providers
        workers = max(1, len(active_providers))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_prov = {
                executor.submit(prov.search, query=query, intent=intent, count=count, exclude_urls=exclude): prov
                for prov in active_providers
            }

            for future in as_completed(future_to_prov):
                prov = future_to_prov[future]
                start_t = time.perf_counter()
                prov_name = getattr(prov, "name", "unknown")
                try:
                    cands = future.result(timeout=b.provider_timeout)
                    latency = time.perf_counter() - start_t
                    valid_cands = self._filter_and_normalize(cands, exclude)
                    candidates.extend(valid_cands)
                    circuit_breaker.record_success(prov_name)
                    provider_reports.append({
                        "provider": prov_name,
                        "status": "SUCCESS",
                        "count": len(valid_cands),
                        "latency": latency
                    })
                except TimeoutError:
                    latency = time.perf_counter() - start_t
                    circuit_breaker.record_failure(prov_name, f"Timed out after {b.provider_timeout}s")
                    logger.warning(f"[PARALLEL_RETRIEVER] Provider '{prov_name}' timed out after {b.provider_timeout}s. Isolated safely.")
                    provider_reports.append({
                        "provider": prov_name,
                        "status": "TIMEOUT",
                        "error": f"Timed out after {b.provider_timeout}s",
                        "latency": latency
                    })
                except Exception as e:
                    latency = time.perf_counter() - start_t
                    circuit_breaker.record_failure(prov_name, str(e))
                    logger.warning(f"[PARALLEL_RETRIEVER] Provider '{prov_name}' failed with {type(e).__name__}: {e}. Isolated safely.")
                    provider_reports.append({
                        "provider": prov_name,
                        "status": "FAILED",
                        "error": str(e),
                        "latency": latency
                    })

        return candidates, provider_reports

    def _filter_and_normalize(
        self,
        cands: List[NormalizedVideoCandidate],
        exclude: Set[str]
    ) -> List[NormalizedVideoCandidate]:
        from .cache import get_canonical_cache
        cache = get_canonical_cache()
        valid: List[NormalizedVideoCandidate] = []
        for c in cands:
            if not getattr(c, "is_video", True):
                continue
            media_url = getattr(c, "media_url", "")
            page_url = getattr(c, "page_url", "")
            if media_url and media_url in exclude:
                continue
            if page_url and page_url in exclude:
                continue
            if (media_url and cache.is_disqualified(media_url)) or (page_url and cache.is_disqualified(page_url)):
                continue
            if media_url and PhysicalVideoValidator.is_image_url(media_url):
                continue
            if page_url and PhysicalVideoValidator.is_image_url(page_url):
                continue
            valid.append(c)
        return valid


# ==============================================================================
# 5. Retrieval Telemetry Data Contract & Collector
# ==============================================================================
@dataclass
class RetrievalTelemetryRecord:
    """Internal diagnostic record for auditing a single retrieval or ingestion attempt."""
    scene_id: str
    query: str
    provider: str
    source_type: str
    candidate_url: str
    retrieval_latency: float
    bytes_downloaded: int
    validation_result: str
    semantic_score: float
    temporal_result: str
    memory_result: str
    rejection_reason: Optional[str] = None
    selected_status: str = "REJECTED"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RetrievalTelemetryCollector:
    """
    Internal diagnostic collector for auditing visual retrieval performance.
    STRICTLY INTERNAL: Never surfaced in public YouTube metadata, titles, or descriptions.
    """

    def __init__(self):
        self._records: List[RetrievalTelemetryRecord] = []

    def record(self, record: RetrievalTelemetryRecord) -> None:
        self._records.append(record)

    def get_summary(self) -> Dict[str, Any]:
        total = len(self._records)
        selected = sum(1 for r in self._records if r.selected_status == "SELECTED")
        total_bytes = sum(r.bytes_downloaded for r in self._records)
        avg_latency = (sum(r.retrieval_latency for r in self._records) / total) if total else 0.0
        return {
            "total_attempts": total,
            "selected_count": selected,
            "total_bytes_downloaded": total_bytes,
            "average_latency_sec": round(avg_latency, 3),
            "providers_audited": list({r.provider for r in self._records})
        }

    def clear(self) -> None:
        self._records.clear()
