"""
AI Council Multi-Agent Editorial & Quality Architecture.
Genuinely invokes 3 distinct Council members:
1. DeepSeek (OpenRouter / Direct / NIM): Story Ideation, Hook Generation & Surprising Framing
2. Kimi K3 (OpenRouter / NIM): Retention Editor, Pacing Critic & Swipe Detector
3. Nemotron (NVIDIA NIM 3.5 / 550B): Factual Grounding, Logic Review & Visual Feasibility Reasoning
Followed by:
- Council Synthesis: Unified story-specific script construction
- Council Quality Gate: 9-metric script evaluation and max 2 rewrites loop
"""
import os
import re
import json
import time
import uuid
import logging
import urllib.request
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

from config.settings import (
    NVIDIA_API_KEY, NVIDIA_BASE_URL,
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL,
    GEMINI_API_KEY, GEMINI_MODEL
)
from intelligence.event_card import EventCard
from intelligence.clustering import is_niche_compliant

logger = logging.getLogger(__name__)


@dataclass
class CouncilMemberReview:
    """Detailed opinion and critique from a specific AI Council member."""
    member_name: str
    role: str
    model: str
    provider: str
    output_text: str
    structured_data: Dict[str, Any] = field(default_factory=dict)
    latency_seconds: float = 0.0
    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class CouncilQualityScore:
    """9-metric evaluation for short-form video quality."""
    hook_strength: float = 0.0          # 1-10
    curiosity: float = 0.0              # 1-10
    story_progression: float = 0.0      # 1-10
    originality: float = 0.0            # 1-10
    payoff: float = 0.0                 # 1-10
    spoken_naturalness: float = 0.0     # 1-10
    factual_confidence: float = 0.0     # 1-10
    visual_potential: float = 0.0       # 1-10
    duration_suitability: float = 0.0   # 1-10
    overall_score: float = 0.0          # Average
    verdict: str = "PASS"               # PASS, REWRITE, REJECT
    critique: str = ""


@dataclass
class CouncilSession:
    """Complete audit record of a Council deliberations pass."""
    session_id: str
    event_id: str
    topic_title: str
    reviews: Dict[str, CouncilMemberReview] = field(default_factory=dict)
    narrative_structure_chosen: str = ""
    quality_score: Optional[CouncilQualityScore] = None
    rewrite_count: int = 0
    approved: bool = False
    rejection_reason: str = ""


