"""A keyframe refused at POST must not freeze the tasks bound in the same batch.

Device ...0334 E05 S6 (2026-11-15): two keyframes were refused at POST three rounds running.  The
submit failed each time, the stage returned before the harvest, and the thirteen tasks bound in the
same batch were never polled -- nothing could finish until every task passed in one round.  The
bound tasks are now polled (query only) after a failed submit; the stage stays BLOCKED.
"""
import importlib
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(TOOLS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REPORT = {
    "status": "FAIL",
    "results": [
        {"task_key": "E05-S01-08-KEYFRAME-V1", "task_id": "tsk_a", "status": "submitted",
         "recovered_from_transaction": True},
        {"task_key": "E05-S01-09-KEYFRAME-V1", "task_id": "tsk_b", "status": "submitted",
         "recovered_from_transaction": False},
    ],
    "failures": [
        {"task_key": "E05-S01-04-KEYFRAME-V1", "task_id": "tsk_c", "status": "PROVIDER_REJECTED_TASK"},
    ],
    "provider_rejected_tasks": [{"task_key": "E05-S01-04-KEYFRAME-V1", "task_id": "tsk_c"}],
}


class HarvestBoundAfterFailedSubmitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("nalu_pipeline")

    def _call(self, tmp: str, report: dict, *, exit_code: int = 2, stale: bool = False,
              write: bool = True, blocker: str | None = None):
        path = Path(tmp) / "E05_KEYFRAME_SUBMIT.json"
        started = time.time() - 1
        if write:
            path.write_text(json.dumps(report), encoding="utf-8")
            if stale:
                os.utime(path, (started - 3600, started - 3600))
        calls: list[dict] = []

        def run(argv, *, name, paid=False):
            calls.append({"argv": list(argv), "name": name, "paid": paid})
            return {"name": name, "exit_code": 2}

        ctx = SimpleNamespace(p=SimpleNamespace(keyframe_submit=path), run=run)
        res = self.mod.StageResult(self.mod.BLOCKED)
        res.blockers.append("KEYFRAME_SUBMIT_FAILED")
        submit = {"exit_code": exit_code}
        if blocker:
            submit["blocker"] = blocker
        bound = self.mod.harvest_bound_after_failed_submit(
            ctx, res, submit, report, ["harvest", "--submit-report", str(path)], started)
        return bound, calls, res

    def test_bound_tasks_are_polled_and_the_stage_stays_blocked(self) -> None:
        with TemporaryDirectory() as tmp:
            bound, calls, res = self._call(tmp, REPORT)
        self.assertEqual(bound, ["E05-S01-08-KEYFRAME-V1", "E05-S01-09-KEYFRAME-V1"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["argv"][0], "harvest")
        self.assertEqual(res.status, self.mod.BLOCKED)
        self.assertEqual(res.blockers, ["KEYFRAME_SUBMIT_FAILED"])
        self.assertEqual(res.details["bound_harvest_after_failed_submit"]["bound_task_keys"], bound)
        self.assertEqual(len(res.steps), 1)

    def test_a_refused_task_alone_is_not_polled(self) -> None:
        report = {**REPORT, "results": []}
        with TemporaryDirectory() as tmp:
            bound, calls, res = self._call(tmp, report)
        self.assertEqual(bound, [])
        self.assertEqual(calls, [])
        self.assertNotIn("bound_harvest_after_failed_submit", res.details)

    def test_a_refused_row_listed_in_results_does_not_count_as_bound(self) -> None:
        report = {**REPORT, "results": [
            {"task_key": "E05-S01-04-KEYFRAME-V1", "task_id": "tsk_c", "status": "submitted"}]}
        with TemporaryDirectory() as tmp:
            bound, calls, _ = self._call(tmp, report)
        self.assertEqual(bound, [])
        self.assertEqual(calls, [])

    def test_an_older_report_is_not_polled(self) -> None:
        # authority refusal / timeout / crash: the submitter wrote nothing this run
        with TemporaryDirectory() as tmp:
            self.assertEqual(self._call(tmp, REPORT, stale=True)[1], [])
            self.assertEqual(self._call(tmp, REPORT, write=False)[1], [])
            self.assertEqual(self._call(tmp, REPORT, exit_code=124)[1], [])
            self.assertEqual(self._call(tmp, REPORT, exit_code=5,
                                        blocker="PAID_AUTHORITY_NOT_VALID_FOR_STAGE")[1], [])


if __name__ == "__main__":
    unittest.main()
