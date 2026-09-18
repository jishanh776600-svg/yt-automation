"""
SEO & Metadata Engine.
Generates curiosity-driven, factual, topic-specific titles, concise contextual descriptions,
and 3-5 targeted, relevant hashtags derived from content intelligence without keyword stuffing.
For all new uploads, YouTube tags are strictly omitted/empty.
"""
import logging
import re
from typing import Dict, List, Any, Optional
from core.models import Topic, ScriptRecord

logger = logging.getLogger(__name__)


class SEOEngine:
    """Generates optimized, viewer-facing metadata adhering strictly to YouTube guidelines."""

    @staticmethod
    def clean_public_text(text: str) -> str:
        """
        Removes all internal production identifiers (job IDs, run IDs, manifest IDs,
        event IDs, UUIDs, telemetry headers) from public text.
        """
        if not text:
            return ""
        # 1. Bracketed internal tags like [JOB_ID: ...] or [RUN_ID: ...]
        cleaned = re.sub(
            r"\[(JOB_ID|RUN_ID|MANIFEST_ID|EVENT_ID|PIPELINE_ID|DRIVE_ID|VAULT_ID)[^\]]*\]",
            "",
            text,
            flags=re.IGNORECASE
        )
        # 2. Standalone internal ID tokens (job_..., upl_..., manrec_..., rnd_..., evt_...)
        cleaned = re.sub(r"\b(job|upl|manrec|man|rnd|evt)_[a-zA-Z0-9_-]+\b", "", cleaned)
        # 3. Standard UUIDs
        cleaned = re.sub(
            r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
            "",
            cleaned,
            flags=re.IGNORECASE
        )
        # 4. Remove internal markdown artifacts / asterisks
        cleaned = re.sub(r"\*{2,}", "", cleaned)
        # 5. Clean up redundant whitespace and excessive newlines
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def generate_metadata(self, topic: Any, script: Any = None) -> Dict[str, Any]:
        """
        Creates topic-specific, curiosity-driven titles, natural narrative descriptions
        with primary topic early, 3-5 relevant hashtags, and strictly empty tags.
        """
        # Extract title and summary safely from Topic object, dict, or string
        raw_title = ""
        summary = ""
        category = "History"

        if isinstance(topic, str):
            raw_title = topic
        elif isinstance(topic, dict):
            raw_title = topic.get("title", "")
            summary = topic.get("summary") or topic.get("description", "")
            category = topic.get("category", "History")
        elif topic is not None:
            raw_title = getattr(topic, "title", "") or ""
            summary = getattr(topic, "summary", "") or ""
            category = getattr(topic, "category", "History") or "History"

        clean_topic_title = self.clean_public_text(raw_title)
        # Strip redundant cliches from raw title if present
        clean_topic_title = re.sub(r"\s+Was Truly Unbelievable.*$", "", clean_topic_title, flags=re.IGNORECASE).strip()

        # Extract script text
        script_text = ""
        if isinstance(script, str):
            script_text = script
        elif isinstance(script, dict):
            script_text = script.get("full_text") or script.get("script_text", "")
        elif script is not None:
            script_text = getattr(script, "full_text", "") or getattr(script, "script_text", "") or ""
        script_text = self.clean_public_text(script_text)

        # 1. Topic-Specific, Concise, Curiosity-Driven Title (<= 70 chars)
        selected_title = self._craft_title(clean_topic_title, summary, category)
        if len(selected_title) > 70:
            selected_title = selected_title[:67].rstrip() + "..."

        # 2. Natural Viewer-Facing Description (2-4 sentences, primary topic early)
        description = self._craft_description(clean_topic_title, summary, script_text, category)

        # 3. 3-5 Targeted, Relevant Hashtags
        hashtags = self._craft_hashtags(clean_topic_title, category, script_text)

        # Append hashtags to description
        full_description = f"{description}\n\n{' '.join(hashtags)}".strip()
        full_description = self.clean_public_text(full_description)

        # 4. Strictly NO YouTube Tags for new uploads
        tags: List[str] = []

        logger.info(f"Generated Content-Driven SEO Title: '{selected_title}'")
        return {
            "title": selected_title,
            "description": full_description,
            "tags": tags,
            "hashtags": hashtags
        }

    def _craft_title(self, topic_title: str, summary: str, category: str) -> str:
        """Crafts a concise, natural, curiosity-driven title without keyword stuffing."""
        if not topic_title:
            return "A Fascinating Mystery Explained"

        # Check curated overrides for famous specific events
        low = topic_title.lower()
        if "38-minute" in low or "shortest war" in low:
            return "The War That Lasted Only 38 Minutes"
        if "great stink" in low or ("stink" in low and "london" in low):
            return "The Summer London's Smell Shut Down Parliament"
        if "molasses" in low and ("boston" in low or "flood" in low):
            return "The 35-MPH Boiling Molasses Tsunami of Boston"
        if "baarle" in low:
            return "The European Town With Borders Through Living Rooms"
        if "pig war" in low:
            return "How a Pig Almost Caused War Between the US and UK"
        if "roanoke" in low:
            return "The 115 Settlers Who Disappeared Without a Trace"
        if "dancing plague" in low:
            return "The 1518 Plague Where Hundreds Danced to Death"
        if "violet jessop" in low or ("violet" in low and "ocean liner" in low):
            return "The Woman Who Survived 3 Sinking Ocean Liners"
        if "emu war" in low:
            return "The Great Emu War Was Actually Real"
        if "kentucky meat shower" in low:
            return "The Bizarre 1876 Kentucky Meat Shower Mystery"
        if "karansebes" in low:
            return "The Battle Where an Army Fought Itself"
        if "lake peigneur" in low:
            return "The Day a Lake Vanished Down a Salt Mine"

        # If title is already curiosity-driven or descriptive and concise, keep it clean
        if 15 <= len(topic_title) <= 65 and not topic_title.endswith(":"):
            return topic_title

        # Natural curiosity framing based on category/subject
        if "mystery" in category.lower() or "mystery" in low or "unexplained" in low:
            candidate = f"The Bizarre Mystery of {topic_title}"
        elif "science" in category.lower():
            candidate = f"The Bizarre Science Behind {topic_title}"
        else:
            candidate = f"The True Story of {topic_title}"

        if len(candidate) <= 70:
            return candidate

        return topic_title[:70].rstrip()

    def _craft_description(
        self,
        topic_title: str,
        summary: str,
        script_text: str,
        category: str
    ) -> str:
        """
        Synthesizes a 2-4 sentence narrative description placing the core topic
        naturally in the first 1-2 sentences. Zero generic boilerplate or dumps.
        """
        # Derive core narrative from script text or summary
        sentences: List[str] = []

        source_text = script_text or summary or ""
        if source_text:
            # Extract distinct sentences
            raw_sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", source_text) if len(s.strip()) > 15]
            for s in raw_sents:
                cleaned_s = self.clean_public_text(s)
                # Skip any lines that look like headers or speaker cues
                if cleaned_s and not cleaned_s.lower().startswith(("narrator:", "hook:", "scene", "shot")):
                    sentences.append(cleaned_s)
                if len(sentences) >= 3:
                    break

        if not sentences and summary:
            sentences.append(self.clean_public_text(summary))

        # Ensure primary topic appears naturally in first 1-2 sentences
        combined_head = " ".join(sentences[:2]).lower() if sentences else ""
        if topic_title and topic_title.lower() not in combined_head:
            intro = f"The true story of {topic_title} reveals one of history's most fascinating real-world events."
            sentences.insert(0, intro)

        # Fallback if no text was available
        if not sentences:
            sentences = [
                f"The documented story behind {topic_title} remains one of the most unusual events ever recorded.",
                "Here is how it unfolded and why it still captivates historians today."
            ]

        # Limit to 2 to 4 concise sentences
        final_sentences = sentences[:3]
        return " ".join(final_sentences)

    def _craft_hashtags(self, topic_title: str, category: str, script_text: str) -> List[str]:
        """Generates 3 to 5 targeted, highly relevant hashtags derived from topic entities."""
        tags = []

        # 1. Base Niche/Category Hashtag
        cat_low = category.lower()
        if "science" in cat_low:
            tags.append("#Science")
        elif "mystery" in cat_low:
            tags.append("#Mystery")
        else:
            tags.append("#History")

        # 2. Extract Specific Entity Hashtags from Topic Title
        words = re.findall(r"[A-Z][a-zA-Z0-9]+|[a-zA-Z0-9]+", topic_title)
        stop_words = {
            "the", "of", "and", "a", "an", "in", "on", "at", "to", "for", "with",
            "was", "is", "were", "are", "behind", "how", "why", "what", "that",
            "story", "history", "mystery", "bizarre", "true", "short", "shorts"
        }
        topic_entities = [w for w in words if w.lower() not in stop_words and len(w) > 2]

        # Multi-word CamelCase entity from title if title is short (e.g. GreatEmuWar)
        clean_slug = "".join([w.capitalize() for w in topic_entities[:3]])
        if clean_slug and len(clean_slug) > 3:
            tags.append(f"#{clean_slug}")

        # Add 1-2 individual distinct entities (e.g. Australia, Emu, London, Molasses)
        for entity in topic_entities:
            tag = f"#{entity.capitalize()}"
            if tag not in tags and len(tags) < 4:
                tags.append(tag)

        # 3. Relevant context tag if needed to reach 3-5
        low_text = f"{topic_title} {script_text}".lower()
        context_candidates = [
            ("australia", "#Australia"),
            ("london", "#London"),
            ("boston", "#Boston"),
            ("paris", "#Paris"),
            ("tokyo", "#Tokyo"),
            ("dinosaur", "#Paleontology"),
            ("fossil", "#Fossils"),
            ("crocodile", "#Wildlife"),
            ("ship", "#Maritime"),
            ("ocean", "#Maritime"),
            ("war", "#MilitaryHistory"),
            ("space", "#Astronomy"),
            ("ancient", "#Archaeology"),
            ("unexplained", "#Unexplained"),
            ("documentary", "#Documentary"),
        ]
        for keyword, cand_tag in context_candidates:
            if keyword in low_text and cand_tag not in tags and len(tags) < 5:
                tags.append(cand_tag)

        # Ensure minimum 3 hashtags
        if len(tags) < 3:
            default_candidates = ["#Documentary", "#TrueStory", "#Facts"]
            for d in default_candidates:
                if d not in tags and len(tags) < 3:
                    tags.append(d)

        # Cap strictly at 5 hashtags
        return tags[:5]

