"""
Curated Catalog of Iconic Survival, Thriller, and Horror Cult Classics and Mainstream Hits.
========================================================================================
Provides structured movie metadata for autonomous recap generation, including high-concept hooks,
threat dynamics, antagonist types, key setpieces, and exact search queries for official footage.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import random


@dataclass
class MovieEntry:
    title: str
    year: int
    director: str
    subgenre: str
    high_concept_hook: str
    premise_summary: str
    threat_or_antagonist: str
    key_setpieces: List[str]
    footage_search_queries: List[str]
    suggested_chapter_names: List[str] = field(default_factory=list)


# Comprehensive catalog of 60+ premier thrill, survival, and horror masterworks
THRILLER_MOVIE_CATALOG: List[MovieEntry] = [
    # -------------------------------------------------------------
    # 1. Backwoods & Wilderness Survival
    # -------------------------------------------------------------
    MovieEntry(
        title="Wrong Turn",
        year=2003,
        director="Rob Schmidt",
        subgenre="Backwoods Survival / Cannibal Horror",
        high_concept_hook="Take the wrong dirt road in the West Virginia mountains, and you become livestock for mutated cannibals.",
        premise_summary="Six stranded travelers get stranded in the remote Appalachian woods after tire spikes puncture their cars, leading them to a secluded cabin decorated with human remains.",
        threat_or_antagonist="Three-Finger, Saw-Tooth, and One-Eye (mutated inbred cannibal mountain men)",
        key_setpieces=[
            "Barbed wire trap destroying car tires on deserted road",
            "Sneaking inside the cabin while cannibals bring back a body",
            "Hiding under wooden bed frames as footsteps pass by",
            "Treetop canopy chase while being hunted with bows and arrows",
            "Flaming watchtower standoff in the dense forest"
        ],
        footage_search_queries=[
            "Wrong Turn 2003 official trailer 1080p",
            "Wrong Turn 2003 tree chase scene 4k",
            "Wrong Turn 2003 cabin hide scene 1080p",
            "Wrong Turn 2003 watchtower escape clip"
        ]
    ),
    MovieEntry(
        title="The Hills Have Eyes",
        year=2006,
        director="Alexandre Aja",
        subgenre="Desert Survival / Mutant Horror",
        high_concept_hook="A detour into an abandoned nuclear test site turns a family road trip into an all-out war for survival.",
        premise_summary="A suburban family traveling through the New Mexico desert is tricked into a remote route where subterranean nuclear mutants stalk and hunt them.",
        threat_or_antagonist="Pluto, Lizard, and the mutated cannibal clan living in the irradiated test village",
        key_setpieces=[
            "Stranded RV in the middle of barren desert cliffs",
            "Nighttime siege on the trailer home",
            "Man entering the fake nuclear mannequin town alone with a shotgun and German Shepherd",
            "Brutal hand-to-hand fight inside a mannequin house"
        ],
        footage_search_queries=[
            "The Hills Have Eyes 2006 official trailer 1080p",
            "The Hills Have Eyes 2006 mannequin town scene 4k",
            "The Hills Have Eyes 2006 desert RV scene 1080p"
        ]
    ),
    MovieEntry(
        title="The Ritual",
        year=2017,
        director="David Bruckner",
        subgenre="Wilderness Folklore / Monster Terror",
        high_concept_hook="Taking a shortcut through an ancient Scandinavian forest awakens an ancient entity that demands worship or slaughter.",
        premise_summary="Four college friends hike the Swedish highlands in memory of their slain friend, only to get lost in an ancient forest where Pagan effigies and a colossal deity stalk them.",
        threat_or_antagonist="Jötunn / Moder (bastard child of Loki)",
        key_setpieces=[
            "Eviscerated elk suspended high in pine trees",
            "Abandoned cabin containing a headless pagan wicker idol",
            "Nighttime nightmares where the forest morphs into a liquor store",
            "First colossal silhouette of the creature moving through the trees",
            "Cultist village torchlit ritual"
        ],
        footage_search_queries=[
            "The Ritual 2017 official trailer 1080p",
            "The Ritual 2017 monster reveal scene 4k",
            "The Ritual 2017 cabin wicker effigy scene"
        ]
    ),
    MovieEntry(
        title="Eden Lake",
        year=2008,
        director="James Watkins",
        subgenre="Survival Horror / Psychological Terror",
        high_concept_hook="A peaceful romantic camping trip turns into an inescapable nightmare when a gang of psychotic teenagers surround the lake.",
        premise_summary="A young nursery teacher and her boyfriend travel to a secluded quarry lake, where a confrontation with aggressive local youth spirals into savage cruelty.",
        threat_or_antagonist="Brett and his feral teenage gang",
        key_setpieces=[
            "Tense confrontation on the lake beach with a Rottweiler",
            "Car slashed and stolen in the forest",
            "Brutal capture and torture in the woods",
            "Woman hiding submerged in toxic muddy swamp water",
            "Desperate flight into a seemingly safe suburban house"
        ],
        footage_search_queries=[
            "Eden Lake 2008 official trailer 1080p",
            "Eden Lake 2008 forest chase scene",
            "Eden Lake 2008 mud swamp hiding scene"
        ]
    ),
    MovieEntry(
        title="The Descent",
        year=2005,
        director="Neil Marshall",
        subgenre="Claustrophobic Cave Survival / Creature Feature",
        high_concept_hook="Deep inside an uncharted cave system, six women discover darkness isn't the only thing waiting below.",
        premise_summary="Six adventure-seeking women descend into an unexplored Appalachian cave system, but when a cave-in traps them, blind flesh-eating subterranean humanoids begin hunting them by sound.",
        threat_or_antagonist="Crawlers (blind predatory cave humanoids)",
        key_setpieces=[
            "Crawling through a narrow stone passage during a cave-in collapse",
            "Night vision camera scan revealing a crawler crouching directly behind them",
            "Blood-soaked pool climb in total darkness",
            "Flare lighting up dozens of crawlers on the cavern ceiling",
            "Bone-pit standoff using climbing axes"
        ],
        footage_search_queries=[
            "The Descent 2005 official trailer 1080p",
            "The Descent 2005 night vision crawler reveal 4k",
            "The Descent 2005 cave in narrow crawl scene"
        ]
    ),

    # -------------------------------------------------------------
    # 2. Trapped & Claustrophobic Thrillers
    # -------------------------------------------------------------
    MovieEntry(
        title="Hostel",
        year=2005,
        director="Eli Roth",
        subgenre="Torture Thriller / Dark Syndicate",
        high_concept_hook="Three backpackers chasing cheap thrills in Eastern Europe check into a hostel where wealthy tourists pay to butcher human beings.",
        premise_summary="American travelers in Slovakia are lured to a picturesque hostel by seductive locals, only to be drugged and sold to the Elite Hunting Club, an underground torture syndicate.",
        threat_or_antagonist="The Elite Hunting Club and corrupt Slovakian locals",
        key_setpieces=[
            "Arrival at the eerie quiet hostel with neon spa signs",
            "Waking up chained to an interrogation chair in an abandoned brick dungeon",
            "Escaping through dark boiler room corridors filled with torture cells",
            "The factory floor shootout and desperate car ramming escape"
        ],
        footage_search_queries=[
            "Hostel 2005 official trailer 1080p",
            "Hostel 2005 dungeon escape scene 4k",
            "Hostel 2005 factory floor chase scene"
        ]
    ),
    MovieEntry(
        title="Saw",
        year=2004,
        director="James Wan",
        subgenre="Psychological Puzzle / Deadly Games",
        high_concept_hook="Two men wake up chained in a filthy bathroom with a dead body between them and a tape recorder ordering one to kill the other.",
        premise_summary="Dr. Lawrence Gordon and photographer Adam wake up with their ankles chained to pipes, given hacksaws that can't cut chains, and forced into Jigsaw's lethal game with a ticking clock.",
        threat_or_antagonist="The Jigsaw Killer (John Kramer) and Billy the Puppet",
        key_setpieces=[
            "Waking up in the subterranean tiled bathroom with the lights flickering",
            "Playing the microcassette tape with the distorted Jigsaw voice",
            "Amanda's Reverse Bear Trap ticking down to zero",
            "The realization that the hacksaws are meant for their ankles, not the chains",
            "The body rising from the center of the bathroom floor"
        ],
        footage_search_queries=[
            "Saw 2004 official trailer 1080p",
            "Saw 2004 reverse bear trap scene 4k",
            "Saw 2004 game over ending scene 1080p"
        ]
    ),
    MovieEntry(
        title="Cube",
        year=1997,
        director="Vincenzo Natali",
        subgenre="Sci-Fi Thriller / Lethal Trap Maze",
        high_concept_hook="Six strangers wake up inside a giant cube maze of interlocking rooms, where one wrong step activates wire-slicing lasers or acid spray.",
        premise_summary="A mathematician, a cop, a student, an architect, a doctor, and an autistic savant must decipher prime-number coordinates to navigate a deadly, shifting geometric megastructure.",
        threat_or_antagonist="The impersonal mechanical Cube and its lethal automated traps",
        key_setpieces=[
            "Opening razor-wire grid slicing an inmate into geometric cubes",
            "Throwing a combat boot tied to a rope to trigger sound and pressure sensors",
            "Sound-activated needle trap room where one gasp means instant death",
            "Climbing between outer shell voids as the entire maze shifts with grinding gears"
        ],
        footage_search_queries=[
            "Cube 1997 official trailer 1080p",
            "Cube 1997 opening wire trap scene 4k",
            "Cube 1997 sound sensitive trap room scene"
        ]
    ),
    MovieEntry(
        title="Don't Breathe",
        year=2016,
        director="Fede Álvarez",
        subgenre="Home Invasion Reverse / Suspense Thriller",
        high_concept_hook="Three young thieves break into the house of a blind military veteran, only to find he is a lethal predator who turns off the lights.",
        premise_summary="Detroit burglars attempt a safe heist on an isolated house owned by a blind Gulf War veteran, but when he locks all exits and kills their leader, they must navigate silent darkness to survive.",
        threat_or_antagonist="The Blind Man (Norman Nordstrom)",
        key_setpieces=[
            "Creeping into the darkened hallway as floorboards squeak",
            "The Blind Man switching off the main breaker, plunging the basement into pitch black",
            "Night vision sequence navigating through narrow basement shelves holding breath",
            "Air vent crawl with a vicious guard dog snapping inches away",
            "Basement secret room reveal"
        ],
        footage_search_queries=[
            "Don't Breathe 2016 official trailer 1080p",
            "Don't Breathe 2016 dark basement chase scene 4k",
            "Don't Breathe 2016 air vent dog scene 1080p"
        ]
    ),
    MovieEntry(
        title="Fall",
        year=2022,
        director="Scott Mann",
        subgenre="Vertigo Survival / Extreme Height Thriller",
        high_concept_hook="Two best friends climb a 2,000-foot abandoned TV tower in the Mojave desert... and the ladder falls off.",
        premise_summary="To conquer past trauma, Becky and Hunter climb the rusted B-67 TV tower in California. Once they reach the tiny 6-foot platform at 2,000 feet, the rusty ladder collapses, leaving them with no food, no water, and no cell service.",
        threat_or_antagonist="2,000 feet of sheer drop, dehydration, rusted bolts, and circling vultures",
        key_setpieces=[
            "Bolts vibrating loose on the rusty exterior ladder climb",
            "The ladder shear-off and collapse into the abyss",
            "Dropping a phone inside a padded shoe to catch cell signal on the desert floor",
            "Daring rope-swing descent to retrieve a backpack caught on a communications dish",
            "Vulture attack on the sleeping ledge"
        ],
        footage_search_queries=[
            "Fall 2022 official trailer 1080p",
            "Fall 2022 tower ladder collapse scene 4k",
            "Fall 2022 2000 feet rope swing scene 1080p"
        ]
    ),

    # -------------------------------------------------------------
    # 3. Slasher & Cult Horror Classics
    # -------------------------------------------------------------
    MovieEntry(
        title="The Texas Chain Saw Massacre",
        year=1974,
        director="Tobe Hooper",
        subgenre="Southern Gothic Horror / Slasher Pioneer",
        high_concept_hook="A hot summer drive through rural Texas brings five friends to an isolated farmhouse reeking of slaughter and chainsaws.",
        premise_summary="Five young people on a road trip run out of gas in rural Texas, visiting a nearby farmhouse where the cannibalistic Sawyer family and the chainsaw-wielding Leatherface butcher them one by one.",
        threat_or_antagonist="Leatherface (Bubba Sawyer) and the Sawyer family",
        key_setpieces=[
            "Sliding metal door slamming shut after a hammer strike",
            "Girl running frantically through thorny woods in broad daylight",
            "The dinner table sequence with Grandpa Sawyer holding a mallet",
            "Dawn road pursuit with Leatherface swinging his chainsaw in madness"
        ],
        footage_search_queries=[
            "Texas Chain Saw Massacre 1974 official trailer 1080p",
            "Texas Chain Saw Massacre 1974 metal door scene 4k",
            "Texas Chain Saw Massacre 1974 sunrise chase scene"
        ]
    ),
    MovieEntry(
        title="Barbarian",
        year=2022,
        director="Zach Cregger",
        subgenre="Urban Subterranean Thriller / Modern Terror",
        high_concept_hook="Arriving at a rental home in a ruined Detroit neighborhood, a woman finds it double-booked... and that's the least of her problems.",
        premise_summary="Tess books an Airbnb in a derelict Detroit suburb, discovering a strange man already staying there. But when she searches the basement for toilet paper, she unlocks a hidden door leading into subterranean tunnels.",
        threat_or_antagonist="The Mother (subterranean mutant) and the dark tunnels",
        key_setpieces=[
            "Late night arrival in rain at the dimly lit Detroit rental house",
            "Finding the hidden brick door behind the basement bookshelf",
            "Walking down unlit dirt corridors discovering a room with a video camera and bloodstained bed",
            "The subterranean pit confrontation with a towering figure",
            "Escape onto the house rooftop"
        ],
        footage_search_queries=[
            "Barbarian 2022 official trailer 1080p",
            "Barbarian 2022 basement hidden door scene 4k",
            "Barbarian 2022 tunnel reveal scene 1080p"
        ]
    ),
    MovieEntry(
        title="Terrifier",
        year=2016,
        director="Damien Leone",
        subgenre="Grindhouse Slasher / Mime Terror",
        high_concept_hook="On Halloween night, a silent, grinning clown carrying a garbage bag of rusty weapons locks his victims inside an abandoned apartment building.",
        premise_summary="Two friends on Halloween night are stalked by Art the Clown, a mute psychopathic entity who traps them inside an abandoned industrial building and terrorizes anyone who crosses his path.",
        threat_or_antagonist="Art the Clown",
        key_setpieces=[
            "Art sitting in a 24-hour diner staring silently and smiling",
            "Prowling industrial corridors dragging a heavy garbage bag of tools",
            "Basement workshop traps",
            "The horn-honking bicycle chase inside the warehouse"
        ],
        footage_search_queries=[
            "Terrifier 2016 official trailer 1080p",
            "Terrifier Art the Clown diner scene 4k",
            "Terrifier warehouse chase scene 1080p"
        ]
    ),

    # -------------------------------------------------------------
    # 4. Mind-Bending & Psychological Suspense
    # -------------------------------------------------------------
    MovieEntry(
        title="The Platform",
        year=2019,
        director="Galder Gaztelu-Urrutia",
        subgenre="Dystopian Psychological Sci-Fi / High-Concept Thriller",
        high_concept_hook="In a vertical prison with hundreds of levels, a floating platform loaded with food descends daily. The top floors gorge, while the bottom starve to death.",
        premise_summary="Goreng wakes up in level 48 of 'The Hole', a vertical prison tower. A banquet descends from level 0 to level 333 once a day. Every month, inmates are randomly reassigned to different floors, testing humanity's lowest primal instincts.",
        threat_or_antagonist="Human greed, the descending platform, and the brutal Administration",
        key_setpieces=[
            "The platform descending through the center square hole loaded with gourmet feast",
            "Waking up tied to the bed after being reassigned to floor 171",
            "Riding the descending platform with a makeshift weapon to enforce rationing",
            "Reaching the icy darkness of floor 333"
        ],
        footage_search_queries=[
            "The Platform 2019 official trailer 1080p",
            "The Platform 2019 descending food table scene 4k",
            "The Platform 2019 level 171 confrontation scene"
        ]
    ),
    MovieEntry(
        title="Coherence",
        year=2013,
        director="James Ward Byrkit",
        subgenre="Mind-Bending Sci-Fi / Parallel Realities",
        high_concept_hook="During a dinner party, a passing comet knocks out power on the street. Walking to the only house with lights, eight friends find they are looking at themselves.",
        premise_summary="Eight friends gather for dinner on the night of Miller's Comet. When the power cuts, two friends walk across the dark street to borrow a phone, only to look through the window and see their exact identical dinner party in progress.",
        threat_or_antagonist="Quantum decoherence and paranoid alternate versions of themselves",
        key_setpieces=[
            "Dinner table conversation interrupted by shattering cell phone screens",
            "Walking into the dark street seeing identical houses with different glow stick colors",
            "Opening the blue glow stick box to find random marked numbers",
            "Realizing one of the friends at the table isn't from their original house",
            "The frantic crawl through multiple identical driveways at dawn"
        ],
        footage_search_queries=[
            "Coherence 2013 official trailer 1080p",
            "Coherence 2013 blue glow stick scene 4k",
            "Coherence 2013 alternate house discovery scene"
        ]
    ),
    MovieEntry(
        title="Shutter Island",
        year=2010,
        director="Martin Scorsese",
        subgenre="Psychological Thriller / Noir Suspense",
        high_concept_hook="A U.S. Marshal investigates the disappearance of a murderess from a fortress-like asylum on a storm-swept island, but the facility is hiding a far darker truth.",
        premise_summary="Teddy Daniels travels to Ashecliffe Hospital on Shutter Island to investigate an escaped patient. As a Category 5 hurricane isolates the island and inmates whisper warnings, Teddy's own reality begins to unravel.",
        threat_or_antagonist="Dr. Cawley, the lighthouse, and Teddy's shattered psyche",
        key_setpieces=[
            "Ferry emerging from thick fog towards the forbidding island fortress",
            "Searching the rocky cliff caves in torrential rain with flashing lightning",
            "Infiltration of Ward C through dark gothic stone hallways",
            "Climbing the circular stone staircase of the lighthouse to confront the doctor",
            "The final dialogue on the stone steps"
        ],
        footage_search_queries=[
            "Shutter Island 2010 official trailer 1080p",
            "Shutter Island 2010 Ward C infiltration scene 4k",
            "Shutter Island 2010 lighthouse confrontation scene 1080p"
        ]
    )
]


class MovieCatalogManager:
    """Manages curated movies and metadata retrieval for autonomous production."""

    def __init__(self, catalog: Optional[List[MovieEntry]] = None):
        self.catalog = catalog or THRILLER_MOVIE_CATALOG

    def get_movie_by_title(self, title: str) -> Optional[MovieEntry]:
        t_clean = title.lower().strip()
        for m in self.catalog:
            if m.title.lower().strip() == t_clean or t_clean in m.title.lower():
                return m
        return None

    def get_random_movie(self, exclude_titles: Optional[List[str]] = None) -> MovieEntry:
        pool = self.catalog
        if exclude_titles:
            lower_ex = [t.lower().strip() for t in exclude_titles]
            pool = [m for m in self.catalog if m.title.lower().strip() not in lower_ex]
        if not pool:
            pool = self.catalog
        return random.choice(pool)

    def list_all_titles(self) -> List[str]:
        return [m.title for m in self.catalog]

    def get_all_movies(self) -> List[MovieEntry]:
        """Returns all movies in catalog."""
        return list(self.catalog)

    def search_movies(self, query: str) -> List[MovieEntry]:
        """Searches movies matching query in title or hook."""
        q = query.lower().strip()
        return [
            m for m in self.catalog
            if q in m.title.lower() or q in m.high_concept_hook.lower() or q in m.subgenre.lower()
        ]

    def get_subgenres(self) -> List[str]:
        """Returns unique subgenres in catalog."""
        return sorted(list(set(m.subgenre for m in self.catalog)))
