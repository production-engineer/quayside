import unittest
from datetime import date

from pm import analyze
from pm.model import WorkItem

TODAY = date(2026, 9, 26)


def item(key, **fields):
    source = fields.pop("source", "tasks")
    fields.setdefault("title", f"Invented {key}")
    fields.setdefault("status", "open")
    fields.setdefault("last_activity", TODAY)
    return WorkItem(source=source, id=key, **fields)


def gh(key, **fields):
    fields.setdefault("kind", "issue")
    return item(f"github:{key}", source="github", **fields)


def ids(findings):
    return [finding.id for finding in findings]


def reasons_of(findings, key):
    return next(finding.reasons for finding in findings if finding.id == key)


class NextRanking(unittest.TestCase):
    def test_done_items_never_rank(self):
        result = analyze.analyze([item("a", status="done")], TODAY)
        self.assertEqual(result["next"], [])

    def test_waiting_on_erik_outranks_plain_work(self):
        result = analyze.analyze([item("plain"), item("erik", waiting_on_erik=["needs Erik's go"])], TODAY)
        self.assertEqual(ids(result["next"]), ["erik", "plain"])
        self.assertTrue(any("waiting on Erik" in reason for reason in reasons_of(result["next"], "erik")))

    def test_critical_hint_and_priority_add_score(self):
        result = analyze.analyze([
            item("plain"), item("hint", critical_hints=["top of queue"]), item("critical", priority="critical"),
        ], TODAY)
        self.assertEqual(ids(result["next"])[-1], "plain")
        self.assertEqual(set(ids(result["next"])[:2]), {"hint", "critical"})

    def test_age_adds_capped_score(self):
        old = item("old", last_activity=date(2025, 1, 1))
        week = item("week", last_activity=date(2026, 9, 12))
        result = analyze.analyze([week, old, item("fresh")], TODAY)
        scores = {finding.id: finding.score for finding in result["next"]}
        self.assertEqual(scores["fresh"], 0)
        self.assertEqual(scores["week"], 2)
        self.assertEqual(scores["old"], analyze.AGE_CAP)

    def test_blocked_on_someone_else_sinks(self):
        result = analyze.analyze([item("blocked", blocked_on="an invented vendor"), item("plain")], TODAY)
        self.assertEqual(ids(result["next"]), ["plain", "blocked"])

    def test_blocked_but_waiting_on_erik_is_not_penalized(self):
        result = analyze.analyze([item("mine", blocked_on="a token he has", waiting_on_erik=["needs Erik to hand over"])], TODAY)
        self.assertFalse(any("blocked" in reason for reason in reasons_of(result["next"], "mine")))

    def test_claimed_portal_sinks(self):
        result = analyze.analyze([item("claimed", claimed_by="session invented-07"), item("plain")], TODAY)
        self.assertEqual(ids(result["next"]), ["plain", "claimed"])

    def test_ready_pr_gets_landing_bonus(self):
        result = analyze.analyze([gh("o/r#1", kind="pr", status="review"), gh("o/r#2")], TODAY)
        self.assertEqual(ids(result["next"])[0], "github:o/r#1")

    def test_every_ranked_item_explains_itself(self):
        result = analyze.analyze([item("plain"), item("erik", waiting_on_erik=["x"])], TODAY)
        self.assertTrue(all(finding.reasons for finding in result["next"]))

    def test_looks_done_items_leave_the_next_list(self):
        result = analyze.analyze([item("hinted", done_hints=["Done, verified"])], TODAY)
        self.assertEqual(result["next"], [])
        self.assertEqual(ids(result["looks_done"]), ["hinted"])

    def test_ranking_is_deterministic_on_ties(self):
        items = [item("b"), item("a"), item("c")]
        self.assertEqual(ids(analyze.analyze(items, TODAY)["next"]), ["a", "b", "c"])


