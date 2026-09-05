"""
Private Cloud Database Synchronization Engine.
Provides fail-closed, transaction-safe synchronization between local SQLite databases
and the canonical Google Drive vault: YouTube_Shorts_Vault/00_SYSTEM/.

Manages:
- Canonical Database: pipeline.db (aliased as youtube_automation.db)
- Auxiliary Databases:
    * visual_memory.db (GlobalVisualMemory asset dHash and deduplication)
    * short_fingerprints.db (ShortDuplicateGuard script and title shingles)
"""
import os
import sys
import time
import shutil
import hashlib
import sqlite3
import logging
import argparse
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from config.settings import DB_PATH, DATABASE_DIR, PROJECT_ROOT
from engines.drive_engine import DriveVaultEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [DB_SYNC] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

CANONICAL_VAULT_FOLDER = "00_SYSTEM"
CANONICAL_DB_FILENAME = "pipeline.db"
CANONICAL_DB_ALIASES = ("pipeline.db", "youtube_automation.db")
LOCAL_ALIAS_FILENAME = "youtube_automation.db"

AUXILIARY_DATABASES: Dict[str, Dict[str, Any]] = {
    "visual_memory": {
        "filename": "visual_memory.db",
        "local_path": DATABASE_DIR / "visual_memory.db",
        "table": "visual_asset_memory",
        "init_sql": """
            CREATE TABLE IF NOT EXISTS visual_asset_memory (
                asset_id TEXT PRIMARY KEY,
                source TEXT,
                exact_hash TEXT,
                perceptual_hash TEXT,
                subjects_json TEXT,
                category TEXT,
                story_id TEXT,
                first_used_at TEXT,
                last_used_at TEXT,
                usage_count INTEGER DEFAULT 1,
                recent_shorts_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_vam_exact ON visual_asset_memory(exact_hash);
            CREATE INDEX IF NOT EXISTS idx_vam_phash ON visual_asset_memory(perceptual_hash);
            CREATE INDEX IF NOT EXISTS idx_vam_last_used ON visual_asset_memory(last_used_at);
        """
    },
    "short_fingerprints": {
        "filename": "short_fingerprints.db",
        "local_path": DATABASE_DIR / "short_fingerprints.db",
        "table": "short_fingerprints",
        "init_sql": """
            CREATE TABLE IF NOT EXISTS short_fingerprints (
                short_id TEXT PRIMARY KEY,
                topic_title TEXT,
                script_text TEXT,
                duration_seconds REAL,
                asset_ids_json TEXT,
                fingerprint_hash TEXT,
                created_at_utc TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sf_hash ON short_fingerprints(fingerprint_hash);
        """
    }
}


