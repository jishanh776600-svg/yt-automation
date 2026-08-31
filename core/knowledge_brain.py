"""
Obsidian Knowledge Brain & Google Drive Knowledge Backup Engine.
Maintains a human-readable, structured Markdown knowledge vault under data/knowledge/
and orchestrates idempotent, safe backups to authoritative Google Drive storage.

Architecture:
  SQLite        = operational state & relational schema
  Google Drive  = durable production/file backup & vault
  Obsidian      = human-readable long-term knowledge/brain with connected wikilinks
"""
import os
import sys
import json
import hashlib
import logging
import subprocess
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from config.settings import PROJECT_ROOT, DATA_DIR, KOKORO_VOICE
from config.constants import (
    DAILY_SHORTS_LIMIT,
    TARGET_RESERVE_BUFFER,
    MIN_DURATION_SEC,
    MAX_DURATION_SEC,
    TARGET_LUFS
)

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
            "Topics",
            "Research",
            "Scripts",
            "Voice",
            "Visuals",
            "BGM",
            "SFX",
            "Production",
            "Performance",
            "Learning",
            "Decisions",
            "Failures",
            "System"
        ]
        created = {}
        for sd in subdirs:
            p = self.vault_dir / sd
            p.mkdir(parents=True, exist_ok=True)
            created[sd] = p
        return created

    def configure_obsidian_settings(self) -> Path:
        """
        Initializes the .obsidian configuration folder inside the vault.
        Configures Obsidian for wikilinks and standard views.
        """
        obsidian_dir = self.vault_dir / ".obsidian"
        obsidian_dir.mkdir(parents=True, exist_ok=True)

        app_json = obsidian_dir / "app.json"
        if not app_json.exists():
            app_config = {
                "useMarkdownLinks": False,
                "newFileLocation": "root",
                "attachmentFolderPath": "Attachments",
                "alwaysUpdateLinks": True
            }
            app_json.write_text(json.dumps(app_config, indent=2), encoding="utf-8")

        core_plugins_json = obsidian_dir / "core-plugins.json"
        if not core_plugins_json.exists():
            plugins = [
                "file-explorer",
                "global-search",
                "switcher",
                "graph",
                "backlink",
                "canvas",
                "outgoing-link",
                "tag-pane",
                "page-preview",
                "command-palette",
                "markdown-importer",
                "word-count",
                "outline"
            ]
            core_plugins_json.write_text(json.dumps(plugins, indent=2), encoding="utf-8")

        graph_json = obsidian_dir / "graph.json"
        if not graph_json.exists():
            graph_config = {
                "collapse-filter": False,
                "search": "",
                "showTags": False,
                "showAttachments": False,
                "hideUnresolved": False,
                "showOrphans": True,
                "collapse-color-groups": True,
                "colorGroups": [],
                "collapse-display": True,
                "showArrow": True,
                "textFadeMultiplier": 0,
                "nodeSizeMultiplier": 1.1,
                "lineSizeMultiplier": 1,
                "collapse-forces": True,
                "centerStrength": 0.518,
                "repelStrength": 10,
                "linkStrength": 1,
                "linkDistance": 250,
                "scale": 1.0
            }
            graph_json.write_text(json.dumps(graph_config, indent=2), encoding="utf-8")

        return obsidian_dir

    def register_in_obsidian_app(self) -> bool:
        """
        Registers this vault in Obsidian's global registry (%APPDATA%/obsidian/obsidian.json)
        so that Obsidian detects and lists the vault on startup.
        """
        app_data = os.getenv("APPDATA")
        if not app_data:
            return False

        obsidian_global_dir = Path(app_data) / "obsidian"
        if not obsidian_global_dir.exists():
            try:
                obsidian_global_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.debug(f"Could not create global obsidian directory: {e}")
                return False

        obsidian_json_file = obsidian_global_dir / "obsidian.json"
        abs_vault_path = str(self.vault_dir.resolve())
        vault_id = hashlib.md5(abs_vault_path.encode("utf-8")).hexdigest()[:16]

        data = {"vaults": {}}
        if obsidian_json_file.exists():
            try:
                data = json.loads(obsidian_json_file.read_text(encoding="utf-8"))
                if not isinstance(data.get("vaults"), dict):
                    data["vaults"] = {}
            except Exception as e:
                logger.warning(f"Could not read obsidian.json: {e}")
                data = {"vaults": {}}

        # Add or update vault entry
        data["vaults"][vault_id] = {
            "path": abs_vault_path,
            "ts": int(datetime.utcnow().timestamp() * 1000),
            "open": True
        }

        try:
            obsidian_json_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"[OBSIDIAN] Registered vault '{abs_vault_path}' in {obsidian_json_file}")
            return True
        except Exception as e:
            logger.warning(f"Could not write obsidian.json: {e}")
            return False

    def open_vault_in_obsidian(self) -> Dict[str, Any]:
        """
        Attempts to open the vault in the local Obsidian application using the obsidian:// protocol.
        """
        self.configure_obsidian_settings()
        self.register_in_obsidian_app()

        abs_path = str(self.vault_dir.resolve())
        encoded_path = urllib.parse.quote(abs_path)
        obsidian_uri = f"obsidian://open?path={encoded_path}"

        success = False
        launch_err = None

        if sys.platform == "win32":
            try:
                # Use start command to invoke default URI handler for obsidian://
                cmd = ["cmd", "/c", "start", "", obsidian_uri]
                subprocess.Popen(cmd, shell=False)
                success = True
                logger.info(f"[OBSIDIAN] Dispatched launch command: {obsidian_uri}")
            except Exception as e:
                launch_err = str(e)
                logger.warning(f"Could not launch Obsidian URI: {e}")

        return {
            "success": success,
            "uri": obsidian_uri,
            "vault_path": abs_path,
            "error": launch_err
        }

    # =========================================================================
    # KNOWLEDGE VAULT NOTE GENERATORS
    # =========================================================================

    def build_index_note(self) -> Path:
        """Generates the master Index.md note connecting the entire knowledge graph."""
        index_file = self.vault_dir / "Index.md"
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        content = f"""# AL AMR // Autonomous YouTube Shorts Production Brain

*Obsidian Knowledge Vault — Operational Intelligence & System Standards*
*Last Synchronized: {now_str}*

---

## 🏛 Core System Invariants
- **Canonical Voice**: `{KOKORO_VOICE}` (Kokoro-v1.0 ONNX, American English Female)
- **Daily Publishing Limit**: `{DAILY_SHORTS_LIMIT}` Shorts/day
- **Target Reserve Buffer**: `{TARGET_RESERVE_BUFFER}` verified Shorts in Drive `01_READY`
- **Publishing Slots (UTC)**: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`
- **Target Duration**: `{MIN_DURATION_SEC}s – {MAX_DURATION_SEC}s` (with mandatory 0.6s outro breathing margin)
- **Target Resolution**: `1080x1920` (9:16 vertical)
- **Target Master Loudness**: `{TARGET_LUFS:.1f} LUFS` (Broadcast window: `-17.0` to `-11.0` LUFS)

---

## 🧠 Provider Failover Hierarchy
1. **Gemini Primary** (`gemini-3.6-flash`)
2. **Gemini Secondary** (Backup Google GenAI credential)
3. **Groq** (`groq/compound-mini` via high-speed REST)
4. **OpenRouter** (`meta-llama/llama-3.3-70b-instruct:free` fallback)
5. **Bounded Clean Failure** (Zero corrupt outputs or infinite retry storms)

---

## 🗺 Knowledge Graph & Operational Workflow
```
[[Topics/topic_lifecycle|01. Topics]]
       │
       ▼
[[Research/historical_grounding|02. Research & Fact Verification]]
       │
       ▼
[[Scripts/retention_architecture|03. Retention Scripting]] ──► [[Voice/af_bella_canonical|Voice Engine]]
       │                                                                 │
       ▼                                                                 │
[[Visuals/composition_rules|04. Visual Composition]] ◄──────────────────┘
       │
       ├──────────────► [[BGM/acoustic_standards|BGM Acoustic Standards]]
       ├──────────────► [[SFX/sfx_integration|SFX Director]]
       │
       ▼
[[Production/pipeline_rules|05. Production & Reserve Buffer]] ──► [[Decisions/provider_chain|AI Providers]]
       │                                                      ──► [[Failures/quarantine_policy|Quarantine Policy]]
       ▼
[[Performance/publishing_and_telemetry|06. Published Videos & Telemetry]]
       │
       ▼
[[Learning/strategy_insights|07. Closed-Loop Learning & Strategy Weights]]
       │
       └──────────────► [[System/operating_invariants|Channel Baseline & Invariants]]
```

---

## 📂 Domain Index
- [[Topics/topic_lifecycle|Topic Discovery & Deduplication]]
- [[Research/historical_grounding|Historical Research & Fact Grounding]]
- [[Scripts/retention_architecture|5-Stage Retention Scripting]]
- [[Voice/af_bella_canonical|Canonical Voice: af_bella]]
- [[Visuals/composition_rules|Visual Composition & Directing]]
- [[BGM/acoustic_standards|BGM Loudness & Fingerprint Verification]]
- [[SFX/sfx_integration|SFX Punctuation & Audio Risers]]
- [[Production/pipeline_rules|6-Stage Production Pipeline]]
- [[Performance/publishing_and_telemetry|Publishing Slots & Telemetry Data Truth]]
- [[Learning/strategy_insights|Closed-Loop Performance Learning]]
- [[Decisions/provider_chain|AI Provider Failover Architecture]]
- [[Failures/quarantine_policy|Poison-Pill Quarantine & Safe Recovery]]
- [[System/operating_invariants|System Invariants & Durable Backup]]
"""
        index_file.write_text(content.strip(), encoding="utf-8")
        return index_file

    def build_topic_note(self) -> Path:
        topic_file = self.vault_dir / "Topics" / "topic_lifecycle.md"
        content = """# Topic Discovery & Deduplication Lifecycle

## Discovery Strategy
AL AMR autonomously discovers compelling historical events, bizarre historical paradoxes, and turning points.

## Semantic Deduplication
- **Method**: Cosine similarity against historical topic vectors + exact title collision detection.
- **Novelty Rule**: Topics with similarity > 0.85 against existing library entries are rejected.
- **Workflow Link**: Once approved, topics proceed to [[Research/historical_grounding|Historical Grounding]].
"""
        topic_file.write_text(content.strip(), encoding="utf-8")
        return topic_file

    def build_research_note(self) -> Path:
        res_file = self.vault_dir / "Research" / "historical_grounding.md"
        content = """# Historical Research & Fact Grounding

## Verification Standards
- **Claim Extraction**: Extracts 3 to 5 verifiable historical claims (dates, numbers, key entities).
- **Anti-Hallucination Gate**: Ensures no AI embellishments or unverified historical myths enter the script.
- **Downstream Flow**: Verified claims are passed directly into [[Scripts/retention_architecture|Retention Scripting]].
"""
        res_file.write_text(content.strip(), encoding="utf-8")
        return res_file

    def build_script_note(self) -> Path:
        script_file = self.vault_dir / "Scripts" / "retention_architecture.md"
        content = """# 5-Stage Retention Scripting Architecture

## Narrative Architecture
Every Short follows a strict 5-part retention curve:
1. **Hook (0-2s)**: Immediate curiosity/tension gap without filler introductions.
2. **Context**: Rapid historical grounding with forward momentum.
3. **Escalation**: Rising stakes and escalating conflict.
4. **Reveal**: Definitive, surprising historical payoff.
5. **Complete Final Resolution (`loop_twist`)**: A grammatically complete, memorable closing statement that provides total closure.

## Constraints & Calibration
- **Word Target**: Strictly 50 to 56 words.
- **Spoken Narration Duration**: 22.0s – 24.0s.
- **Voice Binding**: Synthesized exclusively by [[Voice/af_bella_canonical|af_bella]].
- **Production Integration**: Passed to [[Production/pipeline_rules|Production Pipeline]].
- **Optimization**: Guided by [[Learning/strategy_insights|Learned Strategy Profile]].
"""
        script_file.write_text(content.strip(), encoding="utf-8")
        return script_file

    def build_voice_note(self) -> Path:
        voice_file = self.vault_dir / "Voice" / "af_bella_canonical.md"
        content = f"""# Canonical Narration Voice: af_bella

## Overview
`af_bella` is the authoritative permanent voice for all AL AMR historical YouTube Shorts narration.

## Configuration & Standards
- **Voice Identifier**: `{KOKORO_VOICE}`
- **Engine**: Kokoro-v1.0 ONNX (Zero GPU dependency, ultra-fast CPU inference)
- **Format**: 24kHz / 44.1kHz 16-bit PCM WAV
- **Speed / Pacing**: 1.05x normal conversational speed (~2.3 to 2.6 words/sec)
- **Word Target**: 50 to 56 words for ~22.0 to 24.0s of clean narration
- **Outro Breathing Room**: Exactly +0.6s visual and audio buffer after final syllable

## Voice Invariants
1. All modules (`tts_engine.py`, `settings.py`, workflows, preview UI, E2E) resolve to `af_bella`.
2. Fallback to `am_adam` or other voices is strictly prohibited in production.
- **Pipeline Integration**: Implemented in [[Production/pipeline_rules|Pipeline Rules]].
"""
        voice_file.write_text(content.strip(), encoding="utf-8")
        return voice_file

    def build_visuals_note(self) -> Path:
        vis_file = self.vault_dir / "Visuals" / "composition_rules.md"
        content = """# Visual Composition & Directing Rules

## Specifications
- **Resolution**: 1080x1920 (9:16 Vertical format)
- **Multi-Shot Structure**: 4 to 6 discrete visual scenes matching narration progression.
- **Motion & Color**: Subtle Ken Burns zoom/pan on stills, high-contrast historical color grading.
- **Safe Zones**: Captions centered in middle third; top and bottom 20% reserved for YouTube UI overlays.
- **Pipeline Integration**: Executed in [[Production/pipeline_rules|Pipeline Rules]].
"""
        vis_file.write_text(content.strip(), encoding="utf-8")
        return vis_file

    def build_bgm_note(self) -> Path:
        bgm_file = self.vault_dir / "BGM" / "acoustic_standards.md"
        content = f"""# BGM Loudness & Acoustic Standards

## Acoustic Standards
- **Target Master Loudness**: `{TARGET_LUFS:.1f} LUFS` integrated loudness.
- **Broadcast Range**: `-17.0` to `-11.0` LUFS.
- **Audio Ducking**: BGM dynamically ducked to -18.0 dB during voiceover; transitions smoothly to outro.
- **Fingerprint Verification**: Cross-correlation acoustic fingerprinting confirms chosen track identity.
- **SFX Layering**: Blended with [[SFX/sfx_integration|SFX Tracks]].
"""
        bgm_file.write_text(content.strip(), encoding="utf-8")
        return bgm_file

    def build_sfx_note(self) -> Path:
        sfx_file = self.vault_dir / "SFX" / "sfx_integration.md"
        content = """# SFX Punctuation & Audio Design

## Sound Design Roles
- **Risers**: Builds anticipation during script escalation phase.
- **Impacts / Booms**: Punctuates major historical turning points and reveals.
- **Whooshes**: Smooth scene transitions between visual cuts.
- **Harmonization**: Integrated with [[BGM/acoustic_standards|BGM Track]] and [[Voice/af_bella_canonical|Voiceover]].
"""
        sfx_file.write_text(content.strip(), encoding="utf-8")
        return sfx_file

    def build_production_rules_note(self) -> Path:
        rules_file = self.vault_dir / "Production" / "pipeline_rules.md"
        content = f"""# Production Pipeline & Timing Rules

## 6-Stage Continuous Lifecycle
1. **01. Discovery**: Semantic deduplication & historical topic research (`[[Topics/topic_lifecycle|Topics]]`).
2. **02. Script**: 5-part retention-oriented narrative structure (`[[Scripts/retention_architecture|Scripts]]`).
3. **03. Kokoro**: Authoritative `af_bella` voiceover synthesis (`[[Voice/af_bella_canonical|Voice]]`).
4. **04. Visuals**: Multi-shot 1080x1920 video composition (`[[Visuals/composition_rules|Visuals]]`).
5. **05. Vault**: Automated upload to Google Drive `01_READY` reserve buffer.
6. **06. Live**: Scheduled publication via YouTube API (`[[Performance/publishing_and_telemetry|Publishing]]`).

## Dynamic Script & Audio Calibration
- Narration duration is the **authoritative timing measurement**.
- Target video duration: `video_duration = audio_duration + 0.6s (safety margin)`.
- Never use `-shortest` in FFmpeg; enforce synchronous render duration `-t`.
- Never truncate final spoken sentence.
- QA rejects any render where `voice_duration > video_duration - 0.6s`.
- Failures are quarantined to `[[Failures/quarantine_policy|04_FAILED]]`.
"""
        rules_file.write_text(content.strip(), encoding="utf-8")
        return rules_file

    def build_performance_note(self) -> Path:
        perf_file = self.vault_dir / "Performance" / "publishing_and_telemetry.md"
        content = f"""# Publishing Slots & Telemetry Data Truth

## Automated Scheduling
- **Daily Limit**: Strictly `{DAILY_SHORTS_LIMIT}` Shorts/day.
- **Publishing Slots (UTC)**: `06:00 UTC`, `11:00 UTC`, `15:00 UTC`.
- **Target Reserve Buffer**: `{TARGET_RESERVE_BUFFER}` Shorts maintained in `01_READY`.

## Telemetry Data Truth
- **YouTube Data API v3**: Public statistics (views, likes, comments).
- **YouTube Analytics API**: Retention percentage (APV), average view duration (AVD), watch time.
- **Unavailable vs Zero**: Metrics not yet available from API are stored as `None` (UNAVAILABLE), never fabricated as `0.0`.
- **Downstream Optimization**: Ingested by [[Learning/strategy_insights|Learning Engine]].
"""
        perf_file.write_text(content.strip(), encoding="utf-8")
        return perf_file

    def build_learning_note(self, mature_count: int = 0, baseline: float = 50.0) -> Path:
        learning_file = self.vault_dir / "Learning" / "strategy_insights.md"
        content = rf"""# Closed-Loop Strategy Learning & Analytics

## Analytics Architecture
- **Source**: Authorized YouTube Data API v3 & YouTube Analytics API ([[Performance/publishing_and_telemetry|Telemetry]]).
- **Snapshot Immutability**: Time-series `PerformanceSnapshot` records stored at 24h, 48h, 7d intervals.
- **Data Truth Invariant**: Missing or unsupported API metrics are recorded as `None` (UNAVAILABLE), never fabricated as `0.0`.

## Current Baseline Status
- **Mature Videos Analyzed**: `{mature_count}`
- **Channel Performance Baseline**: `{baseline:.1f} / 100`

## Evidence Thresholds
- **Insufficient Evidence**: $N < 3$ (No strategy weight adjustment)
- **Weak Signal**: $N = 3 - 4$ (Damped adjustment $\pm 10\%$)
- **Usable Signal**: $N \ge 5$ (Full strategy weight adjustment bounded in $[0.20, 2.00]$)

## Strategy Feedback Loop
Top-performing hook archetypes and pacing attributes are compiled into the [[Scripts/retention_architecture|Script Generation]] prompt.
"""
        learning_file.write_text(content.strip(), encoding="utf-8")
        return learning_file

    def build_decisions_note(self) -> Path:
        dec_file = self.vault_dir / "Decisions" / "provider_chain.md"
        content = """# AI Provider Hierarchy & Failover Architecture

## Failover Sequence
$$\\text{Gemini Primary} \\longrightarrow \\text{Gemini Secondary} \\longrightarrow \\text{Groq} \\longrightarrow \\text{OpenRouter} \\longrightarrow \\text{Clean Failure}$$

## Provider Specifications
1. **Gemini Primary**: Google GenAI `gemini-3.6-flash` (High quality, primary LLM).
2. **Gemini Secondary**: Google GenAI secondary project credential.
3. **Groq**: Ultra-low latency `groq/compound-mini` via standard REST API.
4. **OpenRouter**: `meta-llama/llama-3.3-70b-instruct:free` fallback adapter.
5. **Clean Failure**: Bounded fail-fast without infinite retry amplification.

## Deprecated Providers
- **DeepSeek**: Permanently deprecated and removed from active provider chains.
"""
        dec_file.write_text(content.strip(), encoding="utf-8")
        return dec_file

    def build_failures_note(self) -> Path:
        fail_file = self.vault_dir / "Failures" / "quarantine_policy.md"
        content = """# Poison-Pill Quarantine & Safe Recovery

## Quarantine Architecture
- **Automatic Isolation**: Any candidate failing QA, acoustic analysis, narration completeness, or publication safety is moved immediately to Google Drive `04_FAILED`.
- **Zero-Pollution Invariant**: Corrupt files, test artifacts, and zero-byte files are strictly excluded from inventory counts and never returned to `01_READY`.
- **Clean Failure Boundaries**:
  1. *Research Failure*: Fact verification shortfall $\\to$ Topic retired, not looped indefinitely.
  2. *Narration Timing Failure*: Voice duration exceeding $\\text{video\\_duration} - 0.6\\text{s}$ $\\to$ Render rejected, quarantined.
  3. *Provider Exhaustion*: All fallbacks failed (Gemini $\\to$ Groq $\\to$ OpenRouter) $\\to$ Clean fail-fast with `ALL_AI_PROVIDERS_EXHAUSTED`.
  4. *Publishing Safety Rejection*: Metadata mismatch or invalid container $\\to$ Claimed asset moved from `02_PROCESSING` to `04_FAILED`.
- Governed by [[Production/pipeline_rules|Pipeline Rules]] and [[Learning/strategy_insights|Learning Engine]].
"""
        fail_file.write_text(content.strip(), encoding="utf-8")
        return fail_file

    def build_system_note(self) -> Path:
        sys_file = self.vault_dir / "System" / "operating_invariants.md"
        content = f"""# System Invariants & Durable Architecture

## Storage Architecture
- **SQLite**: Ephemeral operational state and relational metadata.
- **Google Drive**: Authoritative physical file storage and vault backup.
- **Obsidian Brain (`data/knowledge/`)**: Human-readable knowledge repository and graph.

## Invariants
- `TARGET_RESERVE_BUFFER = {TARGET_RESERVE_BUFFER}`
- `DAILY_SHORTS_LIMIT = {DAILY_SHORTS_LIMIT}`
- `CANONICAL_VOICE = "{KOKORO_VOICE}"`
- `PUBLISHING_SLOTS = 06:00, 11:00, 15:00 UTC`
"""
        sys_file.write_text(content.strip(), encoding="utf-8")
        return sys_file

    def build_all_knowledge_notes(self, db_session=None) -> List[Path]:
        """Generates the entire interconnected knowledge base."""
        self.initialize_vault_structure()
        self.configure_obsidian_settings()
        self.register_in_obsidian_app()

        files = [
            self.build_index_note(),
            self.build_topic_note(),
            self.build_research_note(),
            self.build_script_note(),
            self.build_voice_note(),
            self.build_visuals_note(),
            self.build_bgm_note(),
            self.build_sfx_note(),
            self.build_production_rules_note(),
            self.build_performance_note(),
            self.build_learning_note(),
            self.build_decisions_note(),
            self.build_failures_note(),
            self.build_system_note()
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
            target_folder = "00_SYSTEM"
            folder_id = drive_engine.ensure_folder_exists(target_folder)

        for root, _, filenames in os.walk(self.vault_dir):
            for fname in filenames:
                if not fname.endswith(".md") and not fname.endswith(".json"):
                    continue
                # Never upload secrets
                fname_lower = fname.lower()
                if "secret" in fname_lower or "token" in fname_lower or ".env" in fname_lower or "password" in fname_lower:
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
