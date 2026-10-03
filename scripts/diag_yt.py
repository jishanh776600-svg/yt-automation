import sys
import sqlite3
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from engines.upload_engine import UploadEngine

ue = UploadEngine()
yt = ue.get_youtube_service()

res = yt.channels().list(part="contentDetails", mine=True).execute()
uploads_playlist_id = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
print(f"Channel Uploads Playlist: {uploads_playlist_id}")

playlist_items = yt.playlistItems().list(part="snippet,status", playlistId=uploads_playlist_id, maxResults=30).execute()
items = playlist_items.get("items", [])
print(f"Total YouTube videos retrieved: {len(items)}\n")

yt_videos = []
for item in items:
    snippet = item["snippet"]
    vid_id = snippet["resourceId"]["videoId"]
    title = snippet["title"]
    pub_at = snippet.get("publishedAt")
    status = item.get("status", {})
    privacy = status.get("privacyStatus")
    yt_videos.append((vid_id, title, pub_at, privacy))
    print(f"YT: {vid_id} | Priv: {privacy} | PubAt: {pub_at} | Title: {title}")

# Now query DB for these video IDs
conn = sqlite3.connect("data/database/pipeline.db")
cur = conn.cursor()

print("\n--- DB STATUS FOR RECENT YOUTUBE VIDEOS ---")
for vid_id, title, pub_at, privacy in yt_videos[:15]:
    cur.execute("SELECT id, job_id, status, scheduled_publish_at, title FROM uploads WHERE youtube_video_id = ?", (vid_id,))
    row = cur.fetchone()
    print(f"Vid {vid_id}: DB Row = {row}")

conn.close()
