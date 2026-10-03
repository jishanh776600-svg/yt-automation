"""
Canonical Topic Niche Guard for Forgotten Files (AL-AMR).
Authoritatively prevents modern academic science, modern medical/oncology research,
modern genetics/aging studies, modern environmental/forestry papers, and generic
university press releases from being ingested, approved, or produced.

Enforces the channel's core niche:
- Historical mysteries & enigmas
- Historical disappearances & vanishings
- Folklore, legends, and mythological events
- Archaeological mysteries & lost civilizations / artifacts
- Historical disasters and bizarre documented incidents
- Historical scientific curiosities (with genuine historical human context)
"""
from dataclasses import dataclass
from enum import Enum
import logging
import re
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger("intelligence.niche_guard")


class NicheRejectionReason(str, Enum):
    NICHE_MISMATCH = "NICHE_MISMATCH"
    MODERN_ACADEMIC_SCIENCE = "MODERN_ACADEMIC_SCIENCE"
    MODERN_MEDICAL_RESEARCH = "MODERN_MEDICAL_RESEARCH"
    MODERN_ENVIRONMENTAL_RESEARCH = "MODERN_ENVIRONMENTAL_RESEARCH"
    MODERN_GENETICS_RESEARCH = "MODERN_GENETICS_RESEARCH"
    PRESS_RELEASE_SCIENCE = "PRESS_RELEASE_SCIENCE"
    INSUFFICIENT_HISTORICAL_CONTEXT = "INSUFFICIENT_HISTORICAL_CONTEXT"
    POLITICAL_CONTENT = "POLITICAL_CONTENT"
    GENERIC_NEWS = "GENERIC_NEWS"
    DRY_ACADEMIC_PAPERS = "DRY_ACADEMIC_PAPERS"


@dataclass
class NicheDecision:
    is_allowed: bool
    reason: str
    rejection_code: Optional[str] = None
    niche_fit_score: float = 0.0


# ==============================================================================
# 1. BANNED POLITICAL / GEOPOLITICAL KEYWORDS (Legacy Phase 0 compatibility)
# ==============================================================================
BANNED_POLITICAL_KEYWORDS = [
    "war", "warfare", "ceasefire", "military", "army", "troops", "infantry", "forces",
    "diplomacy", "diplomat", "diplomatic", "treaty", "election", "elections", "voters",
    "voting", "ballot", "parliament", "congress", "senate", "minister", "prime minister",
    "president", "presidential", "spokesperson", "spokesman", "sanctions", "tariff", "tariffs",
    "bilateral", "geopolitical", "geopolitics", "pentagon", "kremlin", "white house", "nato",
    "un security council", "missile strike", "air strike", "artillery", "offensive",
    "insurgency", "coup", "foreign policy", "envoy", "ambassador", "national security",
    "ground forces", "defense secretary", "state department", "foreign ministry", "legislation",
    "lawmakers", "referendum", "regime", "geopolitic"
]

# ==============================================================================
# 2. NEGATIVE CATEGORY REGEX PATTERNS (Modern Academic Science / Medical / Press)
# ==============================================================================
# Modern Oncology and Clinical Medicine
PATTERNS_MODERN_MEDICAL = [
    r"\bcancer\b",
    r"\boncology\b",
    r"\btumor(s)?\b",
    r"\bchemotherapy\b",
    r"\bcarcinoma\b",
    r"\bmetastasis\b",
    r"\bmalignan(t|cy)\b",
    r"\bpediatric cancer\b",
    r"\bbrain cancer\b",
    r"\bbreast cancer\b",
    r"\blung cancer\b",
    r"\bleukemia\b",
    r"\bimmune organ\b",
    r"\bclinical trial(s)?\b",
    r"\bdrug trial(s)?\b",
    r"\bpharmaceutical(s)?\b",
    r"\bbiomedical\b",
    r"\bimmunotherapy\b",
    r"\bvaccine (study|trial|development)\b",
    r"\bcellular therapy\b",
    r"\bblood test(s)?\b",
    r"\bheart disease risk\b",
    r"\btherapeutic target\b",
    r"\bhealth research\b",
    r"\bmedical research\b",
    r"\bmedical breakthrough\b",
    r"\byounger adults\b",
    r"\bpatient outcomes\b",
]

