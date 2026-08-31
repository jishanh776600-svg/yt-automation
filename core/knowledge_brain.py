"""
Obsidian Knowledge Brain & Google Drive Knowledge Backup Engine.
Maintains a human-readable, structured Markdown knowledge vault under data/knowledge/
and orchestrates idempotent, safe backups to the authoritative Google Drive storage.

Architecture:
  SQLite        = operational state
  Google Drive  = durable production/file backup
  Obsidian      = human-readable long-term knowledge/brain
"""
import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from config.settings import PROJECT_ROOT, DATA_DIR, KOKORO_VOICE
from config.constants import DAILY_SHORTS_LIMIT, TARGET_RESERVE_BUFFER, MIN_DURATION_SEC, MAX_DURATION_SEC

logger = logging.getLogger(__name__)

KNOWLEDGE_VAULT_DIR = DATA_DIR / "knowledge"


class KnowledgeBrain:
    """
    Manages AL AMR's long-term human-readable Obsidian Knowledge Brain.
    Generates structured Markdown knowledge records and synchronizes them to Google Drive.
    """

    def __init__(self, vault_dir: Optional[Path] = None):
        self.vault_dir = vault_dir or KNOWLEDGE_VAULT_DIR
        self.vault_dir.mkdir(parents=True, exist_ok=True)

    def initialize_vault_structure(self) -> Dict[str, Path]:
        """Creates the canonical Obsidian folder hierarchy."""
        subdirs = [
            "Projects",
            "Production",
            "Topics",
            "Scripts",
            "Performance",
            "Learning",
            "Voice",
            "Visuals",
            "BGM",
            "SFX",
            "Research",
            "Decisions",
            "Failures",
            "System",
            "Index"
        ]
        created = {}
        for sd in subdirs:
            p = self.vault_dir / sd
            p.mkdir(parents=True, exist_ok=True)
            created[sd] = p
        return created

    def build_index_note(self) -> Path:
        """Generates the master Index.md note."""
        index_file = self.vault_dir / "Index.md"
        content = f"""# AL AMR // Autonomous YouTube Shorts Production Brain

*Obsidian Knowledge Vault — Operational Intelligence & System Standards*
*Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}*

---

## 🏛 Core System Invariants
- **Canonical Voice**: `{KOKORO_VOICE}` (Kokoro-v1.0 ONNX, American English Female)
- **Daily Publishing Limit**: `{DAILY_SHORTS_LIMIT}` Shorts/day
- **Target Reserve Buffer**: `{TARGET_RESERVE_BUFFER}` verified Shorts in Drive `01_READY`
- **Publishing Slots (UTC)**: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`
- **Target Duration**: `{MIN_DURATION_SEC}s – {MAX_DURATION_SEC}s` (with mandatory 0.6s outro breathing margin)
- **Target Resolution**: `1080x1920` (9:16 vertical)
- **Target Audio Loudness**: `-14.0 LUFS` integrated master loudness

---

## 🧠 Provider Failover Hierarchy
1. **Gemini Primary** (`gemini-3.6-flash`)
2. **Gemini Secondary** (Backup Google GenAI credential)
3. **Groq** (`groq/compound-mini` via high-speed REST)
4. **OpenRouter** (`meta-llama/llama-3.3-70b-instruct:free` fallback)
5. **Bounded Clean Failure** (Zero corrupt outputs or infinite retry storms)

---

## 📂 Knowledge Domain Navigation
- [[Voice/af_bella_canonical|Voice Engine Specification]]
- [[Production/pipeline_rules|Production Pipeline & Timing Rules]]
- [[Learning/strategy_insights|Closed-Loop Learning & Analytics]]
- [[Decisions/provider_chain|AI Provider Architecture & Failover]]
- [[Failures/quarantine_policy|Poison-Pill Quarantine & Verification]]
- [[Visuals/composition_rules|Visual Composition & Video Directing]]
- [[BGM/acoustic_standards|BGM & SFX Acoustic Verification]]
"""
        index_file.write_text(content.strip(), encoding="utf-8")
        return index_file

    def build_voice_note(self) -> Path:
        """Generates the canonical voice knowledge record."""
        voice_file = self.vault_dir / "Voice" / "af_bella_canonical.md"
        content = f"""# Canonical Narration Voice: af_bella

## Overview
`af_bella` is the authoritative permanent voice for all AL AMR historical YouTube Shorts narration.

## Configuration & Standards
- **Voice Identifier**: `af_bella`
- **Engine**: Kokoro-v1.0 ONNX (Zero GPU dependency, ultra-fast CPU inference)
- **Format**: 24kHz / 44.1kHz 16-bit PCM WAV
- **Speed / Pacing**: 1.05x normal conversational speed (~2.3 to 2.6 words/sec)
- **Word Target**: 50 to 56 words for ~22.0 to 24.0s of clean narration
- **Outro Breathing Room**: Exactly +0.6s visual and audio buffer after final syllable

## Voice Invariants
1. All modules (`tts_engine.py`, `settings.py`, workflows, preview UI, E2E) resolve to `af_bella`.
2. Fallback to `am_adam` or other voices is prohibited in production.
"""
        voice_file.write_text(content.strip(), encoding="utf-8")
        return voice_file

    def build_production_rules_note(self) -> Path:
        """Generates the production rules and timing policy note."""
        rules_file = self.vault_dir / "Production" / "pipeline_rules.md"
        content = f"""# Production Pipeline & Timing Rules

## 6-Stage Continuous Lifecycle
1. **01. Discovery**: Semantic deduplication & historical topic research.
2. **02. Script**: 5-part retention-oriented narrative structure.
3. **03. Kokoro**: Authoritative `af_bella` voiceover synthesis.
4. **04. Visuals**: Multi-shot 1080x1920 video composition with editing director.
5. **05. Vault**: Automated upload to Google Drive `01_READY` reserve buffer.
6. **06. Live**: Scheduled publication & reconciliation via YouTube API.

## Dynamic Script & Audio Calibration
- Narration duration is the **authoritative timing measurement**.
- Target video duration: `video_duration = audio_duration + 0.6s (safety margin)`.
- Never use `-shortest` in FFmpeg; enforce synchronous render duration `-t`.
- Never truncate final spoken sentence.
- QA rejects any render where `voice_duration > video_duration - 0.6s`.
"""
        rules_file.write_text(content.strip(), encoding="utf-8")
        return rules_file

    def build_learning_note(self, mature_count: int = 0, baseline: float = 50.0) -> Path:
        """Generates the learning and performance feedback note."""
        learning_file = self.vault_dir / "Learning" / "strategy_insights.md"
        content = rf"""# Closed-Loop Strategy Learning & Analytics

## Analytics Architecture
- **Source**: Authorized YouTube Data API v3 & YouTube Analytics API.
- **Snapshot Immutability**: Time-series `PerformanceSnapshot` records stored at 24h, 48h, 7d intervals.
- **Data Truth Invariant**: Missing or unsupported API metrics are recorded as `None` (UNAVAILABLE), never fabricated as `0.0`.

## Current Baseline Status
- **Mature Videos Analyzed**: `{mature_count}`
- **Channel Performance Baseline**: `{baseline:.1f} / 100`

## Evidence Thresholds
- **Insufficient Evidence**: $N < 3$ (No strategy weight adjustment)
- **Weak Signal**: $N = 3 - 4$ (Damped adjustment $\pm 10\%$)
- **Usable Signal**: $N \ge 5$ (Full strategy weight adjustment bounded in $[0.20, 2.00]$)
"""
        learning_file.write_text(content.strip(), encoding="utf-8")
        return learning_file

    def build_all_knowledge_notes(self, db_session=None) -> List[Path]:
        """Generates the entire knowledge base."""
        self.initialize_vault_structure()
        files = [
            self.build_index_note(),
            self.build_voice_note(),
            self.build_production_rules_note(),
            self.build_learning_note()
        ]
        return files

    def backup_to_drive(self, drive_engine) -> Dict[str, Any]:
        """
        Idempotently backs up all Obsidian Markdown knowledge files to Google Drive vault.
        Strictly excludes any credentials, .env files, tokens, or binary artifacts.
        """
        self.build_all_knowledge_notes()

        uploaded = []
        skipped = []
        errors = []

        # Find or create 05_KNOWLEDGE folder in Drive
        target_folder = "05_KNOWLEDGE"
        try:
            folder_id = drive_engine.ensure_folder_exists(target_folder)
        except Exception:
            # Fallback to 00_SYSTEM if custom folder creation isn't mapped
            target_folder = "00_SYSTEM"
            folder_id = drive_engine.ensure_folder_exists(target_folder)

        for root, _, filenames in os.walk(self.vault_dir):
            for fname in filenames:
                if not fname.endswith(".md") and not fname.endswith(".json"):
                    continue
                # Never upload secrets
                if "secret" in fname.lower() or "token" in fname.lower() or ".env" in fname.lower():
                    continue

                local_file = Path(root) / fname
                rel_path = local_file.relative_to(self.vault_dir).as_posix()

                try:
                    drive_name = f"knowledge_{rel_path.replace('/', '_')}"
                    drive_engine.upload_file(
                        local_path=local_file,
                        target_folder=target_folder,
                        remote_filename=drive_name
                    )
                    uploaded.append(rel_path)
                except Exception as up_err:
                    errors.append(f"{rel_path}: {up_err}")

        return {
            "status": "SUCCESS" if not errors else "PARTIAL",
            "vault_dir": str(self.vault_dir),
            "files_backed_up": uploaded,
            "errors": errors,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
