"""
Asset Fetcher Engine.
Autonomous visual acquisition pipeline prioritizing high-quality Pexels VIDEO first:
  1. Pexels 1080p Video (portrait or landscape with 9:16 center crop)
  2. Pexels 720p Video (if 1080p unavailable; rejects < 720p)
  3. High-resolution Pexels Photo (if no video available)
  4. Pollinations AI Image (if stock photo unavailable)
  5. Procedural neutral canvas (final fallback)

Strictly crops/reframes all visuals to 1080x1920 (9:16 vertical), preserves natural color,
prevents duplicate asset reuse in the same Short, and tracks commercial zero-cost licenses.
"""
import os
import uuid
import random
import logging
import urllib.parse
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Set
from PIL import Image
from sqlalchemy.orm import Session
from config.settings import PEXELS_API_KEY, ASSETS_CACHE_DIR, ASSETS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT, LicenseType
from core.models import AssetRecord

logger = logging.getLogger(__name__)


def parse_rate_limit_headers(headers: Any) -> Dict[str, Optional[int]]:
    """
    Defensively extracts X-Ratelimit-Limit, X-Ratelimit-Remaining, X-Ratelimit-Reset
    from HTTP response headers (case-insensitive). Never raises on malformed or missing headers.
    """
    res: Dict[str, Optional[int]] = {"limit": None, "remaining": None, "reset": None}
    if not headers or not hasattr(headers, "get"):
        return res

    def _parse_int(key: str) -> Optional[int]:
        val = headers.get(key)
        if val is None:
            val = headers.get(key.lower()) or headers.get(key.upper())
        if val is not None:
            try:
                return int(float(str(val).strip()))
            except (ValueError, TypeError):
                return None
        return None

    res["limit"] = _parse_int("X-Ratelimit-Limit")
    res["remaining"] = _parse_int("X-Ratelimit-Remaining")
    res["reset"] = _parse_int("X-Ratelimit-Reset")
    return res


def record_pexels_telemetry(
    db: Session,
    endpoint: str = "/v1/search",
    status_code: Optional[int] = None,
    headers: Optional[Any] = None,
    units: int = 1,
    is_observed: bool = True
) -> None:
    """
    Persists Pexels API usage and observed rate limit headers into provider_usage.
    Fails safely so telemetry issues NEVER crash the production pipeline.
    """
    try:
        from core.models import ProviderUsage
        from datetime import datetime

        parsed = parse_rate_limit_headers(headers)
        usage_entry = ProviderUsage(
            provider_name="pexels",
            units_used=units,
            endpoint=endpoint,
            status_code=status_code,
            rate_limit=parsed["limit"],
            rate_remaining=parsed["remaining"],
            rate_reset=parsed["reset"],
            is_observed=is_observed,
            created_at=datetime.utcnow()
        )
        db.add(usage_entry)
        db.commit()
    except Exception as err:
        logger.warning(f"[PEXELS_TELEMETRY] Failed to record provider telemetry: {err}")
        try:
            db.rollback()
        except Exception:
            pass


