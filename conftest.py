"""
Pytest configuration and session-wide fixtures for test isolation.
Ensures:
1. All test runs execute against an isolated test database (test_pipeline.db).
2. Canonical production database (pipeline.db) is protected and never contaminated.
3. Test environment safety flags prevent accidental Google Drive uploads.
"""
import os
import sys
import shutil
import socket
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_DIR = PROJECT_ROOT / "data" / "database"
TEST_DB_PATH = DATABASE_DIR / "test_pipeline.db"
CANONICAL_DB_PATH = DATABASE_DIR / "pipeline.db"


class ExternalNetworkForbiddenError(RuntimeError):
    """Raised when an unmocked external network connection is attempted during offline test suites."""
    pass


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "live_cloud: mark test as requiring live external cloud network access"
    )


@pytest.fixture(autouse=True)
def block_external_network_io(request, monkeypatch):
    """
    Strict Fail-Safe NO_EXTERNAL_IO Test Boundary.
    Detects and blocks any unexpected external HTTP/HTTPS socket connections to Google Drive,
    YouTube, OpenAI, OpenRouter, Groq, Gemini, Pexels, ElevenLabs, etc.
    Permits local loopback connections (127.0.0.1, localhost, ::1, testserver).
    Permits external traffic ONLY when test is explicitly marked with @pytest.mark.live_cloud
    or when ALLOW_EXTERNAL_NETWORK=true environment variable is set.
    """
    if request.node.get_closest_marker("live_cloud") or os.environ.get("ALLOW_EXTERNAL_NETWORK", "").lower() in ("true", "1", "yes"):
        yield
        return

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"}

    def is_allowed(host):
        if not host:
            return True
        shost = str(host).lower().strip()
        if shost in ALLOWED_HOSTS:
            return True
        if shost.startswith("127."):
            return True
        return False

    def guarded_getaddrinfo(host, port, *args, **kwargs):
        if not is_allowed(host):
            raise ExternalNetworkForbiddenError(
                f"Attempted live external network DNS resolution during offline regression test to '{host}'. "
                f"Automated regression suites must remain strictly offline and deterministic."
            )
        return orig_getaddrinfo(host, port, *args, **kwargs)

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, (tuple, list)) and address else address
        if not is_allowed(host):
            raise ExternalNetworkForbiddenError(
                f"Attempted live external socket connect during offline regression test to {address}. "
                f"Automated regression suites must remain strictly offline and deterministic."
            )
        return orig_connect(sock, address)

    def guarded_connect_ex(sock, address):
        host = address[0] if isinstance(address, (tuple, list)) and address else address
        if not is_allowed(host):
            raise ExternalNetworkForbiddenError(
                f"Attempted live external socket connect_ex during offline regression test to {address}. "
                f"Automated regression suites must remain strictly offline and deterministic."
            )
        return orig_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)

    yield


@pytest.fixture(scope="session", autouse=True)
def setup_isolated_test_database():
    """
    Session-wide test fixture ensuring test execution is strictly isolated from production DB.
    """
    os.environ["IS_TEST_ENV"] = "true"
    os.environ["TEST_DB_PATH"] = str(TEST_DB_PATH)
    os.environ["TEST_MODE"] = "true"

    DATABASE_DIR.mkdir(parents=True, exist_ok=True)

    # Clean any stale test database
    for p in [TEST_DB_PATH, TEST_DB_PATH.with_suffix(".db-wal"), TEST_DB_PATH.with_suffix(".db-shm")]:
        if p.exists():
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass

    if CANONICAL_DB_PATH.exists():
        shutil.copy2(CANONICAL_DB_PATH, TEST_DB_PATH)

    from core.database import init_db, rebind_engine
    rebind_engine(TEST_DB_PATH)
    init_db()

    yield

    # Clean up test database after all tests complete
    try:
        from core.database import rebind_engine
        rebind_engine(CANONICAL_DB_PATH)
    except Exception:
        pass

    for p in [TEST_DB_PATH, TEST_DB_PATH.with_suffix(".db-wal"), TEST_DB_PATH.with_suffix(".db-shm")]:
        if p.exists():
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
