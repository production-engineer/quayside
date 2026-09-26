import unittest
from datetime import date

from pm import signals


class FindRefs(unittest.TestCase):
    def test_github_urls_become_qualified_refs(self):
        text = "See https://github.com/Invented-Org/widget/pull/12 and https://github.com/invented-org/widget/issues/7."
        self.assertEqual(signals.find_refs(text), ["invented-org/widget#12", "invented-org/widget#7"])

    def test_qualified_shorthand(self):
        self.assertEqual(signals.find_refs("tracked in invented-org/widget#5"), ["invented-org/widget#5"])

    def test_qualified_with_pr_word(self):
        self.assertEqual(signals.find_refs("recorded in Invented-Org/widget-docs PR #2"), ["invented-org/widget-docs#2"])

    def test_short_refs_keep_repo_name_only(self):
        self.assertEqual(signals.find_refs("shipped in widget#149 and gadget#59"), ["gadget#59", "widget#149"])

    def test_bare_hash_numbers_are_ignored(self):
        self.assertEqual(signals.find_refs("PR #73 and task #4"), [])

    def test_no_text_is_no_refs(self):
        self.assertEqual(signals.find_refs(""), [])


class FindLinks(unittest.TestCase):
    def test_strips_trailing_punctuation(self):
        self.assertEqual(signals.find_links("go to https://example.com/a, then (https://example.com/b)."),
                         ["https://example.com/a", "https://example.com/b"])

    def test_ignores_non_http_schemes(self):
        self.assertEqual(signals.find_links("javascript:alert(1) ftp://example.com"), [])


class ErikWaits(unittest.TestCase):
    def test_matches_direct_phrasings(self):
        for text in ("This needs Erik's go before merge.", "Waiting on Erik for the token.",
                     "Ask Erik whether this is still needed.", "Decide with Erik how to notify.",
                     "Erik's call before Slice 2."):
            with self.subTest(text=text):
                self.assertTrue(signals.erik_waits(text))

    def test_granted_approval_is_not_a_wait(self):
        self.assertEqual(signals.erik_waits("Re-claimed with Erik's go. Executed by a subagent."), [])

    def test_granted_approval_with_trailing_words_is_not_a_wait(self):
        self.assertEqual(signals.erik_waits("Merged with Erik's go at 14:00."), [])
        self.assertEqual(signals.erik_waits("Shipped with Erik's approval on 2026-09-20."), [])

    def test_other_names_do_not_match(self):
        self.assertEqual(signals.erik_waits("Waiting on Dana for the token."), [])

    def test_custom_name(self):
        self.assertTrue(signals.erik_waits("Waiting on Dana for the token.", name="Dana"))

    def test_evidence_is_a_short_snippet(self):
        text = "x " * 400 + "needs Erik's review" + " y" * 400
        snippets = signals.erik_waits(text)
        self.assertEqual(len(snippets), 1)
        self.assertIn("needs Erik's review", snippets[0])
        self.assertLess(len(snippets[0]), 200)

    def test_snippet_does_not_cut_words(self):
        text = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo " * 3 + "needs Erik's go" + " lima mike november oscar papa quebec romeo sierra tango" * 3
        snippet = signals.erik_waits(text)[0]
        words = set(text.split())
        self.assertIn(snippet.split()[0], words)
        self.assertIn(snippet.split()[-1], words)


class CriticalHints(unittest.TestCase):
    def test_matches_queue_and_path_language(self):
        self.assertTrue(signals.critical_hints("Top of queue: this is the next thing to pick up."))
        self.assertTrue(signals.critical_hints("It is on the critical path."))

    def test_negated_urgency_is_not_a_hint(self):
        self.assertEqual(signals.critical_hints("I don't think any are urgent right now."), [])

    def test_plain_text_has_no_hints(self):
        self.assertEqual(signals.critical_hints("A routine invented chore."), [])


class BlockedOn(unittest.TestCase):
    def test_blocked_on_phrase(self):
        self.assertEqual(signals.blocked_on("It is blocked on an invented token. More text."), "an invented token")

    def test_depends_on_phrase(self):
        self.assertEqual(signals.blocked_on("Depends on the task 4 inventory; more."), "the task 4 inventory")

    def test_not_blocked_is_not_blocked(self):
        self.assertIsNone(signals.blocked_on("This is not blocked on anything."))

    def test_unblocked_word_is_not_blocked(self):
        self.assertIsNone(signals.blocked_on("Everything is unblocked now."))


class DatesInText(unittest.TestCase):
    def test_finds_valid_days_only(self):
        self.assertEqual(signals.dates_in("Claimed 2026-09-26, earlier 2026-02-30, then 2026-09-14."),
                         [date(2026, 9, 26), date(2026, 9, 14)])


if __name__ == "__main__":
    unittest.main()
