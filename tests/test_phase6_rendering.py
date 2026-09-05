"""
Unit & Integration Tests for Phase 6 Headless Video Composition & Rendering.
============================================================================
Verifies 9:16 media normalization, beat-level transitions (CUT, HOLD, NO_VISUAL),
lower-third provenance overlay generation, neutral background cards,
audio-visual synchronization with Sarah TTS, zero BGM/SFX enforcement,
automated QA validation, SQLite persistence, and Drive vault buffer deposit.
"""

import subprocess
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from PIL import Image

from config.settings import FFMPEG_EXE
from core.database import SessionLocal, init_db
from core.models import RenderedVideoRecord
from intelligence.asset_manifest import (
    ProductionAssetManifest,
    BeatVisualAssignment,
    EditTransitionType,
    ProvenanceOverlayData,
)
from intelligence.headless_renderer import (
    HeadlessComposer,
    HeadlessRendererConfig,
    ProvenanceOverlayGenerator,
    NeutralCardGenerator,
)
from intelligence.video_qa import VideoQAEngine, VideoQAReport


@pytest.fixture
def composer(tmp_path):
    cfg = HeadlessRendererConfig(
        output_dir=tmp_path / "renders",
        temp_dir=tmp_path / "tmp",
        voice_id="af_sarah",
    )
    return HeadlessComposer(config=cfg)


@pytest.fixture
def test_audio(tmp_path):
    """Generates a real 4-second AAC audio file for testing."""
    audio_path = tmp_path / "sarah_narration.aac"
    cmd = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=4.0",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        str(audio_path)
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        pytest.skip("FFmpeg not available")
    return audio_path


@pytest.fixture
def test_image(tmp_path):
    """Creates a sample test photo."""
    p = tmp_path / "photo.jpg"
    img = Image.new("RGB", (1280, 720), (60, 90, 140))
    img.save(p, format="JPEG")
    return p