def compute_sha256(file_path: Path) -> str:
    """Computes hex SHA256 checksum of a file."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def verify_sqlite_integrity(file_path: Path, min_size: int = 4096) -> Tuple[bool, str]:
    """
    Executes PRAGMA integrity_check on the specified SQLite database file.
    Returns (is_valid, message).
    """
    if not file_path.exists():
        return False, f"File does not exist: {file_path}"

    if file_path.stat().st_size < min_size:
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


def flush_wal_checkpoint(
    db_path: Path,
    max_attempts: int = 3,
    base_delay: float = 0.5
) -> bool:
    """
    Executes PRAGMA wal_checkpoint(TRUNCATE) on the database file to ensure
    all WAL transactions are fully merged into the primary .db file and the
    WAL log is truncated.
    Guarantees connection closure in finally block and retries safely on busy.
    """
    if not db_path.exists():
        return False

    wal_path = db_path.parent / f"{db_path.name}-wal"

    for attempt in range(max_attempts):
        conn = None
        try:
            conn = sqlite3.connect(str(db_path), timeout=15.0)
            cursor = conn.cursor()
            cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            row = cursor.fetchone()
            cursor.close()
            conn.commit()

            if row and row[0] == 0:
                logger.debug(
                    f"WAL checkpoint TRUNCATE succeeded for '{db_path.name}' "
                    f"(pages checkpointed: {row[2]}, remaining log: {row[1]})"
                )
                return True
            else:
                logger.warning(
                    f"WAL checkpoint attempt {attempt + 1} for '{db_path.name}' reported busy={row[0] if row else '?'}, "
                    f"log={row[1] if row else '?'}, checkpointed={row[2] if row else '?'}"
                )
        except Exception as cp_err:
            logger.warning(f"WAL checkpoint attempt {attempt + 1} notice for '{db_path.name}': {cp_err}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        if attempt < max_attempts - 1:
            time.sleep(base_delay * (attempt + 1))

    if wal_path.exists() and wal_path.stat().st_size > 0:
        logger.warning(f"WAL file '{wal_path.name}' remains non-empty ({wal_path.stat().st_size} bytes)")
        return False
    return True


def safe_replace_sqlite_file(source_temp: Path, dest_target: Path) -> None:
    """
    Atomically updates dest_target from source_temp.
    Uses sqlite3 online backup if dest_target exists to avoid Windows file-locking collisions.
    """
    dest_target.parent.mkdir(parents=True, exist_ok=True)
    if dest_target.exists():
        backup_path = dest_target.with_suffix(".prev_backup")
        try:
            shutil.copy2(dest_target, backup_path)
        except Exception:
            pass

        src_conn = sqlite3.connect(str(source_temp))
        dest_conn = sqlite3.connect(str(dest_target), timeout=30.0)
        try:
            src_conn.backup(dest_conn)
        finally:
            src_conn.close()
            dest_conn.close()

        source_temp.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
    else:
        source_temp.replace(dest_target)


def sync_canonical_alias(canonical_path: Path) -> Optional[Path]:
    """
    Synchronizes local canonical database with its alias.
    If canonical_path is pipeline.db, mirrors to youtube_automation.db.
    """
    if not canonical_path.exists():
        return None

    alias_name = "youtube_automation.db" if canonical_path.name == "pipeline.db" else "pipeline.db"
    alias_path = canonical_path.parent / alias_name

    try:
        src_conn = sqlite3.connect(str(canonical_path))
        dest_conn = sqlite3.connect(str(alias_path), timeout=30.0)
        try:
            src_conn.backup(dest_conn)
        finally:
            src_conn.close()
            dest_conn.close()
        logger.debug(f"[ALIAS] Mirrored canonical database to alias: {alias_path.name}")
        return alias_path
    except Exception as e:
        logger.warning(f"Could not synchronize alias {alias_name}: {e}")
        return None


def get_database_stats(file_path: Path) -> dict:
    """Retrieves key table counts from the database for verification."""
    stats = {}
    try:
        conn = sqlite3.connect(str(file_path), timeout=5.0)
        cursor = conn.cursor()
        for table in ["topics", "scripts", "jobs", "uploads", "performance_snapshots", "renders", "assets"]:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[table] = cursor.fetchone()[0]
            except Exception:
                stats[table] = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM assets WHERE asset_type='voice'")
            stats["voice"] = cursor.fetchone()[0]
        except Exception:
            stats["voice"] = 0
        cursor.close()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not read database stats: {e}")
    return stats


def _init_auxiliary_db(db_path: Path, init_sql: str) -> None:
    """Helper to initialize an auxiliary database with clean schema."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(init_sql)
        conn.commit()
    finally:
        conn.close()


