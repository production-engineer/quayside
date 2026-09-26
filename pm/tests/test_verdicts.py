import unittest
from dataclasses import replace
from datetime import date

from pm import verdicts
from pm.verdicts import MergedPr, PrState

READY = PrState(key="invented-org/widget#5", title="Invented: restore nine widgets that were replaced with dead links",
                url="https://github.com/invented-org/widget/pull/5", is_draft=False, mergeable="MERGEABLE",
                merge_state="CLEAN", review_decision=None, failing_checks=[], pending_checks=[], has_checks=True,
                files=["src/widgets/restore.py", "package.json"], bot=False, created=date(2026, 8, 1),
                last_commit=date(2026, 8, 2))


def merged(title=READY.title, files=("src/widgets/restore.py",), merged_on=date(2026, 9, 1), key="invented-org/widget#9"):
    return MergedPr(key=key, title=title, url=f"https://github.com/{key.replace('#', '/pull/')}", merged_on=merged_on, files=list(files))


class Verdicts(unittest.TestCase):
    def verdict(self, pr, recent=()):
        return verdicts.verdict_of(pr, list(recent))

    def test_green_and_mergeable_is_merge_ready(self):
        verdict, evidence = self.verdict(READY)
        self.assertEqual(verdict, verdicts.MERGE_READY)
        self.assertIn("CI green", evidence)

    def test_no_ci_configured_is_still_merge_ready(self):
        verdict, evidence = self.verdict(replace(READY, has_checks=False))
        self.assertEqual(verdict, verdicts.MERGE_READY)
        self.assertIn("no CI checks configured", evidence)

    def test_conflicts_need_a_rebase(self):
        self.assertEqual(self.verdict(replace(READY, mergeable="CONFLICTING", merge_state="DIRTY"))[0], verdicts.NEEDS_REBASE)

    def test_behind_base_needs_a_rebase(self):
        verdict, evidence = self.verdict(replace(READY, merge_state="BEHIND"))
        self.assertEqual(verdict, verdicts.NEEDS_REBASE)
        self.assertIn("behind", evidence)

    def test_failing_checks_are_broken_and_named(self):
        verdict, evidence = self.verdict(replace(READY, failing_checks=["Deploy Preview", "Build"], merge_state="BEHIND"))
        self.assertEqual(verdict, verdicts.BROKEN)
        self.assertIn("Deploy Preview", evidence)
        self.assertIn("Build", evidence)

    def test_draft_is_a_stale_decision(self):
        verdict, evidence = self.verdict(replace(READY, is_draft=True, merge_state="DRAFT"))
        self.assertEqual(verdict, verdicts.STALE_DECISION)
        self.assertIn("2026-08-02", evidence)

    def test_changes_requested_is_a_stale_decision(self):
        self.assertEqual(self.verdict(replace(READY, review_decision="CHANGES_REQUESTED"))[0], verdicts.STALE_DECISION)

    def test_protected_branch_waiting_for_review_is_a_stale_decision(self):
        self.assertEqual(self.verdict(replace(READY, merge_state="BLOCKED", review_decision="REVIEW_REQUIRED"))[0],
                         verdicts.STALE_DECISION)

    def test_bot_prs_are_dependency_bumps_whatever_the_ci(self):
        green, green_evidence = self.verdict(replace(READY, bot=True))
        red, red_evidence = self.verdict(replace(READY, bot=True, failing_checks=["Type Check"]))
        self.assertEqual((green, red), (verdicts.DEPENDENCY_BUMP, verdicts.DEPENDENCY_BUMP))
        self.assertIn("merge", green_evidence)
        self.assertIn("Type Check", red_evidence)

    def test_unknown_mergeable_is_unknown(self):
        verdict, evidence = self.verdict(replace(READY, mergeable="UNKNOWN", merge_state="UNKNOWN"))
        self.assertEqual(verdict, verdicts.UNKNOWN)
        self.assertIn("UNKNOWN", evidence)

    def test_pending_checks_are_unknown(self):
        verdict, evidence = self.verdict(replace(READY, pending_checks=["Unit tests"]))
        self.assertEqual(verdict, verdicts.UNKNOWN)
        self.assertIn("Unit tests", evidence)

    def test_every_verdict_has_a_suggested_action(self):
        self.assertEqual(set(verdicts.ACTIONS), set(verdicts.ORDER))


