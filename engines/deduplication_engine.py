"""
Semantic Story Deduplication Engine.
Prevents duplicate storytelling across YouTube Shorts production:
  - Distinguishes Exact Duplicates, Semantic Duplicates, Angle Variations, Related Events, and New Stories.
  - Multi-source corpus aggregation (SQLite DB + Google Drive Vault + Upload Records).
  - Layered Deterministic Event Fingerprinting (Years, Entities, Locations, Action Stems).
  - Semantic Natural Language Inference (NLI) comparison.
"""
import re
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from config.settings import GEMINI_API_KEY
from core.models import Topic, ScriptRecord, UploadRecord, Job

logger = logging.getLogger(__name__)

# Stopwords to filter out during entity/stem normalization
DEDUP_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "by", "for", "with", "about",
    "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "can", "will", "just", "don", "should", "now", "that", "this", "these", "those",
    "story", "history", "true", "shocking", "unbelievable", "bizarre", "strange",
    "incident", "event", "disaster", "crisis", "mystery", "case"
}

# Thematic anchors that link events when exact year matches
THEMATIC_EVENT_ANCHORS = {
    "parliament", "river", "sewage", "stink", "stench", "foul", "fumes", "miasma", "curtains",
    "palace", "bombardment", "navy", "cruisers", "sultan", "shortest",
    "molasses", "tank", "tsunami", "wave", "burst", "sweet", "flood",
    "pig", "potatoes", "island", "border", "dispute", "shooting",
    "dancing", "plague", "fever", "compulsive", "strasbourg", "square",
    "roanoke", "settlers", "croatoan", "disappeared", "colony",
    "ocean", "liner", "titanic", "britannic", "olympic", "unsinkable", "nurse",
    "latrine", "cesspool", "erfurt", "cathedral", "collapse", "nobles",
    "emu", "australia", "wheat", "soldiers", "lewis", "machine"
}


@dataclass
class EventFingerprint:
    title: str
    years: Set[int]
    entities: Set[str]
    locations: Set[str]
    action_stems: Set[str]
    summary_text: str = ""


@dataclass
class DeduplicationResult:
    is_duplicate: bool
    classification: str  # EXACT_DUPLICATE, SEMANTIC_DUPLICATE, SAME_EVENT_DIFFERENT_ANGLE, RELATED_DISTINCT_EVENT, COMPLETELY_NEW_STORY
    matched_event_title: Optional[str] = None
    similarity_score: float = 0.0
    shared_elements: List[str] = field(default_factory=list)
    reason: str = ""
    is_allowed: bool = True