def download_canonical_database(
    target_path: Optional[Path] = None,
    drive_engine: Optional[DriveVaultEngine] = None
) -> Path:
    """
    Downloads the canonical database from Drive 00_SYSTEM/pipeline.db (or alias youtube_automation.db).
    Verifies SQLite integrity before atomic replacement.
    Fails closed if the remote file is absent or fails integrity check.
    """
    target = target_path or DB_PATH
    engine = drive_engine or DriveVaultEngine()

    logger.info(f"Initiating canonical database download from Drive vault '{CANONICAL_VAULT_FOLDER}'...")
    target.parent.mkdir(parents=True, exist_ok=True)

    remote_filename = CANONICAL_DB_FILENAME
    try:
        if hasattr(engine, "find_file_in_folder"):
            pipe_found = engine.find_file_in_folder(CANONICAL_VAULT_FOLDER, CANONICAL_DB_FILENAME)
            if not pipe_found:
                for alias in CANONICAL_DB_ALIASES:
                    if alias != CANONICAL_DB_FILENAME and engine.find_file_in_folder(CANONICAL_VAULT_FOLDER, alias):
                        remote_filename = alias
                        break
    except Exception:
        pass

    temp_path = target.with_suffix(".tmp_verify")
    try:
        engine.download_database(local_dest_path=temp_path, filename=remote_filename)

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

        safe_replace_sqlite_file(temp_path, target)
        sync_canonical_alias(target)

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

    # Safety Guard: Block upload if in test environment or using test DB without an injected mock engine
    if (os.getenv("IS_TEST_ENV", "").lower() == "true" or "test_pipeline" in str(source).lower()) and drive_engine is None:
        logger.warning("[SAFETY GUARD] Blocked attempt to upload test database to canonical Drive vault 00_SYSTEM/pipeline.db")
        return {"status": "BLOCKED_TEST_MODE", "message": "Test database cannot be uploaded to canonical Drive vault"}

    if not source.exists():
        # Check aliases
        for alias in CANONICAL_DB_ALIASES:
            cand = source.parent / alias
            if cand.exists():
                source = cand
                break
        if not source.exists():
            raise FileNotFoundError(f"Local database not found for upload: {source}")

    # Dispose any pooled SQLAlchemy connections so no open transaction blocks WAL checkpoint
    try:
        from core.database import engine as sa_engine
        sa_engine.dispose()
    except Exception:
        pass

    # Explicit WAL checkpoint with safe retry
    flush_wal_checkpoint(source)

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
    sync_canonical_alias(source)
    logger.info(f"[+] Canonical database successfully uploaded to Drive (File ID: {res.get('id') if isinstance(res, dict) else res})")
    return res


def download_auxiliary_databases(
    drive_engine: Optional[DriveVaultEngine] = None,
    aux_keys: Optional[List[str]] = None
) -> Dict[str, Path]:
    """
    Downloads auxiliary databases (visual_memory.db, short_fingerprints.db) from Drive 00_SYSTEM/.
    Initializes clean local schema if absent from Drive.
    """
    engine = drive_engine or DriveVaultEngine()
    results = {}
    keys_to_sync = aux_keys or list(AUXILIARY_DATABASES.keys())

    for key in keys_to_sync:
        cfg = AUXILIARY_DATABASES.get(key)
        if not cfg:
            continue

        filename = cfg["filename"]
        target_path = cfg["local_path"]
        target_path.parent.mkdir(parents=True, exist_ok=True)

        existing = None
        try:
            if hasattr(engine, "find_file_in_folder"):
                existing = engine.find_file_in_folder(CANONICAL_VAULT_FOLDER, filename)
        except Exception:
            existing = None

        if existing:
            logger.info(f"Downloading auxiliary database '{filename}' from Drive vault '{CANONICAL_VAULT_FOLDER}'...")
            temp_path = target_path.with_suffix(".tmp_aux_verify")
            try:
                engine.download_database(local_dest_path=temp_path, filename=filename)
                is_valid, msg = verify_sqlite_integrity(temp_path)
                if not is_valid:
                    temp_path.unlink(missing_ok=True)
                    raise ValueError(f"Downloaded auxiliary database '{filename}' failed integrity check: {msg}")

                safe_replace_sqlite_file(temp_path, target_path)
                sha = compute_sha256(target_path)
                logger.info(f"[+] Auxiliary DB '{filename}' synchronized (SHA256: {sha[:16]}...)")
                results[key] = target_path
            except Exception as dl_err:
                temp_path.unlink(missing_ok=True)
                logger.error(f"Failed to download auxiliary DB '{filename}': {dl_err}")
                raise
        else:
            if target_path.exists():
                is_valid, msg = verify_sqlite_integrity(target_path)
                if is_valid:
                    logger.info(f"Auxiliary DB '{filename}' not in Drive vault; preserving valid local copy.")
                    results[key] = target_path
                else:
                    logger.warning(f"Local auxiliary DB '{filename}' invalid; initializing clean tables.")
                    _init_auxiliary_db(target_path, cfg["init_sql"])
                    results[key] = target_path
            else:
                logger.info(f"Auxiliary DB '{filename}' not in Drive or locally. Initializing clean schema.")
                _init_auxiliary_db(target_path, cfg["init_sql"])
                results[key] = target_path

    return results


