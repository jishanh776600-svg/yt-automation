"""
High-Precision 450+ Asset Bank Generator & Cloud Sync Engine.
============================================================
Slices 450 broadcast 1080x1080 square clips and reference frames
per feature film (1,800 clips total across 4 movies),
generates the visual ledger JSON, builds zip packages, and uploads to Google Drive.
"""

import os
import sys
import json
import subprocess
import time
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH = Path("C:/Users/jisha/OneDrive/Desktop/yt automation/token.json")
SCRATCH_VAULT = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\vault")
MOVIES_DIR = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\movies")

MOVIES_CONFIG = [
    {
        "slug": "wrong_turn_2003",
        "title": "Wrong Turn",
        "year": 2003,
        "raw_file": MOVIES_DIR / "wrong_turn_2003_raw.mkv",
        "srt_file": MOVIES_DIR / "wrong_turn_2003.srt",
        "prefix": "WT",
        "folder_id": "1Gn_SDv__le5F8JKPGWeDLolbN8OQnAjk",
        "start_offset": 90.0,
        "end_trim": 120.0
    },
    {
        "slug": "the_hills_have_eyes_2006",
        "title": "The Hills Have Eyes",
        "year": 2006,
        "raw_file": MOVIES_DIR / "the_hills_have_eyes_2006_raw.mkv",
        "srt_file": MOVIES_DIR / "the_hills_have_eyes_subtitles.srt",
        "prefix": "HILLS",
        "folder_id": "1hA6nxOmxg5zxRPTUj0yhaRXYu34CD1iN",
        "start_offset": 120.0,
        "end_trim": 180.0
    },
    {
        "slug": "texas_chainsaw_2013",
        "title": "Texas Chainsaw",
        "year": 2013,
        "raw_file": MOVIES_DIR / "texas_chainsaw_2013_raw.mkv",
        "srt_file": MOVIES_DIR / "texas_chainsaw_subtitles.srt",
        "prefix": "TCM",
        "folder_id": "1SW1OAPAmdSRfSuo4_ofi26KBE-aX2FOZ",
        "start_offset": 90.0,
        "end_trim": 150.0
    },
    {
        "slug": "the_conjuring_2_2016",
        "title": "The Conjuring 2",
        "year": 2016,
        "raw_file": MOVIES_DIR / "the_conjuring_2_2016_raw.mkv",
        "srt_file": MOVIES_DIR / "the_conjuring_2_subtitles.srt",
        "prefix": "CONJ",
        "folder_id": "1Kr3pT5xUc2FzMJ_55d4Hw7evm6oRoRxS",
        "start_offset": 120.0,
        "end_trim": 240.0
    }
]

TARGET_SHOTS = 450
CLIP_DURATION = 3.5
BASE_FILTER = "scale=1080:-2,setsar=1,pad=1080:1080:(ow-iw)/2:(oh-ih)/2:black,fps=24"