class AssetFetcher:
    """Retrieves and prepares 1080x1920 vertical visual assets with zero-cost commercial licensing."""

    def __init__(self):
        self.cache_dir = ASSETS_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def crop_to_vertical_9_16(self, img_path: Path, output_path: Path) -> Path:
        """
        Crops and scales any image to exactly 1080x1920 (9:16 vertical)
        using center-crop with smart aspect ratio preservation.
        """
        with Image.open(img_path) as im:
            im = im.convert("RGB")
            orig_w, orig_h = im.size
            target_ratio = VIDEO_WIDTH / VIDEO_HEIGHT  # 1080 / 1920 = 0.5625
            orig_ratio = orig_w / orig_h

            if orig_ratio > target_ratio:
                # Image is wider: crop sides
                new_w = int(orig_h * target_ratio)
                left = (orig_w - new_w) // 2
                im = im.crop((left, 0, left + new_w, orig_h))
            else:
                # Image is taller: crop top/bottom
                new_h = int(orig_w / target_ratio)
                top = (orig_h - new_h) // 2
                im = im.crop((0, top, orig_w, top + new_h))

            # Resize to exact 1080x1920
            final_img = im.resize((VIDEO_WIDTH, VIDEO_HEIGHT), Image.Resampling.LANCZOS)
            final_img.save(output_path, "JPEG", quality=95)
        return output_path

    def _rank_video_file(self, video_file: Dict[str, Any]) -> Tuple[int, int, int]:
        """
        Ranks video stream files by quality tier:
          Tier 4 (Best): 1080p Portrait (1080x1920+ - zero crop distortion)
          Tier 3: 1080p Landscape (1920x1080+ - standard high-res)
          Tier 2: 720p Portrait (720x1280+)
          Tier 1: 720p Landscape (1280x720+)
          Tier 0: Below 720p (REJECTED)
        Returns: (tier, pixel_count, fps)
        """
        w = video_file.get("width") or 0
        h = video_file.get("height") or 0
        fps = video_file.get("fps") or 24
        file_type = (video_file.get("file_type") or "").lower()

        if "mp4" not in file_type and video_file.get("link", "").split("?")[0].endswith(".webm"):
            return (0, 0, 0)

        # Reject anything below 720p
        if w < 720 and h < 720:
            return (0, 0, 0)
        if min(w, h) < 720:
            return (0, 0, 0)

        pixels = w * h

        # 1080p check
        if min(w, h) >= 1080:
            if h >= w:
                return (4, pixels, fps)  # 1080p portrait
            else:
                return (3, pixels, fps)  # 1080p landscape
        elif min(w, h) >= 720:
            if h >= w:
                return (2, pixels, fps)  # 720p portrait
            else:
                return (1, pixels, fps)  # 720p landscape

        return (0, 0, 0)

    def search_pexels_video(
        self,
        db: Session,
        query: str,
        min_duration: float = 2.0,
        exclude_urls: Optional[Set[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Queries Pexels Video API and selects the best 1080p / 720p candidate.
        Rejects candidates below 720p.
        Returns dict with {download_url, width, height, duration, quality_tier, pexels_id} or None.
        """
        if not PEXELS_API_KEY:
            return None

        url = "https://api.pexels.com/videos/search"
        endpoint = "/videos/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {
            "query": query,
            "per_page": 10,
            "page": 1
        }
        exclude = exclude_urls or set()

        try:
            from core.retry import retry_call
            resp = retry_call(
                lambda: requests.get(url, headers=headers, params=params, timeout=12),
                max_retries=3,
                base_delay=1.0
            )
            if resp is not None:
                record_pexels_telemetry(
                    db=db,
                    endpoint=endpoint,
                    status_code=resp.status_code,
                    headers=resp.headers,
                    units=1,
                    is_observed=True
                )

            if resp is not None and resp.status_code == 200:
                data = resp.json()
                videos = data.get("videos", [])
                if not videos:
                    return None

                # Query database for previously used asset URLs
                used_urls = set([r[0] for r in db.query(AssetRecord.source_url).all() if r[0]])
                used_urls.update(exclude)

                candidates = []
                for vid in videos:
                    vid_url = vid.get("url") or ""
                    vid_id = str(vid.get("id") or "")
                    vid_duration = float(vid.get("duration") or 0.0)

                    # Reject excessively short clips (< 2s)
                    if vid_duration < min_duration:
                        continue

                    # Evaluate available video stream files
                    files = vid.get("video_files", [])
                    best_file = None
                    best_rank = (0, 0, 0)

                    for vf in files:
                        rank = self._rank_video_file(vf)
                        if rank[0] > best_rank[0] or (rank[0] == best_rank[0] and rank[1] > best_rank[1]):
                            best_rank = rank
                            best_file = vf

                    if best_file and best_rank[0] > 0:
                        download_link = best_file.get("link")
                        if not download_link or download_link in used_urls:
                            continue

                        # Candidate score: Tier weight + duration suitability bonus
                        score = best_rank[0] * 100
                        if best_rank[0] >= 3:
                            score += 50  # 1080p bonus
                        if vid_duration >= 3.0:
                            score += 10

                        candidates.append({
                            "download_url": download_link,
                            "pexels_url": vid_url,
                            "pexels_id": vid_id,
                            "width": best_file.get("width"),
                            "height": best_file.get("height"),
                            "duration": vid_duration,
                            "quality_tier": "1080p" if best_rank[0] >= 3 else "720p",
                            "score": score
                        })

                if candidates:
                    candidates.sort(key=lambda c: c["score"], reverse=True)
                    selected = candidates[0]
                    logger.info(
                        f"[PEXELS_VIDEO] Selected {selected['quality_tier']} video ({selected['width']}x{selected['height']}, "
                        f"{selected['duration']:.1f}s) for query '{query}'"
                    )
                    return selected

        except Exception as e:
            logger.warning(f"Pexels video query failed for '{query}': {e}")
            record_pexels_telemetry(
                db=db,
                endpoint=endpoint,
                status_code=getattr(e, "status_code", None),
                headers=getattr(getattr(e, "response", None), "headers", None),
                units=1,
                is_observed=False
            )

        return None

    def search_pexels_photo(
        self,
        db: Session,
        query: str,
        exclude_urls: Optional[Set[str]] = None
    ) -> Optional[str]:
        """Queries Pexels Photo API and picks a fresh, high-resolution photo."""
        if not PEXELS_API_KEY:
            return None
        url = "https://api.pexels.com/v1/search"
        endpoint = "/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {"query": query, "per_page": 15, "page": random.randint(1, 3), "orientation": "portrait"}
        exclude = exclude_urls or set()

        try:
            from core.retry import retry_call
            resp = retry_call(
                lambda: requests.get(url, headers=headers, params=params, timeout=10),
                max_retries=3,
                base_delay=1.0
            )
            if resp is not None:
                record_pexels_telemetry(
                    db=db,
                    endpoint=endpoint,
                    status_code=resp.status_code,
                    headers=resp.headers,
                    units=1,
                    is_observed=True
                )

            if resp is not None and resp.status_code == 200:
                data = resp.json()
                photos = data.get("photos", [])
                if photos:
                    used_urls = set([r[0] for r in db.query(AssetRecord.source_url).all() if r[0]])
                    used_urls.update(exclude)

                    unused = [
                        p["src"].get("large2x") or p["src"].get("original") or p["src"].get("large")
                        for p in photos
                        if (p["src"].get("large2x") or p["src"].get("original")) not in used_urls
                    ]
                    if unused:
                        return unused[0]
                    # Fallback to any high-res photo from list
                    candidate = photos[0]["src"]
                    return candidate.get("large2x") or candidate.get("original") or candidate.get("large")
        except Exception as e:
            logger.warning(f"Pexels photo query failed for '{query}': {e}")
            record_pexels_telemetry(
                db=db,
                endpoint=endpoint,
                status_code=getattr(e, "status_code", None),
                headers=getattr(getattr(e, "response", None), "headers", None),
                units=1,
                is_observed=False
            )
        return None

    def generate_ai_image(self, prompt: str, output_path: Path) -> bool:
        """
        Generates free, commercially usable AI historical image via Pollinations.ai (Free $0 / Open).
        """
        try:
            from core.retry import retry_call
            seed = random.randint(1, 999999)
            encoded_prompt = urllib.parse.quote(prompt + f", historic photograph style, authentic documentary, seed {seed}")
            url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1080&height=1920&nologo=true&seed={seed}"
            resp = retry_call(
                lambda: requests.get(url, timeout=25),
                max_retries=3,
                base_delay=1.5
            )
            if resp.status_code == 200 and len(resp.content) > 5000:
                with open(output_path, "wb") as f:
                    f.write(resp.content)
                return True
        except Exception as e:
            logger.warning(f"AI image generation failed: {e}")
        return False

    def fetch_asset_for_shot(
        self,
        db: Session,
        shot_data: Dict[str, Any],
        used_urls_in_job: Optional[Set[str]] = None
    ) -> AssetRecord:
        """
        Acquires a unique visual asset for a shot:
          Pexels 1080p Video -> Pexels 720p Video -> Pexels Photo -> Pollinations AI Image.
        """
        asset_id = f"ast_{uuid.uuid4().hex[:12]}"
        query = shot_data["search_query"]
        prompt = shot_data.get("visual_prompt", f"Cinematic historical scene of {query}")
        shot_duration = float(shot_data.get("duration", 4.0))

        raw_video_path = self.cache_dir / f"{asset_id}_raw.mp4"
        raw_img_path = self.cache_dir / f"{asset_id}_raw.jpg"
        cropped_img_path = self.cache_dir / f"{asset_id}_1080x1920.jpg"

        exclude_set = used_urls_in_job if used_urls_in_job is not None else set()

        # ----------------------------------------------------
        # 1. PRIMARY: Pexels Video Search (1080p / 720p)
        # ----------------------------------------------------
        video_meta = self.search_pexels_video(db, query, min_duration=2.0, exclude_urls=exclude_set)
        if video_meta and video_meta.get("download_url"):
            dl_url = video_meta["download_url"]
            try:
                logger.info(f"[ASSET_FETCH] Downloading {video_meta['quality_tier']} Pexels video for shot: '{query}'")
                v_resp = requests.get(dl_url, timeout=30, stream=True)
                if v_resp.status_code == 200:
                    with open(raw_video_path, "wb") as vf:
                        for chunk in v_resp.iter_content(chunk_size=65536):
                            if chunk:
                                vf.write(chunk)

                    if raw_video_path.stat().st_size > 10000:
                        exclude_set.add(dl_url)
                        asset_rec = AssetRecord(
                            id=asset_id,
                            asset_type="video",
                            source="pexels_video",
                            source_url=dl_url,
                            license=LicenseType.PEXELS_LICENSE.value,
                            commercial_use=True,
                            attribution_required=False,
                            local_path=str(raw_video_path),
                            width=video_meta.get("width"),
                            height=video_meta.get("height"),
                            duration_sec=video_meta.get("duration", shot_duration)
                        )
                        db.add(asset_rec)
                        db.commit()
                        logger.info(f"[ASSET_READY] Shot {shot_data['shot_id']} supplied with {video_meta['quality_tier']} video ({asset_id})")
                        return asset_rec
            except Exception as vid_err:
                logger.warning(f"Failed downloading Pexels video {dl_url}: {vid_err}")
                raw_video_path.unlink(missing_ok=True)

        # ----------------------------------------------------
        # 2. FALLBACK 1: Pexels Photo
        # ----------------------------------------------------
        photo_url = self.search_pexels_photo(db, query, exclude_urls=exclude_set)
        if photo_url:
            try:
                logger.info(f"[ASSET_FETCH] Falling back to high-res Pexels photo for shot: '{query}'")
                img_data = requests.get(photo_url, timeout=15).content
                with open(raw_img_path, "wb") as f:
                    f.write(img_data)
                self.crop_to_vertical_9_16(raw_img_path, cropped_img_path)
                exclude_set.add(photo_url)
                asset_rec = AssetRecord(
                    id=asset_id,
                    asset_type="image",
                    source="pexels",
                    source_url=photo_url,
                    license=LicenseType.PEXELS_LICENSE.value,
                    commercial_use=True,
                    attribution_required=False,
                    local_path=str(cropped_img_path),
                    width=VIDEO_WIDTH,
                    height=VIDEO_HEIGHT,
                    duration_sec=shot_duration
                )
                db.add(asset_rec)
                db.commit()
                logger.info(f"[ASSET_READY] Shot {shot_data['shot_id']} supplied with Pexels photo ({asset_id})")
                return asset_rec
            except Exception as e:
                logger.warning(f"Failed downloading Pexels image {photo_url}: {e}")

        # ----------------------------------------------------
        # 3. FALLBACK 2: Pollinations AI Image
        # ----------------------------------------------------
        logger.info(f"[ASSET_FETCH] Falling back to AI visual for shot: '{prompt[:40]}...'")
        if self.generate_ai_image(prompt, raw_img_path):
            self.crop_to_vertical_9_16(raw_img_path, cropped_img_path)
            asset_rec = AssetRecord(
                id=asset_id,
                asset_type="image",
                source="pollinations_ai",
                source_url="https://image.pollinations.ai",
                license=LicenseType.PUBLIC_DOMAIN_CC0.value,
                commercial_use=True,
                attribution_required=False,
                local_path=str(cropped_img_path),
                width=VIDEO_WIDTH,
                height=VIDEO_HEIGHT,
                duration_sec=shot_duration
            )
            db.add(asset_rec)
            db.commit()
            logger.info(f"[ASSET_READY] Shot {shot_data['shot_id']} supplied with Pollinations AI visual ({asset_id})")
            return asset_rec

        # ----------------------------------------------------
        # 4. FINAL RESILIENT FALLBACK: Procedural Canvas
        # ----------------------------------------------------
        im = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color=(20, 24, 32))
        im.save(cropped_img_path, "JPEG", quality=95)
        asset_rec = AssetRecord(
            id=asset_id,
            asset_type="image",
            source="procedural_canvas",
            source_url="local://procedural",
            license=LicenseType.PUBLIC_DOMAIN_CC0.value,
            commercial_use=True,
            attribution_required=False,
            local_path=str(cropped_img_path),
            width=VIDEO_WIDTH,
            height=VIDEO_HEIGHT,
            duration_sec=shot_duration
        )
        db.add(asset_rec)
        db.commit()
        logger.info(f"[ASSET_READY] Shot {shot_data['shot_id']} supplied with procedural canvas ({asset_id})")
        return asset_rec