# Modern Genetics, Aging, and Molecular Biology
PATTERNS_MODERN_GENETICS = [
    r"\bgenetics\b",
    r"\bdna sequencing\b",
    r"\bcrispr\b",
    r"\bgene editing\b",
    r"\bcellular aging\b",
    r"\btelomere(s)?\b",
    r"\blongevity gene(s)?\b",
    r"\banti-aging\b",
    r"\bbiological aging\b",
    r"\bhow .* age(s)?\b",
    r"\bepigenetic(s)?\b",
    r"\bsynthetic biology\b",
    r"\bdna alphabet\b",
    r"\bhachimoji\b",
    r"\bdna repair\b",
    r"\bsequenced the genome\b",
    r"\bgenome sequencing\b",
    r"\bbat dna\b",
    r"\bmrna\b",
    r"\bmolecular biology\b",
    r"\bstem cells?\b",
]

# Modern Environmental, Forestry, and Ecology
PATTERNS_MODERN_ENVIRONMENTAL = [
    r"\bclearcutting\b",
    r"\bboreal forest(s)?\b",
    r"\bboreal bird(s)?\b",
    r"\bforest fragmentation\b",
    r"\bclimate change study\b",
    r"\bcarbon emission(s)?\b",
    r"\bgreenhouse gas(es)?\b",
    r"\bglobal warming study\b",
    r"\bmicroplastic(s)?\b",
    r"\bplastic waste\b",
    r"\bedible cookies\b",
    r"\bbiodegradable plastic\b",
    r"\bmarine pollution\b",
    r"\bbiodiversity loss\b",
    r"\bdeforestation\b",
    r"\bclimate model(s)?\b",
    r"\becology study\b",
    r"\becosystem collapse\b",
    r"\benvironmental research\b",
    r"\bconservation biology\b",
    r"\bwildlife habitat loss\b",
    r"\b(industrial logging|logging practices|soil degradation|forestry|forest management|timber reserve(s)?)\b",
]

# Press Release Phrasing & Academic Journal Signifiers
PATTERNS_PRESS_RELEASE = [
    r"\bstudy led by\b",
    r"\bresearchers at\b",
    r"\bstudy finds\b",
    r"\bstudy reveals\b",
    r"\bnew study (documents|shows|finds|reveals|reports)\b",
    r"\bscientists discover that\b",
    r"\bscientists find that\b",
    r"\bin a new paper\b",
    r"\bpublished in the journal\b",
    r"\bpublished in nature\b",
    r"\bpublished in science\b",
    r"\bpublished in cell\b",
    r"\bpublished in pnas\b",
    r"\buniversity researchers\b",
    r"\blaboratory experiment(s)?\b",
    r"\bnew research suggests\b",
    r"\baccording to a new study\b",
    r"\bteam of researchers\b",
    r"\bco-author of the study\b",
    r"\bpress release\b",
    r"\bpeer-reviewed study\b",
    r"\bjournal publication\b",
]

# Dry Academic Digs & Routine Archaeological Survey Reports (Zero Viral Shorts Appeal)
PATTERNS_DRY_ACADEMIC = [
    r"\b(early )?medieval monastery (studied|examined|surveyed|excavated)\b",
    r"\bmonastery studied\b",
    r"\bmonastery (excavated|surveyed|analyzed)\b",
    r"\brailroad worker camp\b",
    r"\bworker camp found\b",
    r"\bcamp found in\b",
    r"\bfield school\b",
    r"\barchaeological survey\b",
    r"\bpottery sherds?\b",
    r"\broutine excavation\b",
    r"\bceramic fragments?\b",
    r"\bgeophysical survey\b",
    r"\bradiocarbon dating confirmed\b",
    r"\bcharcoal samples?\b",
    r"\bmidden deposit(s)?\b",
    r"\blithic scatter\b",
    r"\btest pit(s)?\b",
    r"\btrench (uncovers|reveals)\b",
    r"\bexcavation report\b",
    r"\bexcavators document\b",
    r"\bpreliminary findings\b",
]

