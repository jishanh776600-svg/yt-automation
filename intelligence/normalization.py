"""
Article Normalization & Entity/Token Extraction.
Performs fast, deterministic text cleaning, boilerplate stripping,
URL canonicalization, and geopolitical entity/action extraction without LLM overhead.
"""
import re
import html
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from typing import Set, Tuple, List
from intelligence.models import RawArticle

# Publisher boilerplate prefixes and suffixes
PUBLISHER_SUFFIX_PATTERNS = [
    r"\s*[-|–—]\s*(?:BBC(?:\s+News)?|Reuters|AP(?:\s+News)?|The Guardian|CNN|Fox News|Al Jazeera|Bloomberg|Politico|Financial Times|NPR|DW|France 24|Sky News|CNBC|The New York Times|The Washington Post).*$",
    r"\s*\|\s*World\s+News.*$",
    r"\s*\|\s*Reuters Agency.*$",
]

PREFIX_BOILERPLATE_PATTERNS = [
    r"^(?:BREAKING|ALERT|WATCH|EXCLUSIVE|LIVE|UPDATE|ANALYSIS|REPORT|FACTBOX)\s*[-:–—|]\s*",
    r"^(?:LIVE UPDATES|DEVELOPING STORY)\s*[-:–—|]\s*",
]

# Standard English stopwords
STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "because", "as", "what", "which",
    "this", "that", "these", "those", "then", "just", "so", "than", "such", "both",
    "about", "into", "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "in", "out", "on", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "each", "few", "more", "most", "other", "some", "no", "nor", "not", "only",
    "own", "same", "too", "very", "can", "will", "don", "should", "now", "says",
    "said", "told", "according", "reported", "amid", "following", "could", "would",
    "may", "might", "must", "also", "new", "first", "one", "two", "three", "first"
}

# Major geopolitical entities, countries, capitals, institutions, and leaders
RECOGNIZED_GEOPOLITICAL_ENTITIES = {
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

# Distinct action and event stems for differentiating events occurring in the same location
ACTION_STEMS = {
    # Military / Conflict
    "military", "strike", "attack", "bombing", "missile", "drone", "invasion", "deploy",
    "deployment", "troops", "casualty", "ceasefire", "truce", "combat", "clash",
    "intercept", "airspace", "warfare", "offensive", "retaliation", "mobilize",
    # Diplomatic / Political
    "treaty", "summit", "envoy", "ambassador", "negotiation", "veto", "sanction",
    "election", "vote", "resign", "impeach", "cabinet", "parliament", "protest",
    "demonstration", "dissolve", "coup", "bilateral", "pact", "accord", "treaty",
    # Economic / Trade
    "tariff", "trade", "embargo", "inflation", "debt", "interest rate", "currency",
    "export", "import", "supply chain", "energy", "pipeline", "oil", "gas", "sanctions",
    "deficit", "bailout", "stimulus",
    # Crisis / Security
    "hostage", "cyberattack", "espionage", "intelligence", "border", "refugee",
    "blockade", "evacuation", "emergency", "treaty"
}


def normalize_url(raw_url: str) -> str:
    """
    Strips tracking query parameters (utm_*, fbclid, ref, etc.)
    and fragments from a URL to ensure canonical identity.
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        query_params = parse_qsl(parsed.query)
        # Drop marketing / tracking params
        filtered_params = [
            (k, v) for k, v in query_params
            if not k.startswith("utm_") and k not in {"fbclid", "gclid", "ref", "source", "ncid"}
        ]
        new_query = urlencode(filtered_params)
        canonical = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower().replace("www.", ""),
            parsed.path.rstrip("/"),
            "",
            new_query,
            ""
        ))
        return canonical
    except Exception:
        return raw_url.strip()


def strip_html(text: str) -> str:
    """Strips HTML markup and unescapes HTML entities."""
    if not text:
        return ""
    unescaped = html.unescape(text)
    clean = re.sub(r"<[^>]+>", " ", unescaped)
    return re.sub(r"\s+", " ", clean).strip()


def strip_publisher_boilerplate(title: str) -> str:
    """Removes trailing publisher names and leading BREAKING prefixes."""
    if not title:
        return ""
    t = title.strip()
    for prefix in PREFIX_BOILERPLATE_PATTERNS:
        t = re.sub(prefix, "", t, flags=re.IGNORECASE)
    for suffix in PUBLISHER_SUFFIX_PATTERNS:
        t = re.sub(suffix, "", t, flags=re.IGNORECASE)
    return t.strip()


def clean_text_for_tokens(text: str) -> str:
    """Normalizes whitespace and removes punctuation except hyphens inside words."""
    if not text:
        return ""
    clean = re.sub(r"[^\w\s-]", " ", text.lower())
    return re.sub(r"\s+", " ", clean).strip()


def extract_entities_and_tokens(text: str) -> Tuple[Set[str], Set[str], Set[str], Set[str]]:
    """
    Deterministically extracts:
      - entities: Recognized geopolitical entities & capitalized names
      - countries: Matched nation/region names
      - action_tokens: Matched action stems
      - keywords: Content words excluding stopwords
    """
    if not text:
        return set(), set(), set(), set()

    clean_lower = clean_text_for_tokens(text)
    words = clean_lower.split()
    keywords = {w for w in words if len(w) > 2 and w not in STOPWORDS and not w.isdigit()}

    entities: Set[str] = set()
    countries: Set[str] = set()
    action_tokens: Set[str] = set()

    # Match multi-word or single-word recognized entities
    for ent in RECOGNIZED_GEOPOLITICAL_ENTITIES:
        pattern = r"\b" + re.escape(ent) + r"\b"
        if re.search(pattern, clean_lower):
            entities.add(ent)
            if ent in {
                "united states", "us", "usa", "america", "united kingdom", "uk", "britain",
                "russia", "china", "ukraine", "taiwan", "israel", "gaza", "palestine", "iran",
                "iraq", "germany", "france", "poland", "japan", "south korea", "north korea",
                "india", "pakistan", "saudi arabia", "turkey", "egypt", "syria", "yemen",
                "canada", "australia", "mexico", "brazil", "argentina", "south africa", "philippines"
            }:
                countries.add(ent)

    # Match action tokens
    for act in ACTION_STEMS:
        pattern = r"\b" + re.escape(act) + r"\b"
        if re.search(pattern, clean_lower):
            action_tokens.add(act)

    # Capitalized proper-noun regex from raw text (2+ words capitalized)
    capitalized_matches = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", text)
    for cap in capitalized_matches:
        cap_clean = cap.strip()
        if cap_clean.lower() not in STOPWORDS and len(cap_clean) > 3:
            entities.add(cap_clean.lower())

    return entities, countries, action_tokens, keywords


def normalize_article(article: RawArticle) -> RawArticle:
    """
    Populates normalized text, cleaned URL, entities, countries, action tokens,
    and keywords on a RawArticle instance.
    """
    # 1. Canonicalize URL
    article.url = normalize_url(article.url)

    # 2. Strip HTML and boilerplate
    clean_title = strip_publisher_boilerplate(strip_html(article.title))
    clean_summary = strip_html(article.summary)

    article.normalized_title = clean_title
    article.normalized_summary = clean_summary

    # 3. Extract tokens and entities across title and summary
    combined_text = f"{clean_title}. {clean_summary}"
    entities, countries, action_tokens, keywords = extract_entities_and_tokens(combined_text)

    article.entities = entities
    article.countries = countries
    article.action_tokens = action_tokens
    article.keywords = keywords

    return article
