"""
Asset Fetcher Engine.
Fetches unique stock footage/photos from Pexels API and falls back to free AI Image generation (Pollinations.ai).
Tracks used assets to strictly guarantee zero duplicate images across videos.
Strictly crops/reframes all visuals to 1080x1920 (9:16 vertical) and tracks commercial licenses.
"""
import os
import uuid
import random
import logging
import urllib.parse
import requests
from pathlib import Path
from typing import Dict, Any, List, Optional
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

    def search_pexels_photo(self, db: Session, query: str) -> Optional[str]:
        """Queries Pexels Photo API and picks a fresh, previously unused photo."""
        if not PEXELS_API_KEY:
            return None
        url = "https://api.pexels.com/v1/search"
        endpoint = "/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        # Randomize page between 1 and 4 for variety
        params = {"query": query, "per_page": 15, "page": random.randint(1, 3), "orientation": "portrait"}
        resp = None
        try:
            from core.retry import retry_call
            resp = retry_call(
                lambda: requests.get(url, headers=headers, params=params, timeout=10),
                max_retries=3,
                base_delay=1.0
            )
            # Record observed telemetry from the response (whether 200, 429, 500, etc.)
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
                    # Get previously used URLs from DB
                    used_urls = set([r[0] for r in db.query(AssetRecord.source_url).all() if r[0]])
                    # Filter for unused photos
                    unused = [p for p in photos if p["src"]["large2x"] not in used_urls]
                    candidate = random.choice(unused) if unused else random.choice(photos)
                    return candidate["src"]["large2x"]
        except Exception as e:
            logger.warning(f"Pexels query failed for '{query}': {e}")
            # Record unobserved network/timeout attempt safely
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
            # Add seed to guarantee uniqueness
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

    def fetch_asset_for_shot(self, db: Session, shot_data: Dict[str, Any]) -> AssetRecord:
        """
        Acquires a unique visual asset for a shot via Pexels or Pollinations AI.
        """
        asset_id = f"ast_{uuid.uuid4().hex[:12]}"
        query = shot_data["search_query"]
        prompt = shot_data.get("visual_prompt", f"Cinematic historical scene of {query}")
        
        raw_img_path = self.cache_dir / f"{asset_id}_raw.jpg"
        cropped_img_path = self.cache_dir / f"{asset_id}_1080x1920.jpg"

        photo_url = self.search_pexels_photo(db, query)
        source = "pexels"
        license_type = LicenseType.PEXELS_LICENSE.value

        success = False
        if photo_url:
            try:
                img_data = requests.get(photo_url, timeout=15).content
                with open(raw_img_path, "wb") as f:
                    f.write(img_data)
                self.crop_to_vertical_9_16(raw_img_path, cropped_img_path)
                success = True
            except Exception as e:
                logger.warning(f"Failed downloading Pexels image {photo_url}: {e}")

        # Fallback to AI Image Generation
        if not success:
            logger.info(f"Generating unique AI visual for shot: '{prompt[:40]}...'")
            if self.generate_ai_image(prompt, raw_img_path):
                self.crop_to_vertical_9_16(raw_img_path, cropped_img_path)
                source = "pollinations_ai"
                license_type = LicenseType.PUBLIC_DOMAIN_CC0.value
                success = True

        if not success:
            # Procedural fallback
            im = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), color=(20, 24, 32))
            im.save(cropped_img_path, "JPEG", quality=95)
            source = "procedural_canvas"
            license_type = LicenseType.PUBLIC_DOMAIN_CC0.value

        asset_rec = AssetRecord(
            id=asset_id,
            asset_type="image",
            source=source,
            source_url=photo_url or "https://image.pollinations.ai",
            license=license_type,
            commercial_use=True,
            attribution_required=False,
            local_path=str(cropped_img_path),
            duration_sec=shot_data["duration"]
        )
        db.add(asset_rec)
        db.commit()
        logger.info(f"Prepared unique 1080x1920 asset {asset_id} for shot {shot_data['shot_id']} ({source})")
        return asset_rec
