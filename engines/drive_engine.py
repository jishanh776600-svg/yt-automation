"""
Google Drive Vault Engine.
Manages persistent cloud video storage for YouTube Shorts using Google Drive API v3.
Implements the 4-stage vault lifecycle:
  YouTube_Shorts_Vault/
  ├── 01_READY/          (Pre-rendered, QA-verified MP4s awaiting scheduled publishing)
  ├── 02_PROCESSING/     (Videos currently claimed by an active upload workflow)
  ├── 03_PUBLISHED/      (Historical archive of successfully published YouTube Shorts)
  └── 04_FAILED/         (Videos that failed QA or upload verification)
"""
import io
import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

VAULT_ROOT_NAME = "YouTube_Shorts_Vault"
SUBFOLDERS = ["01_READY", "02_PROCESSING", "03_PUBLISHED", "04_FAILED"]


class DriveVaultEngine:
    """Manages YouTube Shorts cloud video vault using Google Drive API v3."""

    def __init__(self, token_path: Optional[Path] = None):
        self.token_path = token_path or (PROJECT_ROOT / "token.json")
        self._drive_service = None
        self._vault_cache: Dict[str, str] = {}  # Cache of folder_name -> folder_id

    def get_drive_service(self):
        """Initializes and returns the authenticated Google Drive API v3 client."""
        if self._drive_service is not None:
            return self._drive_service

        if not self.token_path.exists():
            raise FileNotFoundError(f"OAuth token not found at {self.token_path}. Run auth_youtube.py first.")

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_authorized_user_file(str(self.token_path))
            self._drive_service = build("drive", "v3", credentials=creds)
            return self._drive_service
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive API client: {e}")
            raise

    def get_storage_quota(self) -> Optional[Dict[str, Any]]:
        """
        Retrieves Google Drive storage quota metrics via Drive API about.get(fields="storageQuota").
        Returns {'limit': int, 'usage': int, 'usage_in_drive': int, 'usage_in_trash': int} or None.
        Includes a 5-minute memory cache to prevent burning Drive API calls on rapid refreshes.
        """
        import time
        if hasattr(self, "_storage_quota_cache") and self._storage_quota_cache:
            cache_time, data = self._storage_quota_cache
            if time.time() - cache_time < 300:  # 5-minute TTL
                return data

        if not self.token_path.exists():
            return None

        try:
            drive = self.get_drive_service()
            about = drive.about().get(fields="storageQuota").execute()
            raw = about.get("storageQuota", {})
            data = {
                "limit": int(raw["limit"]) if raw.get("limit") is not None else None,
                "usage": int(raw["usage"]) if raw.get("usage") is not None else None,
                "usage_in_drive": int(raw["usageInDrive"]) if raw.get("usageInDrive") is not None else None,
                "usage_in_trash": int(raw["usageInTrash"]) if raw.get("usageInTrash") is not None else None,
            }
            self._storage_quota_cache = (time.time(), data)
            return data
        except Exception as e:
            logger.warning(f"Error fetching Google Drive storage quota: {e}")
            return None

    def find_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Searches for an existing folder by name (and optional parent).
        Returns folder metadata dict {'id': ..., 'name': ...} or None.
        """
        drive = self.get_drive_service()
        query = f"mimeType = 'application/vnd.google-apps.folder' and name = '{folder_name}' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        try:
            res = drive.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, parents, createdTime)",
                pageSize=10
            ).execute()
            files = res.get("files", [])
            if files:
                return files[0]
            return None
        except Exception as e:
            logger.error(f"Error querying Google Drive folder '{folder_name}': {e}")
            raise

    def create_folder(self, folder_name: str, parent_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates a new folder in Google Drive."""
        drive = self.get_drive_service()
        file_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder"
        }
        if parent_id:
            file_metadata["parents"] = [parent_id]

        try:
            folder = drive.files().create(
                body=file_metadata,
                fields="id, name, parents"
            ).execute()
            logger.info(f"[+] Created Google Drive folder: '{folder_name}' (ID: {folder.get('id')})")
            return folder
        except Exception as e:
            logger.error(f"Error creating Google Drive folder '{folder_name}': {e}")
            raise

    def inspect_or_init_vault(self, create_if_missing: bool = False) -> Dict[str, Optional[str]]:
        """
        Locates the YouTube_Shorts_Vault and all 4 subfolders.
        If create_if_missing=False, returns dictionary with None for any missing folders.
        If create_if_missing=True, creates only the missing folders.
        """
        structure: Dict[str, Optional[str]] = {
            "root": None,
            "01_READY": None,
            "02_PROCESSING": None,
            "03_PUBLISHED": None,
            "04_FAILED": None
        }

        root_folder = self.find_folder(VAULT_ROOT_NAME)
        if not root_folder:
            if not create_if_missing:
                return structure
            root_folder = self.create_folder(VAULT_ROOT_NAME)

        root_id = root_folder["id"]
        structure["root"] = root_id
        self._vault_cache["root"] = root_id

        for sub_name in SUBFOLDERS:
            sub = self.find_folder(sub_name, parent_id=root_id)
            if not sub:
                if create_if_missing:
                    sub = self.create_folder(sub_name, parent_id=root_id)
                    structure[sub_name] = sub["id"]
                    self._vault_cache[sub_name] = sub["id"]
                else:
                    structure[sub_name] = None
            else:
                structure[sub_name] = sub["id"]
                self._vault_cache[sub_name] = sub["id"]

        return structure

    def get_folder_id(self, folder_name: str, create_if_missing: bool = True) -> str:
        """Retrieves folder ID from cache or queries Drive."""
        if folder_name in self._vault_cache and self._vault_cache[folder_name]:
            return self._vault_cache[folder_name]

        vault = self.inspect_or_init_vault(create_if_missing=create_if_missing)
        folder_id = vault.get(folder_name)
        if not folder_id:
            raise FileNotFoundError(f"Google Drive folder '{folder_name}' not found in vault.")
        return folder_id

    def list_files_in_folder(self, folder_name: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Lists all non-trashed files within a specific vault subfolder."""
        drive = self.get_drive_service()
        folder_id = self.get_folder_id(folder_name, create_if_missing=False)

        query = f"'{folder_id}' in parents and trashed = false and mimeType != 'application/vnd.google-apps.folder'"
        try:
            res = drive.files().list(
                q=query,
                spaces="drive",
                fields="files(id, name, mimeType, size, createdTime, description, properties)",
                orderBy="createdTime asc",
                pageSize=limit
            ).execute()
            return res.get("files", [])
        except Exception as e:
            logger.error(f"Error listing files in vault folder '{folder_name}': {e}")
            raise

    def upload_video_to_vault(
        self,
        local_path: Path,
        target_folder: str = "01_READY",
        custom_filename: Optional[str] = None,
        description: str = "",
        metadata_properties: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Uploads a rendered MP4 video file to a specific vault subfolder.
        """
        if not local_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_path}")

        drive = self.get_drive_service()
        folder_id = self.get_folder_id(target_folder, create_if_missing=True)

        from googleapiclient.http import MediaFileUpload
        filename = custom_filename or local_path.name

        file_metadata = {
            "name": filename,
            "parents": [folder_id],
            "description": description or f"Rendered YouTube Short: {filename}",
            "properties": metadata_properties or {}
        }

        media = MediaFileUpload(
            str(local_path),
            mimetype="video/mp4",
            resumable=True
        )

        logger.info(f"Uploading '{filename}' ({local_path.stat().st_size / (1024*1024):.2f} MB) to Drive vault '{target_folder}'...")
        file_obj = drive.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, size, webViewLink, createdTime, parents"
        ).execute()

        logger.info(f"[+] Successfully uploaded to Google Drive vault: '{filename}' (File ID: {file_obj.get('id')})")
        return file_obj

    def download_video_from_vault(self, file_id: str, local_dest_path: Path) -> Path:
        """Downloads a video from Google Drive to local filesystem."""
        local_dest_path.parent.mkdir(parents=True, exist_ok=True)
        drive = self.get_drive_service()

        from googleapiclient.http import MediaIoBaseDownload

        request = drive.files().get_media(fileId=file_id)
        with open(local_dest_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request, chunksize=1024 * 1024 * 5)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(f"Downloading from Drive: {int(status.progress() * 100)}%")

        logger.info(f"[+] Downloaded Drive file {file_id} to {local_dest_path} ({local_dest_path.stat().st_size} bytes)")
        return local_dest_path

    def move_file_in_vault(self, file_id: str, from_folder: str, to_folder: str) -> Dict[str, Any]:
        """
        Moves a file between vault folders by updating parent IDs (no copy/duplicate).
        """
        drive = self.get_drive_service()
        from_id = self.get_folder_id(from_folder, create_if_missing=True)
        to_id = self.get_folder_id(to_folder, create_if_missing=True)

        try:
            updated_file = drive.files().update(
                fileId=file_id,
                addParents=to_id,
                removeParents=from_id,
                fields="id, name, parents"
            ).execute()
            logger.info(f"[+] Moved file {file_id} in Drive from '{from_folder}' to '{to_folder}'")
            return updated_file
        except Exception as e:
            logger.error(f"Failed to move file {file_id} from '{from_folder}' to '{to_folder}': {e}")
            raise

    def get_file_metadata(self, file_id: str) -> Dict[str, Any]:
        """Retrieves comprehensive metadata and custom properties of a Drive file."""
        drive = self.get_drive_service()
        try:
            return drive.files().get(
                fileId=file_id,
                fields="id, name, mimeType, size, createdTime, description, properties, webViewLink, parents"
            ).execute()
        except Exception as e:
            logger.error(f"Error fetching metadata for Drive file {file_id}: {e}")
            raise

    def get_ready_stock_count(self) -> int:
        """Returns the current number of ready-to-publish videos in '01_READY'."""
        try:
            vault = self.inspect_or_init_vault(create_if_missing=False)
            if not vault.get("01_READY"):
                return 0
            files = self.list_files_in_folder("01_READY")
            return len(files)
        except Exception as e:
            logger.warning(f"Could not count ready stock: {e}")
            return 0
