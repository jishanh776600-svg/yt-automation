"""
Topic Discovery Engine.
Generates, filters, and scores intriguing American and European historical stories.
Avoids spam, balances categories, and scores via multi-factor retention model.
"""
import uuid
import random
import logging
from typing import List, Dict, Any, Optional
import wikipediaapi
from sqlalchemy.orm import Session
from config.constants import HistoricalCategory
from config.settings import GEMINI_API_KEY
from core.models import Topic

logger = logging.getLogger(__name__)

# Vast Curated Archive of High-Retention Factual American & European Historical Events
CURATED_HISTORICAL_SEEDS = [
    {
        "title": "The Great Stink of London (1858)",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In the blazing summer of 1858, the Thames River in London smelled so overpoweringly toxic that Parliament had to soak their curtains in lime chloride and hastily rebuild the entire modern sewage network.",
        "curiosity": 9.5, "visual_potential": 8.5, "historical_interest": 9.0, "storytelling": 9.5, "uniqueness": 9.0
    },
    {
        "title": "The 38-Minute Anglo-Zanzibar War (1896)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "On August 27, 1896, the British Empire engaged in the shortest war in recorded world history, defeating the Sultan's palace in exactly 38 minutes flat.",
        "curiosity": 9.8, "visual_potential": 9.0, "historical_interest": 9.2, "storytelling": 9.7, "uniqueness": 9.8
    },
    {
        "title": "The Strange Town of Baarle-Hertog",
        "category": HistoricalCategory.UNUSUAL_BORDERS.value,
        "summary": "A single town in Europe split between Belgium and the Netherlands has 24 separate exclaves, meaning borders literally cut through living rooms, restaurants, and front doors.",
        "curiosity": 9.4, "visual_potential": 8.8, "historical_interest": 8.5, "storytelling": 9.0, "uniqueness": 9.6
    },
    {
        "title": "The Boston Molasses Flood of 1919",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "A massive 50-foot storage tank burst in Boston, releasing a 35-mile-per-hour tsunami of two million gallons of boiling molasses through city streets.",
        "curiosity": 9.6, "visual_potential": 9.2, "historical_interest": 8.9, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The Pig War of San Juan Island (1859)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In 1859, the United States and Great Britain almost sparked a full-scale armed war in the Pacific Northwest over a single trespassing pig eating potatoes.",
        "curiosity": 9.5, "visual_potential": 8.7, "historical_interest": 9.0, "storytelling": 9.3, "uniqueness": 9.5
    },
    {
        "title": "The Lost Roanoke Colony Mystery",
        "category": HistoricalCategory.LOST_PLACES.value,
        "summary": "In 1590, John White returned to Roanoke Island to discover 115 English settlers had vanished without a trace, leaving only the cryptic word CROATOAN carved on a post.",
        "curiosity": 9.7, "visual_potential": 9.0, "historical_interest": 9.5, "storytelling": 9.6, "uniqueness": 9.4
    },
    {
        "title": "The Dancing Plague of Strasbourg (1518)",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "In July 1518, hundreds of citizens in Strasbourg suddenly began dancing uncontrollably in the public square for weeks on end without rest until collapsing.",
        "curiosity": 9.6, "visual_potential": 8.9, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.8
    },
    {
        "title": "The Unsinkable Violet Jessop",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "An ocean liner nurse who survived three separate maritime disasters: the collision of the Olympic, the sinking of the Titanic, and the disaster of the Britannic.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 9.4, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The Erfurt Latrine Disaster of 1184",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In 1184, King Henry VI held a royal peace summit in Erfurt when the wooden floor collapsed, sending dozens of European nobles plunging into the liquid cesspit below.",
        "curiosity": 9.9, "visual_potential": 8.8, "historical_interest": 9.2, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The War of Jenkins Ear (1739)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "A 9-year global naval war between Britain and Spain erupted after a Spanish coast guard officer sliced off the ear of British merchant captain Robert Jenkins.",
        "curiosity": 9.6, "visual_potential": 8.9, "historical_interest": 9.1, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The London Beer Flood of 1814",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "A massive 22-foot-tall wooden vat at the Meux & Co Brewery ruptured, unleashing a 300,000-gallon wave of porter beer that flooded the slums of St. Giles.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 9.0, "storytelling": 9.6, "uniqueness": 9.8
    },
    {
        "title": "The Great Emu War of 1932",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "The military deployed soldiers armed with Lewis machine guns against a mob of 20,000 crop-destroying emus, only for the fast-running birds to outmaneuver the army.",
        "curiosity": 9.8, "visual_potential": 9.3, "historical_interest": 9.2, "storytelling": 9.7, "uniqueness": 9.9
    },
    {
        "title": "The Cadaver Synod of 897",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "Pope Stephen VI had the rotting corpse of his deceased predecessor, Pope Formosus, exhumed, dressed in papal robes, and placed on trial in a Roman basilica.",
        "curiosity": 9.9, "visual_potential": 9.0, "historical_interest": 9.5, "storytelling": 9.9, "uniqueness": 9.9
    },
    {
        "title": "The Secret Underground City of Derinkuyu",
        "category": HistoricalCategory.LOST_PLACES.value,
        "summary": "In 1963, a Turkish man knocked down a basement wall during renovations and discovered a massive 18-story ancient underground metropolis built for 20,000 citizens.",
        "curiosity": 9.8, "visual_potential": 9.5, "historical_interest": 9.6, "storytelling": 9.7, "uniqueness": 9.8
    },
    {
        "title": "The Bizarre French Bread Law of 1900",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "In 19th-century Paris, bakers were legally forbidden from taking vacations without government permission to prevent citywide revolutionary food riots.",
        "curiosity": 9.3, "visual_potential": 8.6, "historical_interest": 8.8, "storytelling": 9.1, "uniqueness": 9.4
    },
    {
        "title": "The Man Who Bought the Eiffel Tower Twice",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "In 1925, charismatic con artist Victor Lustig forged government documents and convinced French scrap metal dealers to buy the Eiffel Tower for demolition—not once, but twice.",
        "curiosity": 9.8, "visual_potential": 9.2, "historical_interest": 9.4, "storytelling": 9.8, "uniqueness": 9.9
    },
    {
        "title": "The Tunguska Cosmic Explosion of 1908",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "A massive airburst flattened 80 million trees across 800 square miles of Siberian forest with the force of a 15-megaton bomb, leaving zero impact craters.",
        "curiosity": 9.7, "visual_potential": 9.4, "historical_interest": 9.5, "storytelling": 9.6, "uniqueness": 9.6
    },
    {
        "title": "The Great Train Robbery of 1855",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "Edward Agar engineered the first heist of moving railway safes between London and Paris, replacing 200 pounds of solid gold bullion with lead shot.",
        "curiosity": 9.5, "visual_potential": 9.0, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.5
    },
    {
        "title": "The Halifax Harbor Explosion of 1917",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "A collision between two ships in Halifax Harbor sparked the largest man-made non-nuclear explosion in world history, creating a 60-foot tsunami.",
        "curiosity": 9.6, "visual_potential": 9.3, "historical_interest": 9.3, "storytelling": 9.5, "uniqueness": 9.6
    },
    {
        "title": "The Battle of Karánsebes (1788)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "An Austrian army of 100,000 soldiers panicked in the dead of night after a brawl over schnapps, firing on their own shadows and inflicting thousands of friendly casualties.",
        "curiosity": 9.8, "visual_potential": 9.1, "historical_interest": 9.3, "storytelling": 9.7, "uniqueness": 9.9
    },
    {
        "title": "The Day the Sun Went Out (1780)",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "On May 19, 1780, an ominous deep pitch-black darkness enveloped New England at midday, forcing candles to be lit as citizens prepared for the Biblical apocalypse.",
        "curiosity": 9.6, "visual_potential": 9.2, "historical_interest": 9.1, "storytelling": 9.5, "uniqueness": 9.6
    },
    {
        "title": "The Defenestrations of Prague",
        "category": HistoricalCategory.STRANGE_LAWS.value,
        "summary": "Three separate times in European history (1419, 1483, 1618), Bohemian political disputes were resolved by literally hurling government officials out of castle windows.",
        "curiosity": 9.7, "visual_potential": 9.0, "historical_interest": 9.4, "storytelling": 9.6, "uniqueness": 9.8
    },
    {
        "title": "The Great Maple Syrup Heist of 2012",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "Over several months, thieves siphoned off nearly 3,000 tons of maple syrup from the Global Strategic Reserve in Quebec, stealing $18.7 million worth of sweet gold.",
        "curiosity": 9.5, "visual_potential": 8.9, "historical_interest": 8.7, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The Lost City of Heracleion",
        "category": HistoricalCategory.LOST_PLACES.value,
        "summary": "A legendary ancient Mediterranean port city that swallowed by earthquakes in the 8th century AD lay submerged beneath the sea for 1,200 years until discovered by divers.",
        "curiosity": 9.7, "visual_potential": 9.5, "historical_interest": 9.6, "storytelling": 9.6, "uniqueness": 9.7
    },
    {
        "title": "The Ghost Army of World War II",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "The 23rd Headquarters Special Troops used inflatable tanks, sound-effects trucks, and fake radio broadcasts to deceive German intelligence across Europe.",
        "curiosity": 9.8, "visual_potential": 9.4, "historical_interest": 9.5, "storytelling": 9.7, "uniqueness": 9.8
    }
]


