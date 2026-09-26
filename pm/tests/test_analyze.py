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
        old = item("old", last_activity=date(2026, 7, 1))
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
        result = analyze.analyze([item("ancient", last_activity=date(2026, 7, 1)),
                                  item("claimed", status="review", last_activity=date(2026, 9, 1))], TODAY)
        self.assertEqual(ids(result["stuck"]), ["claimed", "ancient"])

    def test_done_is_never_stuck(self):
        self.assertEqual(analyze.analyze([item("d", status="done", last_activity=None)], TODAY)["stuck"], [])


class LooksDone(unittest.TestCase):
    def test_portal_whose_linked_items_are_all_closed(self):
        items = [item("portal:x", source="portal", status_refs=["o/r#1", "o/r#2"]),
                 gh("o/r#1", status="done"), gh("o/r#2", kind="pr", status="done")]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["portal:x"])

    def test_one_open_link_keeps_it_open(self):
        items = [item("portal:x", source="portal", status_refs=["o/r#1", "o/r#2"]),
                 gh("o/r#1", status="done"), gh("o/r#2")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])

    def test_unresolved_links_do_not_count(self):
        items = [item("portal:x", source="portal", status_refs=["o/r#1", "o/r#9"]), gh("o/r#1", status="done")]
        self.assertEqual(ids(analyze.analyze(items, TODAY)["looks_done"]), ["portal:x"])
        self.assertEqual(analyze.analyze([item("portal:y", source="portal", status_refs=["o/r#9"])], TODAY)["looks_done"], [])

    def test_open_issue_closed_by_merged_pr(self):
        items = [gh("o/r#3"), gh("o/r#7", kind="pr", status="done", closes=["o/r#3"])]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["github:o/r#3"])
        self.assertTrue(any("o/r#7" in reason for reason in reasons_of(result["looks_done"], "github:o/r#3")))

    def test_open_ticket_linked_from_a_done_portal(self):
        items = [item("portal:x", source="portal", status="done", status_refs=["o/r#1"]), gh("o/r#1")]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["github:o/r#1"])
        self.assertTrue(any("portal:x" in reason for reason in reasons_of(result["looks_done"], "github:o/r#1")))

    def test_links_listed_as_done_do_not_make_the_portal_look_done(self):
        items = [item("portal:x", source="portal", status="in_progress", done_refs=["o/r#149"]), gh("o/r#149", status="done")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])

    def test_open_item_listed_as_done_is_a_mismatch(self):
        items = [item("portal:x", source="portal", status="in_progress", done_refs=["o/r#8"]), gh("o/r#8")]
        result = analyze.analyze(items, TODAY)
        self.assertEqual(ids(result["looks_done"]), ["github:o/r#8"])
        self.assertIn("portal:x lists this as done but it is still open", reasons_of(result["looks_done"], "github:o/r#8"))

    def test_done_portal_counts_its_done_links_too(self):
        items = [item("portal:x", source="portal", status="done", done_refs=["o/r#4"]), gh("o/r#4")]
        self.assertEqual(ids(analyze.analyze(items, TODAY)["looks_done"]), ["github:o/r#4"])

    def test_passing_mention_is_not_a_cross_check(self):
        items = [item("portal:x", source="portal", status="done", refs=["o/r#157"]), gh("o/r#157")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])

    def test_done_items_are_not_reported(self):
        items = [item("portal:x", source="portal", status="done", status_refs=["o/r#1"]), gh("o/r#1", status="done")]
        self.assertEqual(analyze.analyze(items, TODAY)["looks_done"], [])


class WaitingOnErik(unittest.TestCase):
    def test_lists_open_items_with_wait_signals(self):
        result = analyze.analyze([item("w", waiting_on_erik=["needs Erik's go"]), item("n"),
                                  item("closed", status="done", waiting_on_erik=["x"])], TODAY)
        self.assertEqual(ids(result["waiting_on_erik"]), ["w"])


