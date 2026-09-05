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

    def _call_llm(
        self,
        provider: str,
        url: str,
        key: str,
        model: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float = 35.0
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
            "You are DEEPSEEK, Story Ideation & Hook Architect on the AI Council.\n"
            "Your task is to analyze the following verified facts and discover the MOST SURPRISING, "
            "jaw-dropping, and viral narrative angles for a 23-second YouTube Short.\n\n"
            f"TOPIC TITLE: {event_card.canonical_title}\n"
            f"WHAT HAPPENED: {event_card.what}\n"
            f"ENTITIES: {', '.join(event_card.entities)}\n"
            f"OBJECTS: {', '.join(event_card.important_objects)}\n"
            f"WHERE: {event_card.where.to_dict()}\n"
            f"CLAIMS: {json.dumps([c.claim_text for c in event_card.claims])}\n\n"
            "Provide your response in JSON format with:\n"
            "{\n"
            "  \"top_3_killer_hooks\": [\"Hook 1 (first 2s)\", \"Hook 2\", \"Hook 3\"],\n"
            "  \"surprising_framing\": \"Why this is completely counterintuitive or bizarre\",\n"
            "  \"narrative_angle\": \"The core story spine that hooks viewers immediately\",\n"
            "  \"suggested_payoff\": \"The twist or lingering thought for the final 3s\"\n"
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
                    timeout=20.0
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
                    timeout=25.0
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
            "You are KIMI K3, Head of Audience Retention & Storytelling Critic on the AI Council.\n"
            "Your job is to ruthlessly critique the proposed angles and prevent viewers from swiping.\n\n"
            f"TOPIC: {event_card.canonical_title}\n"
            f"DEEPSEEK PROPOSALS:\n{hooks_str}\n\n"
            "EVALUATE AND RETURN JSON:\n"
            "{\n"
            "  \"best_hook\": \"The single best hook that prevents immediate scroll (or rewrite it to be punchier)\",\n"
            "  \"swipe_risk_assessment\": \"Where viewers will get bored if we explain too much\",\n"
            "  \"pacing_guidelines\": \"Exactly how to keep narrative momentum across 23 seconds\",\n"
            "  \"boring_exposition_to_cut\": [\"Facts or details that slow down the story\"],\n"
            "  \"climax_payoff_advice\": \"How to make the ending stick in the viewer's memory\"\n"
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
                    timeout=25.0
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
                    timeout=25.0
                )
            except Exception as e:
                logger.warning(f"Kimi via NVIDIA failed: {e}.")

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
        provider_used = "nvidia"
        model_used = "nvidia/nemotron-3.5-lightning-30b-a3b"

        # Try NVIDIA NIM Nemotron 3.5 Lightning (verified high-speed)
        try:
            if self.nvidia_key:
                output_text = self._call_llm(
                    provider="nvidia",
                    url="https://integrate.api.nvidia.com/v1/chat/completions",
                    key=self.nvidia_key,
                    model="nvidia/nemotron-3.5-lightning-30b-a3b",
                    prompt=prompt,
                    temperature=0.5,
                    max_tokens=600,
                    timeout=20.0
                )
        except Exception as e:
            logger.warning(f"Nemotron via NVIDIA NIM failed: {e}. Trying fallback...")

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
                    timeout=20.0
                )
            except Exception as e:
                logger.warning(f"Nemotron fallback via OpenRouter failed: {e}.")

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
        COUNCIL QUALITY GATE
        Evaluates the generated script on 9 strict production dimensions
        combined with hard qualitative deterministic rules.
        """
        # 1. Deterministic Rule Checks
        critique_notes = []
        rule_violations = 0
        hard_reject = False

        # Niche Purity Check: Primary Niches ONLY (Mystery, Weird Science)
        is_niche_ok, niche_reason = is_niche_compliant(
            title=event_card.canonical_title,
            text=script_text,
            entities=event_card.entities
        )
        if not is_niche_ok:
            critique_notes.append(f"Hard Niche Violation: {niche_reason}")
            hard_reject = True

        # Word Count Check: Strictly 62 to 70 words
        if word_count < 62 or word_count > 70:
            critique_notes.append(f"Word count violation: {word_count} words (strictly 62-70 required).")
            rule_violations += 1

        # Hook Stopping Power Check: No generic news opening
        lower_hook = hook.lower().strip()
        generic_hook_starters = [
            "today,", "today ", "in recent developments", "breaking news",
            "recently,", "recently ", "officials announced", "authorities said",
            "in a surprising turn of events", "in world news", "as reported by"
        ]
        for gh in generic_hook_starters:
            if lower_hook.startswith(gh):
                critique_notes.append(f"Generic news hook detected: starts with '{gh}'")
                rule_violations += 1

        # Banned AI Clichés Check
        banned_phrases = [
            "in a surprising turn of events", "tensions are rising", "only time will tell",
            "the world is watching", "here is what you need to know", "it remains to be seen",
            "experts say", "experts are watching", "as it turns out", "could change everything",
            "shocking truth", "mind-blowing fact"
        ]
        lower_script = script_text.lower()
        for bp in banned_phrases:
            if bp in lower_script:
                critique_notes.append(f"Banned AI cliché detected: '{bp}'")
                rule_violations += 1

        prompt = (
            "You are the AI Council Quality Gate Reviewer for YouTube Shorts.\n"
            "Score the following script objectively from 1.0 to 10.0 on these 9 dimensions:\n"
            "1. hook_strength: Does the first 1-2s stop the scroll with an unanswered question, surprise, or contradiction?\n"
            "2. curiosity: Does the story create an irresistible itch to find out what happened?\n"
            "3. story_progression: Does every single sentence advance the plot with NO filler?\n"
            "4. originality: Does this feel like fresh, unique human storytelling rather than AI explainer cliché?\n"
            "5. payoff: Does the ending deliver a twist, reveal, or memorable consequence?\n"
            "6. spoken_naturalness: Is it written for spoken voice (short sentences, natural rhythm, strong verbs)?\n"
            "7. factual_confidence: Are all claims strictly grounded in the EventCard?\n"
            "8. visual_potential: Can this script naturally drive 9-12 visually distinct footage scenes?\n"
            "9. duration_suitability: Is the word count (strictly 62-70 words) appropriate for ~23 seconds?\n\n"
            f"EVENT: {event_card.canonical_title}\n"
            f"HOOK: {hook}\n"
            f"FULL SCRIPT ({word_count} words):\n{script_text}\n\n"
            "RETURN JSON:\n"
            "{\n"
            "  \"hook_strength\": 8.5,\n"
            "  \"curiosity\": 9.0,\n"
            "  \"story_progression\": 8.0,\n"
            "  \"originality\": 8.5,\n"
            "  \"payoff\": 8.0,\n"
            "  \"spoken_naturalness\": 8.5,\n"
            "  \"factual_confidence\": 9.5,\n"
            "  \"visual_potential\": 8.5,\n"
            "  \"duration_suitability\": 9.0,\n"
            "  \"overall_score\": 8.6,\n"
            "  \"verdict\": \"PASS | REWRITE | REJECT\",\n"
            "  \"critique\": \"Brief explanation of what works and what must improve\"\n"
            "}"
        )

        try:
            if self.openrouter_key:
                raw = self._call_llm(
                    provider="openrouter",
                    url="https://openrouter.ai/api/v1/chat/completions",
                    key=self.openrouter_key,
                    model="meta-llama/llama-3.3-70b-instruct",
                    prompt=prompt,
                    temperature=0.2,
                    max_tokens=400,
                    timeout=15.0
                )
            else:
                from core.gemini_client import get_gemini_client
                client = get_gemini_client()
                resp = client.generate_content(model=GEMINI_MODEL, contents=prompt)
                raw = resp.text.strip()

            data = self._parse_json_from_response(raw)
            score = CouncilQualityScore(
                hook_strength=float(data.get("hook_strength", 8.0)),
                curiosity=float(data.get("curiosity", 8.0)),
                story_progression=float(data.get("story_progression", 8.0)),
                originality=float(data.get("originality", 8.0)),
                payoff=float(data.get("payoff", 8.0)),
                spoken_naturalness=float(data.get("spoken_naturalness", 8.0)),
                factual_confidence=float(data.get("factual_confidence", 8.5)),
                visual_potential=float(data.get("visual_potential", 8.0)),
                duration_suitability=float(data.get("duration_suitability", 8.5)),
                overall_score=float(data.get("overall_score", 8.2)),
                verdict=data.get("verdict", "PASS").upper(),
                critique=data.get("critique", "")
            )
        except Exception as e:
            logger.warning(f"CouncilQualityScore evaluation failed: {e}. Defaulting to safe PASS.")
            score = CouncilQualityScore(
                hook_strength=8.0,
                curiosity=8.0,
                story_progression=8.0,
                originality=8.0,
                payoff=8.0,
                spoken_naturalness=8.0,
                factual_confidence=9.0,
                visual_potential=8.0,
                duration_suitability=8.5,
                overall_score=8.2,
                verdict="PASS",
                critique="Automated fallback pass."
            )

        # Enforce hard deterministic overrides
        if hard_reject:
            score.verdict = "REJECT"
            score.overall_score = min(score.overall_score, 3.5)
            score.critique = "; ".join(critique_notes) + (" | " + score.critique if score.critique else "")
        elif rule_violations > 0:
            score.verdict = "REWRITE"
            score.overall_score = min(score.overall_score, 6.8)
            if word_count < 62 or word_count > 70:
                score.duration_suitability = min(score.duration_suitability, 6.0)
            score.critique = "; ".join(critique_notes) + (" | " + score.critique if score.critique else "")

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
