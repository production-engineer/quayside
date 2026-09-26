import json
import unittest
from datetime import date

from pm.sources import github

VIEWER = "invented-erik"


def issue(number, title, **extra):
    node = {
        "__typename": "Issue", "number": number, "title": title,
        "url": f"https://github.com/invented-org/widget/issues/{number}", "state": "OPEN",
        "createdAt": "2026-09-01T20:00:00Z", "updatedAt": "2026-09-10T20:00:00Z", "closedAt": None,
        "body": "", "repository": {"nameWithOwner": "invented-org/widget"}, "author": {"login": "invented-dana"},
        "assignees": {"nodes": []}, "labels": {"nodes": []},
    }
    node.update(extra)
    return node


def pull(number, title, **extra):
    node = issue(number, title, url=f"https://github.com/invented-org/widget/pull/{number}")
    node.update({"__typename": "PullRequest", "isDraft": False, "mergedAt": None,
                 "reviewRequests": {"nodes": []}, "author": {"login": VIEWER}})
    node.update(extra)
    return node


def page(nodes, has_next=False, cursor=None, count=None):
    return json.dumps({"data": {"search": {
        "issueCount": len(nodes) if count is None else count,
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}, "nodes": nodes}}})


def query_of(args):
    for value in args:
        if value.startswith("q="):
            return value[2:]
    return ""


def after_of(args):
    for value in args:
        if value.startswith("after="):
            return value[6:]
    return None


class FakeGh:
    def __init__(self, searches=None, fail_on=(), orgs=("invented-org",)):
        self.searches = searches or {}
        self.fail_on = fail_on
        self.orgs = orgs
        self.calls = []

    def __call__(self, args):
        self.calls.append(args)
        if args[:2] == ["api", "user"]:
            return VIEWER + "\n"
        if args[:2] == ["api", "user/orgs"]:
            return "\n".join(self.orgs) + "\n"
        if args[:2] == ["repo", "list"]:
            owner = args[2]
            return json.dumps([{"nameWithOwner": f"{owner}/widget"}, {"nameWithOwner": f"{owner}/gadget"}])
        if args[:2] == ["api", "graphql"]:
            query = query_of(args)
            for needle in self.fail_on:
                if needle in query:
                    raise github.GhFailure(f"invented failure for {needle}")
            for needle, pages in self.searches.items():
                if needle in query:
                    cursor = after_of(args)
                    return pages[int(cursor) if cursor else 0]
            return page([])
        if args[0] == "api" and args[1].startswith("repos/"):
            if args[1].endswith("/404"):
                raise github.GhFailure("HTTP 404: Not Found")
            return json.dumps({"number": 8, "title": "Invented looked up", "state": "closed",
                               "html_url": "https://github.com/invented-org/widget/pull/8",
                               "created_at": "2026-08-01T20:00:00Z", "updated_at": "2026-08-05T20:00:00Z",
                               "closed_at": "2026-08-05T20:00:00Z",
                               "pull_request": {"merged_at": "2026-08-05T20:00:00Z"}})
        raise AssertionError(f"unexpected gh call {args}")


def collect(fake, **kwargs):
    kwargs.setdefault("owners", ["invented-org"])
    return github.collect(fake, since=date(2026, 9, 12), **kwargs)


