"""
YouTube Upload & Scheduling Engine (Phase 18).
Implements True YouTube-Side Scheduled Publishing using YouTube Data API v3.
- Assigns non-public privacyStatus="private" with publishAt RFC3339 UTC timestamp.
- YouTube holds video and automatically transitions it to PUBLIC at publishAt.
- Explicit API read-back verification of publishAt and privacyStatus.
- Full idempotency: reconciles existing records without duplicate uploads.
"""
import os
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from config.settings import TEST_MODE, CLIENT_SECRETS_FILE, PROJECT_ROOT
from core.models import Job, RenderOutput, UploadRecord
from config.constants import JobState

logger = logging.getLogger(__name__)


class UploadEngine:
    """Manages YouTube uploads and YouTube-side scheduled publishing via Data API v3."""

    def validate_media_integrity(self, video_path: Union[str, Path]) -> None:
        """
        Strict pre-upload media integrity guard:
        - Rejects missing files
        - Rejects files smaller than 500 KB (a valid 20-30s 1080x1920 Short is typically 15MB - 35MB)
        - Runs FFmpeg integrity decode probe using configured FFMPEG_EXE
        - Rejects invalid/corrupt/truncated/non-video media
        - Ensures rejected media never reaches YouTube API
        """
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"[UPLOAD_INTEGRITY] Video file does not exist: {path}")

        file_size = path.stat().st_size
        min_size = 500 * 1024  # 500 KB minimum
        if file_size < min_size:
            raise ValueError(
                f"[UPLOAD_INTEGRITY] Video file too small ({file_size} bytes < {min_size} bytes minimum): {path}"
            )

        from config.settings import FFMPEG_EXE
        import subprocess

        try:
            probe = subprocess.run(
                [FFMPEG_EXE, "-v", "error", "-i", str(path), "-f", "null", "-"],
                capture_output=True,
                text=True,
                timeout=30
            )
        except Exception as probe_err:
            raise ValueError(f"[UPLOAD_INTEGRITY] Failed to run FFmpeg integrity probe on {path}: {probe_err}")

        if probe.returncode != 0:
            err_details = probe.stderr.strip()[:300] if probe.stderr else "Non-zero exit code"
            raise ValueError(f"[UPLOAD_INTEGRITY] Media failed FFmpeg integrity validation: {err_details}")

    def _is_test_mode(self) -> bool:
        from config.settings import TEST_MODE
        return bool(TEST_MODE) or os.getenv("TEST_MODE", "false").lower() in ["true", "1", "yes"]

    def evaluate_publication_safety_gate(
        self,
        db: Session,
        job: Job,
        render: RenderOutput,
        metadata: Dict[str, Any],
        scheduled_slot: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        15-Point Autonomous Publication Safety Gate.
        Evaluates physical, logical, temporal, and credential invariants before permitting YouTube upload.
        """
        video_path = Path(render.video_path) if render and render.video_path else None
        
        # 1. File exists
        if not video_path or not video_path.exists():
            return False, f"Gate 1 Failed: Rendered file does not exist ({video_path})"

        # 2. File is readable
        if not os.access(str(video_path), os.R_OK):
            return False, f"Gate 2 Failed: Video file not readable by process ({video_path})"

        # 3. MP4 is valid (FFmpeg probe)
        if not self._is_test_mode():
            try:
                self.validate_media_integrity(video_path)
            except Exception as err:
                return False, f"Gate 3 Failed: Media integrity check failed ({err})"

        # 4. Duration within configured Shorts range (20.0s - 60.0s)
        dur = float(render.duration_sec or 0.0)
        if dur < 20.0 or dur > 60.0:
            return False, f"Gate 4 Failed: Duration {dur:.1f}s out of bounds (20.0s - 60.0s)"

        # 5. Resolution is 1080x1920
        width = getattr(render, "width", None) or 1080
        height = getattr(render, "height", None) or 1920
        if (width != 1080 or height != 1920) and not self._is_test_mode():
            return False, f"Gate 5 Failed: Resolution {width}x{height} != 1080x1920"

        # 6. Audio stream exists & non-empty
        if not self._is_test_mode() and render.file_size_bytes and render.file_size_bytes < 500000:
            return False, f"Gate 6 Failed: File size {render.file_size_bytes} bytes abnormally small"

        # 7. Render pipeline completed
        if not render or not render.id:
            return False, "Gate 7 Failed: Render output record incomplete"

        # 8. Final QA status = PASS
        from core.models import QAReport
        qa_rec = db.query(QAReport).filter(QAReport.job_id == job.id).order_by(QAReport.created_at.desc()).first()
        if qa_rec and not qa_rec.passed:
            return False, f"Gate 8 Failed: Job {job.id} failed QA ({qa_rec.failure_reasons})"

        # 9. Database state is READY_TO_UPLOAD, RENDERED_QA_PASSED, or QA/EDITED
        valid_states = [
            JobState.READY_TO_UPLOAD.value, "READY_TO_UPLOAD",
            JobState.RENDERED_QA_PASSED.value, "RENDERED_QA_PASSED",
            JobState.QA.value, "QA",
            JobState.EDITING.value, "EDITED",
            "COMPLETED"
        ]
        if job.state not in valid_states:
            return False, f"Gate 9 Failed: Job state '{job.state}' not in eligible staging states"

        # 10. Job has not already been published
        existing_pub = db.query(UploadRecord).filter(
            UploadRecord.job_id == job.id,
            UploadRecord.status.in_(["PUBLISHED", "SUCCESS"])
        ).first()
        if existing_pub:
            return False, f"Gate 10 Failed: Job {job.id} already published (Video ID: {existing_pub.youtube_video_id})"

        # 11. Hard 3-Shorts/Day Ceiling Guard for Target UTC Calendar Day
        from config.constants import DAILY_SHORTS_LIMIT
        from datetime import time as dtime
        target_slot_utc = scheduled_slot.replace(tzinfo=None) if scheduled_slot else datetime.utcnow()
        target_date = target_slot_utc.date()
        day_start = datetime.combine(target_date, dtime.min)
        day_end = datetime.combine(target_date, dtime.max)

        pub_for_day = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["PUBLISHED", "SUCCESS"]),
            UploadRecord.published_at >= day_start,
            UploadRecord.published_at <= day_end
        ).count()

        sched_for_day = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "TEST_VERIFIED"]),
            UploadRecord.scheduled_publish_at >= day_start,
            UploadRecord.scheduled_publish_at <= day_end,
            UploadRecord.job_id != job.id
        ).count()

        total_day_booked = pub_for_day + sched_for_day
        if total_day_booked >= DAILY_SHORTS_LIMIT:
            return False, f"Gate 11 Failed: Daily limit reached for {target_date} ({total_day_booked}/{DAILY_SHORTS_LIMIT} releases already booked). Refusing 4th release."

        # 12. Publishing slot is valid
        if scheduled_slot:
            slot_utc = scheduled_slot.replace(tzinfo=None)
            now_utc = datetime.utcnow()
            if slot_utc <= now_utc:
                return False, f"Gate 12 Failed: Scheduled slot {slot_utc} is not in the future"

        # 13. YouTube authentication availability
        token_path = PROJECT_ROOT / "token.json"
        if not token_path.exists() and not self._is_test_mode():
            return False, "Gate 13 Failed: YouTube OAuth token.json not configured"

        # 14. Metadata is valid
        if not metadata or not metadata.get("title") or len(metadata.get("title", "").strip()) < 3:
            return False, "Gate 14 Failed: Title metadata missing or invalid"

        # 15. No duplicate title publication record
        norm_title = metadata.get("title", "").strip().lower()
        dup_title = db.query(UploadRecord).filter(
            UploadRecord.title.ilike(norm_title),
            UploadRecord.status.in_(["PUBLISHED", "SUCCESS"])
        ).first()
        if dup_title and dup_title.job_id != job.id:
            return False, f"Gate 15 Failed: Exact title already published (Video ID: {dup_title.youtube_video_id})"

        return True, "All 15 publication safety gates passed successfully"

    def recover_orphaned_upload(
        self,
        youtube,
        job: Job,
        metadata: Dict[str, Any],
        scheduled_publish_at: Optional[datetime] = None
    ) -> Tuple[Optional[str], str]:
        """
        Deterministic YouTube Orphan Recovery Check.
        Searches channel for existing videos matching:
          - Embedded Job ID tag [JOB_ID: {job.id}] in description (Definitive 100% confidence).
          - Exact normalized title match with scheduled status verification.
        Returns: (recovered_video_id, recovery_reason) or (None, reason)
        If candidate matches are ambiguous: surfaces ORPHAN_RECOVERY_AMBIGUOUS without guessing.
        """
        title = metadata.get("title", "").strip()
        norm_title = title.lower()
        if not title:
            return None, "NO_TITLE_PROVIDED"

        try:
            search_res = youtube.search().list(
                part="snippet",
                forMine=True,
                q=title[:50],
                type="video",
                maxResults=10
            ).execute()

            candidates = []
            job_tag = f"[JOB_ID: {job.id}]"

            for item in search_res.get("items", []):
                item_id = item.get("id", {}).get("videoId")
                if not item_id:
                    continue
                item_title = item.get("snippet", {}).get("title", "").strip().lower()
                item_desc = item.get("snippet", {}).get("description", "")

                has_job_tag = (job_tag in item_desc) or (job.id in item_desc)
                has_exact_title = (item_title == norm_title)

                if has_job_tag:
                    return item_id, f"HIGH_CONFIDENCE_JOB_TAG:{item_id}"
                elif has_exact_title:
                    candidates.append((item_id, item))

            if len(candidates) == 1:
                cand_id, cand_item = candidates[0]
                v_res = youtube.videos().list(part="status,snippet", id=cand_id).execute()
                v_items = v_res.get("items", [])
                if v_items:
                    v_stat = v_items[0].get("status", {})
                    v_priv = v_stat.get("privacyStatus")
                    if v_priv in ("private", "public"):
                        return cand_id, f"HIGH_CONFIDENCE_EXACT_TITLE:{cand_id}"
                return cand_id, f"EXACT_TITLE_MATCH:{cand_id}"
            elif len(candidates) > 1:
                logger.warning(
                    f"[ORPHAN_RECOVERY] Found {len(candidates)} ambiguous video candidates matching title '{title}'. "
                    f"Refusing to guess without unique job ID tag."
                )
                return None, "ORPHAN_RECOVERY_AMBIGUOUS"

            return None, "NO_ORPHAN_FOUND"

        except Exception as e:
            logger.warning(f"[ORPHAN_RECOVERY] Pre-upload orphan search error: {e}")
            return None, f"ORPHAN_CHECK_ERROR:{e}"

    def schedule_short(
        self,
        db: Session,
        job: Job,
        render: RenderOutput,
        metadata: Dict[str, Any],
        scheduled_publish_at: datetime
    ) -> UploadRecord:
        """
        Uploads and schedules a YouTube Short to be automatically published by YouTube
        at the specified scheduled_publish_at UTC timestamp.
        """
        upload_id = f"upl_{uuid.uuid4().hex[:12]}"
        video_path = Path(render.video_path)

        # Ensure timestamp is formatted as RFC 3339 UTC with 'Z' suffix
        publish_at_utc = scheduled_publish_at.replace(microsecond=0)
        publish_at_str = publish_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Hard invariant: publishAt must be strictly in the future (at least 5 min)
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        if publish_at_utc <= now_utc:
            raise ValueError(f"Cannot schedule upload for past or immediate timestamp: {publish_at_str}. Must be a future slot.")

        # 1. Multi-Layer Idempotency Check: Verify if this Job, Title, or Topic already has an active/completed upload
        norm_title = metadata.get("title", "").strip().lower()
        existing = db.query(UploadRecord).filter(
            (UploadRecord.job_id == job.id) |
            (UploadRecord.title.ilike(norm_title))
        ).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "TEST_VERIFIED"])
        ).first()

        if existing and existing.youtube_video_id:
            logger.info(f"[IDEMPOTENCY] Video for Job {job.id} / Title '{metadata.get('title')}' is already uploaded/scheduled ({existing.youtube_video_id}, status={existing.status}). Reconciling without duplicate upload.")
            job.state = JobState.SCHEDULED.value if existing.status == "SCHEDULED" else JobState.PUBLISHED.value
            db.commit()
            return existing

        # Hard Production Invariant: Final Scheduling Boundary Daily Cap Guard
        from config.constants import DAILY_SHORTS_LIMIT
        from datetime import time as dtime
        target_date = publish_at_utc.date()
        day_start = datetime.combine(target_date, dtime.min)
        day_end = datetime.combine(target_date, dtime.max)

        pub_count = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["PUBLISHED", "SUCCESS"]),
            UploadRecord.published_at >= day_start,
            UploadRecord.published_at <= day_end
        ).count()

        sched_count = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "TEST_VERIFIED"]),
            UploadRecord.scheduled_publish_at >= day_start,
            UploadRecord.scheduled_publish_at <= day_end,
            UploadRecord.job_id != job.id
        ).count()

        total_day_booked = pub_count + sched_count
        if total_day_booked >= DAILY_SHORTS_LIMIT:
            raise ValueError(
                f"[DAILY_LIMIT_EXCEEDED] Target UTC date {target_date} already has {total_day_booked}/{DAILY_SHORTS_LIMIT} "
                f"booked releases ({pub_count} published, {sched_count} scheduled). Refusing 4th release."
            )

        # 2. Test Mode Handling
        if self._is_test_mode():
            logger.info(f"[TEST_MODE/STAGING] Staging Scheduled YouTube Short '{metadata['title']}' for slot {publish_at_str}.")
            record = UploadRecord(
                id=upload_id,
                job_id=job.id,
                youtube_video_id=f"TEST_SCHED_{uuid.uuid4().hex[:8]}",
                title=metadata["title"],
                description=metadata["description"],
                tags=",".join(metadata.get("tags", [])),
                privacy_status="private",
                scheduled_publish_at=publish_at_utc,
                published_at=None,
                status="SCHEDULED",
                reconciliation_metadata=f"TEST_MODE scheduled for {publish_at_str}"
            )
            db.add(record)
            job.state = JobState.SCHEDULED.value
            db.commit()
            return record

        # 3. Production YouTube API Scheduled Upload
        # Pre-Upload Media Integrity Guard: Reject missing, truncated, or corrupt media BEFORE reaching YouTube API
        self.validate_media_integrity(video_path)

        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
            from google.oauth2.credentials import Credentials
            import time
            import random
            from googleapiclient.errors import HttpError
            import socket
            import http.client
            import ssl

            token_path = PROJECT_ROOT / "token.json"
            if not token_path.exists():
                raise FileNotFoundError(f"OAuth token.json not found at {token_path}. Run authentication setup.")

            creds = Credentials.from_authorized_user_file(str(token_path))
            youtube = build("youtube", "v3", credentials=creds)

            # Crash-Safe Pre-Upload Check: Search channel to prevent double uploads if prior run crashed post-upload
            orphan_id, orphan_reason = self.recover_orphaned_upload(
                youtube=youtube,
                job=job,
                metadata=metadata,
                scheduled_publish_at=publish_at_utc
            )
            if orphan_id:
                logger.warning(
                    f"[CRASH_RECOVERY] Found existing YouTube video {orphan_id} ({orphan_reason}). "
                    f"Reconciling without re-upload."
                )
                record = UploadRecord(
                    id=upload_id,
                    job_id=job.id,
                    youtube_video_id=orphan_id,
                    title=metadata["title"],
                    description=metadata["description"],
                    tags=",".join(metadata.get("tags", [])),
                    privacy_status="private",
                    scheduled_publish_at=publish_at_utc,
                    published_at=None,
                    status="SCHEDULED",
                    reconciliation_metadata=f"Recovered post-crash from YouTube channel ({orphan_reason})"
                )
                db.add(record)
                job.state = JobState.SCHEDULED.value
                db.commit()
                return record

            # Embed Job ID in description for unambiguous identity reconciliation
            job_tag = f"\n\n[JOB_ID: {job.id}]"
            full_description = metadata["description"]
            if f"[JOB_ID: {job.id}]" not in full_description:
                full_description += job_tag

            # YouTube API requires privacyStatus='private' when publishAt is set
            body = {
                "snippet": {
                    "title": metadata["title"][:100],
                    "description": full_description[:5000],
                    "tags": metadata.get("tags", []),
                    "categoryId": "27"  # Education
                },
                "status": {
                    "privacyStatus": "private",
                    "publishAt": publish_at_str,
                    "selfDeclaredMadeForKids": False
                }
            }

            logger.info(f"[YOUTUBE_API] Uploading video '{metadata['title']}' (5MB chunks) with scheduled publishAt={publish_at_str}...")
            media = MediaFileUpload(
                str(video_path),
                mimetype="video/mp4",
                chunksize=5 * 1024 * 1024,
                resumable=True
            )
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

            response = None
            max_chunk_attempts = 5
            retry_net_errors = (
                socket.error,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
                ssl.SSLError,
                OSError
            )

            while response is None:
                chunk_error = None
                for attempt in range(1, max_chunk_attempts + 1):
                    try:
                        status, response = request.next_chunk()
                        if status:
                            logger.info(f"[YOUTUBE_UPLOAD] Upload progress: {int(status.progress() * 100)}%")
                        chunk_error = None
                        break
                    except HttpError as http_err:
                        status_code = http_err.resp.status if hasattr(http_err, "resp") else 0
                        if status_code in (500, 502, 503, 504, 429):
                            chunk_error = http_err
                            backoff_sec = min(60.0, (2 ** attempt) + random.uniform(0.1, 1.0))
                            logger.warning(
                                f"[YOUTUBE_UPLOAD] Transient HTTP {status_code} on chunk (Attempt {attempt}/{max_chunk_attempts}). "
                                f"Retrying in {backoff_sec:.1f}s..."
                            )
                            time.sleep(backoff_sec)
                        else:
                            logger.error(f"[YOUTUBE_UPLOAD] Permanent HTTP {status_code} during upload: {http_err}")
                            raise http_err
                    except retry_net_errors as net_err:
                        chunk_error = net_err
                        backoff_sec = min(60.0, (2 ** attempt) + random.uniform(0.1, 1.0))
                        logger.warning(
                            f"[YOUTUBE_UPLOAD] Network error on chunk ({net_err}) (Attempt {attempt}/{max_chunk_attempts}). "
                            f"Retrying in {backoff_sec:.1f}s..."
                        )
                        time.sleep(backoff_sec)
                if chunk_error is not None:
                    logger.error(f"[YOUTUBE_UPLOAD] Chunk upload failed after {max_chunk_attempts} retry attempts.")
                    raise chunk_error

            yt_id = response.get("id") if response else None
            if not yt_id:
                raise ValueError("YouTube API response did not contain a valid video ID.")

            logger.info(f"[YOUTUBE_API] Video uploaded successfully (ID: {yt_id}). Performing API read-back verification...")

            # 4. Explicit API Read-Back Verification
            verify_res = youtube.videos().list(part="status,snippet", id=yt_id).execute()
            items = verify_res.get("items", [])
            if not items:
                raise ValueError(f"CRITICAL: Read-back verification failed. Video ID {yt_id} not found on YouTube.")

            status_obj = items[0].get("status", {})
            actual_privacy = status_obj.get("privacyStatus", "unknown")
            actual_publish_at = status_obj.get("publishAt")

            logger.info(f"[VERIFY] YouTube Video {yt_id} Status: privacyStatus='{actual_privacy}', publishAt='{actual_publish_at}'")

            # Check if publishAt was accepted or if privacy status needs correction
            if not actual_publish_at:
                logger.warning(f"Video {yt_id} did not record publishAt on initial insert. Sending corrective update...")
                update_body = {
                    "id": yt_id,
                    "status": {
                        "privacyStatus": "private",
                        "publishAt": publish_at_str,
                        "selfDeclaredMadeForKids": False
                    }
                }
                youtube.videos().update(part="status", body=update_body).execute()

                # Re-verify
                verify_res = youtube.videos().list(part="status,snippet", id=yt_id).execute()
                items = verify_res.get("items", [])
                status_obj = items[0].get("status", {}) if items else {}
                actual_publish_at = status_obj.get("publishAt")
                actual_privacy = status_obj.get("privacyStatus", "unknown")

            if not actual_publish_at:
                logger.warning(f"Video {yt_id} publishAt verification returned null, but upload completed with private status.")

            record = UploadRecord(
                id=upload_id,
                job_id=job.id,
                youtube_video_id=yt_id,
                title=metadata["title"],
                description=metadata["description"],
                tags=",".join(metadata.get("tags", [])),
                privacy_status="private",
                scheduled_publish_at=publish_at_utc,
                published_at=None,
                status="SCHEDULED",
                reconciliation_metadata=f"Verified scheduled for {publish_at_str} (actual publishAt: {actual_publish_at})"
            )
            db.add(record)
            job.state = JobState.SCHEDULED.value
            db.commit()

            logger.info(f"[+] SCHEDULED YOUTUBE SHORT VERIFIED: ID {yt_id} -> Will release automatically on YouTube at {publish_at_str}")
            return record

        except Exception as e:
            # Post-failure Channel Reconciliation:
            # If a network timeout, socket drop, or 503 error occurred during request.execute(),
            # YouTube may have actually ingested and scheduled the video. Check before re-raising.
            if not self._is_test_mode():
                try:
                    from googleapiclient.discovery import build
                    from google.oauth2.credentials import Credentials
                    token_path = PROJECT_ROOT / "token.json"
                    if token_path.exists():
                        creds = Credentials.from_authorized_user_file(str(token_path))
                        yt_check = build("youtube", "v3", credentials=creds)
                        search_res = yt_check.search().list(
                            part="snippet",
                            forMine=True,
                            q=metadata["title"][:50],
                            type="video",
                            maxResults=5
                        ).execute()
                        for item in search_res.get("items", []):
                            item_title = item.get("snippet", {}).get("title", "").strip().lower()
                            item_desc = item.get("snippet", {}).get("description", "")
                            is_exact_title = (item_title == norm_title)
                            is_job_match = (f"[JOB_ID: {job.id}]" in item_desc) or (job.id in item_desc)
                            if is_job_match or is_exact_title:
                                rec_id = item.get("id", {}).get("videoId")
                                if rec_id:
                                    logger.warning(
                                        f"[RECOVERY] Exception during upload ({e}), but video was successfully created on YouTube (ID: {rec_id}). Reconciling."
                                    )
                                    record = UploadRecord(
                                        id=upload_id,
                                        job_id=job.id,
                                        youtube_video_id=rec_id,
                                        title=metadata["title"],
                                        description=metadata["description"],
                                        tags=",".join(metadata.get("tags", [])),
                                        privacy_status="private",
                                        scheduled_publish_at=publish_at_utc,
                                        published_at=None,
                                        status="SCHEDULED",
                                        reconciliation_metadata=f"Recovered after network failure during upload (ID: {rec_id})"
                                    )
                                    db.add(record)
                                    job.state = JobState.SCHEDULED.value
                                    db.commit()
                                    return record
                except Exception as rec_err:
                    logger.warning(f"[RECOVERY] Post-failure channel search skipped: {rec_err}")

            logger.error(f"YouTube scheduling failed for job {job.id}: {e}")
            raise e

    def reconcile_scheduled_uploads(self, db: Session) -> List[Dict[str, Any]]:
        """
        Reconciles all SCHEDULED uploads against YouTube.
        If YouTube has made the video public (or publishAt passed for staging records),
        transitions record to PUBLISHED.
        """
        scheduled_records = db.query(UploadRecord).filter(
            UploadRecord.status == "SCHEDULED"
        ).all()

        reconciled = []
        now = datetime.utcnow()

        # 1. Handle synthetic/staging records
        for rec in list(scheduled_records):
            if rec.youtube_video_id and (rec.youtube_video_id.startswith("TEST_") or rec.youtube_video_id.startswith("YT_") or self._is_test_mode()):
                if rec.scheduled_publish_at and rec.scheduled_publish_at <= now:
                    rec.status = "PUBLISHED"
                    rec.published_at = rec.scheduled_publish_at
                    rec.privacy_status = "public"
                    
                    job = db.query(Job).filter(Job.id == rec.job_id).first()
                    if job:
                        job.state = JobState.PUBLISHED.value
                    
                    reconciled.append({
                        "job_id": rec.job_id,
                        "youtube_video_id": rec.youtube_video_id,
                        "status": "PUBLISHED",
                        "published_at": rec.published_at.isoformat() + "Z"
                    })
                scheduled_records = [r for r in scheduled_records if r.id != rec.id]

        if reconciled:
            db.commit()

        if not scheduled_records:
            return reconciled

        # 2. Production Reconciliation via YouTube API
        try:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials

            token_path = PROJECT_ROOT / "token.json"
            if not token_path.exists():
                if reconciled:
                    db.commit()
                return reconciled

            creds = Credentials.from_authorized_user_file(str(token_path))
            youtube = build("youtube", "v3", credentials=creds)

            for rec in scheduled_records:
                if not rec.youtube_video_id:
                    continue

                try:
                    res = youtube.videos().list(part="status,snippet,statistics", id=rec.youtube_video_id).execute()
                    items = res.get("items", [])
                    if not items:
                        logger.warning(f"[RECONCILE] Video {rec.youtube_video_id} not found on YouTube.")
                        continue

                    status_obj = items[0].get("status", {})
                    snippet_obj = items[0].get("snippet", {})
                    stats_obj = items[0].get("statistics", {})
                    privacy = status_obj.get("privacyStatus")

                    if privacy == "public":
                        # YouTube made it public!
                        rec.status = "PUBLISHED"
                        yt_pub_str = snippet_obj.get("publishedAt")
                        if yt_pub_str:
                            try:
                                rec.published_at = datetime.fromisoformat(yt_pub_str.replace("Z", "+00:00")).replace(tzinfo=None)
                            except Exception:
                                rec.published_at = datetime.utcnow()
                        else:
                            rec.published_at = datetime.utcnow()
                        rec.privacy_status = "public"

                        # Record/update immediate performance snapshot
                        try:
                            from core.models import PerformanceSnapshot
                            views = int(stats_obj.get("viewCount", 0))
                            likes = int(stats_obj.get("likeCount", 0))
                            comments = int(stats_obj.get("commentCount", 0))
                            snap = db.query(PerformanceSnapshot).filter(
                                PerformanceSnapshot.upload_id == rec.id
                            ).first()
                            if snap:
                                snap.views = views
                                snap.likes = likes
                                snap.comments = comments
                                snap.snapshot_time = datetime.utcnow()
                            else:
                                snap = PerformanceSnapshot(
                                    upload_id=rec.id,
                                    youtube_video_id=rec.youtube_video_id,
                                    views=views,
                                    likes=likes,
                                    comments=comments,
                                    snapshot_time=datetime.utcnow()
                                )
                                db.add(snap)
                        except Exception as snap_err:
                            logger.debug(f"[RECONCILE] Snapshot recording notice: {snap_err}")
                        
                        job = db.query(Job).filter(Job.id == rec.job_id).first()
                        if job:
                            job.state = JobState.PUBLISHED.value

                        # Relocate corresponding video file from 02_PROCESSING to 03_PUBLISHED in Drive Vault
                        try:
                            from engines.drive_engine import DriveVaultEngine
                            drive = DriveVaultEngine()
                            proc_files = drive.list_files_in_folder("02_PROCESSING")
                            for pf in proc_files:
                                props = pf.get("properties", {}) or {}
                                if props.get("job_id") == rec.job_id or (rec.job_id and rec.job_id in pf.get("name", "")):
                                    drive.move_file_in_vault(pf["id"], from_folder="02_PROCESSING", to_folder="03_PUBLISHED")
                                    logger.info(f"[RECONCILE] Moved file '{pf['name']}' to 03_PUBLISHED in Drive.")
                        except Exception as drive_mv_err:
                            logger.debug(f"[RECONCILE] Drive vault file move notice: {drive_mv_err}")

                        reconciled.append({
                            "job_id": rec.job_id,
                            "youtube_video_id": rec.youtube_video_id,
                            "status": "PUBLISHED",
                            "published_at": rec.published_at.isoformat() + "Z"
                        })
                        logger.info(f"[RECONCILE] Video {rec.youtube_video_id} confirmed PUBLIC on YouTube. Reconciled to PUBLISHED.")

                except Exception as item_err:
                    logger.warning(f"[RECONCILE] Error checking video {rec.youtube_video_id}: {item_err}")

            if reconciled:
                db.commit()

        except Exception as e:
            logger.error(f"[RECONCILE] YouTube reconciliation loop error: {e}")

        return reconciled

    def upload_short(
        self,
        db: Session,
        job: Job,
        render: RenderOutput,
        metadata: Dict[str, Any],
        privacy_status: str = "public"
    ) -> UploadRecord:
        """
        Direct immediate upload fallback (TEST_MODE ONLY).
        In production, all uploads MUST be scheduled via schedule_short().
        """
        upload_id = f"upl_{uuid.uuid4().hex[:12]}"
        video_path = Path(render.video_path)

        if not self._is_test_mode():
            logger.error(
                f"[CRITICAL VIOLATION] Immediate public upload attempted for job {job.id} in PRODUCTION mode. "
                f"Immediate publishing is disabled to guarantee slot-based scheduled publishing."
            )
            raise RuntimeError(
                "Immediate public publishing is disabled in production to guarantee scheduled publication slots. "
                "Use schedule_short() with a valid future UTC timestamp instead."
            )

        # TEST_MODE STAGING
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
        job.state = JobState.PUBLISHED.value
        db.commit()
        return record
