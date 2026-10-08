"""
High-Impact Movie Recap SEO Engine.
====================================
Transforms plain movie recap titles and descriptions into viral, click-optimized,
search-dominant metadata for YouTube Shorts:
  - High-CTR curiosity-gap titles with scene hooks & hashtags.
  - Multi-paragraph narrative synopsis with movie details & clear CTA.
  - 20 high-volume search tags for maximum YouTube algorithm discovery.
"""

import re
from typing import Dict, Any, List, Optional
from core.movie_catalog import THRILLER_MOVIE_CATALOG, MovieEntry

# Curated high-CTR titles and episode synopses for top catalog movies
CURATED_EPISODE_SEO = {
    "wrong turn": {
        1: {
            "hook": "Couple Attacked While Rock Climbing In The Woods!",
            "synopsis": "A college couple embarks on a peaceful rock-climbing trip deep in the Appalachian mountains, but an unseen predator cuts their safety ropes and stalks them through the dense wilderness.",
        },
        2: {
            "hook": "Stranded In Deep Mountain Woods By A Barbed Wire Trap!",
            "synopsis": "Medical student Chris takes an abandoned dirt shortcut through West Virginia, only to smash into a stranded group whose tires were slashed by a hidden barbed wire spike trap.",
        },
        3: {
            "hook": "They Sneaked Inside A Mountain Cabin Full Of Human Bones!",
            "synopsis": "Searching for a telephone, the stranded survivors stumble upon an isolated log cabin, discovering jars of human organs, car keys from dozens of missing victims, and piles of barbed wire.",
        },
        4: {
            "hook": "Hiding Under The Bed As Monsters Drag A Dead Body Inside!",
            "synopsis": "The mutated mountain cannibals unexpectedly return to the cabin. Trapped with nowhere to run, the survivors crawl under rotting bed frames, watching in frozen terror as a fresh kill is hacked apart inches away.",
        },
        5: {
            "hook": "Quietly Escaping Through The Window While Monsters Sleep!",
            "synopsis": "With the cannibal brothers asleep by the fireplace, the group must quietly unlatch the back window without making a sound and sprint into the moonlit forest before the killers wake.",
        },
        6: {
            "hook": "Hunted High In The Tree Canopies By Savage Cannibals!",
            "synopsis": "Cornered at a dead-end cliff, the survivors climb forty feet up into the dense pine tree branches, desperately leaping between canopies while cannibals hunt them from above with hunting bows.",
        },
        7: {
            "hook": "Cornered Inside An Old Watchtower As Monsters Surround It!",
            "synopsis": "Reaching an abandoned forestry watchtower at sunset, the survivors locate a broken radio, but Three-Finger and his brothers surround the base of the tower and set the wooden staircase ablaze.",
        },
        8: {
            "hook": "Torching The Watchtower To Escape The Bloodthirsty Killers!",
            "synopsis": "With the watchtower engulfed in flames, the final survivors make a suicidal leap into the pine trees below, culminating in a high-octane truck ambush to destroy the cannibal clan once and for all.",
        },
    },
    "the hills have eyes": {
        1: {
            "hook": "Stranded In The Irradiated Desert By A Sabotaged Road!",
            "synopsis": "A family road trip through the New Mexico desert goes horrifically wrong after their trailer tires are destroyed by a hidden road trap, stranding them in an irradiated nuclear testing zone.",
        },
        2: {
            "hook": "Savage Nighttime Siege On The Stranded Desert RV!",
            "synopsis": "As pitch-black night falls over the desert, deformed subterranean mutants launch a coordinated assault on the immobilized RV, unleashing unspeakable chaos on the isolated family.",
        },
        3: {
            "hook": "Mutants Kidnap The Baby Into The Barren Radioactive Hills!",
            "synopsis": "Following the brutal night raid, mutant leader Pluto abducts the infant child into the rocky canyon caves, leaving the surviving father with no choice but to venture into the mutant stronghold alone.",
        },
        4: {
            "hook": "Entering The Creepy Mannequin Village Alone With A Shotgun!",
            "synopsis": "Armed with a shotgun and accompanied by an enraged German Shepherd, Doug infiltrates the eerie full-scale nuclear test town, where mutated cannibals live among frozen 1950s mannequins.",
        },
        5: {
            "hook": "Brutal Hand-To-Hand Duel Inside A Mutated Family Home!",
            "synopsis": "Inside a derelict mannequin home, Doug confronts the savage mutant enforcers in an all-out, tooth-and-nail battle for survival to rescue his infant daughter.",
        },
        6: {
            "hook": "Reclaiming The Baby And Fighting Out Of The Irradiated Mines!",
            "synopsis": "With his child recovered, Doug and his loyal dog fight through the remaining mutant cannibals in an explosive desert showdown, leaving the nuclear graveyard behind in ashes.",
        },
    },
    "texas chainsaw": {
        1: {
            "hook": "She Inherited A Victorian Mansion With A Dark Secret!",
            "synopsis": "Heather travels to remote Texas to claim a luxurious Victorian estate left by her grandmother, unaware that the inheritance comes with a terrifying family legacy chained beneath the house.",
        },
        2: {
            "hook": "Opening The Hidden Metal Door Beneath The Kitchen Rug!",
            "synopsis": "Exploring the lavish estate, Heather and her friends pull back a cellar rug to uncover a massive double-bolted steel door leading into a soundproof subterranean slaughterhouse.",
        },
        3: {
            "hook": "Ambushed In The Basement By A Chainsaw-Wielding Monster!",
            "synopsis": "The basement door swings open, awakening the hulking masked giant Leatherface, who revs his chainsaw and ambushes the trespassers in a narrow hallway of rusted meat hooks.",
        },
        4: {
            "hook": "Sprinting Through A Crowded Carnival Pursued By Chainsaw!",
            "synopsis": "Fleeing the estate, Heather runs into a crowded county fair, only for Leatherface to carve his way through the midway attractions in broad daylight.",
        },
        5: {
            "hook": "Cornered In The Meatpacking Plant As The Chainsaw Revs!",
            "synopsis": "Cornered inside an industrial meat processing facility, Heather discovers the corrupt local sheriff and his deputies are the true villains who slaughtered her biological family decades ago.",
        },
        6: {
            "hook": "The Dark Family Bloodline Truth Finally Revealed!",
            "synopsis": "Realizing Leatherface is her cousin protecting the family bloodline, Heather hands him back his chainsaw to exact ultimate vengeance on the corrupt town authorities.",
        },
    },
    "the conjuring 2": {
        1: {
            "hook": "Young Girl Levitates As An Old Man Speaks Through Her!",
            "synopsis": "In an Enfield council home in 1977, eleven-year-old Janet begins levitating violently above her bed and speaking in the raspy, demonic voice of a deceased former resident.",
        },
        2: {
            "hook": "The Crooked Man Zoetrope Rhyme Comes Alive In The Dark!",
            "synopsis": "A vintage spinning zoetrope nursery rhyme manifests the terrifying tall shadow of The Crooked Man, terrorizing the Hodgson children across the dark corridors.",
        },
        3: {
            "hook": "Lorraine Warren Trapped In The Study By A Shadow Painting!",
            "synopsis": "Paranormal investigator Lorraine Warren is cornered in her study when the terrifying portrait of the demonic Nun Valak detaches from the canvas and stalks her in the dark.",
        },
        4: {
            "hook": "The Demonic Nun Valak Reveals Her True Evil Form!",
            "synopsis": "Ed and Lorraine uncover that the poltergeist is merely a pawn; an ancient demon named Valak is orchestrating the entire haunting to destroy Ed Warren's life.",
        },
        5: {
            "hook": "Flooded Basement Cistern Standoff In Total Darkness!",
            "synopsis": "With lightning flashing through rain-drenched windows, Ed Warren battles through a flooded cellar to pull Janet back from the edge of a jagged tree stump below.",
        },
        6: {
            "hook": "Commanding The Demon By Its True Name To Save The Family!",
            "synopsis": "Lorraine Warren faces down the demon in the climax, speaking its true biblical name 'Valak' to banish the unholy entity back to hell and rescue the Enfield family.",
        },
    },
}


