"""
Private Cloud Database Synchronization Engine (Phase 10.8C).
Provides fail-closed synchronization between local data/database/pipeline.db
and the canonical Google Drive location: YouTube_Shorts_Vault/00_SYSTEM/pipeline.db.

Enforces:
- SHA256 checksum tracking
- SQLite PRAGMA integrity_check before accepting and before uploading
- Atomic replacement on download
- Zero silent creation of empty databases
"""
import os
import sys
import hashlib
import sqlite3
import logging
import argparse
from pathlib import Path
from typing import Optional, Tuple

from config.settings import DB_PATH, PROJECT_ROOT
from engines.drive_engine import DriveVaultEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DB_SYNC] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

CANONICAL_VAULT_FOLDER = "00_SYSTEM"
CANONICAL_DB_FILENAME = "pipeline.db"


def compute_sha256(file_path: Path) -> str:
    """Computes hex SHA256 checksum of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_sqlite_integrity(file_path: Path) -> Tuple[bool, str]:
    """
    Executes PRAGMA integrity_check on the specified SQLite database file.
    Returns (is_valid, message).
    """
    if not file_path.exists():
        return False, f"File does not exist: {file_path}"

    if file_path.stat().st_size < 4096:
        return False, f"File size too small ({file_path.stat().st_size} bytes) to be valid SQLite database"

    conn = None
    try:
        conn = sqlite3.connect(str(file_path), timeout=10.0)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        rows = cursor.fetchall()
        cursor.close()

        if len(rows) == 1 and rows[0][0] == "ok":
            return True, "ok"
        else:
            errors = "; ".join(str(r[0]) for r in rows)
            return False, f"PRAGMA integrity_check failed: {errors}"
    except Exception as e:
        return False, f"SQLite integrity verification error: {e}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_database_stats(file_path: Path) -> dict:
    """Retrieves key table counts from the database for verification."""
    stats = {}
    try:
        conn = sqlite3.connect(str(file_path), timeout=5.0)
        cursor = conn.cursor()
        for table in ["topics", "scripts", "jobs", "uploads", "performance_snapshots"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            except Exception:
                stats[table] = -1
        cursor.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not read database stats: {e}")
    return stats


def download_canonical_database(
    target_path: Optional[Path] = None,
    drive_engine: Optional[DriveVaultEngine] = None
) -> Path:
    """
    Downloads the canonical database from Drive 00_SYSTEM/pipeline.db to local target_path.
    Verifies SQLite integrity before atomic replacement.
    Fails closed if the remote file is absent or fails integrity check.
    """
    target = target_path or DB_PATH
    engine = drive_engine or DriveVaultEngine()

    logger.info(f"Initiating canonical database download from Drive vault '{CANONICAL_VAULT_FOLDER}'...")
    target.parent.mkdir(parents=True, exist_ok=True)

    temp_path = target.with_suffix(".tmp_verify")
    try:
        engine.download_database(local_dest_path=temp_path, filename=CANONICAL_DB_FILENAME)

        is_valid, msg = verify_sqlite_integrity(temp_path)
        if not is_valid:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise ValueError(f"Downloaded canonical database failed integrity check: {msg}")

        sha = compute_sha256(temp_path)
        size_bytes = temp_path.stat().st_size
        stats = get_database_stats(temp_path)

        if target.exists():
            backup_path = target.with_suffix(".prev_backup")
            try:
                import shutil
                shutil.copy2(target, backup_path)
            except Exception:
                pass
            target.unlink()

        temp_path.replace(target)
        if target.with_suffix(".prev_backup").exists():
            try:
                target.with_suffix(".prev_backup").unlink(missing_ok=True)
            except Exception:
                pass

        logger.info(f"[+] Canonical database successfully synchronized from Drive!")
        logger.info(f"    Path: {target}")
        logger.info(f"    Size: {size_bytes / (1024*1024):.2f} MB ({size_bytes} bytes)")
        logger.info(f"    SHA256: {sha[:16]}...{sha[-8:]}")
        logger.info(f"    Table Counts: {stats}")
        return target
    except Exception as e:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        logger.error(f"[FATAL] Failed to download or verify canonical database from Drive: {e}")
        raise


def upload_canonical_database(
    source_path: Optional[Path] = None,
    drive_engine: Optional[DriveVaultEngine] = None
) -> dict:
    """
    Uploads the local database to Drive 00_SYSTEM/pipeline.db.
    Verifies SQLite integrity before uploading.
    Fails closed if the local file is absent or fails integrity check.
    """
    source = source_path or DB_PATH
    engine = drive_engine or DriveVaultEngine()

    if not source.exists():
        raise FileNotFoundError(f"Local database not found for upload: {source}")

    # Explicit WAL checkpoint to ensure all transactions are flushed to primary DB file
    try:
        conn = sqlite3.connect(str(source), timeout=10.0)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        conn.commit()
        conn.close()
    except Exception as cp_err:
        logger.warning(f"WAL checkpoint notice: {cp_err}")

    is_valid, msg = verify_sqlite_integrity(source)
    if not is_valid:
        raise ValueError(f"Local database failed integrity check before upload: {msg}")

    sha = compute_sha256(source)
    size_bytes = source.stat().st_size
    stats = get_database_stats(source)

    logger.info(f"Initiating canonical database upload to Drive vault '{CANONICAL_VAULT_FOLDER}'...")
    logger.info(f"    Source: {source} ({size_bytes} bytes, SHA256: {sha[:16]}...)")
    logger.info(f"    Table Counts: {stats}")

    res = engine.upload_database(local_path=source, filename=CANONICAL_DB_FILENAME)
    logger.info(f"[+] Canonical database successfully uploaded to Drive (File ID: {res.get('id')})")
    return res


def main():
    parser = argparse.ArgumentParser(description="Private Cloud Database Synchronization CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # download
    dl_parser = subparsers.add_parser("download", help="Download canonical DB from Google Drive")
    dl_parser.add_argument("--target", type=str, default=None, help="Local destination path")

    # upload
    ul_parser = subparsers.add_parser("upload", help="Upload local DB to Google Drive")
    ul_parser.add_argument("--source", type=str, default=None, help="Local source path")

    # verify
    vr_parser = subparsers.add_parser("verify", help="Verify integrity and show stats of local DB")
    vr_parser.add_argument("--path", type=str, default=None, help="Path to DB file")

    args = parser.parse_args()

    try:
        if args.command == "download":
            target = Path(args.target) if args.target else None
            download_canonical_database(target_path=target)
        elif args.command == "upload":
            source = Path(args.source) if args.source else None
            upload_canonical_database(source_path=source)
        elif args.command == "verify":
            target = Path(args.path) if args.path else DB_PATH
            is_valid, msg = verify_sqlite_integrity(target)
            if not is_valid:
                print(f"[FAIL] {msg}")
                sys.exit(1)
            sha = compute_sha256(target)
            stats = get_database_stats(target)
            print(f"[PASS] PRAGMA integrity_check: {msg}")
            print(f"       Path: {target}")
            print(f"       Size: {target.stat().st_size} bytes")
            print(f"       SHA256: {sha}")
            print(f"       Stats: {stats}")
    except Exception as e:
        logger.error(f"Operation '{args.command}' failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
