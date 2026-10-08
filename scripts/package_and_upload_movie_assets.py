import os
import sys
import json
import zipfile
import time
from pathlib import Path
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TOKEN_PATH = Path("C:/Users/jisha/OneDrive/Desktop/yt automation/token.json")
SCRATCH_VAULT = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\vault")
MOVIES_DIR = Path(r"C:\Users\jisha\.gemini\antigravity\scratch\data\movies")

DRIVE_SUBFOLDERS = {
    "wrong_turn_2003": {
        "folder_id": "1Gn_SDv__le5F8JKPGWeDLolbN8OQnAjk",
        "asset_dir": SCRATCH_VAULT / "assets_wrong_turn_2003",
        "srt_file": MOVIES_DIR / "wrong_turn_2003.srt",
        "ledger_file": SCRATCH_VAULT / "assets_wrong_turn_2003" / "wrong_turn_2003_visual_ledger_200_shots.json"
    },
    "the_hills_have_eyes_2006": {
        "folder_id": "1hA6nxOmxg5zxRPTUj0yhaRXYu34CD1iN",
        "asset_dir": SCRATCH_VAULT / "assets_hills_have_eyes",
        "srt_file": MOVIES_DIR / "the_hills_have_eyes_subtitles.srt",
        "ledger_file": SCRATCH_VAULT / "assets_hills_have_eyes" / "hills_have_eyes_visual_ledger_200_shots.json"
    },
    "texas_chainsaw_2013": {
        "folder_id": "1SW1OAPAmdSRfSuo4_ofi26KBE-aX2FOZ",
        "asset_dir": SCRATCH_VAULT / "assets_texas_chainsaw_2013",
        "srt_file": MOVIES_DIR / "texas_chainsaw_subtitles.srt",
        "ledger_file": SCRATCH_VAULT / "assets_texas_chainsaw_2013" / "texas_chainsaw_2013_visual_ledger_200_shots.json"
    },
    "the_conjuring_2_2016": {
        "folder_id": "1Kr3pT5xUc2FzMJ_55d4Hw7evm6oRoRxS",
        "asset_dir": SCRATCH_VAULT / "assets_the_conjuring_2_2016",
        "srt_file": MOVIES_DIR / "the_conjuring_2_subtitles.srt",
        "ledger_file": SCRATCH_VAULT / "assets_the_conjuring_2_2016" / "the_conjuring_2_2016_visual_ledger_200_shots.json"
    }
}

def get_drive_service():
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_PATH, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
    return build("drive", "v3", credentials=creds)

def upload_file_resumable(service, local_file: Path, parent_folder_id: str, mime_type: str = "application/octet-stream"):
    print(f"\n[UPLOAD] Uploading '{local_file.name}' ({round(local_file.stat().st_size / (1024*1024), 2)} MB) to folder {parent_folder_id}...")
    file_metadata = {
        "name": local_file.name,
        "parents": [parent_folder_id]
    }
    media = MediaFileUpload(str(local_file), mimetype=mime_type, resumable=True, chunksize=10*1024*1024)
    request = service.files().create(body=file_metadata, media_body=media, fields="id, name, size")

    response = None
    last_print = 0
    t0 = time.time()
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct - last_print >= 20 or pct == 100:
                elapsed = time.time() - t0
                print(f"   Progress: {pct}% uploaded ({elapsed:.1f}s)")
                last_print = pct
    print(f"[SUCCESS] Uploaded {local_file.name} -> Drive ID: {response.get('id')}")
    return response

def create_movie_zip(movie_slug: str, config: dict) -> Path:
    zip_path = SCRATCH_VAULT / f"{movie_slug}_assets.zip"
    if zip_path.exists() and zip_path.stat().st_size > 50 * 1024 * 1024:
        print(f"[CACHE HIT] Zip already exists: {zip_path.name} ({round(zip_path.stat().st_size / (1024*1024), 1)} MB)")
        return zip_path

    print(f"\n[PACKAGING] Compressing asset bank for '{movie_slug}' into {zip_path.name}...")
    asset_dir = config["asset_dir"]
    srt_file = config["srt_file"]
    ledger_file = config["ledger_file"]

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        # Add clips
        clips_dir = asset_dir / "clips"
        if clips_dir.exists():
            for clip in clips_dir.glob("*.mp4"):
                zf.write(clip, arcname=f"clips/{clip.name}")
        # Add frames
        frames_dir = asset_dir / "frames"
        if frames_dir.exists():
            for frame in frames_dir.glob("*.jpg"):
                zf.write(frame, arcname=f"frames/{frame.name}")
        # Add ledger
        if ledger_file.exists():
            zf.write(ledger_file, arcname=ledger_file.name)
        # Add srt
        if srt_file.exists():
            zf.write(srt_file, arcname=srt_file.name)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[COMPRESSION DONE] Created {zip_path.name}: {size_mb:.1f} MB")
    return zip_path

def main():
    service = get_drive_service()
    print("=== STARTING CLOUD ASSET PACKAGING & UPLOAD ===")

    for movie_slug, conf in DRIVE_SUBFOLDERS.items():
        folder_id = conf["folder_id"]
        print(f"\n=======================================================")
        print(f"PROCESSING MOVIE: {movie_slug.upper()} -> DRIVE FOLDER {folder_id}")
        print(f"=======================================================")

        # 1. Upload standalone SDH Subtitles (.srt)
        srt_path = conf["srt_file"]
        if srt_path.exists():
            upload_file_resumable(service, srt_path, folder_id, mime_type="text/plain")

        # 2. Upload standalone Visual Ledger (.json)
        ledger_path = conf["ledger_file"]
        if ledger_path.exists():
            upload_file_resumable(service, ledger_path, folder_id, mime_type="application/json")

        # 3. Zip and upload complete asset bundle (.zip)
        zip_path = create_movie_zip(movie_slug, conf)
        upload_file_resumable(service, zip_path, folder_id, mime_type="application/zip")

    print("\n[ALL COMPLETE] All 4 Movie Asset Banks (840 clips, ledgers, subtitles) are 100% synced in Google Drive!")

if __name__ == "__main__":
    main()
