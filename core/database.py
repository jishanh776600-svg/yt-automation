"""
Database engine and session management.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, scoped_session
from config.settings import DB_PATH
from core.models import Base

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30.0}
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Configures SQLite for safe concurrent reads/writes via WAL mode and busy timeout."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    finally:
        cursor.close()


SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))


def rebind_engine(new_db_path):
    """Rebinds database engine and SessionLocal to a new database path (e.g. for isolated test suites)."""
    global engine, SessionLocal
    try:
        SessionLocal.remove()
    except Exception:
        pass
    try:
        engine.dispose()
    except Exception:
        pass
    engine = create_engine(
        f"sqlite:///{new_db_path}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30.0}
    )
    SessionLocal.configure(bind=engine)


def init_db(target_engine=None):
    """Initializes tables in database and applies idempotent column migrations."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)

    # Safe idempotent SQLite column migrations
    with eng.connect() as conn:
        try:
            # 1. scripts table
            script_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(scripts)")).fetchall()]
            if "hook_archetype" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN hook_archetype VARCHAR(64)"))
            if "duration_target" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN duration_target VARCHAR(64)"))
            if "event_id" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN event_id VARCHAR(64)"))
            if "script_document_json" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN script_document_json TEXT"))
            if "provenance_complete" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN provenance_complete BOOLEAN DEFAULT 0"))
            if "validation_status" not in script_cols:
                conn.execute(text("ALTER TABLE scripts ADD COLUMN validation_status VARCHAR(32) DEFAULT 'PENDING'"))

            # 2. renders table
            render_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(renders)")).fetchall()]
            if "bgm_mood" not in render_cols:
                conn.execute(text("ALTER TABLE renders ADD COLUMN bgm_mood VARCHAR(128)"))
            if "motion_style" not in render_cols:
                conn.execute(text("ALTER TABLE renders ADD COLUMN motion_style VARCHAR(64)"))

            # 3. experiments table
            exp_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(experiments)")).fetchall()]
            exp_new_cols = {
                "experiment_group_id": "VARCHAR(64)",
                "job_id": "VARCHAR(64)",
                "topic_id": "VARCHAR(64)",
                "hook_archetype": "VARCHAR(64)",
                "duration_target": "VARCHAR(64)",
                "bgm_mood": "VARCHAR(128)",
                "motion_style": "VARCHAR(64)",
                "category": "VARCHAR(64)",
                "selection_mode": "VARCHAR(32)",
                "strategy_reason": "TEXT",
                "combination_type": "VARCHAR(32)",
                "failure_reason": "TEXT",
                "upload_id": "VARCHAR(64)",
                "youtube_video_id": "VARCHAR(64)",
                "outcome_snapshot_id": "INTEGER"
            }
            for col, col_type in exp_new_cols.items():
                if col not in exp_cols:
                    conn.execute(text(f"ALTER TABLE experiments ADD COLUMN {col} {col_type}"))

            # 4. uploads table
            upload_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(uploads)")).fetchall()]
            if "scheduled_publish_at" not in upload_cols:
                conn.execute(text("ALTER TABLE uploads ADD COLUMN scheduled_publish_at DATETIME"))
            if "reconciliation_metadata" not in upload_cols:
                conn.execute(text("ALTER TABLE uploads ADD COLUMN reconciliation_metadata TEXT"))

            # 5. assets table
            asset_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(assets)")).fetchall()]
            if "metadata_json" not in asset_cols:
                conn.execute(text("ALTER TABLE assets ADD COLUMN metadata_json TEXT"))

            # 6. provider_usage table
            pu_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(provider_usage)")).fetchall()]
            pu_new_cols = {
                "model_name": "VARCHAR(64)",
                "cost_usd": "FLOAT",
                "endpoint": "VARCHAR(128)",
                "status_code": "INTEGER",
                "rate_limit": "INTEGER",
                "rate_remaining": "INTEGER",
                "rate_reset": "INTEGER",
                "is_observed": "BOOLEAN DEFAULT 1",
                "created_at": "DATETIME"
            }
            for col, col_type in pu_new_cols.items():
                if col not in pu_cols:
                    conn.execute(text(f"ALTER TABLE provider_usage ADD COLUMN {col} {col_type}"))

            # 7. performance_snapshots table
            perf_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(performance_snapshots)")).fetchall()]
            if "validation_status" not in perf_cols:
                conn.execute(text("ALTER TABLE performance_snapshots ADD COLUMN validation_status VARCHAR(32) DEFAULT 'VALID_REAL'"))

            # 8. articles table
            art_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(articles)")).fetchall()]
            if art_cols:
                if "category" not in art_cols:
                    conn.execute(text("ALTER TABLE articles ADD COLUMN category VARCHAR(64) DEFAULT 'Geopolitics'"))
                if "freshness_score" not in art_cols:
                    conn.execute(text("ALTER TABLE articles ADD COLUMN freshness_score FLOAT DEFAULT 0.0"))
                if "source_confidence" not in art_cols:
                    conn.execute(text("ALTER TABLE articles ADD COLUMN source_confidence FLOAT DEFAULT 0.0"))
                if "composite_score" not in art_cols:
                    conn.execute(text("ALTER TABLE articles ADD COLUMN composite_score FLOAT DEFAULT 0.0"))

            # 9. topics table (Phase 2 Event Intelligence)
            topic_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(topics)")).fetchall()]
            if topic_cols:
                if "event_id" not in topic_cols:
                    conn.execute(text("ALTER TABLE topics ADD COLUMN event_id VARCHAR(64)"))
                if "verification_state" not in topic_cols:
                    conn.execute(text("ALTER TABLE topics ADD COLUMN verification_state VARCHAR(64) DEFAULT 'SINGLE_CREDIBLE_SOURCE'"))
                if "independent_sources_count" not in topic_cols:
                    conn.execute(text("ALTER TABLE topics ADD COLUMN independent_sources_count INTEGER DEFAULT 1"))
                if "event_card_json" not in topic_cols:
                    conn.execute(text("ALTER TABLE topics ADD COLUMN event_card_json TEXT"))

            # 10. claims table (Phase 2 Provenance)
            claim_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(claims)")).fetchall()]
            if claim_cols:
                if "source_article_id" not in claim_cols:
                    conn.execute(text("ALTER TABLE claims ADD COLUMN source_article_id VARCHAR(64)"))
                if "publisher" not in claim_cols:
                    conn.execute(text("ALTER TABLE claims ADD COLUMN publisher VARCHAR(255)"))
                if "source_url" not in claim_cols:
                    conn.execute(text("ALTER TABLE claims ADD COLUMN source_url TEXT"))
                if "evidence_excerpt" not in claim_cols:
                    conn.execute(text("ALTER TABLE claims ADD COLUMN evidence_excerpt TEXT"))

            conn.commit()
        except Exception:
            pass


def get_db():
    """Context generator for db session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
