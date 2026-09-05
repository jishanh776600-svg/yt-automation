"""
Unit & Integration Tests for Phase 6 AssetFetcher.
==================================================
Verifies SSRF defense, bounded streaming, redirect protection, SHA-256 integrity,
cache integration, and manifest batch processing using pure standard library mocks.
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from intelligence.asset_fetcher import AssetFetcher, AssetFetchStatus
from intelligence.asset_manifest import (
    ProductionAssetManifest,
    BeatVisualAssignment,
    EditTransitionType,
)
from intelligence.media_cache import MediaCache


@pytest.fixture
def temp_cache(tmp_path):
    cache_dir = tmp_path / "cache"
    return MediaCache(cache_dir=cache_dir)


@pytest.fixture
def fetcher(temp_cache):
    return AssetFetcher(media_cache=temp_cache)  # Default: No arbitrary 50MB or size limits


@pytest.fixture
def limited_fetcher(temp_cache):
    return AssetFetcher(media_cache=temp_cache, max_bytes=1024 * 1024)  # Explicit 1MB limit for limit tests


def test_fetch_empty_url(fetcher):
    res = fetcher.fetch_url("")
    assert res.status == AssetFetchStatus.SKIPPED_NO_URL
    assert res.local_path is None


def test_fetch_ssrf_blocked(fetcher):
    # Prohibited loopback and cloud metadata
    bad_urls = [
        "http://localhost/secret",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://192.168.1.1/router",
        "file:///etc/passwd",
        "ftp://ftp.server.com/file",
    ]
    for url in bad_urls:
        res = fetcher.fetch_url(url)
        assert res.status == AssetFetchStatus.FAILED_SSRF, f"Expected SSRF failure for {url}"
        assert res.local_path is None


def test_fetch_valid_asset_success(fetcher, temp_cache):
    url = "https://images.defense.gov/2026/navy_ship.jpg"
    fake_data = b"\xff\xd8\xff" + b"A" * 500  # Valid JPEG magic bytes

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/jpeg", "Content-Length": str(len(fake_data))}
    mock_resp.iter_content.return_value = [fake_data]

    with patch.object(fetcher.session, "get", return_value=mock_resp):
        res = fetcher.fetch_url(url)

    assert res.status == AssetFetchStatus.SUCCESS
    assert res.local_path is not None
    assert res.local_path.exists()
    assert res.size_bytes == len(fake_data)
    assert res.mime_type == "image/jpeg"
    assert res.sha256 is not None

    # Verify cache hit on second fetch without network call
    with patch.object(fetcher.session, "get") as mock_get:
        res2 = fetcher.fetch_url(url)
        assert res2.status == AssetFetchStatus.CACHE_HIT
        assert res2.local_path == res.local_path
        mock_get.assert_not_called()


def test_fetch_redirect_ssrf_protection(fetcher):
    """Initial public URL redirects to private cloud metadata IP - MUST be blocked."""
    initial_url = "https://public-news.com/redirect"
    evil_redirect = "http://169.254.169.254/computeMetadata/v1/"

    mock_redirect = MagicMock()
    mock_redirect.status_code = 302
    mock_redirect.headers = {"Location": evil_redirect}

    with patch.object(fetcher.session, "get", return_value=mock_redirect):
        res = fetcher.fetch_url(initial_url)

    assert res.status == AssetFetchStatus.FAILED_SSRF
    assert "SSRF violation" in (res.error_message or "")


def test_fetch_large_asset_over_50mb_not_rejected(fetcher):
    """File declaring Content-Length > 50MB and streaming > 50MB is NOT rejected."""
    url = "https://cdn.example.com/massive_75mb_archive.mp4"
    declared_size = 75 * 1024 * 1024  # 75 MB
    chunk_sample = b"\x00\x00\x00 ftypisom" + b"A" * (65536 - 16)  # Valid mp4 magic bytes
    large_chunks = [chunk_sample] + [b"B" * 65536] * 10  # Streamed chunks

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": str(declared_size)}
    mock_resp.iter_content.return_value = large_chunks

    with patch.object(fetcher.session, "get", return_value=mock_resp):
        res = fetcher.fetch_url(url)

    # Must succeed and NOT fail with FAILED_SIZE
    assert res.status == AssetFetchStatus.SUCCESS
    assert res.local_path is not None
    assert res.local_path.exists()
    assert res.mime_type == "video/mp4"


def test_fetch_missing_content_length_streams_successfully(fetcher):
    """Asset with missing Content-Length header downloads normally via streaming chunks."""
    url = "https://cdn.example.com/chunked_video.mp4"
    chunk1 = b"\x00\x00\x00 ftypmp42" + b"X" * 1000
    chunk2 = b"Y" * 2000

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "video/mp4"}  # No Content-Length
    mock_resp.iter_content.return_value = [chunk1, chunk2]

    with patch.object(fetcher.session, "get", return_value=mock_resp):
        res = fetcher.fetch_url(url)

    assert res.status == AssetFetchStatus.SUCCESS
    assert res.local_path is not None
    assert res.size_bytes == len(chunk1) + len(chunk2)


def test_fetch_explicit_size_limit_respected_when_configured(limited_fetcher):
    """When a caller explicitly specifies max_bytes, the limit is respected."""
    url = "https://cdn.example.com/too_big.mp4"
    declared_size = 5 * 1024 * 1024  # 5MB > 1MB limit on limited_fetcher

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": str(declared_size)}

    with patch.object(limited_fetcher.session, "get", return_value=mock_resp):
        res = limited_fetcher.fetch_url(url)

    assert res.status == AssetFetchStatus.FAILED_SIZE
    assert res.local_path is None


def test_fetch_checksum_mismatch(fetcher):
    """Asset whose downloaded content doesn't match expected hash is rejected."""
    url = "https://cdn.example.com/photo.png"
    fake_data = b"\x89PNG\r\n\x1a\n" + b"content123"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "image/png"}
    mock_resp.iter_content.return_value = [fake_data]

    wrong_hash = "0000000000000000000000000000000000000000000000000000000000000000"
    with patch.object(fetcher.session, "get", return_value=mock_resp):
        res = fetcher.fetch_url(url, expected_hash=wrong_hash)

    assert res.status == AssetFetchStatus.FAILED_INTEGRITY
    assert res.local_path is None