# Generic Physics, Astronomy, Paleontology Lab Studies Without Historical Human Context
PATTERNS_MODERN_ACADEMIC_SCIENCE = [
    r"\bquantum computing\b",
    r"\bquantum computer\b",
    r"\bdark matter\b",
    r"\bparticle physics\b",
    r"\bparticle accelerator\b",
    r"\bhadron collider\b",
    r"\bsupermassive black hole\b",
    r"\bblack hole winds\b",
    r"\bstar formation\b",
    r"\bexoplanet(s)?\b",
    r"\bexoplanet atmosphere\b",
    r"\bjames webb\b",
    r"\bjwst\b",
    r"\bneutrino detector\b",
    r"\bmaterials science\b",
    r"\bsuperconductor\b",
    r"\bbattery technology\b",
    r"\blevitated magnet\b",
    r"\bnanotechnology\b",
    r"\bsemiconductor(s)?\b",
    r"\buv light reveals\b",
    r"\buv camouflage\b",
    r"\bmillion-year-old (crocodile|fossil|reptile|dinosaur|lizard)\b",
]

# ==============================================================================
# 3. POSITIVE HISTORICAL & ARCHAEOLOGICAL CONTEXT PATTERNS
# ==============================================================================
PATTERNS_HISTORICAL_CORE = [
    # Historical Civilizations & Eras
    r"\bancient (egypt|rome|greece|mesopotamia|persia|maya|inca|aztec|civilization|world|tomb|text|manuscript|artifact|temple|city|ruins)\b",
    r"\b(roman|ancient rome|byzantine|medieval|middle ages|renaissance|victorian|edwardian|feudal)\b",
    r"\b(egyptian|pharaoh|tutankhamun|sarcophagus|pyramid|hieroglyph|papyrus|mummy)\b",
    r"\b(bronze age|iron age|stone age|neolithic|antiquity)\b",
    r"\b(pompeii|herculaneum|gobekli|stonehenge|antikythera|voynich|nazca|easter island|moai)\b",
    r"\b(mesopotamia|sumer|sumerian|babylon|babylonian|ur|assyria|assyrian|maya|mayan|inca|aztec)\b",
    r"\b(archaeolog(y|ical|ist)?|excavat(ion|ed)?|unearth(ed)?|buried city|lost city|lost civilization|catacomb|crypt|tomb|relic|artifact|ruins)\b",
    # Historical Disappearances & Maritime Mysteries
    r"\b(disappearance of|vanished without a trace|unsolved disappearance|vanished|disappeared)\b",
    r"\b(mary celeste|flight 19|bermuda triangle|roanoke colony|dyatlov pass|percy fawcett|amelia earhart|ambrose bierce)\b",
    r"\b(ghost ship|shipwreck|sunken galleon|sunken treasure|uncrewed schooner|ghost army)\b",
    # Folklore, Legends, and Documented Historical Curiosities
    r"\b(folklore|legend of|ancient legend|medieval legend|mythology|mythological|cryptid)\b",
    r"\b(dancing plague|london beer flood|kentucky meat shower|halifax explosion|tunguska|fish rain|great stink)\b",
    r"\b(jack the ripper|spring-heeled jack|bell witch|beast of gevaudan|man from taured|violet jessop|tarrare)\b",
    r"\b(green children|mad gasser|sailing stones|pollock twins|devil's footprints|ergotism|lycurgus cup|barabar|moon hoax|cadaver synod|silent twins|dr\. james barry|winchester mystery|marree man|wow! signal|toxic lady|gloria ramirez|baarle-hertog|border anomaly)\b",
    r"\b(unsolved mystery|unexplained (historical|acoustic|engineering|architectural|incident|event)|bizarre history|strange history|forgotten history|historical curiosity)\b",
]

# Specific Historical Year Pattern: Years between 500 and 1999, or BC/BCE, or ancient duration
PATTERN_HISTORICAL_DATE = re.compile(
    r"\b([5-9][0-9]{2}|1[0-9]{3}|[0-9]+-year-old|[0-9]+th\s*century|[0-9]+\s*(bc|bce|ad))\b",
    re.IGNORECASE
)