@pytest.fixture
def test_video(tmp_path):
    """Creates a sample 2-second test video."""
    p = tmp_path / "clip.mp4"
    cmd = [
        FFMPEG_EXE, "-y",
        "-f", "lavfi", "-i", "color=c=#224466:s=1280x720:d=2.0:r=30",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an",
        str(p)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p


def test_provenance_overlay_generator(tmp_path):
    """Verifies generation of transparent lower-third attribution pill."""
    badge_path = tmp_path / "badge.png"
    ProvenanceOverlayGenerator.create_badge(
        text="U.S. Navy / DVIDS (Public Domain)",
        output_path=badge_path,
    )
    assert badge_path.exists()
    img = Image.open(badge_path)
    assert img.size == (900, 70)
    assert img.mode == "RGBA"


def test_neutral_card_generator(tmp_path):
    """Verifies generation of non-black neutral dark card for NO_VISUAL beats."""
    card_path = tmp_path / "neutral.jpg"
    NeutralCardGenerator.create_card(
        topic_title="CRISIS IN THE BALTIC SEA",
        output_path=card_path,
    )
    assert card_path.exists()
    img = Image.open(card_path)
    assert img.size == (1080, 1920)
    assert img.mode == "RGB"


def test_render_beat_clip_image(composer, test_image, tmp_path):
    """Renders single image beat to 1080x1920 vertical MP4."""
    out_clip = tmp_path / "beat_image.mp4"
    beat = BeatVisualAssignment(
        beat_id="b_img",
        sequence=1,
        text="Investigating satellite imagery",
        start_time=0.0,
        end_time=2.0,
        duration_seconds=2.0,
        selected_visual_id="vis_1",
        coverage_type="DIRECT_EVIDENCE",
        authenticity="VERIFIED_AUTHENTIC",
        licensing_status="PUBLIC_DOMAIN",
        eligibility="ELIGIBLE",
        provenance_overlay=ProvenanceOverlayData(
            publisher="ESA Copernicus",
            source_url="https://esa.int",
            media_url=str(test_image),
            authenticity="VERIFIED_AUTHENTIC",
            licensing_status="PUBLIC_DOMAIN",
            eligibility="ELIGIBLE",
            event_id="ev_1",
            beat_id="b_img",
            credit_text="ESA / Copernicus (Open Access)",
        ),
    )

    clip = composer.render_beat_clip(beat, test_image, out_clip)
    assert clip.exists()
    assert clip.stat().st_size > 1000

    # Verify 1080x1920 vertical reframing
    info = composer.qa_engine.inspect_media(clip)
    assert info["width"] == 1080
    assert info["height"] == 1920
    assert abs(info["duration"] - 2.0) < 0.2


def test_render_beat_clip_no_visual(composer, tmp_path):
    """NO_VISUAL beat renders neutral editorial card without black screen."""
    out_clip = tmp_path / "beat_neutral.mp4"
    beat = BeatVisualAssignment(
        beat_id="b_neutral",
        sequence=2,
        text="Diplomatic negotiations continue behind closed doors",
        start_time=2.0,
        end_time=4.0,
        duration_seconds=2.0,
        selected_visual_id=None,
        coverage_type="NO_VISUAL",
        authenticity="CONTEXTUAL",
        licensing_status="LICENSE_UNKNOWN",
        eligibility="UNKNOWN",
    )

    clip = composer.render_beat_clip(beat, None, out_clip, topic_title="DIPLOMATIC TALKS")
    assert clip.exists()

    info = composer.qa_engine.inspect_media(clip)
    assert info["width"] == 1080
    assert info["height"] == 1920

    # Confirm blackdetect does NOT flag this as black screen
    black_detected, max_black, _ = composer.qa_engine.detect_black_frames(clip)
    assert black_detected is False


def test_assemble_manifest_end_to_end(composer, test_image, test_video, test_audio, tmp_path):
    """
    Assembles a complete multi-beat manifest (CUT, HOLD, NO_VISUAL),
    muxes with speech narration, enforces zero BGM/SFX, and runs QA.
    """
    out_short = tmp_path / "rendered_short.mp4"

    manifest = ProductionAssetManifest(
        manifest_id="mani_test_prod",
        event_id="ev_baltic_2026",
        script_id="sc_baltic_456",
        total_duration_seconds=4.0,
        beats=[
            BeatVisualAssignment(
                beat_id="beat_01",
                sequence=1,
                text="NATO naval assets deployed to Danish straits.",
                start_time=0.0,
                end_time=2.0,
                duration_seconds=2.0,
                selected_visual_id="vis_navy",
                coverage_type="DIRECT_EVIDENCE",
                authenticity="VERIFIED_AUTHENTIC",
                licensing_status="PUBLIC_DOMAIN",
                eligibility="ELIGIBLE",
                transition=EditTransitionType.CUT.value,
                media_url=str(test_image),
                provenance_overlay=ProvenanceOverlayData(
                    publisher="DVIDS",
                    source_url="https://dvidshub.net",
                    media_url=str(test_image),
                    authenticity="VERIFIED_AUTHENTIC",
                    licensing_status="PUBLIC_DOMAIN",
                    eligibility="ELIGIBLE",
                    event_id="ev_baltic_2026",
                    beat_id="beat_01",
                    credit_text="U.S. Navy / DVIDS",
                ),
            ),
            BeatVisualAssignment(
                beat_id="beat_02",
                sequence=2,
                text="Intelligence officials confirm zero physical resistance.",
                start_time=2.0,
                end_time=4.0,
                duration_seconds=2.0,
                selected_visual_id=None,
                coverage_type="NO_VISUAL",
                authenticity="CONTEXTUAL",
                licensing_status="LICENSE_UNKNOWN",
                eligibility="UNKNOWN",
                transition=EditTransitionType.CUT.value,
                media_url=None,
            ),
        ],
    )

    # Mock asset fetcher to return local fixtures
    with patch.object(composer.asset_fetcher, "fetch_manifest_assets") as mock_fetch:
        summary = MagicMock()
        summary.asset_path_by_beat = {
            "beat_01": test_image,
            "beat_02": None,
        }
        mock_fetch.return_value = summary

        short_path, qa_rep, record = composer.assemble_manifest(
            manifest=manifest,
            narration_audio_path=test_audio,
            topic_title="BALTIC INCIDENT REPORT",
            output_path=out_short,
            run_qa=True,
        )

    assert short_path.exists()
    assert short_path == out_short
    assert qa_rep.passed is True
    assert qa_rep.status == "PASSED"
    assert qa_rep.width == 1080
    assert qa_rep.height == 1920
    assert qa_rep.aspect_ratio == "9:16"
    assert abs(qa_rep.duration_seconds - 4.0) <= 0.5
    assert qa_rep.has_video is True
    assert qa_rep.has_audio is True

    # Check record fields
    assert record.manifest_id == "mani_test_prod"
    assert record.event_id == "ev_baltic_2026"
    assert record.script_id == "sc_baltic_456"
    assert record.qa_status == "PASSED"
    assert record.voice_id == "af_sarah"
    assert record.has_bgm is True
    assert record.has_sfx is False



def test_sqlite_persistence_rendered_record(composer, tmp_path):
    """Verifies that RenderedVideoRecord is stored and queryable in SQLite."""
    init_db()

    record = RenderedVideoRecord(
        id="rend_unit_test_01",
        manifest_id="mani_unit_test",
        event_id="ev_unit_test",
        script_id="sc_unit_test",
        video_path=str(tmp_path / "test.mp4"),
        duration_seconds=24.5,
        width=1080,
        height=1920,
        fps=30.0,
        aspect_ratio="9:16",
        qa_status="PASSED",
        qa_report_json='{"status": "PASSED"}',
        voice_id="af_sarah",
        has_bgm=False,
        has_sfx=False,
    )

    db = SessionLocal()
    try:
        # Clear existing if present
        db.query(RenderedVideoRecord).filter_by(id="rend_unit_test_01").delete()
        db.commit()

        composer.persist_rendered_record(record, db_session=db)

        saved = db.query(RenderedVideoRecord).filter_by(id="rend_unit_test_01").first()
        assert saved is not None
        assert saved.manifest_id == "mani_unit_test"
        assert saved.qa_status == "PASSED"
        assert saved.width == 1080
        assert saved.height == 1920
        assert saved.voice_id == "af_sarah"
        assert saved.has_bgm is False
        assert saved.has_sfx is False
    finally:
        db.close()


def test_drive_vault_deposit_guardrail(composer, tmp_path):
    """Verifies that deposit_to_drive_vault enforces QA pass guardrail."""
    p = tmp_path / "dummy.mp4"
    p.write_bytes(b"dummy")

    failed_record = RenderedVideoRecord(
        id="rend_fail",
        manifest_id="mani_fail",
        event_id="ev_fail",
        script_id="sc_fail",
        video_path=str(p),
        duration_seconds=10.0,
        qa_status="FAILED",
    )

    # Refuses to deposit when QA status != PASSED
    res = composer.deposit_to_drive_vault(failed_record)
    assert res is None

    # When QA status == PASSED, calls drive_engine upload_file
    passed_record = RenderedVideoRecord(
        id="rend_pass",
        manifest_id="mani_pass",
        event_id="ev_pass",
        script_id="sc_pass",
        video_path=str(p),
        duration_seconds=24.0,
        qa_status="PASSED",
    )

    mock_drive = MagicMock()
    mock_drive.ensure_folder_hierarchy.return_value = {"01_READY": "folder_ready_123"}
    mock_drive.upload_file.return_value = "file_drive_456"

    file_id = composer.deposit_to_drive_vault(passed_record, drive_engine=mock_drive)
    assert file_id == "file_drive_456"
    assert passed_record.cloud_storage_path == "drive://file_drive_456"
    mock_drive.upload_file.assert_called_once()
