import tempfile
import unittest
from datetime import date
from pathlib import Path

from pm.sources import portals

INVENTED_NOT_STARTED = """# Invented widget export: Handoff

## Top of queue

This is the next thing to pick up. It needs Erik's go before the production gate.
Tracked in invented-org/widget#12 and https://github.com/invented-org/widget/pull/13.
"""

INVENTED_CLAIMED = """# Invented gadget migration: Handoff

> **Re-claimed 2026-09-20 by session invented-07 (Invented Laptop) with Erik's go.** Message invented-07.

## What this is

Routine invented work.
"""

INVENTED_DONE_BANNER = """# Invented cleanup

> **Done, verified 2026-09-18 (invented-07).** The work shipped 2026-09-10.
"""

INVENTED_PAUSED = """# Invented letter resend

> **Paused 2026-09-19 (invented-07).** Ask Erik whether the resend is still needed.
"""


def write(folder: Path, name: str, text: str) -> None:
    (folder / name).write_text(text, encoding="utf-8")


def no_git(path):
    return None


class PortalAdapter(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def collect(self, **kwargs):
        return portals.collect(self.folder, last_commit_day=kwargs.pop("last_commit_day", no_git), **kwargs)

    def only(self):
        result = self.collect()
        self.assertEqual(len(result.items), 1, result.errors)
        return result.items[0]

    def test_status_comes_from_filename_suffix(self):
        write(self.folder, "portal-2026-09-01-widget-export-not-started.md", INVENTED_NOT_STARTED)
        write(self.folder, "portal-2026-09-02-gadget-migration-in-progress.md", INVENTED_CLAIMED)
        write(self.folder, "portal-2026-09-03-cleanup-done.md", INVENTED_DONE_BANNER)
        statuses = {item.id: item.status for item in self.collect().items}
        self.assertEqual(statuses, {
            "portal:2026-09-01-widget-export": "open",
            "portal:2026-09-02-gadget-migration": "in_progress",
            "portal:2026-09-03-cleanup": "done",
        })

    def test_title_drops_the_handoff_suffix(self):
        write(self.folder, "portal-2026-09-01-widget-export-not-started.md", INVENTED_NOT_STARTED)
        self.assertEqual(self.only().title, "Invented widget export")

    def test_created_is_the_filename_date(self):
        write(self.folder, "portal-2026-09-01-widget-export-not-started.md", INVENTED_NOT_STARTED)
        self.assertEqual(self.only().created, date(2026, 9, 1))

    def test_signals_are_extracted(self):
        write(self.folder, "portal-2026-09-01-widget-export-not-started.md", INVENTED_NOT_STARTED)
        item = self.only()
        self.assertTrue(item.critical_hints)
        self.assertTrue(item.waiting_on_erik)
        self.assertEqual(item.refs, ["invented-org/widget#12", "invented-org/widget#13"])
        self.assertEqual(item.links, ["https://github.com/invented-org/widget/pull/13"])

    def test_claim_banner_sets_claimant_and_activity(self):
        write(self.folder, "portal-2026-09-02-gadget-migration-in-progress.md", INVENTED_CLAIMED)
        item = self.only()
        self.assertEqual(item.claimed_by, "session invented-07")
        self.assertEqual(item.last_activity, date(2026, 9, 20))
        self.assertEqual(item.waiting_on_erik, [])

    def test_in_progress_without_banner_is_still_claimed(self):
        write(self.folder, "portal-2026-09-02-quiet-in-progress.md", "# Invented quiet work\n")
        self.assertEqual(self.only().claimed_by, "another session (filename says in-progress)")

    def test_done_banner_on_open_file_is_a_done_hint(self):
        write(self.folder, "portal-2026-09-03-cleanup-in-progress.md", INVENTED_DONE_BANNER)
        item = self.only()
        self.assertEqual(item.status, "in_progress")
        self.assertTrue(item.done_hints)

    def test_paused_banner_pauses_and_waits_on_erik(self):
        write(self.folder, "portal-2026-09-15-letter-resend-not-started.md", INVENTED_PAUSED)
        item = self.only()
        self.assertEqual(item.status, "paused")
        self.assertTrue(item.waiting_on_erik)

    def test_git_commit_date_counts_as_activity(self):
        write(self.folder, "portal-2026-09-01-widget-export-not-started.md", INVENTED_NOT_STARTED)
        result = self.collect(last_commit_day=lambda path: date(2026, 9, 24))
        self.assertEqual(result.items[0].last_activity, date(2026, 9, 24))

    def test_missing_lifecycle_suffix_is_unknown_with_evidence(self):
        write(self.folder, "portal-2026-09-01-widget-export.md", INVENTED_NOT_STARTED)
        item = self.only()
        self.assertEqual(item.status, "unknown")
        self.assertIn("filename has no lifecycle suffix", item.evidence)

    def test_missing_date_leaves_created_empty(self):
        write(self.folder, "portal-widget-export-not-started.md", INVENTED_NOT_STARTED)
        item = self.only()
        self.assertIsNone(item.created)
        self.assertEqual(item.status, "open")

    def test_impossible_filename_date_is_ignored(self):
        write(self.folder, "portal-2026-02-30-widget-export-not-started.md", INVENTED_NOT_STARTED)
        self.assertIsNone(self.only().created)

    def test_empty_file_uses_slug_as_title(self):
        write(self.folder, "portal-2026-09-01-empty-thing-not-started.md", "")
        self.assertEqual(self.only().title, "empty-thing")

    def test_binary_garbage_does_not_crash(self):
        (self.folder / "portal-2026-09-01-garbage-not-started.md").write_bytes(b"\xff\xfe\x00# \x9c\x80")
        self.assertEqual(len(self.collect().items), 1)

    def test_unicode_title(self):
        write(self.folder, "portal-2026-09-01-unicode-not-started.md", "# Invented café ✓ 北极 migration\n")
        self.assertEqual(self.only().title, "Invented café ✓ 北极 migration")

    def test_non_portal_files_are_ignored(self):
        write(self.folder, "notes.md", "# not a portal")
        write(self.folder, "portal-2026-09-01-a-not-started.txt", "# wrong extension")
        self.assertEqual(self.collect().items, [])

    def test_missing_folder_is_an_error_not_a_crash(self):
        result = portals.collect(self.folder / "absent", last_commit_day=no_git)
        self.assertEqual(result.items, [])
        self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
