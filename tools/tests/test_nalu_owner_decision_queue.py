#!/usr/bin/env python3
"""The owner-decision queue: scoped blockers, and the four classes that may not be narrowed.

run_unattended.sh refused to start while a pending-decision file existed, but nothing wrote
that file — the mechanism was a convention, and it was all-or-nothing.  A decision about one
unit froze the other 57.  The queue records blockers as structured entries with a scope, so
the rest of the episode can continue, and keeps the four always-ask categories at line scope
so a future edit cannot quietly turn one of them into "continue without asking".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
QUEUE = TOOLS / "owner_decision_queue.py"


def run(root: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ, "NALU_RUNTIME_ROOT": str(root), **(env or {})}
    return subprocess.run([sys.executable, str(QUEUE), *args], capture_output=True, text=True, env=merged)


class DecisionQueueTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "runtime" / "reports").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def raise_(self, kind, *extra):
        return run(self.root, "raise", "--episode", "E11", "--class", kind,
                   "--what", "w", "--why", "y", "--if-not-done", "z", *extra)

    def test_a_unit_scope_decision_does_not_stop_the_line(self):
        self.assertEqual(self.raise_("ASSET_AMBIGUITY", "--scope", "unit", "--unit-id", "E11-VU-004").returncode, 0)
        status = run(self.root, "status", "--episode", "E11", "--blocking-line")
        self.assertEqual(status.returncode, 0, status.stdout)
        self.assertEqual(json.loads(status.stdout)["blocking_line"], 0)

    def test_a_line_scope_decision_stops_the_line(self):
        self.assertEqual(self.raise_("ASSET_AMBIGUITY").returncode, 0)
        status = run(self.root, "status", "--episode", "E11", "--blocking-line")
        self.assertEqual(status.returncode, 5, status.stdout)

    def test_each_always_ask_class_is_forced_to_line_scope(self):
        for kind in ("PAID_CATEGORY_NOT_IN_ORDER", "STORY_TEXT_CHANGE", "PUBLICATION"):
            with self.subTest(kind=kind):
                # raising it without a scope yields line scope, and the run must stop
                self.assertEqual(self.raise_(kind).returncode, 0)
                self.assertEqual(run(self.root, "status", "--episode", "E11", "--blocking-line").returncode, 5)

    def test_narrowing_an_always_ask_class_is_refused(self):
        got = self.raise_("STORY_TEXT_CHANGE", "--scope", "unit", "--unit-id", "E11-VU-001")
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("must be line scope", got.stderr + got.stdout)

    def test_voice_consistency_may_be_raised_at_unit_scope(self):
        # line owner 2026-10-22 (supersedes K069): voice out of band is default-accepted after the
        # controlled redo; raising it is optional and no longer stops the whole line
        self.assertEqual(self.raise_("VOICE_CONSISTENCY", "--scope", "unit", "--unit-id", "E11-VU-001").returncode, 0)

    def test_a_non_line_scope_needs_something_to_act_on(self):
        got = self.raise_("ASSET_AMBIGUITY", "--scope", "unit")
        self.assertNotEqual(got.returncode, 0)

    def test_the_pending_file_is_rendered_and_removed_when_clear(self):
        pending = self.root / "runtime" / "reports" / "E11_OWNER_DECISION_PENDING.md"
        self.raise_("ASSET_AMBIGUITY", "--scope", "unit", "--unit-id", "E11-VU-004")
        text = pending.read_text(encoding="utf-8")
        self.assertIn("E11-VU-004", text)
        self.assertIn("只阻塞局部", text)
        # answering the only entry removes the file, so the unattended guard clears by itself
        out = run(self.root, "list", "--episode", "E11", "--status", "OPEN")
        entry_id = json.loads(out.stdout)["entries"][0]["id"]
        answered = run(self.root, "answer", "--episode", "E11", "--id", entry_id,
                       "--order-seq", "28",
                       env={"NALU_SUPERVISOR_ORDERS_PATH": str(REPO / "nonexistent_inbox.json")})
        # with no readable inbox the answer must be refused, and the entry must stay open
        self.assertNotEqual(answered.returncode, 0)
        self.assertTrue(pending.is_file())

    def test_an_answer_needs_a_real_receipted_order(self):
        self.raise_("ASSET_AMBIGUITY")
        out = run(self.root, "list", "--episode", "E11", "--status", "OPEN")
        entry_id = json.loads(out.stdout)["entries"][0]["id"]
        got = run(self.root, "answer", "--episode", "E11", "--id", entry_id, "--order-seq", "999")
        self.assertNotEqual(got.returncode, 0)
        self.assertNotIn("ANSWERED", got.stdout)
        still_open = json.loads(run(self.root, "status", "--episode", "E11").stdout)
        self.assertEqual(still_open["open"], 1)

    def test_unknown_class_is_refused(self):
        self.assertNotEqual(self.raise_("NOT_A_CLASS").returncode, 0)


if __name__ == "__main__":
    unittest.main()