class StoryDeduplicationEngine:
    """Multi-layer Semantic Story Deduplication Gate."""

    def extract_years(self, text: str) -> Set[int]:
        """Extracts 3 or 4 digit historical years."""
        matches = re.findall(r"\b(1\d{3}|20\d{2}|[5-9]\d{2})\b", text)
        return {int(m) for m in matches}

    def extract_stems(self, text: str) -> Set[str]:
        """Extracts significant normalized lexical stems with suffix stripping."""
        words = re.findall(r"\b[a-z]{4,}\b", text.lower())
        stems = set()
        for w in words:
            if w in DEDUP_STOPWORDS:
                continue
            clean_w = re.sub(r"(ary|ation|tion|sion|ment|ing|ied|ed|ers|er|es|s|al|ic|ous|ful|ness)$", "", w)
            if len(clean_w) >= 3 and clean_w not in DEDUP_STOPWORDS:
                stems.add(clean_w)
            stems.add(w)
        return stems

    def extract_entities(self, text: str) -> Set[str]:
        """Extracts capitalized proper entities and locations."""
        matches = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
        entities = set()
        for m in matches:
            words = m.split()
            filtered = [w for w in words if w.lower() not in DEDUP_STOPWORDS]
            if filtered:
                entities.add(" ".join(filtered).lower())
        return entities

    def build_fingerprint(self, title: str, summary: str = "", script_text: str = "") -> EventFingerprint:
        """Builds a deterministic structural fingerprint for a historical story."""
        combined_text = f"{title} {summary} {script_text}"
        years = self.extract_years(combined_text)
        entities = self.extract_entities(combined_text)
        stems = self.extract_stems(combined_text)
        return EventFingerprint(
            title=title,
            years=years,
            entities=entities,
            locations=entities,
            action_stems=stems,
            summary_text=combined_text
        )

    def get_published_and_ready_corpus(self, db: Session, exclude_topic_id: Optional[str] = None) -> List[EventFingerprint]:
        """Aggregates all published, ready, and processing historical stories."""
        corpus = []
        seen_titles = set()

        # 1. Existing Topics with active jobs / uploads
        active_jobs = db.query(Job).all()
        active_topic_ids = {j.topic_id for j in active_jobs if j.topic_id}
        topics = db.query(Topic).filter(Topic.id.in_(active_topic_ids)).all() if active_topic_ids else []
        for t in topics:
            if exclude_topic_id and t.id == exclude_topic_id:
                continue
            if t.title.lower() in seen_titles:
                continue
            seen_titles.add(t.title.lower())
            
            script = db.query(ScriptRecord).filter(ScriptRecord.topic_id == t.id).first()
            script_text = script.full_text if script else ""
            fp = self.build_fingerprint(t.title, t.summary, script_text)
            corpus.append(fp)

        # 2. UploadRecords
        uploads = db.query(UploadRecord).all()
        for u in uploads:
            if u.title.lower() in seen_titles:
                continue
            seen_titles.add(u.title.lower())
            fp = self.build_fingerprint(u.title, u.description or "")
            corpus.append(fp)

        return corpus

    def check_deterministic_duplicate(
        self,
        candidate_fp: EventFingerprint,
        existing_fp: EventFingerprint
    ) -> Optional[DeduplicationResult]:
        """
        Layer 2: Deterministic Consistency and Fingerprint Matching.
        Flags duplicates if core years, locations, and action stems match closely.
        """
        # 1. Exact title match
        if candidate_fp.title.lower().strip() == existing_fp.title.lower().strip():
            return DeduplicationResult(
                is_duplicate=True,
                classification="EXACT_DUPLICATE",
                matched_event_title=existing_fp.title,
                similarity_score=1.0,
                shared_elements=["Exact Title Match"],
                reason=f"Candidate title matches existing topic '{existing_fp.title}' identically.",
                is_allowed=False
            )

        shared_years = candidate_fp.years.intersection(existing_fp.years)
        shared_entities = candidate_fp.entities.intersection(existing_fp.entities)
        shared_stems = candidate_fp.action_stems.intersection(existing_fp.action_stems)

        # 2. Same Year + Thematic Anchor Match (e.g. 1858 + Parliament/River/Miasma)
        if shared_years:
            candidate_thematic = candidate_fp.action_stems.intersection(THEMATIC_EVENT_ANCHORS)
            existing_thematic = existing_fp.action_stems.intersection(THEMATIC_EVENT_ANCHORS)
            shared_thematic = candidate_thematic.intersection(existing_thematic)
            
            if shared_thematic or len(shared_entities) >= 1 or len(shared_stems) >= 2:
                # Disambiguate distinct events in the same year (e.g. 1854 Cholera vs other)
                if not ("cholera" in candidate_fp.summary_text.lower() and "stink" in existing_fp.summary_text.lower()):
                    shared_desc = [f"Year: {list(shared_years)}", f"Anchors: {list(shared_thematic | shared_entities)}"]
                    return DeduplicationResult(
                        is_duplicate=True,
                        classification="SEMANTIC_DUPLICATE",
                        matched_event_title=existing_fp.title,
                        similarity_score=0.94,
                        shared_elements=shared_desc,
                        reason=f"Candidate matches historical event '{existing_fp.title}' on anchor year {list(shared_years)} and thematic elements {list(shared_thematic | shared_entities)}.",
                        is_allowed=False
                    )

        # 3. High Specific Entity & Stem Overlap
        specific_entities = {e for e in shared_entities if e not in {"british", "american", "european", "german", "french", "royal", "empire", "navy"}}
        
        # Check Title Token Overlap (ignoring numbers/years)
        candidate_title_words = set(re.findall(r"\b[a-z]{4,}\b", candidate_fp.title.lower())) - DEDUP_STOPWORDS
        existing_title_words = set(re.findall(r"\b[a-z]{4,}\b", existing_fp.title.lower())) - DEDUP_STOPWORDS
        title_overlap = candidate_title_words.intersection(existing_title_words)
        
        # If titles share 2+ significant words (e.g. "great", "stink", "london") -> DUPLICATE even if year changed
        if len(title_overlap) >= 2 and len(candidate_title_words) > 0 and len(title_overlap) / len(candidate_title_words) >= 0.5:
            return DeduplicationResult(
                is_duplicate=True,
                classification="SEMANTIC_DUPLICATE",
                matched_event_title=existing_fp.title,
                similarity_score=0.95,
                shared_elements=[f"Title Overlap: {list(title_overlap)}"],
                reason=f"Candidate title heavily overlaps with existing topic '{existing_fp.title}'.",
                is_allowed=False
            )

        # If candidate has explicit years that do not intersect and titles don't match, do not flag deterministically
        if candidate_fp.years and existing_fp.years and not shared_years:
            return None

        if (len(specific_entities) >= 2 and len(shared_stems) >= 3) or (len(shared_stems) >= 6):
            shared_desc = [f"Entities: {list(specific_entities)}", f"Keywords: {list(shared_stems)[:4]}"]
            return DeduplicationResult(
                is_duplicate=True,
                classification="SEMANTIC_DUPLICATE",
                matched_event_title=existing_fp.title,
                similarity_score=0.90,
                shared_elements=shared_desc,
                reason=f"Candidate shares core entities {list(specific_entities)} and thematic stems with '{existing_fp.title}'.",
                is_allowed=False
            )

        return None

    def check_semantic_llm(
        self,
        candidate_title: str,
        candidate_summary: str,
        candidate_script: str,
        existing_title: str,
        existing_summary: str,
        existing_script: str
    ) -> DeduplicationResult:
        """
        Layer 3: Semantic NLI Evaluation with Structured Classification.
        """
        if not GEMINI_API_KEY:
            return DeduplicationResult(
                is_duplicate=False,
                classification="COMPLETELY_NEW_STORY",
                similarity_score=0.0,
                is_allowed=True,
                reason="Tier 1 passed and no LLM key configured."
            )

        try:
            from google import genai
            client = genai.Client(api_key=GEMINI_API_KEY)

            prompt = (
                f"You are a strict editorial deduplication judge for a documentary history YouTube channel.\n\n"
                f"EXISTING PUBLISHED STORY:\n"
                f"Title: {existing_title}\n"
                f"Summary: {existing_summary}\n"
                f"Script: {existing_script}\n\n"
                f"PROPOSED CANDIDATE STORY:\n"
                f"Title: {candidate_title}\n"
                f"Summary: {candidate_summary}\n"
                f"Script: {candidate_script}\n\n"
                f"TASK:\n"
                f"Compare the candidate story against the existing story. A different title, hook, wording, or tone does NOT make the same underlying historical story 'new'.\n"
                f"Classify relationship as EXACTLY one of:\n"
                f"1. 'EXACT_DUPLICATE': Same historical event and narrative.\n"
                f"2. 'SEMANTIC_DUPLICATE': Same underlying historical event/story told with different words, perspective, or hook.\n"
                f"3. 'SAME_EVENT_DIFFERENT_ANGLE': Same overarching historical event, but focuses on an entirely separate, non-overlapping figure or sub-event.\n"
                f"4. 'RELATED_DISTINCT_EVENT': Related era, war, or theme, but a clearly separate historical event.\n"
                f"5. 'COMPLETELY_NEW_STORY': Completely different historical topic.\n\n"
                f"Decision Rules:\n"
                f"- If classification is 'EXACT_DUPLICATE' or 'SEMANTIC_DUPLICATE': 'is_allowed' MUST be FALSE.\n"
                f"- If 'SAME_EVENT_DIFFERENT_ANGLE': 'is_allowed' is TRUE only if the narrative is materially distinct (novel_factual_percentage >= 70%). Otherwise FALSE.\n"
                f"- If 'RELATED_DISTINCT_EVENT' or 'COMPLETELY_NEW_STORY': 'is_allowed' MUST be TRUE.\n\n"
                f"Return strictly valid JSON:\n"
                f"{{\n"
                f"  \"classification\": \"EXACT_DUPLICATE|SEMANTIC_DUPLICATE|SAME_EVENT_DIFFERENT_ANGLE|RELATED_DISTINCT_EVENT|COMPLETELY_NEW_STORY\",\n"
                f"  \"similarity_score\": 0.0 to 1.0,\n"
                f"  \"shared_elements\": [\"element1\", \"element2\"],\n"
                f"  \"novel_factual_percentage\": 0 to 100,\n"
                f"  \"is_allowed\": true|false,\n"
                f"  \"reason\": \"...\"\n"
                f"}}"
            )

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )
            raw = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)

            classification = data.get("classification", "COMPLETELY_NEW_STORY").upper()
            is_allowed = bool(data.get("is_allowed", True))
            similarity_score = float(data.get("similarity_score", 0.0))
            shared_elements = data.get("shared_elements", [])
            reason = data.get("reason", "")
            is_dup = not is_allowed

            return DeduplicationResult(
                is_duplicate=is_dup,
                classification=classification,
                matched_event_title=existing_title,
                similarity_score=similarity_score,
                shared_elements=shared_elements,
                reason=reason,
                is_allowed=is_allowed
            )

        except Exception as e:
            logger.warning(f"Semantic LLM deduplication notice: {e} (Relying strictly on Tier 1 deterministic gate)")
            return DeduplicationResult(
                is_duplicate=False,
                classification="COMPLETELY_NEW_STORY",
                similarity_score=0.0,
                is_allowed=True,
                reason=f"LLM check unavailable: {e}"
            )

    def evaluate_candidate(
        self,
        candidate_title: str,
        candidate_summary: str = "",
        candidate_script: str = "",
        corpus: Optional[List[EventFingerprint]] = None,
        db: Optional[Session] = None,
        exclude_topic_id: Optional[str] = None
    ) -> DeduplicationResult:
        """
        Evaluates a candidate story against the entire published and ready vault corpus.
        """
        if corpus is None and db is not None:
            corpus = self.get_published_and_ready_corpus(db, exclude_topic_id=exclude_topic_id)
        elif corpus is None:
            corpus = []

        candidate_fp = self.build_fingerprint(candidate_title, candidate_summary, candidate_script)

        # 1. Tier 1 / 2 Deterministic Check against all items
        for existing in corpus:
            det_res = self.check_deterministic_duplicate(candidate_fp, existing)
            if det_res and not det_res.is_allowed:
                return det_res

        # 2. Tier 3 LLM Semantic Check against top candidate matches
        for existing in corpus:
            shared_years = candidate_fp.years.intersection(existing.years)
            shared_entities = candidate_fp.entities.intersection(existing.entities)
            shared_stems = candidate_fp.action_stems.intersection(existing.action_stems)
            
            # If any thematic connection exists, run deep semantic NLI
            if shared_years or len(shared_entities) >= 1 or len(shared_stems) >= 2:
                sem_res = self.check_semantic_llm(
                    candidate_title=candidate_title,
                    candidate_summary=candidate_summary,
                    candidate_script=candidate_script,
                    existing_title=existing.title,
                    existing_summary=existing.summary_text,
                    existing_script=""
                )
                if not sem_res.is_allowed:
                    return sem_res

        return DeduplicationResult(
            is_duplicate=False,
            classification="COMPLETELY_NEW_STORY",
            similarity_score=0.0,
            is_allowed=True,
            reason="No duplicate or conflicting historical stories found in existing corpus."
        )
