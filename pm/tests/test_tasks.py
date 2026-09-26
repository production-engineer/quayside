import tempfile
import unittest
from datetime import date
from pathlib import Path

from pm.sources import tasks

INVENTED_TASKS = """# Invented tasks

## Writing rules

- [ ] 99. This rule line is not a task (added 2026-01-01)

## Open

- [ ] 1. Decide the invented sharing surface (added 2026-08-15)
  Smallest next increment: name who needs it.
- [ ] 2. Inventory the invented sources (added 2026-08-16)
  In his words: "invented quote". Waiting on Erik for the list.
- [ ] 3. Collect the invented migration sources (added 2026-08-17)
  Depends on the task 2 inventory; the slice is marking sources.
- [ ] 4. Build the invented follow-up (added 2026-08-18)
  Depends on task 5 being done.
- [ ] 7. Model the invented partner effort (added 2026-08-19)
  Depends on RH tracker task 98 taking shape.
- [ ] 6. Café ✓ 北极 invented unicode task (added 2026-02-30)

## Done

- [x] 5. Finish the invented prerequisite (added 2026-08-01)
"""


class TasksAdapter(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "TASKS.md"

    def items(self, text):
        self.path.write_text(text, encoding="utf-8")
        result = tasks.collect(self.path)
        self.assertEqual(result.errors, [])
        return {item.id: item for item in result.items}

    def test_parses_open_and_done_sections(self):
        items = self.items(INVENTED_TASKS)
        self.assertEqual(sorted(items), ["tasks:1", "tasks:2", "tasks:3", "tasks:4", "tasks:5", "tasks:6", "tasks:7"])
        self.assertEqual(items["tasks:1"].status, "open")
        self.assertEqual(items["tasks:5"].status, "done")

    def test_title_and_added_date(self):
        item = self.items(INVENTED_TASKS)["tasks:1"]
        self.assertEqual(item.title, "Decide the invented sharing surface")
        self.assertEqual(item.created, date(2026, 8, 15))
        self.assertEqual(item.last_activity, date(2026, 8, 15))
        self.assertEqual(item.project, "quayside")

    def test_description_lines_feed_signals(self):
        self.assertTrue(self.items(INVENTED_TASKS)["tasks:2"].waiting_on_erik)

    def test_dependency_on_open_task_is_blocked(self):
        self.assertEqual(self.items(INVENTED_TASKS)["tasks:3"].blocked_on, "task 2 (open)")

    def test_dependency_on_done_task_is_not_blocked(self):
        self.assertIsNone(self.items(INVENTED_TASKS)["tasks:4"].blocked_on)

    def test_dependency_on_a_task_elsewhere_keeps_the_phrase(self):
        self.assertEqual(self.items(INVENTED_TASKS)["tasks:7"].blocked_on, "RH tracker task 98 taking shape")

    def test_unicode_title_and_impossible_date(self):
        item = self.items(INVENTED_TASKS)["tasks:6"]
        self.assertEqual(item.title, "Café ✓ 北极 invented unicode task")
        self.assertIsNone(item.created)

    def test_empty_file_has_no_items_and_no_errors(self):
        self.assertEqual(self.items(""), {})

    def test_headings_only_has_no_items(self):
        self.assertEqual(self.items("# Quayside tasks\n\n## Open\n\n## Done\n"), {})

    def test_missing_file_is_an_error(self):
        result = tasks.collect(self.path)
        self.assertEqual(result.items, [])
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
