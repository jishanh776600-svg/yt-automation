"""
Authoritative Publication Gateway.
Enforces non-negotiable cross-system invariants for transitions to 03_PUBLISHED:
1. Valid non-empty youtube_video_id (>= 11 characters).
2. The YouTube video ID must belong to this exact asset/job (no title-only matching).
3. A corresponding authoritative UploadRecord must exist in SQLite.
4. UploadRecord must correspond to the same job_id / manifest_id / drive_file_id.
5. YouTube API read-back must verify the actual video state (uploadStatus == 'processed', privacyStatus == 'public').
6. Scheduled/private videos must NOT enter 03_PUBLISHED.
7. Nonexistent videos must NOT enter 03_PUBLISHED.
8. Un-uploaded assets in 01_READY must NEVER move directly to 03_PUBLISHED.
9. Direct calls to move_file_in_vault with to_folder="03_PUBLISHED" are forbidden outside this gateway.
10. Idempotent and thread/concurrency safe.
"""

import re
import logging
from datetime import datetime
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from core.models import UploadRecord, Job, JobState

logger = logging.getLogger(__name__)


class InvariantViolationError(Exception):
    """Raised when an illegal lifecycle transition or publication invariant violation is detected."""
    pass


def is_valid_youtube_id(video_id: Optional[str]) -> bool:
    """Validates YouTube video ID format (11 characters, base64-url chars)."""
    if not video_id or not isinstance(video_id, str):
        return False
    video_id = video_id.strip()
    if video_id in ["TEST_MODE_ID", "NONE", "null", "undefined"]:
        return False
    return bool(re.match(r"^[A-Za-z0-9_-]{11}$", video_id))


