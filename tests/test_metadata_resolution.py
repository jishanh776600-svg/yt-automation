"""
Tests for Vault Metadata Resolution & Elimination of Collision Fallback.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Topic, RenderedVideoRecord
from main import resolve_vault_file_metadata


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_resolve_from_explicit_properties():
    candidate = {
        "id": "file_001",
        "name": "short_man_abc.mp4",
        "properties": {
            "title": "The Tunguska Blast of 1908",
            "tags": "tunguska,history,blast"
        }
    }
    meta = resolve_vault_file_metadata(candidate)
    assert meta["title"] == "The Tunguska Blast of 1908"
    assert "tunguska" in meta["tags"]


def test_resolve_from_topic_via_event_id(test_db):
    top = Topic(
        id="top_001",
        title="The Flannan Isles Lighthouse Mystery",
        summary="Three lighthouse keepers disappeared without a trace in 1900.",
        event_id="evt_flannan_isles"
    )
    test_db.add(top)
    test_db.commit()

    candidate = {
        "id": "file_002",
        "name": "short_man_flannan.mp4",
        "properties": {
            "event_id": "evt_flannan_isles"
        }
    }
    meta = resolve_vault_file_metadata(candidate, db=test_db)
    assert meta["title"] == "The Flannan Isles Lighthouse Mystery"
    assert "lighthouse keepers" in meta["description"]


def test_resolve_from_topic_via_manifest_rendered_record(test_db):
    top = Topic(
        id="top_002",
        title="The Mystery of the Green Children of Woolpit",
        summary="Two children with green skin appeared in Woolpit.",
        event_id="evt_green_children"
    )
    rec = RenderedVideoRecord(
        id="rend_002",
        manifest_id="man_green_123",
        event_id="evt_green_children",
        script_id="scr_002",
        video_path="short_man_green.mp4",
        duration_seconds=24.0,
        qa_status="PASSED"
    )
    test_db.add_all([top, rec])
    test_db.commit()

    candidate = {
        "id": "file_003",
        "name": "short_man_green.mp4",
        "properties": {
            "manifest_id": "man_green_123"
        }
    }
    meta = resolve_vault_file_metadata(candidate, db=test_db)
    assert meta["title"] == "The Mystery of the Green Children of Woolpit"


def test_no_generic_bizarre_mystery_fallback():
    # If topic is not in DB and properties have only event_id
    candidate = {
        "id": "file_004",
        "name": "short_man_unknown.mp4",
        "properties": {
            "event_id": "evt_hist_the_disappearance_of_the_uss_cyclops"
        }
    }
    meta = resolve_vault_file_metadata(candidate)
    # Must NOT be "Bizarre Real-World Mystery"
    assert meta["title"] != "Bizarre Real-World Mystery"
    assert "Uss Cyclops" in meta["title"]