APPROVED_NICHE_KEYWORDS = [
    # Core mystery/bizarre descriptors
    "anomaly", "anomalies", "bizarre", "mysterious", "mystery", "unexplained", "strange",
    "peculiar", "unusual", "baffling", "puzzle", "enigma", "unsolved", "cryptic", "uncanny",
    "eerie", "eerily", "creepy", "macabre", "disturbing", "haunted", "haunting", "weird",
    "strangest", "oddity", "odd", "perplexing", "inexplicable", "unidentified", "unknown",
    # Archaeological / historical discovery
    "ancient", "skeleton", "tomb", "tombs", "pyramid", "pyramids", "megalith", "monolith",
    "ruins", "artifact", "artifacts", "relic", "relics", "excavation", "buried", "catacomb",
    "mummy", "mummified", "fossil", "stone age", "iron age", "bronze age", "prehistoric",
    "archaeological", "archaeology", "lost civilization", "ancient rome", "roman", "medieval",
    "secret chamber", "hidden chamber", "underground", "burial", "crypt", "sarcophagus",
    "dodecahedron", "voynich", "nazca", "stonehenge", "gobekli", "moai", "easter island",
    # Disappearances and ghost events
    "disappearance", "disappeared", "vanished", "missing", "ghost ship", "abandoned",
    "bermuda", "mary celeste", "lost", "phantom", "wreck", "shipwreck", "wreckage",
    # Survival and extreme events
    "survivor", "survival", "survived", "atomic", "nuclear", "explosion", "disaster",
    "catastrophe", "unbelievable", "incredible", "miracle", "miraculous",
    # Curses, legends, folklore
    "curse", "cursed", "legend", "legends", "folklore", "myth", "ritual", "occult",
    "superstition", "forbidden", "taboo", "dark ritual", "sacrifice",
    # Strange phenomena
    "phenomenon", "phenomena", "paranormal", "unexplained event", "historic incident",
    "historical incident", "unbelievable event", "plague", "mania", "hysteria",
    "mass hysteria", "dancing plague", "bloop", "acoustic anomaly", "deep sea", "abyss",
    "abyssal", "deep sea creature", "cryptid", "sea monster", "creature",
    # Coincidences and strange facts
    "coincidence", "coincidences", "hoax", "conspiracy", "eccentric", "forbidden",
    # Unsolved crimes and mysteries
    "unsolved case", "cold case", "unexplained death", "mysterious death",
    "jack the ripper", "zodiac", "taured", "man from taured",
    # Underwater and space
    "underwater city", "submerged", "labyrinth", "time capsule",
    # History & strange historical incidents
    "historical", "historic", "history", "duel", "forgotten history", "documented history",
    "true event", "true story", "strange history", "unbelievable story",
]


