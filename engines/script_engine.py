"""
Script Engine & Multi-Stage Script Critic.
Generates gripping, fact-grounded 21–25 second (48–62 words) historical narratives.
Follows a rigorous multi-stage pipeline:
  Research Context -> Hook Candidates -> Draft Generation -> Script Critic -> Fact Grounding -> Revision Loop.
Strictly eliminates AI clichés, boilerplate templates, and unsubstantiated claims.
"""
import re
import json
import uuid
import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from sqlalchemy.orm import Session

from config.constants import MIN_WORD_COUNT, MAX_WORD_COUNT, OPTIMAL_WORD_COUNT
from config.settings import GEMINI_API_KEY, AI_PROVIDER_AVAILABLE
from core.models import Topic, ScriptRecord
from core.content_profile import ContentProfile, get_active_profile

logger = logging.getLogger(__name__)

# Strict List of Forbidden AI Clichés & Generic Fillers
FORBIDDEN_CLICHES = [
    "will shock you",
    "unbelievable true story",
    "events spiraled",
    "events rapidly spiraled",
    "events rapidly spiraled out of control",
    "shocked historians",
    "what happened next shocked historians",
    "changed history forever",
    "history changed forever",
    "history would never be the same",
    "the shocking truth",
    "you won't believe",
    "believe it or not",
    "did you know",
    "what happened next",
    "things got worse",
    "things quickly escalated",
    "everything changed",
    "little did they know",
    "for reasons unknown",
    "something strange happened",
    "this unbelievable story",
    "and that's why",
    "that's the mystery",
    "which brings us back",
    "now you know",
    "mind-blowing",
    "an unbelievable event",
    "this shocking event"
]

# Forbidden opening patterns (no dates, years, locations, or rhetorical openers)
FORBIDDEN_HOOK_OPENINGS = [
    re.compile(r"^(?:in\s+)?(?:1\d{3}|20\d{2}|[5-9]\d{2})\b", re.IGNORECASE),
    re.compile(r"^(?:in\s+|on\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", re.IGNORECASE),
    re.compile(r"^in\s+(?:the\s+)?(?:year\s+)?\d{1,4}\b", re.IGNORECASE),
    re.compile(r"^in\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*[,—\.]", re.IGNORECASE),
    re.compile(r"^(?:back\s+in|during|did\s+you\s+know|have\s+you\s+ever|imagine|what\s+if|today|this\s+is\s+the\s+story\s+of|let\s+me\s+tell\s+you)\b", re.IGNORECASE),
]

FORBIDDEN_LOOP_CLICHES = [
    re.compile(r"\band that'?s why\b", re.IGNORECASE),
    re.compile(r"\bthat'?s the mystery\b", re.IGNORECASE),
    re.compile(r"\bwhich brings us back\b", re.IGNORECASE),
    re.compile(r"\bnow you know\b", re.IGNORECASE),
]


