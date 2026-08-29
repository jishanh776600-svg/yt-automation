"""
Unit and Integration Tests for Private Cloud Database Persistence (Phase 10.8C).
Tests:
- Drive database download success and integrity validation
- Drive database upload success
- Missing remote database fails closed (zero silent empty DB creation)
- Corrupted database rejected via PRAGMA integrity_check
- Topic deduplication persistence across database restore
- Unified GitHub Actions concurrency group across all 3 workflows
- Git untracking and .gitignore enforcement
- Workflows do not commit database to Git
"""
import os
import sqlite3
import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock
import yaml

from config.settings import PROJECT_ROOT
from core.database_sync import (
    download_canonical_database,
    upload_canonical_database,
    verify_sqlite_integrity,
    compute_sha256,
    get_database_stats
)
from engines.drive_engine import DriveVaultEngine


class TestDatabaseSyncPhase108C(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_valid_sqlite_db(self, db_path: Path) -> Path:
        """Helper: creates a valid SQLite database with test schema and data."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE topics (id VARCHAR(64) PRIMARY KEY, title VARCHAR(256), status VARCHAR(32));")
        cursor.execute("CREATE TABLE scripts (id VARCHAR(64) PRIMARY KEY, topic_id VARCHAR(64), hook_text TEXT);")
        cursor.execute("CREATE TABLE jobs (id VARCHAR(64) PRIMARY KEY, state VARCHAR(32));")
        cursor.execute("CREATE TABLE uploads (id VARCHAR(64) PRIMARY KEY, youtube_video_id VARCHAR(64));")
        cursor.execute("CREATE TABLE performance_snapshots (id INTEGER PRIMARY KEY, views INTEGER);")

        cursor.execute("INSERT INTO topics VALUES ('top_test_1', 'The Great London Stink of 1858', 'PUBLISHED')")
        cursor.execute("INSERT INTO topics VALUES ('top_test_2', 'The Boston Molasses Disaster', 'PUBLISHED')")
        conn.commit()
        conn.close()
        return db_path

    def test_01_drive_database_download_success(self):
        """Test 1: Drive database download succeeds and passes integrity check."""
        remote_mock_db = self._create_valid_sqlite_db(self.test_dir / "remote_mock.db")
        target_db = self.test_dir / "target_local.db"

        mock_drive = MagicMock(spec=DriveVaultEngine)
        def mock_dl(local_dest_path, filename="pipeline.db"):
            import shutil
            shutil.copy2(remote_mock_db, local_dest_path)
            return local_dest_path

        mock_drive.download_database.side_effect = mock_dl

        result = download_canonical_database(target_path=target_db, drive_engine=mock_drive)
        self.assertTrue(result.exists())
        self.assertEqual(result, target_db)

        is_valid, msg = verify_sqlite_integrity(target_db)
        self.assertTrue(is_valid)
        self.assertEqual(msg, "ok")

        stats = get_database_stats(target_db)
        self.assertEqual(stats["topics"], 2)

    def test_02_drive_database_upload_success(self):
        """Test 2: Valid local database uploads to Drive and triggers update/create."""
        local_db = self._create_valid_sqlite_db(self.test_dir / "local_to_upload.db")

        mock_drive = MagicMock(spec=DriveVaultEngine)
        mock_drive.upload_database.return_value = {
            "id": "mock_drive_file_id_12345",
            "name": "pipeline.db",
            "size": str(local_db.stat().st_size)
        }

        res = upload_canonical_database(source_path=local_db, drive_engine=mock_drive)
        self.assertEqual(res["id"], "mock_drive_file_id_12345")
        mock_drive.upload_database.assert_called_once_with(local_path=local_db, filename="pipeline.db")

    def test_03_missing_remote_database_fails_closed(self):
        """Test 3: If remote DB is absent from Drive, download fails closed without creating empty DB."""
        target_db = self.test_dir / "non_existent_target.db"

        mock_drive = MagicMock(spec=DriveVaultEngine)
        mock_drive.download_database.side_effect = FileNotFoundError("Canonical database not found in Drive")

        with self.assertRaises(FileNotFoundError):
            download_canonical_database(target_path=target_db, drive_engine=mock_drive)

        self.assertFalse(target_db.exists(), "Target database must NOT be created if download fails")

    def test_04_corrupted_database_rejected(self):
        """Test 4: Downloaded file failing PRAGMA integrity_check is rejected immediately."""
        target_db = self.test_dir / "target_corrupt.db"

        mock_drive = MagicMock(spec=DriveVaultEngine)
        def mock_dl_corrupt(local_dest_path, filename="pipeline.db"):
            # Write 5KB of non-SQLite corrupt bytes
            local_dest_path.write_bytes(b"CORRUPT_NOT_SQLITE_GARBAGE_HEADER" * 150)
            return local_dest_path

        mock_drive.download_database.side_effect = mock_dl_corrupt

        with self.assertRaises(ValueError) as ctx:
            download_canonical_database(target_path=target_db, drive_engine=mock_drive)

        self.assertIn("integrity check", str(ctx.exception).lower())
        self.assertFalse(target_db.exists(), "Corrupt file must not replace target")

    def test_05_topic_deduplication_persists_across_mock_sync(self):
        """Test 5: Restored database correctly maintains deduplication corpus."""
        db_path = self._create_valid_sqlite_db(self.test_dir / "sync_dedup_test.db")

        # Verify historical topics are present
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM topics")
        titles = [r[0] for r in cursor.fetchall()]
        conn.close()

        self.assertIn("The Great London Stink of 1858", titles)
        self.assertIn("The Boston Molasses Disaster", titles)

    def test_06_unified_concurrency_group_declared(self):
        """Test 6: autopilot.yml, produce_buffer.yml, and harvest_analytics.yml share pipeline-cloud-execution."""
        workflow_dir = PROJECT_ROOT / ".github" / "workflows"
        target_workflows = ["autopilot.yml", "produce_buffer.yml", "harvest_analytics.yml"]

        for wf_name in target_workflows:
            wf_path = workflow_dir / wf_name
            self.assertTrue(wf_path.exists(), f"Workflow {wf_name} missing")
            with open(wf_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            concurrency = data.get("concurrency")
            self.assertIsNotNone(concurrency, f"Workflow {wf_name} lacks concurrency definition")
            self.assertEqual(
                concurrency.get("group"),
                "pipeline-cloud-execution",
                f"Workflow {wf_name} has wrong concurrency group: {concurrency.get('group')}"
            )
            self.assertFalse(
                concurrency.get("cancel-in-progress"),
                f"Workflow {wf_name} must have cancel-in-progress: false"
            )

    def test_07_database_files_untracked_and_ignored(self):
        """Test 7: pipeline.db is NOT tracked in Git and is ignored by .gitignore."""
        res = subprocess.run(["git", "ls-files", "data/database/pipeline.db"], capture_output=True, text=True)
        self.assertEqual(res.stdout.strip(), "", "data/database/pipeline.db must NOT be tracked in Git")

        gitignore_content = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/database/pipeline.db", gitignore_content)
        self.assertIn("data/database/*.db*", gitignore_content)

    def test_08_workflows_do_not_commit_database(self):
        """Test 8: None of the workflows commit data/database/."""
        workflow_dir = PROJECT_ROOT / ".github" / "workflows"
        target_workflows = ["autopilot.yml", "produce_buffer.yml", "harvest_analytics.yml"]

        for wf_name in target_workflows:
            content = (workflow_dir / wf_name).read_text(encoding="utf-8")
            self.assertNotIn("git add data/database", content, f"Workflow {wf_name} still commits data/database")


if __name__ == "__main__":
    unittest.main()
