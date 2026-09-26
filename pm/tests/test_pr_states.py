import json
import unittest
from datetime import date

from pm import verdicts
from pm.sources import github


def pr_node(number, mergeable="MERGEABLE", state="CLEAN", checks=(("Unit tests", "SUCCESS", "COMPLETED"),), draft=False,
            files=("src/invented.py",), title="Invented PR"):
    contexts = [{"__typename": "CheckRun", "name": name, "conclusion": conclusion, "status": status}
                for name, conclusion, status in checks]
    return {
        "number": number, "title": title, "url": f"https://github.com/invented-org/widget/pull/{number}",
        "isDraft": draft, "mergeable": mergeable, "mergeStateStatus": state, "reviewDecision": None,
        "createdAt": "2026-08-01T20:00:00Z", "author": {"login": "invented-erik"},
        "files": {"nodes": [{"path": path} for path in files]},
        "commits": {"nodes": [{"commit": {"committedDate": "2026-08-02T20:00:00Z",
                                          "statusCheckRollup": {"state": "SUCCESS", "contexts": {"nodes": contexts}} if checks else None}}]},
    }


def merged_nodes():
    return {"nodes": [{"number": 9, "title": "Invented merged", "url": "https://github.com/invented-org/widget/pull/9",
                       "mergedAt": "2026-09-01T20:00:00Z", "files": {"nodes": [{"path": "src/invented.py"}]}}]}


class FakeGraphql:
    def __init__(self, responses=None, fail=False):
        self.responses = responses or []
        self.fail = fail
        self.queries = []

    def __call__(self, args):
        query = next(value[6:] for value in args if value.startswith("query="))
        self.queries.append(query)
        if self.fail:
            raise github.GhFailure("invented outage")
        return json.dumps(self.responses[len(self.queries) - 1])


