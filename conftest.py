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
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_DIR = PROJECT_ROOT / "data" / "database"
TEST_DB_PATH = DATABASE_DIR / "test_pipeline.db"
CANONICAL_DB_PATH = DATABASE_DIR / "pipeline.db"


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
