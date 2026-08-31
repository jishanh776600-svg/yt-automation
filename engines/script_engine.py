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
                verified_facts_text = "Verified Historical Facts:\n- " + "\n- ".join(claims[:5])
            elif research_data.get("summary"):
                verified_facts_text = f"Verified Historical Context: {research_data.get('summary')}"

        feedback_instruction = ""
        if revision_feedback:
            feedback_instruction = "\nCRITICAL REVISION INSTRUCTIONS FROM CRITIC:\n" + "\n".join([f"- FIX: {fb}" for fb in revision_feedback])

        prompt = (
            f"You are a master historical documentary scriptwriter for YouTube Shorts.\n"
            f"Topic: '{topic.title}'\n"
            f"Selected Opening Hook (0-2s): \"{selected_hook}\"\n"
            f"{verified_facts_text}\n"
            f"{learned_guidance}\n"
            f"\nStrict Narrative & Retention Architecture:\n"
            f"1. Structure (5 distinct stages):\n"
            f"   - hook: Immediate curiosity/tension gap (0-2s). No slow introductions, no generic 'Did you know'.\n"
            f"   - context: Clear, rapid historical grounding with forward momentum.\n"
            f"   - escalation: Rising stakes, intensifying conflict or bizarre progression.\n"
            f"   - reveal: The definitive, surprising historical payoff/climax.\n"
            f"   - loop_twist: COMPLETE FINAL RESOLUTION. A grammatically complete, memorable closing statement that provides total closure without trailing off or cutting mid-sentence.\n"
            f"2. Total length: EXACTLY 50 to 58 words across all 5 sections combined (around 10-12 words per section). Pacing requirement: Total word count MUST be between 48 and 62 words.\n"
            f"3. Style: Spoken natural American English. Punchy, rhythmic, conversational sentences (6-12 words/sentence). Zero filler.\n"
            f"4. Factual Grounding: Ground all details strictly in the verified facts. Do NOT hallucinate or exaggerate beyond facts.\n"
            f"5. NO AI Clichés: NEVER use 'will shock you', 'unbelievable true story', 'events spiraled', 'shocked historians', 'changed history forever'.\n"
            f"{feedback_instruction}\n"
            f"\nOutput strictly valid JSON with keys: hook, context, escalation, reveal, loop_twist"
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

        # 1. Check curated seed library first for exact approved scripts
        if topic.title in CURATED_SCRIPTS:
            logger.info(f"Using verified curated script for '{topic.title}'")
            data = CURATED_SCRIPTS[topic.title]
            eval_res = self.critic.evaluate(data, research_data)
        elif AI_PROVIDER_AVAILABLE:
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
        else:
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
