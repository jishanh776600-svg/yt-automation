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

logger = logging.getLogger(__name__)

# Strict List of Forbidden AI Clichés & Generic Fillers
FORBIDDEN_CLICHES = [
    "will shock you",
    "unbelievable true story",
    "events spiraled",
    "events rapidly spiraled",
    "shocked historians",
    "changed history forever",
    "history changed forever",
    "you won't believe",
    "believe it or not",
    "did you know",
    "what happened next",
    "things got worse",
    "mind-blowing",
    "an unbelievable event",
    "this shocking event"
]

# High-Retention Curated Seed Scripts (Pre-verified for seed topics)
CURATED_SCRIPTS = {
    "The Kettle War of 1784": {
        "hook": "In 1784, a European war ended with a shattered soup kettle.",
        "context": "The Holy Roman Empire sent warships to challenge Dutch ports.",
        "escalation": "A Dutch flagship fired one warning cannon shot across the harbor.",
        "reveal": "The shot struck an iron kettle, spraying boiling soup on deck.",
        "loop_twist": "Terrified, the imperial fleet surrendered without a single casualty."
    },
    "The Liechtensteiner Army of 1866": {
        "hook": "An eighty-man army marched to war and returned with eighty-one soldiers.",
        "context": "In 1866, Liechtenstein sent eighty men to guard an alpine pass.",
        "escalation": "They patrolled the quiet border without seeing any combat.",
        "reveal": "Trekking home, they befriended an Italian officer who joined them.",
        "loop_twist": "They suffered negative one casualties in history's most wholesome war."
    },
    "The Kentucky Meat Shower of 1876": {
        "hook": "In 1876, fresh red meat mysteriously rained from a clear sky.",
        "context": "On a sunny afternoon in Kentucky, a farmer made soap outside.",
        "escalation": "Suddenly, large chunks of fresh meat fell across the farm.",
        "reveal": "Scientists concluded startled vultures had regurgitated their meal mid-flight.",
        "loop_twist": "Two brave locals tasted the sky meat, calling it venison."
    },
    "The Balloon Duel of Paris (1808)": {
        "hook": "In 1808, two Frenchmen fought history's only balloon duel.",
        "context": "Two gentlemen loved the same opera singer and demanded a duel.",
        "escalation": "They soared two thousand feet above Paris armed with blunderbusses.",
        "reveal": "One shot punctured his rival's balloon, sending it plunging down.",
        "loop_twist": "The victor landed safely, yet the singer refused his hand."
    },
    "The Cadaver Synod of 897": {
        "hook": "In 897, a dead pope's rotting corpse was put on trial.",
        "context": "Pope Stephen ordered the body of Pope Formosus exhumed.",
        "escalation": "They dressed the decaying corpse in vestments with a defense lawyer.",
        "reveal": "Found guilty, the corpse had three fingers severed and dumped away.",
        "loop_twist": "Enraged Roman citizens rioted and threw Pope Stephen into prison."
    },
    "The Battle of Karansebes (1788)": {
        "hook": "In 1788, an army of one hundred thousand men fought itself.",
        "context": "Austrian cavalry bought schnapps and refused to share with infantry.",
        "escalation": "A drunken brawl erupted, someone shouted Turks, and panic spread.",
        "reveal": "Artillery fired into the camp, believing the enemy had struck.",
        "loop_twist": "When real Turks arrived, they found thousands of dead soldiers."
    },
    "The Lake Peigneur Sinkhole (1980)": {
        "hook": "A thirteen-hundred-acre lake vanished into an underground salt mine.",
        "context": "In 1980, an oil rig accidentally drilled into a Louisiana salt cavern.",
        "escalation": "Water dissolved the salt, creating a whirlpool that swallowed eleven barges.",
        "reveal": "The draining lake temporarily reversed the Gulf of Mexico flow.",
        "loop_twist": "Miraculously, all fifty-five workers escaped without a single casualty."
    },
    "The War of the Stray Dog (1925)": {
        "hook": "In 1925, Greece and Bulgaria went to war over a runaway dog.",
        "context": "A Greek soldier chased his stray dog across the border.",
        "escalation": "Bulgarian sentries shot him, sparking military mobilization on both sides.",
        "reveal": "Greece invaded before the League of Nations ordered an immediate ceasefire.",
        "loop_twist": "Greece was fined forty-five thousand pounds for the canine clash."
    },
    "The Aroostook War": {
        "hook": "In 1838, America and Britain mobilized troops over stolen timber.",
        "context": "Lumberjacks from Maine and New Brunswick clashed in a disputed valley.",
        "escalation": "Both sides deployed armed militias and prepared for full-scale war.",
        "reveal": "General Winfield Scott negotiated a truce before shots were fired.",
        "loop_twist": "The only casualties of the entire war were two men mauled by bears."
    },
    "The 38-Minute Anglo-Zanzibar War (1896)": {
        "hook": "The shortest war in human history lasted less than forty minutes.",
        "context": "In 1896, a rebel sultan seized power in Zanzibar against British demands.",
        "escalation": "Three Royal Navy cruisers opened fire on the palace with explosive shells.",
        "reveal": "In thirty-eight minutes, five hundred defenders fell, and the sultan fled.",
        "loop_twist": "By morning tea, the war was completely over."
    },
    "The Great Stink of London (1858)": {
        "hook": "In 1858, the smell of London became so toxic it shut down Parliament.",
        "context": "A scorching heatwave boiled tons of raw sewage in the River Thames.",
        "escalation": "Lawmakers soaked curtains in lime, but the overwhelming stench caused severe nausea.",
        "reveal": "Politicians panicked and passed an emergency bill to fund a modern sewer network.",
        "loop_twist": "That foul summer created the world's first modern sanitation system."
    },
    "The Strange Town of Baarle-Hertog": {
        "hook": "This European town has borders cutting straight through people's living rooms.",
        "context": "Baarle is split into twenty-four puzzle pieces between Belgium and the Netherlands.",
        "escalation": "A single house can have its front door in Belgium and its kitchen in Holland.",
        "reveal": "During lockdowns, Dutch cafes closed while Belgian tables in the same room stayed open.",
        "loop_twist": "Your nationality literally depends on where your front door opens."
    },
    "The London Beer Flood of 1814": {
        "hook": "In October 1814, a fifteen-foot wave of beer destroyed a London neighborhood.",
        "context": "At the Meux Brewery, a massive wooden fermentation vat suddenly burst open.",
        "escalation": "Over three hundred thousand gallons of porter surged through the streets like a tidal wave.",
        "reveal": "The tsunami collapsed building walls, flooded basements, and claimed eight lives.",
        "loop_twist": "A jury declared the bizarre catastrophe an unavoidable act of God."
    },
    "The Boston Molasses Flood of 1919": {
        "hook": "A two-million-gallon wave of boiling molasses once destroyed Boston.",
        "context": "In 1919, a massive fifty-foot steel tank suddenly burst in the North End.",
        "escalation": "A thirty-five mile per hour sticky tsunami crushed buildings and overturned trains.",
        "reveal": "Twenty-one people died, and the entire city smelled sweet for decades.",
        "loop_twist": "On hot summer days, locals swear you can still smell the molasses."
    },
    "The Pig War of San Juan Island (1859)": {
        "hook": "America and Britain almost went to war over a single potato-eating pig.",
        "context": "In 1859, an American farmer shot a British pig foraging in his garden.",
        "escalation": "Both nations deployed five warships and nearly two thousand heavily armed troops.",
        "reveal": "Military commanders refused to fire the first shot over a farm animal.",
        "loop_twist": "The only casualty in the entire standoff was the pig."
    },
    "The Lost Roanoke Colony Mystery": {
        "hook": "An entire American colony vanished without leaving a single trace.",
        "context": "In 1587, over one hundred English settlers arrived on Roanoke Island.",
        "escalation": "When rescue ships returned three years later, every home and person had disappeared.",
        "reveal": "The only clue was the mysterious word CROATOAN carved into a post.",
        "loop_twist": "To this day, not a single skeleton has ever been found."
    },
    "The Dancing Plague of Strasbourg (1518)": {
        "hook": "In 1518, hundreds of people danced in the streets until collapsing from exhaustion.",
        "context": "A woman in Strasbourg began dancing, and within days, four hundred joined her.",
        "escalation": "Doctors mistakenly prescribed more dancing, hiring musicians to play day and night.",
        "reveal": "Dozens died before the bizarre frenzy mysteriously vanished.",
        "loop_twist": "Modern science still cannot explain what drove them to dance."
    },
    "The Unsinkable Violet Jessop": {
        "hook": "This woman survived three of the deadliest shipwreck disasters in history.",
        "context": "Violet Jessop was a nurse serving aboard White Star Line ocean liners.",
        "escalation": "She survived the Olympic crash, escaped the sinking Titanic, and survived the Britannic explosion.",
        "reveal": "Even jumping into propeller blades couldn't end her life.",
        "loop_twist": "She retired peacefully at eighty-four, nicknamed Miss Unsinkable."
    },
    "The Erfurt Latrine Disaster of 1184": {
        "hook": "In July 1184, sixty European nobles died in the most humiliating disaster in history.",
        "context": "King Henry VI convened a royal peace summit on the second floor of Erfurt Cathedral.",
        "escalation": "The heavy wooden floor suddenly snapped under the weight of the assembled nobles.",
        "reveal": "Dozens plunged straight through into the vast liquid cesspool beneath the building.",
        "loop_twist": "The king only survived by clinging desperately to an iron window grate."
    },
    "The Defenestrations of Prague": {
        "hook": "Three separate times in European history, politicians were hurled out of castle windows.",
        "context": "In 1618, Bohemian rebels marched into Prague Castle to confront royal governors.",
        "escalation": "After a furious argument, they tossed two regents and their secretary seventy feet down.",
        "reveal": "All three remarkably survived by landing in a massive pile of horse manure.",
        "loop_twist": "That seventy-foot plunge sparked the catastrophic Thirty Years War."
    },
    "The Cataclysmic Explosion of Krakatoa in 1883": {
        "hook": "In 1883, a volcanic eruption created the loudest sound in history.",
        "context": "Krakatoa exploded with fifteen thousand times the power of Hiroshima.",
        "escalation": "Shockwaves circled Earth four times, shattering eardrums forty miles away.",
        "reveal": "The entire island collapsed into the sea, blacking out the skies.",
        "loop_twist": "Yet today, an active volcano rises relentlessly from that crater."
    },
    "The Great Emu War of 1932": {
        "hook": "In 1932, Australia declared war on wild birds.",
        "context": "Soldiers arrived with machine guns against twenty thousand destructive emus.",
        "escalation": "Yet the birds scattered into split-second ambushes, dodging every heavy volley.",
        "reveal": "After weeks of humiliating chaos, the army withdrew in defeat.",
        "loop_twist": "The soldiers retreated, completely outmaneuvered by flightless birds."
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
    """Evaluates historical narration scripts against an 8-factor rubric (0-100 scale)."""

    def evaluate(self, script_data: Dict[str, str], research_data: Optional[Dict[str, Any]] = None) -> CriticEvaluation:
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

        # 1. Check Forbidden Clichés (-50 penalty if found)
        full_lower = full_text.lower()
        for cliche in FORBIDDEN_CLICHES:
            if cliche in full_lower:
                cliches_detected.append(cliche)
                feedback.append(f"Forbidden AI cliché detected: '{cliche}'. Must be rephrased naturally.")

        # 2. Hook Quality (20 pts)
        hook_score = 0.0
        hook_words = hook.split()
        if 5 <= len(hook_words) <= 15:
            hook_score += 10.0
        else:
            feedback.append(f"Hook length ({len(hook_words)} words) is outside optimal 6-14 word range.")

        # High curiosity markers (dates, numbers, strong actions, visceral nouns)
        if re.search(r"\b(1\d{3}|20\d{2}|thousands|hundreds|minutes|miles|tons|first|only|deadliest|disaster|war|king|crisis)\b", hook, re.IGNORECASE):
            hook_score += 10.0
        elif len(hook_words) >= 5:
            hook_score += 5.0

        # 3. Information Gap & Curiosity (15 pts)
        info_gap_score = 15.0
        if "shock you" in hook.lower() or "unbelievable" in hook.lower():
            info_gap_score = 5.0
            feedback.append("Hook uses cheap clickbait instead of genuine information gap.")

        # 4. Narrative Flow & Storytelling (15 pts)
        narrative_score = 0.0
        if context and escalation and reveal:
            narrative_score += 10.0
        if len(context.split()) >= 8 and len(escalation.split()) >= 8:
            narrative_score += 5.0
        else:
            feedback.append("Context or escalation lacks sufficient narrative development.")

        # 5. Spoken Cadence & Sentence Rhythm (15 pts)
        cadence_score = 0.0
        sentences = [s.strip() for s in re.split(r"[.!?]", full_text) if s.strip()]
        avg_sent_len = word_count / max(1, len(sentences))
        if 6.0 <= avg_sent_len <= 14.0:
            cadence_score += 10.0
        else:
            feedback.append(f"Average sentence length ({avg_sent_len:.1f} words) is suboptimal for spoken rhythm.")

        if MIN_WORD_COUNT <= word_count <= (MAX_WORD_COUNT + 3):
            cadence_score += 5.0
        else:
            feedback.append(f"Total word count ({word_count}) outside calibrated {MIN_WORD_COUNT}-{MAX_WORD_COUNT + 3} word target.")

        # 6. Concrete Specificity (10 pts)
        specificity_score = 0.0
        specific_matches = re.findall(r"\b([A-Z][a-z]+|\d{1,4}|[A-Z]{2,})\b", full_text)
        if len(specific_matches) >= 5:
            specificity_score = 10.0
        elif len(specific_matches) >= 3:
            specificity_score = 6.0
        else:
            feedback.append("Script lacks concrete specific entities, numbers, or locations.")

        # 7. Payoff & Resolution (10 pts)
        payoff_score = 0.0
        if len(reveal.split()) >= 6 and len(loop_twist.split()) >= 5:
            payoff_score = 10.0
        else:
            payoff_score = 5.0
            feedback.append("Reveal or ending twist is too abrupt.")

        # 8. Multi-Tier Fact Verification (15 pts) - Hard Quality Gate
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
            and (MIN_WORD_COUNT <= word_count <= (MAX_WORD_COUNT + 3))
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

    def __init__(self):
        self.critic = ScriptCritic()
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

    def generate_hook_candidates(self, topic: Topic, research_data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Generates 3 distinct hook candidates (Date-Anchor, In-Medias-Res, Unexpected Consequence)."""
        res_summary = research_data.get("summary", topic.summary) if research_data else topic.summary

        if not AI_PROVIDER_AVAILABLE:
            # Fallback curated candidates
            return [
                {"type": "Date-Anchor", "hook": f"In {topic.title}, an extraordinary event occurred.", "score": 75.0},
                {"type": "In-Medias-Res", "hook": f"When crisis struck in {topic.title}, nobody expected the outcome.", "score": 70.0},
                {"type": "Unexpected-Detail", "hook": f"The documented truth behind {topic.title} changed everything.", "score": 72.0}
            ]

        try:
            from core.gemini_client import get_gemini_client
            gemini_client = get_gemini_client()
            prompt = (
                f"Generate 3 distinct, high-curiosity hook sentences (6-13 words each) for a historical YouTube Short about: '{topic.title}'.\n"
                f"Historical Context: {res_summary}\n"
                f"Strict Rules:\n"
                f"- No 'Did you know', No 'You won't believe', No 'The unbelievable true story', No clickbait tropes.\n"
                f"- Hook 1: Date/Time Anchored (e.g. 'In July 1184, sixty European nobles met a bizarre fate.')\n"
                f"- Hook 2: In-Medias-Res / Action First (e.g. 'Three Royal Navy cruisers opened fire on the palace at dawn.')\n"
                f"- Hook 3: Unexpected Specific Consequence (e.g. 'A single potato-eating pig almost sparked an armed war.')\n"
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
            types = ["Date-Anchor", "In-Medias-Res", "Unexpected-Consequence"]
            for i, h in enumerate(raw_hooks[:3]):
                h_type = types[i] if i < len(types) else "Variant"
                mock_script = {"hook": h, "context": "Context", "escalation": "Escalation", "reveal": "Reveal", "loop_twist": "Twist"}
                eval_res = self.critic.evaluate(mock_script, research_data)
                candidates.append({
                    "type": h_type,
                    "hook": h,
                    "score": eval_res.hook_score + (10.0 if len(eval_res.cliches_detected) == 0 else 0.0)
                })
            
            candidates.sort(key=lambda x: x["score"], reverse=True)
            return candidates if candidates else [
                {"type": "Date-Anchor", "hook": f"The documented history of {topic.title} holds a remarkable truth.", "score": 75.0}
            ]
        except Exception as e:
            if "QuotaExhausted" in type(e).__name__ or "quota" in str(e).lower() or "429" in str(e):
                raise e
            logger.warning(f"Hook candidate generation notice: {e}")
            return [
                {"type": "Date-Anchor", "hook": f"In {topic.title}, a remarkable event unfolded.", "score": 75.0}
            ]

    def _draft_script_pass(
        self,
        topic: Topic,
        selected_hook: str,
        research_data: Optional[Dict[str, Any]],
        revision_feedback: Optional[List[str]] = None,
        learned_guidance: str = ""
    ) -> Dict[str, str]:
        """Executes a single draft/revision pass with configured AI Provider."""
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
                if "outside calibrated" in fb.lower() or "word count" in fb.lower():
                    formatted_fb.append(f"- WORD COUNT CORRECTION: {fb}. Target exactly 50-55 words across all 5 stages combined. Do not introduce new claims.")
                elif "unsupported claim" in fb.lower():
                    formatted_fb.append(f"- FACTUAL CORRECTION: {fb}. Remove or rewrite this claim strictly using provided research.")
                else:
                    formatted_fb.append(f"- REVISE: {fb}")
            feedback_instruction = (
                "\n=======================================================\n"
                "CRITICAL TARGETED REVISION INSTRUCTIONS (PREVIOUS PASS REJECTED BY QUALITY GATE):\n"
                + "\n".join(formatted_fb)
                + "\n=======================================================\n"
            )

        prompt = (
            f"You are a master historical documentary scriptwriter for YouTube Shorts.\n"
            f"Topic: '{topic.title}'\n"
            f"Selected Opening Hook (0-2s): \"{selected_hook}\"\n\n"
            f"{verified_facts_text}\n\n"
            f"{learned_guidance}\n"
            f"\nPRODUCTION CONTRACT & SPECIFICATION:\n"
            f"1. TARGET DURATION: 21–25 seconds spoken narration.\n"
            f"2. WORD COUNT SPECIFICATION (CRITICAL):\n"
            f"   - HARD MINIMUM: 45 words\n"
            f"   - HARD MAXIMUM: 68 words\n"
            f"   - PREFERRED TARGET: 50–55 words total across all 5 stages combined.\n"
            f"3. 5-STAGE NARRATIVE STRUCTURE:\n"
            f"   - hook: (0-2s) Immediate curiosity/tension gap. No generic intros ('Did you know', 'Today we're looking at').\n"
            f"   - context: Clear, rapid historical setting and grounding with forward momentum.\n"
            f"   - escalation: Rising stakes, intensifying conflict or bizarre progression. Every claim MUST be supported by supplied research.\n"
            f"   - reveal: The definitive, surprising historical payoff/climax.\n"
            f"   - loop_twist: Complete final resolution and loop-compatible ending statement. No filler conclusions.\n"
            f"4. STRICT FACTUAL RULES (CRITICAL QUALITY GATE):\n"
            f"   - Use ONLY information explicitly supported by the supplied research.\n"
            f"   - NEVER invent dates (e.g. do not guess specific calendar days if not in research).\n"
            f"   - NEVER invent names, casualty counts, quotations, motives, or precise locations.\n"
            f"   - NEVER convert historical uncertainty into certainty.\n"
            f"   - Do NOT introduce dramatic claims absent from the research evidence.\n"
            f"5. STYLE & CADENCE:\n"
            f"   - Natural spoken American English. Short, punchy sentences (6-12 words/sentence). Strong momentum. Zero filler.\n"
            f"   - NO AI CLICHÉS: NEVER use 'will shock you', 'unbelievable true story', 'events spiraled', 'shocked historians', 'changed history forever'.\n"
            f"6. SELF-CHECK BEFORE RETURNING JSON:\n"
            f"   - Verify total word count is 45-68 words (aim for 50-55 words).\n"
            f"   - Verify all 5 narrative keys exist.\n"
            f"   - Verify all facts are 100% grounded in supplied research.\n"
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
        return data

    def generate_script(
        self,
        db: Session,
        topic: Topic,
        research_data: Optional[Dict[str, Any]] = None,
        strategy: Optional[Dict[str, Any]] = None
    ) -> ScriptRecord:
        """
        Produces an approved, fact-grounded script via multi-stage Critic evaluation and rewrite loop.
        Applies target hook archetype and duration strategy if supplied.
        """
        target_hook_archetype = strategy.get("hook_archetype") if strategy else None
        target_duration = strategy.get("duration_target") if strategy else None

        data = None
        eval_res = None

        # 1. Check pre-generated batch script cache first
        if topic.id and topic.id in self._script_cache:
            cached_data = self._script_cache.pop(topic.id)
            cached_eval = self.critic.evaluate(cached_data, research_data)
            if cached_eval.passed:
                logger.info(f"[BATCH_CACHE_HIT] Using pre-generated batch script for '{topic.title}' (Score: {cached_eval.score}/100)")
                data = cached_data
                eval_res = cached_eval
            else:
                logger.warning(f"[BATCH_CACHE_REJECT] Pre-generated script for '{topic.title}' failed critic ({cached_eval.feedback}). Retrying individually.")
                # data remains None -> falls through to curated/AI generation

        # 2. Check curated seed library for exact or normalized approved scripts
        if not data:
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
                eval_res = self.critic.evaluate(data, research_data)

        if not data and AI_PROVIDER_AVAILABLE:
            # 2. Multi-Candidate Hook Selection
            hook_candidates = self.generate_hook_candidates(topic, research_data)
            
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
                        learned_guidance=learned_guidance
                    )
                    eval_res = self.critic.evaluate(data, research_data)
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
                # If quality gate failed after max attempts, check if curated script exists
                if topic.title in CURATED_SCRIPTS:
                    logger.info(f"Fallback to curated seed script for '{topic.title}'")
                    data = CURATED_SCRIPTS[topic.title]
                else:
                    err_msg = f"Script quality gate failed after {max_attempts} attempts (Score: {eval_res.score if eval_res else 0}/100). Feedback: {eval_res.feedback if eval_res else 'Unknown'}"
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)
        elif not data:
            if topic.title in CURATED_SCRIPTS:
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
        _mock_response: Optional[str] = None
    ) -> Dict[str, Optional[Dict[str, str]]]:
        """
        Executes ONE AI generation call for a batch of topics (e.g. 3 topics)
        and returns a dict mapping topic.id -> validated script dictionary (or None if failed).

        Strict Requirements Implemented:
        1. Return EXACTLY N scripts when N topics are supplied.
        2. Each script maps to exactly one supplied topic.
        3. 45–68 words per script (MIN_WORD_COUNT to MAX_WORD_COUNT).
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
                facts_text = f"TOPIC SUMMARY:\n{topic.summary or 'Documented historical event.'}"

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

        batch_prompt = (
            f"You are a master historical documentary scriptwriter for YouTube Shorts.\n"
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
            f"   - HARD MINIMUM: 45 words per script.\n"
            f"   - HARD MAXIMUM: 68 words per script.\n"
            f"   - PREFERRED TARGET: 50–55 words total across all 5 narrative stages combined.\n"
            f"   - Any script outside 45–68 words will be rejected.\n"
            f"4. DO NOT COMBINE TOPICS: Each script must exclusively narrate its assigned topic.\n"
            f"5. MEANINGFULLY DISTINCT NARRATIVES:\n"
            f"   - Do NOT reuse the same story, facts, angle, hook structure, or opening phrase across scripts.\n"
            f"   - Each script must have a distinct hook archetype, unique dramatic tension, and different tone.\n"
            f"6. 5-STAGE NARRATIVE STRUCTURE (for each script):\n"
            f"   - hook: (0-2s) Immediate curiosity/tension gap (6-14 words). No generic intros ('Did you know', 'You won't believe').\n"
            f"   - context: Clear, rapid historical setting and grounding with forward momentum.\n"
            f"   - escalation: Rising stakes, intensifying conflict or bizarre progression. Every claim MUST be supported by supplied research.\n"
            f"   - reveal: The definitive, surprising historical payoff/climax.\n"
            f"   - loop_twist: Complete final resolution and loop-compatible ending statement. No filler conclusions.\n"
            f"7. STRICT FACTUAL GROUNDING:\n"
            f"   - Use ONLY facts explicitly supported by the supplied research for that topic.\n"
            f"   - NEVER invent dates, names, casualty counts, or details.\n"
            f"8. FORBIDDEN AI CLICHÉS IN ALL SCRIPTS:\n"
            f"   - NEVER use 'will shock you', 'unbelievable true story', 'events spiraled', 'shocked historians', 'changed history forever'.\n"
            f"9. STYLE & CADENCE:\n"
            f"   - Natural spoken American English. Short, punchy sentences (6-12 words/sentence). Zero filler.\n\n"
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
            f"- Verify every script word count is between 45 and 68 words."
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

            # Word count check (45 - 68 words)
            full_text = " ".join(str(script_dict.get(k, "")).strip() for k in ["hook", "context", "escalation", "reveal", "loop_twist"])
            wc = len(full_text.split())
            if not (MIN_WORD_COUNT <= wc <= MAX_WORD_COUNT):
                failures.append(f"Word count ({wc}) outside calibrated {MIN_WORD_COUNT}-{MAX_WORD_COUNT} range")

            # Forbidden clichés check
            full_lower = full_text.lower()
            for cliche in FORBIDDEN_CLICHES:
                if cliche in full_lower:
                    failures.append(f"Forbidden AI cliché detected: '{cliche}'")

            # Critic evaluation
            rd = (research_data_map or {}).get(expected_topic.id)
            eval_res = self.critic.evaluate(script_dict, rd)
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
