import tempfile
import unittest
from datetime import date
from pathlib import Path

from pm.sources import tracker

HEADER = "Task #,Task name,Task description (links here),Status,Status Update,Priority,Due date,Task lead assigned,Resources needed,Date added,Last update\n"

INVENTED_ROWS = HEADER + (
    '1,Invented intake form,"Build it. See invented-org/widget#4 and https://example.com/invented",To Do,,High,,Erik,,2026-08-01,2026-08-20\n'
    '2,Invented payroll check,Reconcile invented rows,In progress,2026-09-10: invented check started,Critical,,Invented Person,,2026-08-02,2026-09-01\n'
    '3,Invented archive,Old invented idea,Backlog,,Low,,,,2026-07-01,\n'
    '4,Invented finished thing,Shipped invented work,Done,2026-09-01: invented done,Medium,,,,2026-07-02,2026-09-01\n'
    '5,Invented shipped but open,Invented,In progress,2026-09-12: merged and live,Medium,,,,2026-07-03,2026-09-12\n'
    '6,Invented not done yet,Invented,In progress,2026-09-12: not done yet,Medium,,,,2026-07-03,2026-09-12\n'
    ',,,,,,,,,,\n'
    '7,Café ✓ 北极 invented,Invented,Weird status,,Urgent-ish,,,,2026-13-01,not a date\n'
)


class TrackerAdapter(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "tracker.csv"

    def collect(self, text, encoding="utf-8"):
        self.path.write_text(text, encoding=encoding)
        return tracker.collect(self.path)

    def items(self, text, encoding="utf-8"):
        result = self.collect(text, encoding)
        self.assertEqual(result.errors, [])
        return {item.id: item for item in result.items}

    def test_rows_become_items_and_blank_rows_are_skipped(self):
        self.assertEqual(sorted(self.items(INVENTED_ROWS)),
                         ["tracker:1", "tracker:2", "tracker:3", "tracker:4", "tracker:5", "tracker:6", "tracker:7"])

    def test_status_normalization(self):
        items = self.items(INVENTED_ROWS)
        self.assertEqual({key: item.status for key, item in items.items()}, {
            "tracker:1": "open", "tracker:2": "in_progress", "tracker:3": "backlog", "tracker:4": "done",
            "tracker:5": "in_progress", "tracker:6": "in_progress", "tracker:7": "unknown",
        })

    def test_fields_map_by_header_name(self):
        item = self.items(INVENTED_ROWS)["tracker:1"]
        self.assertEqual(item.title, "Invented intake form")
        self.assertEqual(item.priority, "high")
        self.assertEqual(item.owner, "Erik")
        self.assertEqual(item.created, date(2026, 8, 1))
        self.assertEqual(item.last_activity, date(2026, 8, 20))
        self.assertEqual(item.refs, ["invented-org/widget#4"])
        self.assertEqual(item.links, ["https://example.com/invented"])
        self.assertEqual(item.project, "remote-hands")

    def test_lead_named_erik_is_waiting_on_erik(self):
        items = self.items(INVENTED_ROWS)
        self.assertEqual(items["tracker:1"].waiting_on_erik, ["task lead is Erik"])
        self.assertEqual(items["tracker:2"].waiting_on_erik, [])

    def test_status_update_dates_count_as_activity(self):
        self.assertEqual(self.items(INVENTED_ROWS)["tracker:2"].last_activity, date(2026, 9, 10))

    def test_future_dates_are_not_activity(self):
        text = "Task #,Task name,Status,Status Update,Date added\n1,Invented,To Do,waiting on vendor due 2026-12-01,2026-08-01\n"
        self.path.write_text(text, encoding="utf-8")
        item = tracker.collect(self.path, today=date(2026, 9, 26)).items[0]
        self.assertEqual(item.last_activity, date(2026, 8, 1))

    def test_shipped_status_update_is_a_done_hint(self):
        items = self.items(INVENTED_ROWS)
        self.assertTrue(items["tracker:5"].done_hints)
        self.assertEqual(items["tracker:6"].done_hints, [])

    def test_bad_dates_and_unknown_priority(self):
        item = self.items(INVENTED_ROWS)["tracker:7"]
        self.assertEqual(item.title, "Café ✓ 北极 invented")
        self.assertIsNone(item.created)
        self.assertIsNone(item.last_activity)
        self.assertIsNone(item.priority)

    def test_reordered_columns_still_map(self):
        text = "Status,Task name,Task #\nDone,Invented reordered,9\n"
        item = self.items(text)["tracker:9"]
        self.assertEqual((item.title, item.status), ("Invented reordered", "done"))

    def test_byte_order_mark_is_tolerated(self):
        self.assertIn("tracker:1", self.items(INVENTED_ROWS, encoding="utf-8-sig"))

    def test_missing_task_number_uses_row_position(self):
        self.assertIn("tracker:row2", self.items("Task name,Status\nInvented unnumbered,To Do\n"))

    def test_missing_task_name_column_is_an_error(self):
        result = self.collect("Status,Priority\nTo Do,High\n")
        self.assertEqual(result.items, [])
        self.assertTrue(result.errors)

    def test_header_only_is_empty(self):
        self.assertEqual(self.items(HEADER), {})

    def test_empty_file_is_an_error(self):
        self.assertTrue(self.collect("").errors)

    def test_missing_file_is_an_error(self):
        result = tracker.collect(self.path)
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
