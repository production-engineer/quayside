import unittest
from datetime import date, datetime, timezone

from pm.model import WorkItem, idle_days, parse_day


class ParseDayValueLadder(unittest.TestCase):
    def test_absent_is_none(self):
        self.assertIsNone(parse_day(None))

    def test_blank_and_whitespace_are_none(self):
        self.assertIsNone(parse_day(""))
        self.assertIsNone(parse_day("   "))

    def test_numbers_are_not_dates(self):
        for value in (0, -1, 1, 2, 1000000, 1.5):
            with self.subTest(value=value):
                self.assertIsNone(parse_day(value))

    def test_booleans_are_not_dates(self):
        self.assertIsNone(parse_day(True))
        self.assertIsNone(parse_day(False))

    def test_wrong_types_are_none(self):
        self.assertIsNone(parse_day(["2026-09-26"]))
        self.assertIsNone(parse_day({"day": "2026-09-26"}))

    def test_iso_day(self):
        self.assertEqual(parse_day("2026-09-26"), date(2026, 9, 26))

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(parse_day(" 2026-09-26\n"), date(2026, 9, 26))

    def test_impossible_calendar_days_are_none(self):
        for value in ("2026-02-30", "2026-13-01", "2026-00-10", "0000-01-01", "2025-02-29"):
            with self.subTest(value=value):
                self.assertIsNone(parse_day(value))

    def test_leap_day_is_valid(self):
        self.assertEqual(parse_day("2028-02-29"), date(2028, 2, 29))

    def test_boundary_days(self):
        self.assertEqual(parse_day("1970-01-01"), date(1970, 1, 1))
        self.assertEqual(parse_day("9999-12-31"), date(9999, 12, 31))

    def test_unpadded_and_garbage_text_are_none(self):
        for value in ("2026-9-5", "26/09/2026", "yesterday", "2026-09-26junk", "TBD"):
            with self.subTest(value=value):
                self.assertIsNone(parse_day(value))

    def test_non_ascii_digits_are_none(self):
        self.assertIsNone(parse_day("２０２６-０９-２６"))

    def test_utc_timestamp_midday_keeps_its_day(self):
        self.assertEqual(parse_day("2026-09-26T20:00:00Z"), date(2026, 9, 26))

    def test_timestamps_use_alaska_time_whatever_the_host_zone(self):
        self.assertEqual(parse_day("2026-09-26T06:00:00Z"), date(2026, 9, 25))
        self.assertEqual(parse_day(datetime(2026, 9, 26, 6, 0, tzinfo=timezone.utc)), date(2026, 9, 25))

    def test_naive_timestamp(self):
        self.assertEqual(parse_day("2026-09-26T08:15:00"), date(2026, 9, 26))

    def test_date_and_datetime_objects_pass_through(self):
        self.assertEqual(parse_day(date(2026, 1, 2)), date(2026, 1, 2))
        self.assertEqual(parse_day(datetime(2026, 1, 2, 12, 0)), date(2026, 1, 2))
        self.assertEqual(parse_day(datetime(2026, 1, 2, 20, 0, tzinfo=timezone.utc)), date(2026, 1, 2))


class IdleDays(unittest.TestCase):
    def test_counts_days_since_last_activity(self):
        item = WorkItem(source="tasks", id="tasks:1", title="Invented", last_activity=date(2026, 9, 1))
        self.assertEqual(idle_days(item, date(2026, 9, 26)), 25)

    def test_future_activity_clamps_to_zero(self):
        item = WorkItem(source="tasks", id="tasks:1", title="Invented", last_activity=date(2027, 1, 1))
        self.assertEqual(idle_days(item, date(2026, 9, 26)), 0)

    def test_unknown_activity_is_none(self):
        item = WorkItem(source="tasks", id="tasks:1", title="Invented")
        self.assertIsNone(idle_days(item, date(2026, 9, 26)))


class SnapshotRoundTrip(unittest.TestCase):
    def test_to_dict_and_back_preserves_every_field(self):
        item = WorkItem(
            source="portal",
            id="portal:invented",
            title="Invented portal ✓ ünïcödé",
            project="Keep",
            kind="portal",
            status="in_progress",
            owner="session invented-01",
            created=date(2026, 9, 1),
            last_activity=date(2026, 9, 20),
            links=["https://example.com/invented"],
            refs=["invented-owner/invented-repo#3"],
            blocked_on="an invented token",
            waiting_on_erik=["needs Erik's go"],
            critical_hints=["top of queue"],
            priority="high",
            done_hints=["Done, verified"],
            closes=["invented-owner/invented-repo#4"],
            claimed_by="session invented-01",
            evidence=["filename says in-progress"],
        )
        self.assertEqual(WorkItem.from_dict(item.to_dict()), item)

    def test_dates_serialize_as_iso_strings(self):
        item = WorkItem(source="tasks", id="tasks:1", title="Invented", created=date(2026, 9, 1))
        self.assertEqual(item.to_dict()["created"], "2026-09-01")
        self.assertIsNone(item.to_dict()["last_activity"])


if __name__ == "__main__":
    unittest.main()
