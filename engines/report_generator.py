"""
Daily & Weekly Performance Strategy Reporter + Persistent Human Learning Log.
Generates structured Markdown reports and maintains data/LEARNING_LOG.md.
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from config.settings import PROJECT_ROOT
from core.models import UploadRecord, PerformanceSnapshot, VideoAnalysisRecord, ContentPattern, ExperimentRecord, Job, Topic, ScriptRecord

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates human-readable learning logs, daily reviews, and weekly strategic updates."""

    def __init__(self):
        self.learning_log_path = PROJECT_ROOT / "data" / "LEARNING_LOG.md"

    def append_to_learning_log(self, date_str: str, video_title: str, result: str, observation: str, hypothesis: str, experiment: str, confidence: str, decision: str):
        """Appends a structured entry to the persistent human-readable learning log."""
        self.learning_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.learning_log_path.exists():
            header = "# Persistent Content Learning Log (Closed Feedback Loop)\n\n| Date | Video | Result | Observation (Facts) | Hypothesis | Experiment | Confidence | Strategic Decision |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
            self.learning_log_path.write_text(header, encoding="utf-8")

        entry = f"| {date_str} | **{video_title}** | `{result}` | {observation} | {hypothesis} | {experiment} | **{confidence}** | {decision} |\n"
        with open(self.learning_log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    def generate_daily_learning_report(self, db: Session) -> str:
        """Generates a concise daily internal report for recent Shorts."""
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        
        analyses = db.query(VideoAnalysisRecord).order_by(VideoAnalysisRecord.analyzed_at.desc()).limit(5).all()
        patterns = db.query(ContentPattern).order_by(ContentPattern.composite_effectiveness_score.desc()).all()
        experiments = db.query(ExperimentRecord).filter(ExperimentRecord.status == "PLANNED").limit(3).all()

        total_published = db.query(UploadRecord).count()
        
        outperformers = [a for a in analyses if a.classification == "OUTPERFORMER"]
        underperformers = [a for a in analyses if a.classification == "UNDERPERFORMER"]

        best_title = "N/A"
        worst_title = "N/A"

        if outperformers:
            upl = db.query(UploadRecord).filter(UploadRecord.id == outperformers[0].upload_id).first()
            if upl:
                best_title = upl.title
        elif analyses:
            upl = db.query(UploadRecord).filter(UploadRecord.id == analyses[0].upload_id).first()
            if upl:
                best_title = upl.title

        if underperformers:
            upl = db.query(UploadRecord).filter(UploadRecord.id == underperformers[0].upload_id).first()
            if upl:
                worst_title = upl.title

        top_pattern = patterns[0] if patterns else None

        report = f"""==================================================
DAILY SHORTS INTELLIGENCE & LEARNING REPORT
Date: {now.strftime('%Y-%m-%d %H:%M UTC')}
==================================================

VIDEOS PUBLISHED (TOTAL):
{total_published}

BEST PERFORMER:
{best_title}

WORST PERFORMER:
{worst_title}

WHAT WORKED (EVIDENCE-BASED):
{top_pattern.pattern_type.upper() + ': ' + top_pattern.pattern_key + ' (APV: ' + f'{top_pattern.avg_percentage_viewed:.1f}%' + ', Score: ' + f'{top_pattern.composite_effectiveness_score:.1f}' + ')' if top_pattern else 'Initial baseline accumulation in progress'}

WHAT FAILED (ROOT-CAUSE HYPOTHESIS):
{('Low early retention on underperformers; investigating 2-second hook drop-off' if underperformers else 'No chronic failure patterns detected yet')}

NEW PATTERN DISCOVERED:
{top_pattern.description if top_pattern else 'Initial baseline cohort'}

CONFIDENCE:
{top_pattern.confidence if top_pattern else 'LOW_CONFIDENCE'}

NEXT SCHEDULED EXPERIMENTS (60/30/10 RULE):
1. {experiments[0].title if len(experiments) > 0 else 'Controlled Experiment A: Re-test winning hook on new topic'}
2. {experiments[1].title if len(experiments) > 1 else 'Controlled Experiment B: 22.5s duration calibration test'}
3. {experiments[2].title if len(experiments) > 2 else 'Controlled Experiment C: In-medias-res hook variant'}

=================================================="""
        return report

    def generate_weekly_strategy_update(self, db: Session) -> str:
        """Generates comprehensive weekly strategy report comparing trends and growth."""
        now = datetime.utcnow()
        patterns = db.query(ContentPattern).all()
        categories = [p for p in patterns if p.pattern_type == "category"]
        hooks = [p for p in patterns if p.pattern_type == "hook_archetype"]
        durations = [p for p in patterns if p.pattern_type == "duration_bracket"]

        categories.sort(key=lambda x: x.composite_effectiveness_score, reverse=True)
        hooks.sort(key=lambda x: x.composite_effectiveness_score, reverse=True)
        durations.sort(key=lambda x: x.composite_effectiveness_score, reverse=True)

        report = f"""# Weekly YouTube Shorts Strategic Intelligence Update
Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}

## 1. Category Retention & Engagement Hierarchy
"""
        for cat in categories:
            report += f"- **{cat.pattern_key}**: Score `{cat.composite_effectiveness_score:.1f}` | APV `{cat.avg_percentage_viewed:.1f}%` | Sample Size: `{cat.sample_size}` [{cat.confidence}]\n"

        report += "\n## 2. Hook Archetype Effectiveness\n"
        for h in hooks:
            report += f"- **{h.pattern_key}**: Score `{h.composite_effectiveness_score:.1f}` | APV `{h.avg_percentage_viewed:.1f}%` | Confidence: `{h.confidence}`\n"

        report += "\n## 3. Video Length & Pacing Sweet Spot\n"
        for d in durations:
            report += f"- **{d.pattern_key}**: Score `{d.composite_effectiveness_score:.1f}` | APV `{d.avg_percentage_viewed:.1f}%`\n"

        report += "\n## 4. Active Allocation Policy (60/30/10 Rule)\n"
        report += "- **60% Proven**: Prioritize top category `" + (categories[0].pattern_key if categories else "Unusual Wars") + "` with `" + (hooks[0].pattern_key if hooks else "High-Stakes Conflict") + "` hooks.\n"
        report += "- **30% Variations**: Test single-variable modifications across secondary categories.\n"
        report += "- **10% Exploration**: Probe new unproven historical oddities.\n"
        return report
