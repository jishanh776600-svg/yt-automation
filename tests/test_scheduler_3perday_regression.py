"""
Comprehensive Regression Test Suite for 3/Day YouTube Shorts Scheduling (Phase 18).

Invariants Verified:
1.  0 scheduled -> exactly 3 vacancies for that date (06:00, 11:00, 15:00 UTC).
2.  1 scheduled -> exactly 2 vacancies for that date.
3.  2 scheduled -> exactly 1 vacancy for that date.
4.  3 scheduled -> exactly 0 vacancies for that date.
5.  Occupied slots are preserved and never returned as vacant.
6.  Middle slot filled (11:00) -> vacancies are first (06:00) and third (15:00).
7.  First slot filled (06:00) -> vacancies are middle (11:00) and third (15:00).
8.  Last slot filled (15:00) -> vacancies are first (06:00) and middle (11:00).
9.  Idempotency: Running get_vacant_slots_in_horizon twice returns identical slots.
10. Rolling 48-hour forward horizon: slots > reference_time + 48h are strictly excluded.
11. Pure UTC calendar boundaries: 00:00:00 to 23:59:59 UTC per day.
12. Minimum lead time: slots <= reference_time + 15 min are skipped.
13. Hard daily ceiling of 3: available_capacity_for_day = max(0, 3 - occupied_count).
14. Authoritative YouTube + DB reconciliation state correctly aggregates occupied slots.
"""

import unittest
from datetime import datetime, date, time as dtime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, UploadRecord, Job, RenderOutput, Topic
from config.constants import DAILY_SHORTS_LIMIT, PUBLISHING_SLOTS_UTC
from engines.scheduler_engine import PublicationScheduler


