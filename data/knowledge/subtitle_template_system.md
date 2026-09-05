# Multi-Style Subtitle Template System

## 1. Requirement: Multiple Styles Within ONE Short
A core differentiator of modern editorial short-form video is that subtitles do not remain static in a single style or position. Important hooks, evidence reveals, statistics, quotes, and emotional peaks require distinct typographic weight, color, highlighting, and screen placement.

The AL-AMR subtitle engine natively supports **multiple subtitle templates within a single video**, controlled deterministically by narrative beat intent.

---

## 2. Supported Template Categories
At minimum, 20 distinct typographic templates are registered in engines/visual_intelligence/editing/subtitle_templates.py:

1. **CLEAN**: Minimalist white sans-serif with subtle drop shadow for standard narration.
2. **KINETIC**: Energetic scale bursts on each word arrival for fast-paced sequences.
3. **WORD_HIGHLIGHT**: Modern karaoke-style where the active spoken word flashes gold/cyan.
4. **PUNCH**: Bold condensed typography with high-contrast black stroke for hooks.
5. **IMPACT**: Uppercase, heavy tracking, vibrant yellow fill for dramatic climaxes.
6. **BOXED**: Translucent dark pill background behind white text for high-contrast readability over complex video.
7. **OUTLINED**: Deep outline (8px) with zero fill for stark, documentary realism.
8. **TOP_CAPTION**: Positioned in the upper safe-third when lower-thirds display document evidence.
9. **BOTTOM_CAPTION**: Traditional lower safe-third positioning.
10. **SIDE_CAPTION**: Vertically stacked or margin-left aligned for split-screen compositions.
11. **SPLIT_CAPTION**: Two-line phrase structure emphasizing cause and effect.
12. **KEYWORD_CALLOUT**: Enlarged 1.25x font size specifically on the primary entity/keyword.
13. **QUOTE**: Italicized serif/sans with quotation marks for verified statements.
14. **QUESTION**: Vibrant cyan with animated punctuation for opening hook interrogatives.
15. **STATISTIC**: Massive numeric typography with secondary label for data beats.
16. **EVIDENCE**: Monospace/condensed style paired with archive document overlays.
17. **LOCATION**: Small-caps tracking with location pin motif for geographic contexts.
18. **DATE**: Clean historical timestamp header style.
19. **REACTION**: Playful italicized font with expressive motion for contextual commentary.
20. **EMPHASIS**: Red/gold warning colorway for critical turning points.

---

## 3. Subtitle Style Selector Rules
- **Hook / Opening Question**: QUESTION or PUNCH.
- **Primary Claim / Evidence**: EVIDENCE or KEYWORD_CALLOUT.
- **Numeric Fact / Statistic**: STATISTIC.
- **Direct Quotation**: QUOTE.
- **Standard Narration**: CLEAN or WORD_HIGHLIGHT.
- **Climactic Peak**: IMPACT or EMPHASIS.

### Anti-Chaos Constraints
- **Minimum Style Persistence**: A style persists for at least 1 beat (minimum 1.8 seconds).
- **Maximum Consecutive Repetition**: A specialized style (e.g. IMPACT, STATISTIC, QUOTE) cannot repeat for more than 2 consecutive beats.
- **Style Cooldown**: Specialized styles have a 2-beat cooldown before re-use.
- **Readability Rules**: Safe-zone boundaries (top 15%, bottom 20%, margins 80px) are enforced at all times.
