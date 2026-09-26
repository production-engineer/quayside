import io
import os
import json
import shutil
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pm import cli
from pm.sources import github

REPO_ROOT = Path(__file__).resolve().parents[2]


def failing_gh(args):
    raise github.GhFailure("invented gh outage")


class Cli(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.keep = self.base / "Keep"
        self.keep.mkdir()
        (self.keep / "portal-2026-09-01-invented-thing-not-started.md").write_text(
            "# Invented thing: Handoff\n\nNeeds Erik's go.\n", encoding="utf-8")
        self.tasks = self.base / "TASKS.md"
        self.tasks.write_text("## Open\n\n- [ ] 1. Invented task (added 2026-09-01)\n", encoding="utf-8")
        self.out = self.base / "out"

    def run_cli(self, *extra, gh=failing_gh):
        argv = ["--keep", str(self.keep), "--tasks", str(self.tasks), "--out", str(self.out), "--today", "2026-09-26", *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(argv, gh=gh)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_writes_report_snapshot_and_board(self):
        code, stdout, _ = self.run_cli("--no-github")
        self.assertEqual(code, 0)
        for name in ("report.md", "snapshot.json", "board.html"):
            self.assertTrue((self.out / name).exists(), name)
        snapshot = json.loads((self.out / "snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot["schema"], cli.SNAPSHOT_SCHEMA)
        self.assertEqual({item["source"] for item in snapshot["items"]}, {"portal", "tasks"})
        self.assertIn("report.md", stdout)

    def test_gh_failure_still_produces_a_report(self):
        code, _, stderr = self.run_cli()
        self.assertEqual(code, 0)
        snapshot = json.loads((self.out / "snapshot.json").read_text(encoding="utf-8"))
        self.assertTrue(snapshot["sources"]["github"]["errors"])
        self.assertIn("invented gh outage", stderr)
        self.assertEqual(len(snapshot["items"]), 2)

    def test_refuses_to_write_inside_the_repository(self):
        self.out = REPO_ROOT / "pm-out-should-not-exist"
        self.assertFalse(self.out.exists())
        self.addCleanup(shutil.rmtree, self.out, True)
        code, _, stderr = self.run_cli("--no-github")
        self.assertEqual(code, 2)
        self.assertFalse(self.out.exists())
        self.assertIn("inside the repository", stderr)

    def test_tilde_output_path_is_expanded_before_writing(self):
        home = self.base / "home"
        home.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.base)
        with unittest.mock.patch.dict("os.environ", {"HOME": str(home)}):
            self.out = Path("~/pm-out")
            code, _, _ = self.run_cli("--no-github")
        self.assertEqual(code, 0)
        self.assertTrue((home / "pm-out" / "snapshot.json").exists())
        self.assertFalse((self.base / "~").exists())

    def test_unwritable_output_is_a_clean_error(self):
        blocker = self.base / "file"
        blocker.write_text("invented", encoding="utf-8")
        self.out = blocker / "out"
        code, _, stderr = self.run_cli("--no-github")
        self.assertEqual(code, 2)
        self.assertIn("could not write", stderr)

    def test_excluded_repos_are_not_looked_up(self):
        (self.keep / "portal-2026-09-02-frozen-ref-not-started.md").write_text(
            "# Invented\n\nSee invented-org/frozen#40 and invented-org/live#41.\n", encoding="utf-8")
        calls = []

        def fake(args):
            calls.append(args)
            if args[:2] == ["api", "user"]:
                return "invented-erik\n"
            if args[:2] == ["api", "graphql"]:
                return json.dumps({"data": {"search": {"issueCount": 0, "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}})
            if args[:2] == ["repo", "list"]:
                return "[]"
            raise github.GhFailure("HTTP 404: Not Found")

        self.run_cli("--owner", "invented-org", "--exclude-repo", "invented-org/frozen", gh=fake)
        looked_up = [call[1] for call in calls if call[0] == "api" and call[1].startswith("repos/")]
        self.assertEqual(looked_up, ["repos/invented-org/live/issues/41"])

    def test_rerenders_from_a_snapshot(self):
        self.run_cli("--no-github")
        (self.out / "board.html").unlink()
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--from-snapshot", str(self.out / "snapshot.json"), "--out", str(self.out)], gh=failing_gh)
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "board.html").exists())

    def test_tracker_csv_is_read_when_given(self):
        csv_path = self.base / "tracker.csv"
        csv_path.write_text("Task #,Task name,Status\n1,Invented tracker row,To Do\n", encoding="utf-8")
        self.run_cli("--no-github", "--tracker-csv", str(csv_path))
        snapshot = json.loads((self.out / "snapshot.json").read_text(encoding="utf-8"))
        self.assertIn("tracker:1", [item["id"] for item in snapshot["items"]])

    def test_bad_today_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_cli("--no-github", "--today", "2026-02-30")


if __name__ == "__main__":
    unittest.main()