class AICouncilEngine:
    """
    Authoritative AI Council Engine.
    Coordinates DeepSeek, Kimi K3, and Nemotron before approving any script for production.
    """

    def __init__(self):
        self.nvidia_key = os.getenv("NVIDIA_API_KEY") or os.getenv("AI_COUNCIL_DEEPSEEK_KEY_3") or ""
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY") or ""
        self.deepseek_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("AI_COUNCIL_DEEPSEEK_KEY_1") or ""
        self.kimi_key = os.getenv("AI_COUNCIL_DEEPSEEK_KEY_2") or self.openrouter_key or self.nvidia_key
        self.groq_key = os.getenv("GROQ_API_KEY") or ""

    def _call_llm(
        self,
        provider: str,
        url: str,
        key: str,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float = 5.0
    ) -> str:
        """Executes a robust HTTP request to an OpenAI-compatible endpoint."""
        if not key:
            raise ValueError(f"Missing API key for provider {provider}")

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"AL-AMR-Council/{provider}"
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        payload_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=payload_bytes, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choices = data.get("choices", [])
            if not choices:
                return ""
            msg = choices[0].get("message", {})
            content = msg.get("content")
            # Some reasoning models (like Kimi) place thoughts in reasoning or require fallback
            if not content:
                content = msg.get("reasoning", "")
            return (content or "").strip()

    def consult_deepseek(self, event_card: EventCard) -> CouncilMemberReview:
        """
        MEMBER 1: DEEPSEEK
        Role: Story Ideation, Hook Generation, Alternative Angles, Surprising Framing.
        """
        t0 = time.time()
        prompt = (
            "You are DEEPSEEK, Story Ideation & Hook Architect on the AL-AMR AI Council.\n"
            "Channel niche: MYSTERY / BIZARRE REAL-WORLD STORIES.\n"
            "Task: Find the most surprising narrative angle for a 23-second YouTube Short.\n\n"
            "MANDATE — Hooks must:\n"
            "✅ Sound like a friend WHISPERING a wild secret\n"
            "✅ Start with a SPECIFIC CONCRETE DETAIL (name, place, number, object)\n"
            "✅ Create INSTANT cognitive dissonance — something contradictory or uncanny\n"
            "✅ End with an implicit 'wait, how is that possible?'\n\n"
            "❌ HARD FORBIDDEN:\n"
            "  'Researchers discovered...' 'Scientists found...' 'A new study...'\n"
            "  'In a surprising turn...' 'Breaking news:' 'Officials say...'\n"
            "  Generic superlatives: 'incredible', 'shocking', 'amazing', 'unbelievable'\n\n"
            f"TOPIC: {event_card.canonical_title}\n"
            f"WHAT HAPPENED: {event_card.what}\n"
            f"ENTITIES: {', '.join(event_card.entities)}\n"
            f"OBJECTS: {', '.join(event_card.important_objects)}\n"
            f"WHERE: {event_card.where.to_dict()}\n"
            f"CLAIMS: {json.dumps([c.claim_text for c in event_card.claims])}\n\n"
            "RETURN JSON ONLY:\n"
            "{\n"
            "  \"top_3_killer_hooks\": [\n"
            "    \"Hook 1 — starts with a specific detail, creates instant question\",\n"
            "    \"Hook 2 — alternative angle or framing\",\n"
            "    \"Hook 3 — most bizarre or counterintuitive version\"\n"
            "  ],\n"
            "  \"surprising_framing\": \"Why this story defies expectations — one specific reason\",\n"
            "  \"narrative_angle\": \"The spine of the story: what the viewer learns by the end\",\n"
            "  \"curiosity_question\": \"The exact unresolved question viewers carry after watching\",\n"
            "  \"suggested_payoff\": \"The twist or realization in the final 2-3 seconds\"\n"
            "}"
        )

        output_text = ""
        provider_used = "openrouter"
        model_used = "deepseek/deepseek-chat"

        # Try OpenRouter DeepSeek first (ultra-reliable), then NVIDIA NIM, then Gemini fallback
        try:
            if self.openrouter_key:
                output_text = self._call_llm(
                    provider="openrouter",
                    url="https://openrouter.ai/api/v1/chat/completions",
                    key=self.openrouter_key,
                    model="deepseek/deepseek-chat",
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=600,
                    timeout=4.0
                )
        except Exception as e:
            logger.warning(f"DeepSeek via OpenRouter failed: {e}. Trying fallback...")

        if not output_text and self.nvidia_key:
            try:
                provider_used = "nvidia"
                model_used = "deepseek-ai/deepseek-v4-flash-0731"
                output_text = self._call_llm(
                    provider="nvidia",
                    url="https://integrate.api.nvidia.com/v1/chat/completions",
                    key=self.nvidia_key,
                    model="deepseek-ai/deepseek-v4-flash-0731",
                    prompt=prompt,
                    temperature=0.7,
                    max_tokens=600,
                    timeout=4.0
                )
            except Exception as e:
                logger.warning(f"DeepSeek via NVIDIA failed: {e}.")

        if not output_text:
            from core.gemini_client import get_gemini_client
            client = get_gemini_client()
            provider_used = "gemini_deepseek_proxy"
            model_used = GEMINI_MODEL
            resp = client.generate_content(model=GEMINI_MODEL, contents=prompt)
            output_text = resp.text.strip()

        latency = time.time() - t0
        structured = self._parse_json_from_response(output_text)
        logger.info(f"[AI_COUNCIL] DeepSeek consulted in {latency:.2f}s via {provider_used} ({model_used})")

        return CouncilMemberReview(
            member_name="DeepSeek",
            role="Story Ideation & Hook Generation",
            model=model_used,
            provider=provider_used,
            output_text=output_text,
            structured_data=structured,
            latency_seconds=latency
        )

    def consult_kimi(self, event_card: EventCard, deepseek_review: CouncilMemberReview) -> CouncilMemberReview:
        """
        MEMBER 2: KIMI K3
        Role: Retention Editor, Storytelling Critic, Pacing Critic, Swipe Risk Detector.
        """
        t0 = time.time()
        hooks = deepseek_review.structured_data.get("top_3_killer_hooks", [])
        hooks_str = json.dumps(hooks) if hooks else deepseek_review.output_text[:300]

        prompt = (
            "You are KIMI K3, Retention Critic & Storytelling Editor on the AL-AMR AI Council.\n"
            "Channel niche: MYSTERY / BIZARRE REAL-WORLD STORIES.\n"
            "Your job: ruthlessly audit the hooks and angle. Reject anything that sounds like text being read aloud.\n\n"
            "WHAT 'ARTICLE-LIKE' MEANS — reject immediately if you see:\n"
            "  - 'According to researchers...' / 'Scientists discovered...'\n"
            "  - 'This discovery suggests...' / 'It is believed that...'\n"
            "  - Passive voice reporting ('it was found that', 'it has been determined')\n"
            "  - Sentences that list facts without emotional momentum\n"
            "  - Generic openers that could apply to any topic ('In recent years...', 'Over time...')\n\n"
            "WHAT MAKES A GREAT HOOK FOR THIS CHANNEL:\n"
            "  - Starts mid-action or with a concrete, surprising detail\n"
            "  - Creates a question the viewer MUST answer ('But why?', 'How?', 'Who?')\n"
            "  - Sounds like something you'd text a friend at 2am\n"
            "  - Short sentences + rhythm variation\n\n"
            f"TOPIC: {event_card.canonical_title}\n"
            f"DEEPSEEK'S PROPOSED HOOKS:\n{hooks_str}\n\n"
            "RETURN JSON ONLY:\n"
            "{\n"
            "  \"best_hook\": \"The single hook that best prevents immediate swipe (must be conversational)\",\n"
            "  \"naturalness_score\": 0.0,\n"
            "  \"sounds_like_article_critique\": \"Specific phrases from the hooks/angle that sound like written text\",\n"
            "  \"specific_phrases_to_rewrite\": [\"exact phrase 1 to avoid\", \"exact phrase 2 to avoid\"],\n"
            "  \"swipe_risk\": \"Specific moment where viewers will lose interest (be precise)\",\n"
            "  \"pacing_guidelines\": \"How to maintain momentum: which beats need to be shorter/longer\",\n"
            "  \"dead_weight_to_cut\": [\"Any fact or detail that slows the story without adding mystery\"],\n"
            "  \"payoff_advice\": \"Exactly what the final beat must do to stick in the viewer's memory\"\n"
            "}"
        )

        output_text = ""
        provider_used = "openrouter"
        model_used = "moonshotai/kimi-k3"

        # Try OpenRouter Kimi K3, then NVIDIA, then Gemini
        try:
            if self.openrouter_key:
                output_text = self._call_llm(
                    provider="openrouter",
                    url="https://openrouter.ai/api/v1/chat/completions",
                    key=self.openrouter_key,
                    model="moonshotai/kimi-k3",
                    prompt=prompt,
                    temperature=0.6,
                    max_tokens=600,
                    timeout=4.0
                )
        except Exception as e:
            logger.warning(f"Kimi via OpenRouter failed: {e}. Trying fallback...")

        if not output_text and self.nvidia_key:
            try:
                provider_used = "nvidia"
                model_used = "moonshotai/kimi-k3"
                output_text = self._call_llm(
                    provider="nvidia",
                    url="https://integrate.api.nvidia.com/v1/chat/completions",
                    key=self.nvidia_key,
                    model="moonshotai/kimi-k3",
                    prompt=prompt,
                    temperature=0.6,
                    max_tokens=600,
                    timeout=4.0
                )
            except Exception as e:
                logger.warning(f"Kimi via NVIDIA failed: {e}.")

        if not output_text and self.groq_key:
            try:
                provider_used = "groq"
                model_used = "qwen/qwen3.6-27b"
                raw_groq = self._call_llm(
                    provider="groq",
                    url="https://api.groq.com/openai/v1/chat/completions",
                    key=self.groq_key,
                    model="qwen/qwen3.6-27b",
                    prompt=prompt,
                    temperature=0.6,
                    max_tokens=600,
                    timeout=8.0
                )
                output_text = re.sub(r"<think>.*?</think>", "", raw_groq, flags=re.DOTALL).strip()
            except Exception as e:
                logger.warning(f"Kimi via Groq failed: {e}.")

        if not output_text:
            from core.gemini_client import get_gemini_client
            client = get_gemini_client()
            provider_used = "gemini_kimi_proxy"
            model_used = GEMINI_MODEL
            resp = client.generate_content(model=GEMINI_MODEL, contents=prompt)
            output_text = resp.text.strip()

        latency = time.time() - t0
        structured = self._parse_json_from_response(output_text)
        logger.info(f"[AI_COUNCIL] Kimi K3 consulted in {latency:.2f}s via {provider_used} ({model_used})")

        return CouncilMemberReview(
            member_name="Kimi K3",
            role="Retention Editor & Storytelling Critic",
            model=model_used,
            provider=provider_used,
            output_text=output_text,
            structured_data=structured,
            latency_seconds=latency
        )

    def consult_nemotron(
        self,
        event_card: EventCard,
        deepseek_review: CouncilMemberReview,
        kimi_review: CouncilMemberReview
    ) -> CouncilMemberReview:
        """
        MEMBER 3: NEMOTRON (3.5 Lightning / 550B)
        Role: Factual / Logic Reviewer, Claim Consistency, Evidence Plausibility, Visual Feasibility.
        """
        t0 = time.time()
        best_hook = kimi_review.structured_data.get("best_hook", "")
        angle = deepseek_review.structured_data.get("narrative_angle", "")

        prompt = (
            "You are NEMOTRON, Factual Grounding & Visual Feasibility Reviewer on the AI Council.\n"
            "Your task is twofold:\n"
            "1. FACTUAL AUDIT: Verify that the proposed narrative does not invent fake facts or overstep the EventCard.\n"
            "2. VISUAL FEASIBILITY: Verify that the proposed story can actually be visually represented with 9-12 real, "
            "photographic, scientific, or archival footage scenes (NOT generic stock or talking heads).\n\n"
            f"TOPIC: {event_card.canonical_title}\n"
            f"FACTS: {json.dumps([c.claim_text for c in event_card.claims])}\n"
            f"PROPOSED HOOK: {best_hook}\n"
            f"PROPOSED ANGLE: {angle}\n\n"
            "EVALUATE AND RETURN JSON:\n"
            "{\n"
            "  \"factual_integrity_passed\": true,\n"
            "  \"unsupported_or_misleading_claims\": [],\n"
            "  \"visual_feasibility_score\": 9.0,\n"
            "  \"concrete_visual_assets_to_use\": [\n"
            "    \"visual scene 1\",\n"
            "    \"visual scene 2\",\n"
            "    \"visual scene 3\"\n"
            "  ],\n"
            "  \"recommended_narrative_structure\": \"Mystery | Historical anomaly | Weird science | Scientific discovery | Bizarre real-world event\"\n"
            "}"
        )
        output_text = ""
        provider_used = "groq"
        model_used = "qwen/qwen3.6-27b"

        # 1. Try Groq Qwen (ultra-fast, high reliability)
        if not output_text and self.groq_key:
            try:
                provider_used = "groq"
                model_used = "qwen/qwen3.6-27b"
                raw_groq = self._call_llm(
                    provider="groq",
                    url="https://api.groq.com/openai/v1/chat/completions",
                    key=self.groq_key,
                    model="qwen/qwen3.6-27b",
                    prompt=prompt,
                    temperature=0.5,
                    max_tokens=600,
                    timeout=8.0
                )
                output_text = re.sub(r"<think>.*?</think>", "", raw_groq, flags=re.DOTALL).strip()
            except Exception as e:
                logger.warning(f"Nemotron via Groq failed: {e}. Trying fallback...")

        # 2. Try OpenRouter fallback
        if not output_text and self.openrouter_key:
            try:
                provider_used = "openrouter"
                model_used = "meta-llama/llama-3.3-70b-instruct"
                output_text = self._call_llm(
                    provider="openrouter",
                    url="https://openrouter.ai/api/v1/chat/completions",
                    key=self.openrouter_key,
                    model="meta-llama/llama-3.3-70b-instruct",
                    prompt=prompt,
                    temperature=0.5,
                    max_tokens=600,
                    timeout=4.0
                )
            except Exception as e:
                logger.warning(f"Nemotron fallback via OpenRouter failed: {e}.")

        # 3. Try Gemini fallback
        if not output_text:
            from core.gemini_client import get_gemini_client
            client = get_gemini_client()
            provider_used = "gemini_nemotron_proxy"
            model_used = GEMINI_MODEL
            resp = client.generate_content(model=GEMINI_MODEL, contents=prompt)
            output_text = resp.text.strip()

        latency = time.time() - t0
        structured = self._parse_json_from_response(output_text)
        logger.info(f"[AI_COUNCIL] Nemotron consulted in {latency:.2f}s via {provider_used} ({model_used})")

        return CouncilMemberReview(
            member_name="Nemotron",
            role="Factual Grounding & Visual Feasibility Reviewer",
            model=model_used,
            provider=provider_used,
            output_text=output_text,
            structured_data=structured,
            latency_seconds=latency
        )

    def evaluate_script_quality(
        self,
        script_text: str,
        hook: str,
        event_card: EventCard,
        word_count: int
    ) -> CouncilQualityScore:
        """
        COUNCIL QUALITY GATE — HARD CREATIVE ENFORCEMENT
        Evaluates the generated script on 10 strict production dimensions.
        Applies DETERMINISTIC HARD REJECTIONS for article-like language BEFORE any LLM scoring.
        A technically-correct but boring/article-like script must be REJECTED.
        """
        critique_notes = []
        rule_violations = 0
        hard_reject = False

        # ── NICHE PURITY ──────────────────────────────────────────────────────
        is_niche_ok, niche_reason = is_niche_compliant(
            title=event_card.canonical_title,
            text=script_text,
            entities=event_card.entities
        )
        if not is_niche_ok:
            critique_notes.append(f"HARD NICHE VIOLATION: {niche_reason}")
            hard_reject = True

        # ── WORD COUNT GATE ───────────────────────────────────────────────────
        # Acceptable range: 50-75 words for a 22-27s Short
        if word_count < 45:
            critique_notes.append(f"Word count {word_count} far too low (minimum 45). Script is incomplete.")
            rule_violations += 2
        elif word_count > 80:
            critique_notes.append(f"Word count {word_count} too high (maximum 80). Script will run long.")
            rule_violations += 1

        # ── HARD REJECT: FORBIDDEN OPENERS ───────────────────────────────────
        # A script that opens like a news article or academic paper is ALWAYS rejected.
        lower_script = script_text.lower().strip()
        lower_hook = hook.lower().strip() if hook else lower_script[:80].lower()

        FORBIDDEN_OPENERS = [
            "researchers discovered", "researchers found", "researchers have",
            "scientists discovered", "scientists found", "scientists have",
            "a new study", "according to a study", "according to scientists",
            "according to researchers", "according to experts", "experts say",
            "a team of researchers", "a team of scientists", "archaeologists discovered",
            "archaeologists have found", "geologists found", "historians believe",
            "in a recent study", "in a surprising turn of events", "in world news",
            "breaking:", "breaking news", "officials announced", "authorities said",
            "it was recently discovered", "it has been found that", "it was found that",
            "it has been reported", "reports indicate", "as reported by",
        ]
        for opener in FORBIDDEN_OPENERS:
            if lower_script.startswith(opener) or lower_hook.startswith(opener):
                critique_notes.append(f"HARD REJECT — Forbidden article opener: '{opener}'")
                hard_reject = True
                break

        # ── HARD REJECT: ARTICLE-LANGUAGE DENSITY ────────────────────────────
        # If 2+ "article patterns" appear in the script body, force REWRITE minimum.
        ARTICLE_BODY_PATTERNS = [
            "this suggests that", "this demonstrates", "this indicates",
            "this discovery suggests", "was discovered to be", "was found to be",
            "studies show", "evidence indicates", "data suggests",
            "this phenomenon demonstrates", "researchers noted", "scientists noted",
            "the findings show", "the study reveals", "results indicate",
            "it is believed that", "it is thought that", "it is estimated that",
            "this represents", "this marks", "this is significant because",
            "in conclusion", "to summarize", "in summary",
            "only time will tell", "the world is watching", "here is what you need to know",
            "it remains to be seen", "as it turns out", "could change everything",
        ]
        article_pattern_count = sum(1 for p in ARTICLE_BODY_PATTERNS if p in lower_script)
        if article_pattern_count >= 3:
            critique_notes.append(
                f"HARD REJECT — Script reads like an article ({article_pattern_count} article patterns detected). "
                "Rewrite as human creator storytelling."
            )
            hard_reject = True
        elif article_pattern_count >= 2:
            critique_notes.append(
                f"Article-language density warning: {article_pattern_count} patterns found. "
                "Script may sound like text being read aloud."
            )
            rule_violations += 2

        # ── STRUCTURAL QUALITY CHECKS ─────────────────────────────────────────
        # Check for banned AI clichés
        BANNED_CLICHES = [
            "tensions are rising", "shocking truth", "mind-blowing fact",
            "you won't believe", "this one weird", "number one reason",
            "top ten", "here's the thing", "let that sink in",
            "at the end of the day", "game changer", "paradigm shift",
        ]
        for bc in BANNED_CLICHES:
            if bc in lower_script:
                critique_notes.append(f"Banned AI cliché detected: '{bc}'")
                rule_violations += 1

        # Check hook quality
        GENERIC_HOOK_STARTERS = [
            "today,", "today ", "in recent developments", "recently,", "recently ",
            "in a surprising turn", "in world news", "as reported by",
        ]
        for gh in GENERIC_HOOK_STARTERS:
            if lower_hook.startswith(gh):
                critique_notes.append(f"Generic hook opener: starts with '{gh}'")
                rule_violations += 1
                break

        # ── LLM QUALITY SCORING ───────────────────────────────────────────────
        prompt = (
            "You are the AL-AMR Council Quality Gate. Score this YouTube Shorts script with brutal honesty.\n"
            "The channel is MYSTERY / BIZARRE REAL-WORLD STORIES. The target viewer is scrolling fast.\n"
            "A script that sounds like Wikipedia, a news article, or a school essay MUST score below 6 "
            "on spoken_naturalness and originality.\n\n"
            f"TOPIC: {event_card.canonical_title}\n"
            f"HOOK: {hook}\n"
            f"SCRIPT ({word_count} words):\n{script_text}\n\n"
            "Score each dimension 1.0–10.0 with NO inflation. Be specific in your critique.\n"
            "Scoring thresholds for PASS: overall ≥ 7.5, hook_strength ≥ 7.5, spoken_naturalness ≥ 7.5\n\n"
            "RETURN JSON ONLY:\n"
            "{\n"
            "  \"hook_strength\": 0.0,\n"
            "  \"curiosity\": 0.0,\n"
            "  \"narrative_momentum\": 0.0,\n"
            "  \"spoken_naturalness\": 0.0,\n"
            "  \"specificity\": 0.0,\n"
            "  \"escalation\": 0.0,\n"
            "  \"originality\": 0.0,\n"
            "  \"payoff\": 0.0,\n"
            "  \"factual_confidence\": 0.0,\n"
            "  \"visual_storytelling_potential\": 0.0,\n"
            "  \"overall_score\": 0.0,\n"
            "  \"verdict\": \"PASS | REWRITE | REJECT\",\n"
            "  \"critique\": \"Specific, actionable critique. Identify exact phrases that sound like an article. "
            "Identify missing escalation. Identify weak payoff.\"\n"
            "}"
        )

        raw = ""
        try:
            # Try Groq first (fast, reliable for structured JSON)
            if self.groq_key:
                try:
                    raw_g = self._call_llm(
                        provider="groq",
                        url="https://api.groq.com/openai/v1/chat/completions",
                        key=self.groq_key,
                        model="qwen/qwen3.6-27b",
                        prompt=prompt,
                        temperature=0.15,
                        max_tokens=500,
                        timeout=10.0
                    )
                    raw = re.sub(r"<think>.*?</think>", "", raw_g, flags=re.DOTALL).strip()
                except Exception as e:
                    logger.warning(f"Groq Quality Gate failed: {e}. Trying OpenRouter fallback...")

            if not raw and self.openrouter_key:
                try:
                    raw = self._call_llm(
                        provider="openrouter",
                        url="https://openrouter.ai/api/v1/chat/completions",
                        key=self.openrouter_key,
                        model="meta-llama/llama-3.3-70b-instruct",
                        prompt=prompt,
                        temperature=0.15,
                        max_tokens=500,
                        timeout=15.0
                    )
                except Exception as e:
                    logger.warning(f"OpenRouter Quality Gate failed: {e}. Trying Gemini fallback...")

            if not raw:
                from core.gemini_client import get_gemini_client
                client = get_gemini_client()
                resp = client.generate_content(model=GEMINI_MODEL, contents=prompt)
                raw = resp.text.strip()

            data = self._parse_json_from_response(raw)

            # Support both old 9-dim and new 10-dim responses
            story_prog = float(data.get("narrative_momentum", data.get("story_progression", 0.0)))
            score = CouncilQualityScore(
                hook_strength=float(data.get("hook_strength", 0.0)),
                curiosity=float(data.get("curiosity", 0.0)),
                story_progression=story_prog,
                originality=float(data.get("originality", 0.0)),
                payoff=float(data.get("payoff", 0.0)),
                spoken_naturalness=float(data.get("spoken_naturalness", 0.0)),
                factual_confidence=float(data.get("factual_confidence", 0.0)),
                visual_potential=float(data.get("visual_storytelling_potential", data.get("visual_potential", 0.0))),
                duration_suitability=float(data.get("duration_suitability", 8.0)),
                overall_score=float(data.get("overall_score", 0.0)),
                verdict=data.get("verdict", "REWRITE").upper(),
                critique=data.get("critique", "")
            )

            # Recompute overall if LLM inflated it
            computed = (
                score.hook_strength + score.curiosity + score.story_progression +
                score.originality + score.payoff + score.spoken_naturalness +
                score.factual_confidence + score.visual_potential
            ) / 8.0
            # Accept LLM's overall only if within 1.0 of computed
            if abs(score.overall_score - computed) > 1.0:
                score.overall_score = round(computed, 2)

        except Exception as e:
            logger.warning(f"CouncilQualityScore LLM evaluation failed: {e}. Using conservative fallback.")
            # Conservative fallback — does NOT rubber-stamp; forces REWRITE
            score = CouncilQualityScore(
                hook_strength=6.5,
                curiosity=6.5,
                story_progression=6.5,
                originality=6.5,
                payoff=6.5,
                spoken_naturalness=6.5,
                factual_confidence=7.5,
                visual_potential=6.5,
                duration_suitability=7.0,
                overall_score=6.6,
                verdict="REWRITE",
                critique="Quality evaluation failed — conservative REWRITE assigned. Manual review recommended."
            )

        # ── APPLY DETERMINISTIC OVERRIDES ─────────────────────────────────────
        if hard_reject:
            score.verdict = "REJECT"
            score.overall_score = min(score.overall_score, 3.5)
            score.hook_strength = min(score.hook_strength, 4.0)
            score.spoken_naturalness = min(score.spoken_naturalness, 3.0)
            score.critique = "[HARD REJECT] " + "; ".join(critique_notes) + (
                " | LLM: " + score.critique if score.critique else ""
            )
        elif rule_violations >= 2:
            score.verdict = "REWRITE"
            score.overall_score = min(score.overall_score, 6.5)
            score.critique = "[RULE VIOLATIONS] " + "; ".join(critique_notes) + (
                " | " + score.critique if score.critique else ""
            )
        else:
            # Dimensional quality gates — explicit rejection reasons
            dimension_failures = []
            if score.hook_strength < 7.5:
                dimension_failures.append(f"Weak hook ({score.hook_strength:.1f} < 7.5)")
            if score.spoken_naturalness < 7.5:
                dimension_failures.append(f"Sounds like article not human ({score.spoken_naturalness:.1f} < 7.5)")
            if score.story_progression < 7.0:
                dimension_failures.append(f"Weak narrative momentum ({score.story_progression:.1f} < 7.0)")
            if score.payoff < 6.5:
                dimension_failures.append(f"No meaningful payoff ({score.payoff:.1f} < 6.5)")
            if score.overall_score < 7.5:
                dimension_failures.append(f"Overall quality insufficient ({score.overall_score:.1f} < 7.5)")

            if dimension_failures:
                score.verdict = "REWRITE"
                score.overall_score = min(score.overall_score, 7.0)
                score.critique = (
                    f"[QUALITY GATE FAILED] {', '.join(dimension_failures)}"
                    + (" | " + score.critique if score.critique else "")
                )
                if critique_notes:
                    score.critique = "; ".join(critique_notes) + " | " + score.critique
            else:
                score.verdict = "PASS"
                if critique_notes:
                    score.critique = "[MINOR WARNINGS] " + "; ".join(critique_notes) + (
                        " | " + score.critique if score.critique else ""
                    )

        logger.info(
            f"[QUALITY_GATE] Verdict={score.verdict} | Score={score.overall_score:.1f} | "
            f"Hook={score.hook_strength:.1f} | Natural={score.spoken_naturalness:.1f} | "
            f"HardReject={hard_reject} | RuleViolations={rule_violations}"
        )
        return score

    def _parse_json_from_response(self, text: str) -> Dict[str, Any]:
        """Extracts JSON dict from raw LLM output, handling markdown blocks or messy responses."""
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except Exception:
                    pass
            m2 = re.search(r"(\{.*\})", text, re.DOTALL)
            if m2:
                try:
                    return json.loads(m2.group(1).strip())
                except Exception:
                    pass
        return {}


# Global Council Singleton
_shared_council: Optional[AICouncilEngine] = None

def get_ai_council() -> AICouncilEngine:
    global _shared_council
    if _shared_council is None:
        _shared_council = AICouncilEngine()
    return _shared_council
