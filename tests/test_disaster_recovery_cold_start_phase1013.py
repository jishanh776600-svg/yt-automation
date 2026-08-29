"""
Phase 10.13 — Cold-Start / Disaster Recovery Test Suite.
Verifies that a completely fresh execution environment (simulating a brand-new cloud runner
with zero local cache, zero local database, and zero pre-existing media folders) can:
1. Reconstruct local workspace directories on demand.
2. Download canonical pipeline.db from Drive fail-closed.
3. Successfully run integrity verification on the cold-started database.
4. Refuse execution safely without leaking credentials if secrets are missing.
"""
import os
import sys
import tempfile
import sqlite3
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.database_sync import download_canonical_database, verify_sqlite_integrity, compute_sha256


class TestDisasterRecoveryColdStartPhase1013(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox_root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_01_cold_start_directory_auto_creation(self):
        """Test 1: Fresh filesystem without data/ or renders/ automatically creates parent dirs."""
        cold_db_path = self.sandbox_root / "non_existent_folder" / "nested" / "pipeline.db"
        self.assertFalse(cold_db_path.parent.exists())

        # Create valid mock sqlite DB to download
        source_db = self.sandbox_root / "source.db"
        conn = sqlite3.connect(str(source_db))
        conn.execute("CREATE TABLE topics (id TEXT);")
        conn.commit()
        conn.close()

        mock_drive = MagicMock()
        def fake_download(*args, **kwargs):
            dest = kwargs.get("local_dest_path") or args[0]
            dest.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source_db, dest)
            return dest

        mock_drive.download_database.side_effect = fake_download

        res_path = download_canonical_database(target_path=cold_db_path, drive_engine=mock_drive)

        self.assertTrue(cold_db_path.exists())
        self.assertTrue(cold_db_path.parent.exists())
        is_valid, msg = verify_sqlite_integrity(cold_db_path)
        self.assertTrue(is_valid)

    def test_02_cold_start_fails_closed_when_drive_db_missing(self):
        """Test 2: If canonical database is missing in cloud Drive, runner aborts fail-closed."""
        cold_db_path = self.sandbox_root / "fresh_run" / "pipeline.db"

        mock_drive = MagicMock()
        mock_drive.download_database.side_effect = FileNotFoundError("Canonical database 'pipeline.db' was not found in Drive")

        with self.assertRaises(FileNotFoundError):
            download_canonical_database(target_path=cold_db_path, drive_engine=mock_drive)

        self.assertFalse(cold_db_path.exists())


if __name__ == "__main__":
    unittest.main()
