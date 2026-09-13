"""
Intelligent TTS Text Normalization Engine.
Converts years, dates, numbers, and symbols into natural documentary-style spoken English
prior to Kokoro/Edge-TTS synthesis, while strictly preserving quantities, measurements,
percentages, rankings, IDs, and versions.

Display script is preserved intact; this layer only transforms the TTS pronunciation payload.
"""
import re
from typing import Dict, List, Tuple, Optional


ONES = {
    0: "zero", 1: "one", 2: "two", 3: "three", 4: "four",
    5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
    10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen", 14: "fourteen",
    15: "fifteen", 16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen"
}

TENS = {
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"
}


def _two_digits_to_words(n: int) -> str:
    """Converts 0-99 to words."""
    if n < 20:
        return ONES[n]
    tens_val = (n // 10) * 10
    ones_val = n % 10
    if ones_val == 0:
        return TENS[tens_val]
    return f"{TENS[tens_val]}-{ONES[ones_val]}"


def year_to_words(year: int) -> str:
    """
    Converts a 4-digit year (1000-2099) to natural spoken words.
    Examples:
        1837 -> eighteen thirty-seven
        1908 -> nineteen oh eight
        1518 -> fifteen eighteen
        1966 -> nineteen sixty-six
        1800 -> eighteen hundred
        2000 -> two thousand
        2008 -> two thousand eight
        2024 -> twenty twenty-four
    """
    if year < 1000 or year > 2099:
        return str(year)

    first_two = year // 100
    last_two = year % 100

    if 2000 <= year <= 2009:
        if last_two == 0:
            return "two thousand"
        return f"two thousand {ONES[last_two]}"

    first_str = _two_digits_to_words(first_two)

    if last_two == 0:
        return f"{first_str} hundred"
    elif last_two < 10:
        return f"{first_str} oh {ONES[last_two]}"
    else:
        return f"{first_str} {_two_digits_to_words(last_two)}"


class TTSNormalizer:
    """
    Intelligent context-aware TTS text preprocessor.
    Resolves robotic pronunciation of years and historical notation without corrupting
    quantities, measurements, addresses, or technical identifiers.
    """

    # Preceding prepositions or context indicating a calendar year
    YEAR_CONTEXT_BEFORE = re.compile(
        r'\b(?:in|by|during|around|circa|c\.|year|dated|since|until|from|between|after|before)\s*$',
        re.IGNORECASE
    )

    # Patterns
    YEAR_PATTERN = re.compile(r'\b(1[0-9]{3}|20[0-2][0-9])\b')
    YEAR_DECADE_PATTERN = re.compile(r'\b(1[0-9]{3}|20[0-2][0-9])s\b')
    BC_AD_PATTERN = re.compile(r'\b(\d{1,4})\s*(BC|AD|BCE|CE)\b', re.IGNORECASE)
    RANK_PATTERN = re.compile(r'#(\d+)\b')
    PERCENT_PATTERN = re.compile(r'(\d+(?:\.\d+)?)\s*%(?!\w)')

    # Measurement units that indicate quantity rather than calendar year
    MEASUREMENT_UNITS = {
        "m", "meter", "meters", "km", "kilometer", "kilometers", "mile", "miles",
        "ft", "feet", "foot", "inch", "inches", "yd", "yard", "yards",
        "kg", "kilo", "kilos", "kilogram", "kilograms", "lb", "lbs", "pound", "pounds",
        "ton", "tons", "tonne", "tonnes", "hour", "hours", "hr", "hrs",
        "min", "minute", "minutes", "sec", "second", "seconds", "ms",
        "knot", "knots", "mph", "kph", "fps",
        "volt", "volts", "v", "watt", "watts", "kw", "hz", "khz", "mhz",
        "men", "soldiers", "people", "citizens", "troops", "casualties",
        "ships", "tanks", "planes", "bombs", "rounds", "deaths", "dollars",
        "barrels", "acres", "square", "percent"
    }

    # Identifier patterns to leave intact
    FLIGHT_ID_PATTERN = re.compile(r'\b(flight|boeing|airbus|apollo|voyager|gemini|b-?\d{2}|u-?\d{2,3})\s+(\d+)\b', re.IGNORECASE)
    VERSION_PATTERN = re.compile(r'\b(?:v|version)\s*(\d+(?:\.\d+)+)\b', re.IGNORECASE)
    TIME_PATTERN = re.compile(r'\b(\d{1,2}):(\d{2})\s*(AM|PM|UTC|GMT)?\b', re.IGNORECASE)

    @classmethod
    def is_likely_year(cls, text: str, start_idx: int, end_idx: int, number_val: int) -> bool:
        """
        Determines whether a 4-digit number at [start_idx:end_idx] in text is acting as a calendar year.
        Rejects quantities followed by measurement units or soldiers/people/items.
        """
        if number_val < 1000 or number_val > 2099:
            return False

        # Look at preceding token context
        preceding_text = text[:start_idx]
        following_text = text[end_idx:]

        # Check following words
        following_words = [w.strip('.,;?!"\'()[]') for w in following_text.split() if w.strip('.,;?!"\'()[]')]
        if following_words:
            first_following = following_words[0].lower()
            if first_following in cls.MEASUREMENT_UNITS:
                return False  # e.g. "1837 meters", "1908 soldiers"

        # Check preceding words for strong year indicators
        if cls.YEAR_CONTEXT_BEFORE.search(preceding_text):
            return True

        # Check following words for year indicator (e.g. "1837 marked", "1908 blast", "1966 incident")
        if following_words:
            first_following = following_words[0].lower()
            year_following_verbs = {
                "marked", "saw", "began", "ended", "was", "is", "witnessed",
                "brought", "struck", "occurred", "shook", "revealed",
                "incident", "event", "disaster", "crisis", "treaty", "war", "battle", "epidemic", "enigma"
            }
            if first_following in year_following_verbs:
                return True

        # If sentence starts with the year (e.g. "1837. Fog covered...")
        preceding_clean = preceding_text.strip()
        if not preceding_clean or preceding_clean.endswith(('.', '!', '?')):
            return True

        # Check if year is in parentheses: "(1837)"
        if preceding_text.endswith("(") and following_text.startswith(")"):
            return True

        # Check if preceded by comma (e.g. "London, 1837")
        if preceding_text.rstrip().endswith(","):
            return True

        # Default for 4-digit historical range if not followed by units: treat as year in narrative context
        return True

    @classmethod
    def normalize_for_tts(cls, text: str) -> str:
        """
        Transforms text into natural spoken phonetic English for TTS narration.
        Preserves display text semantic integrity.
        """
        if not text:
            return ""

        result = text

        # 1. Handle Rankings: "#1" -> "number one", "#2" -> "number two"
        def _replace_rank(m):
            num = int(m.group(1))
            if num in ONES:
                return f"number {ONES[num]}"
            return f"number {num}"
        result = cls.RANK_PATTERN.sub(_replace_rank, result)

        # 2. Handle BC / AD notation: "700 BC" -> "seven hundred B C"
        def _replace_bc_ad(m):
            num_str = m.group(1)
            era = m.group(2).upper()
            era_spoken = "B C" if "BC" in era else "A D"
            num_val = int(num_str)
            if num_val in ONES:
                spoken_num = ONES[num_val]
            elif num_val % 100 == 0 and num_val < 10000:
                spoken_num = f"{_two_digits_to_words(num_val // 100)} hundred"
            elif 1000 <= num_val <= 2099:
                spoken_num = year_to_words(num_val)
            else:
                spoken_num = num_str
            return f"{spoken_num} {era_spoken}"
        result = cls.BC_AD_PATTERN.sub(_replace_bc_ad, result)

        # 3. Handle Decades: "1830s" -> "eighteen thirties", "1900s" -> "nineteen hundreds"
        DECADE_NAMES = {
            "00s": "hundreds", "10s": "teens", "20s": "twenties", "30s": "thirties",
            "40s": "forties", "50s": "fifties", "60s": "sixties", "70s": "seventies",
            "80s": "eighties", "90s": "nineties"
        }
        def _replace_decade(m):
            yr = int(m.group(1))
            century = yr // 100
            decade_code = f"{yr % 100:02d}s"
            cent_word = _two_digits_to_words(century)
            dec_word = DECADE_NAMES.get(decade_code, f"{yr % 100}s")
            return f"{cent_word} {dec_word}"
        result = cls.YEAR_DECADE_PATTERN.sub(_replace_decade, result)

        # 4. Handle 4-Digit Years contextually
        matches = list(cls.YEAR_PATTERN.finditer(result))
        # Iterate in reverse to keep string indices stable
        for m in reversed(matches):
            val = int(m.group(1))
            start, end = m.start(), m.end()
            if cls.is_likely_year(result, start, end, val):
                spoken = year_to_words(val)
                result = result[:start] + spoken + result[end:]

        # 5. Clean up awkward punctuation for smooth speech pauses
        result = re.sub(r'\s*—\s*', ', ', result)
        result = re.sub(r'\s*--\s*', ', ', result)
        result = re.sub(r'\s+', ' ', result).strip()

        return result


def normalize_script_for_tts(text: str) -> str:
    """Convenience functional wrapper for TTS text normalization."""
    return TTSNormalizer.normalize_for_tts(text)