import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

db_path = Path("data/database/pipeline.db")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("--- RECENT UPLOADS (since Sept 25) ---")
cur.execute("SELECT id, job_id, youtube_video_id, status, scheduled_publish_at, title FROM uploads WHERE scheduled_publish_at >= '2026-09-25' OR scheduled_publish_at IS NULL ORDER BY id DESC LIMIT 30")
for r in cur.fetchall():
    print(r)

print("\n--- RECENT JOBS ---")
cur.execute("PRAGMA table_info(jobs)")
cols = [c[1] for c in cur.fetchall()]
print("Jobs columns:", cols)
cur.execute(f"SELECT id, topic_id, state, created_at, updated_at FROM jobs ORDER BY id DESC LIMIT 20")
for r in cur.fetchall():
    print(r)

print("\n--- STATUS COUNTS IN UPLOADS ---")
cur.execute("SELECT status, count(*) FROM uploads GROUP BY status")
for r in cur.fetchall():
    print(r)

print("\n--- STATUS COUNTS IN JOBS ---")
cur.execute("SELECT state, count(*) FROM jobs GROUP BY state")
for r in cur.fetchall():
    print(r)

conn.close()
