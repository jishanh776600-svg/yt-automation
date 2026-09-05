"""
Tests for GlobalVisualMemory & ShortDuplicateGuard.
"""
import pytest
from pathlib import Path
from PIL import Image

from intelligence.visual_memory import (
    GlobalVisualMemory,
    compute_exact_hash,
    compute_dhash,
    hamming_distance,
)
from intelligence.short_duplicate_guard import (
    ShortDuplicateGuard,
    tokenize_shingles,
    jaccard_similarity,
)


@pytest.fixture
def test_images(tmp_path):
    img1 = tmp_path / "img1.png"
    Image.new("RGB", (100, 100), color="blue").save(img1)

    img2 = tmp_path / "img2.png"
    Image.new("RGB", (100, 100), color="blue").save(img2)

    img3 = tmp_path / "img3.png"
    im3 = Image.new("RGB", (100, 100), color="white")
    from PIL import ImageDraw
    d = ImageDraw.Draw(im3)
    d.rectangle([20, 20, 80, 80], fill="black")
    im3.save(img3)

    return img1, img2, img3



def test_visual_memory_exact_and_phash_detection(tmp_path, test_images):
    img1, img2, img3 = test_images
    db_path = tmp_path / "visual_memory.db"
    vm = GlobalVisualMemory(db_path=db_path)

    # Initially permitted
    is_ok, reason, penalty = vm.check_asset_reuse(img1, current_short_id="short_01")
    assert is_ok is True
    assert penalty == 0.0

    # Record img1
    vm.record_asset_usage(
        asset_id="asset_01",
        asset_path=img1,
        source="pexels",
        short_id="short_01",
        category="Short"
    )

    # Exact duplicate check (img2 has exact same content as img1)
    is_ok, reason, penalty = vm.check_asset_reuse(img2, current_short_id="short_02")
    assert is_ok is False
    assert penalty >= 0.85
    assert "Exact duplicate" in reason


    # Different image (img3 is red)
    is_ok, reason, penalty = vm.check_asset_reuse(img3, current_short_id="short_02")
    assert is_ok is True
    assert penalty == 0.0


def test_short_duplicate_guard_detection(tmp_path):
    db_path = tmp_path / "fingerprints.db"
    guard = ShortDuplicateGuard(db_path=db_path)

    title = "Mysterious Oceanic Anomaly Detected by Research Team"
    script = "Scientists documented an unprecedented deep sea phenomenon near the Mariana Trench."
    duration = 23.4
    assets = ["asset_a", "asset_b", "asset_c"]

    # Initial uniqueness check
    is_uniq, reason, metrics = guard.verify_short_uniqueness(
        topic_title=title,
        script_text=script,
        duration_seconds=duration,
        asset_ids=assets,
        short_id="short_alpha"
    )
    assert is_uniq is True

    # Record first Short
    guard.record_short(
        short_id="short_alpha",
        topic_title=title,
        script_text=script,
        duration_seconds=duration,
        asset_ids=assets
    )

    # Test identical title/script rejection
    is_uniq, reason, metrics = guard.verify_short_uniqueness(
        topic_title=title,
        script_text=script,
        duration_seconds=duration,
        asset_ids=["asset_d", "asset_e"],
        short_id="short_beta"
    )
    assert is_uniq is False
    assert "Duplicate topic title" in reason or "Duplicate script content" in reason

    # Test completely different Short passes
    is_uniq, reason, metrics = guard.verify_short_uniqueness(
        topic_title="Quantum Physics Breakthrough In Zero Gravity",
        script_text="Astrophysicists confirmed atomic entanglement inside orbital laboratories.",
        duration_seconds=22.8,
        asset_ids=["asset_x", "asset_y"],
        short_id="short_gamma"
    )
    assert is_uniq is True
