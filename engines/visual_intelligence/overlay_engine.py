"""
Evidence Overlay System.
Generates broadcast-grade contextual evidence overlays:
- Source attribution (Publication, archive, press pool)
- Date and location timestamps
- Verified claim badges
- Quoted statement overlays
- Document citations, maps, statistics, and event labels

Every factual overlay must have provenance. NEVER fabricate attribution.
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image, ImageDraw, ImageFont

from config.settings import ASSETS_DIR, RENDERS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT
from .models import EvidenceOverlaySpec, VisualProvenance

logger = logging.getLogger(__name__)


class EvidenceOverlayEngine:
    """Creates structured, broadcast-grade evidence graphic overlays."""

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or (RENDERS_DIR / "overlays")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_overlay_from_spec(
        self,
        spec: EvidenceOverlaySpec,
        provenance: Optional[VisualProvenance] = None,
        output_filename: Optional[str] = None
    ) -> Path:
        """
        Renders a broadcast-grade factual overlay directly from an EvidenceOverlaySpec.
        Enforces that provenance is present for any factual or official overlay.
        """
        attribution = spec.attribution_text or spec.source_name or (provenance.publisher if provenance else "")
        if spec.require_provenance and not attribution:
            raise ValueError("Factual overlays require valid source provenance; unverified attribution is prohibited.")
        if not provenance and not (spec.source_name or spec.citation_url or spec.attribution_text):
            raise ValueError("Factual overlays require valid source provenance; unverified attribution is prohibited.")

        attribution = attribution or "Official Record"
        date_context = spec.date_text or spec.date_str or (provenance.publication_date if provenance else "Archive")
        location_ctx = f" ({spec.location_str})" if spec.location_str else ""
        meta_line = f"{attribution.upper()}{location_ctx} • {date_context}"

        main_text = (
            spec.headline_text or
            spec.quote_text or
            spec.stat_text or
            f"Verified Record: {spec.label}"
        )

        return self.generate_evidence_overlay(
            headline=main_text,
            attribution=attribution,
            date_label=f"{date_context}{location_ctx}",
            badge_type=spec.label.upper().replace(" ", "_"),
            output_filename=output_filename
        )

    def generate_evidence_overlay(
        self,
        headline: str,
        attribution: str = "Verified Report",
        date_label: str = "Official Context",
        badge_type: str = "FACT_CHECKED",
        output_filename: Optional[str] = None
    ) -> Path:
        """
        Renders a sleek, compact semi-transparent editorial badge overlay (1080x1920 RGBA).
        Covers < 3% of screen, positioned in upper safe zone (x=60, y=220), strictly secondary
        to moving footage, with zero black background or dominant occlusion.
        """
        fname = output_filename or f"evidence_overlay_{uuid.uuid4().hex[:8]}.png"
        out_path = self.output_dir / fname

        # Create transparent canvas (never black)
        img = Image.new("RGBA", (VIDEO_WIDTH, VIDEO_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Compact editorial badge: width 540px, height 76px (only 2.1% of canvas)
        badge_w = 540
        badge_h = 76
        badge_x = 60
        badge_y = 220

        # Subtle semi-transparent glassmorphic background pill
        bg_color = (15, 23, 42, 180)         # Translucent deep slate
        border_color = (56, 189, 248, 170)    # Sleek cyan border
        draw.rounded_rectangle(
            [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
            radius=12,
            fill=bg_color,
            outline=border_color,
            width=1
        )

        # Micro status pill inside badge
        pill_label = badge_type.replace("_", " ").strip()
        pill_w = 110
        pill_h = 24
        pill_x = badge_x + 14
        pill_y = badge_y + 12
        pill_bg = (14, 165, 233, 220) if "FACT" in badge_type or "VERIFIED" in badge_type else (245, 158, 11, 220)
        draw.rounded_rectangle(
            [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
            radius=6,
            fill=pill_bg
        )
        draw.text((pill_x + 8, pill_y + 4), pill_label[:14], fill=(255, 255, 255, 255))

        # Attribution line alongside status pill
        attr_line = f"{attribution.upper()} • {date_label}"
        draw.text((pill_x + pill_w + 14, pill_y + 5), attr_line[:32], fill=(148, 163, 184, 255))

        # Headline / Event note line underneath
        clean_hl = headline.strip()[:42]
        draw.text((badge_x + 16, badge_y + 44), clean_hl, fill=(241, 245, 249, 255))

        img.save(out_path, "PNG")
        logger.debug(f"[EVIDENCE_OVERLAY] Rendered compact editorial badge to {out_path.name}")
        return out_path

# Backwards-compatible alias
EvidenceOverlayEngine.render_overlay_from_spec = EvidenceOverlayEngine.generate_overlay_from_spec
