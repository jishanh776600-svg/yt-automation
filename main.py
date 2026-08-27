"""
Main Pipeline Orchestrator & CLI Entrypoint.
Coordinates autonomous $0-cost YouTube Shorts creation, QA, publishing, and dashboard.
"""
import sys
import uuid
import time
import logging
import argparse
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

# Setup Project Paths
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import TEST_MODE, RENDERS_DIR
from config.constants import JobState
from core.database import init_db, SessionLocal
from core.models import Job, Topic
from core.state_machine import StateMachine
from engines.topic_discovery import TopicDiscoveryEngine
from engines.research_engine import ResearchEngine
from engines.script_engine import ScriptEngine
from engines.storyboard_engine import StoryboardEngine
from engines.asset_fetcher import AssetFetcher
from engines.tts_engine import TTSEngine
from engines.caption_engine import CaptionEngine
from engines.audio_mixer import AudioMixer
from engines.render_engine import RenderEngine
from engines.qa_engine import QAEngine
from engines.seo_engine import SEOEngine
from engines.upload_engine import UploadEngine
from engines.analytics_engine import AnalyticsEngine

# Setup UTF-8 Encoding on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("HistoriaPipeline")
console = Console(force_terminal=False)


class ShortsPipeline:
    """End-to-end production orchestrator."""

    def __init__(self):
        init_db()
        self.topic_engine = TopicDiscoveryEngine()
        self.research_engine = ResearchEngine()
        self.script_engine = ScriptEngine()
        self.storyboard_engine = StoryboardEngine()
        self.asset_fetcher = AssetFetcher()
        self.tts_engine = TTSEngine()
        self.caption_engine = CaptionEngine()
        self.audio_mixer = AudioMixer()
        self.render_engine = RenderEngine()
        self.qa_engine = QAEngine()
        self.seo_engine = SEOEngine()
        self.upload_engine = UploadEngine()
        self.analytics_engine = AnalyticsEngine()

    def run_single_job(self, topic: Optional[Topic] = None) -> bool:
        """Executes full automated pipeline for one historical Short."""
        db = SessionLocal()
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = Job(id=job_id, state=JobState.QUEUED.value)
        db.add(job)
        db.commit()

        console.print(Panel.fit(f"[bold cyan]Starting Production Pipeline for Job {job_id}[/bold cyan]\nTarget: 1080x1920 9:16 Vertical (~23 sec) | Cost: $0.00", border_style="cyan"))

        # 0. CHECK DAILY PUBLISHING LIMIT (EXACTLY MAX 3 SHORTS/DAY)
        from datetime import datetime, timezone
        from core.models import UploadRecord
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = db.query(UploadRecord).filter(
            UploadRecord.published_at >= today_start.replace(tzinfo=None),
            UploadRecord.status == "PUBLISHED"
        ).count()

        # Check live YouTube Data API directly for true cloud-to-local synchronization
        try:
            yt_data, _ = self.analytics_engine.collector.get_youtube_clients()
            if yt_data:
                res = yt_data.search().list(
                    part="snippet",
                    forMine=True,
                    type="video",
                    publishedAfter=today_start.isoformat(),
                    maxResults=10
                ).execute()
                live_count = len(res.get("items", []))
                published_today = max(published_today, live_count)
        except Exception as e:
            logger.info(f"Live YouTube daily count check notice: {e}")

        if published_today >= 3:
            console.print(f"[bold yellow][!] Daily limit reached ({published_today}/3 Shorts published today). Pausing until next scheduled window.[/bold yellow]")
            logger.info(f"Daily limit of 3 Shorts reached ({published_today}/3).")
            return False

        try:
            # 0. CONTINUOUS LEARNING FEEDBACK LOOP (MEASURE -> ANALYZE -> LEARN)
            try:
                console.print("[cyan][*] Executing Performance Intelligence & Learning Feedback Loop...[/cyan]")
                learning_summary = self.analytics_engine.run_feedback_loop(db)
                console.print(f"[green][+] Learning Engine Active:[/green] {learning_summary['patterns_active']} patterns tracked | Baselines: {learning_summary['channel_baselines']['median_apv']:.1f}% APV median")
            except Exception as e:
                logger.warning(f"Feedback loop non-critical notice: {e}")

            # 1. TOPIC SELECTION / DISCOVERY (CONDITIONED ON LEARNED PATTERNS & 60/30/10 RULE)
            if not topic:
                StateMachine.transition(db, job, JobState.RESEARCHING, "Discovering high-retention topics")
                topics = self.topic_engine.discover_topics(db, limit=1)
                if not topics:
                    StateMachine.flag_needs_review(db, job, "No new unique topics found.")
                    return False
                topic = topics[0]
            else:
                StateMachine.transition(db, job, JobState.RESEARCHING, f"Selected topic: {topic.title}")

            job.topic_id = topic.id
            db.commit()
            console.print(f"[green][+] Topic Selected:[/green] [bold]{topic.title}[/bold] ({topic.category})")

            # 2. RESEARCH & FACT-CHECKING
            StateMachine.transition(db, job, JobState.RESEARCHED, "Conducting factual historical research")
            StateMachine.transition(db, job, JobState.FACT_CHECKING, "Fact-checking claims")
            research_res = self.research_engine.research_topic(db, topic)
            StateMachine.transition(db, job, JobState.FACT_CHECKED, f"Verified {research_res['claims_count']} historical claims")
            console.print(f"[green][+] Fact-Checking Complete:[/green] {research_res['claims_count']} claims verified against historical archives.")

            # 3. SCRIPT GENERATION (Calibrated 21-25s Story Flow)
            StateMachine.transition(db, job, JobState.SCRIPTING, "Writing 21-25s story script")
            script = self.script_engine.generate_script(db, topic)
            StateMachine.transition(db, job, JobState.SCRIPT_READY, f"Script approved ({script.word_count} words)")
            console.print(f"[green][+] Script Ready:[/green] {script.word_count} words (Estimated ~{script.estimated_duration_sec:.1f}s)")

            # 4. VISUAL STORYBOARD PLANNING (4-7 Shots with Motion Coordinates)
            StateMachine.transition(db, job, JobState.VISUAL_PLANNING, "Deconstructing script into shots")
            shots = self.storyboard_engine.create_storyboard(script)
            StateMachine.transition(db, job, JobState.VISUALS_SEARCHING, f"Planned {len(shots)} cinematic shots")

            # 5. ASSET ACQUISITION & SMART VERTICAL CROPPING (Pexels + AI Fallback)
            assets_used = []
            asset_map = {}
            for shot in shots:
                asset = self.asset_fetcher.fetch_asset_for_shot(db, shot)
                assets_used.append(asset)
                asset_map[shot["shot_id"]] = asset

            StateMachine.transition(db, job, JobState.VISUALS_READY, f"Prepared {len(shots)} 1080x1920 vertical visuals")
            console.print(f"[green][+] Visual Assets Prepared:[/green] {len(shots)} vertical 1080x1920 images ready.")

            # 6. VOICE SYNTHESIS (Kokoro-82M ONNX / Apache 2.0)
            StateMachine.transition(db, job, JobState.VOICE_GENERATING, "Generating documentary voiceover")
            voice_asset, audio_duration = self.tts_engine.generate_narration(db, script.full_text)
            assets_used.append(voice_asset)
            StateMachine.transition(db, job, JobState.VOICE_READY, f"Voice synthesized ({audio_duration}s)")
            console.print(f"[green][+] Narration Generated:[/green] {audio_duration:.1f}s via {voice_asset.source} (License: {voice_asset.license})")

            # 7. CAPTION GENERATION (Faster-Whisper)
            console.print("[yellow]Generating word-level synchronized ASS captions...[/yellow]")
            voice_path = Path(voice_asset.local_path)
            ass_path = self.caption_engine.generate_ass_subtitles(voice_path)

            # 8. AUDIO MIXING (Voice + Category-Matched BGM + Ducking -18dB + Normalization)
            music_asset = self.audio_mixer.get_background_music(db, category=topic.category)
            assets_used.append(music_asset)
            master_audio_path = RENDERS_DIR / f"master_{job_id}.aac"
            self.audio_mixer.mix_audio(
                voice_path=voice_path,
                music_path=Path(music_asset.local_path),
                output_path=master_audio_path,
                duration=audio_duration
            )
            StateMachine.transition(db, job, JobState.AUDIO_READY, "Master audio mixed and normalized")
            console.print(f"[green][+] Master Audio Mixed:[/green] Voice + Audible BGM (-18dB) normalized to -14 LUFS")

            # 9. FFMPEG COMPOSITION (1080x1920 MP4)
            StateMachine.transition(db, job, JobState.EDITING, "Compositing 1080x1920 vertical video")
            console.print("[yellow]Rendering Ken Burns motion, visual sequence, and burning captions...[/yellow]")
            render_output = self.render_engine.assemble_short(
                db=db,
                job_id=job_id,
                shots_data=shots,
                asset_map=asset_map,
                master_audio_path=master_audio_path,
                ass_subtitle_path=ass_path
            )

            # 10. QUALITY CONTROL (QA)
            StateMachine.transition(db, job, JobState.QA, "Running automated QA verification")
            passed_qa, qa_report = self.qa_engine.run_qa(db, job, render_output, assets_used)

            if not passed_qa:
                StateMachine.flag_needs_review(db, job, f"QA failed: {qa_report.failure_reasons}")
                console.print(f"[bold red][x] QA Failed:[/bold red] {qa_report.failure_reasons}")
                return False

            console.print(f"[bold green][+] QA Passed Successfully![/bold green] (1080x1920 | {render_output.duration_sec:.1f}s | Codec: H.264/AAC | BGM Verified)")

            # 11. SEO & METADATA
            metadata = self.seo_engine.generate_metadata(topic, script)
            console.print(f"[cyan]SEO Title:[/cyan] [bold]{metadata['title']}[/bold]")

            # 12. YOUTUBE UPLOAD & VERIFY (Strictly PUBLIC)
            StateMachine.transition(db, job, JobState.READY_TO_UPLOAD, "Ready for publishing")
            StateMachine.transition(db, job, JobState.UPLOADING, "Uploading to YouTube (Visibility: PUBLIC)")
            upload_rec = self.upload_engine.upload_short(db, job, render_output, metadata, privacy_status="public")

            StateMachine.transition(db, job, JobState.PUBLISHED, f"Published Short ID: {upload_rec.youtube_video_id}")
            console.print(Panel.fit(f"[bold green][+] Production Cycle Complete![/bold green]\nOutput Video: {render_output.video_path}\nYouTube Status: {upload_rec.status} ({upload_rec.youtube_video_id})\nVisibility: PUBLIC (Verified)", border_style="green"))
            return True

        except Exception as e:
            logger.exception(f"Pipeline error on job {job_id}: {e}")
            StateMachine.flag_needs_review(db, job, f"Unexpected pipeline exception: {str(e)}")
            return False
        finally:
            db.close()