class Supersession(unittest.TestCase):
    def verdict(self, pr, recent):
        return verdicts.verdict_of(pr, list(recent))

    def test_similar_title_and_shared_real_file_is_superseded(self):
        verdict, evidence = self.verdict(READY, [merged(title="Invented: restore nine widgets that are dead links on main, and add the sweep")])
        self.assertEqual(verdict, verdicts.SUPERSEDED)
        self.assertIn("invented-org/widget#9", evidence)

    def test_overlap_only_on_common_files_is_not_superseded(self):
        pr = replace(READY, files=["package.json", "vercel.json", ".github/workflows/ci.yml", "package-lock.json"])
        recent = [merged(files=["package.json", "vercel.json", ".github/workflows/ci.yml"])]
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.MERGE_READY)

    def test_common_files_do_not_count_toward_coverage(self):
        pr = replace(READY, files=["src/widgets/restore.py", "src/widgets/sweep.py", "src/widgets/list.py", "package.json", "vercel.json"])
        recent = [merged(files=["src/widgets/restore.py", "package.json", "vercel.json"])]
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.MERGE_READY)

    def test_shared_file_with_an_unrelated_title_is_not_superseded(self):
        recent = [merged(title="Invented: bump the billing gadget and fix tax rounding")]
        self.assertEqual(self.verdict(READY, recent)[0], verdicts.MERGE_READY)

    def test_merge_before_the_pr_was_opened_is_not_superseded(self):
        self.assertEqual(self.verdict(READY, [merged(merged_on=date(2026, 7, 1))])[0], verdicts.MERGE_READY)

    def test_an_earlier_stacked_pr_merging_later_does_not_supersede(self):
        pr = replace(READY, key="invented-org/widget#11", title="Invented rh-dev 0.5.0: widget review runs as a gate")
        recent = [merged(key="invented-org/widget#10", title="Invented rh-dev 0.4.0: widget review, the gate that runs")]
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.MERGE_READY)

    def test_near_total_overlap_on_many_files_accepts_a_looser_title(self):
        files = ["skills/a.md", "skills/b.md", "skills/c.md", "package.json"]
        pr = replace(READY, title="Invented restore nine widgets that the importer replaced with dead links", files=files)
        recent = [merged(title="Invented restore nine widgets that are dead links on main, add the sweep that catches them", files=files[:3])]
        self.assertLess(verdicts.title_similarity(pr.title, recent[0].title), verdicts.TITLE_SIMILARITY)
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.SUPERSEDED)

    def test_near_total_overlap_on_few_files_still_needs_the_normal_title_bar(self):
        files = ["skills/a.md", "skills/b.md"]
        pr = replace(READY, title="Invented restore nine widgets that the importer replaced with dead links", files=files)
        recent = [merged(title="Invented restore nine widgets that are dead links on main, add the sweep that catches them", files=files)]
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.MERGE_READY)

    def test_full_file_overlap_with_an_unrelated_title_is_not_superseded(self):
        files = ["skills/a.md", "skills/b.md", "skills/c.md"]
        pr = replace(READY, title="Invented coherence audit: stale claims and rebrand leftovers", files=files)
        recent = [merged(title="Invented remove old branding; docs link to pricing", files=files)]
        self.assertEqual(self.verdict(pr, recent)[0], verdicts.MERGE_READY)

    def test_a_pr_never_supersedes_itself(self):
        self.assertEqual(self.verdict(READY, [merged(key=READY.key)])[0], verdicts.MERGE_READY)

    def test_pr_with_only_common_files_is_never_superseded(self):
        pr = replace(READY, files=["package.json"])
        self.assertEqual(self.verdict(pr, [merged(files=["package.json"])])[0], verdicts.MERGE_READY)

    def test_title_similarity_ignores_case_and_punctuation(self):
        self.assertGreaterEqual(verdicts.title_similarity("Invented: Restore widgets!", "invented restore widgets"), 0.99)
        self.assertLess(verdicts.title_similarity("Invented: restore widgets", "Invented: bump gadget tax"), verdicts.TITLE_SIMILARITY)


if __name__ == "__main__":
    unittest.main()