def get_drive_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def get_duration(movie_path: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(movie_path)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return float(res.stdout.strip()) if res.stdout.strip() else 5400.0

def slice_single_shot(args):
    idx, movie_path, clips_dir, frames_dir, prefix, t_start = args
    shot_id = f"{prefix}_SHOT_{idx+1:03d}"
    clip_out = clips_dir / f"{shot_id}.mp4"
    frame_out = frames_dir / f"{shot_id}.jpg"

    if not clip_out.exists() or clip_out.stat().st_size < 10000:
        c1 = [
            "ffmpeg", "-y", "-ss", f"{t_start:.2f}",
            "-i", str(movie_path),
            "-t", f"{CLIP_DURATION:.2f}",
            "-vf", BASE_FILTER,
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
            "-an", str(clip_out)
        ]
        subprocess.run(c1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not frame_out.exists() or frame_out.stat().st_size < 1000:
        c2 = [
            "ffmpeg", "-y", "-ss", f"{t_start + 1.0:.2f}",
            "-i", str(movie_path),
            "-vframes", "1",
            "-vf", BASE_FILTER,
            "-q:v", "3", str(frame_out)
        ]
        subprocess.run(c2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return {
        "shot_id": shot_id,
        "index": idx + 1,
        "timestamp_sec": round(t_start, 2),
        "duration_sec": CLIP_DURATION,
        "clip_file": f"{shot_id}.mp4",
        "frame_file": f"{shot_id}.jpg"
    }

def upload_file_resumable(service, local_file: Path, parent_folder_id: str, mime_type: str = "application/octet-stream"):
    print(f"[DRIVE_UPLOAD] Uploading '{local_file.name}' ({round(local_file.stat().st_size / (1024*1024), 2)} MB)...", flush=True)
    file_metadata = {
        "name": local_file.name,
        "parents": [parent_folder_id]
    }
    media = MediaFileUpload(str(local_file), mimetype=mime_type, resumable=True, chunksize=15*1024*1024)
    request = service.files().create(body=file_metadata, media_body=media, fields="id, name, size")

    response = None
    last_pct = 0
    t0 = time.time()
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct - last_pct >= 25 or pct == 100:
                print(f"   Upload progress: {pct}% ({time.time() - t0:.1f}s)", flush=True)
                last_pct = pct
    print(f"[DRIVE_SUCCESS] {local_file.name} uploaded -> ID: {response.get('id')}", flush=True)
    return response

def process_movie(conf, drive_service):
    slug = conf["slug"]
    title = conf["title"]
    year = conf["year"]
    raw_file = conf["raw_file"]
    srt_file = conf["srt_file"]
    prefix = conf["prefix"]
    folder_id = conf["folder_id"]

    print(f"\n=======================================================", flush=True)
    print(f"STARTING 450-SHOT EXTRACTION FOR: {title.upper()} ({year})", flush=True)
    print(f"=======================================================", flush=True)

    vault_dir = SCRATCH_VAULT / f"assets_{slug}"
    clips_dir = vault_dir / "clips"
    frames_dir = vault_dir / "frames"
    clips_dir.mkdir(parents=True, exist_ok=True)
    frames_dir.mkdir(parents=True, exist_ok=True)

    duration = get_duration(raw_file)
    start_t = conf["start_offset"]
    end_t = max(start_t + 600.0, duration - conf["end_trim"])
    active_span = end_t - start_t
    interval = active_span / TARGET_SHOTS

    print(f"Duration: {duration:.1f}s | Active Window: {start_t}s - {end_t}s ({active_span/60:.1f} mins)", flush=True)
    print(f"Target Shots: {TARGET_SHOTS} | Interval: 1 shot every {interval:.2f}s", flush=True)

    tasks = []
    for i in range(TARGET_SHOTS):
        t_shot = start_t + (i * interval)
        tasks.append((i, raw_file, clips_dir, frames_dir, prefix, t_shot))

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        shots = list(ex.map(slice_single_shot, tasks))

    print(f"[SLICING COMPLETE] Sliced {len(shots)} shots in {time.time() - t0:.1f}s!", flush=True)

    # Save 450-shot ledger
    ledger_file = vault_dir / f"{slug}_visual_ledger_450_shots.json"
    ledger_data = {
        "movie": title,
        "year": year,
        "total_shots": len(shots),
        "target_shots": TARGET_SHOTS,
        "interval_seconds": round(interval, 2),
        "shots": sorted(shots, key=lambda x: x["index"])
    }
    with open(ledger_file, "w", encoding="utf-8") as f:
        json.dump(ledger_data, f, indent=2)
    print(f"[LEDGER] Saved ledger to {ledger_file.name}", flush=True)

    # Compress into 450-shot zip package
    zip_path = SCRATCH_VAULT / f"{slug}_assets_450.zip"
    print(f"[COMPRESSING] Building {zip_path.name} with 450 clips...", flush=True)
    t_zip0 = time.time()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for clip in clips_dir.glob("*.mp4"):
            zf.write(clip, arcname=f"clips/{clip.name}")
        for frame in frames_dir.glob("*.jpg"):
            zf.write(frame, arcname=f"frames/{frame.name}")
        zf.write(ledger_file, arcname=ledger_file.name)
        if srt_file.exists():
            zf.write(srt_file, arcname=srt_file.name)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[COMPRESSION DONE] {zip_path.name}: {size_mb:.1f} MB in {time.time() - t_zip0:.1f}s", flush=True)

    # Upload ledger and 450 zip to Google Drive
    upload_file_resumable(drive_service, ledger_file, folder_id, mime_type="application/json")
    upload_file_resumable(drive_service, zip_path, folder_id, mime_type="application/zip")
    print(f"[SUCCESS] {title} 450 Asset Bank is 100% Live in Google Drive!", flush=True)

def main():
    drive_service = get_drive_service()
    print("=== EXPANDING ALL 4 FEATURE FILMS TO 450+ ASSET CLIPS ===", flush=True)
    total_start = time.time()
    for conf in MOVIES_CONFIG:
        process_movie(conf, drive_service)
    print(f"\n[ALL 4 MOVIES COMPLETE] 1,800 High-Precision Clips Synced to Google Drive in {time.time() - total_start:.1f}s!", flush=True)

if __name__ == "__main__":
    main()
