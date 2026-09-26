import io
import json
import os
import shutil
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pm import cli
from pm.sources import github

REPO_ROOT = Path(__file__).resolve().parents[2]
TENANT_MARKERS = {"rh": "RHMARK", "bc": "BCMARK", "personal": "PMARK"}
UNASSIGNED_MARKER = "UNMARK"


def failing_gh(args):
    raise github.GhFailure("invented gh outage")


def search_page(nodes):
    return json.dumps({"data": {"search": {"issueCount": len(nodes), "pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}}})


def invented_node(owner, number, title, kind="Issue", body=""):
    node = {"__typename": kind, "number": number, "title": title, "url": f"https://github.com/{owner}/invented/{'pull' if kind == 'PullRequest' else 'issues'}/{number}",
            "state": "OPEN", "createdAt": "2026-09-01T20:00:00Z", "updatedAt": "2026-09-10T20:00:00Z", "closedAt": None,
            "body": body, "repository": {"nameWithOwner": f"{owner}/invented"}, "author": {"login": "invented-dana"},
            "assignees": {"nodes": []}, "labels": {"nodes": []}}
    if kind == "PullRequest":
        node.update({"isDraft": False, "mergedAt": None, "reviewRequests": {"nodes": []}})
    return node


def three_org_gh(calls):
    by_owner = {
        "Remote-Hands-LLC": [invented_node("Remote-Hands-LLC", 1, "RHMARK invented ticket", body="Tracked in beadedcloud/invented#2")],
        "beadedcloud": [invented_node("beadedcloud", 2, "BCMARK invented ticket")],
        "production-engineer": [invented_node("production-engineer", 3, "PMARK invented ticket")],
    }

    def fake(args):
        calls.append(args)
        if args[:2] == ["api", "user"]:
            return "production-engineer\n"
        if args[:2] == ["api", "user/orgs"]:
            return "Remote-Hands-LLC\nbeadedcloud\n"
        if args[:2] == ["repo", "list"]:
            return json.dumps([{"nameWithOwner": f"{args[2]}/invented"}])
        if args[:2] == ["api", "graphql"]:
            query = next((value[2:] for value in args if value.startswith("q=")), "")
            for owner, nodes in by_owner.items():
                if query.startswith(f"user:{owner} is:issue is:open"):
                    return search_page(nodes)
            if "pullRequest(number:" in next(value for value in args if value.startswith("query=")):
                return json.dumps({"data": {}})
            return search_page([])
        if args[0] == "api" and args[1].startswith("repos/"):
            raise github.GhFailure("HTTP 404: Not Found")
        raise AssertionError(f"unexpected gh call {args}")
    return fake


class Cli(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.keep = self.base / "Keep"
        self.keep.mkdir()
        self.personal_repo = self.base / "repos" / "invented-personal"
        self.rh_repo = self.base / "repos" / "invented-rh-app"
        for folder in (self.personal_repo, self.rh_repo):
            folder.mkdir(parents=True)
        self.remotes = {str(self.personal_repo): "production-engineer", str(self.rh_repo): "Remote-Hands-LLC",
                        str(self.base / "tasks-repo"): "production-engineer"}
        (self.keep / "portal-2026-09-01-invented-thing-not-started.md").write_text(
            f"# PMARK invented thing: Handoff\n\n- Project: `{self.personal_repo}`\n\nNeeds Erik's go.\n", encoding="utf-8")
        (self.base / "tasks-repo").mkdir()
        self.tasks = self.base / "tasks-repo" / "TASKS.md"
        self.tasks.write_text("## Open\n\n- [ ] 1. PMARK invented task (added 2026-09-01)\n", encoding="utf-8")
        self.out = self.base / "out"
        self.state = self.base / "state"

    def remote_owner(self, path):
        return self.remotes.get(str(path))

    def run_cli(self, *extra, gh=failing_gh):
        argv = ["--keep", str(self.keep), "--tasks", str(self.tasks), "--out", str(self.out), "--today", "2026-09-26",
                "--state-dir", str(self.state), *extra]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), unittest.mock.patch.object(cli.Path, "home", return_value=self.base):
            code = cli.main(argv, gh=gh, remote_owner=self.remote_owner)
        return code, stdout.getvalue(), stderr.getvalue()

    def snapshot(self, tenant="personal"):
        return json.loads((self.out / tenant / "snapshot.json").read_text(encoding="utf-8"))

    def add_rh_and_unassigned_portals(self):
        (self.keep / "portal-2026-09-02-rh-thing-not-started.md").write_text(
            f"# RHMARK invented rh work\n\n- Project: `{self.rh_repo}`\n", encoding="utf-8")
        (self.keep / "portal-2026-09-03-loose-not-started.md").write_text(
            "# UNMARK invented loose work\n\n- Project: this is invented operations work.\n", encoding="utf-8")

    def written_files(self):
        return sorted(path for root in (self.out, self.state) if root.exists() for path in root.rglob("*") if path.is_file())

    def test_writes_report_snapshot_and_board_per_tenant(self):
        code, stdout, _ = self.run_cli("--no-github")
        self.assertEqual(code, 0)
        for name in ("report.md", "snapshot.json", "board.html"):
            self.assertTrue((self.out / "personal" / name).exists(), name)
            self.assertFalse((self.out / name).exists(), name)
        snapshot = self.snapshot()
        self.assertEqual((snapshot["schema"], snapshot["tenant"]), (cli.SNAPSHOT_SCHEMA, "personal"))
        self.assertEqual({item["source"] for item in snapshot["items"]}, {"portal", "tasks"})
        self.assertIn("report.md", stdout)

    def test_no_write_path_holds_two_tenants(self):
        self.add_rh_and_unassigned_portals()
        csv_path = self.base / "tracker.csv"
        csv_path.write_text("Task #,Task name,Task description (links here),Status\n"
                            "7,RHMARK invented tracker row,See https://github.com/beadedcloud/invented/issues/2,To Do\n", encoding="utf-8")
        calls = []
        code, stdout, _ = self.run_cli("--tracker-csv", str(csv_path), gh=three_org_gh(calls))
        self.assertEqual(code, 0)
        files = self.written_files()
        self.assertTrue(files)
        seen = set()
        for path in files:
            text = path.read_text(encoding="utf-8")
            present = {tenant for tenant, marker in TENANT_MARKERS.items() if marker in text}
            self.assertLessEqual(len(present), 1, f"{path} holds {present}")
            self.assertNotIn(UNASSIGNED_MARKER, text, path)
            self.assertNotIn(".quayside", str(path.relative_to(self.base)))
            seen |= present
            if present:
                self.assertIn(f"/{present.pop()}/", str(path))
        self.assertEqual(seen, {"rh", "bc", "personal"})
        self.assertIn("unassigned: portals 1", stdout)
        self.assertNotIn(UNASSIGNED_MARKER, stdout)

    def test_each_tenant_reads_only_its_own_github_owners(self):
        calls = []
        self.run_cli("--tenant", "bc", gh=three_org_gh(calls))
        searched = [value for call in calls for value in call if value.startswith("q=")]
        self.assertTrue(searched)
        self.assertTrue(all(value.startswith("q=user:beadedcloud ") for value in searched), searched)
        self.assertFalse((self.out / "rh").exists())
        self.assertFalse((self.out / "personal").exists())

    def test_cross_tenant_refs_are_never_looked_up(self):
        calls = []
        self.run_cli("--tenant", "rh", gh=three_org_gh(calls))
        looked_up = [call[1] for call in calls if call[0] == "api" and call[1].startswith("repos/")]
        self.assertEqual(looked_up, [])

    def test_combined_view_prints_and_writes_nothing(self):
        self.add_rh_and_unassigned_portals()
        self.run_cli(gh=three_org_gh([]))
        before = {path: path.stat().st_mtime_ns for path in self.written_files()}
        code, stdout, _ = self.run_cli("--combined-view")
        self.assertEqual(code, 0)
        self.assertEqual({path: path.stat().st_mtime_ns for path in self.written_files()}, before)
        for marker in TENANT_MARKERS.values():
            self.assertIn(marker, stdout)
        self.assertIn("nothing was written", stdout)

    def test_combined_view_with_no_snapshots_says_so(self):
        code, stdout, _ = self.run_cli("--combined-view")
        self.assertEqual(code, 1)
        self.assertFalse(self.out.exists())
        self.assertIn("no tenant snapshots", stdout)

    def test_gh_failure_still_produces_a_report(self):
        code, _, stderr = self.run_cli()
        self.assertEqual(code, 0)
        snapshot = self.snapshot()
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
        self.assertTrue((home / "pm-out" / "personal" / "snapshot.json").exists())
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
            f"# PMARK invented\n\n- Project: `{self.personal_repo}`\n\nTracked in production-engineer/frozen#40 and production-engineer/live#41.\n",
            encoding="utf-8")
        calls = []

        def fake(args):
            calls.append(args)
            if args[:2] == ["api", "user"]:
                return "production-engineer\n"
            if args[:2] == ["api", "graphql"]:
                return search_page([])
            if args[:2] == ["repo", "list"]:
                return "[]"
            raise github.GhFailure("HTTP 404: Not Found")

        self.run_cli("--owner", "production-engineer", "--exclude-repo", "production-engineer/frozen", gh=fake)
        looked_up = [call[1] for call in calls if call[0] == "api" and call[1].startswith("repos/")]
        self.assertEqual(looked_up, ["repos/production-engineer/live/issues/41"])

    def test_second_run_reports_what_changed_per_tenant(self):
        self.run_cli("--no-github")
        self.assertIsNone(self.snapshot()["changes"]["previous_generated_on"])
        self.assertTrue((self.state / "personal" / "last-snapshot.json").exists())
        self.assertFalse((self.state / "last-snapshot.json").exists())
        self.tasks.write_text("## Open\n\n- [ ] 1. PMARK invented task (added 2026-09-01)\n- [ ] 2. PMARK new task (added 2026-09-26)\n",
                              encoding="utf-8")
        self.run_cli("--no-github")
        second = self.snapshot()
        self.assertEqual(second["changes"]["previous_generated_on"], "2026-09-26")
        self.assertEqual(second["changes"]["new"], ["tasks:2"])
        self.assertIn("What changed since last run", (self.out / "personal" / "report.md").read_text(encoding="utf-8"))

    def test_no_memory_leaves_no_state(self):
        self.run_cli("--no-github", "--no-memory")
        self.assertFalse(self.state.exists())

    def test_state_dir_inside_the_repository_is_refused(self):
        self.state = REPO_ROOT / "pm-state-should-not-exist"
        self.addCleanup(shutil.rmtree, self.state, True)
        code, _, stderr = self.run_cli("--no-github")
        self.assertEqual(code, 2)
        self.assertFalse(self.state.exists())
        self.assertIn("inside the repository", stderr)

    def test_archive_days_flag_is_passed_through(self):
        self.run_cli("--no-github", "--archive-days", "1")
        self.assertIn("tasks:1", [finding["id"] for finding in self.snapshot()["findings"]["archive"]])

    def test_open_prs_get_verdicts_and_merge_ready_waits_on_erik(self):
        pr = invented_node("production-engineer", 5, "PMARK ready PR", kind="PullRequest", body="Co-Authored-By: Claude")
        state = {"number": 5, "title": "PMARK ready PR", "url": pr["url"], "isDraft": False, "mergeable": "MERGEABLE",
                 "mergeStateStatus": "CLEAN", "reviewDecision": None, "createdAt": "2026-09-01T20:00:00Z", "author": {"login": "production-engineer"},
                 "files": {"nodes": [{"path": "src/invented.py"}]}, "commits": {"nodes": [{"commit": {"committedDate": "2026-09-10T20:00:00Z", "statusCheckRollup": None}}]}}

        def fake(args):
            if args[:2] == ["api", "user"]:
                return "production-engineer\n"
            if args[:2] == ["repo", "list"]:
                return "[]"
            query = next(value for value in args if value.startswith("query="))
            if "pullRequest(number: 5)" in query:
                return json.dumps({"data": {"r0": {"p5": state, "merged": {"nodes": []}}}})
            if "q=user:production-engineer is:pr is:open archived:false -repo:beadedcloud/beadedcloud.com" in args:
                return search_page([pr])
            return search_page([])

        self.run_cli("--owner", "production-engineer", gh=fake)
        snapshot = self.snapshot()
        item = next(entry for entry in snapshot["items"] if entry["id"] == "github:production-engineer/invented#5")
        self.assertEqual(item["verdict"], "MERGE_READY")
        self.assertEqual(snapshot["findings"]["waiting_on_erik"][0]["id"], "github:production-engineer/invented#5")
        self.assertIn("## PR verdicts", (self.out / "personal" / "report.md").read_text(encoding="utf-8"))

    def test_rerenders_from_a_snapshot_into_its_tenant_folder(self):
        self.run_cli("--no-github")
        (self.out / "personal" / "board.html").unlink()
        other = self.base / "rerendered"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = cli.main(["--from-snapshot", str(self.out / "personal" / "snapshot.json"), "--out", str(other)], gh=failing_gh)
        self.assertEqual(code, 0)
        self.assertTrue((other / "personal" / "board.html").exists())

    def test_snapshot_without_a_tenant_is_refused(self):
        bare = self.base / "bare.json"
        bare.write_text(json.dumps({"schema": 1, "generated_on": "2026-09-26", "sources": {}, "items": [], "findings": {}}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as stderr:
            code = cli.main(["--from-snapshot", str(bare), "--out", str(self.out)], gh=failing_gh)
        self.assertEqual(code, 2)
        self.assertIn("tenant", stderr.getvalue())

    def test_tracker_csv_goes_to_remote_hands_only(self):
        csv_path = self.base / "tracker.csv"
        csv_path.write_text("Task #,Task name,Status\n1,RHMARK invented tracker row,To Do\n", encoding="utf-8")
        self.run_cli("--no-github", "--tracker-csv", str(csv_path))
        self.assertIn("tracker:1", [item["id"] for item in self.snapshot("rh")["items"]])
        self.assertNotIn("tracker:1", [item["id"] for item in self.snapshot("personal")["items"]])

    def test_bad_today_is_a_usage_error(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.run_cli("--no-github", "--today", "2026-02-30")


if __name__ == "__main__":
    unittest.main()