def start_dashboard():
    """Starts FastAPI monitoring dashboard."""
    import uvicorn
    from dashboard.app import app
    console.print("[bold cyan]Starting Live Dashboard on http://127.0.0.1:8000[/bold cyan]")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="Automated $0-Cost History Shorts Channel Pipeline")
    parser.add_argument("--run-once", action="store_true", help="Run a single production cycle")
    parser.add_argument("--test", action="store_true", help="Run full pipeline in test mode (safe, local validation)")
    parser.add_argument("--dashboard", action="store_true", help="Launch FastAPI web dashboard")
    parser.add_argument("--daemon", action="store_true", help="Run continuous scheduler (Strictly 3 Shorts/day)")
    args = parser.parse_args()

    pipeline = ShortsPipeline()

    if args.dashboard:
        start_dashboard()
    elif args.run_once or args.test:
        pipeline.run_single_job()
    elif args.daemon:
        import schedule
        console.print("[bold green]Starting automated daemon scheduler (Strictly 3 Shorts/day at 10:00, 15:00, 20:00 UTC)...[/bold green]")
        schedule.every().day.at("10:00").do(pipeline.run_single_job)
        schedule.every().day.at("15:00").do(pipeline.run_single_job)
        schedule.every().day.at("20:00").do(pipeline.run_single_job)
        pipeline.run_single_job()  # Run initial cycle
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