class PrStates(unittest.TestCase):
    def setUp(self):
        self.sleeps = []

    def fetch(self, fake, keys):
        return github.pr_states(fake, keys, sleep=self.sleeps.append)

    def test_one_aliased_query_covers_every_repo(self):
        fake = FakeGraphql([{"data": {
            "r0": {"p5": pr_node(5), "p6": pr_node(6, draft=True, state="DRAFT"), "merged": merged_nodes()},
            "r1": {"p7": pr_node(7), "merged": {"nodes": []}},
        }}])
        states, recent, errors = self.fetch(fake, ["invented-org/widget#5", "invented-org/widget#6", "invented-co/gadget.js#7"])
        self.assertEqual(errors, [])
        self.assertEqual(len(fake.queries), 1)
        self.assertIn('repository(owner: "invented-org", name: "widget")', fake.queries[0])
        self.assertIn('repository(owner: "invented-co", name: "gadget.js")', fake.queries[0])
        for field in ("mergeable", "mergeStateStatus", "statusCheckRollup", "reviewDecision", "isDraft", "files(first: 100)"):
            self.assertIn(field, fake.queries[0])
        self.assertEqual(sorted(states), ["invented-co/gadget.js#7", "invented-org/widget#5", "invented-org/widget#6"])
        state = states["invented-org/widget#5"]
        self.assertEqual((state.mergeable, state.merge_state, state.has_checks, state.files),
                         ("MERGEABLE", "CLEAN", True, ["src/invented.py"]))
        self.assertTrue(states["invented-org/widget#6"].is_draft)
        self.assertEqual(recent["invented-org/widget"][0].key, "invented-org/widget#9")
        self.assertEqual(recent["invented-org/widget"][0].merged_on, date(2026, 9, 1))

    def test_failing_and_pending_checks_are_named(self):
        node = pr_node(5, checks=(("Deploy Preview", "FAILURE", "COMPLETED"), ("Lint", "SUCCESS", "COMPLETED"),
                                  ("Slow", None, "IN_PROGRESS"), ("Skipped", "SKIPPED", "COMPLETED")))
        node["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"].append(
            {"__typename": "StatusContext", "context": "Vercel", "state": "ERROR"})
        fake = FakeGraphql([{"data": {"r0": {"p5": node, "merged": {"nodes": []}}}}])
        state = self.fetch(fake, ["invented-org/widget#5"])[0]["invented-org/widget#5"]
        self.assertEqual(state.failing_checks, ["Deploy Preview", "Vercel"])
        self.assertEqual(state.pending_checks, ["Slow"])

    def test_no_rollup_means_no_checks(self):
        fake = FakeGraphql([{"data": {"r0": {"p5": pr_node(5, checks=()), "merged": {"nodes": []}}}}])
        self.assertFalse(self.fetch(fake, ["invented-org/widget#5"])[0]["invented-org/widget#5"].has_checks)

    def test_unknown_mergeable_is_refetched_once_after_a_delay(self):
        fake = FakeGraphql([
            {"data": {"r0": {"p5": pr_node(5, mergeable="UNKNOWN", state="UNKNOWN"), "p6": pr_node(6), "merged": {"nodes": []}}}},
            {"data": {"r0": {"p5": pr_node(5), "merged": {"nodes": []}}}},
        ])
        states, _, _ = self.fetch(fake, ["invented-org/widget#5", "invented-org/widget#6"])
        self.assertEqual(len(fake.queries), 2)
        self.assertEqual(self.sleeps, [github.UNKNOWN_RETRY_SECONDS])
        self.assertIn("p5:", fake.queries[1])
        self.assertNotIn("p6:", fake.queries[1])
        self.assertEqual(states["invented-org/widget#5"].mergeable, "MERGEABLE")

    def test_still_unknown_after_the_refetch_stays_unknown(self):
        unknown = {"data": {"r0": {"p5": pr_node(5, mergeable="UNKNOWN", state="UNKNOWN"), "merged": {"nodes": []}}}}
        fake = FakeGraphql([unknown, unknown])
        states, _, _ = self.fetch(fake, ["invented-org/widget#5"])
        self.assertEqual(len(fake.queries), 2)
        self.assertEqual(verdicts.verdict_of(states["invented-org/widget#5"], [])[0], verdicts.UNKNOWN)

    def test_large_sets_are_chunked(self):
        keys = [f"invented-org/widget#{number}" for number in range(1, github.PRS_PER_QUERY + 2)]
        first = {"data": {"r0": {**{f"p{n}": pr_node(n) for n in range(1, github.PRS_PER_QUERY + 1)}, "merged": {"nodes": []}}}}
        second = {"data": {"r0": {f"p{github.PRS_PER_QUERY + 1}": pr_node(github.PRS_PER_QUERY + 1), "merged": {"nodes": []}}}}
        fake = FakeGraphql([first, second])
        states, _, _ = self.fetch(fake, keys)
        self.assertEqual(len(fake.queries), 2)
        self.assertEqual(len(states), github.PRS_PER_QUERY + 1)

    def test_a_failing_chunk_is_split_and_retried(self):
        class FlakyOnPairs(FakeGraphql):
            def __call__(self, args):
                query = next(value[6:] for value in args if value.startswith("query="))
                self.queries.append(query)
                if query.count("pullRequest(number:") > 1:
                    raise github.GhFailure("gh: HTTP 502")
                number = 5 if "p5:" in query else 6
                return json.dumps({"data": {"r0": {f"p{number}": pr_node(number), "merged": {"nodes": []}}}})

        fake = FlakyOnPairs()
        states, _, errors = self.fetch(fake, ["invented-org/widget#5", "invented-org/widget#6"])
        self.assertEqual(sorted(states), ["invented-org/widget#5", "invented-org/widget#6"])
        self.assertEqual(errors, [])
        self.assertEqual(len(fake.queries), 3)

    def test_gh_failure_is_an_error_not_a_crash(self):
        states, recent, errors = self.fetch(FakeGraphql(fail=True), ["invented-org/widget#5"])
        self.assertEqual((states, recent), ({}, {}))
        self.assertTrue(any("invented outage" in error for error in errors))

    def test_missing_pr_in_the_response_is_skipped(self):
        fake = FakeGraphql([{"data": {"r0": {"p5": None, "merged": {"nodes": []}}}}])
        self.assertEqual(self.fetch(fake, ["invented-org/widget#5"])[0], {})

    def test_malformed_keys_are_ignored(self):
        fake = FakeGraphql([])
        self.assertEqual(self.fetch(fake, ["not a key"]), ({}, {}, []))
        self.assertEqual(fake.queries, [])


if __name__ == "__main__":
    unittest.main()