class NicheGuard:
    """
    Authoritative topic-niche evaluation gate.
    Combines negative exclusion filtering, positive historical-mystery matching,
    and historical-context exception logic.
    """

    @classmethod
    def evaluate(
        cls,
        title: str,
        text: str = "",
        entities: Optional[List[str]] = None,
        allow_political: bool = False
    ) -> NicheDecision:
        import unicodedata
        candidate_repr = title.strip()
        raw_combined = f"{title} {text} {' '.join(entities or [])}".lower()
        normalized = unicodedata.normalize("NFKD", raw_combined)
        combined = "".join(c for c in normalized if not unicodedata.combining(c))

        # ----------------------------------------------------------------------
        # Stage 1: Historical Context Detection
        # ----------------------------------------------------------------------
        has_historical_core = False
        matched_historical_patterns = []
        for pat in PATTERNS_HISTORICAL_CORE:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                has_historical_core = True
                matched_historical_patterns.append(m.group(0))

        has_historical_date = bool(PATTERN_HISTORICAL_DATE.search(combined))
        is_strong_historical = has_historical_core or (has_historical_date and not any(w in combined for w in ["clinical trial", "modern", "study led by", "younger adults", "cancer", "cellular aging", "clearcutting"]))

        # ----------------------------------------------------------------------
        # Stage 2: Political / Geopolitical Content Check
        # ----------------------------------------------------------------------
        if not allow_political:
            # If the candidate is a documented historical curiosity (>50 years ago or historical era),
            # terms like 'war', 'army', 'troops', 'forces', 'parliament', 'regime' describe historical events.
            # In that case, we only block explicit modern political figures or current affairs.
            if is_strong_historical:
                modern_political_block = ["biden", "trump", "harris", "putin", "zelensky", "upcoming election", "current election", "white house press", "un security council"]
                matched_modern = [kw for kw in modern_political_block if kw in combined]
                if matched_modern:
                    reason = f"REJECTED_POLITICAL_CONTENT: matched modern political figures {matched_modern}"
                    logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.POLITICAL_CONTENT.value} score=0.0")
                    return NicheDecision(
                        is_allowed=False,
                        reason=reason,
                        rejection_code=NicheRejectionReason.POLITICAL_CONTENT.value,
                        niche_fit_score=0.0
                    )
            else:
                matched_political = []
                for kw in BANNED_POLITICAL_KEYWORDS:
                    pattern = rf"\b{re.escape(kw)}\b"
                    if re.search(pattern, combined):
                        matched_political.append(kw)
                if matched_political:
                    reason = f"REJECTED_POLITICAL_CONTENT: matched {matched_political[:3]}"
                    logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.POLITICAL_CONTENT.value} score=0.0")
                    return NicheDecision(
                        is_allowed=False,
                        reason=reason,
                        rejection_code=NicheRejectionReason.POLITICAL_CONTENT.value,
                        niche_fit_score=0.0
                    )

        # ----------------------------------------------------------------------
        # Stage 3: Negative Category Evaluations
        # ----------------------------------------------------------------------

        # A. Modern Medical / Cancer Research
        for pat in PATTERNS_MODERN_MEDICAL:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                # Historical Exception Check: e.g. "ancient Roman medical text", "treatment found in 2,000-year-old tomb", "Toxic Lady"
                if is_strong_historical and any(w in combined for w in ["toxic lady", "gloria ramirez", "medical text", "ancient", "medieval", "roman", "tomb", "legend"]) and not any(w in combined for w in ["younger adults", "clinical trial", "chemotherapy", "mrna", "immune organ"]):
                    break
                reason = f"REJECTED_MODERN_MEDICAL_RESEARCH: matched '{m.group(0)}' without historical context"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.MODERN_MEDICAL_RESEARCH.value,
                    niche_fit_score=0.0
                )

        # B. Modern Genetics, Cellular Aging & Molecular Biology
        for pat in PATTERNS_MODERN_GENETICS:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                # Historical Exception: e.g. "medieval legend claiming bats extend life"
                if is_strong_historical and ("legend" in combined or "folklore" in combined or "ancient" in combined) and not any(w in combined for w in ["crispr", "sequenced", "cellular aging", "bat dna", "mrna", "telomere"]):
                    break
                reason = f"REJECTED_MODERN_GENETICS_RESEARCH: matched '{m.group(0)}' without historical context"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.MODERN_GENETICS_RESEARCH.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.MODERN_GENETICS_RESEARCH.value,
                    niche_fit_score=0.0
                )

        # C. Modern Environmental, Forestry, and Ecology Studies
        for pat in PATTERNS_MODERN_ENVIRONMENTAL:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                reason = f"REJECTED_MODERN_ENVIRONMENTAL_RESEARCH: matched '{m.group(0)}'"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.MODERN_ENVIRONMENTAL_RESEARCH.value,
                    niche_fit_score=0.0
                )

        # D. Generic Modern Physics, Astrophysics, & Paleontology Lab Studies
        for pat in PATTERNS_MODERN_ACADEMIC_SCIENCE:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                # Historical Exception: e.g. "ancient Chinese astronomers recorded 1054 supernova", "Nanotechnology of the Roman Lycurgus Cup"
                if is_strong_historical and any(w in combined for w in ["ancient", "roman", "recorded", "medieval", "astronomer", "tablet", "artifact", "cup", "mechanism", "concrete", "manuscript"]):
                    break
                reason = f"REJECTED_MODERN_ACADEMIC_SCIENCE: matched '{m.group(0)}' without historical context"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.MODERN_ACADEMIC_SCIENCE.value,
                    niche_fit_score=0.0
                )

        # E. Press Release Phrasing (University / Academic Press Releases)
        for pat in PATTERNS_PRESS_RELEASE:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                # If it's a press release about an archaeological excavation or ancient artifact, allow it
                if is_strong_historical and any(w in combined for w in ["archaeolog", "ancient", "tomb", "pyramid", "excavat", "unearth", "shipwreck", "sarcophagus"]):
                    break
                reason = f"REJECTED_PRESS_RELEASE_SCIENCE: matched academic press phrase '{m.group(0)}'"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.PRESS_RELEASE_SCIENCE.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.PRESS_RELEASE_SCIENCE.value,
                    niche_fit_score=0.0
                )

        # F. Dry Routine Academic Digs / Worker Camps / Non-Viral Surveys
        for pat in PATTERNS_DRY_ACADEMIC:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                reason = f"REJECTED_DRY_ACADEMIC_PAPERS: matched non-viral routine academic pattern '{m.group(0)}'"
                logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.DRY_ACADEMIC_PAPERS.value} score=0.0")
                return NicheDecision(
                    is_allowed=False,
                    reason=reason,
                    rejection_code=NicheRejectionReason.DRY_ACADEMIC_PAPERS.value,
                    niche_fit_score=0.0
                )

        # ----------------------------------------------------------------------
        # Stage 4: Positive Niche Alignment & Scoring
        # ----------------------------------------------------------------------
        # 1. Strong Historical / Archaeological / Mystery Story
        if is_strong_historical:
            score = 92.0
            logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=ACCEPT reason=APPROVED_HISTORICAL_MYSTERY score={score}")
            return NicheDecision(
                is_allowed=True,
                reason=f"APPROVED_HISTORICAL_MYSTERY: matched {matched_historical_patterns[:2] if matched_historical_patterns else ['historical_date_context']}",
                rejection_code=None,
                niche_fit_score=score
            )

        # 2. General approved mystery / bizarre real-world story check (from keyword lexicon)
        matched_keywords = []
        for kw in APPROVED_NICHE_KEYWORDS:
            if kw in combined:
                matched_keywords.append(kw)

        # To avoid loose false positives (e.g. single words like 'unusual', 'strange', 'puzzle' in modern articles),
        # require either at least 2 distinct mystery keywords or 1 high-specificity indicator
        high_specificity_indicators = {
            "disappearance", "vanished", "ghost ship", "mary celeste", "voynich", "antikythera",
            "bermuda", "shipwreck", "cryptid", "mummy", "sarcophagus", "catacomb", "gobekli",
            "stonehenge", "jack the ripper", "taured", "dancing plague", "bloop", "dodecahedron",
            "unsolved mystery", "cold case", "lost civilization", "pyramid", "megalith"
        }

        has_specific = any(kw in high_specificity_indicators for kw in matched_keywords)

        if has_specific or len(matched_keywords) >= 2:
            score = 85.0 if has_specific else 70.0
            logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=ACCEPT reason=APPROVED_MYSTERY_BIZARRE score={score}")
            return NicheDecision(
                is_allowed=True,
                reason=f"APPROVED_MYSTERY_BIZARRE: matched {matched_keywords[:3]}",
                rejection_code=None,
                niche_fit_score=score
            )

        # If it only matched 1 weak generic word like 'unusual' or 'strange' without historical or specific mystery context:
        reason = f"REJECTED_INSUFFICIENT_HISTORICAL_CONTEXT: Generic indicators ({matched_keywords}) lack genuine historical or mystery framing"
        logger.info(f"[TOPIC NICHE] candidate='{candidate_repr}' decision=REJECT reason={NicheRejectionReason.INSUFFICIENT_HISTORICAL_CONTEXT.value} score=25.0")
        return NicheDecision(
            is_allowed=False,
            reason=reason,
            rejection_code=NicheRejectionReason.INSUFFICIENT_HISTORICAL_CONTEXT.value,
            niche_fit_score=25.0
        )
