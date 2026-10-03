import sys
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from engines.upload_engine import UploadEngine

ue = UploadEngine()
yt = ue.get_youtube_service()
res = yt.channels().list(part="contentDetails", mine=True).execute()
uploads_playlist_id = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

all_vids = []
page_token = None
while True:
    pl = yt.playlistItems().list(part="snippet,status", playlistId=uploads_playlist_id, maxResults=50, pageToken=page_token).execute()
    for item in pl.get("items", []):
        all_vids.append((item["snippet"]["resourceId"]["videoId"], item["snippet"]["title"].strip(), item.get("status", {}).get("privacyStatus"), item["snippet"].get("publishedAt")))
    page_token = pl.get("nextPageToken")
    if not page_token or len(all_vids) >= 200:
        break

title_counts = Counter([v[1].lower() for v in all_vids])
dupes = {t: c for t, c in title_counts.items() if c > 1}
print(f"Total fetched YouTube videos: {len(all_vids)}")
print(f"Duplicate titles on YouTube: {len(dupes)}")
for t, c in dupes.items():
    matching_vids = [v for v in all_vids if v[1].lower() == t]
    print(f"  '{t}' ({c} times): {matching_vids}")
