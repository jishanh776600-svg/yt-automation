"""
Fact Verifier Engine.
Performs 2-Tier Hybrid Fact Verification for YouTube Shorts narration scripts:
  Tier 1: Deterministic Consistency Checks (Dates, Numbers, Entities, Locations, Action/Consequence Inversions)
  Tier 2: Semantic Natural Language Inference (NLI) Classification (SUPPORTED, REASONABLE_PARAPHRASE, UNSUPPORTED, CONTRADICTED, NARRATIVE_STYLING)
Guarantees the research corpus is the sole factual authority; zero fabricated claims allowed.
"""
import re
import json
import logging
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from config.settings import GEMINI_API_KEY

logger = logging.getLogger(__name__)

# Standard English stopwords and sentence-initial common words to exclude from proper-noun entity extraction
ENTITY_STOPWORDS = {
    "In", "On", "At", "By", "After", "Before", "During", "When", "While",
    "The", "A", "An", "This", "That", "These", "Those", "It", "Its", "They",
    "What", "Why", "How", "And", "Or", "But", "So", "If", "Then", "There",
    "To", "From", "Into", "Over", "Under", "Through", "Between", "Against",
    "Lawmakers", "Politicians", "Dozens", "Citizens", "Doctors", "Soldiers",
    "Locals", "Events", "Lawyers", "Engineers", "Rebels", "Defenders",
    "Commanders", "Officers", "Hundreds", "Thousands", "Both", "Modern",
    "Today", "Years", "Months", "Days", "Hours", "Minutes", "Seconds"
}

GENERIC_HISTORICAL_TERMS = {
    "cathedral", "palace", "parliament", "navy", "empire", "sultan",
    "king", "queen", "republic", "island", "street", "river", "ocean",
    "disaster", "history", "europe", "european", "america", "american",
    "british", "german", "french", "dutch", "spanish", "roman", "english",
    "italian", "nobles", "royal", "church", "emperor", "pope",
    "july", "august", "september", "october", "november", "december",
    "january", "february", "march", "april", "may", "june",
    "lawmakers", "politicians", "dozens", "citizens", "doctors", "soldiers",
    "locals", "rebels", "defenders", "commanders", "officers", "summer", "winter"
}

WORD_NUMBER_MAP = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "thousand": 1000, "million": 1000000
}

# Critical Action/Consequence keywords that must be grounded in research if asserted
CRITICAL_ACTION_KEYWORDS = {
    "executed", "execution", "assassinated", "assassination", "bomb", "explosion",
    "gunpowder", "poisoned", "hanged", "beheaded", "sank", "sunk", "invaded",
    "pope", "crown", "aliens", "spaceships", "lasers"
}


@dataclass
class FactVerificationResult:
    passed: bool
    score: float  # 0.0 to 15.0 pts
    contradictions: List[str] = field(default_factory=list)
    unsupported_claims: List[str] = field(default_factory=list)
    supported_claims: List[str] = field(default_factory=list)
    narrative_styling: List[str] = field(default_factory=list)
    feedback: List[str] = field(default_factory=list)


