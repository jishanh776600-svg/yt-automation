"""
Niche-Agnostic Discovery Profile & Configuration Architecture.
Defines DiscoveryProfile dataclass encapsulating all domain-specific discovery parameters:
entity extraction, action stems, action domains, category mapping, relevance rules,
scoring weights, and deduplication policy.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Tuple, Optional, Any
from config.constants import CurrentAffairsCategory


class ProfileType(str, Enum):
    CURRENT_AFFAIRS = "CURRENT_AFFAIRS"
    HISTORICAL = "HISTORICAL"

# ==============================================================================
# GEOPOLITICAL DATA DEFINITIONS (Default Data for Current Affairs)
# ==============================================================================

DEFAULT_GEOPOLITICAL_ENTITIES = {
    # Countries & Regions
    "united states", "us", "usa", "america", "united kingdom", "uk", "britain", "russia",
    "china", "ukraine", "taiwan", "israel", "gaza", "palestine", "iran", "iraq",
    "germany", "france", "poland", "japan", "south korea", "north korea", "india",
    "pakistan", "saudi arabia", "turkey", "egypt", "syria", "yemen", "canada",
    "australia", "mexico", "brazil", "argentina", "south africa", "philippines",
    "european union", "eu", "middle east", "indo-pacific", "baltics", "arctic",
    # Cities / Capitals
    "washington", "moscow", "beijing", "kyiv", "london", "brussels", "tehran", "tel aviv",
    "jerusalem", "taipei", "tokyo", "seoul", "pyongyang", "berlin", "paris", "warsaw",
    "riyadh", "ankara", "cairo", "new delhi", "ottawa", "canberra",
    # Organizations / Alliances
    "nato", "united nations", "un", "g7", "g20", "brics", "opec", "iaea", "pentagon",
    "kremlin", "white house", "congress", "downing street", "bundestag", "elysee",
    "world bank", "imf", "central bank", "federal reserve",
    # Titles & Roles
    "president", "prime minister", "foreign minister", "defense minister", "chancellor",
    "secretary of state", "ambassador", "general", "admiral"
}

DEFAULT_ACTION_STEMS = {
    # Military / Conflict
    "military", "strike", "attack", "bombing", "missile", "drone", "invasion", "deploy",
    "deployment", "troops", "casualty", "ceasefire", "truce", "combat", "clash",
    "intercept", "airspace", "warfare", "offensive", "retaliation", "mobilize",
    # Diplomatic / Political
    "treaty", "summit", "envoy", "ambassador", "negotiation", "veto", "sanction",
    "election", "vote", "resign", "impeach", "cabinet", "parliament", "protest",
    "demonstration", "dissolve", "coup", "bilateral", "pact", "accord",
    # Economic / Trade
    "tariff", "trade", "embargo", "inflation", "debt", "interest rate", "currency",
    "export", "import", "supply chain", "energy", "pipeline", "oil", "gas", "sanctions",
    "deficit", "bailout", "stimulus",
    # Crisis / Security
    "hostage", "cyberattack", "espionage", "intelligence", "border", "refugee",
    "blockade", "evacuation", "emergency"
}

DEFAULT_ACTION_DOMAIN_MAP = {
    # Military / Armed Conflict
    "military": "DEFENSE_CONFLICT", "strike": "DEFENSE_CONFLICT", "attack": "DEFENSE_CONFLICT",
    "bombing": "DEFENSE_CONFLICT", "missile": "DEFENSE_CONFLICT", "drone": "DEFENSE_CONFLICT",
    "invasion": "DEFENSE_CONFLICT", "deploy": "DEFENSE_CONFLICT", "deployment": "DEFENSE_CONFLICT",
    "troops": "DEFENSE_CONFLICT", "ceasefire": "DEFENSE_CONFLICT", "combat": "DEFENSE_CONFLICT",
    "airspace": "DEFENSE_CONFLICT", "offensive": "DEFENSE_CONFLICT",
    # Economic / Trade
    "tariff": "TRADE_ECONOMY", "trade": "TRADE_ECONOMY", "embargo": "TRADE_ECONOMY",
    "inflation": "TRADE_ECONOMY", "debt": "TRADE_ECONOMY", "interest rate": "TRADE_ECONOMY",
    "currency": "TRADE_ECONOMY", "export": "TRADE_ECONOMY", "import": "TRADE_ECONOMY",
    "deficit": "TRADE_ECONOMY", "stimulus": "TRADE_ECONOMY",
    # Political / Elections / Domestic
    "election": "DOMESTIC_POLITICS", "vote": "DOMESTIC_POLITICS", "resign": "DOMESTIC_POLITICS",
    "impeach": "DOMESTIC_POLITICS", "cabinet": "DOMESTIC_POLITICS", "protest": "DOMESTIC_POLITICS",
    "parliament": "DOMESTIC_POLITICS", "dissolve": "DOMESTIC_POLITICS", "coup": "DOMESTIC_POLITICS",
    # Diplomatic / Treaties
    "summit": "DIPLOMACY", "treaty": "DIPLOMACY", "envoy": "DIPLOMACY", "bilateral": "DIPLOMACY",
    "pact": "DIPLOMACY", "accord": "DIPLOMACY", "ambassador": "DIPLOMACY"
}

DEFAULT_CATEGORY_THEME_RULES = [
    (
        CurrentAffairsCategory.GLOBAL_CONFLICT.value,
        {"strike", "attack", "bombing", "missile", "drone", "invasion", "troops", "casualty", "combat", "offensive", "warfare", "ceasefire", "airspace", "retaliation"}
    ),
    (
        CurrentAffairsCategory.DIPLOMACY.value,
        {"summit", "treaty", "envoy", "ambassador", "negotiation", "bilateral", "pact", "accord", "dialogue", "peace talks", "normalization"}
    ),
    (
        CurrentAffairsCategory.GLOBAL_ECONOMY.value,
        {"tariff", "trade", "embargo", "inflation", "debt", "interest rate", "currency", "export", "import", "supply chain", "energy", "pipeline", "oil", "gas", "sanctions", "deficit"}
    ),
    (
        CurrentAffairsCategory.SECURITY.value,
        {"hostage", "cyberattack", "espionage", "intelligence", "border", "refugee", "blockade", "evacuation", "emergency", "defense", "military"}
    ),
    (
        CurrentAffairsCategory.US_POLITICS.value,
        {"congress", "white house", "senate", "supreme court", "democrat", "republican", "biden", "trump", "pentagon", "state department"}
    ),
    (
        CurrentAffairsCategory.EUROPE_POLITICS.value,
        {"european union", "eu", "brussels", "bundestag", "downing street", "elysee", "parliament", "chancellor", "macron", "starmer", "scholz"}
    ),
    (
        CurrentAffairsCategory.WORLD_POLITICS.value,
        {"election", "vote", "resign", "impeach", "cabinet", "protest", "dissolve", "coup", "prime minister", "president"}
    )
]

DEFAULT_HIGH_IMPACT_ENTITIES = {
    "united states", "us", "usa", "america", "united kingdom", "uk", "britain",
    "nato", "european union", "eu", "russia", "china", "ukraine", "taiwan",
    "israel", "iran", "pentagon", "white house", "kremlin", "united nations",
    "g7", "brics", "opec", "federal reserve", "imf"
}

DEFAULT_LOW_RELEVANCE_NOISE = {
    "celebrity", "hollywood", "actor", "actress", "box office", "nfl", "nba",
    "premier league", "football", "soccer", "tennis", "recipe", "horoscope",
    "lottery", "weather forecast", "traffic jam", "zoo", "festival"
}

DEFAULT_TENSION_KEYWORDS = {
    "warns", "crisis", "threat", "escalates", "showdown", "ultimatum", "collapse",
    "deadlock", "emergency", "historic", "unprecedented", "retaliates", "clashes",
    "critical", "fallout", "standoff", "breaking point", "tensions rise"
}
DEFAULT_NARRATIVE_TENSION_KEYWORDS = DEFAULT_TENSION_KEYWORDS


# ==============================================================================
# DISCOVERY PROFILE DATACLASS
# ==============================================================================

@dataclass
class DiscoveryProfile:
    """
    Encapsulates all domain-specific knowledge, taxonomies, and rules
    used across the intelligence harvesting and ranking pipeline.
    """
    name: str = "Geopolitics & Current Affairs"
    profile_type: ProfileType = ProfileType.CURRENT_AFFAIRS
    allow_historical_seeds: bool = False
    allow_historical_trivia_fallback: bool = False
    require_live_news: bool = True
    max_freshness_tier: str = "TIER_2"
    min_source_confidence: float = 0.50
    default_categories: List[str] = field(default_factory=lambda: [
        "Geopolitics",
        "International Conflict",
        "Defense and Security",
        "Diplomacy and Treaties",
        "Global Strategy"
    ])

    description: str = ""
    target_niche: Optional[str] = None
    recognized_entities: Set[str] = field(default_factory=set)
    action_stems: Set[str] = field(default_factory=set)
    action_domain_map: Dict[str, str] = field(default_factory=dict)
    category_theme_rules: List[Tuple[str, Set[str]]] = field(default_factory=list)
    high_impact_entities: Set[str] = field(default_factory=set)
    low_relevance_noise: Set[str] = field(default_factory=set)
    tension_keywords: Set[str] = field(default_factory=set)

    default_category: str = "General"
    fallback_category: str = "General"
    deduplication_policy: str = "event_action_domain"  # "event_action_domain" | "historical_year_location"

    # Source strategy configuration
    rss_feeds: Optional[List[Dict[str, Any]]] = None
    enable_gdelt: bool = False

    def __post_init__(self):
        if self.profile_type == ProfileType.CURRENT_AFFAIRS:
            self.allow_historical_seeds = False
            self.allow_historical_trivia_fallback = False
            self.require_live_news = True

    # Freshness thresholds (in hours)
    breaking_hours: float = 3.0
    developing_hours: float = 12.0
    fresh_hours: float = 24.0
    recent_hours: float = 48.0
    maturing_hours: float = 72.0

    # Opportunity scoring weights (summing to 1.0)
    weight_freshness: float = 0.30
    weight_relevance: float = 0.25
    weight_breadth: float = 0.20
    weight_tension: float = 0.15
    weight_velocity: float = 0.10


# Built-in Current Affairs Discovery Profile
CURRENT_AFFAIRS_DISCOVERY_PROFILE = DiscoveryProfile(
    name="CURRENT_AFFAIRS",
    description="Geopolitics, world affairs, international diplomacy, defense, and global economic developments.",
    recognized_entities=DEFAULT_GEOPOLITICAL_ENTITIES,
    action_stems=DEFAULT_ACTION_STEMS,
    action_domain_map=DEFAULT_ACTION_DOMAIN_MAP,
    category_theme_rules=DEFAULT_CATEGORY_THEME_RULES,
    high_impact_entities=DEFAULT_HIGH_IMPACT_ENTITIES,
    low_relevance_noise=DEFAULT_LOW_RELEVANCE_NOISE,
    tension_keywords=DEFAULT_TENSION_KEYWORDS,
    default_category=CurrentAffairsCategory.GEOPOLITICS.value,
    fallback_category=CurrentAffairsCategory.MAJOR_WORLD_EVENT.value,
    deduplication_policy="event_action_domain",
    enable_gdelt=False,
    rss_feeds=[
        {"name": "BBC World News", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "domain": "bbc.co.uk", "weight": 1.0},
        {"name": "Al Jazeera English", "url": "https://www.aljazeera.com/xml/rss/all.xml", "domain": "aljazeera.com", "weight": 1.0},
        {"name": "Deutsche Welle World", "url": "https://rss.dw.com/xml/rss-en-world", "domain": "dw.com", "weight": 1.0},
        {"name": "France 24 World", "url": "https://www.france24.com/en/rss", "domain": "france24.com", "weight": 1.0},
        {"name": "NPR World", "url": "https://feeds.npr.org/1004/rss.xml", "domain": "npr.org", "weight": 1.0},
        {"name": "Reuters World (Legacy)", "url": "https://www.reutersagency.com/feed/?best-topics=world&post_type=best", "domain": "reuters.com", "weight": 1.0},
        {"name": "Associated Press (Legacy)", "url": "https://apnews.com/rss", "domain": "apnews.com", "weight": 1.0},
    ]
)

# Built-in Historical Discovery Profile
HISTORICAL_DISCOVERY_PROFILE = DiscoveryProfile(
    name="HISTORICAL",
    profile_type=ProfileType.HISTORICAL,
    allow_historical_seeds=True,
    allow_historical_trivia_fallback=True,
    require_live_news=False,
    description="Historical curiosities, bizarre events, documented disasters, and unusual wars.",
    recognized_entities=set(),
    action_stems=set(),
    action_domain_map={},
    category_theme_rules=[],
    high_impact_entities=set(),
    low_relevance_noise=set(),
    tension_keywords=set(),
    default_category="Historical Documentaries",
    fallback_category="Historical Documentaries",
    deduplication_policy="historical_year_location",
    enable_gdelt=False
)

SPACE_TECHNOLOGY_DISCOVERY_PROFILE = DiscoveryProfile(
    name="SPACE_TECHNOLOGY",
    description="Orbital missions, aerospace propulsion, planetary science, and satellite launches.",
    target_niche="SPACE_TECHNOLOGY",
    recognized_entities={"nasa", "spacex", "artemis", "starship", "iss", "esa", "isro", "mars", "moon", "orbit"},
    action_stems={"launch", "docking", "propulsion", "telemetry", "insertion", "abort", "landing", "booster"},
    action_domain_map={
        "launch": "ORBITAL_PROPULSION",
        "docking": "ORBITAL_PROPULSION",
        "propulsion": "ORBITAL_PROPULSION",
        "telemetry": "MISSION_OPERATIONS"
    },
    category_theme_rules=[
        ("Space Exploration", {"launch", "spacex", "nasa", "artemis", "orbit"}),
        ("Aerospace Technology", {"propulsion", "booster", "telemetry"})
    ],
    high_impact_entities={"artemis", "starship", "nasa", "spacex"},
    low_relevance_noise={"astrology", "horoscope", "sci-fi"},
    tension_keywords={"anomaly", "abort", "critical", "countdown", "failure", "success"},
    default_category="Space Exploration",
    fallback_category="Aerospace Technology",
    deduplication_policy="event_action_domain",
    enable_gdelt=False
)

FINANCIAL_MARKETS_DISCOVERY_PROFILE = DiscoveryProfile(
    name="FINANCIAL_MARKETS",
    description="Macroeconomics, interest rate decisions, currency shifts, commodities, and banking.",
    target_niche="FINANCIAL_MARKETS",
    recognized_entities={"federal reserve", "ecb", "treasury", "sec", "wall street", "nasdaq", "dow", "s&p 500"},
    action_stems={"rate hike", "rate cut", "liquidity", "inflation", "yield", "bond", "default", "rally", "selloff"},
    action_domain_map={
        "rate hike": "MONETARY_POLICY",
        "rate cut": "MONETARY_POLICY",
        "liquidity": "MACRO_FINANCE",
        "inflation": "MACRO_FINANCE"
    },
    category_theme_rules=[
        ("Monetary Policy", {"rate hike", "rate cut", "federal reserve", "ecb"}),
        ("Market Volatility", {"selloff", "rally", "liquidity", "yield"})
    ],
    high_impact_entities={"federal reserve", "ecb", "treasury"},
    low_relevance_noise={"crypto meme", "penny stock", "lottery"},
    tension_keywords={"plunge", "surge", "crisis", "default", "hike", "collapse", "tightening"},
    default_category="Monetary Policy",
    fallback_category="Market Volatility",
    deduplication_policy="event_action_domain",
    enable_gdelt=False
)

# Global Registry
_DISCOVERY_REGISTRY: Dict[str, DiscoveryProfile] = {
    "CURRENT_AFFAIRS": CURRENT_AFFAIRS_DISCOVERY_PROFILE,
    "HISTORICAL": HISTORICAL_DISCOVERY_PROFILE,
    "SPACE_TECHNOLOGY": SPACE_TECHNOLOGY_DISCOVERY_PROFILE,
    "FINANCIAL_MARKETS": FINANCIAL_MARKETS_DISCOVERY_PROFILE
}

# Current active discovery profile: None by default, resolved dynamically
_ACTIVE_DISCOVERY_PROFILE: Optional[DiscoveryProfile] = None


def list_registered_discovery_profiles() -> List[Dict[str, Any]]:
    """Returns a summary list of all registered DiscoveryProfiles."""
    return [
        {
            "name": name,
            "description": prof.description,
            "default_category": prof.default_category,
            "deduplication_policy": prof.deduplication_policy,
            "enable_gdelt": prof.enable_gdelt
        }
        for name, prof in _DISCOVERY_REGISTRY.items()
    ]


def get_active_discovery_profile() -> DiscoveryProfile:
    """
    Returns the globally active DiscoveryProfile.
    Resolves from:
      1. Explicit override via set_active_discovery_profile()
      2. Active ContentProfile's attached discovery_profile
      3. Environment variable DISCOVERY_PROFILE or CONTENT_PROFILE
      4. Default CURRENT_AFFAIRS_DISCOVERY_PROFILE
    """
    global _ACTIVE_DISCOVERY_PROFILE
    if _ACTIVE_DISCOVERY_PROFILE is not None:
        return _ACTIVE_DISCOVERY_PROFILE

    try:
        from core.content_profile import get_active_profile
        cp = get_active_profile()
        if cp and cp.discovery_profile:
            return cp.discovery_profile
    except Exception:
        pass

    import os
    env_disc = os.environ.get("DISCOVERY_PROFILE") or os.environ.get("CONTENT_PROFILE") or os.environ.get("ACTIVE_NICHE")
    if env_disc:
        dp = get_discovery_profile_by_name(env_disc)
        if dp:
            return dp

    return CURRENT_AFFAIRS_DISCOVERY_PROFILE


def set_active_discovery_profile(profile: Optional[DiscoveryProfile]) -> None:
    """Sets the globally active DiscoveryProfile."""
    global _ACTIVE_DISCOVERY_PROFILE
    _ACTIVE_DISCOVERY_PROFILE = profile


def register_discovery_profile(profile: DiscoveryProfile) -> None:
    """Registers a DiscoveryProfile in the global registry."""
    _DISCOVERY_REGISTRY[profile.name.upper()] = profile


def get_discovery_profile_by_name(name: str) -> Optional[DiscoveryProfile]:
    """Retrieves a DiscoveryProfile by name."""
    return _DISCOVERY_REGISTRY.get(name.upper())


def resolve_policy_for_category(category: Optional[str]) -> Optional[str]:
    """
    Inspects all registered DiscoveryProfiles to find which profile owns
    the specified category, returning that profile's deduplication_policy.
    Enables 100% niche-agnostic policy resolution without hardcoded category names.
    """
    if not category:
        return None
    cat_clean = category.strip().lower()

    for prof in _DISCOVERY_REGISTRY.values():
        if prof.default_category and prof.default_category.lower() == cat_clean:
            return prof.deduplication_policy
        if prof.fallback_category and prof.fallback_category.lower() == cat_clean:
            return prof.deduplication_policy
        for rule_cat, _ in prof.category_theme_rules:
            if rule_cat.lower() == cat_clean or rule_cat.lower().replace("_", " ") == cat_clean:
                return prof.deduplication_policy

    return None
