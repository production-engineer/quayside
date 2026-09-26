import json
import stat
import tempfile
import unittest
from pathlib import Path

from pm import memory


def snapshot(items, stuck=(), generated_on="2026-09-26"):
    return {
        "schema": 1,
        "generated_on": generated_on,
        "items": [{"id": key, "title": f"Invented {key}", "status": status} for key, status in items],
        "findings": {"stuck": [{"id": key, "score": 0, "reasons": []} for key in stuck]},
    }


class Diff(unittest.TestCase):
    def test_no_previous_run_says_so(self):
        changes = memory.diff(None, snapshot([("a", "open")]))
        self.assertIsNone(changes["previous_generated_on"])
        self.assertEqual(changes["new"], [])

    def test_new_closed_gone_flipped_and_newly_stuck(self):
        before = snapshot([("kept", "open"), ("closing", "review"), ("vanishing", "open"), ("flipping", "open"),
                           ("was-done", "done"), ("stuck-before", "open")], stuck=["stuck-before"], generated_on="2026-09-25")
        after = snapshot([("kept", "open"), ("closing", "done"), ("flipping", "in_progress"), ("fresh", "open"),
                          ("stuck-before", "open")], stuck=["stuck-before", "kept"])
        changes = memory.diff(before, after)
        self.assertEqual(changes["previous_generated_on"], "2026-09-25")
        self.assertEqual(changes["new"], ["fresh"])
        self.assertEqual(changes["closed"], ["closing"])
        self.assertEqual(changes["gone"], ["vanishing"])
        self.assertEqual(changes["newly_stuck"], ["kept"])
        self.assertEqual(changes["status_flips"], [{"id": "flipping", "from": "open", "to": "in_progress"}])

    def test_identical_runs_have_no_changes(self):
        same = snapshot([("a", "open")], stuck=["a"])
        changes = memory.diff(same, same)
        self.assertEqual([changes[key] for key in ("new", "closed", "gone", "newly_stuck", "status_flips")], [[]] * 5)

    def test_gone_titles_come_from_the_previous_run(self):
        changes = memory.diff(snapshot([("vanishing", "open")]), snapshot([]))
        self.assertEqual(changes["titles"]["vanishing"], "Invented vanishing")


class Storage(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp()) / "state"

    def test_missing_state_is_no_previous_run(self):
        self.assertEqual(memory.load(self.state), (None, None))

    def test_round_trip_and_private_permissions(self):
        memory.save(self.state, snapshot([("a", "open")]))
        loaded, warning = memory.load(self.state)
        self.assertIsNone(warning)
        self.assertEqual(loaded["items"][0]["id"], "a")
        mode = stat.S_IMODE(self.state.stat().st_mode)
        self.assertEqual(mode, 0o700)
        self.assertEqual(stat.S_IMODE(memory.snapshot_path(self.state).stat().st_mode), 0o600)

    def test_malformed_previous_is_a_warning_not_a_crash(self):
        self.state.mkdir(parents=True)
        memory.snapshot_path(self.state).write_text("{not json", encoding="utf-8")
        loaded, warning = memory.load(self.state)
        self.assertIsNone(loaded)
        self.assertIn("unreadable", warning)

    def test_wrong_shape_is_a_warning(self):
        self.state.mkdir(parents=True)
        memory.snapshot_path(self.state).write_text(json.dumps(["not", "a", "snapshot"]), encoding="utf-8")
        loaded, warning = memory.load(self.state)
        self.assertIsNone(loaded)
        self.assertTrue(warning)


if __name__ == "__main__":
    unittest.main()