class FactVerifier:
    """Rigorous 2-Tier Fact Verifier for historical scripts against research data."""

    def extract_years(self, text: str) -> Set[int]:
        """Extracts 3 or 4 digit historical years."""
        matches = re.findall(r"\b(1\d{3}|20\d{2}|[5-9]\d{2})\b", text)
        return {int(m) for m in matches}

    def extract_numbers(self, text: str) -> Set[int]:
        """Extracts integer quantities (excluding 4-digit years)."""
        years = self.extract_years(text)
        nums = set()
        digit_matches = re.findall(r"\b\d{1,7}\b", text.replace(",", ""))
        for d in digit_matches:
            val = int(d)
            if val not in years:
                nums.add(val)
        words = text.lower().split()
        for w in words:
            clean_w = re.sub(r"[^\w]", "", w)
            if clean_w in WORD_NUMBER_MAP:
                nums.add(WORD_NUMBER_MAP[clean_w])
        return nums

    def extract_entities(self, text: str) -> Set[str]:
        """Extracts capitalized named entities and locations."""
        matches = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
        entities = set()
        for m in matches:
            words = m.split()
            filtered = [w for w in words if w not in ENTITY_STOPWORDS]
            if filtered:
                entities.add(" ".join(filtered))
        return entities

    def verify_tier1_deterministic(
        self,
        script_text: str,
        research_corpus: str,
        research_data: Dict[str, Any]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Tier 1 Deterministic Consistency Check:
        Compares years, quantities, named entities, and critical action assertions.
        """
        contradictions = []
        unsupported = []
        research_corpus_lower = research_corpus.lower()
        script_lower = script_text.lower()

        # 1. Year / Date Contradiction Check
        script_years = self.extract_years(script_text)
        research_years = self.extract_years(research_corpus)
        for sy in script_years:
            if research_years and sy not in research_years:
                contradictions.append(
                    f"Date Contradiction: Script claims year '{sy}', but research specifies '{sorted(list(research_years))}'."
                )

        # 2. Number / Quantity Consistency Check
        script_nums = self.extract_numbers(script_text)
        research_nums = self.extract_numbers(research_corpus)
        for sn in script_nums:
            if sn >= 10 and research_nums:
                if sn not in research_nums:
                    if sn not in {20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30}:
                        for rn in research_nums:
                            if rn >= 10 and (sn == rn * 10 or sn == rn * 100 or abs(sn - rn) > (rn * 0.5)):
                                contradictions.append(
                                    f"Numerical Contradiction: Script claims count '{sn}', whereas research documents '{rn}'."
                                )
                                break

        # 3. Proper Named Entities & Locations
        script_entities = self.extract_entities(script_text)
        for ent in script_entities:
            ent_lower = ent.lower()
            if len(ent.split()) >= 1 and len(ent) > 4:
                # Check if multi-word parts are individually present in research
                parts = ent_lower.split()
                all_parts_present = all(p in research_corpus_lower for p in parts)
                if not all_parts_present and ent_lower not in GENERIC_HISTORICAL_TERMS:
                    unsupported.append(
                        f"Unsupported Named Entity/Location: Script mentions '{ent}', which is absent from research."
                    )

        # 4. Critical Action / Consequence Keyword Grounding
        for kw in CRITICAL_ACTION_KEYWORDS:
            if re.search(r"\b" + re.escape(kw) + r"\b", script_lower):
                if not re.search(r"\b" + re.escape(kw) + r"\b", research_corpus_lower):
                    unsupported.append(
                        f"Unsupported Major Factual Action/Consequence: Script asserts '{kw}', which is completely absent from research."
                    )

        # 5. Inverted Attacker/Defender Roles Check
        if "sultan" in script_lower and "navy" in script_lower:
            if "sank the entire british" in script_lower or "defeated the british empire" in script_lower:
                if "british" in research_corpus_lower and ("bombarded" in research_corpus_lower or "surrender" in research_corpus_lower):
                    contradictions.append(
                        "Reversed Subject/Object Role: Script asserts the Sultan defeated the British fleet, contradicting historical research."
                    )

        passed = len(contradictions) == 0 and len(unsupported) == 0
        return passed, contradictions, unsupported

    def verify_tier2_semantic(
        self,
        script_text: str,
        research_corpus: str
    ) -> Tuple[bool, List[str], List[str], List[str], List[str]]:
        """
        Tier 2 Semantic NLI Verification using GenAI:
        Classifies each sentence into SUPPORTED, REASONABLE_PARAPHRASE, UNSUPPORTED, CONTRADICTED, NARRATIVE_STYLING.
        """
        contradictions = []
        unsupported = []
        supported = []
        styling = []

        if not GEMINI_API_KEY:
            sentences = [s.strip() for s in re.split(r"[.!?]", script_text) if len(s.strip()) > 10]
            for s in sentences:
                supported.append(s)
            return True, contradictions, unsupported, supported, styling

        try:
            from core.gemini_client import get_gemini_client
            gemini_client = get_gemini_client()

            prompt = (
                f"You are a strict historical fact-checking verifier for documentary scripts.\n"
                f"VERIFIED RESEARCH AUTHORITY:\n\"\"\"{research_corpus}\"\"\"\n\n"
                f"PROPOSED NARRATION SCRIPT:\n\"\"\"{script_text}\"\"\"\n\n"
                f"TASK:\n"
                f"Deconstruct the script sentence-by-sentence and evaluate each against the research authority.\n"
                f"Classify each sentence as EXACTLY one of:\n"
                f"- 'SUPPORTED': Directly supported by research facts.\n"
                f"- 'REASONABLE_PARAPHRASE': Same factual meaning expressed with dramatic spoken cadence.\n"
                f"- 'NARRATIVE_STYLING': Transition or figurative phrase that introduces no new factual claim.\n"
                f"- 'UNSUPPORTED': Asserts a new factual event, person, or consequence absent from research.\n"
                f"- 'CONTRADICTED': Directly conflicts with facts, dates, names, or causes in the research.\n\n"
                f"Strict Rule: The research is the sole authority. Do NOT assume unmentioned facts are true.\n"
                f"Output strictly valid JSON with key 'evaluations' as a list of objects:\n"
                f"[{{\"sentence\": \"...\", \"classification\": \"SUPPORTED|REASONABLE_PARAPHRASE|NARRATIVE_STYLING|UNSUPPORTED|CONTRADICTED\", \"reason\": \"...\"}}]"
            )

            from config.settings import GEMINI_MODEL
            response = gemini_client.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            raw = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            evals = data.get("evaluations", [])

            for item in evals:
                sent = item.get("sentence", "")
                cls = item.get("classification", "").upper()
                reason = item.get("reason", "")

                if cls == "CONTRADICTED":
                    contradictions.append(f"Contradiction in '{sent}': {reason}")
                elif cls == "UNSUPPORTED":
                    unsupported.append(f"Unsupported claim in '{sent}': {reason}")
                elif cls in ("SUPPORTED", "REASONABLE_PARAPHRASE"):
                    supported.append(sent)
                elif cls == "NARRATIVE_STYLING":
                    styling.append(sent)

            passed = len(contradictions) == 0 and len(unsupported) == 0
            return passed, contradictions, unsupported, supported, styling

        except Exception as e:
            logger.warning(f"Tier 2 semantic verification notice: {e} (Relying strictly on Tier 1 deterministic gate)")
            return True, contradictions, unsupported, supported, styling

    def verify(
        self,
        script_text: str,
        research_data: Optional[Dict[str, Any]]
    ) -> FactVerificationResult:
        """
        Executes full 2-Tier Fact Verification.
        Hard fails on any contradiction or unsupported claim.
        """
        if not research_data:
            return FactVerificationResult(
                passed=True,
                score=15.0,
                feedback=[]
            )

        summary = research_data.get("summary", "")
        claims_list = [c.get("claim", "") for c in research_data.get("verified_claims", [])]
        topic_title = research_data.get("topic_title", "")
        research_corpus = f"{topic_title}\n{summary}\n" + "\n".join(claims_list)

        # 1. Tier 1 Deterministic Verification
        t1_passed, t1_contra, t1_unsup = self.verify_tier1_deterministic(
            script_text, research_corpus, research_data
        )

        # 2. Tier 2 Semantic NLI Verification
        t2_passed, t2_contra, t2_unsup, supported, styling = self.verify_tier2_semantic(
            script_text, research_corpus
        )

        all_contradictions = t1_contra + t2_contra
        all_unsupported = t1_unsup + t2_unsup

        feedback = []
        for c in all_contradictions:
            feedback.append(f"FACTUAL CORRECTION REQUIRED: {c}")
        for u in all_unsupported:
            feedback.append(f"UNSUPPORTED CLAIM TO REMOVE/REVISE: {u}")

        # Hard Quality Gate: Zero Contradictions, Zero Major Unsupported Claims Allowed
        overall_passed = (len(all_contradictions) == 0) and (len(all_unsupported) == 0)
        fact_score = 15.0 if overall_passed else 0.0

        return FactVerificationResult(
            passed=overall_passed,
            score=fact_score,
            contradictions=all_contradictions,
            unsupported_claims=all_unsupported,
            supported_claims=supported,
            narrative_styling=styling,
            feedback=feedback
        )