class TestScheduler3PerDayRegression(unittest.TestCase):

    def setUp(self):
        # Create an isolated in-memory SQLite database for every test
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.scheduler = PublicationScheduler(min_lead_minutes=15)
        
        # Fixed reference time: 2026-10-01 00:00:00 UTC
        self.ref_time = datetime(2026, 10, 1, 0, 0, 0)
        self.target_date = self.ref_time.date()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)

    def _add_upload(self, dt: datetime, status: str = "SCHEDULED", video_id: str = "vid_test"):
        job = Job(id=f"job_{video_id}", state="COMPLETED")
        self.db.add(job)
        self.db.flush()
        rec = UploadRecord(
            id=f"upl_{video_id}",
            job_id=job.id,
            youtube_video_id=video_id,
            title=f"Test Video {video_id}",
            description=f"Description for {video_id}",
            status=status,
            scheduled_publish_at=dt if status == "SCHEDULED" else None,
            published_at=dt if status in ("PUBLISHED", "SUCCESS") else None
        )
        self.db.add(rec)
        self.db.commit()
        return rec

    def test_01_zero_scheduled_yields_three_vacancies_for_date(self):
        """Invariant 1: 0 scheduled -> exactly 3 vacancies for that date (06:00, 11:00, 15:00 UTC)."""
        # Limit horizon to 24h so only self.target_date is evaluated
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 6, 0),
            datetime(2026, 10, 1, 11, 0),
            datetime(2026, 10, 1, 15, 0),
        ]
        self.assertEqual(vacant, expected)
        self.assertEqual(len(vacant), 3)

    def test_02_one_scheduled_yields_two_vacancies(self):
        """Invariant 2: 1 scheduled -> exactly 2 vacancies for that date."""
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_1")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 11, 0),
            datetime(2026, 10, 1, 15, 0),
        ]
        self.assertEqual(vacant, expected)
        self.assertEqual(len(vacant), 2)

    def test_03_two_scheduled_yields_one_vacancy(self):
        """Invariant 3: 2 scheduled -> exactly 1 vacancy for that date."""
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_1")
        self._add_upload(datetime(2026, 10, 1, 11, 0), "SCHEDULED", "vid_2")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 15, 0),
        ]
        self.assertEqual(vacant, expected)
        self.assertEqual(len(vacant), 1)

    def test_04_three_scheduled_yields_zero_vacancies(self):
        """Invariant 4: 3 scheduled -> exactly 0 vacancies for that date."""
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_1")
        self._add_upload(datetime(2026, 10, 1, 11, 0), "SCHEDULED", "vid_2")
        self._add_upload(datetime(2026, 10, 1, 15, 0), "SCHEDULED", "vid_3")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        self.assertEqual(vacant, [])
        self.assertEqual(len(vacant), 0)

    def test_05_preserved_slots_not_overwritten(self):
        """Invariant 5: Occupied slots are preserved and never returned as vacant."""
        occupied_dt = datetime(2026, 10, 1, 11, 0)
        self._add_upload(occupied_dt, "SCHEDULED", "vid_preserved")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        self.assertNotIn(occupied_dt, vacant)

    def test_06_middle_slot_filled_preserves_first_and_third(self):
        """Invariant 6: Middle slot filled (11:00) -> vacancies are first (06:00) and third (15:00)."""
        self._add_upload(datetime(2026, 10, 1, 11, 0), "SCHEDULED", "vid_mid")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 6, 0),
            datetime(2026, 10, 1, 15, 0),
        ]
        self.assertEqual(vacant, expected)

    def test_07_first_slot_filled_preserves_second_and_third(self):
        """Invariant 7: First slot filled (06:00) -> vacancies are middle (11:00) and third (15:00)."""
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_first")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 11, 0),
            datetime(2026, 10, 1, 15, 0),
        ]
        self.assertEqual(vacant, expected)

    def test_08_last_slot_filled_preserves_first_and_second(self):
        """Invariant 8: Last slot filled (15:00) -> vacancies are first (06:00) and middle (11:00)."""
        self._add_upload(datetime(2026, 10, 1, 15, 0), "SCHEDULED", "vid_last")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        expected = [
            datetime(2026, 10, 1, 6, 0),
            datetime(2026, 10, 1, 11, 0),
        ]
        self.assertEqual(vacant, expected)

    def test_09_idempotency_running_twice_returns_same_vacancies(self):
        """Invariant 9: Idempotency: Multiple calls without state change yield identical slot lists."""
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_1")
        vacant_run1 = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=48
        )
        vacant_run2 = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=48
        )
        self.assertEqual(vacant_run1, vacant_run2)

    def test_10_rolling_48_hour_horizon_limit(self):
        """Invariant 10: Rolling 48-hour forward horizon excludes slots > reference_time + 48 hours."""
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=48
        )
        # reference is 2026-10-01 00:00:00 -> horizon_end is 2026-10-03 00:00:00
        # Oct 1 has 3 slots, Oct 2 has 3 slots. Oct 3 06:00 is beyond 48 hours!
        self.assertEqual(len(vacant), 6)
        for slot in vacant:
            self.assertLessEqual(slot, self.ref_time + timedelta(hours=48))

    def test_11_utc_calendar_boundary_enforcement(self):
        """Invariant 11: Daily counts evaluate strictly within pure UTC calendar day (00:00:00 to 23:59:59 UTC)."""
        # Day 1 has 3 published/scheduled videos
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "d1_1")
        self._add_upload(datetime(2026, 10, 1, 11, 0), "SCHEDULED", "d1_2")
        self._add_upload(datetime(2026, 10, 1, 15, 0), "SCHEDULED", "d1_3")
        
        # Day 2 has 0 videos
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=48
        )
        # Day 1 should have 0 vacancies, Day 2 should have 3 vacancies
        day1_vacancies = [s for s in vacant if s.date() == date(2026, 10, 1)]
        day2_vacancies = [s for s in vacant if s.date() == date(2026, 10, 2)]
        self.assertEqual(day1_vacancies, [])
        self.assertEqual(len(day2_vacancies), 3)

    def test_12_min_lead_time_exclusion(self):
        """Invariant 12: A slot <= reference_time + min_lead_minutes (15 min) is skipped."""
        # Set reference time to 05:50 UTC (10 mins before 06:00 slot)
        ref_near = datetime(2026, 10, 1, 5, 50, 0)
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=ref_near, horizon_hours=24
        )
        # 06:00 is within 10 mins (< 15 min lead time), so it must be skipped
        self.assertNotIn(datetime(2026, 10, 1, 6, 0), vacant)
        self.assertIn(datetime(2026, 10, 1, 11, 0), vacant)
        self.assertIn(datetime(2026, 10, 1, 15, 0), vacant)

    def test_13_daily_ceiling_of_three_hard_capped(self):
        """Invariant 13: Daily count cannot exceed DAILY_SHORTS_LIMIT = 3."""
        # 2 uploads on Oct 1
        self._add_upload(datetime(2026, 10, 1, 6, 0), "SCHEDULED", "vid_a")
        self._add_upload(datetime(2026, 10, 1, 11, 0), "SCHEDULED", "vid_b")
        vacant = self.scheduler.get_vacant_slots_in_horizon(
            self.db, reference_time=self.ref_time, horizon_hours=24
        )
        # Exactly 1 vacancy remaining for Oct 1
        self.assertEqual(len(vacant), 1)
        self.assertEqual(vacant[0], datetime(2026, 10, 1, 15, 0))

    def test_14_reconciliation_authoritative_youtube_and_db(self):
        """Invariant 14: Authoritative YouTube inventory correctly updates occupied state."""
        with patch.object(self.scheduler, "get_authoritative_schedule_state") as mock_state:
            mock_occupied = {
                datetime(2026, 10, 1, 6, 0),
                datetime(2026, 10, 1, 11, 0)
            }
            mock_day_counts = {
                date(2026, 10, 1): 2
            }
            mock_slot_details = {
                datetime(2026, 10, 1, 6, 0): [{"id": "yt_1", "type": "SCHEDULED"}],
                datetime(2026, 10, 1, 11, 0): [{"id": "yt_2", "type": "SCHEDULED"}]
            }
            mock_state.return_value = (mock_occupied, mock_day_counts, mock_slot_details)
            
            vacant = self.scheduler.get_vacant_slots_in_horizon(
                self.db, reference_time=self.ref_time, horizon_hours=24
            )
            # Only 15:00 should be vacant
            self.assertEqual(vacant, [datetime(2026, 10, 1, 15, 0)])


if __name__ == "__main__":
    unittest.main()
