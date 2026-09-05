"""
Multi-Style Subtitle Engine for AL-AMR.
Produces studio-grade ASS (Advanced SubStation Alpha) subtitle streams supporting
MULTIPLE distinct typographic styles, positions, and active-word animations
within the exact SAME Short.

Features:
- Dynamic style assignment per beat (QUESTION, PUNCH, STATISTIC, QUOTE, IMPACT, etc.)
- Multi-region coordinate placement (Bottom, Center, Upper, Margins)
- Word-level synchronization with active-word karaoke color bursts
- Semantic keyword emphasis highlighting
- Fully deterministic and offline-testable
"""
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Set

from .editing_models import (
    SubtitleCue, SubtitleWord, SubtitleStyleType, SubtitlePositionType
)
from .subtitle_templates import (
    get_subtitle_template, generate_ass_style_header, SUBTITLE_TEMPLATES
)
from .position_engine import POSITION_COORDINATES
from config.settings import CAPTIONS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT

logger = logging.getLogger(__name__)


def format_ass_timestamp(seconds: float) -> str:
    """Formats float seconds into ASS timestamp format: H:MM:SS.cs."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    csecs = int(round((seconds - int(seconds)) * 100))
    if csecs >= 100:
        secs += 1
        csecs = 0
    return f"{hrs}:{mins:02d}:{secs:02d}.{csecs:02d}"


class MultiStyleSubtitleEngine:
    """
    Directorial subtitle compiler that outputs multi-style ASS subtitles.
    """

    SEMANTIC_PUNCH_KEYWORDS: Set[str] = {
        "DISASTER", "EXPLOSION", "WAR", "MYSTERY", "SHOCKING", "SECRET", "DEADLY",
        "CATACLYSM", "UNBELIEVABLE", "TRAGEDY", "COLLAPSE", "BATTLE", "MASSIVE",
        "UNEXPLAINED", "CRISIS", "TREATY", "LEAKED", "EVIDENCE", "PROVEN", "VERIFIED"
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or CAPTIONS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_multistyle_ass(
        self,
        cues: List[SubtitleCue],
        output_path: Optional[Path] = None,
        job_id: Optional[str] = None
    ) -> Path:
        """
        Compiles a list of SubtitleCues into a valid ASS file containing
        all necessary style declarations and timed dialogue events.
        """
        if not output_path:
            jid = job_id or uuid.uuid4().hex[:8]
            output_path = self.output_dir / f"multistyle_subs_{jid}.ass"

        # 1. Determine all unique styles referenced by the cues
        active_styles: Set[SubtitleStyleType] = {c.style_type for c in cues}
        if not active_styles:
            active_styles = {SubtitleStyleType.CLEAN}

        # 2. Build ASS Header with corresponding V4+ Styles
        header = generate_ass_style_header(active_styles)

        # 3. Build Dialogue Events
        dialogue_events = []
        for idx, cue in enumerate(cues):
            start_str = format_ass_timestamp(cue.start_time)
            end_str = format_ass_timestamp(cue.end_time)
            tmpl = get_subtitle_template(cue.style_type)

            # Retrieve position coordinates
            coords = POSITION_COORDINATES.get(cue.position_type, POSITION_COORDINATES[SubtitlePositionType.BOTTOM_CENTER])
            screen_x, screen_y, align, margin_v = coords

            # Build formatted dialogue line
            if cue.words:
                formatted_text = self._format_karaoke_words(cue.words, tmpl, cue.emphasis_keywords)
            else:
                formatted_text = self._format_plain_text(cue.text, tmpl, cue.emphasis_keywords)

            # Position override tag if non-standard position
            pos_tag = f"{{\\an{align}\\pos({screen_x},{screen_y})}}" if cue.position_type != SubtitlePositionType.BOTTOM_CENTER else ""
            line_content = f"{pos_tag}{formatted_text}"

            dialogue_line = f"Dialogue: 0,{start_str},{end_str},{cue.style_type.value},,0,0,0,,{line_content}"
            dialogue_events.append(dialogue_line)
            cue.ass_dialogue_line = dialogue_line

        full_ass_content = header + "\n".join(dialogue_events) + "\n"
        output_path.write_text(full_ass_content, encoding="utf-8")
        logger.info(f"Generated multi-style ASS subtitle stream ({len(cues)} cues, {len(active_styles)} styles) -> {output_path.name}")
        return output_path

    def _format_karaoke_words(
        self,
        words: List[SubtitleWord],
        template: Any,
        emphasis_keywords: List[str]
    ) -> str:
        """Formats words with active-word color bursts and keyword emphasis."""
        elements = []
        for w in words:
            word_str = w.word.upper() if template.uppercase else w.word
            clean_token = "".join(c for c in word_str if c.isalnum()).upper()
            is_emp = clean_token in self.SEMANTIC_PUNCH_KEYWORDS or clean_token in [k.upper() for k in emphasis_keywords] or any(c.isdigit() for c in clean_token)

            if is_emp:
                # Highlight in vibrant Gold or Cyan
                highlight_color = template.highlight_color_hex
                elements.append(f"{{\\c{highlight_color}}}{word_str}{{\\c{template.primary_color_hex}}}")
            else:
                elements.append(word_str)

        return " ".join(elements)

    def _format_plain_text(
        self,
        text: str,
        template: Any,
        emphasis_keywords: List[str]
    ) -> str:
        """Formats raw text string without word-level timestamps."""
        words = text.split()
        return self._format_karaoke_words(
            [SubtitleWord(word=w, start=0.0, end=0.0) for w in words],
            template,
            emphasis_keywords
        )

    def build_cues_from_narration_chunks(
        self,
        words_data: List[Dict[str, Any]],
        chunk_size: int = 3
    ) -> List[SubtitleCue]:
        """Convenience helper to group raw Whisper word records into 2-4 word SubtitleCues."""
        cues = []
        if not words_data:
            return cues

        for i in range(0, len(words_data), chunk_size):
            group = words_data[i:i + chunk_size]
            s_time = group[0].get("start", 0.0)
            e_time = group[-1].get("end", s_time + 1.2)
            word_objs = [
                SubtitleWord(
                    word=g["word"],
                    start=g.get("start", 0.0),
                    end=g.get("end", 0.0)
                ) for g in group
            ]
            full_txt = " ".join(g["word"] for g in group)
            cues.append(SubtitleCue(
                cue_id=f"cue_{len(cues)+1}",
                start_time=s_time,
                end_time=e_time,
                text=full_txt,
                words=word_objs
            ))
        return cues
