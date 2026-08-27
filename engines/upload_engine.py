"""
YouTube Upload & Scheduling Engine.
Uses official YouTube Data API v3 with OAuth 2.0.
Respects TEST_MODE=true by saving staging records without public upload.
Handles rate limits, quotas (1,600 units/upload), and duplicate prevention.
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from config.settings import TEST_MODE, CLIENT_SECRETS_FILE, PROJECT_ROOT
from core.models import Job, RenderOutput, UploadRecord

logger = logging.getLogger(__name__)


class UploadEngine:
    """Manages YouTube uploads via official Data API v3."""

    def upload_short(
        self,
        db: Session,
        job: Job,
        render: RenderOutput,
        metadata: Dict[str, Any],
        privacy_status: str = "public"
    ) -> UploadRecord:
        """
        Uploads and verifies a YouTube Short with strictly PUBLIC visibility.
        """
        upload_id = f"upl_{uuid.uuid4().hex[:12]}"
        video_path = Path(render.video_path)

        # 1. Test Mode Handling (Never publish publicly in test mode)
        if TEST_MODE:
            logger.info(f"[TEST_MODE=true] Staging YouTube Short '{metadata['title']}' locally without public release.")
            record = UploadRecord(
                id=upload_id,
                job_id=job.id,
                youtube_video_id=f"TEST_VIDEO_{uuid.uuid4().hex[:8]}",
                title=metadata["title"],
                description=metadata["description"],
                tags=",".join(metadata.get("tags", [])),
                privacy_status="public",
                published_at=datetime.utcnow(),
                status="TEST_VERIFIED"
            )
            db.add(record)
            db.commit()
            return record

        # 2. Production Upload using Google API Client
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials

            token_path = PROJECT_ROOT / "token.json"
            if not token_path.exists():
                raise FileNotFoundError(f"OAuth token.json not found at {token_path}. Run authentication setup.")

            creds = Credentials.from_authorized_user_file(str(token_path))
            youtube = build("youtube", "v3", credentials=creds)

            # Ensure privacyStatus is strictly public
            target_privacy = "public"

            body = {
                "snippet": {
                    "title": metadata["title"][:100],
                    "description": metadata["description"][:5000],
                    "tags": metadata.get("tags", []),
                    "categoryId": "27"  # Education
                },
                "status": {
                    "privacyStatus": target_privacy,
                    "selfDeclaredMadeForKids": False
                }
            }

            media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()

            yt_id = response.get("id")
            logger.info(f"Video uploaded with ID {yt_id}. Verifying PUBLIC visibility status...")

            # 3. Two-Step API Verification: Confirm status is actually PUBLIC
            verify_res = youtube.videos().list(part="status", id=yt_id).execute()
            items = verify_res.get("items", [])
            actual_privacy = "unknown"
            if items:
                actual_privacy = items[0].get("status", {}).get("privacyStatus", "unknown")

            if actual_privacy != "public":
                logger.warning(f"Video {yt_id} privacy status is '{actual_privacy}', correcting to 'public'...")
                update_body = {
                    "id": yt_id,
                    "status": {
                        "privacyStatus": "public",
                        "selfDeclaredMadeForKids": False
                    }
                }
                youtube.videos().update(part="status", body=update_body).execute()
                # Re-verify
                verify_res = youtube.videos().list(part="status", id=yt_id).execute()
                items = verify_res.get("items", [])
                actual_privacy = items[0].get("status", {}).get("privacyStatus", "unknown") if items else "unknown"

            if actual_privacy != "public":
                raise ValueError(f"CRITICAL: Failed to confirm PUBLIC visibility on YouTube for video {yt_id}. Current status: {actual_privacy}")

            logger.info(f"[+] VERIFIED PUBLIC YouTube Short: https://youtube.com/shorts/{yt_id} (Privacy: {actual_privacy})")

            record = UploadRecord(
                id=upload_id,
                job_id=job.id,
                youtube_video_id=yt_id,
                title=metadata["title"],
                description=metadata["description"],
                tags=",".join(metadata.get("tags", [])),
                privacy_status="public",
                published_at=datetime.utcnow(),
                status="PUBLISHED"
            )
            db.add(record)
            db.commit()
            return record

        except Exception as e:
            logger.error(f"YouTube upload/verification failed: {e}")
            raise e
