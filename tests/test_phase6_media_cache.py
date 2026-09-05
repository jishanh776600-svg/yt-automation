"""
Unit Tests for Phase 6 MediaCache.
==================================
Verifies content-addressable storage, atomic file writes, SHA-256 integrity,
corruption purging, and index persistence.
"""

import pytest
from pathlib import Path

from intelligence.media_cache import (
    MediaCache,
    MediaCacheError,
    MediaIntegrityError,
)


@pytest.fixture
def cache(tmp_path):
    return MediaCache(cache_dir=tmp_path / "test_cache")


def test_put_and_get_by_hash(cache):
    data = b"Hello, AL-AMR military footage!"
    url = "https://images.defense.gov/asset.jpg"
    path, sha = cache.put(url=url, data=data, mime_type="image/jpeg")

    assert path.exists()
    assert sha == cache.compute_sha256(data)
    assert cache.has_hash(sha)
    assert cache.has_url(url)

    retrieved = cache.get_by_hash(sha)
    assert retrieved == path
    assert retrieved.read_bytes() == data


def test_get_by_url(cache):
    data = b"Second asset payload"
    url = "https://reuters.com/news.jpg"
    path, sha = cache.put(url=url, data=data, ext=".jpg")

    retrieved = cache.get_by_url(url)
    assert retrieved == path
    assert retrieved.suffix == ".jpg"


def test_put_empty_data_raises(cache):
    with pytest.raises(MediaCacheError):
        cache.put(url="https://empty.com", data=b"")


def test_integrity_error_on_mismatched_hash(cache):
    data = b"Actual content"
    wrong_hash = "1111111111111111111111111111111111111111111111111111111111111111"

    with pytest.raises(MediaIntegrityError):
        cache.put(url="https://fake.com", data=data, expected_hash=wrong_hash)


def test_put_file(cache, tmp_path):
    src_file = tmp_path / "source_video.mp4"
    src_file.write_bytes(b"Simulated MP4 container bytes")

    cached_p, sha = cache.put_file(
        url="https://defense.gov/clip.mp4",
        source_path=src_file,
    )

    assert cached_p.exists()
    assert cached_p.suffix == ".mp4"
    assert cache.has_hash(sha)
    assert cached_p.read_bytes() == src_file.read_bytes()


def test_verify_integrity(cache):
    data = b"Reliable content"
    path, sha = cache.put(url="https://trusted.gov/img.png", data=data, ext=".png")

    assert cache.verify_integrity(path, sha) is True
    assert cache.verify_integrity(path, "badhash") is False


def test_purge_corrupted(cache):
    # Store valid item
    path, sha = cache.put(url="https://ok.com/a.jpg", data=b"good_data")

    # Create a corrupted zero-byte blob
    corrupt_zero = cache.blobs_dir / "zero_byte_blob.bin"
    corrupt_zero.write_bytes(b"")

    # Create a blob whose content doesn't match its 64-char hex name
    fake_sha = "a" * 64
    corrupt_mismatch = cache.blobs_dir / f"{fake_sha}.bin"
    corrupt_mismatch.write_bytes(b"wrong_content")

    purged_count = cache.purge_corrupted()
    assert purged_count == 2
    assert path.exists()
    assert not corrupt_zero.exists()
    assert not corrupt_mismatch.exists()


def test_cache_idempotency(cache):
    data = b"Duplicate identical asset content"
    url1 = "https://source1.com/photo.jpg"
    url2 = "https://source2.com/photo_mirror.jpg"

    p1, sha1 = cache.put(url=url1, data=data, ext=".jpg")
    p2, sha2 = cache.put(url=url2, data=data, ext=".jpg")

    assert sha1 == sha2
    assert p1 == p2
    assert cache.has_url(url1)
    assert cache.has_url(url2)


def test_clear_cache(cache):
    cache.put(url="https://a.com", data=b"123")
    cache.put(url="https://b.com", data=b"456")

    cache.clear()
    assert len(list(cache.blobs_dir.glob("*"))) == 0
    assert cache.has_url("https://a.com") is False