def upload_auxiliary_databases(
    drive_engine: Optional[DriveVaultEngine] = None,
    aux_keys: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Uploads auxiliary databases (visual_memory.db, short_fingerprints.db) to Drive 00_SYSTEM/.
    """
    engine = drive_engine or DriveVaultEngine()
    results = {}
    keys_to_sync = aux_keys or list(AUXILIARY_DATABASES.keys())

    if (os.getenv("IS_TEST_ENV", "").lower() == "true" or "test_" in os.getenv("TEST_DB_PATH", "").lower()) and drive_engine is None:
        logger.warning("[SAFETY GUARD] Blocked auxiliary database upload in test mode")
        return {"status": "BLOCKED_TEST_MODE"}

    for key in keys_to_sync:
        cfg = AUXILIARY_DATABASES.get(key)
        if not cfg:
            continue

        filename = cfg["filename"]
        source_path = cfg["local_path"]

        if not source_path.exists():
            _init_auxiliary_db(source_path, cfg["init_sql"])

        flush_wal_checkpoint(source_path)

        is_valid, msg = verify_sqlite_integrity(source_path)
        if not is_valid:
            raise ValueError(f"Auxiliary database '{filename}' failed integrity check before upload: {msg}")

        sha = compute_sha256(source_path)
        size_bytes = source_path.stat().st_size
        logger.info(f"Uploading auxiliary database '{filename}' ({size_bytes} bytes, SHA256: {sha[:16]}...) to Drive...")

        res = engine.upload_database(local_path=source_path, filename=filename)
        logger.info(f"[+] Auxiliary database '{filename}' successfully uploaded to Drive (File ID: {res.get('id') if isinstance(res, dict) else res})")
        results[key] = res

    return results


class DatabaseSyncManager:
    """
    Unified manager for bidirectional synchronization of canonical and auxiliary
    databases between local storage and Google Drive 00_SYSTEM/ vault.
    
    Implements Milestone 1 interface contracts:
    - download_database() -> Path
    - upload_database() -> bool
    """

    def __init__(
        self,
        drive_engine: Optional[DriveVaultEngine] = None,
        canonical_path: Optional[Path] = None
    ):
        self.drive_engine = drive_engine
        self.canonical_path = canonical_path or DB_PATH

    def download_database(
        self,
        canonical_only: bool = False,
        target_path: Optional[Path] = None
    ) -> Path:
        """
        Downloads canonical database and auxiliary databases from Drive 00_SYSTEM/.
        Returns the local Path to the canonical database.
        """
        target = target_path or self.canonical_path
        res_canonical = download_canonical_database(
            target_path=target,
            drive_engine=self.drive_engine
        )

        if not canonical_only:
            try:
                download_auxiliary_databases(drive_engine=self.drive_engine)
            except Exception as aux_err:
                logger.warning(f"Auxiliary database download notice: {aux_err}")

        return res_canonical

    def upload_database(
        self,
        canonical_only: bool = False,
        source_path: Optional[Path] = None
    ) -> bool:
        """
        Flushes connections, WAL checkpoints, and uploads canonical database
        (and auxiliary databases if not canonical_only) to Drive 00_SYSTEM/.
        Returns True if successful.
        """
        source = source_path or self.canonical_path
        upload_canonical_database(
            source_path=source,
            drive_engine=self.drive_engine
        )

        if not canonical_only:
            try:
                upload_auxiliary_databases(drive_engine=self.drive_engine)
            except Exception as aux_err:
                logger.warning(f"Auxiliary database upload notice: {aux_err}")

        return True

    def flush_wal(self, db_path: Optional[Path] = None) -> bool:
        """Flushes WAL log for the canonical or specified database."""
        target = db_path or self.canonical_path
        return flush_wal_checkpoint(target)

    def verify_integrity(self, db_path: Optional[Path] = None) -> Tuple[bool, str]:
        """Runs PRAGMA integrity_check on the canonical or specified database."""
        target = db_path or self.canonical_path
        return verify_sqlite_integrity(target)

    def get_stats(self) -> Dict[str, Any]:
        """Gathers stats across canonical and auxiliary databases."""
        stats = {
            "canonical": get_database_stats(self.canonical_path),
            "canonical_sha256": compute_sha256(self.canonical_path) if self.canonical_path.exists() else None,
            "auxiliary": {}
        }
        for k, v in AUXILIARY_DATABASES.items():
            p = v["local_path"]
            if p.exists():
                try:
                    conn = sqlite3.connect(str(p))
                    cnt = conn.execute(f"SELECT COUNT(*) FROM {v['table']}").fetchone()[0]
                    conn.close()
                except Exception:
                    cnt = 0
                stats["auxiliary"][k] = {
                    "count": cnt,
                    "sha256": compute_sha256(p)
                }
        return stats


def main():
    parser = argparse.ArgumentParser(description="Private Cloud Database Synchronization CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # download
    dl_parser = subparsers.add_parser("download", help="Download DB from Google Drive")
    dl_parser.add_argument("--target", type=str, default=None, help="Local destination path")
    dl_parser.add_argument("--canonical-only", action="store_true", help="Download only canonical DB")
    dl_parser.add_argument("--auxiliary-only", action="store_true", help="Download only auxiliary DBs")

    # upload
    ul_parser = subparsers.add_parser("upload", help="Upload local DB to Google Drive")
    ul_parser.add_argument("--source", type=str, default=None, help="Local source path")
    ul_parser.add_argument("--canonical-only", action="store_true", help="Upload only canonical DB")
    ul_parser.add_argument("--auxiliary-only", action="store_true", help="Upload only auxiliary DBs")

    # verify
    vr_parser = subparsers.add_parser("verify", help="Verify integrity and show stats of local DB")
    vr_parser.add_argument("--path", type=str, default=None, help="Path to DB file")

    # stats
    subparsers.add_parser("stats", help="Display stats across canonical and auxiliary databases")

    args = parser.parse_args()

    try:
        manager = DatabaseSyncManager()
        if args.command == "download":
            if getattr(args, "auxiliary_only", False):
                download_auxiliary_databases()
            else:
                target = Path(args.target) if args.target else None
                manager.download_database(
                    canonical_only=getattr(args, "canonical_only", False),
                    target_path=target
                )
        elif args.command == "upload":
            if getattr(args, "auxiliary_only", False):
                upload_auxiliary_databases()
            else:
                source = Path(args.source) if args.source else None
                manager.upload_database(
                    canonical_only=getattr(args, "canonical_only", False),
                    source_path=source
                )
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
        elif args.command == "stats":
            stats = manager.get_stats()
            print(f"Canonical: {stats['canonical']} (SHA: {stats['canonical_sha256']})")
            for k, v in stats.get("auxiliary", {}).items():
                print(f"Auxiliary '{k}': count={v['count']} (SHA: {v['sha256']})")
    except Exception as e:
        logger.error(f"Operation '{args.command}' failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