def test_fetch_http_errors_isolated(fetcher):
    """HTTP 404 and 500 errors fail gracefully with FAILED_HTTP."""
    url404 = "https://cdn.example.com/not_found.jpg"

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(fetcher.session, "get", return_value=mock_resp):
        res = fetcher.fetch_url(url404)

    assert res.status == AssetFetchStatus.FAILED_HTTP
    assert "404" in (res.error_message or "")


def test_fetch_manifest_assets(fetcher):
    """Batch fetch maps local files back to beats in a ProductionAssetManifest."""
    url1 = "https://images.defense.gov/asset1.jpg"
    url2 = "https://images.defense.gov/asset2.png"

    data1 = b"\xff\xd8\xff" + b"1" * 100
    data2 = b"\x89PNG\r\n\x1a\n" + b"2" * 100

    def mock_get_impl(u, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if u == url1:
            resp.headers = {"Content-Type": "image/jpeg"}
            resp.iter_content.return_value = [data1]
        elif u == url2:
            resp.headers = {"Content-Type": "image/png"}
            resp.iter_content.return_value = [data2]
        else:
            resp.status_code = 404
        return resp

    manifest = ProductionAssetManifest(
        manifest_id="mani_batch_test",
        event_id="ev_123",
        script_id="sc_456",
        total_duration_seconds=12.0,
        beats=[
            BeatVisualAssignment(
                beat_id="beat_01",
                sequence=1,
                text="First beat",
                start_time=0.0,
                end_time=4.0,
                duration_seconds=4.0,
                selected_visual_id="vis_1",
                coverage_type="DIRECT_EVIDENCE",
                authenticity="VERIFIED_AUTHENTIC",
                licensing_status="PUBLIC_DOMAIN",
                eligibility="ELIGIBLE",
                media_url=url1,
            ),
            BeatVisualAssignment(
                beat_id="beat_02",
                sequence=2,
                text="Second beat without media",
                start_time=4.0,
                end_time=8.0,
                duration_seconds=4.0,
                selected_visual_id=None,
                coverage_type="NO_VISUAL",
                authenticity="CONTEXTUAL",
                licensing_status="LICENSE_UNKNOWN",
                eligibility="UNKNOWN",
                media_url=None,
            ),
            BeatVisualAssignment(
                beat_id="beat_03",
                sequence=3,
                text="Third beat",
                start_time=8.0,
                end_time=12.0,
                duration_seconds=4.0,
                selected_visual_id="vis_2",
                coverage_type="RELATED_EVIDENCE",
                authenticity="VERIFIED_AUTHENTIC",
                licensing_status="PUBLIC_DOMAIN",
                eligibility="ELIGIBLE",
                media_url=url2,
            ),
        ],
    )

    with patch.object(fetcher.session, "get", side_effect=mock_get_impl):
        summary = fetcher.fetch_manifest_assets(manifest)

    assert summary.total_requested == 2
    assert summary.successful == 2
    assert summary.failed == 0
    assert summary.asset_path_by_beat["beat_01"] is not None
    assert summary.asset_path_by_beat["beat_02"] is None
    assert summary.asset_path_by_beat["beat_03"] is not None
