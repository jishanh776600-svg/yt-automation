"""
Comprehensive Subtitle Template Registry.
Implements 20 distinct, broadcast-grade typographic templates supporting:
- Variable weights, tracking, line heights, fills, outlines, and drop shadows
- Karaoke active-word color switches and kinetic scale bursts
- Dynamic screen alignment and safe-zone boundaries (top 15%, bottom 20%)
- ASS V4+ Style block generation
"""
from typing import Dict, List, Optional, Set
from .editing_models import SubtitleStyleType, SubtitleTemplate, SubtitlePositionType
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT


# 20 Canonical Subtitle Templates
SUBTITLE_TEMPLATES: Dict[SubtitleStyleType, SubtitleTemplate] = {
    SubtitleStyleType.CLEAN: SubtitleTemplate(
        name="Clean Standard",
        style_type=SubtitleStyleType.CLEAN,
        font_name="Arial Black",
        font_size=82,
        font_weight=900,
        tracking=0.5,
        primary_color_hex="&H00FFFFFF&",       # White
        highlight_color_hex="&H0000D7FF&",     # Yellow/Gold
        outline_color_hex="&H00000000&",       # Black
        back_color_hex="&H80000000&",
        outline_width=7,
        shadow_depth=3,
        border_style=1,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.KINETIC: SubtitleTemplate(
        name="Kinetic Burst",
        style_type=SubtitleStyleType.KINETIC,
        font_name="Arial Black",
        font_size=86,
        font_weight=900,
        tracking=1.0,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000FFFF&",     # Cyan
        secondary_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=8,
        shadow_depth=4,
        entry_animation="pop",
        alignment=2,
        margin_v=450
    ),
    SubtitleStyleType.WORD_HIGHLIGHT: SubtitleTemplate(
        name="Word Highlight Karaoke",
        style_type=SubtitleStyleType.WORD_HIGHLIGHT,
        font_name="Arial Black",
        font_size=84,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",     # Gold active word
        outline_color_hex="&H00000000&",
        outline_width=8,
        shadow_depth=4,
        karaoke_highlight=True,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.PUNCH: SubtitleTemplate(
        name="Punchy Hook",
        style_type=SubtitleStyleType.PUNCH,
        font_name="Impact",
        font_size=92,
        font_weight=900,
        tracking=1.5,
        primary_color_hex="&H0000FFFF&",       # Bright Yellow/Cyan Punch
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=9,
        shadow_depth=5,
        alignment=2,
        margin_v=460
    ),
    SubtitleStyleType.IMPACT: SubtitleTemplate(
        name="Dramatic Impact",
        style_type=SubtitleStyleType.IMPACT,
        font_name="Impact",
        font_size=96,
        font_weight=900,
        tracking=2.0,
        primary_color_hex="&H0000D7FF&",       # Bold Gold
        highlight_color_hex="&H00FFFFFF&",
        outline_color_hex="&H00000000&",
        outline_width=10,
        shadow_depth=6,
        alignment=5,                           # Eye-level Center burst
        margin_v=0
    ),
    SubtitleStyleType.BOXED: SubtitleTemplate(
        name="High-Contrast Boxed",
        style_type=SubtitleStyleType.BOXED,
        font_name="Arial Black",
        font_size=80,
        font_weight=800,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        back_color_hex="&HA0000000&",          # Opaque dark box
        border_style=3,                        # Opaque box border
        outline_width=12,
        shadow_depth=0,
        alignment=2,
        margin_v=430
    ),
    SubtitleStyleType.OUTLINED: SubtitleTemplate(
        name="Stark Outlined",
        style_type=SubtitleStyleType.OUTLINED,
        font_name="Arial Black",
        font_size=88,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000FFFF&",
        outline_color_hex="&H00000000&",
        outline_width=11,
        shadow_depth=2,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.TOP_CAPTION: SubtitleTemplate(
        name="Upper Third Caption",
        style_type=SubtitleStyleType.TOP_CAPTION,
        font_name="Arial Black",
        font_size=78,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=7,
        shadow_depth=3,
        alignment=8,                           # Top-Center (clears lower evidence card)
        margin_v=360
    ),
    SubtitleStyleType.BOTTOM_CAPTION: SubtitleTemplate(
        name="Bottom Safe Third",
        style_type=SubtitleStyleType.BOTTOM_CAPTION,
        font_name="Arial Black",
        font_size=80,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=8,
        shadow_depth=4,
        alignment=2,
        margin_v=480
    ),
    SubtitleStyleType.SIDE_CAPTION: SubtitleTemplate(
        name="Left Margin Side",
        style_type=SubtitleStyleType.SIDE_CAPTION,
        font_name="Arial Black",
        font_size=76,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=7,
        shadow_depth=3,
        alignment=1,                           # Bottom-Left
        margin_l=120,
        margin_v=500
    ),
    SubtitleStyleType.SPLIT_CAPTION: SubtitleTemplate(
        name="Two-Tier Split",
        style_type=SubtitleStyleType.SPLIT_CAPTION,
        font_name="Arial Black",
        font_size=82,
        font_weight=900,
        line_spacing=20,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000FFFF&",
        outline_color_hex="&H00000000&",
        outline_width=8,
        shadow_depth=4,
        alignment=2,
        margin_v=430
    ),
    SubtitleStyleType.KEYWORD_CALLOUT: SubtitleTemplate(
        name="Keyword Focus",
        style_type=SubtitleStyleType.KEYWORD_CALLOUT,
        font_name="Arial Black",
        font_size=90,
        font_weight=900,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000D7FF&",     # Gold callout
        outline_color_hex="&H00000000&",
        outline_width=9,
        shadow_depth=5,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.QUOTE: SubtitleTemplate(
        name="Verified Statement Quote",
        style_type=SubtitleStyleType.QUOTE,
        font_name="Georgia",
        font_size=78,
        font_weight=700,
        tracking=0.5,
        primary_color_hex="&H00E0E0E0&",       # Warm Silver
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=6,
        shadow_depth=3,
        alignment=2,
        margin_v=460,
        uppercase=False
    ),
    SubtitleStyleType.QUESTION: SubtitleTemplate(
        name="Hook Interrogative",
        style_type=SubtitleStyleType.QUESTION,
        font_name="Arial Black",
        font_size=88,
        font_weight=900,
        tracking=1.0,
        primary_color_hex="&H00FFFF00&",       # Electric Cyan
        highlight_color_hex="&H00FFFFFF&",
        outline_color_hex="&H00000000&",
        outline_width=9,
        shadow_depth=5,
        alignment=2,
        margin_v=450
    ),
    SubtitleStyleType.STATISTIC: SubtitleTemplate(
        name="Data & Numbers Focus",
        style_type=SubtitleStyleType.STATISTIC,
        font_name="Impact",
        font_size=98,
        font_weight=900,
        tracking=2.0,
        primary_color_hex="&H0000FF7F&",       # Neon Green / Data accent
        highlight_color_hex="&H00FFFFFF&",
        outline_color_hex="&H00000000&",
        outline_width=10,
        shadow_depth=5,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.EVIDENCE: SubtitleTemplate(
        name="Archive Document Tag",
        style_type=SubtitleStyleType.EVIDENCE,
        font_name="Courier New",
        font_size=74,
        font_weight=900,
        primary_color_hex="&H00D4F0FF&",       # Crisp Document Parchment
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=6,
        shadow_depth=3,
        border_style=3,
        back_color_hex="&HB0000000&",
        alignment=8,                           # Positioned high, paired with archive record
        margin_v=340
    ),
    SubtitleStyleType.LOCATION: SubtitleTemplate(
        name="Geographic Context",
        style_type=SubtitleStyleType.LOCATION,
        font_name="Arial",
        font_size=76,
        font_weight=900,
        tracking=2.5,
        primary_color_hex="&H00FFFFFF&",
        highlight_color_hex="&H0000FFFF&",
        outline_color_hex="&H00000000&",
        outline_width=6,
        shadow_depth=3,
        alignment=7,                           # Top-Left
        margin_l=100,
        margin_v=360
    ),
    SubtitleStyleType.DATE: SubtitleTemplate(
        name="Timeline Date Header",
        style_type=SubtitleStyleType.DATE,
        font_name="Arial Black",
        font_size=76,
        font_weight=900,
        tracking=2.0,
        primary_color_hex="&H00E0E0E0&",
        highlight_color_hex="&H0000D7FF&",
        outline_color_hex="&H00000000&",
        outline_width=6,
        shadow_depth=3,
        alignment=9,                           # Top-Right
        margin_r=100,
        margin_v=360
    ),
    SubtitleStyleType.REACTION: SubtitleTemplate(
        name="Expressive Commentary",
        style_type=SubtitleStyleType.REACTION,
        font_name="Arial Black",
        font_size=86,
        font_weight=900,
        primary_color_hex="&H0000C8FF&",       # Amber Orange
        highlight_color_hex="&H00FFFFFF&",
        outline_color_hex="&H00000000&",
        outline_width=8,
        shadow_depth=4,
        alignment=2,
        margin_v=440
    ),
    SubtitleStyleType.EMPHASIS: SubtitleTemplate(
        name="Critical Climax Warning",
        style_type=SubtitleStyleType.EMPHASIS,
        font_name="Impact",
        font_size=96,
        font_weight=900,
        tracking=1.5,
        primary_color_hex="&H002020FF&",       # Deep Red Warning
        highlight_color_hex="&H0000D7FF&",     # Gold active
        outline_color_hex="&H00FFFFFF&",       # White keyline
        outline_width=8,
        shadow_depth=6,
        alignment=2,
        margin_v=440
    ),
}


def get_subtitle_template(style: SubtitleStyleType) -> SubtitleTemplate:
    """Retrieves a SubtitleTemplate by style enum, with CLEAN fallback."""
    return SUBTITLE_TEMPLATES.get(style, SUBTITLE_TEMPLATES[SubtitleStyleType.CLEAN])


def generate_ass_style_header(active_styles: Optional[Set[SubtitleStyleType]] = None) -> str:
    """
    Generates standard ASS V4+ Styles block containing definitions for all requested styles.
    If active_styles is None, generates headers for all 20 templates.
    """
    styles_to_include = active_styles or set(SUBTITLE_TEMPLATES.keys())
    
    header_lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {VIDEO_WIDTH}",
        f"PlayResY: {VIDEO_HEIGHT}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
    ]

    for style_type in styles_to_include:
        tmpl = get_subtitle_template(style_type)
        bold_flag = -1 if tmpl.font_weight >= 700 else 0
        italic_flag = -1 if "italic" in tmpl.name.lower() or tmpl.style_type == SubtitleStyleType.QUOTE else 0
        
        style_line = (
            f"Style: {tmpl.style_type.value},"
            f"{tmpl.font_name},"
            f"{tmpl.font_size},"
            f"{tmpl.primary_color_hex},"
            f"{tmpl.highlight_color_hex},"
            f"{tmpl.outline_color_hex},"
            f"{tmpl.back_color_hex},"
            f"{bold_flag},"
            f"{italic_flag},"
            f"0,0,100,100,"
            f"{int(tmpl.tracking)},"
            f"0,"
            f"{tmpl.border_style},"
            f"{tmpl.outline_width},"
            f"{tmpl.shadow_depth},"
            f"{tmpl.alignment},"
            f"{tmpl.margin_l},"
            f"{tmpl.margin_r},"
            f"{tmpl.margin_v},"
            f"1"
        )
        header_lines.append(style_line)

    header_lines.extend(["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"])
    return "\n".join(header_lines) + "\n"
