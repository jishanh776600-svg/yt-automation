"""
E2E Test Configuration and Deterministic Mock Harness for AL-AMR.
Provides:
1. MockDriveEngine: In-memory Google Drive vault with full 5-folder hierarchy.
2. MockYouTubeChannel: In-memory YouTube scheduling and inventory.
3. Sample test fixtures (EventCards, Scripts, Manifests, DB generators).
4. Strict offline execution guaranteeing zero external socket/HTTP calls.
"""
import os
import json
import sqlite3
import tempfile
import uuid
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import pytest

from core.models import (
    Job, Topic, ArticleRecord, ScriptRecord,
    VisualEvidenceRecord, ProductionAssetManifestRecord, RenderedVideoRecord, UploadRecord
)
from intelligence.event_card import EventCard, ClaimEvidence, WhereSection, WhenSection, WhoSection, VerificationState
from intelligence.asset_manifest import (
    ProductionAssetManifest, BeatVisualAssignment, ManifestCoverageMetrics,
    EditTransitionType, ManifestLicensingEligibility
)
from intelligence.visual_models import VisualCoverageType, VisualAuthenticity, VisualLicensingStatus
from config.constants import ContentNiche, JobState, DAILY_SHORTS_LIMIT


PRESERVED_SARAH_SHORT = "short_man_2bf89781983b.mp4"