def find_matching_movie(text: str) -> Optional[MovieEntry]:
    """Finds matching MovieEntry from catalog by analyzing text/filename."""
    t_lower = text.lower()
    for m in THRILLER_MOVIE_CATALOG:
        clean_m_title = m.title.lower()
        if clean_m_title in t_lower or clean_m_title.replace(" ", "_") in t_lower:
            return m
    return None


def extract_episode_number(text: str) -> int:
    """Extracts episode or part number from text/filename."""
    m = re.search(r"(?:episode|part)[_\s-]*0*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return 1


def generate_movie_recap_seo(
    filename: str,
    properties: Optional[Dict[str, Any]] = None,
    total_parts: int = 8
) -> Dict[str, Any]:
    """
    Generates broadcast-grade, click-optimized SEO metadata for movie recap Shorts.
    Returns:
        title: str (Hook | Movie Part X #Shorts)
        description: str (Synopsis + Credits + Schedule CTA + Hashtags)
        tags: List[str] (20 targeted high-volume YouTube search tags)
    """
    props = properties or {}
    text_to_match = f"{filename} {props.get('title', '')} {props.get('topic_title', '')}"

    movie = find_matching_movie(text_to_match)
    movie_title = movie.title if movie else "Wrong Turn"
    movie_year = movie.year if movie else 2003
    movie_director = movie.director if movie else "Rob Schmidt"
    movie_subgenre = movie.subgenre if movie else "Survival Horror / Thriller"
    movie_premise = movie.premise_summary if movie else "Stranded travelers are hunted in remote woods."

    ep_num = extract_episode_number(text_to_match)
    norm_movie_key = movie_title.lower().strip()

    # Check curated catalog first
    curated_movie = CURATED_EPISODE_SEO.get(norm_movie_key, {})
    curated_ep = curated_movie.get(ep_num)

    if curated_ep:
        hook = curated_ep["hook"]
        synopsis = curated_ep["synopsis"]
    else:
        # Dynamic fallback
        hook = f"Trapped In The Deadliest Nightmare! Part {ep_num}"
        synopsis = f"Episode {ep_num} of {movie_title} ({movie_year}): {movie_premise}"

    # 1. High-CTR Title (Format: Hook | Movie Title Part X #Shorts)
    clean_title = f"{hook} | {movie_title} Part {ep_num} #Shorts"
    if len(clean_title) > 100:
        clean_title = f"{hook[:65]} | {movie_title} Part {ep_num} #Shorts"

    # 2. Rich Viral Description
    tag_slug = re.sub(r"[^a-zA-Z0-9]", "", movie_title)
    next_ep = ep_num + 1

    description = f"""🔥 {synopsis}

🎬 Movie: {movie_title} ({movie_year})
🩸 Subgenre: {movie_subgenre}
🍿 Director: {movie_director}
⏳ Next Episode: Episode {next_ep}

🔴 SUBSCRIBE to @ForgottenFiles for Episode {next_ep}!
⏰ New episodes drop daily at 8:00 AM, 4:00 PM & 12:00 AM Midnight IST!

#{tag_slug} #MovieRecap #MovieExplained #HorrorMovie #SurvivalHorror #FilmRecap #EndingExplained #CinemaRecap #Shorts #MoviesInMinutes #ThrillerMovie #{tag_slug}{movie_year}"""

    # 3. 20 Targeted High-Volume Search Tags
    tags = [
        "movie recap",
        "movie recaps",
        "horror movie recap",
        "movie explained",
        "film recap",
        "survival horror",
        "cinema recap",
        "movies summarized",
        "thriller movie recap",
        "story recap",
        "ending explained",
        "forgotten files",
        "horror recap",
        movie_title.lower(),
        f"{movie_title.lower()} {movie_year}",
        f"{movie_title.lower()} recap",
        f"{movie_title.lower()} part {ep_num}",
        f"{movie_title.lower()} episode {ep_num}",
        f"{movie_title.lower()} explained",
        "movies in minutes"
    ]

    return {
        "title": clean_title,
        "description": description.strip(),
        "tags": tags
    }