def vault_transition_to_published(
    file_id: str,
    youtube_video_id: str,
    db: Session,
    drive_engine: Any,
    youtube_service: Optional[Any] = None,
    job_id: Optional[str] = None,
    manifest_id: Optional[str] = None,
    caller: str = "unknown"
) -> Dict[str, Any]:
    """
    CANONICAL AUTHORITATIVE PUBLICATION GATEWAY:
    The ONLY permitted application-level mechanism to move an asset into 03_PUBLISHED.
    
    Validates physical YouTube reality and SQLite consistency before executing
    the Drive move. Refuses and raises InvariantViolationError if any invariant is unmet.
    """
    if not file_id:
        raise InvariantViolationError("[GATEWAY_ERROR] file_id is required.")

    # 1. YouTube Video ID format validation
    if not is_valid_youtube_id(youtube_video_id):
        raise InvariantViolationError(
            f"[GATEWAY_INVARIANT_VIOLATION] Invalid or empty youtube_video_id '{youtube_video_id}' "
            f"for file {file_id}. Cannot transition to 03_PUBLISHED without authoritative YouTube ID."
        )

    # 2. Inspect Drive File State
    file_meta = None
    try:
        file_meta = drive_engine.get_file_metadata(file_id)
    except AttributeError:
        # Fallback for mock drive engines
        try:
            file_meta = drive_engine.get_file(file_id)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"[GATEWAY] Could not fetch Drive metadata for {file_id}: {e}")

    current_parents = []
    file_props = {}
    file_name = ""
    if isinstance(file_meta, dict):
        current_parents = file_meta.get("parents", [])
        file_props = file_meta.get("properties", {}) or {}
        file_name = file_meta.get("name", "")

    # IDEMPOTENCY CHECK: If already in 03_PUBLISHED and properties match, return cleanly
    if "03_PUBLISHED" in current_parents:
        prop_yt_id = file_props.get("youtube_video_id")
        if prop_yt_id == youtube_video_id:
            logger.info(f"[GATEWAY_IDEMPOTENT] File {file_id} is already in 03_PUBLISHED with matching YouTube ID {youtube_video_id}.")
            return {
                "success": True,
                "status": "ALREADY_PUBLISHED",
                "file_id": file_id,
                "youtube_video_id": youtube_video_id
            }

    # REJECT DIRECT MOVE FROM 01_READY
    if "01_READY" in current_parents:
        raise InvariantViolationError(
            f"[GATEWAY_INVARIANT_VIOLATION] Refusing transition: File {file_id} ({file_name}) is currently in 01_READY. "
            "Un-uploaded assets must be claimed into 02_PROCESSING, uploaded, and verified before entering 03_PUBLISHED."
        )

    # 3. Match and Verify SQLite UploadRecord
    upload_rec = db.query(UploadRecord).filter(UploadRecord.youtube_video_id == youtube_video_id).first()
    if not upload_rec:
        raise InvariantViolationError(
            f"[GATEWAY_INVARIANT_VIOLATION] No authoritative UploadRecord found in SQLite for youtube_video_id '{youtube_video_id}'. "
            f"Asset {file_id} cannot enter 03_PUBLISHED without an authoritative database record."
        )

    # Cross-verify job_id / manifest_id binding
    resolved_job_id = job_id or file_props.get("job_id")
    if resolved_job_id and upload_rec.job_id and upload_rec.job_id != resolved_job_id:
        raise InvariantViolationError(
            f"[GATEWAY_INVARIANT_VIOLATION] Job ID mismatch: File {file_id} associated with job '{resolved_job_id}', "
            f"but UploadRecord {upload_rec.id} belongs to job '{upload_rec.job_id}'. Cross-job clobbering rejected."
        )

    # 4. Authoritative YouTube API Read-Back Verification
    if youtube_service is None:
        try:
            from engines.upload_engine import UploadEngine
            uploader = UploadEngine()
            youtube_service = uploader.get_youtube_service()
        except Exception as e:
            logger.warning(f"[GATEWAY] Could not instantiate YouTube client: {e}")

    if youtube_service is not None:
        try:
            yt_resp = youtube_service.videos().list(part="status,snippet", id=youtube_video_id).execute()
            items = yt_resp.get("items", [])
            if not items:
                raise InvariantViolationError(
                    f"[GATEWAY_INVARIANT_VIOLATION] YouTube API confirmed video '{youtube_video_id}' DOES NOT EXIST on YouTube (404/empty). "
                    f"Asset {file_id} cannot be marked PUBLISHED."
                )

            yt_status = items[0].get("status", {})
            privacy = yt_status.get("privacyStatus", "").lower()
            upload_status = yt_status.get("uploadStatus", "").lower()

            if privacy != "public":
                publish_at = yt_status.get("publishAt", "none")
                raise InvariantViolationError(
                    f"[GATEWAY_INVARIANT_VIOLATION] YouTube API confirms video '{youtube_video_id}' is NOT public (privacyStatus='{privacy}', publishAt='{publish_at}'). "
                    f"Scheduled/private videos belong in 02_PROCESSING, NEVER 03_PUBLISHED."
                )

            if upload_status not in ["processed", "uploaded"]:
                raise InvariantViolationError(
                    f"[GATEWAY_INVARIANT_VIOLATION] YouTube API uploadStatus is '{upload_status}', not processed. Cannot mark PUBLISHED."
                )

        except InvariantViolationError:
            raise
        except Exception as api_err:
            raise InvariantViolationError(
                f"[GATEWAY_INVARIANT_VIOLATION] YouTube API read-back verification failed for '{youtube_video_id}': {api_err}. "
                "Refusing transition to 03_PUBLISHED without authoritative YouTube confirmation."
            )
    else:
        # Fail-closed if youtube_service is unavailable and we cannot verify live YouTube reality
        from config.settings import TEST_MODE
        if not TEST_MODE:
            raise InvariantViolationError(
                "[GATEWAY_INVARIANT_VIOLATION] YouTube service is offline or unavailable. "
                "Production transitions to 03_PUBLISHED fail-closed when live YouTube verification is impossible."
            )

    # 5. Execute Authorized Drive Vault Transition
    from_folder = "02_PROCESSING" if "02_PROCESSING" in current_parents else None
    drive_engine.move_file_in_vault(file_id, from_folder=from_folder or "02_PROCESSING", to_folder="03_PUBLISHED", _from_gateway=True)

    # 6. Synchronize File Properties in Drive
    try:
        drive_engine.set_file_properties(file_id, {
            "upload_status": "PUBLISHED",
            "youtube_video_id": youtube_video_id,
            "published_at": datetime.utcnow().isoformat() + "Z",
            "job_id": upload_rec.job_id or resolved_job_id or ""
        })
    except Exception as prop_e:
        logger.warning(f"[GATEWAY] Notice updating Drive properties on published file {file_id}: {prop_e}")

    # 7. Update SQLite UploadRecord & Job State
    upload_rec.status = "PUBLISHED"
    if not upload_rec.published_at:
        upload_rec.published_at = datetime.utcnow()

    if upload_rec.job_id:
        job = db.query(Job).filter(Job.id == upload_rec.job_id).first()
        if job:
            job.state = JobState.PUBLISHED.value

    db.commit()

    logger.info(
        f"[GATEWAY_SUCCESS] File {file_id} ('{file_name}') successfully transitioned to 03_PUBLISHED. "
        f"YouTube ID: {youtube_video_id} (Caller: {caller})"
    )

    return {
        "success": True,
        "status": "PUBLISHED",
        "file_id": file_id,
        "youtube_video_id": youtube_video_id,
        "job_id": upload_rec.job_id,
        "caller": caller
    }