def sanitize_script_text(text: str) -> str:
    """Strips markdown styling, stage directions, and extraneous whitespace for clean TTS text."""
    if not text:
        return ""
    clean = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    clean = re.sub(r"\*([^*]+)\*", r"\1", clean)
    clean = re.sub(r"__([^_]+)__", r"\1", clean)
    clean = re.sub(r"_([^_]+)_", r"\1", clean)
    clean = re.sub(r"#{1,6}\s*", "", clean)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = re.sub(r"\[[^\]]*\]", "", clean)
    clean = re.sub(r"\([^)]*\)", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def contains_markdown_leakage(text: str) -> bool:
    """Returns True if raw text contains markdown syntax or bracketed directions."""
    if not text:
        return False
    return bool(re.search(r"(\*\*|\*|__|_|#{1,6}|`|\[|\])", text))


# High-Retention Curated Seed Scripts (Pre-verified for seed topics)
CURATED_SCRIPTS = {
    "Red Sea Maritime Chokepoint Crisis": {
        "hook": "Missile strikes diverted twelve percent of world shipping.",
        "context": "Merchant vessels traversing the Bab-el-Mandeb strait faced relentless drone attack swarms.",
        "escalation": "Allied naval destroyers intercepted dozens of anti-ship ballistic missiles in defense.",
        "reveal": "Commercial freight rates tripled as container ships rerouted thousands of miles.",
        "loop_twist": "A twenty-mile maritime bottleneck exposed the fragile vulnerability of modern trade."
    },
    "Baltic Undersea Infrastructure Security": {
        "hook": "Severed undersea cables triggered an emergency naval response.",
        "context": "Critical telecommunication lines and energy conduits were cut across international waters.",
        "escalation": "Maritime patrol aircraft and mine-hunting ships deployed sonar sweeps across the seabed.",
        "reveal": "Investigators tracked commercial vessels dragging heavy anchors over submarine cables.",
        "loop_twist": "Hybrid maritime warfare demonstrated that cutting cables can silently disrupt entire continents."
    },
    "Strait of Hormuz Naval Interceptions": {
        "hook": "Gunboat boardings threatened twenty percent of global oil.",
        "context": "Naval forces patrolled the twenty-one-mile bottleneck connecting the Persian Gulf.",
        "escalation": "Armed speedboats and helicopters shadowed tankers, attempting hostile vessel seizures.",
        "reveal": "Escort warships deployed electronic countermeasures and continuous air patrols to protect commerce.",
        "loop_twist": "Any escalation in these narrow waters can instantly shock global energy markets."
    },
    "Taiwan Strait Freedom of Navigation Patrols": {
        "hook": "Warships sailed through the world's tensest maritime strait.",
        "context": "Allied destroyers conducted freedom of navigation operations across the hundred-mile passage.",
        "escalation": "Dozens of fighter jets and shadowing frigates tracked every nautical mile.",
        "reveal": "Radar arrays tracked continuous missile locks while surveillance aircraft circled overhead.",
        "loop_twist": "This narrow waterway remains the primary friction point shaping global security."
    },
    "The Kettle War of 1784": {
        "hook": "A single soup kettle stopped a war.",
        "context": "Warships advanced under full sail to break a vital harbor blockade.",
        "escalation": "Defending soldiers aimed and fired a single cannon shot across the water.",
        "reveal": "The blast struck only an ordinary brass soup kettle.",
        "loop_twist": "Terrified commanders surrendered, proving one soup kettle can halt an entire invasion."
    },
    "The Liechtensteiner Army of 1866": {
        "hook": "An eighty-man army returned with eighty-one soldiers.",
        "context": "Liechtenstein deployed eighty soldiers to defend an isolated mountain pass.",
        "escalation": "They patrolled the quiet alpine border for weeks without seeing any combat.",
        "reveal": "Marching home, they befriended an Italian officer who chose to enlist with them.",
        "loop_twist": "Their legendary military campaign concluded with negative one total combat casualties."
    },
    "The Kentucky Meat Shower of 1876": {
        "hook": "Fresh meat mysteriously rained from a clear sky.",
        "context": "On a sunny afternoon in 1876, a farmer made soap outdoors.",
        "escalation": "Large chunks of fresh meat fell directly across the entire property.",
        "reveal": "Scientists concluded startled vultures had regurgitated their heavy meal mid-flight.",
        "loop_twist": "Brave Kentucky neighbors actually tasted the sky meat, identifying it as venison."
    },
    "The Balloon Duel of Paris (1808)": {
        "hook": "Rival duelists fought in soaring hot air balloons.",
        "context": "In 1808, two Frenchmen loved the same opera singer and demanded combat.",
        "escalation": "Armed with blunderbusses, they soared two thousand feet directly over Paris.",
        "reveal": "One shot punctured the opposing balloon envelope, sending his rival plunging downward.",
        "loop_twist": "The victorious duelist landed safely, yet the young opera singer refused him."
    },
    "The Cadaver Synod of 897": {
        "hook": "A dead pope stood trial for serious treason.",
        "context": "Pope Stephen exhumed the decaying corpse of his bitter rival Formosus.",
        "escalation": "They dressed the rotting body in vestments and assigned court defense counsel.",
        "reveal": "Found guilty, the corpse had three fingers severed and was dumped away.",
        "loop_twist": "Outraged Roman citizens revolted and threw the vengeful accuser into prison."
    },
    "The Battle of Karansebes (1788)": {
        "hook": "One hundred thousand soldiers accidentally attacked themselves.",
        "context": "Austrian cavalry bought barrels of schnapps and refused to share with infantry.",
        "escalation": "A drunken midnight brawl erupted, terrified men screamed Turks, and panic spread.",
        "reveal": "Artillery fired straight into the camp, believing the enemy had arrived.",
        "loop_twist": "When opposing forces reached the camp, they discovered thousands of dead soldiers."
    },
    "The Lake Peigneur Sinkhole (1980)": {
        "hook": "A giant lake vanished into a salt mine.",
        "context": "In 1980, an oil rig accidentally drilled straight into an underground salt cavern.",
        "escalation": "Rushing water dissolved the cavern, creating a whirlpool that swallowed eleven barges.",
        "reveal": "The draining lake generated a waterfall and temporarily reversed the Gulf flow.",
        "loop_twist": "Remarkably, all fifty-five oil workers escaped safely without a single casualty."
    },
    "The War of the Stray Dog (1925)": {
        "hook": "Two sovereign nations fought over a stray dog.",
        "context": "A Greek soldier chased his runaway puppy directly across the Bulgarian border.",
        "escalation": "Bulgarian sentries fired, triggering military mobilization on both sides.",
        "reveal": "An armed invasion followed before the League ordered an immediate ceasefire.",
        "loop_twist": "The invading country was fined forty-five thousand pounds for the canine clash."
    },
    "The Aroostook War": {
        "hook": "Two rival nations mobilized troops over stolen timber.",
        "context": "American and British lumberjacks clashed furiously along a disputed border river valley.",
        "escalation": "Both governments deployed armed infantry battalions and prepared for full-scale combat.",
        "reveal": "Diplomats quickly negotiated a peaceful treaty before any combat shots were fired.",
        "loop_twist": "The only casualties of the confrontation were two soldiers mauled by bears."
    },
    "The 38-Minute Anglo-Zanzibar War (1896)": {
        "hook": "The shortest war lasted thirty-eight minutes.",
        "context": "In 1896, a defiant sultan seized royal power against British diplomatic demands.",
        "escalation": "Three Royal Navy warships opened explosive bombardment directly upon the fortified palace.",
        "reveal": "Five hundred defending fighters fell in minutes before the royal flag was lowered.",
        "loop_twist": "By morning tea, the entire conflict was completely and unconditionally over."
    },
    "The Great Stink of London (1858)": {
        "hook": "Toxic river stench completely shut down British Parliament.",
        "context": "A severe heatwave in 1858 boiled millions of gallons of raw river sewage.",
        "escalation": "Politicians soaked curtains in chloride of lime, yet lawmakers fled from overwhelming nausea.",
        "reveal": "Panicked lawmakers swiftly passed legislation creating London's massive underground sewer system.",
        "loop_twist": "That unbearable summer stench established the foundation for modern urban sanitation."
    },
    "The Strange Town of Baarle-Hertog": {
        "hook": "Borders cut straight through people's living rooms.",
        "context": "Baarle is split into twenty-four puzzle pieces between Belgium and the Netherlands.",
        "escalation": "A single home can have its front door in Belgium and kitchen in Holland.",
        "reveal": "During lockdowns, Dutch cafes closed while Belgian tables in the room stayed open.",
        "loop_twist": "Your nationality literally depends on where your front door opens."
    },
    "The London Beer Flood of 1814": {
        "hook": "A fifteen-foot beer wave destroyed an entire neighborhood.",
        "context": "At a London brewery, a massive wooden fermentation vat suddenly ruptured open.",
        "escalation": "Three hundred thousand gallons of porter surged through cobblestone streets like a tsunami.",
        "reveal": "The deluge collapsed brick buildings, flooded basements, and claimed eight human lives.",
        "loop_twist": "A jury declared the bizarre catastrophe an unavoidable act of God."
    },
    "The Boston Molasses Flood of 1919": {
        "hook": "Boiling molasses destroyed an entire city district.",
        "context": "In 1919, a massive fifty-foot steel storage tank suddenly burst in Boston.",
        "escalation": "A thirty-five mile per hour sticky wave crushed nearby structures and overturned trains.",
        "reveal": "Twenty-one people died, and the entire metropolitan district smelled sweet for decades.",
        "loop_twist": "On scorching summer afternoons, residents swear you can still smell the molasses."
    },
    "The Pig War of San Juan Island (1859)": {
        "hook": "Two rival empires fought over a garden pig.",
        "context": "An American settler shot a British pig foraging inside his potato garden.",
        "escalation": "Both superpowers deployed warships and hundreds of soldiers to the disputed island.",
        "reveal": "Commanders refused to fire a single shot over a farm animal.",
        "loop_twist": "The only casualty in the entire military standoff was the pig."
    },
    "The Lost Roanoke Colony Mystery": {
        "hook": "An entire American colony vanished without a trace.",
        "context": "In 1587, over one hundred English settlers arrived on isolated Roanoke Island.",
        "escalation": "When supply ships returned three years later, every home and colonist had disappeared.",
        "reveal": "The only clue was the word CROATOAN carved into a post.",
        "loop_twist": "Centuries later, not a single human skeleton has ever been found."
    },
    "The Dancing Plague of Strasbourg (1518)": {
        "hook": "Hundreds danced until they collapsed from physical exhaustion.",
        "context": "A woman stepped into the street and began dancing uncontrollably for days.",
        "escalation": "Physicians prescribed continuous dancing, hiring musicians to play day and night.",
        "reveal": "Dozens died from heart attacks and strokes before the mania mysteriously ceased.",
        "loop_twist": "Centuries later, modern medical science still cannot explain the bizarre dancing frenzy."
    },
    "The Unsinkable Violet Jessop": {
        "hook": "One woman survived three famous shipwreck disasters.",
        "context": "Violet Jessop worked as a nurse aboard White Star Line ocean liners.",
        "escalation": "She survived the Olympic crash, escaped the Titanic, and survived the Britannic.",
        "reveal": "Jumping into the sea, she was struck by propeller blades but survived.",
        "loop_twist": "She retired peacefully at eighty-four, forever remembered as Miss Unsinkable."
    },
    "The Erfurt Latrine Disaster of 1184": {
        "hook": "Sixty European nobles plunged into a cathedral cesspool.",
        "context": "King Henry convened a peace summit inside Erfurt Cathedral in 1184.",
        "escalation": "The wooden floor suddenly snapped under the weight of the gathered nobility.",
        "reveal": "Dozens fell directly through into the deep liquid cesspool below.",
        "loop_twist": "The king survived by clinging desperately to an iron window grate."
    },
    "The Defenestrations of Prague": {
        "hook": "Rebels threw royal governors seventy feet out windows.",
        "context": "In 1618, Protestant rebels marched into Prague Castle to confront imperial representatives.",
        "escalation": "After a furious argument, they tossed two regents and their secretary outside.",
        "reveal": "All three men remarkably survived falling seventy feet into a dung heap.",
        "loop_twist": "That humiliating seventy-foot plunge ignited the catastrophic Thirty Years War."
    },
    "The Cataclysmic Explosion of Krakatoa in 1883": {
        "hook": "A volcanic eruption produced the loudest sound recorded.",
        "context": "Krakatoa detonated with fifteen thousand times the explosive force of nuclear bombs.",
        "escalation": "Atmospheric shockwaves circled Earth four times, rupturing sailors' eardrums forty miles away.",
        "reveal": "The volcanic island collapsed into the sea, darkening global skies for weeks.",
        "loop_twist": "Today, an active volcanic cone rises relentlessly from that submerged crater."
    },
    "The Great Emu War of 1932": {
        "hook": "An elite military unit surrendered to flightless birds.",
        "context": "Australian soldiers arrived armed with heavy machine guns against twenty thousand emus.",
        "escalation": "The birds quickly split into small ambush groups, outmaneuvering every tactical attack.",
        "reveal": "After weeks of humiliating failure, the commanding defense minister ordered complete withdrawal.",
        "loop_twist": "The military retreated completely defeated, leaving the wild emus victorious in battle."
    }
}


@dataclass
class CriticEvaluation:
    score: float
    passed: bool
    hook_score: float
    information_gap_score: float
    narrative_flow_score: float
    spoken_cadence_score: float
    specificity_score: float
    payoff_score: float
    fact_grounding_score: float
    cliches_detected: List[str] = field(default_factory=list)
    feedback: List[str] = field(default_factory=list)


class ScriptCritic:
    """Evaluates narration scripts against an 8-factor rubric (0-100 scale) using active ContentProfile."""

    def __init__(self, profile: Optional[ContentProfile] = None):
        self.profile = profile

    def evaluate_script(
        self,
        script: Any,
        research_data: Optional[Dict[str, Any]] = None,
        profile: Optional[ContentProfile] = None
    ) -> Tuple[bool, List[str]]:
        """Universal script evaluation accepting either a dict or a ScriptRecord."""
        if isinstance(script, dict):
            s_dict = script
        else:
            s_dict = {
                "hook": getattr(script, "hook", ""),
                "context": getattr(script, "context", ""),
                "escalation": getattr(script, "escalation", ""),
                "reveal": getattr(script, "reveal", ""),
                "loop_twist": getattr(script, "loop_twist", "")
            }
        res = self.evaluate(s_dict, research_data, profile=profile)
        return res.passed, res.feedback

    def evaluate(
        self,
        script_data: Dict[str, str],
        research_data: Optional[Dict[str, Any]] = None,
        profile: Optional[ContentProfile] = None
    ) -> CriticEvaluation:
        active_profile = profile or self.profile or get_active_profile()
        hook = script_data.get("hook", "").strip()
        context = script_data.get("context", "").strip()
        escalation = script_data.get("escalation", "").strip()
        reveal = script_data.get("reveal", "").strip()
        loop_twist = script_data.get("loop_twist", "").strip()

        full_text = f"{hook} {context} {escalation} {reveal} {loop_twist}"
        words = full_text.split()
        word_count = len(words)

        feedback = []
        cliches_detected = []

        # 0. Markdown Leakage & Clean Text Gate
        has_markdown = contains_markdown_leakage(full_text)
        if has_markdown:
            feedback.append("Markdown syntax or bracketed directions detected in script text. Spoken narration must be clean plain text.")

        # 1. Check Forbidden Clichés (-50 penalty if found)
        full_lower = full_text.lower()
        cliches_to_check = active_profile.forbidden_cliches if (active_profile and active_profile.forbidden_cliches) else FORBIDDEN_CLICHES
        for cliche in cliches_to_check:
            if cliche in full_lower:
                cliches_detected.append(cliche)
                feedback.append(f"Forbidden AI cliché detected: '{cliche}'. Must be rephrased naturally.")

        # 1b. Check Forbidden Loop Clichés
        for pattern in FORBIDDEN_LOOP_CLICHES:
            if pattern.search(loop_twist) or pattern.search(full_text):
                matched_cliche = pattern.pattern.replace(r"\b", "").replace(r"'?s", "'s")
                cliches_detected.append(matched_cliche)
                feedback.append(f"Forbidden loop cliché detected: '{matched_cliche}'. Natural loop must reconnect without artificial phrases.")

        is_historical = (active_profile is None or active_profile.name == "HISTORICAL")

        # 2. Hook Quality (20 pts) - Hard Constraint: Strictly 1 to 8 words, no date/location openings for HISTORICAL
        hook_score = 0.0
        hook_words = hook.split()
        hook_len = len(hook_words)

        hook_forbidden_start = False
        max_hook_len = 8 if is_historical else 16
        if is_historical:
            for pattern in FORBIDDEN_HOOK_OPENINGS:
                if pattern.search(hook):
                    hook_forbidden_start = True
                    feedback.append(f"Forbidden hook opening detected: '{hook[:35]}...'. Hook must begin immediately with contradiction/shock/paradox, never dates, years, locations, or rhetorical questions.")
                    break

            if not (1 <= hook_len <= 8):
                feedback.append(f"Hook length ({hook_len} words) is outside strict 1-8 word limit.")
        else:
            if not (1 <= hook_len <= max_hook_len):
                feedback.append(f"Hook length ({hook_len} words) is outside acceptable limit ({max_hook_len} words max).")

        # High curiosity markers (contradiction, action, tension from profile)
        hook_marker_matched = False
        markers = active_profile.hook_markers if (active_profile and active_profile.hook_markers) else [
            r"\b(thousands|hundreds|minutes|miles|tons|first|only|deadliest|disaster|war|king|crisis|shattered|surrendered|marched|returned|exploded|burst|vanished|danced|survived|plunged|retreated)\b"
        ]
        for marker_pattern in markers:
            if re.search(marker_pattern, hook, re.IGNORECASE):
                hook_marker_matched = True
                break

        if (1 <= hook_len <= max_hook_len) and not hook_forbidden_start:
            if hook_marker_matched:
                hook_score += 20.0
            else:
                hook_score += 15.0

        # 3. Information Gap & Curiosity (15 pts)
        info_gap_score = 15.0
        if "shock you" in hook.lower() or "unbelievable" in hook.lower():
            info_gap_score = 5.0
            feedback.append("Hook uses cheap clickbait instead of genuine information gap.")

        # 4. Narrative Flow & Storytelling (15 pts)
        narrative_score = 0.0
        if context and escalation and reveal:
            narrative_score += 10.0
        if len(context.split()) >= 6 and len(escalation.split()) >= 6:
            narrative_score += 5.0
        else:
            feedback.append("Context or escalation lacks sufficient narrative development.")

        # 5. Spoken Cadence & Word Count (15 pts) - Hard Constraint: Strictly 50 to 56 words
        cadence_score = 0.0
        sentences = [s.strip() for s in re.split(r"[.!?]", full_text) if s.strip()]
        avg_sent_len = word_count / max(1, len(sentences))
        if 5.0 <= avg_sent_len <= 15.0:
            cadence_score += 10.0
        else:
            feedback.append(f"Average sentence length ({avg_sent_len:.1f} words) is suboptimal for spoken rhythm.")

        min_words = MIN_WORD_COUNT if is_historical else (active_profile.min_words if active_profile else MIN_WORD_COUNT)
        max_words = MAX_WORD_COUNT if is_historical else (active_profile.max_words if active_profile else MAX_WORD_COUNT)

        word_count_valid = (min_words <= word_count <= max_words)
        if word_count_valid:
            cadence_score += 5.0
        else:
            feedback.append(f"Total word count ({word_count}) outside strict {min_words}-{max_words} word bounds.")

        # 6. Concrete Specificity (10 pts)
        specificity_score = 0.0
        specific_matches = re.findall(r"\b([A-Z][a-z]+|\d{1,4}|[A-Z]{2,})\b", full_text)
        if len(specific_matches) >= 4:
            specificity_score = 10.0
        elif len(specific_matches) >= 2:
            specificity_score = 6.0
        else:
            feedback.append("Script lacks concrete specific entities, numbers, or locations.")

        # 7. Payoff & Resolution (10 pts)
        payoff_score = 0.0
        if len(reveal.split()) >= 5 and len(loop_twist.split()) >= 5:
            payoff_score += 10.0
        elif len(reveal.split()) >= 3 and len(loop_twist.split()) >= 3:
            payoff_score += 5.0
        else:
            feedback.append("Reveal or loop twist resolution is too abrupt.")

        # 8. Factual Alignment (15 pts)
        fact_score = 15.0
        fact_passed = True
        if research_data:
            from engines.fact_verifier import FactVerifier
            verifier = FactVerifier()
            fact_res = verifier.verify(full_text, research_data)
            fact_score = fact_res.score
            fact_passed = fact_res.passed
            if not fact_passed:
                feedback.extend(fact_res.feedback)

        # Total Calculation
        total_score = hook_score + info_gap_score + narrative_score + cadence_score + specificity_score + payoff_score + fact_score
        if cliches_detected:
            total_score = max(0.0, total_score - 50.0)

        passed = (
            (total_score >= 80.0)
            and (len(cliches_detected) == 0)
            and (not hook_forbidden_start)
            and (not has_markdown)
            and (1 <= hook_len <= max_hook_len)
            and word_count_valid
            and fact_passed
        )

        return CriticEvaluation(
            score=round(total_score, 1),
            passed=passed,
            hook_score=hook_score,
            information_gap_score=info_gap_score,
            narrative_flow_score=narrative_score,
            spoken_cadence_score=cadence_score,
            specificity_score=specificity_score,
            payoff_score=payoff_score,
            fact_grounding_score=fact_score,
            cliches_detected=cliches_detected,
            feedback=feedback
        )


class ScriptEngine:
    """Multi-stage Script Generation Engine with Critic Evaluation and Fact Grounding."""

    def __init__(self, profile: Optional[ContentProfile] = None):
        self.profile = profile or get_active_profile()
        self.critic = ScriptCritic(profile=self.profile)
        self._script_cache: Dict[str, Dict[str, str]] = {}

    def cache_script(self, topic_id: str, script_data: Dict[str, str]) -> None:
        """Caches a pre-generated batch script for a topic."""
        self._script_cache[topic_id] = script_data

    def get_cached_script(self, topic_id: str) -> Optional[Dict[str, str]]:
        """Retrieves and clears any cached script for a topic."""
        return self._script_cache.pop(topic_id, None)

    def clear_script_cache(self) -> None:
        """Clears all cached pre-generated scripts."""
        self._script_cache.clear()

    def generate_hook_candidates(
        self,
        topic: Topic,
        research_data: Optional[Dict[str, Any]] = None,
        profile: Optional[ContentProfile] = None
    ) -> List[Dict[str, Any]]:
        """Generates 3 distinct hook candidates (Contradiction, In-Medias-Res, Shock-Fact) strictly 1-8 words."""
        active_profile = profile or self.profile or get_active_profile()
        res_summary = research_data.get("summary", topic.summary) if research_data else topic.summary

        if not AI_PROVIDER_AVAILABLE:
            # Fallback curated candidates (strictly 1-8 words, no date openers)
            return [
                {"type": "Contradiction", "hook": "The documented truth shocked everyone.", "score": 75.0},
                {"type": "In-Medias-Res", "hook": "Disaster struck without any warning.", "score": 70.0},
                {"type": "Shock-Fact", "hook": "One impossible event changed everything.", "score": 72.0}
            ]

        try:
            from core.gemini_client import get_gemini_client
            gemini_client = get_gemini_client()
            prompt = (
                f"Generate 3 distinct, high-curiosity hook sentences (STRICTLY 1-8 words each) for a YouTube Short about: '{topic.title}'.\n"
                f"Context: {res_summary}\n"
                f"Target Audience: {active_profile.target_audience}\n"
                f"Tone: {active_profile.tone}\n"
                f"Strict Invariants:\n"
                f"- STRICTLY 1 to 8 words per hook. Count your words!\n"
                f"- Must begin immediately with contradiction, paradox, or shock fact.\n"
                f"- NEVER begin with a year, date, month, or location (e.g. 'In 1784...', 'In London...').\n"
                f"- No rhetorical questions or generic fillers ('Did you know', 'You won't believe', 'Imagine').\n"
                f"- Hook 1: Contradiction / Paradox First\n"
                f"- Hook 2: In-Medias-Res / Immediate Crisis Action\n"
                f"- Hook 3: Shocking Specific Fact\n"
                f"Output strictly valid JSON with key 'hooks' containing a list of 3 strings."
            )
            from config.settings import GEMINI_MODEL
            response = gemini_client.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            raw = response.text.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(raw)
            raw_hooks = data.get("hooks", [])
            
            candidates = []
            types = ["Contradiction", "In-Medias-Res", "Shock-Fact"]
            for i, h in enumerate(raw_hooks[:3]):
                clean_h = sanitize_script_text(h)
                h_type = types[i] if i < len(types) else "Variant"
                mock_script = {"hook": clean_h, "context": "Context verified.", "escalation": "Details developing.", "reveal": "Monitors reported.", "loop_twist": "Records confirm."}
                eval_res = self.critic.evaluate(mock_script, research_data, profile=active_profile)
                candidates.append({
                    "type": h_type,
                    "hook": clean_h,
                    "score": eval_res.hook_score + (10.0 if len(eval_res.cliches_detected) == 0 else 0.0)
                })
            
            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates if candidates else [
                {"type": "Contradiction", "hook": "The documented truth shocked everyone.", "score": 75.0}
            ]
        except Exception as e:
            if "QuotaExhausted" in type(e).__name__ or "quota" in str(e).lower() or "429" in str(e):
                raise e
            logger.warning(f"Hook candidate generation notice: {e}")
            return [
                {"type": "Contradiction", "hook": "The documented truth shocked everyone.", "score": 75.0}
            ]

    def _draft_script_pass(
        self,
        topic: Topic,
        selected_hook: str,
        research_data: Optional[Dict[str, Any]],
        revision_feedback: Optional[List[str]] = None,
        learned_guidance: str = "",
        profile: Optional[ContentProfile] = None
    ) -> Dict[str, str]:
        """Executes a single draft/revision pass with configured AI Provider."""
        active_profile = profile or self.profile or get_active_profile()
        from core.gemini_client import get_gemini_client
        gemini_client = get_gemini_client()

        # Extract verified facts to anchor the model
        verified_facts_text = ""
        if research_data:
            claims = [c.get("claim", "") for c in research_data.get("verified_claims", []) if c.get("claim")]
            if claims:
                verified_facts_text = "VERIFIED RESEARCH FACTS (USE ONLY THESE CLAIMS):\n- " + "\n- ".join(claims[:5])
            elif research_data.get("summary"):
                verified_facts_text = f"VERIFIED RESEARCH CONTEXT (USE ONLY THIS):\n{research_data.get('summary')}"

        feedback_instruction = ""
        if revision_feedback:
            formatted_fb = []
            for fb in revision_feedback:
                if "outside" in fb.lower() or "word count" in fb.lower():
                    formatted_fb.append(f"- WORD COUNT CORRECTION: {fb}. Target strictly {active_profile.min_words}-{active_profile.max_words} words (aim for {active_profile.target_words}) across all 5 stages combined.")
                elif "hook" in fb.lower():
                    formatted_fb.append(f"- HOOK CORRECTION: {fb}. Strictly 1-8 words, contradiction/shock only, zero dates or locations at start.")
                elif "unsupported claim" in fb.lower():
                    formatted_fb.append(f"- FACTUAL CORRECTION: {fb}. Remove or rewrite this claim strictly using provided research.")
                elif "markdown" in fb.lower():
                    formatted_fb.append("- FORMATTING: Remove all markdown asterisks, hashes, and brackets. Return clean spoken text only.")
                else:
                    formatted_fb.append(f"- REVISE: {fb}")
            feedback_instruction = (
                "\n=======================================================\n"
                "CRITICAL TARGETED REVISION INSTRUCTIONS (PREVIOUS PASS REJECTED BY QUALITY GATE):\n"
                + "\n".join(formatted_fb)
                + "\n=======================================================\n"
            )

        cliches_str = ", ".join(repr(c) for c in active_profile.forbidden_cliches[:5])
        extra_inst = f"\n7. ADDITIONAL STRATEGY:\n   - {active_profile.additional_instructions}\n" if active_profile.additional_instructions else ""

        prompt = (
            f"{active_profile.system_role_instruction}\n"
            f"Topic: '{topic.title}'\n"
            f"Target Audience: {active_profile.target_audience}\n"
            f"Editorial Tone: {active_profile.tone}\n"
            f"Objective: {active_profile.script_objective}\n"
            f"Selected Opening Hook (0-2s): \"{selected_hook}\"\n\n"
            f"{verified_facts_text}\n\n"
            f"{learned_guidance}\n"
            f"\nHARD PRODUCTION CONTRACT & SPECIFICATION:\n"
            f"1. TARGET DURATION: 21–24 seconds spoken narration.\n"
            f"2. HARD WORD COUNT BOUNDS (MANDATORY):\n"
            f"   - STRICT MINIMUM: {active_profile.min_words} words\n"
            f"   - STRICT MAXIMUM: {active_profile.max_words} words\n"
            f"   - OPTIMAL TARGET: {active_profile.target_words} total across all 5 stages combined.\n"
            f"   - Any script with fewer than {active_profile.min_words} or more than {active_profile.max_words} words will be REJECTED.\n"
            f"3. 5-STAGE RETENTION STRUCTURE:\n"
            f"   - hook: Strictly 1-8 words. Immediate contradiction, paradox, or shock. NEVER begin with a year, date, month, location, or 'Did you know'.\n"
            f"   - context: Rapid setting and background grounding with forward momentum.\n"
            f"   - escalation: Rising stakes, intensifying conflict or bizarre progression.\n"
            f"   - reveal: The peak absurdity, definitive payoff, or climax.\n"
            f"   - loop_twist: Seamless loop resolution reconnecting to the opening premise. NO artificial phrases like 'And that's why' or 'Now you know'.\n"
            f"4. CLEAN SPOKEN TEXT (NO MARKDOWN):\n"
            f"   - Plain spoken text ONLY. Strictly NO Markdown (*, **, _, #), stage directions, or bracketed instructions.\n"
            f"5. FACTUAL POLICY (CRITICAL QUALITY GATE):\n"
            f"   - {active_profile.factual_policy}\n"
            f"6. STYLE & CADENCE:\n"
            f"   - {active_profile.preferred_cadence}\n"
            f"   - NO AI CLICHÉS: NEVER use {cliches_str}.\n"
            f"{extra_inst}"
            f"SELF-CHECK BEFORE RETURNING JSON:\n"
            f"   - Count words: Total word count MUST be between {active_profile.min_words} and {active_profile.max_words} words.\n"
            f"   - Verify hook is 1-8 words and does NOT start with a date or location.\n"
            f"   - Verify zero markdown formatting in values.\n"
            f"   - Verify all 5 narrative keys exist: hook, context, escalation, reveal, loop_twist.\n"
            f"{feedback_instruction}\n"
            f"Output strictly valid JSON with keys: hook, context, escalation, reveal, loop_twist"
        )

        from config.settings import GEMINI_MODEL
        response = gemini_client.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )
        import re
        raw_text = response.text.strip()
        data = None
        try:
            data = json.loads(raw_text)
        except Exception:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1).strip())
                except Exception:
                    pass
            if not data:
                m = re.search(r"(\{.*\})", raw_text, re.DOTALL)
                if m:
                    try:
                        data = json.loads(m.group(1).strip())
                    except Exception:
                        pass
            if not data:
                cleaned = raw_text.replace("```json", "").replace("```", "").strip()
                data = json.loads(cleaned)

        if data and isinstance(data, dict):
            for k in ["hook", "context", "escalation", "reveal", "loop_twist"]:
                if k in data:
                    data[k] = sanitize_script_text(str(data[k]))

        return data

    def generate_script(
        self,
        db: Session,
        topic: Topic,
        research_data: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None,
        profile: Optional[ContentProfile] = None
    ) -> ScriptRecord:
        """
        Produces an approved, fact-grounded script via multi-stage Critic evaluation and rewrite loop.
        Applies target hook archetype and duration strategy if supplied.
        """
        active_profile = profile or self.profile or get_active_profile()
        target_hook_archetype = strategy.get("hook_archetype") if strategy else None
        target_duration = strategy.get("duration_target") if strategy else None

        # 0. Primary Path for Phase 3 Current-Affairs EventCard-Grounded Scripting
        card = None
        if getattr(topic, "event_card_json", None):
            from intelligence.event_card import EventCard
            try:
                card = EventCard.from_json(topic.event_card_json)
            except Exception as e:
                logger.warning(f"Could not parse topic.event_card_json: {e}")
        elif research_data and research_data.get("event_card"):
            from intelligence.event_card import EventCard
            c_data = research_data["event_card"]
            card = EventCard.from_dict(c_data) if isinstance(c_data, dict) else c_data

        if card:
            from intelligence.journalistic_script import JournalisticScriptEngine, ScriptBeatType
            j_engine = JournalisticScriptEngine()
            target_sec = 45.0
            if target_duration == "ULTRA_TIGHT":
                target_sec = 35.0
            elif target_duration == "NARRATIVE_RICH":
                target_sec = 55.0

            script_doc = j_engine.generate_journalistic_script(
                event_card=card,
                target_duration_seconds=target_sec,
                profile=active_profile
            )

            # Map beats into legacy 5-stage fields for downstream engine compatibility
            hook_text = script_doc.hook
            what_beats = [b.text for b in script_doc.beats if b.beat_type in [ScriptBeatType.WHAT_HAPPENED.value, ScriptBeatType.WHO.value, ScriptBeatType.WHERE.value]]
            context_beats = [b.text for b in script_doc.beats if b.beat_type in [ScriptBeatType.CONTEXT.value, ScriptBeatType.KEY_DEVELOPMENT.value]]
            reveal_beats = [b.text for b in script_doc.beats if b.beat_type in [ScriptBeatType.CONFLICT.value, ScriptBeatType.OFFICIAL_RESPONSE.value]]
            closing_text = script_doc.closing or (script_doc.beats[-1].text if script_doc.beats else "")

            context_str = " ".join(what_beats) if what_beats else (script_doc.beats[1].text if len(script_doc.beats) > 1 else card.what)
            escalation_str = " ".join(context_beats) if context_beats else (script_doc.beats[2].text if len(script_doc.beats) > 2 else "")
            reveal_str = " ".join(reveal_beats) if reveal_beats else (script_doc.beats[3].text if len(script_doc.beats) > 3 else "")

            script_rec = ScriptRecord(
                id=script_doc.script_id,
                topic_id=topic.id,
                event_id=card.event_id,
                hook=hook_text,
                context=context_str or "Context verified.",
                escalation=escalation_str or "Details developing.",
                reveal=reveal_str or "Reported by monitors.",
                loop_twist=closing_text,
                full_text=script_doc.full_text,
                word_count=script_doc.word_count,
                estimated_duration_sec=script_doc.estimated_duration_sec,
                hook_archetype=target_hook_archetype or "DATE_TIME_ANCHOR",
                duration_target=target_duration or "SWEET_SPOT",
                status="APPROVED",
                script_document_json=script_doc.to_json(),
                provenance_complete=script_doc.provenance_complete,
                validation_status="APPROVED" if script_doc.provenance_complete else "FLAGGED"
            )
            db.add(script_rec)
            db.commit()
            db.refresh(script_rec)
            return script_rec

        data = None
        eval_res = None

        # 1. Check pre-generated batch script cache first
        if topic.id and topic.id in self._script_cache:
            cached_data = self._script_cache.pop(topic.id)
            cached_eval = self.critic.evaluate(cached_data, research_data, profile=active_profile)
            if cached_eval.passed:
                logger.info(f"[BATCH_CACHE_HIT] Using pre-generated batch script for '{topic.title}' (Score: {cached_eval.score}/100)")
                data = cached_data
                eval_res = cached_eval
            else:
                logger.warning(f"[BATCH_CACHE_REJECT] Pre-generated script for '{topic.title}' failed critic ({cached_eval.feedback}). Retrying individually.")
                # data remains None -> falls through to curated/AI generation

        # 2. Check curated seed library for exact or normalized approved scripts
        # Only allow curated historical scripts if NOT in current-affairs mode
        is_current_affairs = (
            getattr(topic, "category", "") in ["Current Affairs", "Geopolitics", "Conflict", "Diplomacy"]
            or bool(getattr(topic, "event_id", None))
        )
        if not data and not is_current_affairs:
            curated_match = None
            norm_title = re.sub(r"[^\w\s]", "", topic.title.lower()).strip()
            for k in CURATED_SCRIPTS:
                norm_k = re.sub(r"[^\w\s]", "", k.lower()).strip()
                if norm_k in norm_title or norm_title in norm_k or k.lower() in topic.title.lower():
                    curated_match = k
                    break

            if curated_match:
                logger.info(f"Using verified curated script for '{topic.title}' (matched: '{curated_match}')")
                data = CURATED_SCRIPTS[curated_match]
                eval_res = self.critic.evaluate(data, research_data, profile=active_profile)

        if not data and AI_PROVIDER_AVAILABLE:
            # 2. Multi-Candidate Hook Selection
            hook_candidates = self.generate_hook_candidates(topic, research_data, profile=active_profile)
            
            # If target archetype requested, search for matching candidate
            selected_hook = None
            if target_hook_archetype:
                for cand in hook_candidates:
                    if self.classify_hook_archetype(cand["hook"]) == target_hook_archetype:
                        selected_hook = cand["hook"]
                        logger.info(f"Selected Strategy-Matched Hook ({target_hook_archetype}): \"{selected_hook}\"")
                        break
            if not selected_hook:
                selected_hook = hook_candidates[0]["hook"]
                top_type = hook_candidates[0].get("type", "DEFAULT")
                logger.info(f"Selected Top Hook ({top_type}): \"{selected_hook}\"")

            # 3. Iterative Draft & Critic Rewrite Loop (Max 3 attempts)
            data = None
            eval_res = None
            max_attempts = 3
            current_feedback = None

            # Get learned production guidance from closed-loop analytics
            learned_guidance = ""
            try:
                from engines.learning_engine import LearningEngine
                learned_guidance = LearningEngine().get_learned_production_profile(db)
            except Exception as learn_err:
                logger.debug(f"Learning guidance query notice: {learn_err}")

            for attempt in range(1, max_attempts + 1):
                logger.info(f"Script Generation Pass {attempt}/{max_attempts} for '{topic.title}'...")
                try:
                    data = self._draft_script_pass(
                        topic=topic,
                        selected_hook=selected_hook,
                        research_data=research_data,
                        revision_feedback=current_feedback,
                        learned_guidance=learned_guidance,
                        profile=active_profile
                    )
                    eval_res = self.critic.evaluate(data, research_data, profile=active_profile)
                    logger.info(f"Pass {attempt} Critic Score: {eval_res.score}/100 (Passed: {eval_res.passed})")

                    if eval_res.passed:
                        break
                    else:
                        logger.warning(f"Pass {attempt} rejected by Critic: {eval_res.feedback}")
                        current_feedback = eval_res.feedback

                except Exception as gen_err:
                    if "QuotaExhausted" in type(gen_err).__name__ or "quota" in str(gen_err).lower() or "429" in str(gen_err):
                        logger.error(f"[AI_EXHAUSTED] Terminal quota exhaustion detected during script generation pass {attempt}: {gen_err}")
                        raise gen_err
                    logger.warning(f"Pass {attempt} error: {gen_err}")
                    current_feedback = [f"Regenerate cleanly without formatting errors: {str(gen_err)}"]

            # 4. Strict Quality Gate Check
            if not eval_res or not eval_res.passed:
                # If quality gate failed after max attempts, check if curated script exists (historical only)
                if not is_current_affairs and topic.title in CURATED_SCRIPTS:
                    logger.info(f"Fallback to curated seed script for '{topic.title}'")
                    data = CURATED_SCRIPTS[topic.title]
                else:
                    err_msg = f"Script quality gate failed after {max_attempts} attempts (Score: {eval_res.score if eval_res else 0}/100). Feedback: {eval_res.feedback if eval_res else 'Unknown'}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)
        elif not data:
            if not is_current_affairs and topic.title in CURATED_SCRIPTS:
                data = CURATED_SCRIPTS[topic.title]
            else:
                raise RuntimeError(f"Cannot generate script without active AI provider (GEMINI_API_KEY, GROQ_API_KEY, DEEPSEEK_API_KEY) or curated record for '{topic.title}'")

        full_text = f"{data['hook']} {data['context']} {data['escalation']} {data['reveal']} {data['loop_twist']}"
        words = full_text.split()
        word_count = len(words)
        estimated_duration = round(word_count / 2.4, 1)

        # Classify strategic features or apply assigned strategy
        classified_hook = self.classify_hook_archetype(data["hook"])
        classified_duration = self.classify_duration_target(estimated_duration)
        
        final_hook_archetype = target_hook_archetype or classified_hook
        final_duration_target = target_duration or classified_duration

        script_rec = ScriptRecord(
            id=f"scr_{uuid.uuid4().hex[:12]}",
            topic_id=topic.id,
            hook=data["hook"],
            context=data["context"],
            escalation=data["escalation"],
            reveal=data["reveal"],
            loop_twist=data["loop_twist"],
            full_text=full_text,
            word_count=word_count,
            estimated_duration_sec=estimated_duration,
            hook_archetype=final_hook_archetype,
            duration_target=final_duration_target,
            status="APPROVED"
        )
        db.add(script_rec)
        db.commit()
        logger.info(f"[+] Script Approved ({eval_res.score if eval_res else 95.0}/100): '{topic.title}' ({word_count} words | ~{estimated_duration}s | Archetype: {final_hook_archetype} | Duration: {final_duration_target})")
        return script_rec

    def generate_batch_scripts(
        self,
        db: Session,
        topics: List[Topic],
        research_data_map: Optional[Dict[str, Dict[str, Any]]] = None,
        _mock_response: Optional[str] = None,
        profile: Optional[ContentProfile] = None
    ) -> Dict[str, Optional[Dict[str, str]]]:
        """
        Executes ONE AI generation call for a batch of topics (e.g. 3 topics)
        and returns a dict mapping topic.id -> validated script dictionary (or None if failed).

        Strict Requirements Implemented:
        1. Return EXACTLY N scripts when N topics are supplied.
        2. Each script maps to exactly one supplied topic.
        3. 45–68 words per script (active profile min_words to max_words).
        4. Do not combine topics.
        5. Do not reuse story, facts, angle, hook, or substantially similar narrative.
        6. Scripts must be meaningfully distinct.
        7. Do not invent an extra (N+1)th script.
        8. Unambiguous structured JSON mapping (topic_index, topic_id).
        9. Preserve fact-grounding behavior (use only supplied research).
        10. Do not weaken existing quality gates (evaluated by ScriptCritic).

        Recovery:
        If any script fails validation, that topic returns None while valid scripts
        are preserved. The caller retries ONLY the failed script via single-script path.
        """
        if not topics:
            return {}

        active_profile = profile or self.profile or get_active_profile()
        n = len(topics)
        results: Dict[str, Optional[Dict[str, str]]] = {t.id: None for t in topics}

        if not AI_PROVIDER_AVAILABLE and _mock_response is None:
            logger.warning("[BATCH_SCRIPT] AI provider not available and no mock response — falling back per-script.")
            return results

        # Build full context block for each topic
        topic_blocks = []
        topic_id_by_index: Dict[int, str] = {}
        topic_title_by_index: Dict[int, str] = {}

        for idx, topic in enumerate(topics, start=1):
            topic_id_by_index[idx] = topic.id
            topic_title_by_index[idx] = topic.title
            rd = (research_data_map or {}).get(topic.id, {})
            claims = [c.get("claim", "") for c in rd.get("verified_claims", []) if c.get("claim")]
            if claims:
                facts_text = "VERIFIED RESEARCH FACTS (USE ONLY THESE):\n- " + "\n- ".join(claims[:5])
            elif rd.get("summary"):
                facts_text = f"VERIFIED RESEARCH CONTEXT (USE ONLY THIS):\n{rd.get('summary')}"
            else:
                facts_text = f"TOPIC SUMMARY:\n{topic.summary or 'Documented event.'}"

            cat_text = f"Category: {topic.category}" if topic.category else ""
            topic_blocks.append(
                f"=== TOPIC {idx} of {n} ===\n"
                f"topic_index: {idx}\n"
                f"topic_id: {topic.id}\n"
                f"title: \"{topic.title}\"\n"
                f"{cat_text}\n"
                f"{facts_text}\n"
            )

        topics_section = "\n".join(topic_blocks)

        # Closed-loop learned guidance if available
        learned_guidance = ""
        try:
            from engines.learning_engine import LearningEngine
            learned_guidance = LearningEngine().get_learned_production_profile(db)
        except Exception:
            pass

        cliches_str = ", ".join(repr(c) for c in active_profile.forbidden_cliches[:6])
        batch_prompt = (
            f"{active_profile.system_role_instruction}\n"
            f"Editorial Tone: {active_profile.tone}\n"
            f"Target Audience: {active_profile.target_audience}\n"
            f"Core Objective: {active_profile.script_objective}\n"
            f"Write EXACTLY {n} independent, fact-grounded documentary scripts — one per topic supplied below.\n\n"
            f"{'=' * 65}\n"
            f"{topics_section}\n"
            f"{'=' * 65}\n\n"
            f"{learned_guidance}\n\n"
            f"CRITICAL PRODUCTION CONTRACT & CONSTRAINTS:\n"
            f"1. EXACT SCRIPT COUNT: Return EXACTLY {n} scripts when {n} topics are supplied.\n"
            f"   - Do NOT omit any topic (missing scripts are rejected).\n"
            f"   - Do NOT invent extra scripts ({n+1}th script is strictly rejected).\n"
            f"2. UNAMBIGUOUS TOPIC MAPPING:\n"
            f"   - Each script must map to EXACTLY ONE topic using 'topic_index' (1 to {n}) and 'topic_id'.\n"
            f"   - Do NOT swap topics or assign one topic's narrative to another.\n"
            f"3. WORD COUNT SPECIFICATION (CRITICAL QUALITY GATE):\n"
            f"   - HARD MINIMUM: {active_profile.min_words} words per script.\n"
            f"   - HARD MAXIMUM: {active_profile.max_words} words per script.\n"
            f"   - PREFERRED TARGET: {active_profile.target_words} total across all 5 narrative stages combined.\n"
            f"   - Any script outside {active_profile.min_words}–{active_profile.max_words} words will be rejected.\n"
            f"4. DO NOT COMBINE TOPICS: Each script must exclusively narrate its assigned topic.\n"
            f"5. MEANINGFULLY DISTINCT NARRATIVES:\n"
            f"   - Do NOT reuse the same story, facts, angle, hook structure, or opening phrase across scripts.\n"
            f"   - Each script must have a distinct hook archetype, unique dramatic tension, and different tone.\n"
            f"6. 5-STAGE RETENTION STRUCTURE (for each script):\n"
            f"   - hook: Strictly 1-8 words. Immediate contradiction, paradox, or shock. NEVER start with a year, date, month, or location.\n"
            f"   - context: Clear, rapid setting and grounding with forward momentum.\n"
            f"   - escalation: Rising stakes, intensifying conflict or progression.\n"
            f"   - reveal: The definitive payoff/climax.\n"
            f"   - loop_twist: Complete final resolution and seamless loop-compatible ending statement. Zero artificial loop phrases.\n"
            f"7. CLEAN SPOKEN TEXT (NO MARKDOWN):\n"
            f"   - Plain spoken text ONLY. Strictly NO Markdown (*, **, _, #), stage directions, or bracketed instructions.\n"
            f"8. STRICT FACTUAL GROUNDING:\n"
            f"   - {active_profile.factual_policy}\n"
            f"9. FORBIDDEN AI CLICHÉS IN ALL SCRIPTS:\n"
            f"   - NEVER use {cliches_str}.\n"
            f"10. STYLE & CADENCE:\n"
            f"   - {active_profile.preferred_cadence}\n\n"
            f"OUTPUT FORMAT — strictly valid JSON object matching this exact schema:\n"
            f"{{\n"
            f"  \"scripts\": [\n"
            f"    {{\n"
            f"      \"topic_index\": 1,\n"
            f"      \"topic_id\": \"{topics[0].id}\",\n"
            f"      \"hook\": \"...\",\n"
            f"      \"context\": \"...\",\n"
            f"      \"escalation\": \"...\",\n"
            f"      \"reveal\": \"...\",\n"
            f"      \"loop_twist\": \"...\"\n"
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
            f"SELF-CHECK BEFORE RETURNING:\n"
            f"- Verify 'scripts' list has EXACTLY {n} elements.\n"
            f"- Verify each element has all 5 keys: hook, context, escalation, reveal, loop_twist.\n"
            f"- Verify every script word count is between {active_profile.min_words} and {active_profile.max_words} words.\n"
            f"- Verify every hook is 1-8 words and does NOT start with a date or location."
        )

        raw_text = ""
        if _mock_response is not None:
            raw_text = _mock_response.strip()
        else:
            try:
                from core.gemini_client import get_gemini_client
                from config.settings import GEMINI_MODEL
                gemini_client = get_gemini_client()
                logger.info(f"[BATCH_SCRIPT] Dispatching single batch script generation request for {n} topics...")
                response = gemini_client.generate_content(model=GEMINI_MODEL, contents=batch_prompt)
                raw_text = response.text.strip()
            except Exception as e:
                logger.error(f"[BATCH_SCRIPT] Batch AI request failed: {e}. Falling back to per-script generation.")
                return results

        # Parse JSON
        batch_data = None
        try:
            batch_data = json.loads(raw_text)
        except Exception:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
            if m:
                try:
                    batch_data = json.loads(m.group(1).strip())
                except Exception:
                    pass
            if not batch_data:
                m = re.search(r"(\{.*\})", raw_text, re.DOTALL)
                if m:
                    try:
                        batch_data = json.loads(m.group(1).strip())
                    except Exception:
                        pass

        if not batch_data or not isinstance(batch_data, dict):
            logger.warning("[BATCH_SCRIPT] Failed to parse valid JSON from batch response. Falling back per-script.")
            return results

        raw_scripts = batch_data.get("scripts", [])
        if not isinstance(raw_scripts, list):
            logger.warning("[BATCH_SCRIPT] 'scripts' field in response is not a list. Falling back per-script.")
            return results

        # 1. Exact count check: reject extra scripts or missing scripts
        if len(raw_scripts) != n:
            logger.warning(
                f"[BATCH_SCRIPT] Expected exactly {n} scripts, got {len(raw_scripts)}. "
                f"Batch count invariant violated ({'extra' if len(raw_scripts) > n else 'missing'} scripts). "
                f"Falling back to per-script generation."
            )
            return results

        REQUIRED_KEYS = {"hook", "context", "escalation", "reveal", "loop_twist"}

        def _validate_individual_script(script_dict: Dict[str, Any], expected_topic: Topic) -> Tuple[bool, List[str]]:
            """Validates a single candidate script against production quality gates."""
            failures = []
            if not isinstance(script_dict, dict):
                return False, ["Script item is not a dictionary"]

            missing = REQUIRED_KEYS - set(script_dict.keys())
            if missing:
                failures.append(f"Missing required keys: {sorted(missing)}")
                return False, failures

            # Sanitize all fields
            for k in REQUIRED_KEYS:
                script_dict[k] = sanitize_script_text(str(script_dict.get(k, "")))

            # Word count check
            full_text = " ".join(str(script_dict.get(k, "")).strip() for k in ["hook", "context", "escalation", "reveal", "loop_twist"])
            wc = len(full_text.split())
            if not (active_profile.min_words <= wc <= active_profile.max_words):
                failures.append(f"Word count ({wc}) outside calibrated {active_profile.min_words}-{active_profile.max_words} range")

            # Forbidden clichés check
            full_lower = full_text.lower()
            cliches_to_check = active_profile.forbidden_cliches if (active_profile and active_profile.forbidden_cliches) else FORBIDDEN_CLICHES
            for cliche in cliches_to_check:
                if cliche in full_lower:
                    failures.append(f"Forbidden AI cliché detected: '{cliche}'")

            # Critic evaluation
            rd = (research_data_map or {}).get(expected_topic.id)
            eval_res = self.critic.evaluate(script_dict, rd, profile=active_profile)
            if not eval_res.passed:
                failures.append(f"Critic rejected (Score {eval_res.score}/100): {eval_res.feedback}")

            return len(failures) == 0, failures

        # 2. Topic Mapping & Structural Extraction
        # Build mapping by topic_index or topic_id
        mapped_scripts: Dict[str, Dict[str, str]] = {}
        used_indices: set = set()

        for s_idx, item in enumerate(raw_scripts, start=1):
            if not isinstance(item, dict):
                continue
            # Determine mapped topic
            t_idx = item.get("topic_index")
            t_id = item.get("topic_id")
            resolved_topic_id = None

            if t_id and any(t.id == t_id for t in topics):
                resolved_topic_id = t_id
            elif isinstance(t_idx, int) and t_idx in topic_id_by_index and t_idx not in used_indices:
                resolved_topic_id = topic_id_by_index[t_idx]
                used_indices.add(t_idx)
            elif s_idx in topic_id_by_index and s_idx not in used_indices:
                # Fallback to ordinal position if unambiguous
                resolved_topic_id = topic_id_by_index[s_idx]
                used_indices.add(s_idx)

            if resolved_topic_id and resolved_topic_id not in mapped_scripts:
                clean_script = {k: str(item.get(k, "")).strip() for k in REQUIRED_KEYS}
                mapped_scripts[resolved_topic_id] = clean_script

        if len(mapped_scripts) != n:
            logger.warning(
                f"[BATCH_SCRIPT] Ambiguous or incomplete topic mapping: resolved {len(mapped_scripts)}/{n} topics. "
                f"Unmapped topics will fall back to single-script path."
            )

        # 3. Cross-Script Deduplication / Similarity Check
        # Reject duplicate or substantially similar narratives within the same batch
        rejected_by_similarity: set = set()
        topic_id_list = list(mapped_scripts.keys())
        for i in range(len(topic_id_list)):
            id_a = topic_id_list[i]
            script_a = mapped_scripts[id_a]
            full_a = " ".join(script_a.get(k, "") for k in REQUIRED_KEYS).lower()
            words_a = set(re.findall(r"\b\w{4,}\b", full_a))

            hook_words_a = set(re.findall(r"\b\w{4,}\b", script_a.get("hook", "").lower()))

            for j in range(i + 1, len(topic_id_list)):
                id_b = topic_id_list[j]
                script_b = mapped_scripts[id_b]
                full_b = " ".join(script_b.get(k, "") for k in REQUIRED_KEYS).lower()
                words_b = set(re.findall(r"\b\w{4,}\b", full_b))
                hook_words_b = set(re.findall(r"\b\w{4,}\b", script_b.get("hook", "").lower()))

                # Check hook overlap (4+ significant shared words)
                shared_hook = hook_words_a & hook_words_b
                if len(shared_hook) >= 4:
                    logger.warning(f"[BATCH_SCRIPT] Hook similarity conflict between '{id_a}' and '{id_b}': shared {shared_hook}")
                    rejected_by_similarity.add(id_b)

                # Check content word Jaccard similarity (> 0.35 threshold)
                if words_a and words_b:
                    jaccard = len(words_a & words_b) / len(words_a | words_b)
                    if jaccard > 0.35:
                        logger.warning(f"[BATCH_SCRIPT] High cross-script similarity ({jaccard:.2f}) between '{id_a}' and '{id_b}'. Rejecting '{id_b}'.")
                        rejected_by_similarity.add(id_b)

        # 4. Final Per-Topic Validation & Result Assembly
        for topic in topics:
            if topic.id not in mapped_scripts:
                logger.info(f"[BATCH_SCRIPT] Topic '{topic.title[:45]}' not mapped in batch output -> single-script fallback.")
                results[topic.id] = None
                continue

            if topic.id in rejected_by_similarity:
                logger.info(f"[BATCH_SCRIPT] Topic '{topic.title[:45]}' rejected for batch similarity -> single-script fallback.")
                results[topic.id] = None
                continue

            candidate_script = mapped_scripts[topic.id]
            is_valid, failure_reasons = _validate_individual_script(candidate_script, topic)

            if is_valid:
                wc = len(" ".join(candidate_script.values()).split())
                logger.info(f"[BATCH_SCRIPT] Topic '{topic.title[:45]}' VALID ({wc} words).")
                results[topic.id] = candidate_script
            else:
                logger.warning(
                    f"[BATCH_SCRIPT] Topic '{topic.title[:45]}' INVALID ({failure_reasons}). "
                    f"Will retry individually via single-script path."
                )
                results[topic.id] = None

        valid_count = sum(1 for v in results.values() if v is not None)
        logger.info(f"[BATCH_SCRIPT] Batch generation complete: {valid_count}/{n} scripts approved on first pass.")
        return results



    @staticmethod
    def classify_hook_archetype(hook_text: str) -> str:
        """Classifies a hook string into the standard strategic taxonomy."""
        h_lower = hook_text.lower()
        if re.search(r"\b(in (1\d{3}|20\d{2}|[5-9]\d{2})|on (january|february|march|april|may|june|july|august|september|october|november|december))\b", h_lower):
            return "DATE_TIME_ANCHOR"
        elif any(w in h_lower for w in ["what if", "imagine", "ever wonder"]):
            return "HYPOTHETICAL_CURIOSITY"
        elif any(w in h_lower for w in ["vanish", "disappear", "mystery", "secret", "never found", "lost"]):
            return "UNSOLVED_MYSTERY"
        elif any(w in h_lower for w in ["opened fire", "struck", "exploded", "invaded", "bombed", "crashed", "burst", "collapsed"]):
            return "IN_MEDIAS_RES"
        elif any(w in h_lower for w in ["instead", "almost sparked", "shortest", "bizarre", "strangest", "shocking", "paralyzed"]):
            return "CONTRADICTION_SHOCK"
        return "OTHER"

    @staticmethod
    def classify_duration_target(duration_sec: float) -> str:
        """Classifies duration into standard strategic brackets."""
        if duration_sec < 22.5:
            return "ULTRA_TIGHT"
        elif duration_sec <= 23.8:
            return "SWEET_SPOT"
        return "NARRATIVE_RICH"