class TopicDiscoveryEngine:
    """Discovers, evaluates, and scores high-performing historical topics."""

    def __init__(self):
        self.wiki = wikipediaapi.Wikipedia(
            user_agent="HistoryShortsPipeline/1.0 (historical_research@shorts.ai)",
            language="en"
        )

    def calculate_topic_score(self, item: Dict[str, Any]) -> float:
        """
        Calculates multi-factor score:
        TOPIC_SCORE = curiosity + visual_potential + historical_interest + storytelling + uniqueness
        """
        curiosity = float(item.get("curiosity", 8.0))
        visual_potential = float(item.get("visual_potential", 8.0))
        historical_interest = float(item.get("historical_interest", 8.0))
        storytelling = float(item.get("storytelling", 8.0))
        uniqueness = float(item.get("uniqueness", 8.0))

        score = (curiosity * 1.3) + (visual_potential * 1.1) + (historical_interest * 1.0) + (storytelling * 1.4) + (uniqueness * 1.2)
        return round(score, 2)

    def is_duplicate(self, db: Session, title: str) -> bool:
        """Checks if a topic with similar title already exists in DB."""
        clean_title = title.lower().strip()
        existing = db.query(Topic).all()
        for t in existing:
            t_clean = t.title.lower().strip()
            if clean_title == t_clean or (len(clean_title) > 5 and clean_title in t_clean):
                return True
        return False

    def discover_topics(self, db: Session, limit: int = 5) -> List[Topic]:
        """Discovers new candidate topics or returns unproduced approved topics."""
        # 1. First check if we have approved topics in DB that have not been published or queued yet
        from core.models import Job
        used_topic_ids = {j.topic_id for j in db.query(Job).all() if j.topic_id}

        unproduced = db.query(Topic).filter(Topic.id.notin_(used_topic_ids)).all()
        if unproduced:
            random.shuffle(unproduced)
            return unproduced[:limit]

        # 2. Check content strategy from ExperimentManager
        strategy_info = {"strategy_type": "PROVEN_PATTERN", "description": "Default strategy"}
        try:
            from engines.experiment_manager import ExperimentManager
            from engines.learning_engine import LearningEngine
            exp_mgr = ExperimentManager()
            learn_eng = LearningEngine()
            strategy_info = exp_mgr.select_content_strategy(db)
            guidance = learn_eng.get_strategy_guidance(db)
            logger.info(f"Topic Discovery running under strategy: [{strategy_info['strategy_type']}] - {strategy_info['description']}")
        except Exception as e:
            logger.warning(f"Could not load learning guidance: {e}")
            guidance = {}

        discovered = []

        # 3. If Gemini API Key is available, generate fresh unique historical stories online
        if GEMINI_API_KEY:
            try:
                from google import genai
                client = genai.Client(api_key=GEMINI_API_KEY)
                
                favored_cats = guidance.get("top_categories", ["Unusual Wars", "Documented Disasters"])
                cat_prompt_part = f"Focus especially on high-performing categories: {', '.join(favored_cats)}." if strategy_info["strategy_type"] == "PROVEN_PATTERN" else "Explore unusual, less-known historical categories."

                prompt = (
                    f"Suggest 3 obscure, true, bizarre historical events from American or European history "
                    f"that make great 23-second YouTube Shorts. {cat_prompt_part} "
                    f"Format each as: Title | Category | 1-sentence factual summary. "
                    f"Do NOT use generic facts. Prioritize strange laws, unusual wars, or documented mysteries."
                )
                response = client.models.generate_content(
                    model="gemini-3.6-flash",
                    contents=prompt
                )
                lines = response.text.strip().split("\n")
                for line in lines:
                    if "|" in line:
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 3:
                            title, category, summary = parts[0].lstrip("1234567890. -*"), parts[1], parts[2]
                            if not self.is_duplicate(db, title):
                                topic_id = f"top_{uuid.uuid4().hex[:12]}"
                                topic = Topic(
                                    id=topic_id,
                                    title=title,
                                    summary=summary,
                                    category=category,
                                    score=52.0,
                                    status="APPROVED"
                                )
                                db.add(topic)
                                discovered.append(topic)
                                if len(discovered) >= limit:
                                    break
                if discovered:
                    db.commit()
                    logger.info(f"Discovered {len(discovered)} fresh topics via Gemini 3.6 Flash AI under strategy {strategy_info['strategy_type']}!")
                    return discovered
            except Exception as e:
                logger.warning(f"Gemini live topic discovery notice: {e} (Falling back to curated historical seed archive)")

        # 4. Fallback: Evaluate curated seed archive
        candidates = list(CURATED_HISTORICAL_SEEDS)
        random.shuffle(candidates)

        for item in candidates:
            if self.is_duplicate(db, item["title"]):
                continue

            score = self.calculate_topic_score(item)
            if score < 45.0:
                continue

            topic_id = f"top_{uuid.uuid4().hex[:12]}"
            topic = Topic(
                id=topic_id,
                title=item["title"],
                summary=item["summary"],
                category=item["category"],
                score=score,
                status="APPROVED"
            )
            db.add(topic)
            discovered.append(topic)
            if len(discovered) >= limit:
                break

        db.commit()
        logger.info(f"Discovered {len(discovered)} qualified historical topics from curated historical library.")
        return discovered
