"""
Niche-Agnostic Content Strategy & Profile Layer.
Defines the ContentProfile abstraction that decouples ScriptEngine and content evaluation
from any hardcoded niche (Current Affairs, Geopolitics, History, Science, etc.).
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from core.discovery_profile import (
    DiscoveryProfile,
    CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    HISTORICAL_DISCOVERY_PROFILE,
    SPACE_TECHNOLOGY_DISCOVERY_PROFILE,
    FINANCIAL_MARKETS_DISCOVERY_PROFILE
)


@dataclass
class ContentProfile:
    """
    Generic content strategy and editorial specification consumed by ScriptEngine.
    Enables zero-code niche transitions by encapsulating all domain-specific guidance,
    tone, narrative objectives, beat descriptions, and forbidden patterns.
    """
    name: str
    description: str
    target_audience: str
    tone: str
    script_objective: str
    system_role_instruction: str

    # 5-Stage narrative beat guidance
    beat_descriptions: Dict[str, str] = field(default_factory=lambda: {
        "hook": "Immediate curiosity/tension gap (6-14 words). Pattern interrupt without generic filler.",
        "context": "Rapid setting and background grounding with strong forward momentum.",
        "escalation": "Rising stakes, conflict, or complication. Grounded strictly in supplied research.",
        "reveal": "The definitive turning point, key development, or climactic payoff.",
        "loop_twist": "Memorable final resolution and seamless loop-compatible conclusion."
    })

    factual_policy: str = (
        "Use ONLY facts explicitly supported by the supplied research. "
        "NEVER invent dates, names, numbers, quotations, or unverified claims."
    )

    forbidden_cliches: List[str] = field(default_factory=lambda: [
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
    ])

    hook_markers: List[str] = field(default_factory=lambda: [
        r"\b(1\d{3}|20\d{2}|thousands|hundreds|minutes|miles|tons|first|only|deadliest|disaster|war|crisis|billion|million|percent)\b"
    ])

    preferred_cadence: str = (
        "Natural spoken American English. Short, punchy sentences (6-12 words/sentence). "
        "High information density. Zero filler."
    )

    min_words: int = 45
    max_words: int = 68
    target_words: str = "50-55 words"
    additional_instructions: str = ""
    discovery_profile: Optional[DiscoveryProfile] = None
    deduplication_policy: str = "auto"  # "event_action_domain" | "historical_year_location" | "auto"
    research_strategy: str = "wikipedia"  # "wikipedia" | "pre_attached_first"
    default_archive_name: str = "Verified Public Record"
    default_archive_url: str = "https://en.wikipedia.org/wiki/Reference_work"


# ----------------------------------------------------------------------
# BUILT-IN PRODUCTION PROFILES
# ----------------------------------------------------------------------

# Current Production Niche: Current Affairs & Geopolitics
CURRENT_AFFAIRS_PROFILE = ContentProfile(
    name="CURRENT_AFFAIRS",
    description="Geopolitics, world affairs, international diplomacy, defense, and global economic developments.",
    target_audience="Western English-speaking audience interested in global affairs, geopolitics, and international events.",
    tone="Analytical, authoritative, urgent, balanced, sober, non-sensational.",
    script_objective="Transform fresh, multi-source global developments into engaging 50-60 second analytical breakdowns.",
    system_role_instruction=(
        "You are an expert geopolitical intelligence analyst and scriptwriter for AL-AMR, "
        "a premier YouTube Shorts channel covering major world affairs, diplomacy, defense, "
        "global economics, and international conflicts for English-speaking audiences."
    ),
    beat_descriptions={
        "hook": "Immediate high-stakes geopolitical tension or development (6-14 words). No generic filler.",
        "context": "Rapid geographic and geopolitical grounding with essential background actors.",
        "escalation": "Rising conflict, strategic reaction, economic fallout, or diplomatic response.",
        "reveal": "The core consequence, turning point, or strategic impact for global stability.",
        "loop_twist": "Forward-looking strategic implication and seamless loop-compatible conclusion."
    },
    factual_policy=(
        "Use ONLY verified facts from the supplied intelligence research. "
        "Strictly attribute claims to official statements, diplomatic communiques, or confirmed reports. "
        "Zero speculation, zero hyperbole."
    ),
    forbidden_cliches=[
        "will shock you",
        "unbelievable true story",
        "events spiraled",
        "events rapidly spiraled",
        "changed the world forever",
        "you won't believe",
        "believe it or not",
        "did you know",
        "what happened next",
        "things took a turn",
        "mind-blowing",
        "history changed forever",
        "the world was stunned",
        "breaking news"
    ],
    hook_markers=[
        r"\b(20\d{2}|strike|attack|tariff|summit|treaty|sanctions|border|troops|crisis|billions?|millions?|percent|nato|un|eu|us|china|russia)\b"
    ],
    preferred_cadence="Crisp, authoritative broadcast cadence. Active voice. Short clauses. High information density.",
    min_words=48,
    max_words=68,
    target_words="52-58 words",
    discovery_profile=CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    deduplication_policy="event_action_domain",
    research_strategy="pre_attached_first",
    default_archive_name="Wire Service Archive",
    default_archive_url="https://en.wikipedia.org/wiki/News_agency"
)

# Historical / Legacy Niche
HISTORICAL_PROFILE = ContentProfile(
    name="HISTORICAL",
    description="Little-known, bizarre, or shocking documented true historical events.",
    target_audience="General history enthusiasts, curious learners, short-form video audience.",
    tone="Curious, dramatic, factual, paced, immersive.",
    script_objective="Hook the viewer with a bizarre historical premise and resolve it factually in under 60 seconds.",
    system_role_instruction=(
        "You are an elite short-form video scriptwriter specializing in unbelievable true historical events. "
        "Craft punchy, voiceover-optimized scripts that hook viewers instantly and loop seamlessly."
    ),
    beat_descriptions={
        "hook": "Immediate curiosity gap (6-14 words). Mention the year, number, or absurd premise. No filler.",
        "context": "Rapid setting and character introduction with forward momentum.",
        "escalation": "The bizarre turn of events that made the situation worse or stranger.",
        "reveal": "The peak of the absurdity or the surprising climax.",
        "loop_twist": "A clever punchline that wraps the story and seamlessly loops back to the hook."
    },
    factual_policy=(
        "Use ONLY documented historical facts supported by primary/encyclopedic research. "
        "Never invent details, dates, or numbers."
    ),
    forbidden_cliches=[
        "will shock you",
        "unbelievable true story",
        "events spiraled",
        "events rapidly spiraled",
        "shocked historians",
        "changed history forever",
        "you won't believe",
        "believe it or not",
        "did you know",
        "what happened next",
        "things got worse",
        "mind-blowing"
    ],
    hook_markers=[
        r"\b(1\d{3}|20\d{2}|thousands|hundreds|minutes|miles|tons|first|only|deadliest|disaster|war|king|crisis)\b"
    ],
    preferred_cadence="Natural spoken American English. Short, punchy sentences (6-12 words/sentence). Zero filler.",
    min_words=45,
    max_words=68,
    target_words="50-55 words",
    discovery_profile=HISTORICAL_DISCOVERY_PROFILE,
    deduplication_policy="historical_year_location",
    research_strategy="wikipedia",
    default_archive_name="Documented Historical Record",
    default_archive_url="https://en.wikipedia.org/wiki/History"
)

SPACE_TECHNOLOGY_PROFILE = ContentProfile(
    name="SPACE_TECHNOLOGY",
    description="Orbital mechanics, deep-space probes, rocket engineering, and astronomical breakthroughs.",
    target_audience="Aerospace engineers, science enthusiasts, and future technology observers.",
    tone="Technically precise, awe-inspiring, forward-looking, and rigorous.",
    script_objective="Explain intricate rocket science, mission parameters, and orbital mechanics with high velocity clarity.",
    system_role_instruction="You are an aerospace mission analyst communicating high-stakes orbital missions and engineering feats.",
    forbidden_cliches=[
        "out of this world",
        "to infinity and beyond",
        "rocket science is hard",
        "aliens confirmed",
        "mind-blowing space fact"
    ],
    hook_markers=[
        r"\b(orbit|thrust|payload|velocity|booster|telemetry|docking|trajectory|mach|stages|burn)\b"
    ],
    preferred_cadence="Crisp, authoritative, technical cadence. 6-12 words per sentence.",
    min_words=45,
    max_words=68,
    target_words="50-55 words",
    discovery_profile=SPACE_TECHNOLOGY_DISCOVERY_PROFILE,
    deduplication_policy="event_action_domain",
    research_strategy="pre_attached_or_archive",
    default_archive_name="NASA Technical Reports & Flight Data",
    default_archive_url="https://ntrs.nasa.gov/"
)

FINANCIAL_MARKETS_PROFILE = ContentProfile(
    name="FINANCIAL_MARKETS",
    description="Central banking, interest rates, currency volatility, sovereign debt, and market liquidity.",
    target_audience="Macro analysts, institutional traders, economists, and market participants.",
    tone="Analytical, clinical, disciplined, and focused on capital flows.",
    script_objective="Deconstruct complex macroeconomic shifts and monetary decisions into sharp actionable insights.",
    system_role_instruction="You are an institutional macro strategist breaking down market liquidity and monetary policy.",
    forbidden_cliches=[
        "to the moon",
        "get rich quick",
        "secret trick",
        "guaranteed returns",
        "financial freedom"
    ],
    hook_markers=[
        r"\b(basis points|liquidity|yield curve|treasury|inflation|fed|spread|default|bonds)\b"
    ],
    preferred_cadence="Clinical institutional cadence. Dense, information-rich, zero fluff.",
    min_words=45,
    max_words=68,
    target_words="50-55 words",
    discovery_profile=FINANCIAL_MARKETS_DISCOVERY_PROFILE,
    deduplication_policy="event_action_domain",
    research_strategy="pre_attached_or_archive",
    default_archive_name="Federal Reserve Economic Data (FRED)",
    default_archive_url="https://fred.stlouisfed.org/"
)


# Global profile registry
_PROFILE_REGISTRY: Dict[str, ContentProfile] = {
    "CURRENT_AFFAIRS": CURRENT_AFFAIRS_PROFILE,
    "HISTORICAL": HISTORICAL_PROFILE,
    "SPACE_TECHNOLOGY": SPACE_TECHNOLOGY_PROFILE,
    "FINANCIAL_MARKETS": FINANCIAL_MARKETS_PROFILE
}

# Current active profile: None by default, resolved dynamically
_ACTIVE_PROFILE: Optional[ContentProfile] = None


def list_registered_profiles() -> List[Dict[str, Any]]:
    """Returns a summary list of all registered ContentProfiles."""
    return [
        {
            "name": name,
            "description": prof.description,
            "target_audience": prof.target_audience,
            "tone": prof.tone,
            "script_objective": prof.script_objective,
            "deduplication_policy": prof.deduplication_policy,
            "research_strategy": prof.research_strategy,
            "discovery_profile_name": prof.discovery_profile.name if prof.discovery_profile else None
        }
        for name, prof in _PROFILE_REGISTRY.items()
    ]


def get_active_profile() -> ContentProfile:
    """
    Returns the currently active ContentProfile.
    Priority:
      1. Explicit runtime override via set_active_profile()
      2. Environment variable CONTENT_PROFILE or ACTIVE_NICHE
      3. Default profile (CURRENT_AFFAIRS_PROFILE)
    """
    global _ACTIVE_PROFILE
    if _ACTIVE_PROFILE is not None:
        return _ACTIVE_PROFILE

    import os
    env_niche = os.environ.get("CONTENT_PROFILE") or os.environ.get("ACTIVE_NICHE")
    if env_niche:
        prof = get_profile_by_name(env_niche)
        if prof:
            return prof

    return CURRENT_AFFAIRS_PROFILE


def set_active_profile(profile: Optional[ContentProfile]) -> None:
    """Sets the globally active ContentProfile and synchronizes DiscoveryProfile."""
    global _ACTIVE_PROFILE
    _ACTIVE_PROFILE = profile
    if profile and profile.discovery_profile:
        from core.discovery_profile import set_active_discovery_profile
        set_active_discovery_profile(profile.discovery_profile)
    elif profile is None:
        from core.discovery_profile import set_active_discovery_profile
        set_active_discovery_profile(None)


def register_profile(profile: ContentProfile) -> None:
    """Registers a new ContentProfile in the registry."""
    _PROFILE_REGISTRY[profile.name.upper()] = profile
    if profile.discovery_profile:
        from core.discovery_profile import register_discovery_profile
        register_discovery_profile(profile.discovery_profile)


def get_profile_by_name(name: str) -> Optional[ContentProfile]:
    """Retrieves a ContentProfile by name from the registry."""
    return _PROFILE_REGISTRY.get(name.upper())
