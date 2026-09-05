"""
Publication Scheduler & Slot Allocation Engine (Phase 18).
Calculates and assigns deterministic publication slots for YouTube Shorts.

Slot Rules:
- 3 Release Slots per UTC calendar day:
  1. 06:00 UTC (11:30 AM IST)
  2. 11:00 UTC (04:30 PM IST)
  3. 15:00 UTC (08:30 PM IST)
- Strictly maximum 3 publication slots per UTC calendar day.
- Never assign two Shorts to the same slot.
- Never schedule into a past slot or a slot less than min_lead_minutes in the future.
- If today's remaining slots are full or passed, rolls over to the next UTC day starting at 06:00 UTC.
"""
import os
import logging
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, Any, List, Set, Optional, Tuple
from sqlalchemy.orm import Session

from config.constants import DAILY_SHORTS_LIMIT, PUBLISHING_SLOTS_UTC
from config.settings import TEST_MODE
from core.models import UploadRecord

logger = logging.getLogger(__name__)


def _parse_yt_iso(ts: str) -> datetime:
    """
    Parses a YouTube API ISO 8601 timestamp to a **naive UTC** datetime.

    Handles 'Z' suffix, '+00:00', and any explicit UTC-offset.
    Returns a naive datetime in UTC (tzinfo stripped), matching the behaviour
    of the previously used ``dateutil.parser.isoparse(ts).replace(tzinfo=None)``.

    Raises:
        ValueError: if ``ts`` is not a valid ISO 8601 string.
    """
    from datetime import timezone
    normalized = ts.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class PublicationScheduler:
    """Calculates publication slots and ensures collision-free scheduling."""

    def __init__(self, min_lead_minutes: int = 15):
        self.min_lead_minutes = min_lead_minutes

    @staticmethod
    def get_canonical_slot_times() -> List[Tuple[int, int]]:
        """Returns list of (hour, minute) tuples for release slots."""
        return [(hour, minute) for hour, minute, _ in PUBLISHING_SLOTS_UTC]

    def get_authoritative_schedule_state(
        self,
        db: Session
    ) -> Tuple[Set[datetime], Dict[date, int], Dict[datetime, List[Dict[str, Any]]]]:
        """
        Retrieves authoritative occupied slots, daily release counts, and slot details
        directly from live YouTube channel inventory and reconciled SQLite records.
        Ensures both published and scheduled Shorts are counted toward the exact UTC calendar day limit.
        """
        occupied = set()
        day_counts = {}
        slot_details = {}

        is_test = TEST_MODE or os.environ.get("TEST_MODE", "").lower() in ("true", "1", "yes")
        if not is_test:
            try:
                from dashboard.data_provider import SystemDataProvider
                dp = SystemDataProvider()
                inventory = dp.fetch_authoritative_youtube_inventory(db=db)
                public_shorts = inventory.get("public_shorts", [])
                scheduled_shorts = inventory.get("scheduled_shorts", [])

                for p in public_shorts:
                    pub_iso = p.get("published_at")
                    if pub_iso:
                        p_dt = _parse_yt_iso(pub_iso)
                        cal_date = p_dt.date()
                        day_counts[cal_date] = day_counts.get(cal_date, 0) + 1
                        # Associate to nearest canonical slot
                        for hour, minute in self.get_canonical_slot_times():
                            slot_cand = p_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                            if abs((p_dt - slot_cand).total_seconds()) <= 3600:
                                occupied.add(slot_cand)
                                slot_details.setdefault(slot_cand, []).append({
                                    "id": p["id"],
                                    "title": p["title"],
                                    "type": "PUBLISHED",
                                    "time": p_dt.isoformat() + "Z"
                                })

                for s in scheduled_shorts:
                    sch_iso = s.get("publish_at")
                    if sch_iso:
                        s_dt = _parse_yt_iso(sch_iso)
                        cal_date = s_dt.date()
                        day_counts[cal_date] = day_counts.get(cal_date, 0) + 1
                        slot_dt = s_dt.replace(second=0, microsecond=0)
                        occupied.add(slot_dt)
                        slot_details.setdefault(slot_dt, []).append({
                            "id": s["id"],
                            "title": s["title"],
                            "type": "SCHEDULED",
                            "time": sch_iso
                        })

            except Exception as e:
                logger.warning(f"[SCHEDULER] Authoritative YouTube fetch notice: {e}")

        # Reconcile with any SQLite records not caught above
        db_records = db.query(UploadRecord).filter(
            UploadRecord.status.in_(["SCHEDULED", "PUBLISHED", "SUCCESS", "TEST_VERIFIED"])
        ).all()

        for r in db_records:
            if r.scheduled_publish_at:
                dt = r.scheduled_publish_at.replace(second=0, microsecond=0)
                if dt not in occupied:
                    occupied.add(dt)
                    cal_date = dt.date()
                    day_counts[cal_date] = day_counts.get(cal_date, 0) + 1
                    slot_details.setdefault(dt, []).append({
                        "id": r.youtube_video_id or r.id,
                        "title": r.title,
                        "type": "SCHEDULED_DB",
                        "time": dt.isoformat() + "Z"
                    })
            elif r.published_at:
                dt = r.published_at.replace(second=0, microsecond=0)
                cal_date = dt.date()
                for hour, minute in self.get_canonical_slot_times():
                    slot_cand = dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if abs((dt - slot_cand).total_seconds()) <= 3600:
                        if slot_cand not in occupied:
                            occupied.add(slot_cand)
                            day_counts[cal_date] = day_counts.get(cal_date, 0) + 1

        return occupied, day_counts, slot_details

    def get_occupied_slots(self, db: Session) -> Set[datetime]:
        """
        Retrieves all occupied UTC slot timestamps.
        """
        occupied, _, _ = self.get_authoritative_schedule_state(db)
        return occupied

    def get_slots_for_date(self, target_date: date) -> List[datetime]:
        """Returns all 3 canonical slot datetimes for a specific UTC date."""
        return [
            datetime.combine(target_date, dtime(hour=hour, minute=minute))
            for hour, minute in self.get_canonical_slot_times()
        ]

    def get_vacant_slots(
        self,
        db: Session,
        days_horizon: int = 2,
        reference_time: Optional[datetime] = None
    ) -> List[datetime]:
        """Convenience alias for get_vacant_slots_in_horizon."""
        return self.get_vacant_slots_in_horizon(db=db, reference_time=reference_time)

    def get_vacant_slots_in_horizon(
        self,
        db: Session,
        reference_time: Optional[datetime] = None
    ) -> List[datetime]:
        """
        Inspects all publication slots across CURRENT DAY + NEXT DAY (max 2 calendar days = up to 6 slots).
        Returns a chronologically ordered list of genuinely vacant slots that can be scheduled immediately,
        strictly respecting the DAILY_SHORTS_LIMIT = 3 ceiling per calendar day.
        Does NOT schedule beyond the next day's 15:00 UTC slot.
        """
        now = reference_time or datetime.utcnow()
        now = now.replace(microsecond=0)
        earliest_allowed = now + timedelta(minutes=self.min_lead_minutes)

        occupied_slots, day_counts, slot_details = self.get_authoritative_schedule_state(db)
        current_date = now.date()
        vacant_slots = []

        # Strictly 2 calendar days: Day 0 (Today) and Day 1 (Tomorrow)
        for day_offset in (0, 1):
            eval_date = current_date + timedelta(days=day_offset)
            day_slots = self.get_slots_for_date(eval_date)

            # Count all published & scheduled releases for this specific UTC calendar day
            occupied_count_for_day = day_counts.get(eval_date, 0)
            available_capacity_for_day = max(0, DAILY_SHORTS_LIMIT - occupied_count_for_day)

            if available_capacity_for_day <= 0:
                logger.debug(f"[SCHEDULER] Date {eval_date} has reached/exceeded daily limit ({occupied_count_for_day}/{DAILY_SHORTS_LIMIT}). Zero vacancies available.")
                continue

            day_vacancies = []
            for slot_dt in day_slots:
                if slot_dt <= earliest_allowed:
                    continue  # In past or too close (< min_lead_minutes)
                if slot_dt in occupied_slots:
                    continue  # Already occupied or double-booked

                day_vacancies.append(slot_dt)

            # Take up to the daily limit capacity for this calendar day
            allowed_for_day = day_vacancies[:available_capacity_for_day]
            vacant_slots.extend(allowed_for_day)

        # Sort chronologically (Today slots first, then Tomorrow slots)
        vacant_slots.sort()
        return vacant_slots

    def calculate_next_available_slot(
        self,
        db: Session,
        reference_time: Optional[datetime] = None,
        max_days_forward: int = 14
    ) -> datetime:
        """
        Finds the next valid, unoccupied publication slot in UTC.
        Enforces DAILY_SHORTS_LIMIT = 3 ceiling per UTC calendar day.
        """
        now = reference_time or datetime.utcnow()
        now = now.replace(microsecond=0)
        earliest_allowed = now + timedelta(minutes=self.min_lead_minutes)

        occupied_slots, day_counts, _ = self.get_authoritative_schedule_state(db)

        current_date = now.date()
        for day_offset in range(max_days_forward):
            eval_date = current_date + timedelta(days=day_offset)
            day_slots = self.get_slots_for_date(eval_date)

            # Count occupied slots for this UTC date
            occupied_count_for_day = day_counts.get(eval_date, 0)
            if occupied_count_for_day >= DAILY_SHORTS_LIMIT:
                logger.debug(f"[SCHEDULER] Date {eval_date} is fully booked ({occupied_count_for_day}/{DAILY_SHORTS_LIMIT} slots). Rolling over.")
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