class MockDriveEngine:
    """
    High-fidelity in-memory Google Drive Vault Engine.
    Simulates Google Drive API and DriveVaultEngine methods without network I/O.
    """

    def __init__(self, populate_preserved_short: bool = True):
        self.folders = {
            "00_SYSTEM": "folder_00_system_id",
            "01_READY": "folder_01_ready_id",
            "02_PROCESSING": "folder_02_processing_id",
            "03_PUBLISHED": "folder_03_published_id",
            "04_FAILED": "folder_04_failed_id",
        }
        self.folder_names_by_id = {v: k for k, v in self.folders.items()}
        # Map: file_id -> file dict
        self.files: Dict[str, Dict[str, Any]] = {}

        if populate_preserved_short:
            self._inject_preserved_short()

    def _inject_preserved_short(self):
        file_id = "drive_sarah_preserved_id"
        self.files[file_id] = {
            "id": file_id,
            "name": PRESERVED_SARAH_SHORT,
            "parent_id": self.folders["01_READY"],
            "folder_name": "01_READY",
            "size": 1850000,
            "mime_type": "video/mp4",
            "properties": {
                "voice": "af_sarah",
                "voice_id": "af_sarah",
                "qa_passed": "true",
                "short_id": "short_man_2bf89781983b",
                "niche": "mystery",
                "duration": "23.4",
            },
            "content": b"PRESERVED_SARAH_SHORT_MP4_PAYLOAD",
            "created_time": "2026-09-01T12:00:00Z"
        }

    def ensure_folder_hierarchy(self) -> Dict[str, str]:
        return dict(self.folders)

    def list_files(self, folder_id: Optional[str] = None, name_contains: Optional[str] = None) -> List[Dict[str, Any]]:
        results = []
        for f in self.files.values():
            if folder_id and f.get("parent_id") != folder_id:
                continue
            if name_contains and name_contains not in f.get("name", ""):
                continue
            results.append(dict(f))
        return results

    def list_files_in_folder(self, folder_name: str) -> List[Dict[str, Any]]:
        folder_id = self.folders.get(folder_name)
        if not folder_id:
            return []
        return [dict(f) for f in self.files.values() if f.get("parent_id") == folder_id]

    def get_ready_stock_count(self) -> int:
        return len(self.list_files_in_folder("01_READY"))

    def upload_raw_content(
        self,
        content: bytes,
        filename: str,
        parent_folder_id: str,
        mime_type: str = "application/octet-stream",
        properties: Optional[Dict[str, Any]] = None
    ) -> str:
        file_id = f"file_{uuid.uuid4().hex[:12]}"
        folder_name = self.folder_names_by_id.get(parent_folder_id, "UNKNOWN")
        self.files[file_id] = {
            "id": file_id,
            "name": filename,
            "parent_id": parent_folder_id,
            "folder_name": folder_name,
            "size": len(content),
            "mime_type": mime_type,
            "properties": properties or {},
            "content": content,
            "created_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        return file_id

    def upload_file(
        self,
        local_path: Path,
        target_folder: str,
        filename: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        local_path = Path(local_path)
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")
        parent_folder_id = self.folders.get(target_folder)
        if not parent_folder_id:
            raise ValueError(f"Unknown vault folder: {target_folder}")

        target_name = filename or local_path.name
        content = local_path.read_bytes()
        fid = self.upload_raw_content(
            content=content,
            filename=target_name,
            parent_folder_id=parent_folder_id,
            properties=properties
        )
        return {"id": fid, "name": target_name, "folder": target_folder, "size": len(content)}

    def download_file(self, file_id: str, local_destination: Path) -> Path:
        local_destination = Path(local_destination)
        file_data = self.files.get(file_id)
        if not file_data:
            raise FileNotFoundError(f"Drive file {file_id} not found in mock vault")
        local_destination.parent.mkdir(parents=True, exist_ok=True)
        local_destination.write_bytes(file_data.get("content", b""))
        return local_destination

    def delete_file(self, file_id: str) -> bool:
        if file_id in self.files:
            del self.files[file_id]
            return True
        return False

    def move_file_in_vault(self, file_id: str, from_folder: str, to_folder: str) -> bool:
        f = self.files.get(file_id)
        if not f:
            return False
        to_folder_id = self.folders.get(to_folder)
        if not to_folder_id:
            return False
        f["parent_id"] = to_folder_id
        f["folder_name"] = to_folder
        return True

    def upload_database(self, local_path: Path, filename: str = "pipeline.db") -> Dict[str, Any]:
        return self.upload_file(
            local_path=local_path,
            target_folder="00_SYSTEM",
            filename=filename,
            properties={"type": "sqlite_database", "filename": filename}
        )

    def download_canonical_database(self, target_path: Path, filename: str = "pipeline.db") -> Path:
        sys_files = self.list_files_in_folder("00_SYSTEM")
        target_file = next((f for f in sys_files if f["name"] == filename), None)
        if not target_file:
            raise FileNotFoundError(f"Canonical database '{filename}' not found in Drive vault '00_SYSTEM'")
        return self.download_file(target_file["id"], target_path)

    def download_database(self, local_dest_path: Path, filename: str = "pipeline.db") -> Path:
        return self.download_canonical_database(target_path=local_dest_path, filename=filename)

    def find_file_in_folder(self, folder_name: str, filename: str) -> Optional[Dict[str, Any]]:
        files = self.list_files_in_folder(folder_name)
        return next((f for f in files if f.get("name") == filename), None)



def create_mock_sqlite_db(path: Path) -> Path:
    """Initializes a valid SQLite database with standard tables and sample records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id VARCHAR(64) PRIMARY KEY,
            canonical_id VARCHAR(64),
            title VARCHAR(256) NOT NULL,
            category VARCHAR(64) NOT NULL,
            niche VARCHAR(64) DEFAULT 'Mystery / Bizarre',
            status VARCHAR(32) NOT NULL,
            source VARCHAR(64),
            event_id VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            discovered_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS scripts (
            id VARCHAR(64) PRIMARY KEY,
            topic_id VARCHAR(64) NOT NULL,
            title VARCHAR(256),
            hook_text TEXT,
            body_text TEXT,
            word_count INTEGER,
            estimated_duration REAL,
            visual_beats_count INTEGER,
            voice_id VARCHAR(32) DEFAULT 'af_sarah',
            quality_score REAL DEFAULT 8.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id VARCHAR(64) PRIMARY KEY,
            topic_id VARCHAR(64),
            state VARCHAR(32) NOT NULL,
            voice_id VARCHAR(32) DEFAULT 'af_sarah',
            attempts INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS renders (
            id VARCHAR(64) PRIMARY KEY,
            job_id VARCHAR(64),
            video_path TEXT,
            duration_seconds REAL,
            resolution VARCHAR(32),
            qa_status VARCHAR(32),
            qa_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rendered_videos (
            id VARCHAR(64) PRIMARY KEY,
            job_id VARCHAR(64),
            event_id VARCHAR(64),
            video_path TEXT,
            qa_status VARCHAR(32),
            qa_report_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id VARCHAR(64) PRIMARY KEY,
            job_id VARCHAR(64),
            topic_id VARCHAR(64),
            title VARCHAR(256),
            youtube_video_id VARCHAR(64),
            status VARCHAR(32) NOT NULL,
            scheduled_publish_at TIMESTAMP,
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS performance_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            upload_id VARCHAR(64),
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id VARCHAR(64) PRIMARY KEY,
            asset_type VARCHAR(32),
            file_path TEXT,
            source VARCHAR(64),
            exact_hash VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Populate baseline verified record
    cur.execute("""
        INSERT OR IGNORE INTO topics (id, canonical_id, title, category, niche, status, event_id)
        VALUES ('top_seed_01', 'canon_01', 'The Strange Bell of Lake Baikal', 'Mystery / Bizarre', 'Mystery / Bizarre', 'PRODUCED', 'evt_seed_01');
    """)
    cur.execute("""
        INSERT OR IGNORE INTO scripts (id, topic_id, title, hook_text, body_text, word_count, estimated_duration, visual_beats_count, voice_id, quality_score)
        VALUES ('scr_seed_01', 'top_seed_01', 'The Strange Bell of Lake Baikal', 'Deep beneath Siberian ice, divers heard an acoustic rhythm.', 'Divers exploring Lake Baikal in 1982 reported a metallic acoustic chime repeating every 10 seconds. Hydrophones confirmed the signal. The origin remains an enigma.', 65, 23.2, 10, 'af_sarah', 8.9);
    """)

    conn.commit()
    conn.close()
    return path


def make_sample_event_card(
    event_id: str = "evt_sample_001",
    title: str = "The Toxic Crystal Caves of Naica",
    niche: str = "Weird Science",
    entities: Optional[List[str]] = None
) -> EventCard:
    now = datetime.datetime.now(datetime.timezone.utc)
    claim1 = ClaimEvidence(
        claim_id="cl_001",
        claim_text="Explorers inside Chihuahua gypsum caverns discovered 50-ton selenite crystals heated by magma chambers.",
        publisher="Geological Institute",
        source_url="https://geology.org/naica_crystal",
        published_utc=now,
        confidence=0.98
    )
    claim2 = ClaimEvidence(
        claim_id="cl_002",
        claim_text="Ambient humidity of 99 percent and temperatures reaching 58 degrees Celsius limit human survival to ten minutes without cooling suits.",
        publisher="Speleological Review",
        source_url="https://speleo.org/naica_limits",
        published_utc=now,
        confidence=0.95
    )

    return EventCard(
        event_id=event_id,
        canonical_title=title,
        verification_state=VerificationState.MULTI_SOURCE_CORROBORATED.value,
        confidence=0.96,
        first_seen_utc=now,
        latest_seen_utc=now,
        who=WhoSection(organizations=["Geological Survey"], countries=["Mexico"]),
        what=f"Scientific exploration of subterranean anomalies in {niche}.",
        where=WhereSection(location_name="Naica Mine", country="Mexico"),
        when=WhenSection(event_time_utc=now),
        entities=entities or ["Naica Mine", "selenite crystal", "magma chamber", "subterranean cavern"],
        actions=["discovered", "measured", "explored", "documented"],
        important_objects=["selenite crystal", "respirator suit", "thermal sensor"],
        claims=[claim1, claim2]
    )


def make_sample_manifest(
    event_id: str = "evt_sample_001",
    beat_count: int = 10,
    duration: float = 23.5
) -> ProductionAssetManifest:
    """Generates a valid ProductionAssetManifest with beat_count distinct beats."""
    beat_dur = duration / float(beat_count)
    beats = []
    for i in range(beat_count):
        b = BeatVisualAssignment(
            beat_id=f"beat_{i+1:02d}",
            sequence=i + 1,
            text=f"Narrative statement {i+1} describing genuine physical evidence.",
            start_time=round(i * beat_dur, 2),
            end_time=round((i + 1) * beat_dur, 2),
            duration_seconds=round(beat_dur, 2),
            selected_visual_id=f"vis_asset_{i+1:02d}",
            coverage_type=VisualCoverageType.DIRECT_EVIDENCE.value,
            authenticity=VisualAuthenticity.EVENT_SPECIFIC.value,
            licensing_status=VisualLicensingStatus.PUBLIC_DOMAIN.value,
            eligibility=ManifestLicensingEligibility.ELIGIBLE.value,
            transition=EditTransitionType.CUT.value,
            claim_ids=["cl_001"],
            source_publisher="Archives of Science",
            source_url=f"https://science-archive.org/asset_{i+1}",
            confidence=0.95,
        )
        beats.append(b)

    metrics = ManifestCoverageMetrics(
        total_beats=beat_count,
        direct_evidence_beats=beat_count,
        related_evidence_beats=0,
        contextual_beats=0,
        no_visual_beats=0,
        direct_evidence_ratio=1.0,
        eligible_licensing_ratio=1.0,
        average_visual_confidence=0.95,
        unique_visual_sources_count=beat_count,
        visual_reuse_rate=0.0
    )

    return ProductionAssetManifest(
        manifest_id=f"man_{uuid.uuid4().hex[:12]}",
        event_id=event_id,
        script_id=f"scr_{uuid.uuid4().hex[:8]}",
        total_duration_seconds=duration,
        beats=beats,
        metrics=metrics,
        validation_status="VALID"
    )


@pytest.fixture
def mock_drive():
    """Provides a clean in-memory MockDriveEngine with preserved Sarah short."""
    return MockDriveEngine(populate_preserved_short=True)


@pytest.fixture
def temp_workspace(tmp_path):
    """Provides a fresh isolated workspace with SQLite database and lock dirs."""
    db_path = tmp_path / "data" / "database" / "pipeline.db"
    create_mock_sqlite_db(db_path)
    locks_dir = tmp_path / "runtime" / "locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    renders_dir = tmp_path / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    return {
        "root": tmp_path,
        "db_path": db_path,
        "locks_dir": locks_dir,
        "renders_dir": renders_dir
    }