class Stuck(unittest.TestCase):
    def test_claimed_work_idle_a_week_is_stuck(self):
        result = analyze.analyze([item("p", status="in_progress", last_activity=date(2026, 9, 19)),
                                  item("q", status="in_progress", last_activity=date(2026, 9, 20))], TODAY)
        self.assertEqual(ids(result["stuck"]), ["p"])

    def test_open_work_stuck_after_three_weeks(self):
        result = analyze.analyze([item("old", last_activity=date(2026, 9, 5)),
                                  item("young", last_activity=date(2026, 9, 6))], TODAY)
        self.assertEqual(ids(result["stuck"]), ["old"])

    def test_no_activity_date_is_stuck(self):
        result = analyze.analyze([item("nodate", last_activity=None)], TODAY)
        self.assertIn("no activity date recorded", reasons_of(result["stuck"], "nodate"))

    def test_stuck_pr_reason_names_the_pr_state(self):
        result = analyze.analyze([gh("o/r#1", kind="pr", status="review", last_activity=date(2026, 9, 1))], TODAY)
        self.assertEqual(reasons_of(result["stuck"], "github:o/r#1"), ["PR open for review with no activity for 25 days"])

    def test_claimed_items_sort_before_merely_old_ones(self):
        result = analyze.analyze([item("ancient", last_activity=date(2024, 1, 1)),
                                  item("claimed", status="review", last_activity=date(2026, 9, 1))], TODAY)
        self.assertEqual(ids(result["stuck"]), ["claimed", "ancient"])

    def test_done_is_never_stuck(self):
        self.assertEqual(analyze.analyze([item("d", status="done", last_activity=None)], TODAY)["stuck"], [])


class LooksDone(unittest.TestCase):
    def test_portal_whose_linked_items_are_all_closed(self):
        items = [item("portal:x", source="portal", refs=["o/r#1", "o/r#2"]),
                 gh("o/r#1", status="done"), gh("o/r#2", kind="pr", status="done")]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["portal:x"])

    def test_one_open_link_keeps_it_open(self):
        items = [item("portal:x", source="portal", refs=["o/r#1", "o/r#2"]),
                 gh("o/r#1", status="done"), gh("o/r#2")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])

    def test_unresolved_links_do_not_count(self):
        items = [item("portal:x", source="portal", refs=["o/r#1", "o/r#9"]), gh("o/r#1", status="done")]
        self.assertEqual(ids(analyze.analyze(items, TODAY)["looks_done"]), ["portal:x"])
        self.assertEqual(analyze.analyze([item("portal:y", source="portal", refs=["o/r#9"])], TODAY)["looks_done"], [])

    def test_open_issue_closed_by_merged_pr(self):
        items = [gh("o/r#3"), gh("o/r#7", kind="pr", status="done", closes=["o/r#3"])]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["github:o/r#3"])
        self.assertTrue(any("o/r#7" in reason for reason in reasons_of(result["looks_done"], "github:o/r#3")))

    def test_open_ticket_linked_from_a_done_portal(self):
        items = [item("portal:x", source="portal", status="done", refs=["o/r#1"]), gh("o/r#1")]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["github:o/r#1"])
        self.assertTrue(any("portal:x" in reason for reason in reasons_of(result["looks_done"], "github:o/r#1")))

    def test_done_items_are_not_reported(self):
        items = [item("portal:x", source="portal", status="done", refs=["o/r#1"]), gh("o/r#1", status="done")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])


class WaitingOnErik(unittest.TestCase):
    def test_lists_open_items_with_wait_signals(self):
        result = analyze.analyze([item("w", waiting_on_erik=["needs Erik's go"]), item("n"),
                                  item("closed", status="done", waiting_on_erik=["x"])], TODAY)
        self.assertEqual(ids(result["waiting_on_erik"]), ["w"])


class QualifyRefs(unittest.TestCase):
    def test_short_refs_resolve_through_the_repo_index(self):
        items = [item("t", refs=["widget#4", "gadget#2", "o/r#1"])]
        repos = {"widget": ["invented-org/widget"], "gadget": ["a/gadget", "b/gadget"]}
        qualified = analyze.qualify_refs(items, repos)
        self.assertEqual(qualified[0].refs, ["invented-org/widget#4", "o/r#1"])

    def test_unresolved_refs_are_the_ones_not_collected(self):
        items = [item("t", refs=["o/r#1", "o/r#2"]), gh("o/r#1")]
        self.assertEqual(analyze.unresolved_refs(items), ["o/r#2"])

    def test_refs_inside_github_bodies_are_not_looked_up(self):
        self.assertEqual(analyze.unresolved_refs([gh("o/r#1", refs=["o/r#5"])]), [])


if __name__ == "__main__":
    unittest.main()
