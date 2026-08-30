"""
Main Pipeline Orchestrator & CLI Entrypoint.
Coordinates autonomous $0-cost YouTube Shorts creation, batch production,
Google Drive Vault storage, scheduled publishing, QA, and learning feedback.
"""
import os
import sys
import uuid
import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

# Setup Project Paths
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import (
    TEST_MODE, RENDERS_DIR,
    MAX_BATCH_PRODUCTION_CEILING,
    MAX_PRODUCTION_ATTEMPTS_CEILING,
    MAX_BUFFER_RESERVE_CEILING
)
from config.constants import JobState, DAILY_SHORTS_LIMIT
from sqlalchemy.orm import Session
from core.database import init_db, SessionLocal
from core.models import Job, Topic, RenderOutput, UploadRecord, ScriptRecord
from core.state_machine import StateMachine
from core.lock import ProcessLock, ProcessLockError
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
from engines.scheduler_engine import PublicationScheduler
from engines.analytics_engine import AnalyticsEngine
from engines.drive_engine import DriveVaultEngine
from engines.experiment_manager import ExperimentManager
from core.recovery_manager import RecoveryManager

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
    """End-to-end production and publishing orchestrator."""

    def __init__(self, voice: Optional[str] = None):
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
        self.scheduler = PublicationScheduler()
        self.analytics_engine = AnalyticsEngine()
        self.drive_engine = DriveVaultEngine()
        self.experiment_manager = ExperimentManager()
        self.recovery_manager = RecoveryManager(self.drive_engine, self.upload_engine)

        from engines.tts_engine import get_active_voice
        db = SessionLocal()
        try:
            self.run_voice = voice or os.getenv("KOKORO_VOICE") or get_active_voice(db)
        finally:
            db.close()
        logger.info(f"[PIPELINE_INIT] Run-scoped authoritative voice captured: '{self.run_voice}'")

    def _render_and_qa_job(self, db, job: Job, topic: Topic, force: bool = False) -> Tuple[Optional[RenderOutput], Optional[Dict[str, Any]]]:
        """Internal helper: Executes research -> script -> visuals -> voice -> audio -> render -> QA -> SEO."""
        job.topic_id = topic.id
        db.commit()
        console.print(f"[green][+] Topic Selected:[/green] [bold]{topic.title}[/bold] ({topic.category})")

        # 0. STRATEGY SELECTION & EXPERIMENT TRACKING
        strategy = self.experiment_manager.select_strategy(db, topic)
        self.experiment_manager.create_experiment(db, job_id=job.id, topic_id=topic.id, strategy=strategy)
        logger.info(f"Assigned Strategy for Job {job.id[:8]}: Hook={strategy['hook_archetype']}, Target={strategy['duration_target']}, Mode={strategy['selection_mode']}")

        # 1. RESEARCH & FACT-CHECKING
        StateMachine.transition(db, job, JobState.RESEARCHED, "Conducting factual historical research")
        StateMachine.transition(db, job, JobState.FACT_CHECKING, "Fact-checking claims")
        research_res = self.research_engine.research_topic(db, topic)
        StateMachine.transition(db, job, JobState.FACT_CHECKED, f"Verified {research_res['claims_count']} historical claims")
        console.print(f"[green][+] Fact-Checking Complete:[/green] {research_res['claims_count']} claims verified against historical archives.")

        # 2. SCRIPT GENERATION (Calibrated 21-25s Story Flow with Multi-Stage Critic & Strategy)
        StateMachine.transition(db, job, JobState.SCRIPTING, f"Writing script with {strategy.get('hook_archetype')} hook & {strategy.get('duration_target')} duration")
        script = self.script_engine.generate_script(db, topic, research_data=research_res, strategy=strategy)
        StateMachine.transition(db, job, JobState.SCRIPT_READY, f"Script approved ({script.word_count} words)")
        console.print(f"[green][+] Script Ready:[/green] {script.word_count} words (Estimated ~{script.estimated_duration_sec:.1f}s)")

        # 3. VISUAL STORYBOARD PLANNING
        StateMachine.transition(db, job, JobState.VISUAL_PLANNING, "Deconstructing script into shots")
        shots = self.storyboard_engine.create_storyboard(script)
        StateMachine.transition(db, job, JobState.VISUALS_SEARCHING, f"Planned {len(shots)} cinematic shots")

        # 4. ASSET ACQUISITION (Pexels + Anti-Duplication)
        assets_used = []
        asset_map = {}
        for shot in shots:
            asset = self.asset_fetcher.fetch_asset_for_shot(db, shot)
            assets_used.append(asset)
            asset_map[shot["shot_id"]] = asset

        StateMachine.transition(db, job, JobState.VISUALS_READY, f"Prepared {len(shots)} 1080x1920 vertical visuals")

        # 5. VOICE SYNTHESIS (Kokoro-v1.0 ONNX)
        StateMachine.transition(db, job, JobState.VOICE_GENERATING, f"Generating documentary voiceover ({self.run_voice})")
        voice_asset, audio_duration = self.tts_engine.generate_narration(db, script.full_text, voice=self.run_voice)
        assets_used.append(voice_asset)
        StateMachine.transition(db, job, JobState.VOICE_READY, f"Voice synthesized ({audio_duration}s, voice={self.run_voice})")
        console.print(f"[green][+] Narration Generated:[/green] {audio_duration:.1f}s via {voice_asset.source} [cyan]({self.run_voice})[/cyan]")

        # 6. CAPTION GENERATION (Faster-Whisper)
        voice_path = Path(voice_asset.local_path)
        ass_path = self.caption_engine.generate_ass_subtitles(voice_path)

        # 7. AUDIO MIXING (Voice + Intelligent BGM at -13dB & -14 LUFS)
        music_asset = self.audio_mixer.get_background_music(
            db=db,
            category=topic.category,
            title=topic.title,
            summary=topic.summary,
            script_text=script.full_text
        )
        assets_used.append(music_asset)
        master_audio_path = RENDERS_DIR / f"master_{job.id}.aac"
        master_audio_path, bgm_only_path = self.audio_mixer.mix_audio(
            voice_path=voice_path,
            music_path=Path(music_asset.local_path),
            output_path=master_audio_path,
            duration=audio_duration,
            job_id=job.id
        )
        StateMachine.transition(db, job, JobState.AUDIO_READY, "Master audio mixed with audible BGM (-13dB) and normalized")

        # 8. FFMPEG COMPOSITION (1080x1920 MP4)
        StateMachine.transition(db, job, JobState.EDITING, "Compositing 1080x1920 vertical video")
        render_output = self.render_engine.assemble_short(
            db=db,
            job_id=job.id,
            shots_data=shots,
            asset_map=asset_map,
            master_audio_path=master_audio_path,
            ass_subtitle_path=ass_path,
            bgm_mood=strategy.get("bgm_mood"),
            motion_style=strategy.get("motion_style", "DYNAMIC_ZOOM_PAN")
        )

        # 9. QUALITY CONTROL (QA) WITH AUTOMATED BGM FAIL-SAFE REPAIR LOOP
        StateMachine.transition(db, job, JobState.QA, "Running automated QA & BGM acoustic verification")
        passed_qa, qa_report = self.qa_engine.run_qa(
            db=db,
            job=job,
            render=render_output,
            assets_used=assets_used,
            bgm_reference_path=bgm_only_path,
            force=force
        )

        # Auto-Repair Discrepancy Pass
        if not passed_qa and qa_report.failure_reasons and ("Audio" in qa_report.failure_reasons or "BGM" in qa_report.failure_reasons or "loudness" in qa_report.failure_reasons):
            console.print(f"[yellow][!] Audio QA discrepancy detected ({qa_report.failure_reasons}). Executing automatic repair pass...[/yellow]")
            try:
                repair_music = Path(self.audio_mixer.music_dir / "No copyright Best Historical.wav")
                master_audio_path, bgm_only_path = self.audio_mixer.mix_audio(
                    voice_path=voice_path,
                    music_path=repair_music,
                    output_path=master_audio_path,
                    duration=audio_duration,
                    bgm_volume_db=-13.0,
                    job_id=job.id
                )
                render_output = self.render_engine.assemble_short(
                    db=db,
                    job_id=job.id,
                    shots_data=shots,
                    asset_map=asset_map,
                    master_audio_path=master_audio_path,
                    ass_subtitle_path=ass_path,
                    bgm_mood="Historical / Serious Documentary / War / Disaster / Historic Riots & Oddities",
                    motion_style="DYNAMIC_ZOOM_PAN"
                )
                passed_qa, qa_report = self.qa_engine.run_qa(
                    db=db,
                    job=job,
                    render=render_output,
                    assets_used=assets_used,
                    bgm_reference_path=bgm_only_path,
                    force=force
                )
            except Exception as repair_err:
                logger.warning(f"Auto-repair attempt warning: {repair_err}")

        if not passed_qa:
            self.experiment_manager.update_experiment_status(db, job.id, "FAILED", failure_reason=str(qa_report.failure_reasons if qa_report else "QA Failed"))
            StateMachine.flag_needs_review(db, job, f"QA failed: {qa_report.failure_reasons}")
            console.print(f"[bold red][x] QA Failed (Upload Aborted by Fail-Safe):[/bold red] {qa_report.failure_reasons}")
            return None, None

        self.experiment_manager.update_experiment_status(db, job.id, "READY")
        console.print(f"[bold green][+] QA Passed Successfully![/bold green] (1080x1920 | {render_output.duration_sec:.1f}s | Codec: H.264/AAC | BGM Verified)")

        # 10. SEO METADATA
        metadata = self.seo_engine.generate_metadata(topic, script)
        console.print(f"[cyan]SEO Title:[/cyan] [bold]{metadata['title']}[/bold]")

        return render_output, metadata

    def produce_single_to_vault(self, topic: Optional[Topic] = None) -> Optional[Job]:
        """
        PRODUCER MODE: Generates a single Short, verifies QA, attaches metadata properties,
        and deposits the final MP4 into Google Drive vault 'YouTube_Shorts_Vault/01_READY'.
        Does NOT upload to YouTube or count against daily publishing limit.
        """
        db = SessionLocal()
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = Job(id=job_id, state=JobState.QUEUED.value)
        db.add(job)
        db.commit()

        console.print(Panel.fit(f"[bold cyan]Starting Batch Producer for Job {job_id}[/bold cyan]\nTarget: Deposit in Google Drive Vault (01_READY) | Cost: $0.00", border_style="cyan"))

        try:
            # 1. TOPIC SELECTION
            if not topic:
                StateMachine.transition(db, job, JobState.RESEARCHING, "Discovering high-retention topics")
                topics = self.topic_engine.discover_topics(db, limit=1)
                if not topics:
                    StateMachine.flag_needs_review(db, job, "No new unique topics found.")
                    return None
                topic = topics[0]
            else:
                StateMachine.transition(db, job, JobState.RESEARCHING, f"Selected topic: {topic.title}")

            # 2. RENDER & QA
            render_output, metadata = self._render_and_qa_job(db, job, topic, force=True)
            if not render_output or not metadata:
                logger.error(f"Production for job {job_id} failed during render/QA phase.")
                return None

            # 3. UPLOAD TO GOOGLE DRIVE VAULT (01_READY)
            local_video_path = Path(render_output.video_path)
            # Compact key-value properties (max 124 bytes per pair per Google Drive API spec)
            metadata_props = {
                "job_id": str(job.id)[:60],
                "topic_id": str(topic.id)[:60],
                "title": str(metadata.get("title", ""))[:100],
                "tags": ",".join(metadata.get("tags", []))[:100]
            }

            full_description = str(metadata.get("description", ""))

            console.print(f"[yellow][*] Depositing verified MP4 into Google Drive Vault '01_READY'...[/yellow]")
            drive_file = self.drive_engine.upload_video_to_vault(
                local_path=local_video_path,
                target_folder="01_READY",
                description=full_description,
                metadata_properties=metadata_props
            )

            # Persist Drive identifier in database
            drive_file_id = drive_file.get("id")
            render_output.video_path = f"drive://{drive_file_id}"
            db.commit()

            StateMachine.transition(db, job, JobState.READY_TO_UPLOAD, f"Deposited in Drive Vault 01_READY (Drive ID: {drive_file_id})")
            console.print(Panel.fit(
                f"[bold green][+] Producer Success: Video Deposited in Google Drive Vault![/bold green]\n"
                f"Topic: [bold]{topic.title}[/bold]\n"
                f"Drive Vault Location: [bold cyan]YouTube_Shorts_Vault/01_READY[/bold cyan]\n"
                f"Drive File ID: [bold yellow]{drive_file_id}[/bold yellow]\n"
                f"Status: [bold green]READY_TO_UPLOAD[/bold green] (Awaiting Scheduled Publisher)",
                border_style="green"
            ))
            return job

        except Exception as e:
            logger.exception(f"Producer error on job {job_id}: {e}")
            StateMachine.flag_needs_review(db, job, f"Producer exception: {str(e)}")
            if "QuotaExhausted" in type(e).__name__ or "generaterequestsperday" in str(e).lower() or "quota exhausted" in str(e).lower():
                raise e
            return None
        finally:
            db.close()

    def _write_production_summary(self, summary: Dict[str, Any]) -> None:
        """Persists machine-readable outcome summary for GitHub Actions and dashboard."""
        try:
            summary_path = PROJECT_ROOT / "data" / "production_summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
            console.print(f"[bold cyan][PRODUCTION_SUMMARY][/bold cyan] {json.dumps(summary)}")
        except Exception as e:
            logger.warning(f"Could not persist production summary: {e}")

    def produce_batch(self, count: int = 3) -> Tuple[int, Dict[str, Any]]:
        """
        BATCH PRODUCER: Generates multiple complete YouTube Shorts sequentially into Google Drive Vault.
        Acquires process lock, validates production quota, generates assets, renders, QAs,
        and uploads directly to Google Drive '01_READY' folder.
        """
        lock = ProcessLock(name="production", command_name="produce-batch")
        if not lock.acquire():
            info = lock.get_lock_info()
            owner_pid = info.get("pid") if info else "unknown"
            cmd = info.get("command") if info else "unknown"
            console.print(f"[bold yellow][!] Production lock currently held by PID {owner_pid} ('{cmd}'). Batch producer exiting safely.[/bold yellow]")
            return 0, {"outcome": "BLOCKED", "block_reason": "LOCK_HELD", "produced_count": 0}

        try:
            # Enforce hard batch ceiling
            effective_count = min(max(1, count), MAX_BATCH_PRODUCTION_CEILING)
            if effective_count < count:
                console.print(f"[bold yellow][!] Requested count ({count}) exceeds hard safety ceiling ({MAX_BATCH_PRODUCTION_CEILING}). Clamped to {effective_count}.[/bold yellow]")

            console.print(Panel.fit(f"[bold magenta]=== Starting Batch Production ({effective_count} Shorts | Safety Ceiling: {MAX_BATCH_PRODUCTION_CEILING}) ===[/bold magenta]", border_style="magenta"))

            initial_stock = self.drive_engine.get_ready_stock_count()
            success_count = 0
            total_attempts = 0
            consecutive_failures = 0
            block_reason = None

            while success_count < effective_count and total_attempts < MAX_PRODUCTION_ATTEMPTS_CEILING:
                total_attempts += 1
                console.print(f"\n[bold cyan]>>> Generating Batch Item {success_count + 1}/{effective_count} (Attempt {total_attempts}/{MAX_PRODUCTION_ATTEMPTS_CEILING}) <<<[/bold cyan]")
                try:
                    job = self.produce_single_to_vault()
                    if job:
                        success_count += 1
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            block_reason = "CONSECUTIVE_FAILURES"
                            logger.error("[BATCH] 3 consecutive single production failures encountered. Halting safely.")
                            break
                except Exception as fatal_e:
                    if "QuotaExhausted" in type(fatal_e).__name__ or "quota" in str(fatal_e).lower() or "429" in str(fatal_e):
                        block_reason = "ALL_GEMINI_PROVIDERS_EXHAUSTED"
                        logger.error(f"[BATCH] Fatal Gemini quota exhaustion detected: {fatal_e}. Halting batch production immediately.")
                        break
                    raise fatal_e
                time.sleep(2)

            if total_attempts >= MAX_PRODUCTION_ATTEMPTS_CEILING and success_count < effective_count:
                logger.warning(f"Batch production reached maximum attempt ceiling ({MAX_PRODUCTION_ATTEMPTS_CEILING}). Halting safely.")
                if not block_reason:
                    block_reason = "ATTEMPT_CEILING_REACHED"

            final_stock = self.drive_engine.get_ready_stock_count()
            
            if success_count >= effective_count:
                outcome = "SUCCEEDED"
            elif success_count > 0:
                outcome = "PARTIAL"
            elif block_reason:
                outcome = "BLOCKED"
            else:
                outcome = "FAILED"

            summary = {
                "action": "PRODUCE_BATCH",
                "outcome": outcome,
                "block_reason": block_reason,
                "requested_count": effective_count,
                "produced_count": success_count,
                "initial_stock": initial_stock,
                "final_stock": final_stock,
                "voice": self.run_voice,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            self._write_production_summary(summary)

            console.print(Panel.fit(
                f"[bold green]=== Batch Production Complete ===[/bold green]\n"
                f"Outcome: [bold]{outcome}[/bold] (Reason: {block_reason or 'None'})\n"
                f"Successfully Produced: [bold]{success_count}/{effective_count}[/bold] (Total Attempts: {total_attempts})\n"
                f"Total Ready Stock in Drive (01_READY): [bold cyan]{final_stock} Shorts[/bold cyan]",
                border_style="green" if outcome == "SUCCEEDED" else ("yellow" if outcome == "PARTIAL" else "red")
            ))
            return success_count, summary
        finally:
            lock.release()

    def maintain_buffer(self, target_stock: int = 12) -> Tuple[int, Dict[str, Any]]:
        """
        BUFFER MANAGER: Checks current ready stock in Drive '01_READY'.
        If stock < target_stock, dynamically calculates deficit per iteration and generates
        the exact number needed to replenish without assuming batch completion.
        If stock >= target_stock, exits cleanly with zero unnecessary production.
        """
        clamped_target = min(max(1, target_stock), MAX_BUFFER_RESERVE_CEILING)
        if clamped_target < target_stock:
            console.print(f"[bold yellow][!] Target reserve ({target_stock}) exceeds max capacity ceiling ({MAX_BUFFER_RESERVE_CEILING}). Clamped to {clamped_target}.[/bold yellow]")

        console.print(Panel.fit(f"[bold cyan]Auditing Reserve Buffer (Target: {clamped_target} Shorts)[/bold cyan]", border_style="cyan"))
        
        lock = ProcessLock(name="production", command_name="maintain-buffer")
        try:
            lock.acquire()
        except ProcessLockError as e:
            logger.warning(f"Production lock already held: {e}")
            console.print(f"[bold yellow][!] Production lock active: {e}[/bold yellow]")
            return 0, {"outcome": "BLOCKED", "block_reason": "LOCK_HELD", "produced_count": 0}

        initial_stock = self.drive_engine.get_ready_stock_count()
        initial_needed = max(0, clamped_target - initial_stock)
        produced_count = 0
        total_attempts = 0
        consecutive_failures = 0
        block_reason = None

        try:
            while total_attempts < MAX_PRODUCTION_ATTEMPTS_CEILING:
                current_stock = self.drive_engine.get_ready_stock_count()
                needed = max(0, clamped_target - current_stock)

                if needed == 0:
                    console.print(Panel.fit(
                        f"[bold green][+] Reserve Buffer Healthy & Fully Stocked![/bold green]\n"
                        f"Current Ready Stock in 01_READY: [bold cyan]{current_stock} Shorts[/bold cyan]\n"
                        f"Target Reserve: [bold]{clamped_target} Shorts[/bold]\n"
                        f"Produced This Session: [bold]{produced_count} Shorts[/bold]",
                        border_style="green"
                     ))
                    break

                if produced_count >= MAX_BATCH_PRODUCTION_CEILING:
                    logger.warning(f"Batch production reached session limit ({MAX_BATCH_PRODUCTION_CEILING}). Halting safely.")
                    if not block_reason:
                        block_reason = "SESSION_LIMIT_REACHED"
                    break

                total_attempts += 1
                console.print(f"\n[bold yellow][*] Reserve Deficit: {needed} Shorts remaining (Current: {current_stock}/{clamped_target}). Producing next Short (Attempt {total_attempts})...[/bold yellow]")
                try:
                    job = self.produce_single_to_vault()
                    if job:
                        produced_count += 1
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        if consecutive_failures >= 3:
                            block_reason = "CONSECUTIVE_FAILURES"
                            logger.error("[BUFFER] 3 consecutive production failures encountered. Halting buffer maintenance safely.")
                            break
                except Exception as fatal_e:
                    if "QuotaExhausted" in type(fatal_e).__name__ or "quota" in str(fatal_e).lower() or "429" in str(fatal_e):
                        block_reason = "ALL_GEMINI_PROVIDERS_EXHAUSTED"
                        logger.error(f"[BUFFER] Fatal Gemini quota exhaustion detected: {fatal_e}. Halting buffer maintenance immediately.")
                        break
                    raise fatal_e
                time.sleep(2)

            final_stock = self.drive_engine.get_ready_stock_count()
            
            if initial_needed == 0 or produced_count >= initial_needed or final_stock >= clamped_target:
                outcome = "SUCCEEDED"
            elif produced_count > 0:
                outcome = "PARTIAL"
            elif block_reason:
                outcome = "BLOCKED"
            else:
                outcome = "FAILED"

            summary = {
                "action": "MAINTAIN_BUFFER",
                "outcome": outcome,
                "block_reason": block_reason,
                "requested_deficit": initial_needed,
                "produced_count": produced_count,
                "initial_stock": initial_stock,
                "final_stock": final_stock,
                "target_stock": clamped_target,
                "voice": self.run_voice,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            self._write_production_summary(summary)

            console.print(Panel.fit(
                f"[bold green]=== Buffer Maintenance Complete ===[/bold green]\n"
                f"Outcome: [bold]{outcome}[/bold] (Reason: {block_reason or 'None'})\n"
                f"Produced: [bold]{produced_count}/{initial_needed}[/bold] (Total Attempts: {total_attempts})\n"
                f"Vault Reserve: [bold cyan]{final_stock}/{clamped_target} Shorts[/bold cyan]",
                border_style="green" if outcome == "SUCCEEDED" else ("yellow" if outcome == "PARTIAL" else "red")
            ))
            return produced_count, summary
        finally:
            lock.release()

    def _schedule_single_drive_file(
        self,
        db: Session,
        target_file: Dict[str, Any],
        scheduled_slot: datetime,
        current_folder: str = "01_READY"
    ) -> Optional[UploadRecord]:
        """Atomically claims, downloads, and schedules a single Drive video on YouTube."""
        file_id = target_file["id"]
        props = target_file.get("properties", {}) or {}

        # Atomically move 01_READY -> 02_PROCESSING if not already there
        if current_folder != "02_PROCESSING":
            self.drive_engine.move_file_in_vault(file_id, from_folder=current_folder, to_folder="02_PROCESSING")

        # Robust Job ID Extraction: Properties -> Filename Regex -> Fallback
        import re
        extracted_job_id = props.get("job_id")
        if not extracted_job_id:
            m = re.search(r"short_(job_[a-f0-9]+)", target_file.get("name", ""))
            if m:
                extracted_job_id = m.group(1)
        job_id = extracted_job_id or f"job_vault_{file_id[:8]}"
        title = props.get("title") or target_file.get("name", "Documentary Short").replace(".mp4", "")
        description = props.get("description") or f"Historical Short: {title}\n\n#history #shorts #documentary"
        tags = [t.strip() for t in props.get("tags", "history,shorts,documentary,facts").split(",") if t.strip()]

        metadata = {
            "title": title,
            "description": description,
            "tags": tags
        }

        temp_download_path = RENDERS_DIR / f"temp_publish_{file_id}.mp4"
        try:
            console.print(f"[yellow][*] Downloading Short '{title}' from Google Drive Vault...[/yellow]")
            self.drive_engine.download_video_from_vault(file_id, temp_download_path)

            job = db.query(Job).filter_by(id=job_id).first()
            if not job:
                job = Job(id=job_id, state=JobState.READY_TO_UPLOAD.value)
                db.add(job)
                db.commit()

            render_output = db.query(RenderOutput).filter_by(job_id=job.id).first()
            if not render_output:
                render_output = RenderOutput(
                    id=f"rnd_{uuid.uuid4().hex[:10]}",
                    job_id=job.id,
                    video_path=str(temp_download_path),
                    duration_sec=23.0,
                    file_size_bytes=temp_download_path.stat().st_size if temp_download_path.exists() else 1024000
                )
                db.add(render_output)
                db.commit()
            else:
                render_output.video_path = str(temp_download_path)
                db.commit()

            if TEST_MODE:
                desktop_candidate = Path.home() / "Desktop"
                output_dir = desktop_candidate if desktop_candidate.exists() else (PROJECT_ROOT / "data" / "renders")
                dest_video = output_dir / f"VERIFIED_VAULT_PUBLISHED_{file_id[:8]}.mp4"
                import shutil
                shutil.copy2(temp_download_path, dest_video)

                upload_rec = self.upload_engine.schedule_short(
                    db=db,
                    job=job,
                    render=render_output,
                    metadata=metadata,
                    scheduled_publish_at=scheduled_slot
                )
                self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
                StateMachine.transition(db, job, JobState.PUBLISHED, f"TEST_MODE verified: Scheduled for {scheduled_slot.isoformat()}Z")
                console.print(Panel.fit(
                    f"[bold green][+] Test Scheduled Publisher Success![/bold green]\n"
                    f"Title: [bold]{title}[/bold]\n"
                    f"Assigned Slot: [bold cyan]{scheduled_slot.strftime('%Y-%m-%d %H:%M')} UTC[/bold cyan]\n"
                    f"Drive File ID: {file_id}\n"
                    f"Moved To: [bold cyan]YouTube_Shorts_Vault/03_PUBLISHED[/bold cyan]\n"
                    f"YouTube Upload: [bold cyan]BYPASSED (TEST_MODE=true)[/bold cyan]",
                    border_style="green"
                ))
                return upload_rec

            # Production YouTube scheduled upload
            upload_rec = self.upload_engine.schedule_short(
                db=db,
                job=job,
                render=render_output,
                metadata=metadata,
                scheduled_publish_at=scheduled_slot
            )

            try:
                self.drive_engine.set_file_properties(file_id, {
                    "job_id": job.id,
                    "youtube_video_id": upload_rec.youtube_video_id,
                    "upload_status": "SCHEDULED",
                    "scheduled_publish_at": scheduled_slot.isoformat() + "Z"
                })
            except Exception as prop_err:
                logger.warning(f"Could not attach Drive scheduling properties: {prop_err}")

            self.experiment_manager.link_experiment_to_upload(
                db,
                job_id=job.id,
                upload_id=upload_rec.id,
                youtube_video_id=upload_rec.youtube_video_id
            )

            console.print(Panel.fit(
                f"[bold green][+] True YouTube Scheduled Short Successfully Uploaded & Verified![/bold green]\n"
                f"Title: [bold]{title}[/bold]\n"
                f"YouTube ID: [bold yellow]{upload_rec.youtube_video_id}[/bold yellow]\n"
                f"Assigned UTC Slot: [bold cyan]{scheduled_slot.strftime('%Y-%m-%d %H:%M')} UTC[/bold cyan]\n"
                f"Privacy Status: [bold magenta]PRIVATE (Will auto-release on YouTube)[/bold magenta]\n"
                f"Drive State: [bold cyan]02_PROCESSING (Tracked until public)[/bold cyan]",
                border_style="green"
            ))
            return upload_rec

        except Exception as upload_err:
            logger.error(f"YouTube scheduling failed for Drive file {file_id}: {upload_err}")
            self.experiment_manager.update_experiment_status(db, job.id, "FAILED", failure_reason=f"YouTube scheduling failed: {str(upload_err)}")

            is_permanent_media_err = "UPLOAD_INTEGRITY" in str(upload_err) or "integrity" in str(upload_err).lower()
            if is_permanent_media_err:
                logger.error(f"Quarantining corrupted file {file_id} to 04_FAILED.")
                self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="04_FAILED")
                StateMachine.flag_needs_review(db, job, f"YouTube scheduling failed: {str(upload_err)}")
            else:
                logger.warning(f"Transient upload error for {file_id}. Returning file to 01_READY for subsequent slot retry.")
                self.drive_engine.move_file_in_vault(file_id, from_folder="02_PROCESSING", to_folder="01_READY")
                job.state = JobState.READY_TO_UPLOAD.value
                db.commit()
            return None
        finally:
            if temp_download_path and hasattr(temp_download_path, "unlink"):
                temp_download_path.unlink(missing_ok=True)

    def schedule_ready_buffer(
        self,
        db: Optional[Session] = None,
        max_to_schedule: Optional[int] = None,
        target_file_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        CANONICAL AUTONOMOUS SCHEDULER:
        Calculates remaining daily upload capacity (DAILY_SHORTS_LIMIT - published_today - scheduled_today),
        evaluates available fresh 01_READY inventory, and schedules all eligible videos into consecutive
        upcoming publication slots in ONE atomic operation.
        """
        lock = ProcessLock(name="publisher", command_name="schedule-ready")
        if not lock.acquire():
            info = lock.get_lock_info()
            owner_pid = info.get("pid") if info else "unknown"
            cmd = info.get("command") if info else "unknown"
            console.print(f"[bold yellow][!] Publisher lock currently held by PID {owner_pid} ('{cmd}'). Scheduler halting safely.[/bold yellow]")
            return {"scheduled_count": 0, "status": "LOCK_HELD"}

        close_db = False
        if db is None:
            db = getattr(self, "SessionLocal", SessionLocal)()
            close_db = True

        console.print(Panel.fit("[bold cyan]Starting Autonomous READY Buffer Scheduling[/bold cyan]", border_style="cyan"))

        try:
            # 1. Reconcile prior scheduled uploads (check if any became public on YouTube)
            try:
                reconciled_jobs = self.upload_engine.reconcile_scheduled_uploads(db)
                if reconciled_jobs:
                    console.print(f"[bold green][+] Reconciled {len(reconciled_jobs)} previously scheduled Short(s) to PUBLISHED status.[/bold green]")
                    processing_files = self.drive_engine.list_files_in_folder("02_PROCESSING")
                    for rec_item in reconciled_jobs:
                        for pf in processing_files:
                            props = pf.get("properties", {}) or {}
                            if props.get("job_id") == rec_item["job_id"] or rec_item["job_id"] in pf.get("name", ""):
                                self.drive_engine.move_file_in_vault(pf["id"], from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
            except Exception as rec_err:
                logger.warning(f"Reconciliation check notice: {rec_err}")

            # 2. Run continuous learning feedback loop
            try:
                self.analytics_engine.run_feedback_loop(db)
            except Exception as e:
                logger.warning(f"Analytics feedback notice: {e}")

            # 3. Calculate canonical today boundaries & counts in Asia/Kolkata timezone
            from config.constants import get_business_day_bounds_utc
            today_start, today_end = get_business_day_bounds_utc()
            
            published_count_today = db.query(UploadRecord).filter(
                UploadRecord.status.in_(["PUBLISHED", "SUCCESS"]),
                UploadRecord.published_at >= today_start,
                UploadRecord.published_at < today_end
            ).count()

            now_utc = datetime.utcnow()
            scheduled_count_today = db.query(UploadRecord).filter(
                UploadRecord.status == "SCHEDULED",
                UploadRecord.scheduled_publish_at >= now_utc,
                UploadRecord.scheduled_publish_at < today_end
            ).count()

            total_booked_today = published_count_today + scheduled_count_today
            remaining_capacity = max(0, DAILY_SHORTS_LIMIT - total_booked_today)

            console.print(
                f"[cyan][*] Daily Capacity Audit:[/cyan] "
                f"Published Today: [bold]{published_count_today}[/bold] | "
                f"Scheduled Today: [bold]{scheduled_count_today}[/bold] | "
                f"Remaining Slots: [bold yellow]{remaining_capacity}/{DAILY_SHORTS_LIMIT}[/bold yellow]"
            )

            # 4. Check 02_PROCESSING for any recovered/in-flight items first
            scheduled_results = []
            processing_files = self.drive_engine.list_files_in_folder("02_PROCESSING")
            recovered_candidates = []
            if processing_files:
                for candidate in processing_files:
                    props = candidate.get("properties", {}) or {}
                    cand_job_id = props.get("job_id")
                    existing_upl = db.query(UploadRecord).filter(UploadRecord.job_id == cand_job_id).first() if cand_job_id else None
                    if existing_upl and existing_upl.status == "PUBLISHED":
                        self.drive_engine.move_file_in_vault(candidate["id"], from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
                    elif existing_upl and existing_upl.status == "SCHEDULED":
                        continue
                    else:
                        recovered_candidates.append(candidate)

            # 5. Check 01_READY for fresh unscheduled inventory
            ready_files = self.drive_engine.list_files_in_folder("01_READY")
            import re
            fresh_ready_files = []
            for candidate in ready_files:
                c_props = candidate.get("properties", {}) or {}
                c_job_id = c_props.get("job_id")
                if not c_job_id:
                    m = re.search(r"short_(job_[a-f0-9]+)", candidate.get("name", ""))
                    if m:
                        c_job_id = m.group(1)
                c_title = c_props.get("title") or candidate.get("name", "").replace(".mp4", "")
                existing_upl = db.query(UploadRecord).filter(
                    (UploadRecord.job_id == c_job_id) |
                    (UploadRecord.title.ilike(c_title.strip().lower()))
                ).first() if c_job_id else None

                if existing_upl and existing_upl.status == "PUBLISHED":
                    logger.warning(f"[PRE-CLAIM DEDUP] File {candidate['id']} already PUBLISHED on YouTube. Moving to 03_PUBLISHED.")
                    self.drive_engine.move_file_in_vault(candidate["id"], from_folder="01_READY", to_folder="03_PUBLISHED")
                elif existing_upl and existing_upl.status == "SCHEDULED":
                    logger.warning(f"[PRE-CLAIM DEDUP] File {candidate['id']} already SCHEDULED on YouTube. Moving to 02_PROCESSING.")
                    self.drive_engine.move_file_in_vault(candidate["id"], from_folder="01_READY", to_folder="02_PROCESSING")
                else:
                    fresh_ready_files.append(candidate)

            all_eligible_candidates = recovered_candidates + fresh_ready_files
            if target_file_id:
                all_eligible_candidates = [f for f in all_eligible_candidates if f["id"] == target_file_id]

            # 6. Calculate eligible quota to schedule in this run
            ready_stock_count = len(all_eligible_candidates)
            eligible_to_schedule = min(remaining_capacity, ready_stock_count)
            if max_to_schedule is not None and max_to_schedule > 0:
                eligible_to_schedule = min(eligible_to_schedule, max_to_schedule)

            if eligible_to_schedule <= 0:
                console.print(f"[bold yellow][!] Zero eligible Shorts to schedule (Remaining Capacity: {remaining_capacity}, READY Stock: {ready_stock_count}). Scheduler exiting safely.[/bold yellow]")
                return {
                    "scheduled_count": 0,
                    "scheduled_jobs": [],
                    "published_today": published_count_today,
                    "scheduled_today": scheduled_count_today,
                    "remaining_capacity": remaining_capacity,
                    "ready_stock": ready_stock_count,
                    "status": "NO_ACTION_REQUIRED"
                }

            console.print(f"[bold green][*] Scheduling {eligible_to_schedule} eligible Short(s) into next publication slots...[/bold green]")

            for i in range(eligible_to_schedule):
                cand = all_eligible_candidates[i]
                cand_folder = "02_PROCESSING" if cand in recovered_candidates else "01_READY"
                next_slot = self.scheduler.calculate_next_available_slot(db)
                console.print(f"[cyan][*] Candidate {i+1}/{eligible_to_schedule} allocated Slot:[/cyan] [bold yellow]{next_slot.strftime('%Y-%m-%d %H:%M')} UTC[/bold yellow]")

                upload_rec = self._schedule_single_drive_file(
                    db=db,
                    target_file=cand,
                    scheduled_slot=next_slot,
                    current_folder=cand_folder
                )
                if upload_rec:
                    scheduled_results.append({
                        "job_id": upload_rec.job_id,
                        "youtube_video_id": upload_rec.youtube_video_id,
                        "scheduled_publish_at": upload_rec.scheduled_publish_at.isoformat() + "Z",
                        "title": upload_rec.title
                    })

            return {
                "scheduled_count": len(scheduled_results),
                "scheduled_jobs": scheduled_results,
                "published_today": published_count_today,
                "scheduled_today": scheduled_count_today + len(scheduled_results),
                "remaining_capacity": max(0, remaining_capacity - len(scheduled_results)),
                "ready_stock": max(0, ready_stock_count - len(scheduled_results)),
                "status": "SUCCESS"
            }

        finally:
            if close_db:
                db.close()
            lock.release()

    def publish_next_from_vault(self, force: bool = False, target_file_id: Optional[str] = None) -> bool:
        """Invokes canonical schedule_ready_buffer for a single video."""
        res = self.schedule_ready_buffer(max_to_schedule=1, target_file_id=target_file_id)
        return bool(res.get("scheduled_count", 0) > 0)

    def run_single_job(self, topic: Optional[Topic] = None, force: bool = False) -> bool:
        """
        LEGACY MONOLITHIC / FALLBACK RUNNER:
        Executes single production cycle and uploads immediately.
        """
        lock = ProcessLock(name="production", command_name="run-single-job")
        if not lock.acquire():
            info = lock.get_lock_info()
            owner_pid = info.get("pid") if info else "unknown"
            cmd = info.get("command") if info else "unknown"
            console.print(f"[bold yellow][!] Production lock currently held by PID {owner_pid} ('{cmd}'). Exiting safely.[/bold yellow]")
            return False

        db = SessionLocal()
        job_id = f"job_{uuid.uuid4().hex[:10]}"
        job = Job(id=job_id, state=JobState.QUEUED.value)
        db.add(job)
        db.commit()

        console.print(Panel.fit(f"[bold cyan]Starting Production Pipeline for Job {job_id}[/bold cyan]\nTarget: 1080x1920 9:16 Vertical (~23 sec) | Cost: $0.00", border_style="cyan"))

        # 0. CHECK DAILY PUBLISHING LIMIT
        from datetime import datetime
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        published_today = db.query(UploadRecord).filter(
            UploadRecord.published_at >= today_start,
            UploadRecord.status == "PUBLISHED"
        ).count()

        if published_today >= DAILY_SHORTS_LIMIT and not force:
            console.print(f"[bold yellow][!] Daily limit reached ({published_today}/{DAILY_SHORTS_LIMIT} Shorts published today). Pausing until next scheduled window.[/bold yellow]")
            logger.info(f"Daily limit reached ({published_today}/{DAILY_SHORTS_LIMIT}).")
            db.close()
            lock.release()
            return False

        try:
            # Topic selection
            if not topic:
                StateMachine.transition(db, job, JobState.RESEARCHING, "Discovering high-retention topics")
                topics = self.topic_engine.discover_topics(db, limit=1)
                if not topics:
                    StateMachine.flag_needs_review(db, job, "No new unique topics found.")
                    return False
                topic = topics[0]
            else:
                StateMachine.transition(db, job, JobState.RESEARCHING, f"Selected topic: {topic.title}")

            render_output, metadata = self._render_and_qa_job(db, job, topic, force=force)
            if not render_output or not metadata:
                return False

            import shutil
            if TEST_MODE:
                desktop_candidate = Path.home() / "Desktop"
                output_dir = desktop_candidate if desktop_candidate.exists() else (PROJECT_ROOT / "data" / "renders")
                dest_video = output_dir / "VERIFIED_SHORT_TEST_OUTPUT.mp4"
                shutil.copy2(Path(render_output.video_path), dest_video)
                console.print(Panel.fit(
                    f"[bold green][+] Test Pipeline Complete![/bold green]\n"
                    f"Final Verified MP4 saved to: [bold yellow]{dest_video}[/bold yellow]\n"
                    f"YouTube Upload: [bold cyan]BYPASSED (No publishing occurred)[/bold cyan]",
                    border_style="green"
                ))
                return True

            # PRODUCTION YOUTUBE-SIDE SCHEDULED PUBLISHING
            from engines.scheduler_engine import PublicationScheduler
            scheduler = PublicationScheduler()
            next_slot = scheduler.calculate_next_available_slot(db)

            StateMachine.transition(db, job, JobState.READY_TO_UPLOAD, "Ready for scheduled publishing")
            StateMachine.transition(db, job, JobState.UPLOADING, f"Uploading to YouTube (Scheduled for {next_slot.strftime('%Y-%m-%d %H:%M')} UTC)")
            upload_rec = self.upload_engine.schedule_short(
                db=db,
                job=job,
                render=render_output,
                metadata=metadata,
                scheduled_publish_at=next_slot
            )

            StateMachine.transition(db, job, JobState.SCHEDULED, f"Scheduled on YouTube for {next_slot.isoformat()}Z (ID: {upload_rec.youtube_video_id})")
            console.print(Panel.fit(
                f"[bold green][+] Production Cycle Complete (Scheduled)![/bold green]\n"
                f"Output Video: {render_output.video_path}\n"
                f"YouTube Status: {upload_rec.status} ({upload_rec.youtube_video_id})\n"
                f"Scheduled Release: {next_slot.strftime('%Y-%m-%d %H:%M')} UTC\n"
                f"Visibility: PRIVATE -> AUTO-PUBLIC (Verified)",
                border_style="green"
            ))
            return True

        except Exception as e:
            logger.exception(f"Pipeline error on job {job_id}: {e}")
            StateMachine.flag_needs_review(db, job, f"Unexpected pipeline exception: {str(e)}")
            return False
        finally:
            db.close()
            lock.release()


def start_dashboard():
    """Starts FastAPI monitoring dashboard."""
    import uvicorn
    from dashboard.app import app
    console.print("[bold cyan]Starting Live Dashboard on http://127.0.0.1:8000[/bold cyan]")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


def main():
    parser = argparse.ArgumentParser(description="Automated $0-Cost History Shorts Channel Pipeline")
    parser.add_argument("--health-check", action="store_true", help="Run non-destructive production health check and launch readiness gate")
    parser.add_argument("--self-heal", action="store_true", help="Executes master autonomous self-healing, stale recovery, and vault reconciliation")
    parser.add_argument("--json", action="store_true", help="Output health check or diagnostic results in JSON format")
    parser.add_argument("--maintain-buffer", type=int, nargs="?", const=12, default=0, metavar="TARGET", help="Maintain a reserve of TARGET ready Shorts in Drive 01_READY (default: 12)")
    parser.add_argument("--produce-batch", type=int, default=0, metavar="N", help="Generate N Shorts, verify QA, and deposit in Google Drive 01_READY")
    parser.add_argument("--publish-next", action="store_true", help="Claim next ready Short from Google Drive 01_READY and publish to YouTube")
    parser.add_argument("--schedule-ready", action="store_true", help="Claim and schedule all available READY Shorts up to daily limit")
    parser.add_argument("--file-id", type=str, default=None, help="Target specific Google Drive File ID for publishing")
    parser.add_argument("--run-once", action="store_true", help="Run a single production cycle")
    parser.add_argument("--test", action="store_true", help="Run full pipeline in test mode (safe, local validation)")
    parser.add_argument("--harvest-analytics", action="store_true", help="Harvest performance metrics for eligible published Shorts")
    parser.add_argument("--learn", action="store_true", help="Execute closed-loop learning cycle and update strategy weights")
    parser.add_argument("--force", action="store_true", help="Force cycle even if daily limit is met")
    parser.add_argument("--voice", type=str, default=None, help="Explicit active voice identifier to use for this run (overrides default/DB)")
    parser.add_argument("--dashboard", action="store_true", help="Launch FastAPI web dashboard")
    parser.add_argument("--daemon", action="store_true", help="Run continuous scheduler (Strictly 4 Shorts/day)")
    args = parser.parse_args()

    pipeline = ShortsPipeline(voice=args.voice)

    if args.health_check:
        from engines.health_checker import HealthChecker, HealthStatus, CheckStatus
        checker = HealthChecker()
        result = checker.run_full_audit()

        if getattr(args, "json", False):
            import json
            print(json.dumps(result, indent=2))
        else:
            from rich.table import Table
            table = Table(title="Production Readiness Health Check (Phase 5.4)", border_style="cyan")
            table.add_column("Category", style="bold white", width=22)
            table.add_column("Status", width=10)
            table.add_column("Diagnostics", style="dim white")

            status_colors = {
                CheckStatus.PASS: "[bold green]PASS[/bold green]",
                CheckStatus.WARN: "[bold yellow]WARN[/bold yellow]",
                CheckStatus.FAIL: "[bold red]FAIL[/bold red]"
            }

            for cat, check_res in result["checks"].items():
                cat_display = cat.replace("_", " ").title()
                table.add_row(cat_display, status_colors.get(check_res["status"], check_res["status"]), check_res["message"])

            console.print(table)

            verdict_colors = {
                HealthStatus.READY: ("bold green", "[bold green]SYSTEM READY FOR PRODUCTION[/bold green]"),
                HealthStatus.DEGRADED: ("bold yellow", "[bold yellow]SYSTEM DEGRADED (Operational with Non-Critical Warnings)[/bold yellow]"),
                HealthStatus.NOT_READY: ("bold red", "[bold red]SYSTEM NOT READY (Critical Failures Detected)[/bold red]")
            }
            color, title = verdict_colors.get(result["verdict"], ("bold white", result["verdict"]))
            console.print(Panel.fit(
                f"{title}\n\n"
                f"{result['summary']}\n"
                f"• Passed Checks: [bold green]{len(result['passed_checks'])}[/bold green]\n"
                f"• Warnings: [bold yellow]{len(result['warnings'])}[/bold yellow]\n"
                f"• Critical Failures: [bold red]{len(result['critical_failures'])}[/bold red]",
                border_style=color
            ))
    elif args.self_heal:
        db = SessionLocal()
        try:
            res = pipeline.recovery_manager.run_full_self_healing(db)
            console.print(Panel.fit(
                f"[bold green][+] Master Autonomous Self-Healing Cycle Complete![/bold green]\n"
                f"Stale Jobs Handled: [bold]{res['stale_jobs_recovered_count']}[/bold]\n"
                f"Processing Vault Recoveries: [bold]{res['vault_recoveries_count']}[/bold]\n"
                f"YouTube Videos Reconciled: [bold]{res['youtube_reconciled_count']}[/bold]\n"
                f"System Health Status: [bold cyan]{res['status']}[/bold cyan]",
                border_style="green"
            ))
        finally:
            db.close()
    elif args.dashboard:
        start_dashboard()
    elif args.harvest_analytics:
        from engines.metrics_collector import MetricsCollector
        db = SessionLocal()
        try:
            collector = MetricsCollector()
            summary = collector.harvest_all_eligible_shorts(db)
            console.print(f"[bold green][+] Analytics Harvesting Complete:[/bold green] {summary['snapshots_harvested']} snapshots recorded, {summary['skipped_idempotent_count']} already fresh, {summary['skipped_immature_count']} immature (<24h).")
        finally:
            db.close()
    elif args.learn:
        from engines.learning_engine import LearningEngine
        db = SessionLocal()
        try:
            learner = LearningEngine()
            summary = learner.run_learning_cycle(db)
            console.print(Panel.fit(
                f"[bold green][+] Closed-Loop Learning Cycle Complete![/bold green]\n"
                f"Eligible Videos Evaluated: [bold]{summary['eligible_videos_evaluated']}[/bold]\n"
                f"Channel Baseline Score: [bold]{summary['channel_baseline_score']:.2f}/100[/bold]\n"
                f"Strategy Weights Updated: [bold]{summary['weights_updated_count']}[/bold]",
                border_style="green"
            ))
            rec = learner.get_strategy_recommendation(db, deterministic=True)
            console.print("[bold cyan]Current Strategy Recommendations:[/bold cyan]")
            for k, v in rec["recommendations"].items():
                console.print(f"  • [yellow]{k}[/yellow]: [bold white]{v}[/bold white] ({rec['reasoning'].get(k, '')})")
        finally:
            db.close()
    elif args.maintain_buffer > 0:
        res = pipeline.maintain_buffer(target_stock=args.maintain_buffer)
        count = res[0] if isinstance(res, tuple) else res
        summary = res[1] if isinstance(res, tuple) else {}
        if summary.get("outcome") in ("BLOCKED", "FAILED"):
            sys.exit(2)
    elif args.produce_batch > 0:
        res = pipeline.produce_batch(count=args.produce_batch)
        count = res[0] if isinstance(res, tuple) else res
        summary = res[1] if isinstance(res, tuple) else {}
        if summary.get("outcome") in ("BLOCKED", "FAILED"):
            sys.exit(2)
    elif args.publish_next:
        pipeline.publish_next_from_vault(force=args.force, target_file_id=args.file_id)
    elif args.schedule_ready:
        pipeline.schedule_ready_buffer(target_file_id=args.file_id)
    elif args.run_once or args.test:
        pipeline.run_single_job(force=args.force)
    elif args.daemon:
        import schedule
        console.print("[bold green]Starting automated daemon scheduler (Strictly 4 Shorts/day at 06:00, 10:00, 15:00, 20:00 UTC)...[/bold green]")
        schedule.every().day.at("06:00").do(pipeline.publish_next_from_vault)
        schedule.every().day.at("10:00").do(pipeline.publish_next_from_vault)
        schedule.every().day.at("15:00").do(pipeline.publish_next_from_vault)
        schedule.every().day.at("20:00").do(pipeline.publish_next_from_vault)
        pipeline.publish_next_from_vault()  # Run initial cycle
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