class AgentPrs(unittest.TestCase):
    def test_stale_agent_pr_gets_its_own_bucket(self):
        result = analyze.analyze([gh("o/r#1", kind="pr", status="review", agent_authored=True, last_activity=date(2026, 9, 10))], TODAY)
        self.assertEqual(ids(result["agent_prs"]), ["github:o/r#1"])
        self.assertIn("agent-authored PR awaiting a verdict", reasons_of(result["agent_prs"], "github:o/r#1")[0])
        self.assertEqual(result["stuck"], [])
        self.assertEqual(result["waiting_on_erik"], [])

    def test_fresh_agent_pr_is_not_yet_in_the_bucket(self):
        result = analyze.analyze([gh("o/r#1", kind="pr", status="review", agent_authored=True, last_activity=date(2026, 9, 24))], TODAY)
        self.assertEqual(result["agent_prs"], [])

    def test_stale_bot_pr_joins_the_bucket_not_stuck(self):
        result = analyze.analyze([gh("o/r#3", kind="pr", status="review", bot_authored=True, last_activity=date(2026, 8, 1))], TODAY)
        self.assertEqual(ids(result["agent_prs"]), ["github:o/r#3"])
        self.assertIn("bot PR awaiting a verdict", reasons_of(result["agent_prs"], "github:o/r#3")[0])
        self.assertEqual(result["stuck"], [])

    def test_agent_issues_are_not_agent_prs(self):
        result = analyze.analyze([gh("o/r#1", agent_authored=True, last_activity=date(2026, 9, 1))], TODAY)
        self.assertEqual(result["agent_prs"], [])

    def test_oldest_agent_pr_first(self):
        result = analyze.analyze([gh("o/r#1", kind="pr", status="review", agent_authored=True, last_activity=date(2026, 9, 10)),
                                  gh("o/r#2", kind="pr", status="in_progress", agent_authored=True, last_activity=date(2026, 8, 10))], TODAY)
        self.assertEqual(ids(result["agent_prs"]), ["github:o/r#2", "github:o/r#1"])


class ArchiveCandidates(unittest.TestCase):
    def test_items_idle_past_the_archive_age_leave_every_other_bucket(self):
        old = item("old", status="in_progress", last_activity=date(2026, 6, 28), waiting_on_erik=["x"])
        result = analyze.analyze([old], TODAY)
        self.assertEqual(ids(result["archive"]), ["old"])
        for bucket in ("next", "stuck", "waiting_on_erik", "agent_prs", "looks_done"):
            self.assertEqual(result[bucket], [], bucket)
        self.assertIn("idle 90 days", reasons_of(result["archive"], "old")[0])

    def test_one_day_short_of_the_archive_age_stays_active(self):
        result = analyze.analyze([item("young", last_activity=date(2026, 6, 29))], TODAY)
        self.assertEqual(result["archive"], [])
        self.assertEqual(ids(result["stuck"]), ["young"])

    def test_archive_age_is_configurable(self):
        result = analyze.analyze([item("a", last_activity=date(2026, 9, 1))], TODAY, archive_days=20)
        self.assertEqual(ids(result["archive"]), ["a"])

    def test_undated_items_are_not_archived(self):
        result = analyze.analyze([item("nodate", last_activity=None)], TODAY)
        self.assertEqual(result["archive"], [])

    def test_done_items_are_not_archived(self):
        self.assertEqual(analyze.analyze([item("d", status="done", last_activity=date(2020, 1, 1))], TODAY)["archive"], [])

    def test_oldest_first(self):
        result = analyze.analyze([item("a", last_activity=date(2026, 1, 1)), item("b", last_activity=date(2024, 1, 1))], TODAY)
        self.assertEqual(ids(result["archive"]), ["b", "a"])


class QualifyRefs(unittest.TestCase):
    def test_short_refs_resolve_through_the_repo_index(self):
        items = [item("t", refs=["widget#4", "gadget#2", "o/r#1"])]
        repos = {"widget": ["invented-org/widget"], "gadget": ["a/gadget", "b/gadget"]}
        qualified = analyze.qualify_refs(items, repos)
        self.assertEqual(qualified[0].refs, ["invented-org/widget#4", "o/r#1"])

    def test_unresolved_refs_are_the_ones_not_collected(self):
        items = [item("t", status_refs=["o/r#1", "o/r#2"], done_refs=["o/r#4"], refs=["o/r#3"]), gh("o/r#1")]
        self.assertEqual(analyze.unresolved_refs(items), ["o/r#2", "o/r#4"])

    def test_refs_inside_github_bodies_are_not_looked_up(self):
        self.assertEqual(analyze.unresolved_refs([gh("o/r#1", status_refs=["o/r#5"])]), [])

    def test_status_refs_are_qualified_too(self):
        qualified = analyze.qualify_refs([item("t", status_refs=["widget#4"], done_refs=["widget#5"])], {"widget": ["invented-org/widget"]})
        self.assertEqual(qualified[0].status_refs, ["invented-org/widget#4"])
        self.assertEqual(qualified[0].done_refs, ["invented-org/widget#5"])


if __name__ == "__main__":
    unittest.main()
