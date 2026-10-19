"""Non-paid preparation: per-shot keyframe compilation runs concurrently, order fixed.

The S5 keyframe builder compiles every shot's prompt independently.  A serial list
comprehension meant one slow read (reference-image SHA verification is file I/O) held
every later shot.  These tests pin the two properties that make the concurrent form
safe: shots genuinely overlap, and the merged report data stays in input order.
"""

from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_keyframe_manifest as builder  # noqa: E402  (runtime tools dir on sys.path above)


class CompileTasksConcurrencyTest(unittest.TestCase):
    def _run(self, rows, fake_compile, *, workers=None, timeout=4.0):
        dropped: list[dict[str, str]] = []

        def fake(inputs, row, prompt_dir, keyframe_dir, gate_ref, model, resolution, per_row_dropped, task_version="V1"):
            return fake_compile(row, per_row_dropped)

        with mock.patch.object(builder, "compile_task", fake):
            tasks = builder.compile_tasks(
                inputs=SimpleNamespace(), rows=rows, prompt_dir=Path("/nonexistent"),
                keyframe_dir=Path("/nonexistent"), gate_ref="GATE", model="M",
                resolution="2K", dropped=dropped, workers=workers,
            )
        return tasks, dropped

    def test_shots_overlap_instead_of_running_one_at_a_time(self):
        rows = [{"shot_id": f"S{i}"} for i in range(4)]
        barrier = threading.Barrier(4, timeout=4.0)
        entered = threading.Semaphore(0)

        def fake_compile(row, _per_row_dropped):
            entered.release()
            # Every shot must arrive here before any may leave: a serial loop deadlocks
            # and the Barrier raises BrokenBarrierError, failing the test.
            barrier.wait()
            return {"task_key": row["shot_id"]}

        tasks, _ = self._run(rows, fake_compile)

        self.assertEqual(len(tasks), 4)
        for _ in rows:
            self.assertTrue(entered.acquire(timeout=0.01), "a shot never entered compile")

    def test_merged_dropped_segments_keep_input_order(self):
        rows = [{"shot_id": f"S{i}"} for i in range(3)]

        def fake_compile(row, per_row_dropped):
            # Deliberately slow the first shot so completion order differs from input order.
            if row["shot_id"] == "S0":
                threading.Event().wait(0.05)
            per_row_dropped.append({"shot_id": row["shot_id"], "reason": "x"})
            return {"task_key": row["shot_id"]}

        tasks, dropped = self._run(rows, fake_compile, workers=3)

        self.assertEqual([task["task_key"] for task in tasks], ["S0", "S1", "S2"])
        self.assertEqual([row["shot_id"] for row in dropped], ["S0", "S1", "S2"])

    def test_one_failing_shot_fails_the_build(self):
        rows = [{"shot_id": "S0"}, {"shot_id": "S1"}]

        def fake_compile(row, _per_row_dropped):
            if row["shot_id"] == "S1":
                raise ValueError("S1: entry_state is empty")
            return {"task_key": row["shot_id"]}

        with self.assertRaisesRegex(ValueError, "entry_state is empty"):
            self._run(rows, fake_compile, workers=2)

    def test_workers_one_keeps_the_serial_path_deterministic(self):
        rows = [{"shot_id": f"S{i}"} for i in range(3)]

        def fake_compile(row, per_row_dropped):
            per_row_dropped.append({"shot_id": row["shot_id"]})
            return {"task_key": row["shot_id"]}

        tasks, dropped = self._run(rows, fake_compile, workers=1)

        self.assertEqual([task["task_key"] for task in tasks], ["S0", "S1", "S2"])
        self.assertEqual([row["shot_id"] for row in dropped], ["S0", "S1", "S2"])

    def test_empty_input_returns_empty(self):
        tasks, dropped = self._run([], lambda row, _d: {"task_key": row["shot_id"]})
        self.assertEqual((tasks, dropped), ([], []))


if __name__ == "__main__":
    unittest.main()
