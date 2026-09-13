"""
Intelligent Ending & Loop Strategy Engine.
Every Short intentionally designs its final seconds to avoid abrupt stops.

Supports 4 ending modes:
  A) SEAMLESS_LOOP: Semantic callback linking final words directly to the opening hook.
  B) UNRESOLVED_MYSTERY: Atmospheric, lingering enigma ending.
  C) PROVOCATIVE_QUESTION: Story-grounded inquiry (not generic engagement bait).
  D) CONSEQUENCE_REVEAL: Dramatic historical or geopolitical aftermath.
"""
import re
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict


class EndingMode(str, Enum):
    SEAMLESS_LOOP = "SEAMLESS_LOOP"
    UNRESOLVED_MYSTERY = "UNRESOLVED_MYSTERY"
    PROVOCATIVE_QUESTION = "PROVOCATIVE_QUESTION"
    CONSEQUENCE_REVEAL = "CONSEQUENCE_REVEAL"


@dataclass
class EndingStrategyPlan:
    ending_mode: EndingMode
    hook_anchor: str
    closing_text: str
    is_semantic_loop: bool
    loop_callback_phrase: Optional[str] = None
    provocative_question: Optional[str] = None
    transition_tail_sec: float = 0.4
    engagement_strategy: str = ""
    retention_target_sec: float = 3.0

    @property
    def closing_sentence(self) -> str:
        return self.closing_text

    @property
    def viewer_prompt(self) -> str:
        return self.provocative_question or self.engagement_strategy

    @property
    def hook_callback_text(self) -> str:
        return self.loop_callback_phrase or ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ending_mode"] = self.ending_mode.value if hasattr(self.ending_mode, "value") else str(self.ending_mode)
        d["closing_sentence"] = self.closing_sentence
        d["viewer_prompt"] = self.viewer_prompt
        d["hook_callback_text"] = self.hook_callback_text
        return d


class EndingStrategyEngine:
    """Evaluates script flow and formulates tailored Short ending."""

    def plan_ending(
        self,
        hook: str = "",
        reveal: str = "",
        loop_twist: str = "",
        category: str = "",
        topic_title: str = "",
        script_text: str = ""
    ) -> EndingStrategyPlan:
        """
        Determines the optimal ending mode and generates structured ending metadata.
        Does NOT force a question onto every Short.
        Avoids generic engagement bait like 'What do you think? Comment below!'.
        """
        if script_text:
            sentences = [s.strip() for s in re.split(r'[.!?]+', script_text) if s.strip()]
            if not hook and sentences:
                hook = sentences[0]
            if not loop_twist and len(sentences) > 1:
                loop_twist = sentences[-1]
            if not reveal and len(sentences) > 2:
                reveal = sentences[-2]

        full_context = f"{category} {topic_title} {hook} {reveal} {loop_twist} {script_text}".lower()

        # 1. Detect if story naturally fits an Unresolved Mystery
        if any(k in full_context for k in [
            "unsolved", "disappear", "vanished", "never found", "mystery",
            "enigma", "cipher", "unexplained", "baffling", "haunted", "lead masks", "tamam shud"
        ]):
            mode = EndingMode.UNRESOLVED_MYSTERY
            is_loop = False
            question = None
            # If there's an active controversy or binary theory, formulate a provocative story-specific inquiry
            if any(w in full_context for w in ["murder", "accident", "alien", "hoax", "conspiracy", "secret"]):
                mode = EndingMode.PROVOCATIVE_QUESTION
                if "hoax" in full_context or "aristocrat" in full_context:
                    question = "Was it a calculated aristocratic hoax—or something genuinely unexplained?"
                elif "murder" in full_context or "accident" in full_context:
                    question = "Was it a catastrophic accident—or did someone want them silenced?"
                else:
                    question = "Was it an ingenious deception—or a phenomenon science still cannot explain?"

            strategy_desc = "Lingering historical enigma with story-grounded reflection"

        # 2. Detect if story has an ironic loop twist / circular structure
        elif any(k in full_context for k in [
            "again", "cycle", "surrendered", "casualty", "negative one", "kettle",
            "loop", "wholesome", "repeated", "irony", "ironic", "ended where it began"
        ]) or (len(hook.split()) >= 4 and any(w in loop_twist.lower() for w in hook.lower().split()[:3])):
            mode = EndingMode.SEAMLESS_LOOP
            is_loop = True
            question = None
            strategy_desc = "Seamless circular narrative callback linking final line into opening hook"

        # 3. Detect modern geopolitical / consequence ending
        elif any(k in full_context for k in [
            "war", "treaty", "market", "economy", "crisis", "chokepoint", "balance of power",
            "paralyze", "destabilize", "sanction", "conflict", "fleet", "patrol"
        ]):
            mode = EndingMode.CONSEQUENCE_REVEAL
            is_loop = False
            question = None
            strategy_desc = "Strategic geopolitical consequence and enduring global impact"

        # 4. Default: Seamless semantic loop
        else:
            mode = EndingMode.SEAMLESS_LOOP
            is_loop = True
            question = None
            strategy_desc = "Seamless narrative loop back to beginning"

        # Derive loop callback phrase if applicable
        callback_phrase = None
        if mode == EndingMode.SEAMLESS_LOOP:
            hook_lead = " ".join(hook.split()[:4])
            callback_phrase = f"And that's why {hook_lead}..."

        return EndingStrategyPlan(
            ending_mode=mode,
            hook_anchor=hook,
            closing_text=loop_twist or reveal,
            is_semantic_loop=is_loop,
            loop_callback_phrase=callback_phrase,
            provocative_question=question,
            transition_tail_sec=0.4,
            engagement_strategy=strategy_desc
        )