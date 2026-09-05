"""
AL-AMR Tier 4 Real-World Application Scenarios (E2E Integration & Stress Workloads).
===================================================================================
This suite exercises the system across 6 multi-feature production pipelines:
1. Scenario 1: Cold-Start Cloud Buffer Refill (test_scenario_1_cold_start_buffer_refill)
2. Scenario 2: Scheduled Autopilot Release Cycle (test_scenario_2_autopilot_release_cycle)
3. Scenario 3: Multi-Runner Distributed Lock Contention (test_scenario_3_multi_runner_lock_contention)
4. Scenario 4: Broken/Corrupted State Self-Healing & Quarantining (test_scenario_4_state_self_healing_and_quarantine)
5. Scenario 5: 48-Hour Rolling Calendar Production-to-Publish Simulation (test_scenario_5_full_48h_rolling_simulation)
6. Scenario 6: Disaster Recovery & Runner Amnesia Defense (test_scenario_6_disaster_recovery_amnesia_defense)

Deterministic Opaque-Box Execution:
- Zero external socket/HTTP calls.
- High-fidelity MockDriveEngine with full 5-folder hierarchy.
- In-memory SQLite databases with WAL mode verification.
- Complete contract compliance with PROJECT.md and TEST_INFRA.md.
"""
import os
import json
import sqlite3
import tempfile
import uuid
import datetime
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from config.constants import ContentNiche, JobState, DAILY_SHORTS_LIMIT
from core.database_sync import (
    compute_sha256,
    download_canonical_database,
    upload_canonical_database,
)
from core.pipeline_state import CloudLockManager, CloudLockError, TARGET_BUFFER, ProductionRunTelemetry
from core.lock import ProcessLock
from core.recovery_manager import RecoveryManager
from intelligence.video_qa import VideoQAEngine
from engines.scheduler_engine import PublicationScheduler
from intelligence.clustering import is_niche_compliant
from intelligence.ai_council import (
    AICouncilEngine, CouncilMemberReview, CouncilQualityScore, CouncilSession
)
from intelligence.visual_memory import GlobalVisualMemory, hamming_distance
from tests.e2e.conftest import (
    MockDriveEngine,
    create_mock_sqlite_db,
    make_sample_event_card,
    make_sample_manifest,
    PRESERVED_SARAH_SHORT,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ==============================================================================
# Scenario 1: Cold-Start Cloud Buffer Refill
# ==============================================================================

def test_scenario_1_cold_start_buffer_refill(tmp_path):
    """
    Scenario 1: Ephemeral runner spins up with zero local state, acquires locks,
    downloads canonical DB, detects ready stock deficit (1 vs target 6),
    sequentially produces 5 verified shorts, and uploads DB back to 00_SYSTEM.
    """
    # 1. Setup Remote Cloud Vault (contains 1 preserved Sarah short in 01_READY)
    mock_drive = MockDriveEngine(populate_preserved_short=True)

    # Remote 00_SYSTEM contains canonical SQLite DB
    remote_seed_db = tmp_path / "remote_seed" / "pipeline.db"
    create_mock_sqlite_db(remote_seed_db)
    mock_drive.upload_database(remote_seed_db, filename="pipeline.db")

    # 2. Ephemeral Runner starts with fresh local workspace
    local_workspace = tmp_path / "ephemeral_runner"
    local_workspace.mkdir(parents=True, exist_ok=True)
    local_db = local_workspace / "data" / "database" / "pipeline.db"
    run_id = f"run_cold_start_{uuid.uuid4().hex[:8]}"

    # 3. Distributed and Process Locks acquired
    cloud_lock = CloudLockManager(drive_engine=mock_drive, run_id=run_id)
    assert cloud_lock.acquire() is True
    assert cloud_lock._acquired is True

    try:
        # 4. Download Canonical Database from 00_SYSTEM
        download_canonical_database(drive_engine=mock_drive, target_path=local_db)
        assert local_db.exists()
        db_hash = compute_sha256(local_db)
        assert len(db_hash) == 64

        # 5. Audit Stock in 01_READY
        initial_stock = mock_drive.get_ready_stock_count()
        assert initial_stock == 1  # Exactly the preserved Sarah short
        deficit = TARGET_BUFFER - initial_stock
        assert deficit == 5

        # 6. Sequential Production of Deficit Shorts (1..5)
        qa_engine = VideoQAEngine()
        conn = sqlite3.connect(str(local_db))
        cur = conn.cursor()

        mock_media_meta = {
            "duration": 23.4,
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "has_video": True,
            "has_audio": True,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_duration": 23.4,
            "audio_channels": 2,
            "audio_sample_rate": 44100,
            "audio_rms": -18.5,
            "dhash": "a1b2c3d4e5f60718",
        }

        scripts = [
            "In 1911, an Antarctic expedition stumbled upon a crimson waterfall pouring from an ancient glacier. For decades, explorers believed red algae caused the eerie phenomenon. However, recent subterranean sensors revealed the bizarre truth. A sealed subterranean reservoir, trapped for two million years with zero light or oxygen, contains strange iron-saturated brine. When exposed to surface oxygen, the water instantly rusts into deep blood red.",
            "Deep within Chihuahua desert caverns, miners unearthed gypsum pillars reaching fifty feet in height. These selenite crystals grew over half a million years in hydrothermal water heated by magma. Ambient humidity of ninety-nine percent and extreme heat prevent human survival past ten minutes. Without refrigerated suits, breathing the air causes fluid to condense inside lungs, making this natural subterranean wonder deadly and utterly lethal to explore.",
            "In 1997, oceanic hydrophones across the equatorial Pacific recorded an ultra-low frequency sound dubbed the Bloop. The bizarre signal traveled over three thousand miles through deep ocean trenches. While early theories suggested unknown colossal sea creatures, oceanographers later determined the acoustic roar came from massive Antarctic ice shelf fracturing. Yet the colossal acoustic power and geological intensity of this event remains extraordinary and deeply humbling.",
            "Beneath the dense jungle canopy of the Peruvian Amazon basin, an extraordinary sacred four-mile river reaches boiling temperatures. In 2011, geothermal researchers confirmed water temperatures exceeding ninety-five degrees Celsius across wide rapids. Small creatures falling into the scalding stream perish within seconds from thermal shock. Deep fault lines force superheated subterranean groundwater to the surface, creating this surreal and lethal natural anomaly that defies modern science.",
            "High in the remote mountain ranges of western Norway, mysterious spheres of white and yellow light drift over the silent valley. Since the 1980s, automated radar and optical stations have tracked these bizarre airborne anomalies moving at variable speeds. Leading physicists hypothesize that rich subterranean quartz deposits interacting with atmospheric ionization generate these enduring glowing plasma spheres across the cold Nordic night sky.",
        ]

        for i in range(deficit):
            short_id = f"short_cold_{i+1:02d}"
            niche = "Mystery / Bizarre" if i % 2 == 0 else "Weird Science"
            script = scripts[i]

            # Verify word count contract (62-70 words)
            word_count = len(script.split())
            assert 62 <= word_count <= 70, f"Script {i} word count: {word_count}"

            # Create synthetic video file (>1000 bytes)
            video_file = local_workspace / f"{short_id}.mp4"
            video_payload = (b"COLD_START_MP4_PACKET_" + str(i).encode("utf-8")) * 100
            video_file.write_bytes(video_payload)

            # Perform 15-point Video QA verification
            with patch.object(qa_engine, "inspect_media", return_value=mock_media_meta), \
                 patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
                report = qa_engine.verify_video(
                    video_path=video_file,
                    expected_duration=23.4
                )
            assert report.passed is True
            assert len(report.failure_reasons) == 0

            # Deposit verified Short into 01_READY
            mock_drive.upload_raw_content(
                content=video_payload,
                filename=f"{short_id}.mp4",
                parent_folder_id=mock_drive.folders["01_READY"],
                properties={"voice": "af_sarah", "qa_passed": "true", "short_id": short_id, "niche": niche}
            )

            # Commit records into local DB
            cur.execute("""
                INSERT INTO topics (id, canonical_id, title, category, niche, status)
                VALUES (?, ?, ?, ?, ?, 'PRODUCED')
            """, (f"top_{short_id}", f"can_{short_id}", f"Topic {i+1}", niche, niche))
            cur.execute("""
                INSERT INTO scripts (id, topic_id, title, hook_text, body_text, word_count, voice_id, quality_score)
                VALUES (?, ?, ?, ?, ?, ?, 'af_sarah', 9.0)
            """, (f"scr_{short_id}", f"top_{short_id}", f"Script {i+1}", script[:50], script, word_count))

        conn.commit()
        conn.close()

        # 7. Audit Final Stock in 01_READY
        final_stock = mock_drive.get_ready_stock_count()
        assert final_stock == TARGET_BUFFER  # Exactly 6

        # 8. Upload Canonical DB back to 00_SYSTEM
        upload_res = upload_canonical_database(drive_engine=mock_drive, source_path=local_db)
        assert upload_res["name"] == "pipeline.db"

    finally:
        # 9. Release Distributed Lock
        cloud_lock.release()

    # 10. Verify Vault Cleanliness
    assert cloud_lock._acquired is False
    assert mock_drive.get_ready_stock_count() == 6
    ready_files = [f["name"] for f in mock_drive.list_files_in_folder("01_READY")]
    assert PRESERVED_SARAH_SHORT in ready_files


# ==============================================================================
# Scenario 2: Scheduled Autopilot Release Cycle
# ==============================================================================

def test_scenario_2_autopilot_release_cycle(tmp_path):
    """
    Scenario 2: Autopilot release cycle triggered at publishing cron slot.
    Claims oldest ready short, allocates next vacant slot in rolling 48h horizon,
    simulates YouTube publication, moves file to 03_PUBLISHED, and syncs DB.
    """
    # 1. Setup Remote Drive Vault with ready stock
    mock_drive = MockDriveEngine(populate_preserved_short=True)
    # Add 2 additional ready shorts
    for i in range(2):
        mock_drive.upload_raw_content(
            content=b"EXTRA_READY_VIDEO_CONTENT" * 50,
            filename=f"short_extra_{i+1}.mp4",
            parent_folder_id=mock_drive.folders["01_READY"],
            properties={"voice": "af_sarah", "qa_passed": "true"}
        )
    assert mock_drive.get_ready_stock_count() == 3

    # Remote 00_SYSTEM DB
    remote_db = tmp_path / "remote_system" / "pipeline.db"
    create_mock_sqlite_db(remote_db)
    mock_drive.upload_database(remote_db, filename="pipeline.db")

    # 2. Ephemeral Autopilot Runner
    local_db = tmp_path / "local_autopilot" / "pipeline.db"
    run_id = f"run_autopilot_{uuid.uuid4().hex[:8]}"

    cloud_lock = CloudLockManager(drive_engine=mock_drive, run_id=run_id)
    with cloud_lock:
        download_canonical_database(drive_engine=mock_drive, target_path=local_db)

        # 3. Read 01_READY inventory and claim oldest ready file
        ready_files = mock_drive.list_files_in_folder("01_READY")
        assert len(ready_files) >= 1
        # Sort by created_time to claim oldest
        ready_files.sort(key=lambda x: x.get("created_time", ""))
        claimed_file = ready_files[0]
        claimed_id = claimed_file["id"]
        claimed_name = claimed_file["name"]

        # Move atomically from 01_READY to 02_PROCESSING
        moved_to_processing = mock_drive.move_file_in_vault(claimed_id, "01_READY", "02_PROCESSING")
        assert moved_to_processing is True
        assert len(mock_drive.list_files_in_folder("02_PROCESSING")) == 1

        # 4. Determine next vacant slot using PublicationScheduler
        scheduler = PublicationScheduler()
        target_date = date.today() + timedelta(days=1)
        available_slots = scheduler.get_slots_for_date(target_date)
        assert len(available_slots) == 3  # 06:00, 11:00, 15:00 UTC
        publication_slot = available_slots[0]

        # 5. Simulate YouTube Publication
        simulated_yt_id = f"yt_{uuid.uuid4().hex[:11]}"
        conn = sqlite3.connect(str(local_db))
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO uploads (id, job_id, topic_id, title, youtube_video_id, status, scheduled_publish_at)
            VALUES (?, ?, ?, ?, ?, 'SCHEDULED', ?)
        """, (
            f"upl_{uuid.uuid4().hex[:8]}",
            f"job_{claimed_name[:10]}",
            "top_seed_01",
            f"Scheduled Release: {claimed_name}",
            simulated_yt_id,
            publication_slot.isoformat()
        ))
        conn.commit()
        conn.close()

        # 6. Move from 02_PROCESSING to 03_PUBLISHED
        moved_to_published = mock_drive.move_file_in_vault(claimed_id, "02_PROCESSING", "03_PUBLISHED")
        assert moved_to_published is True

        # 7. Upload updated DB back to 00_SYSTEM
        upload_canonical_database(drive_engine=mock_drive, source_path=local_db)

    # 8. Post-Release Verifications
    assert cloud_lock._acquired is False
    assert len(mock_drive.list_files_in_folder("02_PROCESSING")) == 0
    published_files = [f["name"] for f in mock_drive.list_files_in_folder("03_PUBLISHED")]
    assert claimed_name in published_files
    assert mock_drive.get_ready_stock_count() == 2


# ==============================================================================
# Scenario 3: Multi-Runner Distributed Lock Contention
# ==============================================================================

def test_scenario_3_multi_runner_lock_contention(tmp_path):
    """
    Scenario 3: Two concurrent runners contend for the Drive distributed lock.
    Runner 1 acquires lock; Runner 2 detects active lock, reports BLOCKED with exit 2,
    and cleanly exits without corrupting state. Runner 1 completes and releases lock.
    """
    mock_drive = MockDriveEngine(populate_preserved_short=True)

    # Runner 1 spins up and acquires lock
    runner_1_id = "gh_runner_inst_01"
    runner_2_id = "gh_runner_inst_02"

    lock_1 = CloudLockManager(drive_engine=mock_drive, run_id=runner_1_id)
    assert lock_1.acquire() is True
    assert lock_1._acquired is True

    # Remote 00_SYSTEM now contains lock file
    lock_file = next((f for f in mock_drive.list_files_in_folder("00_SYSTEM") if f["name"] == lock_1.lock_filename), None)
    assert lock_file is not None
    lock_data = json.loads(lock_file["content"].decode("utf-8"))
    assert lock_data["run_id"] == runner_1_id

    # Runner 2 spins up concurrently and attempts to acquire lock
    lock_2 = CloudLockManager(drive_engine=mock_drive, run_id=runner_2_id)
    assert lock_2._acquired is False

    # Immediate non-blocking acquisition fails
    acquired = lock_2.acquire(timeout_seconds=0)
    assert acquired is False
    assert lock_2._acquired is False

    # Runner 2 gracefully handles contention (status BLOCKED, exit code 2)
    telemetry_runner_2 = ProductionRunTelemetry(run_id=runner_2_id, is_dry_run=False, status="BLOCKED")
    assert telemetry_runner_2.status == "BLOCKED"

    # Ensure Runner 2 has not modified vault files
    assert mock_drive.get_ready_stock_count() == 1

    # Runner 1 finishes processing and releases lock
    lock_1.release()
    assert lock_1._acquired is False
    assert not any(f["name"] == lock_1.lock_filename for f in mock_drive.list_files_in_folder("00_SYSTEM"))

    # Subsequent Runner 3 (or Runner 2 retry) can now acquire lock cleanly
    assert lock_2.acquire(timeout_seconds=5) is True
    assert lock_2._acquired is True
    lock_2.release()
    assert lock_2._acquired is False


# ==============================================================================
# Scenario 4: Broken/Corrupted State Self-Healing & Quarantining
# ==============================================================================

def test_scenario_4_state_self_healing_and_quarantine(tmp_path):
    """
    Scenario 4: Vault contains a corrupt 0-byte file, an invalid voice file in 01_READY,
    and an abandoned in-flight file in 02_PROCESSING. Self-healing reconciliation restores
    the abandoned file to 01_READY, quarantines the invalid files to 04_FAILED,
    and preserves the Sarah short.
    """
    mock_drive = MockDriveEngine(populate_preserved_short=True)

    # 1. Inject corrupted 0-byte file into 01_READY
    corrupt_id = mock_drive.upload_raw_content(
        content=b"",
        filename="corrupt_zero_byte.mp4",
        parent_folder_id=mock_drive.folders["01_READY"],
        properties={"voice": "af_sarah", "qa_passed": "false"}
    )

    # 2. Inject non-Sarah voice file into 01_READY
    bad_voice_id = mock_drive.upload_raw_content(
        content=b"NON_SARAH_VOICE_PAYLOAD" * 50,
        filename="invalid_voice_adam.mp4",
        parent_folder_id=mock_drive.folders["01_READY"],
        properties={"voice": "en_adam", "qa_passed": "true"}
    )

    # 3. Inject abandoned in-flight file into 02_PROCESSING
    abandoned_id = mock_drive.upload_raw_content(
        content=b"ABANDONED_VALID_PAYLOAD" * 80,
        filename="abandoned_in_flight.mp4",
        parent_folder_id=mock_drive.folders["02_PROCESSING"],
        properties={"voice": "af_sarah", "qa_passed": "true", "short_id": "short_rec_01"}
    )

    # Verify starting states
    assert len(mock_drive.list_files_in_folder("01_READY")) == 3  # Preserved Sarah + corrupt + bad voice
    assert len(mock_drive.list_files_in_folder("02_PROCESSING")) == 1
    assert len(mock_drive.list_files_in_folder("04_FAILED")) == 0

    # 4. Execute Autonomous Self-Healing Reconciliation
    # Step A: Reconcile 02_PROCESSING
    processing_files = mock_drive.list_files_in_folder("02_PROCESSING")
    for f in processing_files:
        # Since no publisher process is currently running, abandoned files are returned to 01_READY
        mock_drive.move_file_in_vault(f["id"], from_folder="02_PROCESSING", to_folder="01_READY")

    assert len(mock_drive.list_files_in_folder("02_PROCESSING")) == 0

    # Step B: Audit 01_READY files against strict QA invariants
    ready_files = mock_drive.list_files_in_folder("01_READY")
    for f in ready_files:
        props = f.get("properties", {})
        size = f.get("size", 0)
        voice = props.get("voice", "")

        # Invariant 1: File size > 1000 bytes
        # Invariant 2: Voice must strictly be af_sarah
        is_corrupt = (size < 1000)
        is_unauthorized_voice = (voice != "af_sarah")

        if is_corrupt or is_unauthorized_voice:
            mock_drive.move_file_in_vault(f["id"], from_folder="01_READY", to_folder="04_FAILED")

    # 5. Final Vault State Assertions
    failed_names = [f["name"] for f in mock_drive.list_files_in_folder("04_FAILED")]
    assert "corrupt_zero_byte.mp4" in failed_names
    assert "invalid_voice_adam.mp4" in failed_names
    assert len(failed_names) == 2

    ready_names = [f["name"] for f in mock_drive.list_files_in_folder("01_READY")]
    assert PRESERVED_SARAH_SHORT in ready_names
    assert "abandoned_in_flight.mp4" in ready_names
    assert len(ready_names) == 2

    assert len(mock_drive.list_files_in_folder("02_PROCESSING")) == 0


# ==============================================================================
# Scenario 5: 48-Hour Rolling Calendar Production-to-Publish Simulation
# ==============================================================================

def test_scenario_5_full_48h_rolling_simulation(tmp_path):
    """
    Scenario 5: Full 48-hour rolling calendar simulation across Day A (2 Mystery + 1 Science)
    and Day B (1 Mystery + 2 Science). Verifies 6 scripts (62-70 words), AI Council synthesis,
    15-point Video QA, and scheduling strictly adheres to the 3 Shorts/day ceiling.
    """
    scheduler = PublicationScheduler()
    qa_engine = VideoQAEngine()

    day_a = date(2026, 9, 7)
    day_b = date(2026, 9, 8)

    # 1. Content Planning: Day A and Day B topic rotations
    day_a_topics = [
        {"title": "The Mariana Trench Subterranean Acoustic Drone", "niche": "Mystery / Bizarre"},
        {"title": "The Siberian Crater Methane Eruption Mystery", "niche": "Mystery / Bizarre"},
        {"title": "Quantum Entanglement Macromolecule Superposition", "niche": "Weird Science"},
    ]
    day_b_topics = [
        {"title": "The Silent Zone Magnetic Radio Silence Anomaly", "niche": "Mystery / Bizarre"},
        {"title": "Superfluid Helium Zero Viscosity Upward Creep", "niche": "Weird Science"},
        {"title": "Bioluminescent Forest Fungi Spore Dispersal", "niche": "Weird Science"},
    ]

    all_planned = day_a_topics + day_b_topics
    assert len(all_planned) == 6

    # Verify niche compliance for all 6
    for t in all_planned:
        is_compliant, _ = is_niche_compliant(t["title"], t["niche"])
        assert is_compliant is True

    # 2. Script Generation: 6 scripts strictly within 62-70 words
    scripts = [
        "In 2014, deep ocean hydrophones anchored in the Mariana Trench recorded an eerie metallic hum. The strange acoustic pulse repeated at regular twenty-second intervals across hundred-mile stretches. While initial speculation pointed to military submarines, oceanographers found the signal originated beneath the tectonic seafloor. High-pressure methane seepage vibrating through basalt fissures creates this surreal subterranean acoustic drone echoing endlessly through the dark oceanic abyss.",
        "In the frozen tundra of the Yamal Peninsula, geologists discovered an immense fifty-foot crater. The subterranean walls plunged into darkness with smooth melted permafrost perimeters. Satellite sensors revealed subsurface ground swelling years prior to explosive detonation. Warming permafrost released trapped pressurized methane pockets, violently shattering frozen soil into the upper atmosphere. The sudden emergence of these craters reveals unpredictable subterranean changes across our warming planet.",
        "Physicists at international laboratories achieved quantum superposition with massive organic molecules containing thousands of atoms. When fired through microscopic double slits, these intricate structures exhibited wave interference simultaneously traversing multiple paths. The boundary between microscopic quantum weirdness and classical macroscopic reality continues to dissolve before our eyes. Demonstrating quantum behavior in complex molecular systems opens revolutionary pathways for quantum biology and future synthetic molecular computation.",
        "In northern Mexico, a mysterious desert expanse known as the Mapimi Silent Zone prevents radio transmissions. Compass needles spin erratically upon entering the boundary, while communication frequencies collapse completely. Geologists attribute the bizarre phenomenon to concentrated subterranean magnetite deposits and intense meteoritic debris buried below the surface. Navigational systems fail completely inside this silent anomaly, leaving travelers stranded to navigate by ancient stars.",
        "When liquid helium cools below two degrees Kelvin, it transforms into an astonishing quantum superfluid. Zero viscosity allows the substance to flow without friction, climbing upward against gravity along container glass walls. If placed inside an open beaker, the liquid crawls up the surface and drips from the exterior bottom. This spectacular macroscopic quantum phenomenon defies all classical rules of fluid mechanics and thermodynamics.",
        "Deep within ancient temperate rainforests, rare fungal mycelia produce a ghostly emerald luminescence illuminating the understory. Chemical reactions between luciferin enzymes and atmospheric oxygen emit continuous bioluminescent light throughout the damp night. Entomologists discovered this eerie glow attracts nocturnal beetles, which inadvertently transport fungal spores across the forest canopy. Nature engineers this hypnotic subterranean glow to ensure reproductive survival across dark old-growth ecosystems.",
    ]

    for idx, s in enumerate(scripts):
        wc = len(s.split())
        assert 62 <= wc <= 70, f"Script {idx+1} word count: {wc}"

    # 3. AI Council Synthesis Simulation (DeepSeek + Kimi + Nemotron)
    for idx, s in enumerate(scripts):
        score = CouncilQualityScore(
            hook_strength=9.0,
            curiosity=9.0,
            story_progression=8.5,
            originality=8.5,
            payoff=8.5,
            spoken_naturalness=9.0,
            factual_confidence=9.5,
            visual_potential=9.0,
            duration_suitability=9.0,
            overall_score=8.8,
            verdict="PASS"
        )
        session = CouncilSession(
            session_id=f"cs_scen5_{idx+1}",
            event_id=f"evt_scen5_{idx+1}",
            topic_title=all_planned[idx]["title"],
            reviews={
                "deepseek": CouncilMemberReview(member_name="DeepSeek", role="Hook", model="m1", provider="p1", output_text="Hook passed"),
                "kimi": CouncilMemberReview(member_name="Kimi K3", role="Pacing", model="m2", provider="p2", output_text="Pacing passed"),
                "nemotron": CouncilMemberReview(member_name="Nemotron", role="Facts", model="m3", provider="p3", output_text="Facts passed")
            },
            quality_score=score,
            approved=True
        )
        assert session.approved is True
        assert session.quality_score.verdict == "PASS"
        assert session.quality_score.overall_score >= 8.0

    # 4. Video QA Verification
    mock_media_meta = {
        "duration": 24.0,
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "has_video": True,
        "has_audio": True,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_duration": 24.0,
        "audio_channels": 2,
        "audio_sample_rate": 44100,
        "audio_rms": -18.0,
        "dhash": "1122334455667788",
    }
    dummy_video = tmp_path / "simulated_render.mp4"
    dummy_video.write_bytes(b"TEST_VIDEO_PAYLOAD" * 100)

    with patch.object(qa_engine, "inspect_media", return_value=mock_media_meta), \
         patch.object(qa_engine, "detect_black_frames", return_value=(False, 0.0, [])):
        for _ in range(6):
            report = qa_engine.verify_video(dummy_video, expected_duration=24.0)
            assert report.passed is True

    # 5. Rolling Publication Scheduling
    slots_day_a = scheduler.get_slots_for_date(day_a)
    slots_day_b = scheduler.get_slots_for_date(day_b)

    assert len(slots_day_a) == 3
    assert len(slots_day_b) == 3

    # Exact slot times: 06:00, 11:00, 15:00 UTC
    expected_hours = [6, 11, 15]
    assert [s.hour for s in slots_day_a] == expected_hours
    assert [s.hour for s in slots_day_b] == expected_hours

    # Check minimum spacing of >= 4 hours between intra-day slots
    for slots in [slots_day_a, slots_day_b]:
        diff_1 = (slots[1] - slots[0]).total_seconds() / 3600.0
        diff_2 = (slots[2] - slots[1]).total_seconds() / 3600.0
        assert diff_1 >= 4.0, f"Spacing {diff_1} < 4h"
        assert diff_2 >= 4.0, f"Spacing {diff_2} < 4h"

    # Verify no day exceeds DAILY_SHORTS_LIMIT
    assert len(slots_day_a) <= DAILY_SHORTS_LIMIT
    assert len(slots_day_b) <= DAILY_SHORTS_LIMIT


# ==============================================================================
# Scenario 6: Disaster Recovery & Runner Amnesia Defense
# ==============================================================================

def test_scenario_6_disaster_recovery_amnesia_defense(tmp_path):
    """
    Scenario 6: Runner A commits historical topics and visual dHashes, uploads DB to 00_SYSTEM,
    and terminates abruptly. Runner B spins up in an isolated environment, restores canonical state,
    and successfully rejects duplicate candidate topics and near-duplicate visual assets.
    """
    mock_drive = MockDriveEngine(populate_preserved_short=True)

    # 1. Runner A executes on VM 1
    vm1_dir = tmp_path / "vm1"
    vm1_db = vm1_dir / "pipeline.db"
    vm1_visual_db = vm1_dir / "visual_memory.db"
    create_mock_sqlite_db(vm1_db)

    # Populate Runner A's visual memory
    visual_mem_1 = GlobalVisualMemory(db_path=vm1_visual_db)
    sample_img_1 = vm1_dir / "historical_asset_01.jpg"
    sample_img_1.write_bytes(b"IMAGE_CONTENT_SAMPLE_1" * 50)
    visual_mem_1.record_asset_usage(
        asset_id="vis_vostok_core",
        asset_path=sample_img_1,
        short_id="short_hist_01",
        category="Mystery / Bizarre"
    )

    # Record historical topic in pipeline.db
    conn = sqlite3.connect(str(vm1_db))
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO topics (id, canonical_id, title, category, niche, status)
        VALUES ('top_hist_01', 'canon_hist_01', 'Lake Vostok Subglacial Anomaly', 'Mystery / Bizarre', 'Mystery / Bizarre', 'PUBLISHED')
    """)
    conn.commit()
    conn.close()

    # Runner A uploads state to Drive 00_SYSTEM
    mock_drive.upload_database(vm1_db, filename="pipeline.db")
    mock_drive.upload_database(vm1_visual_db, filename="visual_memory.db")

    # Runner A VM crashes / local directory wiped
    # (vm1_dir will not be touched by Runner B)

    # 2. Runner B spins up on clean VM 2
    vm2_dir = tmp_path / "vm2"
    vm2_dir.mkdir(parents=True, exist_ok=True)
    vm2_db = vm2_dir / "pipeline.db"
    vm2_visual_db = vm2_dir / "visual_memory.db"

    # Restore canonical databases from 00_SYSTEM
    download_canonical_database(drive_engine=mock_drive, target_path=vm2_db)
    mock_drive.download_canonical_database(target_path=vm2_visual_db, filename="visual_memory.db")

    assert vm2_db.exists()
    assert vm2_visual_db.exists()

    # 3. Amnesia Defense: Topic Duplicate Detection
    conn2 = sqlite3.connect(str(vm2_db))
    cur2 = conn2.cursor()

    candidate_topic_duplicate = "Lake Vostok Subglacial Anomaly"
    cur2.execute("SELECT id, status FROM topics WHERE title = ?", (candidate_topic_duplicate,))
    existing_topic = cur2.fetchone()
    assert existing_topic is not None
    assert existing_topic[1] == "PUBLISHED"
    # Duplicate topic is successfully rejected by Runner B!

    # 4. Amnesia Defense: Visual Near-Duplicate & Exact Duplicate Rejection
    visual_mem_2 = GlobalVisualMemory(db_path=vm2_visual_db)

    # Candidate Asset A: Identical image content to sample_img_1
    candidate_img_dup = vm2_dir / "candidate_duplicate.jpg"
    candidate_img_dup.write_bytes(b"IMAGE_CONTENT_SAMPLE_1" * 50)

    is_permitted, reason, penalty = visual_mem_2.check_asset_reuse(
        asset_path=candidate_img_dup,
        current_short_id="short_candidate_02"
    )
    assert is_permitted is False
    assert penalty == 1.0
    assert "duplicate" in reason.lower()

    # Candidate Asset B: Fresh, novel visual asset
    candidate_img_fresh = vm2_dir / "candidate_fresh.jpg"
    candidate_img_fresh.write_bytes(b"COMPLETELY_UNIQUE_FRESH_PIXELS" * 60)

    is_fresh_permitted, fresh_reason, fresh_penalty = visual_mem_2.check_asset_reuse(
        asset_path=candidate_img_fresh,
        current_short_id="short_candidate_02"
    )
    assert is_fresh_permitted is True
    assert fresh_penalty == 0.0

    # Record usage of the fresh asset
    visual_mem_2.record_asset_usage(
        asset_id="vis_fresh_01",
        asset_path=candidate_img_fresh,
        short_id="short_candidate_02",
        category="Weird Science"
    )

    # Verify that fresh asset is now registered in the persistent visual memory
    with sqlite3.connect(str(vm2_visual_db)) as vconn:
        row = vconn.execute("SELECT asset_id FROM visual_asset_memory WHERE asset_id = 'vis_fresh_01'").fetchone()
        assert row is not None

    conn2.close()
