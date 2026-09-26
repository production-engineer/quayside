import re
import unittest
from datetime import date

from pm import analyze, render
from pm.cli import build_snapshot_dict
from pm.model import SourceResult, WorkItem

TODAY = date(2026, 9, 26)


def snapshot():
    items = [
        WorkItem(source="portal", id="portal:x", title="Invented <script>alert(1)</script> café ✓", status="open",
                 last_activity=TODAY, waiting_on_erik=["needs Erik's go"],
                 links=["https://example.com/invented", "javascript:alert(1)"]),
        WorkItem(source="tasks", id="tasks:1", title="Invented old task", status="open", last_activity=date(2026, 1, 1)),
        WorkItem(source="github", id="github:o/r#7", title="Invented rebase me", kind="pr", status="review",
                 last_activity=TODAY, verdict="NEEDS_REBASE", verdict_evidence="behind base, no conflicts",
                 links=["https://github.com/o/r/pull/7"]),
    ]
    results = [SourceResult("portals", items[:1], []), SourceResult("tasks", items[1:2], ["invented warning"]),
               SourceResult("github", items[2:], [])]
    built = build_snapshot_dict(results, analyze.analyze(items, TODAY), TODAY)
    built["changes"] = {"previous_generated_on": "2026-09-25", "new": ["portal:x"], "closed": [], "gone": ["tasks:9"],
                        "newly_stuck": [], "status_flips": [{"id": "tasks:1", "from": "backlog", "to": "open"}],
                        "titles": {"tasks:9": "Invented vanished <b>task</b>"}}
    return built


class Markdown(unittest.TestCase):
    def setUp(self):
        self.text = render.markdown(snapshot())

    def test_has_all_four_sections(self):
        for heading in ("## What to work on next", "## What is stuck", "## Looks done but is not closed", "## Waiting on Erik",
                        "## Agent and bot PRs awaiting a verdict", "## Archive candidates", "## What changed since last run"):
            self.assertIn(heading, self.text)

    def test_shows_reasons_and_counts(self):
        self.assertIn("waiting on Erik", self.text)
        self.assertIn("portals: 1 items", self.text)
        self.assertIn("invented warning", self.text)

    def test_unicode_survives(self):
        self.assertIn("café ✓", self.text)

    def test_pr_verdicts_are_grouped_with_an_action(self):
        self.assertIn("## PR verdicts", self.text)
        self.assertIn("Needs rebase (1)", self.text)
        self.assertIn("Rebase onto the base branch", self.text)
        self.assertIn("Invented rebase me", self.text)

    def test_changes_list_titles_and_flips(self):
        self.assertIn("Invented vanished", self.text)
        self.assertIn("backlog to open", self.text)
        self.assertIn("since 2026-09-25", self.text)

    def test_first_run_says_there_is_nothing_to_compare(self):
        first = snapshot()
        first["changes"] = {"previous_generated_on": None, "new": [], "closed": [], "gone": [], "newly_stuck": [],
                            "status_flips": [], "titles": {}}
        self.assertIn("First run", render.markdown(first))

    def test_snapshot_without_changes_still_renders(self):
        bare = snapshot()
        del bare["changes"]
        self.assertIn("## What to work on next", render.markdown(bare))

    def test_unsafe_links_are_dropped(self):
        self.assertNotIn("javascript:", self.text)


class Html(unittest.TestCase):
    def setUp(self):
        self.page = render.html(snapshot())

    def test_titles_are_escaped(self):
        self.assertNotIn("<script>alert(1)</script>", self.page)
        self.assertIn("&lt;script&gt;", self.page)

    def test_makes_no_external_requests(self):
        self.assertNotRegex(self.page, r"<script[^>]*\bsrc=")
        self.assertNotRegex(self.page, r"<link[^>]*\bhref=")
        self.assertNotRegex(self.page, r"<img[^>]*\bsrc=\"?https?:")
        self.assertNotIn("@import", self.page)
        self.assertNotRegex(self.page, r"url\(\s*['\"]?https?:")

    def test_only_http_links_become_hrefs(self):
        hrefs = re.findall(r'href="([^"]*)"', self.page)
        self.assertTrue(hrefs)
        self.assertTrue(all(href.startswith(("https://", "http://", "#")) for href in hrefs))

    def test_has_the_four_columns(self):
        for heading in ("What to work on next", "What is stuck", "Looks done but is not closed", "Waiting on Erik",
                        "Agent and bot PRs awaiting a verdict", "Archive candidates", "What changed since last run"):
            self.assertIn(heading, self.page)

    def test_pr_verdicts_section(self):
        self.assertIn("PR verdicts", self.page)
        self.assertIn("Needs rebase (1)", self.page)

    def test_change_titles_are_escaped(self):
        self.assertNotIn("<b>task</b>", self.page)

    def test_unicode_survives(self):
        self.assertIn("café ✓", self.page)


if __name__ == "__main__":
    unittest.main()
