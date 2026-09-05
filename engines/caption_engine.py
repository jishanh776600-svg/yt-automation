"""
Caption Engine.
Uses Faster-Whisper to generate accurate word-level timestamps.
Renders stylized ASS subtitle streams placed in safe zones with dynamic word highlighting
and semantic punch-word emphasis.
"""
import uuid
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from faster_whisper import WhisperModel
from config.settings import CAPTIONS_DIR
from config.constants import VIDEO_WIDTH, VIDEO_HEIGHT

logger = logging.getLogger(__name__)


class CaptionEngine:
    """Extracts word-level timestamps and produces modern, vertical Shorts subtitles."""

    def __init__(self, model_size: str = "base"):
        self.captions_dir = CAPTIONS_DIR
        self.captions_dir.mkdir(parents=True, exist_ok=True)
        self.model_size = model_size
        self._model = None

    def _get_whisper_model(self) -> WhisperModel:
        if self._model is None:
            logger.info(f"Loading faster-whisper model ({self.model_size}) on CPU...")
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe_words(self, audio_path: Path) -> List[Dict[str, Any]]:
        """Extracts word-level timestamp entries."""
        model = self._get_whisper_model()
        segments, _ = model.transcribe(str(audio_path), word_timestamps=True, language="en")

        words = []
        for segment in segments:
            if segment.words:
                for w in segment.words:
                    clean_w = w.word.strip()
                    if clean_w:
                        words.append({
                            "word": clean_w,
                            "start": round(w.start, 2),
                            "end": round(w.end, 2)
                        })
            else:
                text_words = segment.text.strip().split()
                dur = (segment.end - segment.start) / max(len(text_words), 1)
                for idx, tw in enumerate(text_words):
                    if tw.strip():
                        words.append({
                            "word": tw.strip(),
                            "start": round(segment.start + (idx * dur), 2),
                            "end": round(segment.start + ((idx + 1) * dur), 2)
                        })
        return words

    def generate_ass_subtitles(
        self,
        audio_path: Path,
        output_path: Optional[Path] = None,
        editing_plan: Optional[Any] = None
    ) -> Path:
        """
        Builds modern ASS subtitle file with karaoke style active-word highlighting
        and semantic emphasis in the vertical safe zone.
        """
        words = self.transcribe_words(audio_path)
        if not output_path:
            output_path = self.captions_dir / f"subs_{uuid.uuid4().hex[:8]}.ass"

        # Chunk into 2-3 words per caption display for punchy Shorts readability
        chunks = []
        chunk_size = 3
        for i in range(0, len(words), chunk_size):
            group = words[i:i + chunk_size]
            if group:
                chunks.append(group)

        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_WIDTH}
PlayResY: {VIDEO_HEIGHT}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,86,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,8,4,2,60,60,500,1
Style: Punch,Arial Black,90,&H0000D7FF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,110,110,0,0,1,9,5,2,60,60,500,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events = []

        def fmt_time(t: float) -> str:
            hours = int(t // 3600)
            mins = int((t % 3600) // 60)
            secs = int(t % 60)
            csecs = int(round((t - int(t)) * 100))
            if csecs >= 100:
                csecs = 99
            return f"{hours}:{mins:02d}:{secs:02d}.{csecs:02d}"

        punch_keywords = {
            "DISASTER", "EXPLOSION", "WAR", "MYSTERY", "SHOCKING", "SECRET", "DEADLY",
            "CATACLYSM", "UNBELIEVABLE", "TRAGEDY", "COLLAPSE", "BATTLE", "MASSIVE",
            "UNEXPLAINED", "CRISIS", "ELECTION", "SABOTAGE", "SUBMARINE", "SURVEILLANCE",
            "SCANDAL", "ESCORT", "DRILLING", "DISPUTE", "COALITION", "SHOCKWAVES", "NATO", "BERLIN"
        }

        for group in chunks:
            if not group:
                continue
            for idx, target_w in enumerate(group):
                w_start = target_w["start"]
                if idx < len(group) - 1:
                    w_end = max(w_start + 0.1, group[idx + 1]["start"])
                else:
                    w_end = max(w_start + 0.15, target_w["end"])

                s_fmt = fmt_time(w_start)
                e_fmt = fmt_time(w_end)

                # Render cluster with active word highlighted
                line_elements = []
                for j, w in enumerate(group):
                    w_text = w["word"].upper()
                    clean_punct = "".join([c for c in w_text if c.isalnum()])
                    if j == idx:
                        # Active spoken word: vibrant gold pop with 115% scale
                        if clean_punct in punch_keywords or any(c.isdigit() for c in clean_punct):
                            line_elements.append(f"{{\\c&H0000FFFF&\\fscx115\\fscy115}}{w_text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                        else:
                            line_elements.append(f"{{\\c&H0000D7FF&\\fscx115\\fscy115}}{w_text}{{\\c&H00FFFFFF&\\fscx100\\fscy100}}")
                    else:
                        line_elements.append(f"{{\\c&H00E0E0E0&\\fscx100\\fscy100}}{w_text}{{\\c&H00FFFFFF&}}")

                full_line_text = " ".join(line_elements)
                event_line = f"Dialogue: 0,{s_fmt},{e_fmt},Default,,0,0,0,,{full_line_text}"
                events.append(event_line)

        ass_content = ass_header + "\n".join(events) + "\n"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        logger.info(f"Generated enhanced ASS subtitles at {output_path}")
        return output_path