class GithubAdapter(unittest.TestCase):
    def test_open_issue_normalizes(self):
        fake = FakeGh({"is:issue is:open": [page([issue(3, "Invented ünïcödé 北极 bug", assignees={"nodes": [{"login": "invented-dana"}]},
                                                          labels={"nodes": [{"name": "priority: high"}, {"name": "blocked"}]})])]})
        result = collect(fake)
        self.assertEqual(result.errors, [])
        item = result.items[0]
        self.assertEqual(item.id, "github:invented-org/widget#3")
        self.assertEqual(item.title, "Invented ünïcödé 北极 bug")
        self.assertEqual((item.kind, item.status, item.owner, item.project), ("issue", "open", "invented-dana", "invented-org/widget"))
        self.assertEqual((item.created, item.last_activity), (date(2026, 9, 1), date(2026, 9, 10)))
        self.assertEqual(item.priority, "high")
        self.assertEqual(item.blocked_on, "label: blocked")
        self.assertEqual(item.links, ["https://github.com/invented-org/widget/issues/3"])

    def test_unblocked_label_is_not_blocked(self):
        fake = FakeGh({"is:issue is:open": [page([issue(3, "Invented", labels={"nodes": [{"name": "unblocked"}, {"name": "not-blocked"}]})])]})
        self.assertIsNone(collect(fake).items[0].blocked_on)

    def test_highest_pure_priority_label_wins(self):
        fake = FakeGh({"is:issue is:open": [page([
            issue(3, "Invented", labels={"nodes": [{"name": "P0"}, {"name": "low-hanging-fruit"}]}),
            issue(4, "Invented", labels={"nodes": [{"name": "high-impact"}, {"name": "medium-effort"}]}),
            issue(5, "Invented", labels={"nodes": [{"name": "priority: low"}, {"name": "priority/high"}]}),
        ])]})
        priorities = [item.priority for item in collect(fake).items]
        self.assertEqual(priorities, ["critical", None, "high"])

    def test_pull_request_states(self):
        fake = FakeGh({"is:pr is:open": [page([pull(5, "Invented ready"), pull(6, "Invented draft", isDraft=True)])],
                       "is:merged": [page([pull(7, "Invented merged", state="MERGED", mergedAt="2026-09-20T20:00:00Z",
                                                body="Closes #3 and fixes invented-org/gadget#2")])]})
        items = {item.id: item for item in collect(fake).items}
        self.assertEqual(items["github:invented-org/widget#5"].status, "review")
        self.assertEqual(items["github:invented-org/widget#6"].status, "in_progress")
        merged = items["github:invented-org/widget#7"]
        self.assertEqual(merged.status, "done")
        self.assertEqual(merged.closes, ["invented-org/gadget#2", "invented-org/widget#3"])
        self.assertEqual(merged.closed_on, date(2026, 9, 20))
        self.assertIsNone(items["github:invented-org/widget#5"].closed_on)

    def test_waiting_on_erik_signals(self):
        fake = FakeGh({"is:pr is:open": [page([
            pull(5, "Invented own ready PR"),
            pull(6, "Invented own draft", isDraft=True),
            pull(9, "Invented review ask", author={"login": "invented-dana"},
                 reviewRequests={"nodes": [{"requestedReviewer": {"login": VIEWER}}]}),
            pull(10, "Invented bot bump", author={"login": "dependabot"}),
        ])], "is:issue is:open": [page([issue(11, "Invented question", body="This needs Erik's call on scope.")])]})
        items = {item.id: item for item in collect(fake).items}
        self.assertEqual(items["github:invented-org/widget#5"].waiting_on_erik, [])
        self.assertEqual(items["github:invented-org/widget#6"].waiting_on_erik, [])
        self.assertEqual(items["github:invented-org/widget#9"].waiting_on_erik, ["review requested from you"])
        self.assertEqual(items["github:invented-org/widget#10"].waiting_on_erik, [])
        self.assertTrue(items["github:invented-org/widget#11"].waiting_on_erik)

    def test_agent_marker_in_pr_body_marks_agent_authorship(self):
        fake = FakeGh({"is:pr is:open": [page([pull(5, "Invented agent PR", body="Did it.\n\n🤖 Generated with [Claude Code](https://claude.com/claude-code)")])]})
        item = collect(fake).items[0]
        self.assertTrue(item.agent_authored)
        self.assertEqual(item.waiting_on_erik, [])

    def test_agent_marker_in_head_commit_marks_agent_authorship(self):
        fake = FakeGh({"is:pr is:open": [page([pull(5, "Invented", commits={"nodes": [{"commit": {"message": "Fix\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"}}]})])]})
        self.assertTrue(collect(fake).items[0].agent_authored)

    def test_agent_marker_in_issue_body(self):
        fake = FakeGh({"is:issue is:open": [page([issue(3, "Invented", body="Co-authored-by: Claude")])]})
        self.assertTrue(collect(fake).items[0].agent_authored)

    def test_bot_pr_is_bot_authored(self):
        fake = FakeGh({"is:pr is:open": [page([pull(10, "Invented bump", author={"login": "dependabot"})])]})
        item = collect(fake).items[0]
        self.assertTrue(item.bot_authored)
        self.assertFalse(item.agent_authored)

    def test_plain_pr_is_not_agent_authored(self):
        fake = FakeGh({"is:pr is:open": [page([pull(5, "Invented human PR", body="Handwritten.")])]})
        self.assertFalse(collect(fake).items[0].agent_authored)

    def test_someone_elses_ready_pr_in_your_own_repo_waits_on_you(self):
        fake = FakeGh({"is:pr is:open": [page([
            pull(5, "Invented contribution", author={"login": "invented-dana"}, repository={"nameWithOwner": f"{VIEWER}/tool"},
                 url=f"https://github.com/{VIEWER}/tool/pull/5"),
            pull(6, "Invented org PR", author={"login": "invented-dana"}),
        ])]})
        items = {item.id: item for item in collect(fake).items}
        self.assertEqual(items[f"github:{VIEWER}/tool#5"].waiting_on_erik, ["ready PR in your repo awaiting your merge"])
        self.assertEqual(items["github:invented-org/widget#6"].waiting_on_erik, [])

    def test_review_request_waits_even_on_agent_prs(self):
        fake = FakeGh({"is:pr is:open": [page([pull(9, "Invented", body="Co-Authored-By: Claude",
                                                   reviewRequests={"nodes": [{"requestedReviewer": {"login": VIEWER}}]})])]})
        self.assertEqual(collect(fake).items[0].waiting_on_erik, ["review requested from you"])

    def test_search_asks_for_the_head_commit_message(self):
        self.assertIn("commits(last: 1)", github.SEARCH_QUERY)

    def test_bodies_are_not_stored(self):
        fake = FakeGh({"is:issue is:open": [page([issue(11, "Invented", body="invented secret-looking body text")])]})
        snapshot_text = json.dumps([item.to_dict() for item in collect(fake).items])
        self.assertNotIn("secret-looking", snapshot_text)

    def test_paginates_until_done(self):
        fake = FakeGh({"is:issue is:open": [page([issue(1, "Invented one")], has_next=True, cursor="1", count=2),
                                            page([issue(2, "Invented two")], count=2)]})
        self.assertEqual(len(collect(fake).items), 2)

    def test_truncated_search_is_reported(self):
        fake = FakeGh({"is:issue is:open": [page([issue(1, "Invented one")], has_next=True, cursor="1", count=5000)] * 3})
        result = collect(fake, max_pages=2)
        self.assertTrue(any("5000" in error for error in result.errors))

    def test_zero_pages_fetches_nothing_without_crashing(self):
        fake = FakeGh({"is:issue is:open": [page([issue(1, "Invented one")], has_next=True, cursor="1", count=9)]})
        result = collect(fake, max_pages=0)
        self.assertEqual(result.items, [])

    def test_excluded_repos_are_in_the_query(self):
        fake = FakeGh()
        collect(fake, exclude=["invented-org/frozen"])
        queries = [query_of(call) for call in fake.calls if call[:2] == ["api", "graphql"]]
        self.assertTrue(queries)
        self.assertTrue(all("-repo:invented-org/frozen" in query for query in queries))

    def test_owners_are_discovered_when_not_given(self):
        fake = FakeGh(orgs=("invented-org", "invented-co"))
        result = github.collect(fake, since=date(2026, 9, 12))
        self.assertEqual(result.owners, [VIEWER, "invented-co", "invented-org"])

    def test_repo_index_maps_names_to_owners(self):
        result = collect(FakeGh())
        self.assertEqual(result.repos["widget"], ["invented-org/widget"])

    def test_one_failing_query_does_not_sink_the_rest(self):
        fake = FakeGh({"is:pr is:open": [page([pull(5, "Invented ready")])]}, fail_on=["is:issue is:open"])
        result = collect(fake)
        self.assertEqual([item.id for item in result.items], ["github:invented-org/widget#5"])
        self.assertTrue(any("invented failure" in error for error in result.errors))

    def test_missing_gh_binary_is_one_error(self):
        def absent(args):
            raise github.GhFailure("gh not found")
        result = github.collect(absent, since=date(2026, 9, 12))
        self.assertEqual(result.items, [])
        self.assertEqual(len(result.errors), 1)

    def test_malformed_json_is_an_error(self):
        fake = FakeGh({"is:issue is:open": ["{not json"]})
        result = collect(fake)
        self.assertTrue(result.errors)

    def test_graphql_error_payload_is_an_error(self):
        fake = FakeGh({"is:issue is:open": [json.dumps({"errors": [{"message": "invented rate limit"}]})]})
        self.assertTrue(any("invented rate limit" in error for error in collect(fake).errors))

    def test_lookup_fetches_items_outside_the_search_window(self):
        items, errors = github.lookup(FakeGh(), ["invented-org/widget#8", "invented-org/widget#404"], viewer=VIEWER)
        self.assertEqual([(item.id, item.kind, item.status, item.closed_on) for item in items],
                         [("github:invented-org/widget#8", "pr", "done", date(2026, 8, 5))])
        self.assertIn("merged", items[0].evidence[0])
        self.assertEqual(len(errors), 1)

    def test_lookup_ignores_malformed_keys(self):
        items, errors = github.lookup(FakeGh(), ["widget#8", "not a ref"], viewer=VIEWER)
        self.assertEqual((items, errors), ([], []))


class DefaultRunner(unittest.TestCase):
    def test_nonzero_exit_raises_gh_failure(self):
        with self.assertRaises(github.GhFailure):
            github.run_command(["python3", "-c", "import sys; sys.exit(3)"])

    def test_missing_binary_raises_gh_failure(self):
        with self.assertRaises(github.GhFailure):
            github.run_command(["invented-binary-that-does-not-exist"])


if __name__ == "__main__":
    unittest.main()
