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

# Curated seed database of high-retention factual American & European historical events
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
        "title": "The Erfurt Latrine Disaster of 1184",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In July 1184, King Henry VI held a royal diet at the Church of St. Peter in Erfurt, where the wooden floor collapsed under the weight of dozens of nobles who fell into the latrine cesspool below.",
        "curiosity": 9.8, "visual_potential": 8.5, "historical_interest": 9.2, "storytelling": 9.6, "uniqueness": 9.9
    },
    {
        "title": "The London Beer Flood of 1814",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In October 1814, a massive wooden vat at Meux and Company Brewery ruptured, unleashing a 15-foot wave of 320,000 gallons of fermenting porter beer through the streets of St Giles.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 8.8, "storytelling": 9.4, "uniqueness": 9.7
    },
    {
        "title": "The Defenestration of Prague (1618)",
        "category": HistoricalCategory.UNUSUAL_WARS.value,
        "summary": "In May 1618, Protestant nobles threw two Catholic imperial regents out of a 70-foot third-story window of Prague Castle, sparking the Thirty Years War.",
        "curiosity": 9.6, "visual_potential": 9.3, "historical_interest": 9.4, "storytelling": 9.5, "uniqueness": 9.6
    },
    {
        "title": "The Halifax Explosion of 1917",
        "category": HistoricalCategory.DOCUMENTED_DISASTERS.value,
        "summary": "In December 1917, the French cargo ship SS Mont-Blanc, fully loaded with wartime munitions, collided with the Norwegian vessel SS Imo in Halifax Harbour, creating the largest man-made blast before the atomic bomb.",
        "curiosity": 9.7, "visual_potential": 9.5, "historical_interest": 9.3, "storytelling": 9.6, "uniqueness": 9.5
    },
    {
        "title": "The Unsinkable Violet Jessop",
        "category": HistoricalCategory.FORGOTTEN_FIGURES.value,
        "summary": "An ocean liner nurse who survived three separate maritime disasters: the collision of the Olympic, the sinking of the Titanic, and the disaster of the Britannic.",
        "curiosity": 9.7, "visual_potential": 9.1, "historical_interest": 9.4, "storytelling": 9.8, "uniqueness": 9.9
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

    def is_duplicate(self, db: Session, title: str, summary: str = "", script_text: str = "", exclude_topic_id: Optional[str] = None) -> bool:
        """
        Evaluates candidate story against the complete published, ready, and database historical corpus
        using the multi-layer StoryDeduplicationEngine.
        """
        from engines.deduplication_engine import StoryDeduplicationEngine
        dedup_engine = StoryDeduplicationEngine()
        result = dedup_engine.evaluate_candidate(
            candidate_title=title,
            candidate_summary=summary,
            candidate_script=script_text,
            db=db,
            exclude_topic_id=exclude_topic_id
        )
        if not result.is_allowed:
            logger.info(f"Topic '{title}' rejected by Semantic Deduplication Gate ({result.classification}): {result.reason}")
            return True
        return False

    def discover_topics(self, db: Session, limit: int = 5) -> List[Topic]:
        """Discovers new candidate topics or returns unproduced approved topics."""
        # 1. First check if we have approved topics in DB that have not been published or produced yet
        from core.models import Job, UploadRecord
        published_topic_ids = {j.topic_id for j in db.query(Job).filter(Job.state.in_(["PUBLISHED", "READY_TO_UPLOAD"])).all() if j.topic_id}

        unproduced = db.query(Topic).filter(Topic.id.notin_(published_topic_ids)).all()
        # Filter unproduced topics through deduplication against published stories
        valid_unproduced = [t for t in unproduced if not self.is_duplicate(db, t.title, t.summary, exclude_topic_id=t.id)]
        if valid_unproduced:
            random.shuffle(valid_unproduced)
            return valid_unproduced[:limit]

        # 1. Check content strategy from ExperimentManager
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

        # 2. If Gemini API Key is available, generate fresh unique historical stories online with strategy conditioning
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
                            if not self.is_duplicate(db, title, summary):
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
                logger.warning(f"Gemini live topic discovery fallback: {e}")

        # 3. Evaluate curated seed topics
        candidates = list(CURATED_HISTORICAL_SEEDS)
        random.shuffle(candidates)

        for item in candidates:
            if self.is_duplicate(db, item["title"], item["summary"]):
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
        logger.info(f"Discovered {len(discovered)} qualified historical topics.")
        return discovered
