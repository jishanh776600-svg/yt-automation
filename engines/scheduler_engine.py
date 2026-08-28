"""
Publication Scheduler & Slot Allocation Engine (Phase 18).
Calculates and assigns deterministic publication slots for YouTube Shorts.

Slot Rules:
- 4 Release Slots per UTC calendar day:
  1. 06:00 UTC (11:30 AM IST)
  2. 10:00 UTC (03:30 PM IST)
  3. 15:00 UTC (08:30 PM IST)
  4. 20:00 UTC (01:30 AM IST)
- Strictly maximum 4 publication slots per UTC calendar day.
- Never assign two Shorts to the same slot.
- Never schedule into a past slot or a slot less than min_lead_minutes in the future.
- If today's remaining slots are full or passed, rolls over to the next UTC day starting at 06:00 UTC.
"""
import logging
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, Any, List, Set, Optional, Tuple
from sqlalchemy.orm import Session

from config.constants import DAILY_SHORTS_LIMIT, PUBLISHING_SLOTS_UTC
from core.models import UploadRecord

logger = logging.getLogger(__name__)


class PublicationScheduler:
    """Calculates publication slots and ensures collision-free scheduling."""

    def __init__(self, min_lead_minutes: int = 15):
        self.min_lead_minutes = min_lead_minutes

    @staticmethod
    def get_canonical_slot_times() -> List[Tuple[int, int]]:
        """Returns list of (hour, minute) tuples for release slots."""
        return [(hour, minute) for hour, minute, _ in PUBLISHING_SLOTS_UTC]

    def get_occupied_slots(self, db: Session) -> Set[datetime]:
        """
        Retrieves all occupied UTC slot timestamps from SQLite database.
        Includes both scheduled and published uploads.
        """
        records = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "SUCCESS", "TEST_VERIFIED"])
        ).all()

        occupied = set()
        for r in records:
            if r.scheduled_publish_at:
                # Normalize to minute precision
                dt = r.scheduled_publish_at.replace(second=0, microsecond=0)
                occupied.add(dt)
            elif r.published_at:
                # If published directly without scheduled_publish_at, match nearest slot
                dt = r.published_at.replace(second=0, microsecond=0)
                # Find if it fell into one of the canonical slots today
                for hour, minute in self.get_canonical_slot_times():
                    slot_cand = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if abs((dt - slot_cand).total_seconds()) <= 3600:
                        occupied.add(slot_cand)
        return occupied

    def get_slots_for_date(self, target_date: date) -> List[datetime]:
        """Returns all 4 canonical slot datetimes for a specific UTC date."""
        return [
            datetime.combine(target_date, dtime(hour=hour, minute=minute))
            for hour, minute in self.get_canonical_slot_times()
        ]

    def calculate_next_available_slot(
        self,
        db: Session,
        reference_time: Optional[datetime] = None,
        max_days_forward: int = 14
    ) -> datetime:
        """
        Finds the next valid, unoccupied publication slot in UTC.
        Enforces DAILY_SHORTS_LIMIT = 4 ceiling per UTC calendar day.
        """
        now = reference_time or datetime.utcnow()
        now = now.replace(microsecond=0)
        earliest_allowed = now + timedelta(minutes=self.min_lead_minutes)

        occupied_slots = self.get_occupied_slots(db)

        current_date = now.date()
        for day_offset in range(max_days_forward):
            eval_date = current_date + timedelta(days=day_offset)
            day_slots = self.get_slots_for_date(eval_date)

            # Count occupied slots for this UTC date
            occupied_count_for_day = sum(1 for s in day_slots if s in occupied_slots)
            if occupied_count_for_day >= DAILY_SHORTS_LIMIT:
                logger.debug(f"Date {eval_date} is fully booked ({occupied_count_for_day}/{DAILY_SHORTS_LIMIT} slots). Rolling over.")
                continue

            for slot_dt in day_slots:
                if slot_dt <= earliest_allowed:
                    continue  # Slot is in past or too close

                if slot_dt in occupied_slots:
                    continue  # Slot is already taken

                logger.info(f"[SCHEDULER] Allocated next available slot: {slot_dt.isoformat()}Z (Ref: {now.isoformat()}Z)")
                return slot_dt

        # Fallback if somehow all max_days_forward are booked: next day 06:00 UTC
        fallback = datetime.combine(current_date + timedelta(days=max_days_forward), dtime(hour=6, minute=0))
        logger.warning(f"[SCHEDULER] Max search horizon reached. Fallback slot: {fallback.isoformat()}Z")
        return fallback

    def get_schedule_overview(self, db: Session, days_ahead: int = 4) -> List[Dict[str, Any]]:
        """
        Returns structured view of upcoming slots for UI/telemetry.
        """
        now = datetime.utcnow()
        occupied_slots = self.get_occupied_slots(db)
        
        # Load upload records indexed by scheduled_publish_at
        records = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "SUCCESS", "TEST_VERIFIED"])
        ).all()
        record_map = {}
        for r in records:
            if r.scheduled_publish_at:
                record_map[r.scheduled_publish_at.replace(second=0, microsecond=0)] = r

        overview = []
        for d in range(days_ahead):
            eval_date = now.date() + timedelta(days=d)
            for hour, minute in self.get_canonical_slot_times():
                slot_dt = datetime.combine(eval_date, dtime(hour=hour, minute=minute))
                is_occupied = slot_dt in occupied_slots
                rec = record_map.get(slot_dt)

                status_label = "OPEN"
                if is_occupied:
                    status_label = rec.status if rec else "BOOKED"
                elif slot_dt < now:
                    status_label = "PASSED"

                overview.append({
                    "slot_time": slot_dt.isoformat() + "Z",
                    "slot_label": f"{slot_dt.strftime('%b %d, %Y')} at {slot_dt.strftime('%H:%M')} UTC",
                    "status": status_label,
                    "is_occupied": is_occupied,
                    "youtube_video_id": rec.youtube_video_id if rec else None,
                    "title": rec.title if rec else None,
                    "job_id": rec.job_id if rec else None
                })

        return overview
